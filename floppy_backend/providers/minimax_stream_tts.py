"""MiniMax streaming TTS over WebSocket.

Connects to wss://api.minimaxi.com/ws/v1/t2a_v2 and drives the
task_start -> task_continue* -> task_finish protocol. Audio arrives in
`task_continued` events as hex-encoded chunks (mp3 by default), which we decode
and yield as bytes so the caller can stream them straight to the client.

Docs: https://platform.minimaxi.com/docs/api-reference/speech-t2a-websocket
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import websockets

from floppy_backend.config import Settings
from floppy_backend.providers.audio import build_audio_setting, build_voice_setting


class StreamTTSError(RuntimeError):
    pass


class MiniMaxStreamTTS:
    """Streaming text-to-speech client over MiniMax WebSocket."""

    def __init__(self, settings: Settings):
        if not settings.minimax_api_key:
            raise StreamTTSError("FLOPPY_MINIMAX_API_KEY is required for streaming TTS")
        self._settings = settings

    def _task_start_payload(self, voice_style: str | None, voice_id: str | None) -> dict:
        return {
            "event": "task_start",
            "model": self._settings.minimax_stream_model,
            "language_boost": "auto",
            "voice_setting": build_voice_setting(self._settings, voice_style=voice_style, voice_id=voice_id),
            "audio_setting": build_audio_setting(self._settings),
        }

    @staticmethod
    def _audio_chunk(message: str) -> bytes | None:
        """Extract decoded audio bytes from a server event, if present."""
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            return None
        base_resp = event.get("base_resp") or {}
        if base_resp.get("status_code") not in (0, None):
            raise StreamTTSError(
                f"MiniMax TTS error: {base_resp.get('status_msg')} (code={base_resp.get('status_code')})"
            )
        if event.get("event") == "task_failed":
            raise StreamTTSError(f"MiniMax TTS task_failed: {event}")
        audio_hex = ((event.get("data") or {}).get("audio") or "").strip()
        if not audio_hex:
            return None
        try:
            return bytes.fromhex(audio_hex)
        except ValueError as exc:
            raise StreamTTSError(f"MiniMax TTS returned non-hex audio: {exc}") from exc

    async def stream_synthesize(
        self,
        text_iter: AsyncIterator[str],
        *,
        voice_style: str | None = None,
        voice_id: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Synthesize a stream of text chunks into a stream of audio bytes.

        Opens one WebSocket per call, sends each text chunk as a task_continue,
        and yields audio bytes as they arrive. Closes with task_finish.
        """
        headers = {"Authorization": f"Bearer {self._settings.minimax_api_key}"}
        async with websockets.connect(self._settings.minimax_ws_url, additional_headers=headers) as ws:
            # Drain the initial connected_success event (best-effort).
            await self._recv_until_started(ws, voice_style, voice_id)

            async for text in text_iter:
                text = (text or "").strip()
                if not text:
                    continue
                await ws.send(json.dumps({"event": "task_continue", "text": text}, ensure_ascii=False))
                # Pull all audio produced for this chunk until is_final for it.
                async for chunk in self._recv_audio_until_idle(ws):
                    yield chunk

            await ws.send(json.dumps({"event": "task_finish"}))
            async for chunk in self._drain_remaining(ws):
                yield chunk

    async def _recv_until_started(self, ws, voice_style: str | None, voice_id: str | None) -> None:
        """Send task_start and wait for task_started."""
        await ws.send(json.dumps(self._task_start_payload(voice_style, voice_id), ensure_ascii=False))
        while True:
            message = await ws.recv()
            event = json.loads(message)
            base_resp = event.get("base_resp") or {}
            if base_resp.get("status_code") not in (0, None):
                raise StreamTTSError(
                    f"MiniMax task_start failed: {base_resp.get('status_msg')} (code={base_resp.get('status_code')})"
                )
            if event.get("event") == "task_started":
                return
            if event.get("event") == "task_failed":
                raise StreamTTSError(f"MiniMax task_start failed: {event}")

    async def _recv_audio_until_idle(self, ws) -> AsyncIterator[bytes]:
        """Yield audio for one task_continue until the server marks it final."""
        while True:
            message = await ws.recv()
            chunk = self._audio_chunk(message)
            if chunk:
                yield chunk
            event = json.loads(message)
            # is_final marks the end of audio for the current text segment.
            if event.get("is_final") or event.get("event") == "task_finished":
                return

    async def _drain_remaining(self, ws) -> AsyncIterator[bytes]:
        """After task_finish, drain any trailing audio until the socket closes."""
        try:
            while True:
                message = await ws.recv()
                chunk = self._audio_chunk(message)
                if chunk:
                    yield chunk
                event = json.loads(message)
                if event.get("event") == "task_finished":
                    return
        except websockets.ConnectionClosed:
            return
