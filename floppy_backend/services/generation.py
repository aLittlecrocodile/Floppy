from __future__ import annotations

from dataclasses import dataclass

from floppy_backend.config import Settings
from floppy_backend.models import AudioAsset, AudioScript, EventIn, GenerationDirective, GenerationJobCreateResponse, GenerationRequest, GenerationResponse, NormalizedAudioRequest
from floppy_backend.providers.audio import AudioGenerationProvider, GeneratedAudio
from floppy_backend.repositories import Repository
from floppy_backend.services.asset_catalog import AssetCatalogService
from floppy_backend.services.request_defaults import RequestDefaults
from floppy_backend.services.script import SleepScriptService
from floppy_backend.storage import LocalFileStorage
from floppy_backend.workflows.cache import build_sleep_audio_cache_key
from floppy_backend.workflows.sleep_audio import SleepAudioWorkflowService


@dataclass(frozen=True)
class PreparedGeneration:
    normalized: NormalizedAudioRequest
    cache_key: str
    cached_asset: AudioAsset | None
    match_type: str
    script: AudioScript | None = None
    directive: GenerationDirective | None = None


class BudgetExceededError(RuntimeError):
    pass


class GenerationService:
    def __init__(
        self,
        repository: Repository,
        storage: LocalFileStorage,
        provider: AudioGenerationProvider,
        request_defaults: RequestDefaults,
        asset_catalog_service: AssetCatalogService,
        script_service: SleepScriptService,
        settings: Settings | None = None,
    ):
        self.repository = repository
        self.storage = storage
        self.provider = provider
        self.request_defaults = request_defaults
        self.asset_catalog_service = asset_catalog_service
        self.script_service = script_service
        self._settings = settings
        self.workflow_service = SleepAudioWorkflowService(
            repository=repository,
            storage=storage,
            provider=provider,
            script_service=script_service,
            settings=settings,
        )

    def check_generation_budget(self, user_id: str) -> None:
        if self._settings is None or not self._settings.enforce_generation_budget:
            return
        used_chars, used_count = self.repository.generation_usage_since(user_id, hours=24)
        if used_chars >= self._settings.daily_char_budget:
            raise BudgetExceededError(f"daily character budget exceeded: {used_chars}/{self._settings.daily_char_budget}")
        if used_count >= self._settings.daily_generate_count:
            raise BudgetExceededError(f"daily generation count exceeded: {used_count}/{self._settings.daily_generate_count}")

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

        self.check_generation_budget(user_id)
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

        self.check_generation_budget(user_id)
        job, claimed = self.repository.claim_generation_job(
            user_id=user_id,
            request_text=request.request_text,
            normalized_intent=prepared.normalized.intent.value,
            cache_key=prepared.cache_key,
            status="queued",
            provider=self.provider.name,
            directive_json=request.directive.model_dump_json() if request.directive else None,
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
        # Recover the agent's directive from the persisted job when the caller
        # didn't carry it (async path reconstructs a bare GenerationRequest).
        # Without this the worker would regenerate from a template even though
        # the agent already wrote a content outline at enqueue time.
        if request.directive is None and job.directive is not None:
            request = request.model_copy(update={"directive": job.directive})
        self.repository.update_generation_job(job_id, status="generating")
        script = None
        try:
            prepared = self.prepare(user_id, request, allow_cache=False)
            script = prepared.script
            asset, latency_ms, generated = self.execute_generation(user_id, prepared)
        except Exception as exc:  # pragma: no cover - defensive boundary for provider failures.
            self._mark_failed(job_id, exc, script)
            return
        self._mark_succeeded(job_id, asset, latency_ms, prepared.script, generated)

    def cache_key_for(self, normalized: NormalizedAudioRequest, directive=None) -> str:
        return build_sleep_audio_cache_key(
            normalized, provider_name=self.provider.name, settings=self._settings, directive=directive
        )

    def prepare(self, user_id: str, request: GenerationRequest, allow_cache: bool = True) -> PreparedGeneration:
        profile = self.repository.get_profile(user_id)
        directive = request.directive
        normalized = self.request_defaults.normalize(request, profile, directive)
        cache_key = self.cache_key_for(normalized, directive)

        if allow_cache and not request.force_generate:
            asset = self.repository.get_asset_by_prompt_hash(cache_key)
            if asset is not None and asset.type == normalized.intent:
                asset.playback_url = self.storage.public_url(asset.object_key)
                self.repository.record_event(
                    user_id,
                    EventIn(
                        event_type="asset_served",
                        asset_id=asset.id,
                        payload={"match_type": "exact", "score": 1.0, "reasons": ["exact cache asset"]},
                    ),
                )
                return PreparedGeneration(normalized=normalized, cache_key=cache_key, cached_asset=asset, match_type="exact", directive=directive)

        script = None
        if self.workflow_service.script_required(normalized):
            script = self.workflow_service.prepare_script(
                user_id=user_id, normalized=normalized, profile=profile, directive=directive
            )
        return PreparedGeneration(
            normalized=normalized,
            cache_key=cache_key,
            cached_asset=None,
            match_type="generated",
            script=script,
            directive=directive,
        )

    def execute_generation(self, user_id: str, prepared: PreparedGeneration) -> tuple[AudioAsset, int, GeneratedAudio]:
        profile = self.repository.get_profile(user_id)
        result = self.workflow_service.run(
            user_id=user_id,
            cache_key=prepared.cache_key,
            normalized=prepared.normalized,
            profile=profile,
            script=prepared.script,
            directive=prepared.directive,
        )
        return result.asset, result.latency_ms, result.generated

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
