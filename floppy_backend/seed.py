from __future__ import annotations

from floppy_backend.catalog import AUDIO_CATALOG
from floppy_backend.models import AudioAssetIn, AudioType
from floppy_backend.providers.audio import LocalToneAudioProvider
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json, text_embedding
from floppy_backend.models import GenerationRequest


def seed_assets(repository: Repository, storage: LocalFileStorage) -> int:
    provider = LocalToneAudioProvider()
    normalizer = RequestNormalizer()
    created = 0
    for item in AUDIO_CATALOG:
        normalized = normalizer.normalize(GenerationRequest(request_text=item["request_text"]), profile=None)
        cache_key = sha256_json({"normalized": normalized.model_dump(mode="json"), "title": item["title"]})
        object_key = f"pregen/{item['audio_type']}/{cache_key[:16]}.wav"
        generated = provider.generate(normalized, storage.path_for(object_key), object_key, title=item["title"])
        repository.upsert_asset(
            AudioAssetIn(
                type=AudioType(item["audio_type"]),
                title=item["title"],
                object_key=object_key,
                duration_sec=item["duration_sec"],
                language="zh-CN",
                voice_id=normalized.voice_style,
                prompt_hash=cache_key,
                content_hash=generated.content_hash,
                mood_tags=item["mood_tags"],
                tags=item["tags"],
                user_segment_tags=item["user_segment_tags"],
                safety_status="approved",
                quality_score=item["quality_score"],
                embedding=text_embedding(
                    " ".join([
                        item["request_text"],
                        item["audio_type"],
                        item["title"],
                        normalized.voice_style,
                        *item["mood_tags"],
                        *item["user_segment_tags"],
                        *item["tags"],
                    ])
                ),
                created_by="seed_placeholder",
            )
        )
        created += 1
    return created
