from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure repo root is importable when the script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import app


def main() -> int:
    settings = get_settings()
    if settings.minimax_api_key and not os.getenv("FLOPPY_MINIMAX_API_KEY"):
        os.environ["FLOPPY_MINIMAX_API_KEY"] = settings.minimax_api_key

    required = ["FLOPPY_MINIMAX_API_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print(f"missing env: {', '.join(missing)}")
        return 2

    os.environ.setdefault("FLOPPY_AUDIO_PROVIDER", "minimax")
    os.environ.setdefault("FLOPPY_MINIMAX_MODEL", "speech-2.8-hd")
    os.environ.setdefault("FLOPPY_MINIMAX_VOICE_ID", "Chinese (Mandarin)_Warm_Bestie")
    os.environ.setdefault("FLOPPY_DATABASE_PATH", f"data/minimax_smoke_{datetime.now().strftime('%Y%m%d%H%M%S')}.db")
    os.environ.setdefault("FLOPPY_STORAGE_DIR", "storage/audio")
    get_settings.cache_clear()

    with TestClient(app, raise_server_exceptions=False) as client:
        profile = {
            "audio_type_preferences": ["story"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 5,
            "stress_level": "medium",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 25,
            "mood_tags": ["gentle"],
        }
        profile_resp = client.put("/users/u_minimax_smoke/profile", json=profile)
        print("profile_status", profile_resp.status_code)
        if profile_resp.status_code >= 400:
            print(profile_resp.text[:1000])
            return 1

        request = {
            "request_text": f"请用温柔女声讲一个很短的海边雨夜睡前故事，轻柔雨声，5分钟。实验编号{datetime.now().strftime('%H%M%S')}",
            "force_generate": True,
        }
        response = client.post("/users/u_minimax_smoke/generate-audio", json=request)
        print("generate_status", response.status_code)
        if response.status_code >= 400:
            print(response.text[:2000])
            return 1

        body = response.json()
        print("job_id", body["job_id"])
        print("status", body["status"])
        print("match_type", body["match_type"])

        job_resp = client.get(f"/generation-jobs/{body['job_id']}")
        job = job_resp.json()
        print("provider", job.get("provider"))
        print("provider_model", job.get("provider_model"))
        print("provider_status", job.get("provider_status"))
        print("usage_characters", job.get("usage_characters"))
        print("estimated_cost_usd", job.get("estimated_cost_usd"))
        print("error_code", job.get("error_code"))
        print("error_message", job.get("error_message"))
        print("script_chars", job.get("script_chars"))

        if body["status"] != "succeeded":
            return 1

        audio_url = body["asset"]["playback_url"].replace("http://127.0.0.1:8000", "")
        audio = client.get(audio_url)
        print("audio_status", audio.status_code)
        print("audio_content_type", audio.headers.get("content-type"))
        print("audio_bytes", len(audio.content))
        return 0 if audio.status_code == 200 and audio.content else 1


if __name__ == "__main__":
    raise SystemExit(main())
