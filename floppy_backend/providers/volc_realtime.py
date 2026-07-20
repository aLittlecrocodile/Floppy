"""豆包端到端实时语音大模型（Realtime API）客户端。

协议: wss://openspeech.bytedance.com/api/v3/realtime/dialogue
文档: https://www.volcengine.com/docs/6561/1594356
帧格式: [4B header][4B event][(session事件) 4B sid_size + sid][4B payload_size][payload]
header = [0x11, msg_type<<4|flags, serialization<<4|compression, 0x00]
鉴权: 新版控制台单 X-Api-Key（与流式 ASR 共用凭证），Resource-Id 固定 volc.speech.dialog
"""

from __future__ import annotations

import json
import struct
import uuid
from dataclasses import dataclass

from floppy_backend.config import Settings

REALTIME_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
RESOURCE_ID = "volc.speech.dialog"
FIXED_APP_KEY = "PlgvMymc7f3tQnJ6"  # 文档规定的固定值

# 客户端事件
EV_START_CONNECTION = 1
EV_FINISH_CONNECTION = 2
EV_START_SESSION = 100
EV_FINISH_SESSION = 102
EV_TASK_REQUEST = 200  # 上行音频
EV_CHAT_TEXT_QUERY = 501

# 服务端事件
EV_CONNECTION_STARTED = 50
EV_CONNECTION_FAILED = 51
EV_SESSION_STARTED = 150
EV_SESSION_FINISHED = 152
EV_SESSION_FAILED = 153
EV_TTS_SENTENCE_START = 350
EV_TTS_RESPONSE = 352  # 下行音频（binary payload）
EV_TTS_ENDED = 359
EV_ASR_INFO = 450      # 识别到用户开口（用于打断播报）
EV_ASR_RESPONSE = 451
EV_ASR_ENDED = 459
EV_CHAT_RESPONSE = 550
EV_CHAT_ENDED = 559
EV_DIALOG_ERROR = 599

_CONNECT_CLASS_EVENTS = {EV_START_CONNECTION, EV_FINISH_CONNECTION, EV_CONNECTION_STARTED, EV_CONNECTION_FAILED, 52}

_MSG_FULL_CLIENT = 0b0001
_MSG_AUDIO_CLIENT = 0b0010
_FLAG_EVENT = 0b0100
_SER_RAW = 0b0000
_SER_JSON = 0b0001


def _frame(event: int, payload: bytes, *, session_id: str | None = None, msg_type: int = _MSG_FULL_CLIENT, serialization: int = _SER_JSON) -> bytes:
    buf = bytearray([0x11, (msg_type << 4) | _FLAG_EVENT, (serialization << 4) | 0x00, 0x00])
    buf += struct.pack(">i", event)
    if session_id is not None:
        sid = session_id.encode("utf-8")
        buf += struct.pack(">I", len(sid)) + sid
    buf += struct.pack(">I", len(payload)) + payload
    return bytes(buf)


def start_connection_frame() -> bytes:
    return _frame(EV_START_CONNECTION, b"{}")


def finish_connection_frame() -> bytes:
    return _frame(EV_FINISH_CONNECTION, b"{}")


def start_session_frame(session_id: str, config: dict) -> bytes:
    return _frame(EV_START_SESSION, json.dumps(config, ensure_ascii=False).encode("utf-8"), session_id=session_id)


def finish_session_frame(session_id: str) -> bytes:
    return _frame(EV_FINISH_SESSION, b"{}", session_id=session_id)


def audio_frame(session_id: str, pcm: bytes) -> bytes:
    return _frame(EV_TASK_REQUEST, pcm, session_id=session_id, msg_type=_MSG_AUDIO_CLIENT, serialization=_SER_RAW)


def chat_text_query_frame(session_id: str, content: str) -> bytes:
    return _frame(EV_CHAT_TEXT_QUERY, json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"), session_id=session_id)


@dataclass(frozen=True)
class ServerEvent:
    event: int
    session_id: str | None
    payload: bytes
    is_json: bool

    def json(self) -> dict:
        try:
            return json.loads(self.payload.decode("utf-8")) if self.payload else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}


def parse_server_frame(data: bytes) -> ServerEvent:
    serialization = data[2] >> 4
    flags = data[1] & 0x0F
    pos = 4
    event = None
    if flags & _FLAG_EVENT:
        event = struct.unpack(">i", data[pos:pos + 4])[0]
        pos += 4
    session_id = None
    if event is not None and event not in _CONNECT_CLASS_EVENTS:
        sid_len = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4
        session_id = data[pos:pos + sid_len].decode("utf-8", errors="replace")
        pos += sid_len
    payload_len = struct.unpack(">I", data[pos:pos + 4])[0]
    pos += 4
    payload = data[pos:pos + payload_len]
    return ServerEvent(event=event or 0, session_id=session_id, payload=payload, is_json=serialization == _SER_JSON)


# Unwind 人设 —— O2.0 版本（model 1.2.1.1）支持 bot_name/system_role/speaking_style
FLOPPY_SYSTEM_ROLE = (
    "你是 Unwind，一个深夜陪伴用户入睡的 AI 伙伴。用户通常躺在床上、准备睡觉，"
    "可能有些疲惫、焦虑或者睡不着。你的任务是陪伴、倾听、安抚，帮助用户放松下来。"
    "不要讨论刺激、兴奋或令人紧张的话题；用户倾诉时先共情，不要急着给建议。"
    "当用户表达想听某种音频、故事、白噪音或音乐时：告诉 TA 你已经去准备了，"
    "做好了会马上叫 TA，然后继续温柔地陪 TA 聊天；绝对不要假装你正在播放任何音频。"
)
FLOPPY_SPEAKING_STYLE = "你说话轻声细语、语速缓慢、温柔安静，句子简短，像深夜坐在床边的朋友。"


def session_config(settings: Settings, *, speaker: str | None = None, dialog_id: str | None = None) -> dict:
    return {
        "asr": {
            "extra": {
                "end_smooth_window_ms": 1200,
            },
        },
        "tts": {
            "speaker": speaker or settings.volc_realtime_speaker,
            "audio_config": {
                "channel": 1,
                "format": "pcm_s16le",  # 24kHz s16le —— Android AudioTrack 直接播
                "sample_rate": 24000,
            },
        },
        "dialog": {
            "bot_name": "Unwind",
            "system_role": FLOPPY_SYSTEM_ROLE,
            "speaking_style": FLOPPY_SPEAKING_STYLE,
            "dialog_id": dialog_id or "",
            "extra": {
                "strict_audit": False,
                "input_mod": "keep_alive",  # 麦克风可能静音（对方在听音频）
                "model": settings.volc_realtime_model,
            },
        },
    }


def upstream_headers(settings: Settings) -> dict[str, str]:
    if not settings.volc_asr_api_key:
        raise RuntimeError("FLOPPY_VOLC_ASR_API_KEY is required for the realtime voice call")
    return {
        "X-Api-Key": settings.volc_asr_api_key,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-App-Key": FIXED_APP_KEY,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
