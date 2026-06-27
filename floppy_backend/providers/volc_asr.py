"""Volcengine large-model streaming ASR over WebSocket.

Implements the binary protocol for the 豆包大模型流式语音识别 (bigmodel sauc):
  - wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async  (双向流式优化版，推荐)
  - wss://openspeech.bytedance.com/api/v3/sauc/bigmodel        (基础双向流式)

Accepts a stream of raw PCM (16k, mono, int16) audio chunks and yields
recognition results as they arrive.

The server returns CUMULATIVE text in `result.text` (full utterance so far).
Sentence finality is signalled by `result.utterances[].definite=true` (a VAD/
semantic sentence boundary), which we map to ASRResult.is_final.

Auth (新版控制台): single `X-Api-Key` header.
Auth (旧版控制台): `X-Api-App-Key` + `X-Api-Access-Key`.

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
_NO_SERIALIZATION = 0b0000
_GZIP_COMPRESSION = 0b0001

_FULL_CLIENT_REQUEST = 0b0001
_AUDIO_ONLY_REQUEST = 0b0010
_FULL_SERVER_RESPONSE = 0b1001
_SERVER_ERROR_RESPONSE = 0b1111

# message-type-specific flags
_FLAG_POS_SEQUENCE = 0b0001   # header 后 4 字节为正 sequence number
_FLAG_LAST_NO_SEQ = 0b0010    # 最后一包（负包），header 后无 sequence
_FLAG_NONE = 0b0000


@dataclass(frozen=True)
class ASRResult:
    text: str  # cumulative recognized text so far
    is_final: bool


class VolcASRError(RuntimeError):
    pass


def _build_header(message_type: int, flags: int, serialization: int = _JSON_SERIALIZATION) -> bytearray:
    hdr = bytearray(4)
    hdr[0] = (_PROTOCOL_VERSION << 4) | _HEADER_SIZE
    hdr[1] = (message_type << 4) | flags
    hdr[2] = (serialization << 4) | _GZIP_COMPRESSION
    hdr[3] = 0x00
    return hdr


def _full_client_request(payload: dict) -> bytes:
    """First frame: JSON config, gzipped, with a positive sequence number."""
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    pkt = _build_header(_FULL_CLIENT_REQUEST, _FLAG_POS_SEQUENCE)
    pkt.extend((1).to_bytes(4, "big", signed=True))  # sequence = 1
    pkt.extend(len(body).to_bytes(4, "big"))
    pkt.extend(body)
    return bytes(pkt)


def _audio_request(audio: bytes, *, is_last: bool) -> bytes:
    """Audio-only frame: raw (non-serialized) gzipped audio. Last packet flagged."""
    body = gzip.compress(audio)
    flags = _FLAG_LAST_NO_SEQ if is_last else _FLAG_NONE
    pkt = _build_header(_AUDIO_ONLY_REQUEST, flags, serialization=_NO_SERIALIZATION)
    pkt.extend(len(body).to_bytes(4, "big"))
    pkt.extend(body)
    return bytes(pkt)


def _safe_json(body: bytes) -> dict:
    """Decode a payload to JSON, tolerating empty / non-JSON trailing frames."""
    if not body:
        return {}
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _maybe_gunzip(body: bytes, compression: int) -> bytes:
    """Decompress if gzip flagged, but tolerate servers that send plain JSON
    despite the gzip bit (observed on bigmodel_async)."""
    if not body:
        return body
    if compression == _GZIP_COMPRESSION:
        try:
            return gzip.decompress(body)
        except (OSError, gzip.BadGzipFile):
            return body  # already uncompressed
    return body


def _parse_response(data: bytes) -> dict:
    """Parse a server frame.

    Layout for full_server_response: Header(4B) + Sequence(4B) + PayloadSize(4B) + Payload.
    For error response: Header(4B) + ErrorCode(4B) + MsgSize(4B) + Msg.
    """
    header_size = data[0] & 0x0F
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    compression = data[2] & 0x0F
    offset = header_size * 4
    result: dict = {"message_type": message_type, "flags": flags}

    if message_type == _FULL_SERVER_RESPONSE:
        sequence = int.from_bytes(data[offset:offset + 4], "big", signed=True)
        offset += 4
        result["sequence"] = sequence
        # negative sequence => last package
        result["is_last"] = sequence < 0 or bool(flags & _FLAG_LAST_NO_SEQ)
        size = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
        body = _maybe_gunzip(data[offset:offset + size], compression)
        result["payload"] = _safe_json(body)
    elif message_type == _SERVER_ERROR_RESPONSE:
        result["error_code"] = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
        size = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
        body = _maybe_gunzip(data[offset:offset + size], compression)
        result["error_msg"] = body.decode("utf-8", errors="replace")
    return result


class VolcStreamASR:
    """Streaming ASR client over Volcengine WebSocket (bigmodel sauc)."""

    def __init__(self, settings: Settings):
        has_new = bool(settings.volc_asr_api_key)
        has_old = bool(settings.volc_asr_app_key and settings.volc_asr_access_key)
        if not (has_new or has_old):
            raise VolcASRError(
                "Volcengine ASR requires FLOPPY_VOLC_ASR_API_KEY (新版控制台), "
                "or FLOPPY_VOLC_ASR_APP_KEY + FLOPPY_VOLC_ASR_ACCESS_KEY (旧版控制台)"
            )
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        headers = {
            "X-Api-Resource-Id": self._settings.volc_asr_resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
            "X-Api-Request-Id": str(uuid.uuid4()),
        }
        if self._settings.volc_asr_api_key:  # 新版控制台
            headers["X-Api-Key"] = self._settings.volc_asr_api_key
        else:  # 旧版控制台
            headers["X-Api-App-Key"] = self._settings.volc_asr_app_key or ""
            headers["X-Api-Access-Key"] = self._settings.volc_asr_access_key or ""
        return headers

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
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,   # needed for definite (sentence finality)
                "result_type": "single",   # incremental results
                "end_window_size": 800,    # 800ms 静音判停 -> definite=true
            },
        }

    @staticmethod
    def _extract(payload: dict) -> tuple[str, bool]:
        """Return (cumulative_text, is_sentence_final).

        result is a dict: {"text": "...", "utterances": [{"definite": bool, ...}]}.
        is_final is true when the latest utterance is marked definite.
        """
        result = payload.get("result")
        if not isinstance(result, dict):
            return "", False
        text = str(result.get("text") or "")
        definite = False
        utterances = result.get("utterances")
        if isinstance(utterances, list) and utterances:
            definite = bool(utterances[-1].get("definite"))
        return text, definite

    async def stream_recognize(self, audio_iter: AsyncIterator[bytes]) -> AsyncIterator[ASRResult]:
        """Recognize a stream of PCM audio chunks, yielding cumulative results.

        Sends the config frame, then pumps audio while concurrently receiving
        results. Each yielded ASRResult.text is cumulative; is_final marks a
        finalized sentence (definite) or the last packet.
        """
        import asyncio

        async with websockets.connect(self._settings.volc_asr_ws_url, additional_headers=self._headers()) as ws:
            await ws.send(_full_client_request(self._init_payload()))

            queue: asyncio.Queue[ASRResult | None] = asyncio.Queue()

            async def _send() -> None:
                # Stream each chunk as it arrives; mark the final one. We can't
                # know which chunk is last until the iterator ends, so we hold
                # one chunk back and flush it as the last packet.
                prev: bytes | None = None
                sent_any = False
                async for chunk in audio_iter:
                    if prev is not None:
                        await ws.send(_audio_request(prev, is_last=False))
                        sent_any = True
                    prev = chunk
                if prev is not None:
                    await ws.send(_audio_request(prev, is_last=True))
                elif not sent_any:
                    await ws.send(_audio_request(b"", is_last=True))

            async def _recv() -> None:
                last_text = ""
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
                        text, definite = self._extract(parsed.get("payload") or {})
                        is_last = parsed.get("is_last", False)
                        # The final (negative) packet often carries an empty
                        # payload — don't let it wipe the text we already have.
                        if text:
                            last_text = text
                        if text or definite:
                            await queue.put(ASRResult(text=text, is_final=definite))
                        if is_last:
                            # Emit a final marker carrying the best text so far.
                            await queue.put(ASRResult(text=last_text, is_final=True))
                            break
                except websockets.ConnectionClosed:
                    if last_text:
                        await queue.put(ASRResult(text=last_text, is_final=True))
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
