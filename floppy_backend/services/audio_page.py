"""Mappers from internal models to the Android Audio page camelCase DTOs.

The Android client (Explore -> Audio: Library / Uploads / History) consumes
camelCase `AudioItem` / `UploadItem` / `AudioLibrary` directly. Internal
storage keeps snake_case `AudioAsset`; this module bridges the two so the
internal model and the frontend contract can evolve independently.
"""
from __future__ import annotations

import sqlite3

from floppy_backend.models import (
    Artwork,
    AudioAsset,
    AudioItem,
    AudioType,
    UploadItem,
)
from floppy_backend.storage import LocalFileStorage

# AudioType -> human-friendly Library grouping label (AudioItem.category).
_CATEGORY_LABELS: dict[str, str] = {
    AudioType.STORY.value: "Sleep stories",
    AudioType.MEDITATION.value: "Meditation",
    AudioType.WHITE_NOISE.value: "White noise",
    AudioType.MUSIC.value: "Sleep music",
    AudioType.ASMR.value: "ASMR",
    AudioType.PODCAST_DIGEST.value: "Podcast",
}

# Stable accent color per type so the client can render a cover background even
# before a real cover image exists. ARGB-ish Long values, matching the
# frontend's `seedColor: Long` field.
_SEED_COLORS: dict[str, int] = {
    AudioType.STORY.value: 0xFF5C6BC0,
    AudioType.MEDITATION.value: 0xFF26A69A,
    AudioType.WHITE_NOISE.value: 0xFF7E57C2,
    AudioType.MUSIC.value: 0xFFEF5350,
    AudioType.ASMR.value: 0xFF66BB6A,
    AudioType.PODCAST_DIGEST.value: 0xFFFFA726,
}

_DEFAULT_SEED_COLOR = 0xFF455A64


def category_for(asset: AudioAsset) -> str:
    return _CATEGORY_LABELS.get(asset.type.value, asset.type.value)


def _seed_color_for(asset: AudioAsset) -> int:
    return _SEED_COLORS.get(asset.type.value, _DEFAULT_SEED_COLOR)


def _subtitle_for(asset: AudioAsset) -> str:
    # Prefer the first mood tag, else the first generic tag, else duration hint.
    if asset.mood_tags:
        return asset.mood_tags[0]
    if asset.tags:
        return asset.tags[0]
    return f"{asset.duration_sec // 60} min"


def asset_to_audio_item(
    asset: AudioAsset,
    storage: LocalFileStorage,
    *,
    source: str = "Library",
    playback_progress: float = 0.0,
) -> AudioItem:
    stream_url = storage.public_url(asset.object_key)
    is_generated = source == "Generated" or not _is_catalog(asset)
    resolved_source = source
    return AudioItem(
        id=asset.id,
        title=asset.title,
        subtitle=_subtitle_for(asset),
        durationSeconds=asset.duration_sec,
        streamUrl=stream_url,
        coverUrl=None,
        artwork=Artwork(
            imageUrl=None,
            seedColor=_seed_color_for(asset),
            prompt=asset.title,
            status="Ready",
        ),
        source=resolved_source,
        category=category_for(asset),
        playbackProgress=playback_progress,
        isGenerated=is_generated and resolved_source != "Library",
    )


def _is_catalog(asset: AudioAsset) -> bool:
    from floppy_backend.services.assets import is_placeholder_created_by

    return is_placeholder_created_by(asset.created_by) or asset.created_by in {"ondemand", "seed"}


def _size_label(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0B"
    units = ["B", "K", "M", "G"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}G"


_PLAYABLE_UPLOAD_TYPES = {"mp3", "wav", "m4a"}

_UPLOAD_SEED_COLOR = 0xFF455A64


def _upload_to_audio_item(row: sqlite3.Row, storage: LocalFileStorage) -> AudioItem | None:
    """Build a playable AudioItem from an uploaded audio file (mp3/wav/m4a).

    The uploaded file itself is the audio — there is no generation step — so we
    point streamUrl at the stored object via the existing /audio/{object_key}
    route (which supports Range). pdf/txt return None (待处理)."""
    file_type = (row["file_type"] or "").lower()
    object_key = row["object_key"]
    if file_type not in _PLAYABLE_UPLOAD_TYPES or not object_key:
        return None
    return AudioItem(
        id=row["id"],
        title=row["file_name"],
        subtitle="My upload",
        durationSeconds=0,  # unknown without decoding; client can read from stream
        streamUrl=storage.public_url(object_key),
        coverUrl=None,
        artwork=Artwork(
            imageUrl=None,
            seedColor=_UPLOAD_SEED_COLOR,
            prompt=row["file_name"],
            status="Ready",
        ),
        source="Upload",
        category="My upload",
        playbackProgress=0.0,
        isGenerated=False,
    )


def upload_row_to_item(
    row: sqlite3.Row,
    storage: LocalFileStorage,
    *,
    generated_asset: AudioAsset | None = None,
) -> UploadItem:
    if generated_asset is not None:
        # A real generation pipeline produced an asset (future pdf/txt flow).
        generated_audio = asset_to_audio_item(generated_asset, storage, source="Upload")
    else:
        # Method A: for already-playable audio uploads, expose the file itself
        # as generatedAudio so the current frontend can play it without changes.
        generated_audio = _upload_to_audio_item(row, storage)
    return UploadItem(
        id=row["id"],
        fileName=row["file_name"],
        fileType=row["file_type"],
        sizeLabel=_size_label(row["size_bytes"] or 0),
        progress=row["progress"] or 0.0,
        status=row["status"],
        message=row["message"],
        generatedAudio=generated_audio,
    )
