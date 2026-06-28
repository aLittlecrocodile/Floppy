"""Voice picker support: list selectable voices and pre-generate real TTS
preview clips.

The frontend voice picker needs a real, playable preview per voice (not just a
display label). We synthesize one short sample sentence per voice via the
configured TTS provider (MiniMax) once and cache it under
storage/voice_previews/{voice_style}.mp3, then serve it via /audio/{key}.
Generation is idempotent — existing previews are reused so we don't burn
provider quota on every startup/list call.
"""
from __future__ import annotations

from floppy_backend.config import Settings
from floppy_backend.models import VoiceOption
from floppy_backend.providers.audio import MiniMaxTTSProvider
from floppy_backend.storage import LocalFileStorage
from floppy_backend.voice_profiles import VOICE_PREVIEW_SAMPLE_TEXT, VOICE_PROFILES

_PREVIEW_DIR = "voice_previews"


def _preview_object_key(voice_style: str) -> str:
    return f"{_PREVIEW_DIR}/{voice_style}.mp3"


def ensure_preview(voice_style: str, profile: dict, storage: LocalFileStorage, settings: Settings) -> str | None:
    """Ensure a preview mp3 exists for a voice; return its public URL or None.

    Idempotent: if the file already exists it is reused. Only attempts real
    synthesis when the MiniMax provider is configured; otherwise returns None
    (the voice still lists, just without a preview)."""
    object_key = _preview_object_key(voice_style)
    path = storage.path_for(object_key)
    if path.exists() and path.stat().st_size > 0:
        return storage.public_url(object_key)

    if not settings.minimax_api_key:
        return None
    try:
        provider = MiniMaxTTSProvider(settings)
        provider.generate_text_to_file(
            VOICE_PREVIEW_SAMPLE_TEXT,
            path,
            object_key,
            voice_style=voice_style,
            voice_id=profile["voice_id"],
            title=f"voice preview {voice_style}",
        )
    except Exception:  # noqa: BLE001 — preview is best-effort
        return None
    if path.exists() and path.stat().st_size > 0:
        return storage.public_url(object_key)
    return None


def list_voice_options(storage: LocalFileStorage, settings: Settings) -> list[VoiceOption]:
    options: list[VoiceOption] = []
    for voice_style, profile in VOICE_PROFILES.items():
        preview_url = ensure_preview(voice_style, profile, storage, settings)
        options.append(VoiceOption(
            id=voice_style,
            name=profile.get("name", voice_style),
            description=profile.get("description", ""),
            gender=profile.get("gender", ""),
            style=profile.get("style", ""),
            provider="minimax",
            providerVoiceId=profile["voice_id"],
            previewAudioUrl=preview_url,
            sampleText=VOICE_PREVIEW_SAMPLE_TEXT,
        ))
    return options
