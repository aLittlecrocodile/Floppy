from __future__ import annotations

import re

from floppy_backend.models import AudioType, GenerationRequest, NormalizedAudioRequest, UserProfile


class RequestNormalizer:
    def normalize(self, request: GenerationRequest, profile: UserProfile | None) -> NormalizedAudioRequest:
        text = request.request_text.lower()
        intent = self._intent(text, profile)
        explicit_duration_min = request.duration_preference_min or self._duration_from_text(text)
        duration_min = explicit_duration_min or self._default_duration(intent, profile)
        voice_style = self._voice(text, profile)
        background = self._background(text, profile)
        mood = self._mood(text, profile)
        topics = self._topics(text)
        return NormalizedAudioRequest(
            intent=intent,
            duration_bucket=self._duration_bucket(duration_min),
            duration_sec=duration_min * 60,
            voice_style=voice_style,
            background=background,
            mood=mood,
            content_topic=topics,
        )

    def _intent(self, text: str, profile: UserProfile | None) -> AudioType:
        if any(keyword in text for keyword in ["故事", "童话", "讲一个", "story"]):
            return AudioType.STORY
        if any(keyword in text for keyword in ["冥想", "呼吸", "meditation"]):
            return AudioType.MEDITATION
        if any(keyword in text for keyword in ["白噪音", "雨声", "海浪", "风声", "white noise"]):
            return AudioType.WHITE_NOISE
        if any(keyword in text for keyword in ["音乐", "钢琴", "小提琴", "吉他", "曲子", "乐曲", "music"]):
            return AudioType.MUSIC
        if any(keyword in text for keyword in ["asmr", "低语"]):
            return AudioType.ASMR
        if any(keyword in text for keyword in ["文章", "播客", "书", "摘要"]):
            return AudioType.PODCAST_DIGEST
        if profile and profile.audio_type_preferences:
            return profile.audio_type_preferences[0]
        return AudioType.MUSIC

    def _duration_from_text(self, text: str) -> int | None:
        match = re.search(r"(\d{1,2})\s*(分钟|min)", text)
        if match:
            return max(5, min(60, int(match.group(1))))
        return None

    def _default_duration(self, intent: AudioType, profile: UserProfile | None) -> int:
        if intent == AudioType.MEDITATION:
            return 20
        return profile.duration_preference_min if profile else 15

    def _duration_bucket(self, duration_min: int) -> str:
        if duration_min <= 10:
            return "5-10min"
        if duration_min <= 20:
            return "10-20min"
        if duration_min <= 30:
            return "20-30min"
        return "30-60min"

    def _voice(self, text: str, profile: UserProfile | None) -> str:
        if "男声" in text:
            return "warm_male"
        if "女声" in text:
            return "warm_female"
        if "低语" in text:
            return "whisper"
        if profile and profile.voice_preferences:
            return profile.voice_preferences[0]
        return "warm_female"

    def _background(self, text: str, profile: UserProfile | None) -> str:
        mapping = {
            "雨": "rain_soft",
            "海": "ocean_soft",
            "浪": "ocean_soft",
            "风": "wind_soft",
            "森林": "forest_night",
            "壁炉": "fireplace",
        }
        for keyword, background in mapping.items():
            if keyword in text:
                return background
        if profile and profile.background_preferences:
            return profile.background_preferences[0]
        return "none"

    def _mood(self, text: str, profile: UserProfile | None) -> list[str]:
        moods = []
        if any(keyword in text for keyword in ["焦虑", "压力", "烦", "紧张"]):
            moods.append("anxiety_relief")
        if any(keyword in text for keyword in ["安心", "安全", "陪"]):
            moods.append("safe")
        if any(keyword in text for keyword in ["温柔", "柔和", "轻"]):
            moods.append("gentle")
        if profile:
            moods.extend(profile.mood_tags)
        return sorted(set(moods or ["calm"]))

    def _topics(self, text: str) -> list[str]:
        topics = []
        mapping = {
            "海": "sea",
            "书店": "bookstore",
            "森林": "forest",
            "雨": "rain",
            "星星": "stars",
            "猫": "cat",
            "城市": "city",
            "钢琴": "piano",
            "小提琴": "violin",
            "吉他": "guitar",
            "爵士": "jazz",
            "古典": "classical",
        }
        for keyword, topic in mapping.items():
            if keyword in text:
                topics.append(topic)
        return topics or ["sleep"]
