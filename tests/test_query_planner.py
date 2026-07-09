"""Tests for AI Query Planner — mock HTTP, no real network calls."""
from __future__ import annotations

import json
import unittest.mock
import urllib.error

import pytest

from floppy_backend.models import AudioType, GenerationBudget, ProfileContext, ProfileLevel
from floppy_backend.services.query_planner import AVAILABLE_TAGS, AIQueryPlanner, PlannerTruncatedError, RuleQueryPlanner, StructuredQuery, build_query_planner


def _profile() -> ProfileContext:
    return ProfileContext(
        user_id="u_test",
        audio_type_preferences=[AudioType.MEDITATION],
        voice_preferences=["warm_female"],
        background_preferences=["rain_soft"],
        duration_preference_min=15,
        stress_level=ProfileLevel.HIGH,
        anxiety_level=ProfileLevel.HIGH,
        avg_sleep_latency_min=40,
        mood_tags=["anxiety_relief"],
        segment="anxiety_relief",
        algo_segment=None,
        tonight_mood=None,
        tonight_stress=None,
        profile_version=1,
        updated_at="2026-06-21T00:00:00",
        generation_budget=GenerationBudget(daily_remaining_chars=100000, daily_generate_count_remaining=5),
    )


def _mock_llm_response(content: str):
    """Create a mock urlopen context manager returning given content."""
    resp_body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    mock_resp = unittest.mock.MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)
    mock_resp.read.return_value = resp_body
    return mock_resp


class TestAIQueryPlannerSuccess:
    def test_valid_response_returns_structured_query(self):
        planner = AIQueryPlanner(api_key="test-key")
        llm_output = json.dumps({
            "preferred_tags": ["breathing", "grounding", "low_stimulation"],
            "negative_tags": ["high_energy"],
            "mood": ["calm"],
            "duration_hint_sec": 900,
            "confidence": 0.88,
            "reason_codes": ["extracted_from_request"],
        })

        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response(llm_output)):
            result = planner.plan("呼吸冥想放松", _profile())

        assert result.source == "ai"
        assert result.confidence == 0.88
        assert "breathing" in result.preferred_tags
        assert "high_energy" in result.negative_tags
        assert all(t in AVAILABLE_TAGS for t in result.preferred_tags)

    def test_markdown_fenced_json_is_parsed(self):
        planner = AIQueryPlanner(api_key="test-key")
        inner = json.dumps({"preferred_tags": ["rain", "nature"], "negative_tags": [], "confidence": 0.9, "reason_codes": ["ai"]})
        fenced = f"```json\n{inner}\n```"

        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response(fenced)):
            result = planner.plan("雨声", _profile())

        assert "rain" in result.preferred_tags


class TestAIQueryPlannerInvalidTags:
    def test_invalid_tags_stripped(self):
        planner = AIQueryPlanner(api_key="test-key")
        llm_output = json.dumps({
            "preferred_tags": ["breathing", "INVALID_TAG_XYZ", "grounding"],
            "negative_tags": ["NOT_REAL"],
            "confidence": 0.8,
            "reason_codes": ["ai"],
        })

        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response(llm_output)):
            result = planner.plan("test", _profile())

        assert "INVALID_TAG_XYZ" not in result.preferred_tags
        assert "NOT_REAL" not in result.negative_tags
        assert "breathing" in result.preferred_tags

    def test_all_invalid_tags_sets_zero_confidence(self):
        planner = AIQueryPlanner(api_key="test-key")
        llm_output = json.dumps({
            "preferred_tags": ["FAKE1", "FAKE2"],
            "negative_tags": [],
            "confidence": 0.9,
            "reason_codes": ["ai"],
        })

        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response(llm_output)):
            result = planner.plan("test", _profile())

        assert result.confidence == 0.0
        assert "all_tags_invalid" in result.reason_codes


class TestAIQueryPlannerFallback:
    def test_timeout_raises(self):
        planner = AIQueryPlanner(api_key="test-key", timeout_sec=0.1)

        with unittest.mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with pytest.raises(TimeoutError):
                planner.plan("test", _profile())

    def test_http_error_raises(self):
        planner = AIQueryPlanner(api_key="test-key")
        err = urllib.error.HTTPError(url="", code=500, msg="ISE", hdrs=None, fp=None)  # type: ignore[arg-type]
        err.read = lambda: b"server error"

        with unittest.mock.patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(urllib.error.HTTPError):
                planner.plan("test", _profile())

    def test_invalid_json_raises(self):
        planner = AIQueryPlanner(api_key="test-key")

        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response("not json at all no braces")):
            with pytest.raises((json.JSONDecodeError, ValueError)):
                planner.plan("test", _profile())

    def test_empty_content_with_reasoning_content_fallback(self):
        planner = AIQueryPlanner(api_key="test-key")
        inner = json.dumps({"preferred_tags": ["rain"], "negative_tags": [], "confidence": 0.7, "reason_codes": ["ai"]})
        resp_body = json.dumps({"choices": [{"message": {"content": "", "reasoning_content": inner}}]}).encode()
        mock_resp = unittest.mock.MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        mock_resp.read.return_value = resp_body

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            result = planner.plan("雨声", _profile())
        assert "rain" in result.preferred_tags

    def test_json_with_surrounding_noise(self):
        planner = AIQueryPlanner(api_key="test-key")
        inner = json.dumps({"preferred_tags": ["breathing", "grounding"], "negative_tags": [], "confidence": 0.8, "reason_codes": ["ai"]})
        noisy = f"Here is the result:\n{inner}\nHope this helps!"

        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response(noisy)):
            result = planner.plan("test", _profile())
        assert "breathing" in result.preferred_tags
        assert result.confidence == 0.8

    def test_completely_empty_content_raises(self):
        planner = AIQueryPlanner(api_key="test-key")
        resp_body = json.dumps({"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}).encode()
        mock_resp = unittest.mock.MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        mock_resp.read.return_value = resp_body

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ValueError, match="empty content"):
                planner.plan("test", _profile())

    def test_finish_reason_length_empty_content_raises_truncated(self):
        planner = AIQueryPlanner(api_key="test-key")
        resp_body = json.dumps({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}).encode()
        mock_resp = unittest.mock.MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        mock_resp.read.return_value = resp_body

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(PlannerTruncatedError, match="finish_reason=length"):
                planner.plan("test", _profile())

    def test_finish_reason_length_invalid_json_raises_truncated(self):
        planner = AIQueryPlanner(api_key="test-key")
        resp_body = json.dumps({"choices": [{"message": {"content": "partial json {"}, "finish_reason": "length"}]}).encode()
        mock_resp = unittest.mock.MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        mock_resp.read.return_value = resp_body

        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(PlannerTruncatedError, match="finish_reason=length"):
                planner.plan("test", _profile())


class TestDefaultConfig:
    def test_default_model_is_deepseek(self):
        from floppy_backend.config import Settings
        s = Settings()
        assert s.query_planner_model == "DeepSeek-V4-Flash"

    def test_default_timeout_is_8(self):
        from floppy_backend.config import Settings
        s = Settings()
        assert s.query_planner_timeout_sec == 8.0

    def test_default_max_tokens_is_5000(self):
        from floppy_backend.config import Settings
        s = Settings()
        assert s.query_planner_max_tokens == 5000

    def test_ai_planner_default_params(self):
        p = AIQueryPlanner(api_key="test-key")
        assert p._model == "DeepSeek-V4-Flash"
        assert p._timeout_sec == 8.0
        assert p._max_tokens == 5000


class TestResponseFormatPayload:
    def test_payload_includes_response_format(self):
        planner = AIQueryPlanner(api_key="test-key")
        llm_output = json.dumps({"preferred_tags": ["rain"], "negative_tags": [], "confidence": 0.9, "reason_codes": ["ai"]})

        captured = {}

        def capture_urlopen(req, **kwargs):
            captured["body"] = json.loads(req.data.decode())
            return _mock_llm_response(llm_output)

        with unittest.mock.patch("urllib.request.urlopen", side_effect=capture_urlopen):
            planner.plan("test", _profile())

        assert captured["body"]["response_format"] == {"type": "json_object"}
        assert captured["body"]["max_tokens"] == 5000
        assert captured["body"]["temperature"] == 0.1


class TestBuildQueryPlanner:
    def test_default_returns_rule(self):
        p = build_query_planner("rule")
        assert isinstance(p, RuleQueryPlanner)

    def test_ai_without_key_raises(self):
        with pytest.raises(RuntimeError, match="FLOPPY_QUERY_PLANNER_API_KEY"):
            build_query_planner("ai", api_key=None)

    def test_ai_with_key_returns_ai_planner(self):
        p = build_query_planner("ai", api_key="test-key")
        assert isinstance(p, AIQueryPlanner)


class TestDynamicAvailableTags:
    def test_custom_tags_used_for_validation(self):
        planner = AIQueryPlanner(api_key="test-key")
        custom_tags = {"custom_a", "custom_b", "breathing"}
        llm_output = json.dumps({
            "preferred_tags": ["custom_a", "breathing", "INVALID"],
            "negative_tags": ["custom_b"],
            "confidence": 0.9,
            "reason_codes": ["ai"],
        })
        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response(llm_output)):
            result = planner.plan("test", _profile(), available_tags=custom_tags)
        assert "custom_a" in result.preferred_tags
        assert "breathing" in result.preferred_tags
        assert "INVALID" not in result.preferred_tags
        assert "custom_b" in result.negative_tags

    def test_empty_db_tags_uses_fallback_constant(self):
        planner = AIQueryPlanner(api_key="test-key")
        llm_output = json.dumps({
            "preferred_tags": ["rain", "nature"],
            "negative_tags": [],
            "confidence": 0.85,
            "reason_codes": ["ai"],
        })
        # Pass None → falls back to AVAILABLE_TAGS
        with unittest.mock.patch("urllib.request.urlopen", return_value=_mock_llm_response(llm_output)):
            result = planner.plan("test", _profile(), available_tags=None)
        assert "rain" in result.preferred_tags


class TestHermesDecisionLayer:
    """Hermes is now the sole decision layer; the runtime must survive both a
    working Hermes (autonomous asset pick) and an unreachable one (degraded
    no_match), without any local rule fallback."""

    def test_hermes_pick_and_degraded_fallback(self, tmp_path, monkeypatch):
        from floppy_backend.config import get_settings
        from floppy_backend.main import app, state
        from floppy_backend.services.hermes_agent import HermesDecision
        from fastapi.testclient import TestClient

        monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
        monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
        get_settings.cache_clear()

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

        class StubClient:
            def __init__(self, decision=None, exc=None):
                self.decision = decision
                self.exc = exc

            def decide(self, **kwargs):
                if self.exc:
                    raise self.exc
                return self.decision

        with TestClient(app) as client:
            assert client.put("/users/u_obs/profile", json=profile_payload).status_code == 200

            # Seed one catalog asset directly (file-backed seeding needs real
            # audio sources that aren't present in the tmp test env).
            from floppy_backend.models import AudioAssetIn, AudioType
            state.repository.upsert_asset(
                AudioAssetIn(
                    type=AudioType.MEDITATION,
                    title="呼吸冥想·测试",
                    object_key="ondemand/test/breath.mp3",
                    duration_sec=600,
                    voice_id="warm_female",
                    prompt_hash="test-prompt-hash",
                    content_hash="test-content-hash",
                    mood_tags=["calm"],
                    tags=["meditation", "rain"],
                    user_segment_tags=["anxiety_relief"],
                    quality_score=0.9,
                    embedding=[0.0] * 32,
                    created_by="ondemand",
                )
            )
            # Catalog pools skip assets whose file is missing — write a dummy.
            state.storage.path_for("ondemand/test/breath.mp3").write_bytes(b"\x00")

            # Hermes autonomously picks an asset — no score threshold gate.
            asset = state.agent_runtime._catalog_candidates()[0]
            state.agent_runtime._client = StubClient(
                decision=HermesDecision(action="play_asset", asset_id=asset.id, reasons=["测试"], confidence=0.9)
            )
            resp = client.post("/agent/decide", json={"user_id": "u_obs", "request_text": "呼吸冥想引导放松压力释放"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["action"] == "play_asset"
            assert body["asset"]["id"] == asset.id
            assert body["planner_meta"]["planner_source"] == "hermes"

            # Hermes unreachable → degraded no_match with fallback_reason.
            state.agent_runtime._client = StubClient(exc=RuntimeError("connection refused"))
            resp = client.post("/agent/decide", json={"user_id": "u_obs", "request_text": "来一段海边篝火白噪音"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["action"] == "no_match"
            assert "hermes_unavailable" in body["planner_meta"]["fallback_reason"]
