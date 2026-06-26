"""Volcengine large-model streaming ASR over WebSocket.

Implements the binary protocol for wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
(豆包 / bigmodel sauc). Accepts a stream of raw PCM (16k, mono, int16) audio
chunks and yields recognition results as they arrive.

The server returns CUMULATIVE text, so each ASRResult.text is the full
utterance so far (not a delta). is_final marks the last packet.

Docs: https://www.volcengine.com/docs/6561/1354869
"""

from __future__ import annotations

import gzip
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import websockets

from floppy_backend.config import Settings

# --- Protocol constants ---
_PROTOCOL_VERSION = 0b0001
_HEADER_SIZE = 0b0001  # in 4-byte units -> 4-byte header
_JSON_SERIALIZATION = 0b0001
_GZIP_COMPRESSION = 0b0001

_FULL_CLIENT_REQUEST = 0b0001
_AUDIO_ONLY_REQUEST = 0b0010
_FULL_SERVER_RESPONSE = 0b1001
_SERVER_ERROR_RESPONSE = 0b1111

_POS_SEQUENCE = 0b0001
_NO_SEQUENCE = 0b0000
_NEG_SEQUENCE = 0b0010  # last package


@dataclass(frozen=True)
class ASRResult:
    text: str  # cumulative recognized text so far
    is_final: bool


class VolcASRError(RuntimeError):
    pass


def _build_header(message_type: int, flags: int) -> bytearray:
    hdr = bytearray(4)
    hdr[0] = (_PROTOCOL_VERSION << 4) | _HEADER_SIZE
    hdr[1] = (message_type << 4) | flags
    hdr[2] = (_JSON_SERIALIZATION << 4) | _GZIP_COMPRESSION
    hdr[3] = 0x00
    return hdr


def _full_client_request(payload: dict, sequence: int = 1) -> bytes:
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    pkt = _build_header(_FULL_CLIENT_REQUEST, _POS_SEQUENCE)
    pkt.extend(sequence.to_bytes(4, "big", signed=True))
    pkt.extend(len(body).to_bytes(4, "big"))
    pkt.extend(body)
    return bytes(pkt)


def _audio_request(audio: bytes, *, is_last: bool) -> bytes:
    body = gzip.compress(audio)
    pkt = _build_header(_AUDIO_ONLY_REQUEST, _NEG_SEQUENCE if is_last else _NO_SEQUENCE)
    pkt.extend(len(body).to_bytes(4, "big"))
    pkt.extend(body)
    return bytes(pkt)


def _parse_response(data: bytes) -> dict:
    header_size = data[0] & 0x0F
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    compression = data[2] & 0x0F
    payload = data[header_size * 4:]
    result: dict = {"is_last": bool(flags & 0x02), "message_type": message_type}

    if flags & 0x01:  # leading sequence number
        result["sequence"] = int.from_bytes(payload[:4], "big", signed=True)
        payload = payload[4:]

    if message_type == _FULL_SERVER_RESPONSE:
        size = int.from_bytes(payload[:4], "big", signed=True)
        body = payload[4:4 + size]
        if compression == _GZIP_COMPRESSION:
            body = gzip.decompress(body)
        result["payload"] = json.loads(body.decode("utf-8"))
    elif message_type == _SERVER_ERROR_RESPONSE:
        result["error_code"] = int.from_bytes(payload[:4], "big", signed=False)
        size = int.from_bytes(payload[4:8], "big", signed=False)
        body = payload[8:8 + size]
        if compression == _GZIP_COMPRESSION:
            body = gzip.decompress(body)
        result["error_msg"] = body.decode("utf-8", errors="replace")
    return result


class VolcStreamASR:
    """Streaming ASR client over Volcengine WebSocket."""

    def __init__(self, settings: Settings):
        if not (settings.volc_asr_app_key and settings.volc_asr_access_key):
            raise VolcASRError(
                "Volcengine ASR requires FLOPPY_VOLC_ASR_APP_KEY and FLOPPY_VOLC_ASR_ACCESS_KEY"
            )
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-App-Key": self._settings.volc_asr_app_key,
            "X-Api-Access-Key": self._settings.volc_asr_access_key,
            "X-Api-Resource-Id": self._settings.volc_asr_resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

    def _init_payload(self) -> dict:
        return {
            "user": {"uid": "floppy-voice"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": self._settings.volc_asr_sample_rate,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True,
                "enable_itn": True,
                "result_type": "single",
            },
        }

    @staticmethod
    def _extract_text(payload: dict) -> str:
        result = payload.get("result")
        if isinstance(result, dict):
            return str(result.get("text") or "")
        if isinstance(result, list) and result:
            return str(result[0].get("text") or "")
        return ""

    async def stream_recognize(self, audio_iter: AsyncIterator[bytes]) -> AsyncIterator[ASRResult]:
        """Recognize a stream of PCM audio chunks, yielding cumulative results.

        Runs the audio sender and response receiver concurrently so partial
        results surface while audio is still being pushed.
        """
        import asyncio

        async with websockets.connect(self._settings.volc_asr_ws_url, additional_headers=self._headers()) as ws:
            await ws.send(_full_client_request(self._init_payload()))

            queue: asyncio.Queue[ASRResult | None] = asyncio.Queue()

            async def _send() -> None:
                chunks: list[bytes] = []
                async for chunk in audio_iter:
                    chunks.append(chunk)
                # Drain: send all but last as non-final, last as final.
                if not chunks:
                    await ws.send(_audio_request(b"", is_last=True))
                    return
                for index, chunk in enumerate(chunks):
                    await ws.send(_audio_request(chunk, is_last=(index == len(chunks) - 1)))

            async def _recv() -> None:
                try:
                    while True:
                        raw = await ws.recv()
                        if isinstance(raw, str):
                            continue
                        parsed = _parse_response(raw)
                        if parsed["message_type"] == _SERVER_ERROR_RESPONSE:
                            raise VolcASRError(
                                f"Volc ASR error {parsed.get('error_code')}: {parsed.get('error_msg')}"
                            )
                        payload = parsed.get("payload") or {}
                        text = self._extract_text(payload)
                        is_final = parsed["is_last"]
                        if text or is_final:
                            await queue.put(ASRResult(text=text, is_final=is_final))
                        if is_final:
                            break
                except websockets.ConnectionClosed:
                    pass
                finally:
                    await queue.put(None)

            send_task = asyncio.create_task(_send())
            recv_task = asyncio.create_task(_recv())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield item
            finally:
                send_task.cancel()
                recv_task.cancel()
