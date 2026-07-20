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
