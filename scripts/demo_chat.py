#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import app


def main() -> int:
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        text = input("你想听什么助眠音频？\n> ").strip()
    if not text:
        print("没有输入内容")
        return 2

    settings = get_settings()
    print(f"AI planner={settings.query_planner}:{settings.query_planner_model}")
    print(f"audio_provider={settings.audio_provider}:{settings.minimax_model if settings.audio_provider == 'minimax' else 'local'}")

    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/admin/seed")
        client.put(
            "/users/demo_user/profile",
            json={
                "audio_type_preferences": ["meditation", "white_noise", "story"],
                "voice_preferences": ["warm_female"],
                "background_preferences": ["rain_soft"],
                "duration_preference_min": 15,
                "stress_level": "high",
                "anxiety_level": "high",
                "avg_sleep_latency_min": 40,
                "mood_tags": ["anxiety_relief"],
            },
        )

        decide = client.post(
            "/agent/decide",
            json={"user_id": "demo_user", "request_text": text, "generation_allowed": True},
        )
        if decide.status_code >= 400:
            print(decide.text)
            return 1

        body = decide.json()
        print("\nDECIDE")
        print(json.dumps({
            "action": body.get("action"),
            "planner_meta": body.get("planner_meta"),
            "best_score": body.get("search", {}).get("best_score"),
            "reasons": body.get("reasons"),
        }, ensure_ascii=False, indent=2))

        if body.get("asset"):
            print("\nAUDIO_URL")
            print(body["asset"]["playback_url"])
            return 0

        job_id = body.get("job_id")
        if not job_id:
            print("\n没有命中音频，也没有创建生成任务")
            return 1

        print(f"\n生成任务: {job_id}")
        for _ in range(90):
            job_resp = client.get(f"/generation-jobs/{job_id}")
            job = job_resp.json()
            status = job.get("status")
            if status in {"succeeded", "failed"}:
                print("\nJOB")
                print(json.dumps({
                    "status": status,
                    "provider": job.get("provider"),
                    "provider_model": job.get("provider_model"),
                    "provider_status": job.get("provider_status"),
                    "error_code": job.get("error_code"),
                    "error_message": job.get("error_message"),
                }, ensure_ascii=False, indent=2))
                if status == "succeeded" and job.get("asset"):
                    print("\nAUDIO_URL")
                    print(job["asset"]["playback_url"])
                    return 0
                return 1
            time.sleep(1)

        print("生成任务超时")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
