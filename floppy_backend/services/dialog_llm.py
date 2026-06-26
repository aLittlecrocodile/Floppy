"""Streaming dialog LLM client for realtime voice conversation.

Reuses the OpenAI-compatible chat completions endpoint that the query planner
talks to (base_url/api_key/model), but streams tokens (stream=True) so the
TTS pipeline can begin synthesizing as soon as the first sentence is ready.

This is intentionally separate from query_planner.AIQueryPlanner, which does
one-shot JSON tag extraction — different prompt, different output contract.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from floppy_backend.config import Settings

# Sentence-final punctuation used to chunk the token stream into TTS-sized
# pieces. We flush a chunk as soon as one of these is seen so synthesis can
# overlap with generation.
_SENTENCE_ENDINGS = "。！？!?…\n"
_MIN_CHUNK_CHARS = 4


@dataclass
class DialogTurn:
    role: str  # "user" | "assistant"
    content: str


class DialogLLMError(RuntimeError):
    pass


class DialogLLM:
    """Streaming chat client producing assistant text token-by-token."""

    def __init__(self, settings: Settings):
        api_key = settings.dialog_llm_api_key or settings.query_planner_api_key
        if not api_key:
            raise DialogLLMError(
                "dialog LLM requires FLOPPY_DIALOG_LLM_API_KEY or FLOPPY_QUERY_PLANNER_API_KEY"
            )
        self._api_key = api_key
        self._base_url = (settings.dialog_llm_base_url or settings.query_planner_base_url).rstrip("/")
        self._model = settings.dialog_llm_model or settings.query_planner_model
        self._settings = settings

    def _build_messages(self, history: list[DialogTurn], user_text: str) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": self._settings.dialog_system_prompt}]
        # Keep only the most recent N turns to bound context/latency.
        max_msgs = self._settings.dialog_history_max_turns * 2
        for turn in history[-max_msgs:]:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": user_text})
        return messages

    async def stream_tokens(self, history: list[DialogTurn], user_text: str) -> AsyncIterator[str]:
        """Yield assistant text deltas as they arrive from the LLM."""
        payload = {
            "model": self._model,
            "messages": self._build_messages(history, user_text),
            "temperature": self._settings.dialog_temperature,
            "max_tokens": self._settings.dialog_max_tokens,
            "stream": True,
        }
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise DialogLLMError(f"dialog LLM HTTP {resp.status_code}: {body[:500]}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece

    async def stream_sentences(self, history: list[DialogTurn], user_text: str) -> AsyncIterator[str]:
        """Yield complete sentences for low-latency TTS chunking.

        Buffers token deltas and flushes when a sentence-ending punctuation is
        seen (and the buffer is non-trivial), so synthesis can start early.
        """
        buffer = ""
        async for piece in self.stream_tokens(history, user_text):
            buffer += piece
            while True:
                split_at = -1
                for index, char in enumerate(buffer):
                    if char in _SENTENCE_ENDINGS:
                        split_at = index
                        break
                if split_at == -1:
                    break
                sentence = buffer[: split_at + 1].strip()
                buffer = buffer[split_at + 1:]
                if len(sentence) >= _MIN_CHUNK_CHARS:
                    yield sentence
        tail = buffer.strip()
        if tail:
            yield tail
