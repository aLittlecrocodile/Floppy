#!/usr/bin/env python3
"""AI Query Planner smoke test.

Requires env vars:
  FLOPPY_QUERY_PLANNER=ai
  FLOPPY_QUERY_PLANNER_API_KEY=<your-key>
  FLOPPY_QUERY_PLANNER_BASE_URL=<your-oneapi-url>  (optional)

Usage:
  .venv/bin/python scripts/ai_planner_smoke.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path so floppy_backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import app


def main():
    settings = get_settings()
    print(f"planner={settings.query_planner} model={settings.query_planner_model} timeout={settings.query_planner_timeout_sec}s max_tokens={settings.query_planner_max_tokens}")

    with TestClient(app) as client:
        # Seed
        seed = client.post("/admin/seed")
        assert seed.status_code == 200, f"seed failed: {seed.text}"
        print(f"seeded {seed.json()['created_or_updated']} assets")

        # Profile
        profile_payload = {
            "audio_type_preferences": ["meditation", "white_noise"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 15,
            "stress_level": "high",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 40,
            "mood_tags": ["anxiety_relief"],
        }
        resp = client.put("/users/u_smoke/profile", json=profile_payload)
        assert resp.status_code == 200

        # Decide
        request_text = "我今晚压力很大，一直胡思乱想，想听一个温柔的呼吸冥想，最好有轻微雨声，15分钟"
        decide = client.post("/agent/decide", json={"user_id": "u_smoke", "request_text": request_text})

        if decide.status_code == 429:
            print("BUDGET EXCEEDED — reset or increase FLOPPY_DAILY_GENERATE_COUNT")
            sys.exit(1)
        assert decide.status_code == 200, f"decide failed {decide.status_code}: {decide.text}"

        body = decide.json()
        print(f"\naction: {body['action']}")
        print(f"planner_meta: {json.dumps(body.get('planner_meta'), ensure_ascii=False)}")
        print(f"best_score: {body['search']['best_score']}")
        print(f"hit: {body['search']['hit']}")
        if body.get("asset"):
            print(f"asset: {body['asset']['title']} ({body['asset']['id']})")
        if body.get("job_id"):
            print(f"job_id: {body['job_id']}")
        print(f"reasons: {body['reasons']}")


if __name__ == "__main__":
    main()
