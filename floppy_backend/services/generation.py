from __future__ import annotations

import time
from dataclasses import dataclass

from floppy_backend.config import Settings
from floppy_backend.models import (
    AudioAsset,
    AudioScript,
    AudioType,
    EventIn,
    GenerationBudget,
    GenerationJob,
    GenerationJobCreateResponse,
    GenerationRequest,
    GenerationResponse,
    NormalizedAudioRequest,
    ProfileContext,
)
from floppy_backend.providers.audio import AudioGenerationProvider, GeneratedAudio
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer
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
    directive: object | None = None  # GenerationDirective — carried to the workflow for title/tags


class BudgetExceededError(RuntimeError):
    pass


class GenerationService:
    def __init__(
        self,
        repository: Repository,
        storage: LocalFileStorage,
        provider: AudioGenerationProvider,
        normalizer: RequestNormalizer,
        script_service: SleepScriptService,
        settings: Settings | None = None,
        directive_planner=None,
    ):
        self.repository = repository
        self.storage = storage
        self.provider = provider
        self.normalizer = normalizer
        self.script_service = script_service
        self._settings = settings
        # 异步路径下 worker 自己补指令规划（enqueue 阶段不再同步跑 LLM）
        self._directive_planner = directive_planner
        # In-memory handoff of PreparedGeneration from enqueue_or_match to the
        # inline run_job call in the same process — avoids regenerating the
        # script LLM output (5-20s + double LLM cost) at run time.
        self._prepared_by_job: dict[str, PreparedGeneration] = {}
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
        # 轻量入队：只做归一化 + 缓存匹配（毫秒级）。脚本 LLM（10-20s）留给
        # 后台 run_job —— 前台对话必须秒回（前后台双流程）。
        prepared = self.prepare(user_id, request, prepare_script=False)
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
        if claimed and prepared.script is not None:
            # Hand the already-generated script to run_job (same process) so the
            # script LLM doesn't run twice per generation.
            self._prepared_by_job[job.id] = prepared
        return GenerationJobCreateResponse(
            job_id=job.id,
            status=job.status,
            cache_hit=False,
            match_type="queued" if claimed else "in_flight",
            asset=job.asset,
            normalized_request=prepared.normalized,
        )

    def run_job(
        self,
        job_id: str,
        user_id: str,
        request: GenerationRequest,
        prepared: PreparedGeneration | None = None,
    ) -> GenerationJob | None:
        job = self.repository.get_generation_job(job_id)
        if job is None:
            return None
        if job.status == "succeeded":
            return job
        # Atomic claim: only one worker may run the pipeline for a job. A job
        # already 'generating' (client timeout+retry, double-tap) is NOT re-run
        # — we wait for the in-flight worker instead of double-spending TTS and
        # corrupting the shared output file.
        if not self.repository.claim_job_for_run(job_id):
            for _ in range(60):
                time.sleep(1)
                job = self.repository.get_generation_job(job_id)
                if job is None or job.status != "generating":
                    break
            return job
        # Recover the agent's directive from the persisted job when the caller
        # didn't carry it (async path reconstructs a bare GenerationRequest).
        # Without this the worker would regenerate from a template even though
        # the agent already wrote a content outline at enqueue time.
        if request.directive is None and job.directive is not None:
            request = request.model_copy(update={"directive": job.directive})
        # 异步路径：指令规划挪到了 worker（enqueue 不再同步跑 LLM）。
        # 规划失败不阻塞 —— 脚本服务会用归一化结果兜底。
        if request.directive is None and self._directive_planner is not None:
            try:
                request = request.model_copy(update={
                    "directive": self._directive_planner.plan(request.request_text, self._planning_context(user_id))
                })
            except Exception:  # noqa: BLE001 — directive is best-effort
                pass
        if prepared is None:
            prepared = self._prepared_by_job.pop(job_id, None)
        if prepared is None:
            try:
                prepared = self.prepare(user_id, request, allow_cache=False)
            except Exception as exc:  # noqa: BLE001 — never leave the job stuck 'generating'
                self._mark_failed(job_id, exc, None)
                return self.repository.get_generation_job(job_id)
        try:
            asset, latency_ms, generated = self.execute_generation(user_id, prepared)
        except Exception as exc:  # pragma: no cover - defensive boundary for provider failures.
            self._mark_failed(job_id, exc, prepared.script)
            return self.repository.get_generation_job(job_id)
        self._mark_succeeded(job_id, asset, latency_ms, prepared.script, generated)
        return self.repository.get_generation_job(job_id)

    def _planning_context(self, user_id: str) -> ProfileContext | None:
        """给指令规划器的画像上下文（对齐 hermes_agent._profile_context 的形状）。"""
        try:
            profile = self.repository.get_profile(user_id)
            if profile is None:
                return None
            used_chars, used_count = self.repository.generation_usage_since(user_id)
            char_budget = self._settings.daily_char_budget if self._settings else 0
            count_budget = self._settings.daily_generate_count if self._settings else 0
            return ProfileContext(
                **profile.model_dump(),
                generation_budget=GenerationBudget(
                    daily_remaining_chars=max(0, char_budget - used_chars),
                    daily_generate_count_remaining=max(0, count_budget - used_count),
                ),
            )
        except Exception:  # noqa: BLE001 — 上下文缺失时规划器照样能工作
            return None

    def cache_key_for(self, normalized: NormalizedAudioRequest, directive=None, request_text: str | None = None) -> str:
        return build_sleep_audio_cache_key(
            normalized, provider_name=self.provider.name, settings=self._settings, directive=directive,
            request_text=request_text,
        )

    def prepare(
        self, user_id: str, request: GenerationRequest, allow_cache: bool = True, prepare_script: bool = True
    ) -> PreparedGeneration:
        profile = self.repository.get_profile(user_id)
        normalized = self.normalizer.normalize(request, profile)
        directive = request.directive
        # The agent's directive carries the effective media type. Apply it
        # before cache lookup so a music request cannot reuse a speech asset.
        if directive is not None and directive.intent is not None:
            normalized = normalized.model_copy(update={"intent": directive.intent})
        cache_key = self.cache_key_for(normalized, directive, request_text=request.request_text)

        if allow_cache and not request.force_generate:
            # Exact prompt_hash cache only — fuzzy "close enough" matching is
            # the agent's call (Hermes decision layer), never this service's.
            asset = self.repository.get_asset_by_prompt_hash(cache_key)
            if asset is not None:
                asset.playback_url = self.storage.public_url(asset.object_key)
                self.repository.record_event(
                    user_id,
                    EventIn(
                        event_type="recommendation_served",
                        asset_id=asset.id,
                        payload={"match_type": "exact", "reasons": ["精确缓存命中"]},
                    ),
                )
                return PreparedGeneration(normalized=normalized, cache_key=cache_key, cached_asset=asset, match_type="exact")

        if not prepare_script or normalized.intent == AudioType.MUSIC:
            return PreparedGeneration(
                normalized=normalized, cache_key=cache_key, cached_asset=None, match_type="generated", script=None, directive=directive
            )

        script = self.workflow_service.prepare_script(
            user_id=user_id, normalized=normalized, profile=profile, directive=directive
        )
        return PreparedGeneration(
            normalized=normalized, cache_key=cache_key, cached_asset=None, match_type="generated", script=script, directive=directive
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
