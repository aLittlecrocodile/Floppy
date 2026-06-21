from __future__ import annotations

from floppy_backend.models import AudioAssetIn, AudioType, GenerationRequest
from floppy_backend.providers.audio import LocalToneAudioProvider
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json, text_embedding


SEED_REQUESTS = [
    ("雨声白噪音，适合焦虑时放松，20分钟", ["anxiety_relief", "calm"], ["anxiety_relief", "environmental_sleep"]),
    ("海浪和轻音乐，帮助快速入睡，15分钟", ["calm", "gentle"], ["quick_sleep", "environmental_sleep"]),
    ("温柔女声睡前故事，森林和星星，20分钟", ["safe", "gentle"], ["companionship", "anxiety_relief"]),
    ("低语 ASMR，轻柔陪伴，10分钟", ["safe", "gentle"], ["companionship"]),
    ("呼吸冥想引导，压力释放，15分钟", ["anxiety_relief", "calm"], ["anxiety_relief"]),
    ("壁炉背景声，安静长时播放，30分钟", ["calm"], ["environmental_sleep"]),
    ("城市夜晚轻音乐，睡前放松，20分钟", ["calm", "gentle"], ["balanced_sleep"]),
    ("播客内容睡前摘要，低信息密度，10分钟", ["calm"], ["content_transform"]),
]


def seed_assets(repository: Repository, storage: LocalFileStorage) -> int:
    provider = LocalToneAudioProvider()
    normalizer = RequestNormalizer()
    created = 0
    for request_text, moods, segments in SEED_REQUESTS:
        normalized = normalizer.normalize(GenerationRequest(request_text=request_text), profile=None)
        normalized.mood = sorted(set([*normalized.mood, *moods]))
        cache_key = sha256_json(normalized.model_dump(mode="json"))
        object_key = f"pregen/{normalized.intent.value}/{cache_key[:16]}.wav"
        generated = provider.generate(normalized, storage.path_for(object_key), object_key)
        repository.upsert_asset(
            AudioAssetIn(
                type=AudioType(normalized.intent.value),
                title=generated.title,
                object_key=object_key,
                duration_sec=generated.duration_sec,
                language=normalized.language,
                voice_id=normalized.voice_style,
                prompt_hash=cache_key,
                content_hash=generated.content_hash,
                mood_tags=normalized.mood,
                user_segment_tags=segments,
                safety_status="approved",
                quality_score=0.78 if normalized.intent != AudioType.STORY else 0.84,
                embedding=text_embedding(
                    " ".join(
                        [
                            request_text,
                            normalized.intent.value,
                            normalized.background,
                            normalized.voice_style,
                            *normalized.mood,
                            *normalized.content_topic,
                            *segments,
                        ]
                    )
                ),
                created_by="pregen",
            )
        )
        created += 1
    return created
