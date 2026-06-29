from __future__ import annotations

import re

from floppy_backend.models import AudioAsset, AudioType, GenerationDirective, GenerationRequest, NormalizedAudioRequest, UserProfile


class RequestDefaults:
    def normalize(
        self,
        request: GenerationRequest,
        profile: UserProfile | None,
        directive: GenerationDirective | None = None,
    ) -> NormalizedAudioRequest:
        directive = directive or request.directive
        text = request.request_text.lower()
        intent = directive.intent if directive and directive.intent else self._fallback_intent(text, profile)
        explicit_duration_min = (
            request.duration_preference_min
            or self._duration_from_directive(directive)
            or self._duration_from_text(text)
        )
        duration_min = explicit_duration_min or self._default_duration(intent, profile)
        voice_style = (directive.voice_style if directive and directive.voice_style else None) or self._voice(text, profile, intent)
        background = self._background(self._directive_text(text, directive), profile)
        mood = self._mood(self._directive_text(text, directive), profile)
        topics = self._topics(self._directive_text(text, directive))
        return NormalizedAudioRequest(
            intent=intent,
            duration_bucket=self._duration_bucket(duration_min),
            duration_sec=duration_min * 60,
            voice_style=voice_style,
            background=background,
            mood=mood,
            content_topic=topics,
        )

    def from_asset(self, asset: AudioAsset, profile: UserProfile | None = None) -> NormalizedAudioRequest:
        background = self._background(" ".join([asset.title, *asset.tags]), profile)
        mood = list(asset.mood_tags or profile.mood_tags if profile else asset.mood_tags) or ["calm"]
        topics = [tag for tag in asset.tags if tag in {"rain", "ocean", "nature", "forest", "ambient"}] or ["sleep"]
        voice_style = "none" if asset.type in {AudioType.WHITE_NOISE, AudioType.MUSIC} else asset.voice_id
        return NormalizedAudioRequest(
            intent=asset.type,
            duration_bucket=self._duration_bucket(max(1, round(asset.duration_sec / 60))),
            duration_sec=asset.duration_sec,
            voice_style=voice_style,
            background=background,
            mood=sorted(set(mood)),
            content_topic=topics,
        )

    def _fallback_intent(self, text: str, profile: UserProfile | None) -> AudioType:
        if self._contains_positive(text, ["白噪音", "自然音", "环境音", "white noise"]):
            return AudioType.WHITE_NOISE
        if self._contains_positive(text, ["音乐", "钢琴", "弦乐", "轻音乐", "music"]):
            return AudioType.MUSIC
        if self._contains_positive(text, ["故事", "童话", "讲一个", "story"]):
            return AudioType.STORY
        if self._contains_positive(text, ["冥想", "呼吸", "meditation"]):
            return AudioType.MEDITATION
        if self._contains_positive(text, ["asmr", "低语"]):
            return AudioType.ASMR
        if self._contains_positive(text, ["文章", "播客", "摘要"]):
            return AudioType.PODCAST_DIGEST
        if self._contains_positive(text, ["雨声", "海浪", "风声"]):
            return AudioType.WHITE_NOISE
        if profile and profile.audio_type_preferences:
            return profile.audio_type_preferences[0]
        return AudioType.MUSIC

    def _contains_positive(self, text: str, keywords: list[str]) -> bool:
        for keyword in keywords:
            index = text.find(keyword)
            if index < 0:
                continue
            prefix = text[max(0, index - 8):index]
            if any(neg in prefix for neg in ["不要", "不想", "别", "不是", "无需", "无"]):
                continue
            return True
        return False

    def _duration_from_text(self, text: str) -> int | None:
        match = re.search(r"(\d{1,2})\s*(分钟|min)", text)
        if match:
            return max(5, min(60, int(match.group(1))))
        return None

    def _duration_from_directive(self, directive: GenerationDirective | None) -> int | None:
        if directive is None or directive.duration_sec is None:
            return None
        return max(1, round(directive.duration_sec / 60))

    def _default_duration(self, intent: AudioType, profile: UserProfile | None) -> int:
        if intent in {AudioType.MEDITATION, AudioType.WHITE_NOISE, AudioType.MUSIC}:
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

    def _voice(self, text: str, profile: UserProfile | None, intent: AudioType) -> str:
        if intent in {AudioType.WHITE_NOISE, AudioType.MUSIC}:
            return "none"
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
        }
        for keyword, topic in mapping.items():
            if keyword in text:
                topics.append(topic)
        return topics or ["sleep"]

    def _directive_text(self, request_text: str, directive: GenerationDirective | None) -> str:
        if directive is None:
            return request_text
        return " ".join(
            [
                request_text,
                directive.content_brief,
                *(directive.key_elements or []),
                *(directive.outline or []),
            ]
        ).lower()
