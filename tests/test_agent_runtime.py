from __future__ import annotations

from datetime import datetime, timezone

import pytest

from floppy_backend.config import Settings
from floppy_backend.models import (
    AgentDecideRequest,
    AssetSearchFilters,
    AssetSearchResponse,
    AudioAssetFacets,
    AudioType,
    GenerationBudget,
    GenerationDirective,
    ProfileContext,
)
from floppy_backend.services.agent_runtime import AgentRuntimeDeps, build_agent_runtime


def _deps(settings: Settings) -> AgentRuntimeDeps:
    return AgentRuntimeDeps(
        repository=None,
        storage=None,
        request_defaults=None,
        asset_catalog_service=None,
        generation_service=None,
        remix_service=None,
        settings=settings,
    )


def test_hermes_is_the_only_agent_runtime():
    built = build_agent_runtime(_deps(Settings(agent_runtime="hermes")))

    assert built.runtime.__class__.__name__ == "HermesAgentRuntime"


def test_local_agent_runtime_is_removed():
    with pytest.raises(RuntimeError, match="LangGraph runtime has been removed"):
        build_agent_runtime(_deps(Settings(agent_runtime="local")))


def test_hermes_client_uses_structured_plan_and_decision_calls(monkeypatch):
    from floppy_backend.services.hermes_agent import HermesAgentClient

    captured = []

    class FakeResponse:
        def __init__(self, text: str):
            self._text = text

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": self._text,
                            }
                        ],
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        captured.append({"url": url, "json": json})
        if "search plan" in json["instructions"]:
            return FakeResponse(
                '{"query":"雨声","filters":{"type":"white_noise",'
                '"required_tags":["rain","no_voice"],"negative_tags":["voice_present"]},'
                '"reasons":["测试计划"],"confidence":0.9}'
            )
        return FakeResponse(
            '{"action":"generate_job",'
            '"selected_skill":"generate_sleep_audio",'
            '"reasons":["测试"],"confidence":0.8}'
        )

    monkeypatch.setattr("floppy_backend.services.hermes_agent.httpx.post", fake_post)
    client = HermesAgentClient(
        Settings(
            hermes_base_url="http://127.0.0.1:8642",
            hermes_api_key="test-key",
            hermes_model="DeepSeek-V4-Flash",
        )
    )
    profile_context = ProfileContext(
        user_id="u_hermes",
        segment="anxiety_relief",
        updated_at=datetime.now(timezone.utc),
        audio_type_preferences=[AudioType.MEDITATION],
        voice_preferences=["warm_female"],
        background_preferences=["rain_soft"],
        mood_tags=["anxiety_relief"],
        generation_budget=GenerationBudget(
            daily_remaining_chars=1000,
            daily_generate_count_remaining=3,
        ),
    )
    request = AgentDecideRequest(
        user_id="u_hermes",
        request_text="来一段雨声呼吸冥想",
    )

    search_plan = client.plan_search(
        request=request,
        profile_context=profile_context,
        facets=AudioAssetFacets(
            total_assets=1,
            asset_types=["white_noise"],
            tags=["rain", "no_voice", "voice_present"],
        ),
    )

    decision = client.decide(
        request=request,
        profile_context=profile_context,
        search=AssetSearchResponse(results=[], hit=False, best_score=None, threshold=0.58),
        search_plan=search_plan,
    )

    assert captured[0]["json"]["model"] == "DeepSeek-V4-Flash"
    assert captured[0]["json"]["tools"] == []
    assert captured[0]["json"]["tool_choice"] == "none"
    assert search_plan.filters.required_tags == ["rain", "no_voice"]
    assert captured[1]["json"]["tool_choice"] == "none"
    assert '"search_plan"' in captured[1]["json"]["input"]
    assert decision.action == "generate_job"


def test_hermes_client_repairs_high_confidence_empty_search_plan(monkeypatch):
    from floppy_backend.services.hermes_agent import HermesAgentClient

    captured = []

    class FakeResponse:
        def __init__(self, text: str):
            self._text = text

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": self._text}],
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        captured.append(json)
        if "修复器" in json["instructions"]:
            return FakeResponse(
                '{"query":"雨声","filters":{"type":"white_noise",'
                '"required_tags":["rain","no_voice"],'
                '"negative_tags":["voice_present","thunder","meditation"]},'
                '"reasons":["修复为空filters"],"confidence":0.95}'
            )
        return FakeResponse(
            '{"query":null,"filters":{},'
            '"reasons":["已识别rain/no_voice/thunder但误留空"],"confidence":0.9}'
        )

    monkeypatch.setattr("floppy_backend.services.hermes_agent.httpx.post", fake_post)
    client = HermesAgentClient(Settings(hermes_base_url="http://127.0.0.1:8642", hermes_api_key="test-key"))
    profile_context = ProfileContext(
        user_id="u_hermes",
        segment="anxiety_relief",
        updated_at=datetime.now(timezone.utc),
        audio_type_preferences=[AudioType.WHITE_NOISE],
        voice_preferences=["warm_female"],
        background_preferences=["rain_soft"],
        mood_tags=["anxiety_relief"],
        generation_budget=GenerationBudget(
            daily_remaining_chars=1000,
            daily_generate_count_remaining=3,
        ),
    )

    plan = client.plan_search(
        request=AgentDecideRequest(
            user_id="u_hermes",
            request_text="给我放雨声，不要人声，不要雷声",
        ),
        profile_context=profile_context,
        facets=AudioAssetFacets(
            total_assets=2,
            asset_types=["white_noise", "meditation"],
            tags=["rain", "no_voice", "voice_present", "thunder"],
        ),
    )

    assert len(captured) == 2
    assert plan.filters.type == AudioType.WHITE_NOISE
    assert plan.filters.required_tags == ["rain", "no_voice"]
    assert "thunder" in plan.filters.negative_tags


def test_agent_decide_can_run_on_hermes_without_local_graph(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from floppy_backend.config import get_settings
    from floppy_backend.main import app
    from floppy_backend.services.hermes_agent import HermesDecision

    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("FLOPPY_AGENT_RUNTIME", "hermes")
    get_settings.cache_clear()

    def fake_plan_search(self, *, request, profile_context, facets):
        from floppy_backend.services.hermes_agent import HermesSearchPlan

        return HermesSearchPlan(
            query="雨声呼吸冥想",
            filters=AssetSearchFilters(type=AudioType.MEDITATION, required_tags=["rain"]),
            reasons=["测试搜索计划"],
            confidence=0.9,
        )

    def fake_decide(self, *, request, profile_context, search, search_plan=None):
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
        "floppy_backend.services.hermes_agent.HermesAgentClient.plan_search",
        fake_plan_search,
    )
    monkeypatch.setattr(
        "floppy_backend.services.hermes_agent.HermesAgentClient.decide",
        fake_decide,
    )

    with TestClient(app) as client:
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


def test_hermes_search_does_not_prefilter_with_request_defaults(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from floppy_backend.config import get_settings
    from floppy_backend.main import app
    from floppy_backend.services.hermes_agent import HermesDecision

    captured = {}

    def fake_search(self, request):
        captured["request"] = request
        return AssetSearchResponse(results=[], hit=False, best_score=None, threshold=0.58)

    def fake_plan_search(self, *, request, profile_context, facets):
        from floppy_backend.services.hermes_agent import HermesSearchPlan

        return HermesSearchPlan(
            query="雨声",
            filters=AssetSearchFilters(
                type=AudioType.WHITE_NOISE,
                required_tags=["rain", "no_voice"],
                negative_tags=["voice_present", "meditation"],
            ),
            reasons=["Hermes 将用户原话转成结构化资源过滤器"],
            confidence=0.95,
        )

    def fake_decide(self, *, request, profile_context, search, search_plan=None):
        return HermesDecision(
            action="no_match",
            selected_skill="no_match",
            reasons=["测试无需真实 Hermes"],
            confidence=0.7,
        )

    monkeypatch.setattr("floppy_backend.services.asset_catalog.AssetCatalogService.search", fake_search)
    monkeypatch.setattr("floppy_backend.services.hermes_agent.HermesAgentClient.plan_search", fake_plan_search)
    monkeypatch.setattr("floppy_backend.services.hermes_agent.HermesAgentClient.decide", fake_decide)
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile_payload = {
            "audio_type_preferences": ["meditation", "white_noise"],
            "voice_preferences": ["warm_female"],
            "background_preferences": ["rain_soft"],
            "duration_preference_min": 15,
            "stress_level": "medium",
            "anxiety_level": "medium",
            "avg_sleep_latency_min": 25,
            "mood_tags": ["calm"],
        }
        assert client.put("/users/u_white_noise/profile", json=profile_payload).status_code == 200
        response = client.post(
            "/agent/decide",
            json={
                "user_id": "u_white_noise",
                "request_text": "给我放雨声，不要冥想，不要人声",
                "generation_allowed": False,
            },
        )

    assert response.status_code == 200
    assert captured["request"].query == "雨声"
    assert captured["request"].filters.type == AudioType.WHITE_NOISE
    assert captured["request"].filters.required_tags == ["rain", "no_voice"]
    assert "meditation" in captured["request"].filters.negative_tags
