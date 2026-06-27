#!/usr/bin/env python3
"""把真实音频素材包导入 Floppy storage。

读取素材包的 manifest.csv，将每条 mp3 复制到 storage/audio/real/<category>/<idx>.mp3，
object_key 用 idx 前缀避免中文文件名的 URL 编码问题。幂等：已存在则跳过。

用法:
  .venv/bin/python scripts/import_real_audio.py
  .venv/bin/python scripts/import_real_audio.py --src /path/to/Floppy_audio_v3
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floppy_backend.config import get_settings  # noqa: E402

DEFAULT_SRC = Path("/Users/aooway/Desktop/Floppy_audio_v3")


def object_key_for(idx: str, category: str) -> str:
    return f"real/{category}/{int(idx):02d}.mp3"


def main() -> int:
    parser = argparse.ArgumentParser(description="导入真实音频素材到 storage")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="素材包目录（含 manifest.csv）")
    args = parser.parse_args()

    manifest = args.src / "manifest.csv"
    if not manifest.exists():
        print(f"manifest 不存在: {manifest}", file=sys.stderr)
        return 2

    settings = get_settings()
    storage_dir = settings.storage_dir
    copied = skipped = missing = 0

    with manifest.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            src_file = args.src / row["file"]
            object_key = object_key_for(row["idx"], row["category"])
            dest = storage_dir / object_key
            if not src_file.exists():
                print(f"  ⚠️ 源文件缺失: {src_file}")
                missing += 1
                continue
            if dest.exists() and dest.stat().st_size == src_file.stat().st_size:
                skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)
            print(f"  ✅ {row['idx']:>2} {row['title']} -> {object_key}")
            copied += 1

    print(f"\n完成: 复制 {copied}, 跳过 {skipped}, 缺失 {missing} -> {storage_dir}/real/")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
