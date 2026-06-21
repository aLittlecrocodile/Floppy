from __future__ import annotations

import time
from dataclasses import dataclass

from floppy_backend.models import AudioAsset, AudioAssetIn, AudioScript, GenerationJobCreateResponse, GenerationRequest, GenerationResponse, NormalizedAudioRequest
from floppy_backend.providers.audio import AudioGenerationProvider, GeneratedAudio
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.recommendation import RecommendationService
from floppy_backend.services.script import SleepScriptService
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json, text_embedding


@dataclass(frozen=True)
class PreparedGeneration:
    normalized: NormalizedAudioRequest
    cache_key: str
    cached_asset: AudioAsset | None
    match_type: str
    script: AudioScript | None = None


class GenerationService:
    def __init__(
        self,
        repository: Repository,
        storage: LocalFileStorage,
        provider: AudioGenerationProvider,
        normalizer: RequestNormalizer,
        recommendation_service: RecommendationService,
        script_service: SleepScriptService,
    ):
        self.repository = repository
        self.storage = storage
        self.provider = provider
        self.normalizer = normalizer
        self.recommendation_service = recommendation_service
        self.script_service = script_service

    def generate_or_match(self, user_id: str, request: GenerationRequest) -> GenerationResponse:
        prepared = self.prepare(user_id, request)
        if prepared.cached_asset:
            job_id = self.repository.create_generation_job(
                user_id=user_id,
                request_text=request.request_text,
                normalized_intent=prepared.normalized.intent.value,
                cache_key=prepared.cache_key,
                status="succeeded",
                provider=self.provider.name,
                asset_id=prepared.cached_asset.id,
                latency_ms=0,
            )
            return GenerationResponse(
                job_id=job_id,
                status="succeeded",
                cache_hit=True,
                match_type=prepared.match_type,
                asset=prepared.cached_asset,
                normalized_request=prepared.normalized,
            )

        job_id = self.repository.create_generation_job(
            user_id=user_id,
            request_text=request.request_text,
            normalized_intent=prepared.normalized.intent.value,
            cache_key=prepared.cache_key,
            status="generating",
            provider=self.provider.name,
        )
        try:
            asset, latency_ms, generated = self.execute_generation(user_id, prepared)
        except Exception as exc:  # pragma: no cover - provider boundary.
            self._mark_failed(job_id, exc, prepared.script)
            return GenerationResponse(
                job_id=job_id,
                status="failed",
                cache_hit=False,
                match_type="failed",
                asset=None,
                normalized_request=prepared.normalized,
            )
        self._mark_succeeded(job_id, asset, latency_ms, prepared.script, generated)
        return GenerationResponse(
            job_id=job_id,
            status="succeeded",
            cache_hit=False,
            match_type="generated",
            asset=asset,
            normalized_request=prepared.normalized,
        )

    def enqueue_or_match(self, user_id: str, request: GenerationRequest) -> GenerationJobCreateResponse:
        prepared = self.prepare(user_id, request)
        if prepared.cached_asset:
            job_id = self.repository.create_generation_job(
                user_id=user_id,
                request_text=request.request_text,
                normalized_intent=prepared.normalized.intent.value,
                cache_key=prepared.cache_key,
                status="succeeded",
                provider=self.provider.name,
                asset_id=prepared.cached_asset.id,
                latency_ms=0,
            )
            return GenerationJobCreateResponse(
                job_id=job_id,
                status="succeeded",
                cache_hit=True,
                match_type=prepared.match_type,
                asset=prepared.cached_asset,
                normalized_request=prepared.normalized,
            )

        job, claimed = self.repository.claim_generation_job(
            user_id=user_id,
            request_text=request.request_text,
            normalized_intent=prepared.normalized.intent.value,
            cache_key=prepared.cache_key,
            status="queued",
            provider=self.provider.name,
        )
        return GenerationJobCreateResponse(
            job_id=job.id,
            status=job.status,
            cache_hit=False,
            match_type="queued" if claimed else "in_flight",
            asset=job.asset,
            normalized_request=prepared.normalized,
        )

    def run_job(self, job_id: str, user_id: str, request: GenerationRequest) -> None:
        job = self.repository.get_generation_job(job_id)
        if job is None:
            return
        if job.status == "succeeded":
            return
        self.repository.update_generation_job(job_id, status="generating")
        prepared = self.prepare(user_id, request, allow_cache=False)
        try:
            asset, latency_ms, generated = self.execute_generation(user_id, prepared)
        except Exception as exc:  # pragma: no cover - defensive boundary for provider failures.
            self._mark_failed(job_id, exc, prepared.script)
            return
        self._mark_succeeded(job_id, asset, latency_ms, prepared.script, generated)

    def prepare(self, user_id: str, request: GenerationRequest, allow_cache: bool = True) -> PreparedGeneration:
        profile = self.repository.get_profile(user_id)
        normalized = self.normalizer.normalize(request, profile)
        cache_key = sha256_json(normalized.model_dump(mode="json"))

        if allow_cache and not request.force_generate:
            exact = self.repository.get_asset_by_prompt_hash(cache_key)
            if exact:
                exact.playback_url = self.storage.public_url(exact.object_key)
                return PreparedGeneration(normalized=normalized, cache_key=cache_key, cached_asset=exact, match_type="exact")

            nearest = self.recommendation_service.nearest(request.request_text, limit=1)
            if nearest and nearest[0].score >= 0.58:
                asset = nearest[0].asset
                asset.playback_url = self.storage.public_url(asset.object_key)
                return PreparedGeneration(normalized=normalized, cache_key=cache_key, cached_asset=asset, match_type="nearest")

        sleep_script = self.script_service.generate(normalized, profile)
        script = self.repository.upsert_audio_script(sleep_script.to_input(user_id))
        return PreparedGeneration(normalized=normalized, cache_key=cache_key, cached_asset=None, match_type="generated", script=script)

    def execute_generation(self, user_id: str, prepared: PreparedGeneration) -> tuple[AudioAsset, int, GeneratedAudio]:
        profile = self.repository.get_profile(user_id)
        started = time.perf_counter()
        output_ext = "mp3" if self.provider.name == "minimax_t2a" else "wav"
        object_key = f"ondemand/{user_id}/{prepared.cache_key[:16]}.{output_ext}"
        path = self.storage.path_for(object_key)
        generated = self.provider.generate(
            prepared.normalized,
            path,
            object_key,
            script_text=prepared.script.script_text if prepared.script else None,
            title=prepared.script.title if prepared.script else None,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        asset = self.repository.upsert_asset(
            AudioAssetIn(
                type=prepared.normalized.intent,
                title=generated.title,
                object_key=generated.object_key,
                duration_sec=generated.duration_sec,
                language=prepared.normalized.language,
                voice_id=prepared.normalized.voice_style,
                prompt_hash=prepared.cache_key,
                content_hash=generated.content_hash,
                mood_tags=prepared.normalized.mood,
                user_segment_tags=[profile.segment if profile else "balanced_sleep"],
                quality_score=0.72,
                embedding=text_embedding(
                    " ".join(
                        [
                            prepared.normalized.intent.value,
                            prepared.normalized.background,
                            prepared.normalized.voice_style,
                            *prepared.normalized.mood,
                            *prepared.normalized.content_topic,
                        ]
                    )
                ),
                created_by="ondemand",
            )
        )
        asset.playback_url = self.storage.public_url(asset.object_key)
        return asset, latency_ms, generated

    def _mark_succeeded(self, job_id: str, asset: AudioAsset, latency_ms: int, script: AudioScript | None, generated: GeneratedAudio) -> None:
        self.repository.update_generation_job(
            job_id,
            status="succeeded",
            asset_id=asset.id,
            script_id=script.id if script else None,
            script_hash=script.script_hash if script else None,
            script_chars=len(script.script_text) if script else None,
            provider_model=generated.provider_model,
            provider_task_id=generated.provider_task_id,
            provider_file_id=generated.provider_file_id,
            provider_status=generated.provider_status,
            provider_payload=generated.provider_payload,
            usage_characters=generated.usage_characters,
            estimated_cost_usd=generated.estimated_cost_usd,
            latency_ms=latency_ms,
        )

    def _mark_failed(self, job_id: str, exc: Exception, script: AudioScript | None) -> None:
        self.repository.update_generation_job(
            job_id,
            status="failed",
            script_id=script.id if script else None,
            script_hash=script.script_hash if script else None,
            script_chars=len(script.script_text) if script else None,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
