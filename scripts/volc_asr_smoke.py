#!/usr/bin/env python3
"""火山引擎大模型流式 ASR 冒烟测试。

读取一个 wav 文件（16k/mono/16bit 最佳），按 200ms 切片喂进流式识别，打印
增量识别结果与最终文本。

用法:
  export FLOPPY_VOLC_ASR_API_KEY=...
  # 或旧版 app/access 双 Key:
  export FLOPPY_VOLC_ASR_APP_KEY=...
  export FLOPPY_VOLC_ASR_ACCESS_KEY=...
  .venv/bin/python scripts/volc_asr_smoke.py path/to/audio.wav
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floppy_backend.config import get_settings  # noqa: E402
from floppy_backend.providers.volc_asr import VolcStreamASR  # noqa: E402


async def _wav_chunks(path: Path, chunk_ms: int = 200) -> AsyncIterator[bytes]:
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        frames_per_chunk = int(rate * chunk_ms / 1000)
        while True:
            frames = wav.readframes(frames_per_chunk)
            if not frames:
                break
            yield frames
            await asyncio.sleep(chunk_ms / 1000)  # simulate realtime pacing


async def main() -> int:
    parser = argparse.ArgumentParser(description="火山流式 ASR 冒烟测试")
    parser.add_argument("wav", type=Path, help="输入 wav 文件 (16k/mono/16bit)")
    args = parser.parse_args()

    if not args.wav.exists():
        print(f"文件不存在: {args.wav}", file=sys.stderr)
        return 2

    settings = get_settings()
    try:
        asr = VolcStreamASR(settings)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    final_text = ""
    try:
        async for result in asr.stream_recognize(_wav_chunks(args.wav)):
            marker = "FINAL" if result.is_final else "partial"
            print(f"[{marker}] {result.text}")
            if result.is_final:
                final_text = result.text
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 识别失败: {exc}", file=sys.stderr)
        return 1

    print(f"\n✅ 最终识别: {final_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
