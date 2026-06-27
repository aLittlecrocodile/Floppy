from __future__ import annotations

from dataclasses import dataclass

from floppy_backend.models import (
    AudioScriptIn,
    AudioType,
    GenerationDirective,
    NormalizedAudioRequest,
    UserProfile,
)
from floppy_backend.services import script_guard
from floppy_backend.services.script_writer import LLMScriptWriter
from floppy_backend.utils import sha256_text

MEDITATION_MIN_TARGET_RATIO = 0.92
MEDITATION_MAX_READABLE_CHARS = 1_650


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
    """Script generator for provider integration.

    Two paths, same contract (low-stimulation text, MiniMax pause marks, stable
    hashing, content-type rhythm):

    - **directive with outline** → an LLMScriptWriter writes a personalized
      script from the agent's content points (the smart path). If the LLM is
      unavailable or its output fails the guard, we silently fall back to ...
    - **no directive / fallback** → the deterministic templates below (the safe
      path that always works, never breaks the old flow).
    """

    def __init__(self, script_writer: LLMScriptWriter | None = None):
        self._writer = script_writer

    def generate(
        self,
        normalized: NormalizedAudioRequest,
        profile: UserProfile | None = None,
        directive: GenerationDirective | None = None,
    ) -> SleepScript:
        if directive is not None and directive.has_outline and self._writer is not None:
            llm_script = self._try_llm_script(normalized, directive)
            if llm_script is not None:
                return llm_script

        content_type = normalized.intent
        if content_type == AudioType.MEDITATION:
            return self._meditation(normalized, profile)
        if content_type == AudioType.ASMR:
            return self._asmr(normalized, profile)
        return self._story(normalized, profile)

    def _try_llm_script(
        self, normalized: NormalizedAudioRequest, directive: GenerationDirective
    ) -> SleepScript | None:
        """Write a script from the directive's outline; None → caller falls back."""
        intent = directive.intent or normalized.intent
        duration = directive.duration_sec or normalized.duration_sec
        written = self._writer.write(directive, intent, duration)
        if written is None:
            return None
        title, script_text = written
        # Reuse the same build path (guard + hashing) as templates. If the LLM
        # script trips script_guard (e.g. medical claim slipped in), reject it
        # so the caller falls back to a known-safe template.
        candidate = self._build(title, script_text, normalized, self._pause_density_for(intent))
        if candidate.safety_status != "approved":
            return None
        return candidate

    @staticmethod
    def _pause_density_for(intent: AudioType) -> str:
        return {
            AudioType.ASMR: "very_high",
            AudioType.MEDITATION: "high",
        }.get(intent, "medium")

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
        body = self._extend_meditation(body, normalized.duration_sec, background)
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

    def _extend_meditation(self, body: list[str], target_duration_sec: int, background: str) -> list[str]:
        if target_duration_sec <= 0:
            return body

        target = int(target_duration_sec * MEDITATION_MIN_TARGET_RATIO)
        if self._estimate_duration("\n\n".join(body)) >= target:
            return body

        cycles = [
            "把注意力放在鼻尖。<#8#>吸气的时候，知道自己正在吸气。<#8#>呼气的时候，知道自己正在呼气。<#10#>",
            "让肩膀再松一点。<#8#>让背部也慢慢放宽。<#8#>身体不需要支撑什么。<#10#>",
            "感受胸口轻轻起伏。<#8#>不用控制它。<#8#>只是陪着这一点点起伏。<#10#>",
            "如果有念头经过，也没关系。<#8#>看见它。<#6#>然后，让它像云一样慢慢走远。<#10#>",
            f"想象{background}在远处继续陪着你。<#8#>声音很轻。<#8#>节奏很慢。<#10#>",
            "把注意力带到双手。<#8#>手指放松。<#8#>掌心放松。<#10#>",
            "把注意力带到腹部。<#8#>吸气时，腹部微微鼓起。<#8#>呼气时，腹部慢慢落下。<#10#>",
            "把注意力带到双腿。<#8#>大腿放松。<#8#>小腿放松。<#8#>脚背和脚趾也放松。<#10#>",
            "现在，只听见呼吸。<#8#>只感觉身体。<#8#>这一刻，已经足够安静。<#10#>",
            "吸气。<#8#>停一停。<#6#>呼气。<#10#>让呼气比吸气更慢一点。<#10#>",
            "你不需要做得很好。<#8#>也不需要追求任何结果。<#8#>只是休息。<#10#>",
            "让脸颊变软。<#8#>让眼皮变沉。<#8#>让下颌自然地松开。<#10#>",
        ]

        extended = list(body[:-2])
        index = 0
        while self._estimate_duration("\n\n".join(extended + body[-2:])) < target:
            if self._readable_chars("\n\n".join(extended)) >= MEDITATION_MAX_READABLE_CHARS:
                break
            extended.append(cycles[index % len(cycles)])
            index += 1

        extended.extend([
            "接下来的时间，话会越来越少。<#10#>你可以继续听，也可以让声音慢慢退到远处。<#12#>",
            "如果你还醒着，就回到呼吸。<#10#>吸气。<#8#>呼气。<#12#>",
            "很好。<#10#>现在，把剩下的安静留给身体。<#15#>",
        ])
        return extended

    def _readable_chars(self, text: str) -> int:
        return sum(1 for char in text if "\u4e00" <= char <= "\u9fff" or char.isalnum())

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
