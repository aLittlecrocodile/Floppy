from __future__ import annotations

from floppy_backend.config import Settings
from floppy_backend.models import AgentDecideRequest, GenerationDirective, AudioType
from floppy_backend.services import agent_runtime
from floppy_backend.services.agent_runtime import AgentRuntimeDeps, build_agent_runtime


class DummyRuntime:
    def run(self, request: AgentDecideRequest):
        raise NotImplementedError


def _deps(settings: Settings) -> AgentRuntimeDeps:
    return AgentRuntimeDeps(
        repository=None,
        storage=None,
        normalizer=None,
        recommendation_service=None,
        generation_service=None,
        remix_service=None,
        settings=settings,
        directive_planner=None,
    )


def test_local_runtime_uses_local_agent(monkeypatch):
    local_agent = DummyRuntime()
    monkeypatch.setattr(agent_runtime, "_build_local_agent", lambda deps: local_agent)

    built = build_agent_runtime(_deps(Settings(agent_runtime="local")))

    assert built.runtime is local_agent
    assert built.local_agent is local_agent


def test_hermes_without_fallback_does_not_build_local_agent(monkeypatch):
    def fail_if_called(deps):
        raise AssertionError("local graph should not be built")

    monkeypatch.setattr(agent_runtime, "_build_local_agent", fail_if_called)

    built = build_agent_runtime(
        _deps(Settings(agent_runtime="hermes", hermes_fallback_to_local=False))
    )

    assert built.local_agent is None
    assert built.runtime.__class__.__name__ == "HermesAgentRuntime"


def test_hermes_with_fallback_builds_local_agent(monkeypatch):
    local_agent = DummyRuntime()
    monkeypatch.setattr(agent_runtime, "_build_local_agent", lambda deps: local_agent)

    built = build_agent_runtime(
        _deps(Settings(agent_runtime="hermes", hermes_fallback_to_local=True))
    )

    assert built.local_agent is local_agent
    assert built.runtime.__class__.__name__ == "HermesAgentRuntime"


def test_agent_decide_can_run_on_hermes_without_local_graph(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from floppy_backend.config import get_settings
    from floppy_backend.main import app, state
    from floppy_backend.services.hermes_agent import HermesDecision

    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("FLOPPY_AGENT_RUNTIME", "hermes")
    monkeypatch.setenv("FLOPPY_HERMES_FALLBACK_TO_LOCAL", "false")
    get_settings.cache_clear()

    def fake_decide(self, *, request, profile_context, search):
        return HermesDecision(
            action="generate_job",
            selected_skill="generate_sleep_audio",
            directive=GenerationDirective(
                intent=AudioType.MEDITATION,
                content_brief="雨声背景下的睡前呼吸冥想",
                outline=["安顿身体", "放慢呼吸", "进入睡眠"],
                confidence=0.9,
                source="hermes",
            ),
            reasons=["Hermes 选择生成新的助眠音频"],
            confidence=0.9,
        )

    monkeypatch.setattr(
        "floppy_backend.services.hermes_agent.HermesAgentClient.decide",
        fake_decide,
    )

    with TestClient(app) as client:
        assert state.agent_graph is None
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
        assert client.put("/users/u_hermes/profile", json=profile_payload).status_code == 200

        response = client.post(
            "/agent/decide",
            json={"user_id": "u_hermes", "request_text": "来一段雨声呼吸冥想"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "generate_job"
    assert body["selected_skill"] == "generate_sleep_audio"
    assert body["planner_meta"]["planner_source"] == "hermes"
    assert body["planner_meta"]["planner_confidence"] == 0.9
    assert body["tool_calls"][0]["name"] == "hermes_agent"
    assert body["tool_calls"][1]["name"] == "generate_sleep_audio"
