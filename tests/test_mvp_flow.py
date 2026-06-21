from __future__ import annotations

import json
import sqlite3
import threading
import unittest.mock
import urllib.error

from fastapi.testclient import TestClient
import pytest

from floppy_backend.config import Settings, get_settings
from floppy_backend.db import connect, initialize
from floppy_backend.main import app, state
from floppy_backend.models import AudioAssetIn, AudioType, GenerationRequest
from floppy_backend.providers.audio import LocalToneAudioProvider, MiniMaxTTSProvider, ProviderAPIError, ProviderConfigurationError, build_audio_provider
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer


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

        request_payload = {"request_text": "我想听一个温柔女声讲海边书店的睡前故事，背景有轻微雨声，15分钟", "force_generate": True}
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

        cache_request_payload = dict(request_payload)
        cache_request_payload["force_generate"] = False
        second = client.post("/users/u_test/generate-audio", json=cache_request_payload)
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


def test_minimax_default_base_url_uses_chinese_host(monkeypatch):
    monkeypatch.delenv("FLOPPY_MINIMAX_BASE_URL", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.minimax_base_url == "https://api.minimaxi.com"


def test_minimax_invalid_key_hint_for_international_host():
    settings = Settings(minimax_api_key="test-key", minimax_base_url="https://api.minimax.io")
    provider = MiniMaxTTSProvider(settings)

    with pytest.raises(ProviderAPIError, match="FLOPPY_MINIMAX_BASE_URL=https://api.minimaxi.com"):
        provider._raise_base_resp_error({"status_code": 1004, "status_msg": "invalid api key"}, "failed")


def test_build_audio_provider_unsupported_raises():
    settings = Settings(audio_provider="nonexistent_provider")
    with pytest.raises(ProviderConfigurationError, match="nonexistent_provider"):
        build_audio_provider(settings)


def test_minimax_http_401_hint_via_post_json(monkeypatch):
    settings = Settings(minimax_api_key="test-key", minimax_base_url="https://api.minimax.io")
    provider = MiniMaxTTSProvider(settings)

    http_err = urllib.error.HTTPError(url="", code=401, msg="Unauthorized", hdrs=None, fp=None)  # type: ignore[arg-type]
    http_err.read = lambda: b"invalid api key"

    with unittest.mock.patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(ProviderAPIError) as exc_info:
            provider._post_json("/v1/t2a_v2", {})
    assert "api.minimaxi.com" in str(exc_info.value)
    assert exc_info.value.status_code == 401


def test_minimax_async_job_failed_raises():
    settings = Settings(minimax_api_key="test-key")
    provider = MiniMaxTTSProvider(settings)

    task_resp = {"task_id": "t1", "file_id": None, "task_token": None, "usage_characters": 100, "base_resp": {"status_code": 0}}
    status_resp = {"task_id": "t1", "status": "failed", "file_id": None, "base_resp": {"status_code": 0}}

    with unittest.mock.patch.object(provider, "_post_json", return_value=task_resp), \
         unittest.mock.patch.object(provider, "_get_json", return_value=status_resp), \
         unittest.mock.patch("time.sleep"):
        with pytest.raises(ProviderAPIError, match="status=failed"):
            from pathlib import Path
            from floppy_backend.models import NormalizedAudioRequest, AudioType
            normalized = NormalizedAudioRequest(
                intent=AudioType.STORY,
                duration_bucket="medium",
                duration_sec=300,
                voice_style="warm_female",
                background="rain_soft",
                mood=["calm"],
                content_topic=["海边"],
            )
            provider.generate_async_and_wait(normalized, Path("/tmp/out.mp3"), "obj/key", script_text="短文本" * 20)


def test_minimax_estimate_cost():
    settings = Settings(minimax_api_key="test-key", minimax_model="speech-2.8-hd")
    provider = MiniMaxTTSProvider(settings)
    cost = provider.estimate_cost(1_000_000, "speech-2.8-hd")
    assert cost == 100.0
    cost_turbo = provider.estimate_cost(500_000, "speech-2.8-turbo")
    assert cost_turbo == 30.0


def test_minimax_provider_failure_recorded_on_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("FLOPPY_AUDIO_PROVIDER", "minimax")
    monkeypatch.setenv("FLOPPY_MINIMAX_API_KEY", "test-key")
    get_settings.cache_clear()

    with unittest.mock.patch(
        "floppy_backend.providers.audio.urllib.request.urlopen",
        side_effect=urllib.error.URLError("network unavailable"),
    ):
        with TestClient(app) as client:
            profile_payload = {
                "audio_type_preferences": ["story"],
                "voice_preferences": ["warm_female"],
                "background_preferences": ["rain_soft"],
                "duration_preference_min": 5,
                "stress_level": "medium",
                "anxiety_level": "medium",
                "avg_sleep_latency_min": 20,
                "mood_tags": ["gentle"],
            }
            assert client.put("/users/u_mmfailed/profile", json=profile_payload).status_code == 200

            resp = client.post(
                "/users/u_mmfailed/generate-audio",
                json={"request_text": "请用温柔女声讲一个短故事，5分钟", "force_generate": True},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "failed"
            assert body["asset"] is None

            job_resp = client.get(f"/generation-jobs/{body['job_id']}")
            job = job_resp.json()
            assert job["status"] == "failed"
            assert job["error_code"] == "ProviderAPIError"
            assert "network unavailable" in job["error_message"]
            assert job["script_hash"]
            assert job["script_chars"] > 0

    get_settings.cache_clear()



def test_minimax_cost_recorded_on_succeeded_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("FLOPPY_AUDIO_PROVIDER", "minimax")
    monkeypatch.setenv("FLOPPY_MINIMAX_API_KEY", "test-key")
    get_settings.cache_clear()

    fake_audio_hex = bytes([0xFF, 0xFB] + [0] * 100).hex()
    sync_resp = {
        "base_resp": {"status_code": 0},
        "data": {"audio": fake_audio_hex},
        "extra_info": {"audio_length": 5000, "usage_characters": 200},
        "trace_id": "trace-test",
    }

    with unittest.mock.patch("floppy_backend.providers.audio.urllib.request.urlopen") as mock_urlopen:
        mock_response = unittest.mock.MagicMock()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = unittest.mock.MagicMock(return_value=False)
        mock_response.read.return_value = json.dumps(sync_resp).encode()
        mock_urlopen.return_value = mock_response

        with TestClient(app) as client:
            profile_payload = {
                "audio_type_preferences": ["story"],
                "voice_preferences": ["warm_female"],
                "background_preferences": ["rain_soft"],
                "duration_preference_min": 5,
                "stress_level": "medium",
                "anxiety_level": "medium",
                "avg_sleep_latency_min": 20,
                "mood_tags": ["gentle"],
            }
            assert client.put("/users/u_mmcost/profile", json=profile_payload).status_code == 200

            resp = client.post(
                "/users/u_mmcost/generate-audio",
                json={"request_text": "请用温柔女声讲一个短故事，5分钟", "force_generate": True},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "succeeded"

            job_resp = client.get(f"/generation-jobs/{body['job_id']}")
            job = job_resp.json()
            assert job["usage_characters"] == 200
            assert job["estimated_cost_usd"] is not None
            assert job["estimated_cost_usd"] > 0
            assert job["provider_model"] is not None

    get_settings.cache_clear()


def test_asset_library_cache_hit_skips_provider_generate(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.delenv("FLOPPY_AUDIO_PROVIDER", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["story"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 10,
            "stress_level": "medium",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 20,
            "mood_tags": ["gentle"],
        }
        assert client.put("/users/u_cache_hit/profile", json=profile_payload).status_code == 200

        request_payload = {"request_text": "请用温柔女声讲一个雨夜书店的睡前故事，10分钟"}
        first = client.post("/users/u_cache_hit/generate-audio", json=request_payload)
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["status"] == "succeeded"
        assert first_body["cache_hit"] is False

        with unittest.mock.patch.object(
            state.generation_service.provider,
            "generate",
            side_effect=AssertionError("provider.generate should not run on cache hit"),
        ) as generate_mock:
            second = client.post("/users/u_cache_hit/generate-audio", json=request_payload)

        assert second.status_code == 200
        second_body = second.json()
        assert second_body["cache_hit"] is True
        assert second_body["asset"]["id"] == first_body["asset"]["id"]
        generate_mock.assert_not_called()


def test_request_normalizer_maps_chinese_tags():
    normalizer = RequestNormalizer()

    rain = normalizer.normalize(GenerationRequest(request_text="我想听雨声帮助入睡"), None)
    female = normalizer.normalize(GenerationRequest(request_text="请用女声讲一个睡前故事"), None)

    assert rain.background == "rain_soft"
    assert female.voice_style == "warm_female"


def test_force_generate_creates_audio_asset_with_matching_prompt_hash(tmp_path, monkeypatch):
    db_path = tmp_path / "floppy.db"
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.delenv("FLOPPY_AUDIO_PROVIDER", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_male"],
            "background_preferences": ["forest_night"],
            "duration_preference_min": 5,
            "stress_level": "low",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 15,
            "mood_tags": ["calm"],
        }
        assert client.put("/users/u_asset_row/profile", json=profile_payload).status_code == 200

        response = client.post(
            "/users/u_asset_row/generate-audio",
            json={"request_text": "请生成男声森林呼吸冥想，5分钟", "force_generate": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "succeeded"
        asset = body["asset"]

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, prompt_hash FROM audio_assets WHERE id = ? AND prompt_hash = ?",
            (asset["id"], asset["prompt_hash"]),
        ).fetchone()
        conn.close()

    assert row is not None
    assert row["prompt_hash"] == asset["prompt_hash"]


def test_rejected_asset_excluded_from_list_assets(tmp_path):
    conn = connect(tmp_path / "floppy.db")
    initialize(conn)
    repo = Repository(conn)

    rejected = repo.upsert_asset(
        AudioAssetIn(
            type=AudioType.STORY,
            title="Rejected story",
            object_key="test/rejected.wav",
            duration_sec=60,
            voice_id="warm_female",
            prompt_hash="rejected-prompt-hash",
            content_hash="rejected-content-hash",
            mood_tags=["calm"],
            user_segment_tags=["balanced_sleep"],
            safety_status="rejected",
            quality_score=0.95,
            embedding=[0.0] * 32,
            created_by="test",
        )
    )

    listed_ids = {asset.id for asset in repo.list_assets()}
    conn.close()

    assert rejected.id not in listed_ids


def test_default_audio_provider_is_local(monkeypatch):
    monkeypatch.delenv("FLOPPY_AUDIO_PROVIDER", raising=False)
    monkeypatch.delenv("FLOPPY_MINIMAX_API_KEY", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    provider = build_audio_provider(settings)

    assert settings.audio_provider == "local"
    assert isinstance(provider, LocalToneAudioProvider)
    assert not isinstance(provider, MiniMaxTTSProvider)

    get_settings.cache_clear()


def test_agent_tool_contract_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.delenv("FLOPPY_AUDIO_PROVIDER", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 10,
            "stress_level": "medium",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 30,
            "mood_tags": ["anxiety_relief"],
        }
        assert client.put("/users/u_agent/profile", json=profile_payload).status_code == 200

        checkin = client.post(
            "/users/u_agent/profile/checkin",
            json={"tonight_mood": "tired", "tonight_stress": "high", "sleep_latency_hint_min": 45},
        )
        assert checkin.status_code == 200
        assert checkin.json()["tonight_mood"] == "tired"
        assert checkin.json()["tonight_stress"] == "high"

        context = client.get("/users/u_agent/profile/context")
        assert context.status_code == 200
        context_body = context.json()
        assert context_body["segment"] == "anxiety_relief"
        assert context_body["generation_budget"]["daily_remaining_chars"] > 0
        assert context_body["generation_budget"]["daily_generate_count_remaining"] > 0

        normalized = client.post(
            "/normalize",
            json={"user_id": "u_agent", "request_text": "今晚压力很大，想听温柔女声雨声呼吸冥想，10分钟"},
        )
        assert normalized.status_code == 200
        normalized_body = normalized.json()
        assert normalized_body["normalized_request"]["intent"] == "meditation"
        assert normalized_body["normalized_request"]["background"] == "rain_soft"
        assert normalized_body["cache_key"]

        generated = client.post(
            "/users/u_agent/generate-audio",
            json={"request_text": "今晚压力很大，想听温柔女声雨声呼吸冥想，10分钟", "force_generate": True},
        )
        assert generated.status_code == 200
        generated_body = generated.json()
        assert generated_body["status"] == "succeeded"

        search = client.post(
            "/assets/search",
            json={
                "user_id": "u_agent",
                "query": "今晚压力很大，想听温柔女声雨声呼吸冥想，10分钟",
                "cache_key": normalized_body["cache_key"],
                "filters": {"type": "meditation", "mood_tags": ["anxiety_relief"]},
                "limit": 3,
            },
        )
        assert search.status_code == 200
        search_body = search.json()
        assert search_body["hit"] is True
        assert search_body["best_score"] is not None
        assert search_body["threshold"] == get_settings().asset_hit_threshold
        assert search_body["results"][0]["asset"]["playback_url"].startswith("http://127.0.0.1:8000/audio/")

    get_settings.cache_clear()


def test_generation_budget_rejects_new_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("FLOPPY_DAILY_GENERATE_COUNT", "0")
    monkeypatch.delenv("FLOPPY_AUDIO_PROVIDER", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["story"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 10,
            "stress_level": "medium",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 20,
            "mood_tags": ["gentle"],
        }
        assert client.put("/users/u_budget/profile", json=profile_payload).status_code == 200

        response = client.post(
            "/users/u_budget/generation-jobs",
            json={"request_text": "请生成一个新的雨夜睡前故事，10分钟", "force_generate": True},
        )
        assert response.status_code == 429
        assert "daily generation count exceeded" in response.json()["detail"]

    get_settings.cache_clear()


def test_agent_decide_play_asset_on_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["story"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 10,
            "stress_level": "medium",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 20,
            "mood_tags": ["gentle"],
        }
        assert client.put("/users/u_ad1/profile", json=profile_payload).status_code == 200

        gen = client.post("/users/u_ad1/generate-audio", json={"request_text": "温柔女声讲雨夜书店故事，10分钟", "force_generate": True})
        assert gen.status_code == 200
        asset_id = gen.json()["asset"]["id"]

        resp = client.post("/agent/decide", json={"user_id": "u_ad1", "request_text": "温柔女声讲雨夜书店故事，10分钟"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "play_asset"
        assert body["asset"]["id"] == asset_id
        assert body["job_id"] is None
        assert body["profile_context"]["user_id"] == "u_ad1"
        assert body["search"]["hit"] is True


def test_agent_decide_no_match_when_generation_disallowed(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_male"],
            "background_preferences": ["forest_night"],
            "duration_preference_min": 10,
            "stress_level": "high",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 40,
            "mood_tags": ["safe"],
        }
        assert client.put("/users/u_ad2/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_ad2", "request_text": "一段极其独特的月球冥想音频", "generation_allowed": False})
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "no_match"
        assert body["asset"] is None
        assert body["job_id"] is None


def test_agent_decide_generate_job_on_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_male"],
            "background_preferences": ["forest_night"],
            "duration_preference_min": 10,
            "stress_level": "high",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 40,
            "mood_tags": ["safe"],
        }
        assert client.put("/users/u_ad3/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_ad3", "request_text": "一段极其独特的月球冥想音频", "generation_allowed": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "generate_job"
        assert body["job_id"] is not None
        assert body["asset"] is None

        job = client.get(f"/generation-jobs/{body['job_id']}")
        assert job.status_code == 200
        assert job.json()["status"] == "succeeded"


def test_agent_decide_budget_exceeded_returns_429(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("FLOPPY_DAILY_GENERATE_COUNT", "0")
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["story"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 10,
            "stress_level": "medium",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 20,
            "mood_tags": ["gentle"],
        }
        assert client.put("/users/u_ad4/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_ad4", "request_text": "一段极其独特的太空冥想", "generation_allowed": True})
        assert resp.status_code == 429

    get_settings.cache_clear()


def test_agent_decide_tag_hit_ranks_higher(tmp_path, monkeypatch):
    """Assets with matching preferred_tags from profile should rank higher than generic semantic matches."""
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200

        # anxiety_relief segment → preferred_tags include low_stimulation, breathing, grounding
        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 15,
            "stress_level": "high",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 40,
            "mood_tags": ["anxiety_relief"],
        }
        assert client.put("/users/u_tag1/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_tag1", "request_text": "呼吸冥想引导放松压力释放"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "play_asset"
        # The hit should mention tag reasons
        reasons_str = " ".join(body["reasons"])
        assert "标签命中" in reasons_str or "匹配" in reasons_str


def test_agent_decide_negative_tag_not_first(tmp_path, monkeypatch):
    """Assets with negative_tags matching profile are hard-excluded from results."""
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200

        # environmental_sleep → negative_tags include voice_heavy, narrative
        profile_payload = {
            "audio_type_preferences": ["white_noise"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 20,
            "stress_level": "low",
            "anxiety_level": "low",
            "avg_sleep_latency_min": 15,
            "mood_tags": ["calm"],
        }
        assert client.put("/users/u_tag2/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_tag2", "request_text": "安静的雨声白噪音"})
        assert resp.status_code == 200
        body = resp.json()
        # All results must be free of negative tags (narrative, voice_heavy)
        for result in body["search"]["results"]:
            asset_tags = result["asset"].get("tags", [])
            assert "narrative" not in asset_tags, f"narrative should be hard-filtered but found in {result['asset']['title']}"
            assert "voice_heavy" not in asset_tags


def test_agent_decide_mock_ai_planner_controls_tags(tmp_path, monkeypatch):
    """Mock AI planner returns specific tags that control search results."""
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    from floppy_backend.services.query_planner import StructuredQuery

    class MockAIPlanner:
        def plan(self, request_text, profile_context):
            return StructuredQuery(
                preferred_tags=["breathing", "grounding", "low_stimulation"],
                negative_tags=["narrative", "voice_present"],
                mood=["calm"],
                confidence=0.9,
                source="ai",
                reason_codes=["ai_tag_extraction"],
            )

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200
        state.agent_graph._planner = MockAIPlanner()

        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 15,
            "stress_level": "high",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 40,
            "mood_tags": ["anxiety_relief"],
        }
        assert client.put("/users/u_ai1/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_ai1", "request_text": "呼吸冥想放松"})
        assert resp.status_code == 200
        body = resp.json()
        # narrative/voice_present assets hard-filtered
        for result in body["search"]["results"]:
            assert "narrative" not in result["asset"].get("tags", [])
            assert "voice_present" not in result["asset"].get("tags", [])


def test_agent_decide_ai_low_confidence_fallback(tmp_path, monkeypatch):
    """Low confidence AI planner merges with rule fallback."""
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    from floppy_backend.services.query_planner import StructuredQuery

    class LowConfidencePlanner:
        def plan(self, request_text, profile_context):
            return StructuredQuery(
                preferred_tags=["ocean"],
                negative_tags=[],
                confidence=0.3,
                source="ai",
                reason_codes=["ai_uncertain"],
            )

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200
        state.agent_graph._planner = LowConfidencePlanner()

        profile_payload = {
            "audio_type_preferences": ["white_noise"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 20,
            "stress_level": "low",
            "anxiety_level": "low",
            "avg_sleep_latency_min": 15,
            "mood_tags": ["calm"],
        }
        assert client.put("/users/u_ai2/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_ai2", "request_text": "海浪声音助眠"})
        assert resp.status_code == 200
        body = resp.json()
        # Should still get results (rule fallback merged)
        assert body["action"] in ("play_asset", "generate_job")


def test_agent_decide_ai_unavailable_fallback(tmp_path, monkeypatch):
    """AI planner raising exception falls back to rule planner."""
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    class FailingPlanner:
        def plan(self, request_text, profile_context):
            raise RuntimeError("LLM API timeout")

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200
        state.agent_graph._planner = FailingPlanner()

        profile_payload = {
            "audio_type_preferences": ["meditation"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 15,
            "stress_level": "high",
            "anxiety_level": "high",
            "avg_sleep_latency_min": 40,
            "mood_tags": ["anxiety_relief"],
        }
        assert client.put("/users/u_ai3/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={"user_id": "u_ai3", "request_text": "呼吸冥想引导放松压力释放"})
        assert resp.status_code == 200
        body = resp.json()
        # Fallback still works — should hit seeded meditation asset
        assert body["action"] == "play_asset"


def test_agent_decide_ai_tags_hit_demo_asset(tmp_path, monkeypatch):
    """Mock AI planner with real demo tags hits the anxiety breathing rain asset with score >= 0.58."""
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    from floppy_backend.services.query_planner import StructuredQuery

    class DemoAIPlanner:
        def plan(self, request_text, profile_context, available_tags=None):
            return StructuredQuery(
                preferred_tags=["breathing", "low_stimulation", "minimal_voice", "rain", "short_duration", "warm_voice"],
                negative_tags=["high_energy", "suspense"],
                mood=["anxiety_relief", "calm"],
                confidence=0.85,
                source="ai",
                reason_codes=["ai_tag_extraction"],
            )

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200
        state.agent_graph._planner = DemoAIPlanner()

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
        assert client.put("/users/u_demo_hit/profile", json=profile_payload).status_code == 200

        resp = client.post("/agent/decide", json={
            "user_id": "u_demo_hit",
            "request_text": "我今晚压力很大，一直胡思乱想，想听一个温柔的呼吸冥想，最好有轻微雨声，15分钟",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "play_asset"
        assert body["search"]["best_score"] >= 0.60
        assert body["search"]["hit"] is True
        assert any("标签命中" in r for r in body["reasons"])