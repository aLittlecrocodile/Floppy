from __future__ import annotations

from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import _attach_reply_audio, app
from floppy_backend.models import AgentDecideResponse


def _configure_tmp_app(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()


def test_showcase_page_serves_branding(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.get("/showcase")
        assert resp.status_code == 200
        assert "Unwind" in resp.text
        assert "智能体决策轨迹" in resp.text
        assert "Hermes" not in resp.text
        assert 'id="callBtn"' in resp.text
        assert 'id="callOverlay"' in resp.text
        assert "/voice/ws?user_id=" in resp.text
        assert "/voice/realtime?user_id=" in resp.text
        assert "__SCRIPT__" not in resp.text  # script placeholder must be substituted

        logo = client.get("/showcase/assets/baidu-bear.png")
        assert logo.status_code == 200
        assert logo.headers["content-type"].startswith("image/png")

        root = client.get("/", follow_redirects=False)
        assert root.status_code in {302, 307}
        assert root.headers["location"] == "/showcase"


def test_showcase_chat_returns_decision_trace(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.post("/showcase/chat", json={"request_text": "帮我放松一下，来点雨声"})
        assert resp.status_code == 200
        data = resp.json()
        # the decision timeline depends on these fields being present
        assert data["action"] in {"chat", "play_asset", "generate_job", "remix_current", "no_match"}
        assert "selected_skill" in data
        assert "tool_calls" in data
        assert "planner_meta" in data
        assert "reasons" in data


def test_showcase_chat_rejects_blank_text(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        assert client.post("/showcase/chat", json={"request_text": " "}).status_code == 400


def test_showcase_skill_matrix(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.get("/showcase/skills")
        assert resp.status_code == 200
        skills = resp.json()["skills"]
        assert len(skills) >= 15
        assert {s["category"] for s in skills} == {"onetool", "ritual", "sound"}
        assert all(s["status"] in {"live", "demo", "planned"} for s in skills)


def test_showcase_weekly_ghostwriter_demo_route(tmp_path, monkeypatch):
    """OneTool demo flows short-circuit before Hermes — no Hermes needed."""
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        resp = client.post("/showcase/chat", json={"request_text": "周报还没写，帮我搞定"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "chat"
        assert data["selected_skill"] == "weekly_ghostwriter"
        assert data["skill_card"]["type"] == "weekly_draft"
        assert data["skill_card"]["rows"]
        assert data["planner_meta"]["planner_source"] == "skill_demo"
        assert any(c["name"].startswith("weekly_ghostwriter") for c in data["tool_calls"])


def test_showcase_okr_and_neisou_demo_routes(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        okr = client.post("/showcase/chat", json={"request_text": "这季度 OKR 感觉要完不成了"}).json()
        assert okr["skill_card"]["type"] == "okr_progress"
        assert okr["skill_card"]["krs"]
        # canned 内搜 demo only serves when the real service is unauthorized
        from types import SimpleNamespace
        from floppy_backend.main import state
        monkeypatch.setattr(state, "enterprise_search", SimpleNamespace(available=False))
        ns = client.post("/showcase/chat", json={"request_text": "差旅报销流程怎么走？"}).json()
        assert ns["skill_card"]["type"] == "neisou_answer"
        assert ns["skill_card"]["owner"]


def test_showcase_cbt_routes_to_dialog_not_audio(tmp_path, monkeypatch):
    """'来进行一次CBT吧' must be a conversation, never an audio generation."""
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        data = client.post("/showcase/chat", json={"request_text": "来进行一次CBT吧。"}).json()
        assert data["action"] == "chat"
        assert data["selected_skill"] == "reframe_thought"
        assert data["job_id"] is None


def test_attach_reply_audio_skips_tts_when_asset_already_plays(monkeypatch):
    """A response that already carries a playable asset (play_asset, a
    synchronous remix) must not also get a spoken reply_audio_url — both
    would start playing at once. The test env's audio provider has no TTS
    support either way, so this pins the *decision*, not just the output."""
    import floppy_backend.main as main_module

    calls: list[str] = []
    monkeypatch.setattr(main_module, "_reply_audio_url", lambda text: calls.append(text) or "http://fake/reply.mp3")

    with_asset = AgentDecideResponse.model_construct(reply="给你放一段《雨声》", asset=object())
    _attach_reply_audio(with_asset)
    assert with_asset.reply_audio_url is None
    assert calls == []

    without_asset = AgentDecideResponse.model_construct(reply="我在呢，想聊什么都可以。", asset=None)
    _attach_reply_audio(without_asset)
    assert without_asset.reply_audio_url == "http://fake/reply.mp3"
    assert calls == ["我在呢，想聊什么都可以。"]


def test_intranet_quick_pattern():
    from floppy_backend.showcase_skills import is_intranet_quick

    assert is_intranet_quick("食堂在哪")
    assert is_intranet_quick("班车几点发车？")
    assert is_intranet_quick("请假流程是什么")
    assert not is_intranet_quick("食堂的饭太难吃了，好烦")          # venting, no lookup intent
    assert not is_intranet_quick("今天好累")                        # no intranet noun
    assert not is_intranet_quick("我想跟你聊聊最近报销单据堆积带来的巨大压力和焦虑感受该怎么调节")  # too long


def test_showcase_neisou_fast_path_speaks_the_answer(tmp_path, monkeypatch):
    """食堂在哪 → deterministic real-search path: no decision LLM, and the
    reply carries the answer instead of a 稍等 promise."""
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        from types import SimpleNamespace
        from floppy_backend.main import state
        fake = SimpleNamespace(
            available=True,
            neisou=lambda q, **k: {"status": "ok", "results": [
                {"title": "百度生活小贴士", "url": "http://ku/x", "snippet": "食堂位置：1号楼与2号楼B1各有一个"},
            ]},
        )
        monkeypatch.setattr(state, "enterprise_search", fake)
        state.agent_runtime._enterprise = fake
        data = client.post("/showcase/chat", json={"request_text": "食堂在哪"}).json()
        assert data["planner_meta"]["planner_source"] == "neisou_fast"
        assert data["selected_skill"] == "neisou_answer"
        assert "1号楼" in data["reply"]
        assert "稍等" not in data["reply"]
        assert data["skill_card"]["results"][0]["url"] == "http://ku/x"


def test_showcase_nudge_scenarios(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        for scenario in ("post_meeting", "weekly_due"):
            resp = client.get(f"/showcase/nudge?scenario={scenario}")
            assert resp.status_code == 200
            assert resp.json()["title"]
        assert client.get("/showcase/nudge?scenario=nope").status_code == 404
