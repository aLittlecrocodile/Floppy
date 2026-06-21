from __future__ import annotations

import threading

from fastapi.testclient import TestClient
import pytest

from floppy_backend.config import get_settings
from floppy_backend.main import app
from floppy_backend.providers.audio import ProviderConfigurationError, build_audio_provider


def test_seed_profile_recommend_generate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200

        seed = client.post("/admin/seed")
        assert seed.status_code == 200
        assert seed.json()["created_or_updated"] >= 8

        profile_payload = {
            "audio_type_preferences": ["story", "white_noise"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 15,
            "stress_level": "high",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 35,
            "mood_tags": ["anxiety_relief"],
        }
        profile = client.put("/users/u_test/profile", json=profile_payload)
        assert profile.status_code == 200
        assert profile.json()["segment"] == "anxiety_relief"

        recommendations = client.get("/users/u_test/recommendations?limit=3")
        assert recommendations.status_code == 200
        body = recommendations.json()
        assert len(body) == 3
        assert body[0]["asset"]["playback_url"].startswith("http://127.0.0.1:8000/audio/")
        assert body[0]["reasons"]

        request_payload = {"request_text": "我想听一个温柔女声讲海边书店的睡前故事，背景有轻微雨声，15分钟"}
        first = client.post("/users/u_test/generate-audio", json=request_payload)
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["status"] == "succeeded"
        assert first_body["asset"]["playback_url"]

        first_job = client.get(f"/generation-jobs/{first_body['job_id']}")
        assert first_job.status_code == 200
        first_job_body = first_job.json()
        assert first_job_body["script"]["script_text"].count("<#") >= 5
        assert first_job_body["script_hash"] == first_job_body["script"]["script_hash"]
        assert first_job_body["script_chars"] == len(first_job_body["script"]["script_text"])
        assert first_job_body["provider_model"] == "local_tone"
        assert first_job_body["provider_status"] == "succeeded"

        second = client.post("/users/u_test/generate-audio", json=request_payload)
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["cache_hit"] is True
        assert second_body["asset"]["id"] == first_body["asset"]["id"]

        audio_url = first_body["asset"]["playback_url"].replace("http://127.0.0.1:8000", "")
        audio = client.get(audio_url)
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/wav")

        traversal = client.get("/audio/../pyproject.toml")
        assert traversal.status_code in {400, 404}

        event = client.post(
            "/users/u_test/events",
            json={"event_type": "audio_play_started", "asset_id": first_body["asset"]["id"], "payload": {"source": "test"}},
        )
        assert event.status_code == 200
        assert event.json()["event_id"].startswith("evt_")


def test_async_generation_job_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_male"],
            "background_preferences": ["forest_night"],
            "duration_preference_min": 10,
            "stress_level": "medium",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 45,
            "mood_tags": ["safe"],
        }
        assert client.put("/users/u_async/profile", json=profile_payload).status_code == 200

        request_payload = {
            "request_text": "请生成一个温柔男声的呼吸冥想，引导我放松，森林背景，10分钟",
            "force_generate": True,
        }
        created = client.post("/users/u_async/generation-jobs", json=request_payload)
        assert created.status_code == 202
        created_body = created.json()
        assert created_body["cache_hit"] is False
        assert created_body["match_type"] == "queued"
        assert created_body["asset"] is None

        job = client.get(f"/generation-jobs/{created_body['job_id']}")
        assert job.status_code == 200
        job_body = job.json()
        assert job_body["status"] == "succeeded"
        assert job_body["asset"]["playback_url"].startswith("http://127.0.0.1:8000/audio/")
        assert job_body["latency_ms"] is not None
        assert job_body["script"]["pause_density"] == "high"
        assert "<#4#>" in job_body["script"]["script_text"]

        request_payload["force_generate"] = False
        cached = client.post("/users/u_async/generation-jobs", json=request_payload)
        assert cached.status_code == 202
        cached_body = cached.json()
        assert cached_body["cache_hit"] is True
        assert cached_body["match_type"] == "exact"
        assert cached_body["asset"]["id"] == job_body["asset"]["id"]


def test_in_flight_generation_jobs_are_deduped(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("FLOPPY_LOCAL_PROVIDER_DELAY_SEC", "0.2")
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["story"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 10,
            "stress_level": "low",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 20,
            "mood_tags": ["gentle"],
        }
        assert client.put("/users/u_dupe/profile", json=profile_payload).status_code == 200

        request_payload = {
            "request_text": "请生成一个温柔女声讲雨夜城市的睡前故事，10分钟",
            "force_generate": True,
        }
        responses = []

        def submit_job():
            responses.append(client.post("/users/u_dupe/generation-jobs", json=request_payload))

        first_thread = threading.Thread(target=submit_job)
        first_thread.start()
        second = client.post("/users/u_dupe/generation-jobs", json=request_payload)
        first_thread.join()

        first = responses[0]
        assert first.status_code == 202
        assert second.status_code == 202
        first_body = first.json()
        second_body = second.json()
        assert {first_body["match_type"], second_body["match_type"]} == {"queued", "in_flight"}
        assert first_body["job_id"] == second_body["job_id"]

        job = client.get(f"/generation-jobs/{first_body['job_id']}")
        assert job.status_code == 200
        assert job.json()["status"] == "succeeded"


def test_minimax_provider_requires_api_key(monkeypatch):
    monkeypatch.setenv("FLOPPY_AUDIO_PROVIDER", "minimax")
    monkeypatch.delenv("FLOPPY_MINIMAX_API_KEY", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    with pytest.raises(ProviderConfigurationError, match="FLOPPY_MINIMAX_API_KEY"):
        build_audio_provider(settings)
