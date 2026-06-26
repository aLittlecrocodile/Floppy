#!/usr/bin/env python3
"""MiniMax 流式 TTS (WebSocket) 冒烟测试。

独立验证 wss://api.minimaxi.com/ws/v1/t2a_v2 的 task_start/continue/finish 协议，
把流式返回的音频片段拼接落盘。

用法:
  export FLOPPY_MINIMAX_API_KEY=...
  .venv/bin/python scripts/minimax_stream_tts_smoke.py
  .venv/bin/python scripts/minimax_stream_tts_smoke.py --text "你好呀，今晚睡得好吗？"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floppy_backend.config import get_settings  # noqa: E402
from floppy_backend.providers.minimax_stream_tts import MiniMaxStreamTTS  # noqa: E402

DEFAULT_CHUNKS = [
    "你好呀，欢迎回来。",
    "今晚就让我陪着你，慢慢放松下来。",
    "把呼吸放轻一点，我们一起静下来。",
]


async def _feed(chunks: list[str]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk


async def main() -> int:
    parser = argparse.ArgumentParser(description="MiniMax 流式 TTS 冒烟测试")
    parser.add_argument("--text", default=None, help="单段自定义文本，不传则用内置多段")
    parser.add_argument("--voice-style", default="warm_female")
    parser.add_argument("--out", default="storage/stream_tts_smoke/out.mp3", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.minimax_api_key:
        print("缺少 FLOPPY_MINIMAX_API_KEY", file=sys.stderr)
        return 2

    chunks = [args.text] if args.text else DEFAULT_CHUNKS
    tts = MiniMaxStreamTTS(settings)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    audio = bytearray()
    first_chunk_at: float | None = None
    started = time.perf_counter()
    try:
        async for piece in tts.stream_synthesize(_feed(chunks), voice_style=args.voice_style):
            if first_chunk_at is None:
                first_chunk_at = time.perf_counter() - started
                print(f"首个音频片段延迟: {first_chunk_at * 1000:.0f}ms")
            audio.extend(piece)
    except Exception as exc:  # noqa: BLE001 — 冒烟脚本，直接打印
        print(f"❌ 失败: {exc}", file=sys.stderr)
        return 1

    if not audio:
        print("⚠️ 请求成功但没拿到音频", file=sys.stderr)
        return 1

    args.out.write_bytes(bytes(audio))
    print(f"✅ {len(audio)} bytes -> {args.out}  (总耗时 {(time.perf_counter() - started):.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
