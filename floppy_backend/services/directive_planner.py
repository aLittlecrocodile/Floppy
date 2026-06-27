"""Directive Planner — the agent "thinks first" before commanding the workflow.

Before触发生成，把用户原话 + 画像提炼成一份结构化的 GenerationDirective：
内容要点（outline）、必含意象（key_elements）、基调、时长、音色。workflow 拿到
要点后用 LLM 写出贴合用户的脚本，而不是套通用模板。

复用 query_planner.AIQueryPlanner 的骨架（OpenAI-compatible chat completions，
JSON 输出，超时/失败回退）。任何失败 → 返回 None，让 script.py 走模板兜底，
不破坏已跑通的老链路。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from floppy_backend.models import AudioType, GenerationDirective, ProfileContext
from floppy_backend.services.query_planner import _extract_json

_INTENT_VALUES = ", ".join(t.value for t in AudioType)

_SYSTEM_PROMPT = """你是助眠音频的内容策划。把用户的需求和画像，提炼成一份"生成指令"，供后续写脚本用。

只输出一个 JSON 对象，不要解释、不要 markdown。

JSON 结构（严格按此输出）:
{{"intent":"<以下之一: {intents}>","tone":"温柔平静","duration_sec":900,"voice_style":"gentle_female","content_brief":"一句话主题","outline":["分段要点1","分段要点2","分段要点3"],"key_elements":["必须出现的意象1","意象2"],"confidence":0.85}}

规则:
- intent 必须从给定枚举里选，最贴合用户想听的类型（讲故事=story，呼吸/冥想引导=meditation，雨声/海浪/自然白噪音=white_noise，轻音乐=music，低语=asmr，播客/资讯=podcast_digest）。
- content_brief 一句话概括这次要生成什么，贴合用户原话。
- outline 是 4-8 条分段要点，把用户提到的具体意象、人物、场景拆进去，按助眠节奏推进（开场轻、中段展开、结尾越来越静）。绝不重复同一要点。
- key_elements 抽取用户明确提到的、脚本里必须出现的具体意象（如"祖母""老花园""老槐树"）。用户没提就留空数组。
- 助眠基调：低刺激、缓慢、温柔；不要紧张/惊吓/医疗承诺/兴奋情绪。
- duration_sec 依据用户要求或画像偏好（分钟×60）。confidence 0.0-1.0。"""


class DirectivePlanner:
    """LLM-backed planner: request + profile -> GenerationDirective (or None)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "DeepSeek-V4-Flash",
        timeout_sec: float = 12.0,
        max_tokens: int = 1200,
        confidence_threshold: float = 0.5,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_sec = timeout_sec
        self._max_tokens = max_tokens
        self._confidence_threshold = confidence_threshold

    def plan(self, request_text: str, profile_context: ProfileContext | None) -> GenerationDirective | None:
        """Return a directive, or None to let the workflow use templates."""
        try:
            parsed = self._call_llm(request_text, profile_context)
            directive = self._validate(parsed)
        except (urllib.error.URLError, OSError, ValueError, KeyError, json.JSONDecodeError, TimeoutError):
            return None
        if directive is None or directive.confidence < self._confidence_threshold:
            return None
        return directive

    # -- internals ------------------------------------------------------------

    def _call_llm(self, request_text: str, ctx: ProfileContext | None) -> dict:
        system_msg = _SYSTEM_PROMPT.format(intents=_INTENT_VALUES)
        user_msg = self._build_user_message(request_text, ctx)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.4,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choice = data["choices"][0]
        content = (choice["message"].get("content") or "").strip()
        if not content:
            content = (choice["message"].get("reasoning_content") or "").strip()
        if not content:
            raise ValueError("LLM returned empty content")
        return _extract_json(content)

    def _build_user_message(self, request_text: str, ctx: ProfileContext | None) -> str:
        if ctx is None:
            return f"用户需求: {request_text}\n画像: 未知，按通用助眠偏好处理。"
        prefs = [t.value for t in ctx.audio_type_preferences]
        return (
            f"用户需求: {request_text}\n"
            f"用户分群: {ctx.algo_segment or ctx.segment}\n"
            f"情绪标签: {ctx.mood_tags}\n"
            f"今晚心情: {ctx.tonight_mood or '未知'}\n"
            f"偏好音频类型: {prefs}\n"
            f"偏好时长: {ctx.duration_preference_min}分钟\n"
            f"声音偏好: {ctx.voice_preferences}"
        )

    def _validate(self, parsed: dict) -> GenerationDirective | None:
        intent_raw = parsed.get("intent")
        intent: AudioType | None = None
        if intent_raw:
            try:
                intent = AudioType(intent_raw)
            except ValueError:
                intent = None

        outline = [str(x).strip() for x in parsed.get("outline", []) if str(x).strip()]
        key_elements = [str(x).strip() for x in parsed.get("key_elements", []) if str(x).strip()]
        content_brief = str(parsed.get("content_brief", "")).strip()

        # No usable content intent → not worth a directive; let templates run.
        if not outline and not content_brief:
            return None

        duration = parsed.get("duration_sec")
        try:
            duration = int(duration) if duration else None
        except (TypeError, ValueError):
            duration = None
        if duration is not None:
            duration = max(30, min(3600, duration))

        return GenerationDirective(
            intent=intent,
            tone=(str(parsed.get("tone")).strip() or None) if parsed.get("tone") else None,
            duration_sec=duration,
            voice_style=(str(parsed.get("voice_style")).strip() or None) if parsed.get("voice_style") else None,
            content_brief=content_brief,
            outline=outline,
            key_elements=key_elements,
            confidence=float(parsed.get("confidence", 0.6)),
            source="agent",
        )
