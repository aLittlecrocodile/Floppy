from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from floppy_backend.config import Settings
from floppy_backend.services.hermes_agent import _extract_json_object, _local_hermes_api_key, _responses_output_text


_ACTIONS = {"chat", "clarify", "audio_workflow", "remix_current", "stop_audio", "no_match"}
_STOP_AUDIO_RE = re.compile(
    r"(停一下|停下|停止|暂停|停掉|关掉|别放了?|别播了?|不要放了?|不听了|够了|静音|安静一点)"
)


class VoiceDialogRoute(BaseModel):
    action: str = "chat"
    reply_text: str = ""
    audio_request_text: str | None = None
    audio_intent_hint: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)

    def normalized_action(self) -> str:
        if self.action not in _ACTIONS:
            raise ValueError(f"unsupported voice dialog action: {self.action}")
        return self.action

    def response_text(self) -> str:
        return self.reply_text.strip() or "我听到了，我们先慢慢聊一会儿。"

    def audio_text(self, fallback: str) -> str:
        return (self.audio_request_text or fallback).strip() or fallback


class HermesVoiceDialogClient:
    """Hermes Skill adapter for voice-dialog routing.

    It decides whether an ASR-finalized utterance is just conversation, needs a
    clarification, or should be handed to the sleep-audio workflow. It never
    searches assets or generates audio directly.
    """

    def __init__(self, settings: Settings):
        self._base_url = settings.hermes_base_url.rstrip("/")
        self._responses_url = f"{self._base_url}/responses" if self._base_url.endswith("/v1") else f"{self._base_url}/v1/responses"
        self._api_key = settings.hermes_api_key or _local_hermes_api_key(settings.hermes_base_url)
        self._model = settings.hermes_model
        self._timeout = settings.hermes_timeout_sec
        self._store = settings.hermes_store_conversation

    def route(
        self,
        *,
        user_id: str,
        conversation_id: str,
        text: str,
        history: list[dict[str, str]],
        source: str = "voice",
        current_asset_id: str | None = None,
    ) -> VoiceDialogRoute:
        if _STOP_AUDIO_RE.search(text):
            return VoiceDialogRoute(
                action="stop_audio",
                reply_text="好的，先帮你停掉。",
                confidence=0.98,
                reasons=["用户明确要求停止当前播放"],
            )

        prompt = json.dumps(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "source": source,
                "current_asset_id": current_asset_id,
                "history": history,
                "user_text": text,
            },
            ensure_ascii=False,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": f"floppy-voice-dialog:{conversation_id}",
            "X-Hermes-Session-Key": f"floppy:voice:{conversation_id}",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = httpx.post(
                self._responses_url,
                headers=headers,
                json={
                    "model": self._model,
                    "input": prompt,
                    "instructions": _HERMES_VOICE_DIALOG_INSTRUCTIONS,
                    "store": self._store,
                    "conversation": f"floppy-voice-dialog:{conversation_id}",
                    "tools": [],
                    "tool_choice": "none",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload: dict[str, Any] = _extract_json_object(_responses_output_text(response.json()))
            route = VoiceDialogRoute.model_validate(payload)
            route.normalized_action()
            return route
        except Exception as exc:  # noqa: BLE001 - voice should degrade to chat, not surprise-play audio
            return VoiceDialogRoute(
                action="chat",
                reply_text="我听到了，我们先慢慢聊一会儿。",
                confidence=0.0,
                reasons=[f"Hermes voice-dialog fallback: {type(exc).__name__}"],
            )


_HERMES_VOICE_DIALOG_INSTRUCTIONS = """
你是 Floppy 的 voice-dialog Skill。你只负责判断一条 ASR 完句在语音对话里应该怎么路由；不要搜索资源，不要生成音频，不要编 asset id。

核心原则：
- 语音入口是对话优先，不是推荐入口。
- 用户表达模糊、倾诉、打招呼、说睡不着或想放松时，先 chat 或 clarify，不要直接进入音频 workflow。
- 用户明确要求播放/来一段/想听某类音频时，才进入 audio_workflow。
- 用户要求停止、暂停、别放了、关掉音乐时，选择 stop_audio；这是播放控制，不进入音频 workflow。
- 用户想改当前播放内容，比如换一个、加雨声、小声点、不要这个，且有 current_asset_id 时，选择 remix_current；没有 current_asset_id 时选择 clarify。
- audio_workflow 只负责把明确音频请求交给 floppy-sleep-audio Skill；你不要自己调用资源工具。

可选 action：
- chat：普通聊天、倾诉、安抚，不触发音频。
- clarify：需求模糊，需要追问。比如“我想放松一点”可以问想听雨声、钢琴还是呼吸引导。
- audio_workflow：明确要音频。填写 audio_request_text，保留用户硬约束。
- remix_current：明确修改当前音频。填写 audio_request_text，保留修改目标。
- stop_audio：停止当前正在播放的助眠音频，不搜索、不生成、不 remix。
- no_match：不适合处理或不安全。

audio_intent_hint 只能是：
white_noise | music | meditation | story | asmr | podcast_digest | null

判断例子：
- “我睡不着”“有点焦虑”“今天好累” -> chat。
- “想放松一点” -> clarify。
- “放点雨声”“我想听钢琴”“来个睡前故事” -> audio_workflow。
- “不要人声的雨声”“白噪音不要雷声” -> audio_workflow，并把这些硬约束写进 audio_request_text。
- “换一个”“加点雨声”“小声一点” -> 有 current_asset_id 则 remix_current，否则 clarify。
- “停一下”“停止音乐”“先别放了”“暂停播放” -> stop_audio。

reply_text 要是给用户听的一句话，温柔、简短、口语化。audio_workflow 时可以说“好的，我先帮你找；没有合适的我会实时生成。”；chat/clarify 时不要承诺已经播放。

只输出 JSON，不要 Markdown：
{
  "action": "chat|clarify|audio_workflow|remix_current|stop_audio|no_match",
  "reply_text": "给用户听的一句话",
  "audio_request_text": null,
  "audio_intent_hint": null,
  "confidence": 0.0,
  "reasons": ["简短中文原因"]
}
""".strip()
