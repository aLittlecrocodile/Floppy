#!/usr/bin/env python3
"""端到端语音对话 WebSocket 测试客户端。

从一个 wav 文件（16k/mono/16bit）按 200ms 推流到 /voice/ws，打印服务端回传的
识别/助手文本事件，并把回传的 TTS 音频拼接落盘。用于全链路联调与首响延迟测量。

用法:
  # 先启动服务: .venv/bin/uvicorn floppy_backend.main:app --port 8000
  .venv/bin/python scripts/voice_ws_client.py path/to/audio.wav
  .venv/bin/python scripts/voice_ws_client.py audio.wav --url ws://127.0.0.1:8000/voice/ws --token secret
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import websockets


async def _send_audio(ws, wav_path: Path, chunk_ms: int = 200) -> None:
    with wave.open(str(wav_path), "rb") as wav:
        rate = wav.getframerate()
        frames_per_chunk = int(rate * chunk_ms / 1000)
        while True:
            frames = wav.readframes(frames_per_chunk)
            if not frames:
                break
            await ws.send(frames)
            await asyncio.sleep(chunk_ms / 1000)
    await ws.send(json.dumps({"type": "stop"}))


async def main() -> int:
    parser = argparse.ArgumentParser(description="语音对话 WS 测试客户端")
    parser.add_argument("wav", type=Path, help="输入 wav (16k/mono/16bit)")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/voice/ws")
    parser.add_argument("--token", default=None, help="FLOPPY_VOICE_WS_TOKEN")
    parser.add_argument("--out", default="storage/voice_ws_client/reply.mp3", type=Path)
    args = parser.parse_args()

    if not args.wav.exists():
        print(f"文件不存在: {args.wav}", file=sys.stderr)
        return 2

    url = args.url + (f"?token={args.token}" if args.token else "")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    audio = bytearray()
    started = time.perf_counter()
    first_audio_at: float | None = None

    async with websockets.connect(url) as ws:
        sender = asyncio.create_task(_send_audio(ws, args.wav))
        try:
            while True:
                message = await ws.recv()
                if isinstance(message, bytes):
                    if first_audio_at is None:
                        first_audio_at = time.perf_counter() - started
                        print(f"⏱  首个回复音频延迟: {first_audio_at * 1000:.0f}ms")
                    audio.extend(message)
                    continue
                event = json.loads(message)
                etype = event.get("type")
                if etype == "user_text":
                    tag = "FINAL" if event.get("is_final") else "partial"
                    print(f"🗣  [{tag}] {event.get('text')}")
                elif etype == "assistant_text":
                    print(f"🤖 {event.get('text')}")
                elif etype == "turn_end":
                    print("— turn end —")
                elif etype == "error":
                    print(f"❌ {event.get('text')}", file=sys.stderr)
                    break
        except websockets.ConnectionClosed:
            pass
        finally:
            sender.cancel()

    if audio:
        args.out.write_bytes(bytes(audio))
        print(f"✅ 回复音频 {len(audio)} bytes -> {args.out}")
    else:
        print("⚠️ 未收到回复音频")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
