from __future__ import annotations

from floppy_backend.models import AudioAssetIn, AudioType, GenerationRequest
from floppy_backend.providers.audio import LocalToneAudioProvider
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json, text_embedding


SEED_REQUESTS = [
    # (request_text, moods, segments, tags, duration_override, quality_override)
    ("雨声白噪音，适合焦虑时放松，20分钟", ["anxiety_relief", "calm"], ["anxiety_relief", "environmental_sleep"], ["rain", "nature", "low_stimulation", "ambient", "no_voice"], None, None),
    ("海浪和轻音乐，帮助快速入睡，15分钟", ["calm", "gentle"], ["quick_sleep", "environmental_sleep"], ["ocean", "nature", "ambient", "minimal_voice", "short_duration"], None, None),
    ("温柔女声睡前故事，森林和星星，20分钟", ["safe", "gentle"], ["companionship", "anxiety_relief"], ["warm_voice", "gentle_story", "nature", "voice_present", "narrative"], None, None),
    ("低语 ASMR，轻柔陪伴，10分钟", ["safe", "gentle"], ["companionship"], ["warm_voice", "slow_pace", "voice_present", "minimal_voice"], None, None),
    ("呼吸冥想引导，压力释放，15分钟", ["anxiety_relief", "calm"], ["anxiety_relief"], ["breathing", "grounding", "low_stimulation", "slow_pace", "high_pause_density"], None, None),
    ("壁炉背景声，安静长时播放，30分钟", ["calm"], ["environmental_sleep"], ["ambient", "nature", "no_voice", "low_stimulation"], None, None),
    ("城市夜晚轻音乐，睡前放松，20分钟", ["calm", "gentle"], ["balanced_sleep"], ["ambient", "minimal_voice", "low_stimulation"], None, None),
    ("播客内容睡前摘要，低信息密度，10分钟", ["calm"], ["content_transform"], ["voice_present", "narrative", "slow_pace"], None, None),
    ("森林夜晚自然音，虫鸣溪流，25分钟", ["calm", "safe"], ["environmental_sleep"], ["nature", "ambient", "no_voice", "rain", "low_stimulation"], None, None),
    ("引导式身体扫描冥想，帮助放松入睡，15分钟", ["anxiety_relief", "calm"], ["anxiety_relief", "quick_sleep"], ["grounding", "breathing", "slow_pace", "high_pause_density", "low_stimulation"], None, None),
    ("温柔男声讲童话故事，猫和月亮，20分钟", ["safe", "gentle"], ["companionship"], ["warm_voice", "gentle_story", "voice_present", "narrative", "slow_pace"], None, None),
    ("海边日落白噪音混合轻柔钢琴，30分钟", ["calm", "gentle"], ["environmental_sleep", "balanced_sleep"], ["ocean", "nature", "ambient", "minimal_voice", "low_stimulation"], None, None),
    ("温柔女声呼吸冥想配轻微雨声，焦虑舒缓，15分钟", ["anxiety_relief", "calm"], ["anxiety_relief", "quick_sleep"], ["breathing", "low_stimulation", "minimal_voice", "rain", "short_duration", "warm_voice", "slow_pace", "grounding"], 900, 0.88),
]


def seed_assets(repository: Repository, storage: LocalFileStorage) -> int:
    provider = LocalToneAudioProvider()
    normalizer = RequestNormalizer()
    created = 0
    for request_text, moods, segments, tags, duration_override, quality_override in SEED_REQUESTS:
        normalized = normalizer.normalize(GenerationRequest(request_text=request_text), profile=None)
        normalized.mood = sorted(set([*normalized.mood, *moods]))
        cache_key = sha256_json(normalized.model_dump(mode="json"))
        object_key = f"pregen/{normalized.intent.value}/{cache_key[:16]}.wav"
        generated = provider.generate(normalized, storage.path_for(object_key), object_key)
        duration_sec = duration_override if duration_override is not None else generated.duration_sec
        quality_score = quality_override if quality_override is not None else (0.78 if normalized.intent != AudioType.STORY else 0.84)
        repository.upsert_asset(
            AudioAssetIn(
                type=AudioType(normalized.intent.value),
                title=generated.title,
                object_key=object_key,
                duration_sec=duration_sec,
                language=normalized.language,
                voice_id=normalized.voice_style,
                prompt_hash=cache_key,
                content_hash=generated.content_hash,
                mood_tags=normalized.mood,
                tags=tags,
                user_segment_tags=segments,
                safety_status="approved",
                quality_score=quality_score,
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
                            *tags,
                        ]
                    )
                ),
                created_by="pregen",
            )
        )
        created += 1
    return created
