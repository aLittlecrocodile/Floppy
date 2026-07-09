from __future__ import annotations

from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import app, state
from floppy_backend.models import AudioType


def _configure_tmp_app(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()


def _profile_payload() -> dict:
    return {
        "audio_type_preferences": ["meditation", "white_noise", "story"],
        "voice_preferences": ["warm_female"],
        "background_preferences": ["rain_soft"],
        "duration_preference_min": 10,
        "stress_level": "medium",
        "anxiety_level": "medium",
        "avg_sleep_latency_min": 25,
        "mood_tags": ["calm"],
    }


def test_generation_job_smoke(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.put("/users/u_smoke/profile", json=_profile_payload()).status_code == 200

        created = client.post(
            "/users/u_smoke/generation-jobs",
            json={
                "request_text": "请生成一段温柔女声的呼吸冥想，雨声背景，10分钟",
                "force_generate": True,
            },
        )
        assert created.status_code == 202
        body = created.json()
        assert body["job_id"]
        assert body["match_type"] in {"queued", "in_flight"}

        job = client.get(f"/generation-jobs/{body['job_id']}")
        assert job.status_code == 200
        job_body = job.json()
        assert job_body["status"] == "succeeded"
        # Playback URLs are minted from the request's own host (stale-IP fix).
        assert job_body["asset"]["playback_url"].startswith("http://testserver/audio/")
        assert job_body["script"]["script_text"]


def test_agent_decide_response_contract_smoke(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200
        assert client.put("/users/u_agent_smoke/profile", json=_profile_payload()).status_code == 200

        response = client.post(
            "/agent/decide",
            json={
                "user_id": "u_agent_smoke",
                "request_text": "今晚想听温柔女声雨声冥想",
                "generation_allowed": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["action"] in {"play_asset", "generate_job", "remix_current", "no_match"}
        assert body["normalized_request"]["intent"] in {item.value for item in AudioType}
        assert isinstance(body["reasons"], list)
        assert "search" in body

        if body["asset"]:
            assert body["asset"]["playback_url"].startswith("http://testserver/audio/")
        if body["job_id"]:
            job = client.get(f"/generation-jobs/{body['job_id']}")
            assert job.status_code == 200


def test_remix_session_smoke(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200
        assets = state.repository.list_assets(limit=20)
        foreground = next((asset for asset in assets if asset.type != AudioType.WHITE_NOISE), assets[0])

        created = client.post(
            "/remix/sessions",
            json={
                "foreground_asset_id": foreground.id,
                "intent": "add_background",
                "sound_type": "rain",
                "mix_params": {"background_volume": 0.25},
            },
        )
        assert created.status_code == 202
        session_id = created.json()["id"]

        session = client.get(f"/remix/sessions/{session_id}")
        assert session.status_code == 200
        assert session.json()["id"] == session_id
