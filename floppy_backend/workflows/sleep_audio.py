from __future__ import annotations

import time
from dataclasses import dataclass

from floppy_backend.config import Settings
from floppy_backend.models import AudioAsset, AudioAssetIn, AudioScript, GenerationDirective, NormalizedAudioRequest, UserProfile
from floppy_backend.providers.audio import AudioGenerationProvider, GeneratedAudio
from floppy_backend.repositories import Repository
from floppy_backend.services import script_guard
from floppy_backend.services.minimax_hubless import build_sleep_music_prompt, ffmpeg_mix, probe_audio
from floppy_backend.services.script import SleepScriptService
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_text, stable_id, text_embedding
from floppy_backend.voice_profiles import resolve_voice_id
from floppy_backend.workflows.contracts import (
    AgentWorkflowContext,
    GenerationPolicy,
    MixPreferences,
    SleepAudioIntent,
    SleepAudioWorkflowRequest,
    WorkflowArtifact,
    WorkflowDiagnostics,
    WorkflowProvider,
    WorkflowStatus,
    WorkflowStatusResponse,
    WorkflowStepState,
    WorkflowStepStatus,
)


# Generations by these users are official prewarm content → curated tier.
# Also keeps prewarm re-runs from flipping curated back to community on upsert.
CURATED_GENERATION_USERS = {"prewarm_user"}

# 中英句读 + 逗号：标题在第一处截断
_TITLE_BREAK_CHARS = "，。,.;；!！?？:：\n"

_TITLE_FALLBACK_BY_INTENT = {
    "story": "睡前故事",
    "meditation": "冥想引导",
    "white_noise": "白噪音",
    "music": "助眠音乐",
    "asmr": "轻声细语",
    "podcast_digest": "睡前播客",
}


def _clean_title(raw: str | None, intent: str) -> str:
    """Card-worthy title: cut at first sentence punctuation, cap at 14 chars,
    strip trailing punctuation; fall back to a type label when nothing usable
    remains (prevents raw prompts like "用平和声音讲几条科技短讯，低信息密度"
    from becoming Home titles)."""
    text = (raw or "").strip()
    for idx, char in enumerate(text):
        if char in _TITLE_BREAK_CHARS:
            text = text[:idx]
            break
    text = text[:14].rstrip("".join(_TITLE_BREAK_CHARS) + " 、的")
    if len(text) < 2:
        return _TITLE_FALLBACK_BY_INTENT.get(intent, "助眠音频")
    return text


@dataclass(frozen=True)
class SleepAudioWorkflowResult:
    asset: AudioAsset
    generated: GeneratedAudio
    script: AudioScript | None
    status: WorkflowStatusResponse
    latency_ms: int


class SleepAudioWorkflowService:
    """Executes the sleep-audio production workflow behind the Agent contract."""

    def __init__(
        self,
        repository: Repository,
        storage: LocalFileStorage,
        provider: AudioGenerationProvider,
        script_service: SleepScriptService,
        settings: Settings | None = None,
    ):
        self.repository = repository
        self.storage = storage
        self.provider = provider
        self.script_service = script_service
        self.settings = settings

    def build_request(
        self,
        *,
        user_id: str,
        cache_key: str,
        normalized: NormalizedAudioRequest,
        profile: UserProfile | None,
        title_hint: str | None = None,
    ) -> SleepAudioWorkflowRequest:
        provider = WorkflowProvider.MINIMAX if self.provider.name == "minimax_t2a" else WorkflowProvider.LOCAL
        mix = self._default_mix_preferences(normalized)
        return SleepAudioWorkflowRequest(
            request_id=stable_id("wf_req", {"user_id": user_id, "cache_key": cache_key}),
            user_id=user_id,
            intent=SleepAudioIntent.from_normalized(normalized, title_hint=title_hint),
            mix_preferences=mix,
            generation_policy=GenerationPolicy(provider=provider),
            agent_context=AgentWorkflowContext(
                profile_segment=profile.segment if profile else None,
                user_visible_summary=self._summary(normalized),
            ),
        )

    def prepare_script(
        self,
        *,
        user_id: str,
        normalized: NormalizedAudioRequest,
        profile: UserProfile | None,
        directive: GenerationDirective | None = None,
    ) -> AudioScript:
        sleep_script = self.script_service.generate(normalized, profile, directive)
        return self.repository.upsert_audio_script(sleep_script.to_input(user_id))

    def run(
        self,
        *,
        user_id: str,
        cache_key: str,
        normalized: NormalizedAudioRequest,
        profile: UserProfile | None,
        script: AudioScript | None,
        directive: GenerationDirective | None = None,
    ) -> SleepAudioWorkflowResult:
        if script is None:
            script = self.prepare_script(user_id=user_id, normalized=normalized, profile=profile, directive=directive)

        if script.safety_status != "approved":
            notes = ", ".join(script.safety_notes)
            raise script_guard.ScriptGuardError(f"script guard rejected script: {script.safety_status}; {notes}")

        request = self.build_request(user_id=user_id, cache_key=cache_key, normalized=normalized, profile=profile, title_hint=script.title)
        started = time.perf_counter()
        generated = self._generate_audio(user_id=user_id, cache_key=cache_key, normalized=normalized, request=request, script=script)
        asset = self._upsert_asset(
            user_id=user_id, cache_key=cache_key, normalized=normalized, profile=profile, generated=generated, directive=directive
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        status = self._status_response(request=request, normalized=normalized, script=script, generated=generated, asset=asset)
        generated = self._attach_workflow_payload(generated, status)
        return SleepAudioWorkflowResult(asset=asset, generated=generated, script=script, status=status, latency_ms=latency_ms)

    def _generate_audio(
        self,
        *,
        user_id: str,
        cache_key: str,
        normalized: NormalizedAudioRequest,
        request: SleepAudioWorkflowRequest,
        script: AudioScript,
    ) -> GeneratedAudio:
        output_ext = "mp3" if self.provider.name == "minimax_t2a" else "wav"
        music_mix_enabled = self._music_mix_enabled(request)
        suffix = "_voice" if music_mix_enabled else ""
        object_key = f"ondemand/{user_id}/{cache_key[:16]}{suffix}.{output_ext}"
        path = self.storage.path_for(object_key)
        generated = self.provider.generate(
            normalized,
            path,
            object_key,
            script_text=script.script_text,
            title=script.title,
        )
        if music_mix_enabled:
            return self._mix_minimax_music_layer(user_id=user_id, cache_key=cache_key, normalized=normalized, request=request, speech=generated)
        return generated

    def _mix_minimax_music_layer(
        self,
        *,
        user_id: str,
        cache_key: str,
        normalized: NormalizedAudioRequest,
        request: SleepAudioWorkflowRequest,
        speech: GeneratedAudio,
    ) -> GeneratedAudio:
        base = cache_key[:16]
        music_key = f"ondemand/{user_id}/{base}_music.mp3"
        mixed_key = f"ondemand/{user_id}/{base}.mp3"
        music_path = self.storage.path_for(music_key)
        mixed_path = self.storage.path_for(mixed_key)
        music_prompt = build_sleep_music_prompt(normalized)
        music = self.provider.generate_instrumental_music(  # type: ignore[attr-defined]
            music_prompt,
            music_path,
            music_key,
            title=f"{speech.title} background",
        )
        mixed_meta = ffmpeg_mix(
            speech.path,
            music.path,
            mixed_path,
            foreground_volume=request.mix_preferences.voice_volume,
            background_volume=request.mix_preferences.background_volume,
            fade_out_sec=request.mix_preferences.fade_out_sec,
        )
        if mixed_meta.duration_sec <= 0:
            mixed_meta = probe_audio(mixed_path)
        payload = {
            "speech": speech.provider_payload,
            "music": music.provider_payload,
            "mix": {
                "music_prompt": music_prompt,
                "voice_object_key": speech.object_key,
                "music_object_key": music.object_key,
                "mixed_object_key": mixed_key,
                "duration_sec": mixed_meta.duration_sec,
                "voice_volume": request.mix_preferences.voice_volume,
                "music_volume": request.mix_preferences.background_volume,
            },
        }
        return GeneratedAudio(
            object_key=mixed_key,
            path=mixed_path,
            duration_sec=max(1, int(mixed_meta.duration_sec)),
            title=speech.title,
            content_hash=sha256_text(mixed_path.read_bytes().hex()),
            provider_model=f"{speech.provider_model}+{music.provider_model}",
            provider_task_id=speech.provider_task_id,
            provider_file_id=speech.provider_file_id,
            provider_status="succeeded",
            provider_payload=payload,
            usage_characters=speech.usage_characters,
            estimated_cost_usd=speech.estimated_cost_usd,
        )

    def _upsert_asset(
        self,
        *,
        user_id: str,
        cache_key: str,
        normalized: NormalizedAudioRequest,
        profile: UserProfile | None,
        generated: GeneratedAudio,
        directive: GenerationDirective | None = None,
    ) -> AudioAsset:
        key_elements = list(directive.key_elements) if directive and directive.key_elements else []
        tags = ["generated", *(key_elements[:4] or normalized.content_topic[:3])]
        asset = self.repository.upsert_asset(
            AudioAssetIn(
                type=normalized.intent,
                title=_clean_title(generated.title, normalized.intent.value),
                object_key=generated.object_key,
                duration_sec=generated.duration_sec,
                language=normalized.language,
                voice_id=normalized.voice_style,
                prompt_hash=cache_key,
                content_hash=generated.content_hash,
                mood_tags=normalized.mood,
                tags=list(dict.fromkeys(tags)),
                user_segment_tags=[profile.segment if profile else "balanced_sleep"],
                quality_score=0.72,
                embedding=text_embedding(
                    " ".join(
                        [
                            normalized.intent.value,
                            normalized.background,
                            normalized.voice_style,
                            *normalized.mood,
                            *normalized.content_topic,
                        ]
                    )
                ),
                created_by="ondemand",
                tier="curated" if user_id in CURATED_GENERATION_USERS else "community",
            )
        )
        asset.playback_url = self.storage.public_url(asset.object_key)
        return asset

    def _status_response(
        self,
        *,
        request: SleepAudioWorkflowRequest,
        normalized: NormalizedAudioRequest,
        script: AudioScript,
        generated: GeneratedAudio,
        asset: AudioAsset,
    ) -> WorkflowStatusResponse:
        music_enabled = self._music_mix_enabled(request)
        steps = [
            WorkflowStepState(name="script", status=WorkflowStepStatus.SUCCEEDED),
            WorkflowStepState(name="speech", status=WorkflowStepStatus.SUCCEEDED),
            WorkflowStepState(name="music", status=WorkflowStepStatus.SUCCEEDED if music_enabled else WorkflowStepStatus.SKIPPED),
            WorkflowStepState(name="mix_audio", status=WorkflowStepStatus.SUCCEEDED if music_enabled else WorkflowStepStatus.SKIPPED),
            WorkflowStepState(name="asset", status=WorkflowStepStatus.SUCCEEDED),
        ]
        provider_payload = generated.provider_payload or {}
        mix_payload = provider_payload.get("mix") if isinstance(provider_payload, dict) else None
        voice_object_key = (mix_payload or {}).get("voice_object_key") or generated.object_key
        music_object_key = (mix_payload or {}).get("music_object_key")
        mixed_object_key = (mix_payload or {}).get("mixed_object_key") or generated.object_key
        return WorkflowStatusResponse(
            workflow_run_id=stable_id("wf", {"request_id": request.request_id, "object_key": generated.object_key}),
            request_id=request.request_id,
            status=WorkflowStatus.SUCCEEDED,
            current_step="done",
            steps=steps,
            artifact=WorkflowArtifact(
                asset_id=asset.id,
                playback_url=asset.playback_url or self.storage.public_url(asset.object_key),
                duration_sec=asset.duration_sec,
                title=asset.title,
                content_type=normalized.intent,
            ),
            diagnostics=WorkflowDiagnostics(
                script_hash=script.script_hash,
                script_chars=len(script.script_text),
                voice_id=self._resolved_voice_id(normalized.voice_style),
                voice_object_key=voice_object_key,
                music_object_key=music_object_key,
                mixed_object_key=mixed_object_key,
                provider_model=generated.provider_model,
                provider_task_id=generated.provider_task_id,
                provider_file_id=generated.provider_file_id,
                estimated_cost_usd=generated.estimated_cost_usd,
            ),
        )

    def _attach_workflow_payload(self, generated: GeneratedAudio, status: WorkflowStatusResponse) -> GeneratedAudio:
        payload = dict(generated.provider_payload or {})
        payload["workflow"] = status.model_dump(mode="json")
        return GeneratedAudio(
            object_key=generated.object_key,
            path=generated.path,
            duration_sec=generated.duration_sec,
            title=generated.title,
            content_hash=generated.content_hash,
            provider_model=generated.provider_model,
            provider_task_id=generated.provider_task_id,
            provider_file_id=generated.provider_file_id,
            provider_status=generated.provider_status,
            provider_payload=payload,
            usage_characters=generated.usage_characters,
            estimated_cost_usd=generated.estimated_cost_usd,
        )

    def _music_mix_enabled(self, request: SleepAudioWorkflowRequest) -> bool:
        return (
            self.provider.name == "minimax_t2a"
            and self.settings is not None
            and self.settings.minimax_enable_music_mix
            and request.constraints.allow_background_music
            and hasattr(self.provider, "generate_instrumental_music")
        )

    def _default_mix_preferences(self, normalized: NormalizedAudioRequest) -> MixPreferences:
        if self.settings is None:
            return MixPreferences(preset=normalized.intent.value)
        return MixPreferences(
            preset=normalized.intent.value,
            voice_volume=self.settings.minimax_voice_mix_volume,
            background_volume=self.settings.minimax_music_mix_volume,
        )

    def _resolved_voice_id(self, voice_style: str) -> str:
        fallback = self.settings.minimax_voice_id if self.settings else voice_style
        return resolve_voice_id(voice_style, fallback)["voice_id"]

    def _summary(self, normalized: NormalizedAudioRequest) -> str:
        minutes = max(1, round(normalized.duration_sec / 60))
        return f"生成约{minutes}分钟的{normalized.intent.value}音频"
