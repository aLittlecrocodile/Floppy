"""LLM script writer — turns a GenerationDirective's outline into a full
sleep-audio script (with MiniMax <#秒#> pause marks).

Second LLM step in the "agent commands workflow" flow: DirectivePlanner picks
the要点, this writes the成稿. Reuses the OpenAI-compatible endpoint. Any failure
returns None so SleepScriptService falls back to templates.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from floppy_backend.models import AudioType, GenerationDirective

# Keep within script_guard quality envelope (MIN_CHARS=80, MAX_CHARS=1800).
# Sleep audio stretches short text over long duration via pauses, so we cap
# readable chars rather than chasing the literal minute count.
_MAX_READABLE_CHARS = 1600

_SYSTEM_PROMPT = """你是助眠音频脚本作者。根据给定的"生成指令"写一段中文助眠脚本。

只输出脚本正文，不要标题、不要解释、不要 markdown。

格式要求:
- 用 MiniMax 停顿标记控制节奏：在句子之间插入 <#秒数#>（如 <#4#> <#6#> <#8#>），单个停顿不超过 12 秒。
- 越往后停顿越长、话越少，引导用户慢慢睡去。
- 句子要短、口语、温柔，低刺激。
- 必须自然融入指令里的 key_elements（用户点名的意象），不能漏。
- 严格按 outline 的要点推进，每个要点展开 1-3 句，绝不重复同一画面或同一句式。
- 总字数控制在 {max_chars} 个汉字以内（停顿不算字数）。
- 不要出现：恐怖/惊吓、暴力、医疗承诺（如"保证睡着""治疗失眠"）、兴奋/紧张情绪、色情。"""


class LLMScriptWriter:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "DeepSeek-V4-Flash",
        timeout_sec: float = 20.0,
        max_tokens: int = 2000,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_sec = timeout_sec
        self._max_tokens = max_tokens

    def write(self, directive: GenerationDirective, intent: AudioType, duration_sec: int) -> tuple[str, str] | None:
        """Return (title, script_text) or None to fall back to templates."""
        try:
            content = self._call_llm(directive, intent, duration_sec)
        except (urllib.error.URLError, OSError, ValueError, KeyError, json.JSONDecodeError, TimeoutError):
            return None
        script_text = content.strip()
        if not script_text:
            return None
        title = self._title_for(directive, intent)
        return title, script_text

    def _call_llm(self, directive: GenerationDirective, intent: AudioType, duration_sec: int) -> str:
        minutes = max(1, round(duration_sec / 60))
        user_msg = (
            f"音频类型: {intent.value}\n"
            f"基调: {directive.tone or '温柔平静'}\n"
            f"目标时长: 约{minutes}分钟\n"
            f"主题: {directive.content_brief or '安静助眠'}\n"
            f"必含意象 (key_elements): {directive.key_elements or '无特定要求'}\n"
            f"分段要点 (outline):\n" + "\n".join(f"  {i+1}. {pt}" for i, pt in enumerate(directive.outline))
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT.format(max_chars=_MAX_READABLE_CHARS)},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.7,
            "max_tokens": self._max_tokens,
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
        return content

    def _title_for(self, directive: GenerationDirective, intent: AudioType) -> str:
        if directive.key_elements:
            return directive.key_elements[0][:20]
        if directive.content_brief:
            return directive.content_brief[:20]
        return {
            AudioType.STORY: "安静的睡前故事",
            AudioType.MEDITATION: "呼吸放松引导",
            AudioType.ASMR: "温柔低语",
        }.get(intent, "助眠音频")
