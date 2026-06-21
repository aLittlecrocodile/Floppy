from __future__ import annotations

from dataclasses import dataclass

from floppy_backend.models import AudioScriptIn, AudioType, NormalizedAudioRequest, UserProfile
from floppy_backend.services import script_guard
from floppy_backend.utils import sha256_text


@dataclass(frozen=True)
class SleepScript:
    title: str
    script_text: str
    content_type: AudioType
    language: str
    pause_density: str
    estimated_duration_sec: int
    script_hash: str
    safety_status: str = "approved"
    safety_notes: tuple[str, ...] = ()

    def to_input(self, user_id: str) -> AudioScriptIn:
        return AudioScriptIn(
            user_id=user_id,
            title=self.title,
            content_type=self.content_type,
            language=self.language,
            script_text=self.script_text,
            script_hash=self.script_hash,
            pause_density=self.pause_density,
            estimated_duration_sec=self.estimated_duration_sec,
            safety_status=self.safety_status,
            safety_notes=list(self.safety_notes),
        )


class SleepScriptService:
    """Deterministic first-pass script generator for provider integration.

    The real product can later swap this for an LLM-backed implementation. This
    service still owns the contract: low-stimulation text, MiniMax pause marks,
    stable hashing, and content-type-specific rhythm.
    """

    def generate(self, normalized: NormalizedAudioRequest, profile: UserProfile | None = None) -> SleepScript:
        content_type = normalized.intent
        if content_type == AudioType.MEDITATION:
            return self._meditation(normalized, profile)
        if content_type == AudioType.ASMR:
            return self._asmr(normalized, profile)
        return self._story(normalized, profile)

    def _story(self, normalized: NormalizedAudioRequest, profile: UserProfile | None) -> SleepScript:
        topic = self._topic_label(normalized)
        background = self._background_label(normalized.background)
        title = f"{topic}的安静夜晚"
        body = [
            f"今晚，我给你讲一个关于{topic}的故事。<#3#>",
            "这是一个很轻、很慢的故事。<#3#>你不需要记住任何情节，只要听着就好。<#6#>",
            f"夜色慢慢落下来，{background}在远处轻轻铺开。<#3#>",
            f"{topic}安静地待在柔和的灯光里，像一页刚刚翻开的旧书。<#2#>",
            "空气里有一点温暖，也有一点清凉。<#2#>",
            "每一个声音都很轻。<#1#>每一次停顿都像是在替夜晚整理呼吸。<#4#>",
            "有人沿着安静的小路慢慢走着。<#2#>脚步不急，也没有要赶去的地方。<#3#>",
            "路边的窗子透出淡淡的光。<#2#>那光落在地面上，又慢慢变得柔和。<#4#>",
            "故事就这样继续着。<#2#>没有突然的转折，也没有需要担心的事情。<#4#>",
            "只是一个安稳的夜晚，一点点向更深处展开。<#5#>",
            "如果你愿意，可以让注意力停在我的声音旁边。<#3#>",
            "也可以让它慢慢飘远。<#4#>像一盏灯，在很远的地方，安静地亮着。<#8#>",
        ]
        return self._build(title, "\n\n".join(body), normalized, "medium")

    def _meditation(self, normalized: NormalizedAudioRequest, profile: UserProfile | None) -> SleepScript:
        background = self._background_label(normalized.background)
        title = f"{background}呼吸放松"
        body = [
            "嗨。<#3#>今晚，我会带你做一次很轻的呼吸放松。<#3#>",
            "你只需要找一个舒服的姿势，跟着我的声音就好。<#6#>",
            "先慢慢吸气。<#4#>然后，慢慢呼气。<#5#>",
            "再一次，吸气。<#4#>呼气。<#5#>",
            "让肩膀松下来。<#3#>让手臂也慢慢变沉。<#4#>",
            f"想象{background}在很远的地方，轻轻地陪着你。<#4#>",
            "你的额头放松。<#2#>眼睛周围放松。<#3#>下颌也放松。<#4#>",
            "每一次呼气，都可以少用一点力。<#5#>",
            "你不用让自己马上睡着。<#3#>只要在这里，慢慢休息。<#6#>",
            "吸气时，感受一点点安稳。<#4#>呼气时，把今天放远一点。<#6#>",
            "接下来，我会少说一些话。<#4#>把更多安静留给你。<#8#>",
            "很好。<#5#>就这样。<#8#>",
        ]
        return self._build(title, "\n\n".join(body), normalized, "high")

    def _asmr(self, normalized: NormalizedAudioRequest, profile: UserProfile | None) -> SleepScript:
        topic = self._topic_label(normalized)
        title = f"{topic}低语"
        body = [
            "嗨。<#3#>",
            "睡不着也没关系。<#4#>",
            "今晚，我会很轻很轻地说话。<#5#>",
            f"我们可以想一想{topic}。<#4#>",
            "很慢。<#3#>",
            "很安静。<#5#>",
            "一点点声音。<#3#>",
            "一点点停顿。<#5#>",
            "你不需要回应。<#4#>",
            "只要听着。<#5#>",
            f"{topic}在夜里慢慢安静下来。<#5#>",
            "一。<#3#>",
            "二。<#3#>",
            "三。<#4#>",
            "慢慢地。<#5#>",
            "不用着急。<#6#>",
            "就这样。<#8#>",
        ]
        return self._build(title, "\n\n".join(body), normalized, "very_high")

    def _build(self, title: str, script_text: str, normalized: NormalizedAudioRequest, pause_density: str) -> SleepScript:
        estimated = min(normalized.duration_sec, self._estimate_duration(script_text))
        script_hash = sha256_text(
            "|".join(
                [
                    normalized.intent.value,
                    normalized.language,
                    title,
                    pause_density,
                    script_text,
                ]
            )
        )
        guard = script_guard.check(script_text, estimated)
        notes: tuple[str, ...] = tuple(guard.all_notes) if guard.all_notes else ("low_stimulation", "no_medical_claim")
        return SleepScript(
            title=title,
            script_text=script_text,
            content_type=normalized.intent,
            language=normalized.language,
            pause_density=pause_density,
            estimated_duration_sec=estimated,
            script_hash=script_hash,
            safety_status=guard.status,
            safety_notes=notes,
        )

    def _estimate_duration(self, script_text: str) -> int:
        readable_chars = sum(1 for char in script_text if "\u4e00" <= char <= "\u9fff" or char.isalnum())
        pause_seconds = 0.0
        for marker in script_text.split("<#")[1:]:
            value = marker.split("#>", 1)[0]
            try:
                pause_seconds += float(value)
            except ValueError:
                continue
        return max(30, int(readable_chars / 3.2 + pause_seconds))

    def _topic_label(self, normalized: NormalizedAudioRequest) -> str:
        labels = {
            "sea": "海边",
            "bookstore": "书店",
            "forest": "森林",
            "rain": "雨夜",
            "stars": "星空",
            "cat": "猫",
            "city": "城市",
            "sleep": "夜晚",
        }
        for topic in normalized.content_topic:
            if topic in labels:
                return labels[topic]
        return "夜晚"

    def _background_label(self, background: str) -> str:
        labels = {
            "rain_soft": "轻柔的雨声",
            "ocean_soft": "远处的海浪",
            "wind_soft": "很轻的风声",
            "forest_night": "夜晚的森林",
            "fireplace": "温暖的壁炉声",
            "none": "安静",
        }
        return labels.get(background, "安静")
