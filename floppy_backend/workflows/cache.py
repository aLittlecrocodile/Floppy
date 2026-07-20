from __future__ import annotations

from floppy_backend.config import Settings
from floppy_backend.models import AudioType, NormalizedAudioRequest
from floppy_backend.utils import sha256_json


SCRIPT_POLICY_VERSION = "sleep_script.v1"
MUSIC_PROMPT_POLICY_VERSION = "sleep_music_prompt.v1"
MUSIC_GENERATION_POLICY_VERSION = "music_generation.v2"
MIX_POLICY_VERSION = "sleep_mix.v1"


def build_sleep_audio_cache_key(
    normalized: NormalizedAudioRequest,
    *,
    provider_name: str,
    settings: Settings | None = None,
    directive=None,  # noqa: ANN001 — accepted for call-site compat; intentionally NOT hashed
    request_text: str | None = None,
) -> str:
    """Return a generation cache key that changes when production policy changes.

    When `request_text` is provided it is folded into the key: the normalizer
    is lossy (unrelated requests can normalize identically — e.g. any 12-min
    story with no keyword topic), and cross-wording reuse is the Hermes
    agent's job now, not the cache's. The cache only answers "have we generated
    THIS exact request before". The `directive` param is accepted only so
    callers don't need to branch; it is deliberately ignored (LLM wording
    drifts run to run).
    """
    is_minimax = provider_name == "minimax_t2a"
    music_mix_enabled = bool(is_minimax and settings and settings.minimax_enable_music_mix)
    base_key = sha256_json(
        {
            "normalized": normalized.model_dump(mode="json"),
            "provider": provider_name,
            "script_policy_version": SCRIPT_POLICY_VERSION,
            "voice_profile": normalized.voice_style,
            "tts_model": settings.minimax_model if is_minimax and settings else provider_name,
            "music_prompt_policy_version": MUSIC_PROMPT_POLICY_VERSION,
            "music_generation_policy_version": (
                MUSIC_GENERATION_POLICY_VERSION if normalized.intent == AudioType.MUSIC else None
            ),
            "music_model": settings.minimax_music_model if music_mix_enabled and settings else None,
            "mix_policy_version": MIX_POLICY_VERSION,
            "mix_preset": normalized.intent.value,
            "music_mix_enabled": music_mix_enabled,
            "voice_mix_volume": settings.minimax_voice_mix_volume if music_mix_enabled and settings else None,
            "music_mix_volume": settings.minimax_music_mix_volume if music_mix_enabled and settings else None,
            "target_duration_sec": normalized.duration_sec,
        }
    )
    if not request_text:
        return base_key
    # Two-level hash keeps existing keys migratable: new = f(old, request_text).
    return sha256_json({"base_key": base_key, "request_text": request_text})
