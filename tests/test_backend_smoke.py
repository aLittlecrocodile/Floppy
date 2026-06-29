from __future__ import annotations

from types import SimpleNamespace

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import app, state, _run_chat_decision
from floppy_backend.models import AssetSearchFilters, AudioType, GenerationRequest


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
        assert job_body["asset"]["playback_url"].startswith("http://127.0.0.1:8000/audio/")
        assert job_body["script"]["script_text"]


def test_agent_decide_response_contract_smoke(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    def fake_plan_search(self, *, request, profile_context, facets):
        from floppy_backend.services.hermes_agent import HermesSearchPlan

        return HermesSearchPlan(
            query=request.request_text,
            filters=AssetSearchFilters(type=AudioType.MEDITATION),
            reasons=["测试环境使用 mock Hermes search plan"],
            confidence=0.8,
        )

    def fake_decide(self, *, request, profile_context, search, search_plan=None):
        from floppy_backend.services.hermes_agent import HermesDecision

        return HermesDecision(
            action="no_match",
            selected_skill="no_match",
            reasons=["测试环境使用 mock Hermes"],
            confidence=0.8,
        )

    monkeypatch.setattr(
        "floppy_backend.services.hermes_agent.HermesAgentClient.plan_search",
        fake_plan_search,
    )
    monkeypatch.setattr(
        "floppy_backend.services.hermes_agent.HermesAgentClient.decide",
        fake_decide,
    )

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
            assert body["asset"]["playback_url"].startswith("http://127.0.0.1:8000/audio/")
        if body["job_id"]:
            job = client.get(f"/generation-jobs/{body['job_id']}")
            assert job.status_code == 200


def test_audio_asset_facets_and_lookup_smoke(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.put("/users/u_facets_smoke/profile", json=_profile_payload()).status_code == 200
        created = client.post(
            "/users/u_facets_smoke/generation-jobs",
            json={"request_text": "请生成一段很短的雨声呼吸冥想", "force_generate": True},
        )
        assert created.status_code == 202

        facets = client.get("/assets/facets?limit=3")
        assert facets.status_code == 200
        body = facets.json()
        assert body["total_assets"] >= 1
        assert "meditation" in body["asset_types"]
        assert body["top_assets"]
        asset_id = body["top_assets"][0]["id"]
        assert body["top_assets"][0]["playback_url"].startswith("http://127.0.0.1:8000/audio/")

        asset = client.get(f"/assets/{asset_id}")
        assert asset.status_code == 200
        assert asset.json()["id"] == asset_id
        assert asset.json()["playback_url"].startswith("http://127.0.0.1:8000/audio/")


def test_voice_intent_chat_route_does_not_run_audio_workflow(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    def fake_route(self, *, user_id, conversation_id, text, history, source="voice", current_asset_id=None):
        from floppy_backend.services.voice_dialog_router import VoiceDialogRoute

        return VoiceDialogRoute(
            action="chat",
            reply_text="听起来你今晚有点累，我们先慢慢聊一会儿。",
            confidence=0.9,
            reasons=["用户只是倾诉，没有明确音频请求"],
        )

    def fail_run_chat_decision(*args, **kwargs):
        raise AssertionError("voice chat route should not run audio workflow")

    monkeypatch.setattr("floppy_backend.services.voice_dialog_router.HermesVoiceDialogClient.route", fake_route)
    monkeypatch.setattr("floppy_backend.main._run_chat_decision", fail_run_chat_decision)

    with TestClient(app) as client:
        response = client.post(
            "/voice/intent",
            json={
                "text": "我今天有点烦，睡不着",
                "conversationId": "voice-chat-route",
                "clientRequestId": "req-1",
                "turnIndex": 1,
                "user_id": "u_voice_chat",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "chat"
    assert body["audio_url"] is None
    assert body["reply"] == "听起来你今晚有点累，我们先慢慢聊一会儿。"


def test_voice_intent_audio_route_enters_sleep_audio_workflow(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    captured = {}

    def fake_route(self, *, user_id, conversation_id, text, history, source="voice", current_asset_id=None):
        from floppy_backend.services.voice_dialog_router import VoiceDialogRoute

        return VoiceDialogRoute(
            action="audio_workflow",
            reply_text="好的，我给你找一段没有人声的雨声。",
            audio_request_text="给我放雨声，不要人声，不要雷声",
            audio_intent_hint="white_noise",
            confidence=0.94,
            reasons=["用户明确要求播放雨声"],
        )

    def fake_run_chat_decision(user_id, request_text, reply_text=None, current_asset_id=None, background_tasks=None):
        captured["user_id"] = user_id
        captured["request_text"] = request_text
        captured["reply_text"] = reply_text
        captured["has_background_tasks"] = background_tasks is not None
        return (
            SimpleNamespace(
                action="play_asset",
                asset=None,
                search=SimpleNamespace(hit=True, best_score=1.0),
                reasons=["Hermes sleep-audio 选择播放雨声"],
            ),
            "http://127.0.0.1:8000/audio/real/white_noise/01.mp3",
            None,
            None,
            False,
            reply_text,
        )

    monkeypatch.setattr("floppy_backend.services.voice_dialog_router.HermesVoiceDialogClient.route", fake_route)
    monkeypatch.setattr("floppy_backend.main._run_chat_decision", fake_run_chat_decision)

    with TestClient(app) as client:
        response = client.post(
            "/voice/intent",
            json={
                "text": "放点雨声吧，不要人声",
                "conversationId": "voice-audio-route",
                "clientRequestId": "req-1",
                "turnIndex": 1,
                "user_id": "u_voice_audio",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "play_asset"
    assert body["audio_type"] == "white_noise"
    assert body["audio_url"].endswith("/audio/real/white_noise/01.mp3")
    assert captured["request_text"] == "给我放雨声，不要人声，不要雷声"
    assert captured["reply_text"] == "好的，我给你找一段没有人声的雨声。"
    assert captured["has_background_tasks"] is True


def test_voice_intent_generate_route_returns_pollable_job(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    def fake_route(self, *, user_id, conversation_id, text, history, source="voice", current_asset_id=None):
        from floppy_backend.services.voice_dialog_router import VoiceDialogRoute

        return VoiceDialogRoute(
            action="audio_workflow",
            reply_text="好的，我正在给你准备一段故事。",
            audio_request_text="讲个睡前故事",
            audio_intent_hint="story",
            confidence=0.92,
        )

    def fake_run_chat_decision(user_id, request_text, reply_text=None, current_asset_id=None, background_tasks=None):
        return (
            SimpleNamespace(
                action="generate_job",
                asset=None,
                job_id="job_voice_story",
                search=SimpleNamespace(hit=False, best_score=None),
                reasons=["Hermes sleep-audio 选择生成故事"],
            ),
            None,
            SimpleNamespace(status="queued", asset=None),
            None,
            False,
            reply_text,
        )

    monkeypatch.setattr("floppy_backend.services.voice_dialog_router.HermesVoiceDialogClient.route", fake_route)
    monkeypatch.setattr("floppy_backend.main._run_chat_decision", fake_run_chat_decision)

    with TestClient(app) as client:
        response = client.post(
            "/voice/intent",
            json={
                "text": "讲个故事",
                "conversationId": "voice-generate-route",
                "clientRequestId": "req-1",
                "turnIndex": 1,
                "user_id": "u_voice_generate",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "generate_job"
    assert body["audio_url"] is None
    assert body["job_id"] == "job_voice_story"
    assert body["job_status"] == "queued"


def test_run_chat_decision_schedules_generation_without_inline_run(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    class FakeRuntime:
        def run(self, request):
            return SimpleNamespace(
                action="generate_job",
                asset=None,
                job_id="job_nonblocking",
                search=SimpleNamespace(hit=False, best_score=None),
            )

    def fail_inline_run(*args, **kwargs):
        raise AssertionError("generation should be scheduled, not run inline")

    with TestClient(app):
        monkeypatch.setattr(state, "agent_runtime", FakeRuntime())
        monkeypatch.setattr(state.generation_service, "run_job", fail_inline_run)
        background_tasks = BackgroundTasks()

        response, audio_url, job, asset_data, _is_placeholder, _reply_text = _run_chat_decision(
            "u_nonblocking",
            "请生成一个故事",
            background_tasks=background_tasks,
        )

    assert response.action == "generate_job"
    assert audio_url is None
    assert job is None
    assert asset_data is None
    assert len(background_tasks.tasks) == 1


def test_white_noise_generation_is_non_voice_workflow(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.put("/users/u_noise_smoke/profile", json=_profile_payload()).status_code == 200
        created = client.post(
            "/users/u_noise_smoke/generation-jobs",
            json={
                "request_text": "给我放雨声，不要冥想，不要人声",
                "force_generate": True,
                "directive": {
                    "intent": "white_noise",
                    "content_brief": "持续雨声",
                    "key_elements": ["雨声"],
                    "confidence": 0.95,
                    "source": "hermes",
                },
            },
        )
        assert created.status_code == 202

        job = client.get(f"/generation-jobs/{created.json()['job_id']}")
        assert job.status_code == 200
        body = job.json()
        assert body["status"] == "succeeded"
        assert body["script"] is None
        assert body["provider_model"] == "ambient_procedural_v1"
        assert body["asset"]["type"] == "white_noise"
        assert body["asset"]["voice_id"] == "none"
        assert "no_voice" in body["asset"]["tags"]


def test_remix_session_smoke(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.put("/users/u_remix_smoke/profile", json=_profile_payload()).status_code == 200
        generated = client.post(
            "/users/u_remix_smoke/generation-jobs",
            json={
                "request_text": "请生成一段温柔女声的短呼吸冥想",
                "force_generate": True,
            },
        )
        assert generated.status_code == 202
        job_id = generated.json()["job_id"]
        job = client.get(f"/generation-jobs/{job_id}")
        assert job.status_code == 200
        foreground_id = job.json()["asset"]["id"]

        created = client.post(
            "/remix/sessions",
            json={
                "foreground_asset_id": foreground_id,
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


def test_profile_playback_and_safety_skill_endpoints(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    clean_script = (
        "今晚，我们慢慢把注意力放在呼吸上。<#3#>"
        "吸气的时候，不用刻意用力。<#4#>"
        "呼气的时候，让肩膀轻轻放松。<#5#>"
        "如果念头经过，也没关系。<#4#>"
        "你只需要在这里，听见一点安静。<#6#>"
        "窗外的声音很远，房间里的光也慢慢柔和下来。<#4#>"
        "不用追赶任何结果，只是让身体一点一点休息。<#6#>"
    )

    with TestClient(app) as client:
        assert client.post("/admin/seed").status_code == 200
        assert client.put("/users/u_skill/profile", json=_profile_payload()).status_code == 200

        checkin = client.post(
            "/users/u_skill/profile/checkin",
            json={"tonight_mood": "有点焦虑", "tonight_stress": "high", "sleep_latency_hint_min": 35},
        )
        assert checkin.status_code == 200
        assert checkin.json()["tonight_mood"] == "有点焦虑"

        context = client.get("/users/u_skill/profile/context")
        assert context.status_code == 200
        assert "generation_budget" in context.json()

        generated = client.post(
            "/users/u_skill/generation-jobs",
            json={"request_text": "请生成一段短短的温柔呼吸冥想", "force_generate": True},
        )
        assert generated.status_code == 202
        job = client.get(f"/generation-jobs/{generated.json()['job_id']}")
        assert job.status_code == 200
        asset_id = job.json()["asset"]["id"]

        started = client.post(
            "/users/u_skill/playback",
            json={"asset_id": asset_id, "source": "recommend", "request_text": "放点雨声"},
        )
        assert started.status_code == 201
        record_id = started.json()["record_id"]

        active = client.get("/users/u_skill/playback/active")
        assert active.status_code == 200
        assert active.json()["id"] == record_id

        wrong_user = client.post(
            f"/users/u_other/playback/{record_id}/feedback",
            json={"feedback_type": "favorite", "rating": 5, "progress": 0.42},
        )
        assert wrong_user.status_code == 404

        missing_record = client.post(
            "/users/u_skill/playback/pb_missing/feedback",
            json={"feedback_type": "favorite", "rating": 5, "progress": 0.42},
        )
        assert missing_record.status_code == 404

        feedback = client.post(
            f"/users/u_skill/playback/{record_id}/feedback",
            json={"feedback_type": "favorite", "rating": 5, "progress": 0.42},
        )
        assert feedback.status_code == 200

        history = client.get("/users/u_skill/playback/history")
        assert history.status_code == 200
        assert history.json()[0]["feedback_type"] == "favorite"

        safety_ok = client.post(
            "/safety/script/check",
            json={"script_text": clean_script, "estimated_duration_sec": 120},
        )
        assert safety_ok.status_code == 200
        assert safety_ok.json()["status"] == "approved"

        safety_blocked = client.post(
            "/safety/script/check",
            json={"script_text": "突然爆炸声响起。<#3#>你必须现在醒来。", "estimated_duration_sec": 30},
        )
        assert safety_blocked.status_code == 200
        assert safety_blocked.json()["status"] == "blocked"


def test_txt_upload_can_generate_sleep_audio(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    text = (
        "这是一篇关于夜晚散步的短文。作者慢慢穿过安静的街道，看见路灯、树影和远处的窗光。"
        "内容没有紧急事件，只适合被改写成睡前可以听的低信息密度音频。"
    )

    with TestClient(app) as client:
        assert client.put("/users/u_upload_skill/profile", json=_profile_payload()).status_code == 200

        uploaded = client.post(
            "/users/u_upload_skill/uploads",
            files={"file": ("../night-note.txt", text.encode("utf-8"), "text/plain")},
        )
        assert uploaded.status_code == 201
        upload_id = uploaded.json()["id"]
        assert uploaded.json()["fileName"] == "night-note.txt"
        assert uploaded.json()["generatedAudio"] is None

        created = client.post(
            f"/users/u_upload_skill/uploads/{upload_id}/generate-audio",
            json={
                "request_text": "把这篇短文改成适合睡前听的慢节奏音频",
                "audio_intent": "podcast_digest",
                "duration_sec": 300,
            },
        )
        assert created.status_code == 202
        body = created.json()
        assert body["job_id"]
        assert body["normalized_request"]["intent"] == "podcast_digest"

        job = client.get(f"/generation-jobs/{body['job_id']}")
        assert job.status_code == 200
        assert job.json()["status"] == "succeeded"
        assert job.json()["asset"]["type"] == "podcast_digest"

        upload = client.get(f"/users/u_upload_skill/uploads/{upload_id}")
        assert upload.status_code == 200
        upload_body = upload.json()
        assert upload_body["status"] == "Completed"
        assert upload_body["generatedAudio"]["id"] == job.json()["asset"]["id"]


def test_generation_job_prepare_exception_marks_failed(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        assert client.put("/users/u_fail_job/profile", json=_profile_payload()).status_code == 200
        request = GenerationRequest(request_text="请生成一段短短的睡前故事", force_generate=True)
        created = state.generation_service.enqueue_or_match("u_fail_job", request)

        def broken_prepare(*args, **kwargs):
            raise RuntimeError("prepare exploded")

        monkeypatch.setattr(state.generation_service, "prepare", broken_prepare)
        state.generation_service.run_job(created.job_id, "u_fail_job", request)

        job = client.get(f"/generation-jobs/{created.job_id}")
        assert job.status_code == 200
        body = job.json()
        assert body["status"] == "failed"
        assert body["error_code"] == "RuntimeError"
        assert "prepare exploded" in body["error_message"]
