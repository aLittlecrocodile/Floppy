from __future__ import annotations

from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import app


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


def test_showcase_nudge_scenarios(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        for scenario in ("post_meeting", "weekly_due"):
            resp = client.get(f"/showcase/nudge?scenario={scenario}")
            assert resp.status_code == 200
            assert resp.json()["title"]
        assert client.get("/showcase/nudge?scenario=nope").status_code == 404
