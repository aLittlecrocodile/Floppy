#!/usr/bin/env python3
"""一次性清理联调测试期产生的 ondemand 垃圾资产（DB 行 + 音频文件）。

保留：real_asset 真实素材、prewarm_user 官方预热、用户上传（uploads/）、remix。
清除：测试用户（demo_user / doc_check_user / voice_demo_user / mobile_user /
android_* 等）在 ondemand/ 下的生成产物，连同引用它们的 playback_history /
events 行，并把 generation_jobs.asset_id 置空（保留任务记录本身）。

用法:
  .venv/bin/python scripts/cleanup_test_assets.py            # dry-run，只打印
  .venv/bin/python scripts/cleanup_test_assets.py --apply    # 真删
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floppy_backend.config import get_settings  # noqa: E402
from floppy_backend.db import connect, initialize  # noqa: E402

KEEP_PREFIX = "ondemand/prewarm_user/"


def main() -> int:
    parser = argparse.ArgumentParser(description="清理测试期垃圾资产")
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认 dry-run）")
    args = parser.parse_args()

    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)

    rows = conn.execute(
        """SELECT id, title, object_key FROM audio_assets
           WHERE created_by = 'ondemand' AND object_key NOT LIKE ?""",
        (KEEP_PREFIX + "%",),
    ).fetchall()
    if not rows:
        print("没有需要清理的资产。")
        return 0

    ids = [r["id"] for r in rows]
    marks = ",".join("?" * len(ids))
    history_n = conn.execute(f"SELECT COUNT(*) n FROM playback_history WHERE asset_id IN ({marks})", ids).fetchone()["n"]
    events_n = conn.execute(f"SELECT COUNT(*) n FROM events WHERE asset_id IN ({marks})", ids).fetchone()["n"]
    jobs_n = conn.execute(f"SELECT COUNT(*) n FROM generation_jobs WHERE asset_id IN ({marks})", ids).fetchone()["n"]

    print(f"将清理 {len(rows)} 条资产（连带 history {history_n} 条、events {events_n} 条，解除 jobs 引用 {jobs_n} 条）：")
    for r in rows:
        print(f"  {r['id']}  {r['title'][:24]:<26} {r['object_key']}")

    if not args.apply:
        print("\ndry-run 完成。确认无误后加 --apply 执行。")
        return 0

    storage_dir = settings.storage_dir.resolve()
    with conn:  # single transaction
        conn.execute(f"DELETE FROM playback_history WHERE asset_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM events WHERE asset_id IN ({marks})", ids)
        conn.execute(f"UPDATE generation_jobs SET asset_id = NULL WHERE asset_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM remix_jobs WHERE voice_asset_id IN ({marks}) OR output_asset_id IN ({marks})", ids + ids)
        conn.execute(f"DELETE FROM audio_assets WHERE id IN ({marks})", ids)

    removed_files = 0
    for r in rows:
        base = storage_dir / r["object_key"]
        stem, suffix = base.with_suffix("").name, base.suffix
        # 连同混音的 _voice/_music 兄弟文件一起删
        for candidate in [base, base.parent / f"{stem}_voice{suffix}", base.parent / f"{stem}_music{suffix}"]:
            if candidate.exists():
                candidate.unlink()
                removed_files += 1

    print(f"\n✅ 已删除 {len(rows)} 条资产、{removed_files} 个音频文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
