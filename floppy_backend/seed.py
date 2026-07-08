from __future__ import annotations

from floppy_backend.catalog import AUDIO_CATALOG
from floppy_backend.models import AudioAssetIn, AudioType
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json, sha256_text, text_embedding
from floppy_backend.models import GenerationRequest


def _embedding_for(item: dict, voice_style: str) -> list[float]:
    return text_embedding(
        " ".join([
            item["request_text"],
            item["audio_type"],
            item["title"],
            voice_style,
            *item["mood_tags"],
            *item["user_segment_tags"],
            *item["tags"],
        ])
    )


def seed_assets(repository: Repository, storage: LocalFileStorage) -> int:
    normalizer = RequestNormalizer()
    created = 0
    for item in AUDIO_CATALOG:
        # Only real audio files (white_noise/music) are seeded as assets. The
        # TTS-readable entries (meditation/story/podcast) are NOT pre-seeded:
        # they would otherwise register as LocalTone *placeholders* (a beep
        # tone, not real voice) that the agent then recommends and remix layers
        # on top of — exactly the "[Remix] 海边书店" placeholder the user hit.
        # Those entries stay in the catalog purely as generation templates;
        # the agent produces real-voice audio for them on demand via MiniMax.
        if not item.get("is_real"):
            continue

        normalized = normalizer.normalize(GenerationRequest(request_text=item["request_text"]), profile=None)
        voice_style = item.get("voice_style") or normalized.voice_style

        # Real audio file already imported under storage (real/...). Register it
        # directly so agent_graph can match it and remix can use it as a layer.
        object_key = item["object_key"]
        path = storage.path_for(object_key)
        if not path.exists():
            # File not imported yet; skip so seeding stays idempotent.
            continue
        content_hash = sha256_text(f"{object_key}:{path.stat().st_size}")
        prompt_hash = sha256_json({"title": item["title"], "object_key": object_key})
        created_by = "real_asset"
        duration_sec = item["duration_sec"]

        repository.upsert_asset(
            AudioAssetIn(
                type=AudioType(item["audio_type"]),
                title=item["title"],
                object_key=object_key,
                duration_sec=duration_sec,
                language="zh-CN",
                voice_id=voice_style,
                prompt_hash=prompt_hash,
                content_hash=content_hash,
                mood_tags=item["mood_tags"],
                tags=item["tags"],
                user_segment_tags=item["user_segment_tags"],
                safety_status="approved",
                quality_score=item["quality_score"],
                embedding=_embedding_for(item, voice_style),
                created_by=created_by,
                tier="curated",
            )
        )
        created += 1
    return created

