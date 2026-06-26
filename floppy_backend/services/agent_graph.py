"""LangGraph-based Agent decision graph.

Replaces the inline if/else orchestration in the /agent/decide endpoint.
P0: no persistent checkpointer; graph runs in-memory per request.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from floppy_backend.config import Settings
from floppy_backend.models import (
    AgentDecideRequest,
    AgentDecideResponse,
    AssetSearchFilters,
    AssetSearchRequest,
    AssetSearchResponse,
    AudioAsset,
    EventIn,
    GenerationBudget,
    GenerationRequest,
    NormalizedAudioRequest,
    PlannerMeta,
    ProfileContext,
)
from floppy_backend.repositories import Repository
from floppy_backend.services.generation import BudgetExceededError, GenerationService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.query_planner import QueryPlanner, RuleQueryPlanner, StructuredQuery
from floppy_backend.services.recommendation import RecommendationService
from floppy_backend.services.remix import RemixService
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json


# Remix intent keywords — user wants to add/adjust background on current asset
REMIX_KEYWORDS = ("加点", "加一点", "加个", "叠加", "背景音", "背景", "混音", "加上", "配上", "小一点", "大一点", "声音太干", "加雨", "加海", "加森林")


# ---------------------------------------------------------------------------
# Graph State
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    # Input
    request: AgentDecideRequest
    # Intermediate
    profile_context: ProfileContext
    normalized_request: NormalizedAudioRequest
    cache_key: str
    structured_query: StructuredQuery
    search_result: AssetSearchResponse
    planner_meta: dict
    is_remix_intent: bool
    remix_sound_type: str | None
    # Output
    action: str
    asset: AudioAsset | None
    job_id: str | None
    remix_job_id: str | None
    reasons: list[str]
    error: str | None


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------

class AgentGraphBuilder:
    def __init__(
        self,
        repository: Repository,
        storage: LocalFileStorage,
        normalizer: RequestNormalizer,
        recommendation_service: RecommendationService,
        generation_service: GenerationService,
        settings: Settings,
        query_planner: QueryPlanner | None = None,
        remix_service: RemixService | None = None,
    ):
        self._repo = repository
        self._storage = storage
        self._normalizer = normalizer
        self._rec = recommendation_service
        self._gen = generation_service
        self._remix = remix_service
        self._settings = settings
        self._planner = query_planner or RuleQueryPlanner()
        self._fallback_planner = RuleQueryPlanner()
        self._graph = self._build()

    # -- Nodes ----------------------------------------------------------------

    def _load_profile_context(self, state: AgentState) -> dict[str, Any]:
        req = state["request"]
        profile = self._repo.get_profile(req.user_id)
        if profile is None:
            return {"error": "profile not found"}
        used_chars, used_count = self._repo.generation_usage_since(req.user_id)
        budget = GenerationBudget(
            daily_remaining_chars=max(0, self._settings.daily_char_budget - used_chars),
            daily_generate_count_remaining=max(0, self._settings.daily_generate_count - used_count),
        )
        ctx = ProfileContext(**profile.model_dump(), generation_budget=budget)
        return {"profile_context": ctx}

    def _normalize_request(self, state: AgentState) -> dict[str, Any]:
        req = state["request"]
        profile = self._repo.get_profile(req.user_id)
        gen_req = GenerationRequest(request_text=req.request_text)
        normalized = self._normalizer.normalize(gen_req, profile)
        cache_key = sha256_json(normalized.model_dump(mode="json"))

        # Detect remix intent
        is_remix = req.current_asset_id and any(kw in req.request_text for kw in REMIX_KEYWORDS)
        remix_sound_type: str | None = None
        if is_remix:
            from floppy_backend.providers.ambient import detect_sound_type
            remix_sound_type = detect_sound_type(req.request_text, [])

        return {"normalized_request": normalized, "cache_key": cache_key, "is_remix_intent": is_remix, "remix_sound_type": remix_sound_type}

    def _search_assets(self, state: AgentState) -> dict[str, Any]:
        import time as _time
        req = state["request"]
        profile_ctx = state["profile_context"]

        # Dynamic available_tags from asset DB; fallback to constant
        db_tags = self._repo.list_available_tags()
        from floppy_backend.services.query_planner import AVAILABLE_TAGS
        available_tags = db_tags if db_tags else AVAILABLE_TAGS

        # AI query planner is primary; rule fallback on failure/low confidence
        planner_start = _time.perf_counter()
        fallback_reason: str | None = None
        try:
            sq = self._planner.plan(req.request_text, profile_ctx, available_tags=available_tags)
            if sq.confidence < self._settings.query_planner_confidence_threshold:
                fallback = self._fallback_planner.plan(req.request_text, profile_ctx, available_tags=available_tags)
                fallback_reason = "low_confidence_merged_rule"
                sq = StructuredQuery(
                    preferred_tags=sorted(set(sq.preferred_tags + fallback.preferred_tags)),
                    negative_tags=sorted(set(sq.negative_tags + fallback.negative_tags)),
                    mood=sq.mood or fallback.mood,
                    duration_hint_sec=sq.duration_hint_sec,
                    confidence=sq.confidence,
                    source="ai_fallback",
                    reason_codes=sq.reason_codes + [fallback_reason],
                )
        except Exception as exc:
            fallback_reason = f"ai_unavailable:{type(exc).__name__}"
            sq = self._fallback_planner.plan(req.request_text, profile_ctx, available_tags=available_tags)
            sq = StructuredQuery(
                preferred_tags=sq.preferred_tags,
                negative_tags=sq.negative_tags,
                mood=sq.mood,
                duration_hint_sec=sq.duration_hint_sec,
                confidence=sq.confidence,
                source="ai_fallback",
                reason_codes=sq.reason_codes + ["ai_unavailable"],
            )
        planner_latency_ms = int((_time.perf_counter() - planner_start) * 1000)

        search_result = self._rec.search(
            AssetSearchRequest(
                user_id=req.user_id,
                query=req.request_text,
                cache_key=state["cache_key"],
                filters=AssetSearchFilters(preferred_tags=sq.preferred_tags, negative_tags=sq.negative_tags),
                limit=3,
            )
        )
        for r in search_result.results:
            r.asset.playback_url = self._storage.public_url(r.asset.object_key)

        # Observability: enrich reasons with planner metadata
        planner_meta = {
            "planner_source": sq.source,
            "planner_confidence": sq.confidence,
            "planner_latency_ms": planner_latency_ms,
        }
        if fallback_reason:
            planner_meta["fallback_reason"] = fallback_reason

        return {"search_result": search_result, "structured_query": sq, "planner_meta": planner_meta}

    def _play_asset(self, state: AgentState) -> dict[str, Any]:
        req = state["request"]
        result = state["search_result"].results[0]
        self._repo.record_event(
            req.user_id,
            EventIn(event_type="recommendation_served", asset_id=result.asset.id, payload={"match_type": result.match_type, "score": result.score}),
        )
        return {"action": "play_asset", "asset": result.asset, "job_id": None, "remix_job_id": None, "reasons": result.reasons}

    def _no_match(self, state: AgentState) -> dict[str, Any]:
        return {"action": "no_match", "asset": None, "job_id": None, "remix_job_id": None, "reasons": ["资产库未命中，且未授权生成"]}

    def _create_generation_job(self, state: AgentState) -> dict[str, Any]:
        req = state["request"]
        self._gen.check_generation_budget(req.user_id)
        response = self._gen.enqueue_or_match(req.user_id, GenerationRequest(request_text=req.request_text, force_generate=True))
        return {"action": "generate_job", "asset": None, "job_id": response.job_id, "remix_job_id": None, "reasons": ["资产库未命中，已创建生成任务"]}

    def _remix_current(self, state: AgentState) -> dict[str, Any]:
        """Remix the current asset with an ambient layer (no TTS quota consumed)."""
        req = state["request"]
        sound_type = state.get("remix_sound_type") or "rain"
        if self._remix:
            job_id = self._repo.create_remix_job(
                req.user_id, req.current_asset_id, None, [],
                voice_volume=1.0, ambient_volume=0.3, sound_type=sound_type,
            )
            self._remix.run_remix(job_id)
            job = self._repo.get_remix_job(job_id)
            asset = job.output_asset if job and job.status == "succeeded" else None
            if asset:
                asset.playback_url = self._storage.public_url(asset.object_key)
            return {"action": "remix_current", "asset": asset, "job_id": None, "remix_job_id": job_id, "reasons": [f"已为当前音频添加{sound_type}背景"]}
        return {"action": "remix_current", "asset": None, "job_id": None, "remix_job_id": None, "reasons": ["remix service unavailable"]}

    # -- Conditional edge -----------------------------------------------------

    def _decide_route(self, state: AgentState) -> str:
        if state.get("error"):
            return "error_end"
        if state.get("is_remix_intent"):
            return "remix_current"
        search = state["search_result"]
        if search.hit and search.results:
            return "play_asset"
        if not state["request"].generation_allowed:
            return "no_match"
        return "generate"

    # -- Build ----------------------------------------------------------------

    def _build(self) -> Any:
        graph = StateGraph(AgentState)

        graph.add_node("load_profile_context", self._load_profile_context)
        graph.add_node("normalize_request", self._normalize_request)
        graph.add_node("search_assets", self._search_assets)
        graph.add_node("play_asset", self._play_asset)
        graph.add_node("no_match", self._no_match)
        graph.add_node("create_generation_job", self._create_generation_job)
        graph.add_node("remix_current", self._remix_current)

        graph.set_entry_point("load_profile_context")
        graph.add_edge("load_profile_context", "normalize_request")
        graph.add_edge("normalize_request", "search_assets")
        graph.add_conditional_edges(
            "search_assets",
            self._decide_route,
            {"play_asset": "play_asset", "no_match": "no_match", "generate": "create_generation_job", "remix_current": "remix_current", "error_end": END},
        )
        graph.add_edge("play_asset", END)
        graph.add_edge("no_match", END)
        graph.add_edge("create_generation_job", END)
        graph.add_edge("remix_current", END)

        return graph.compile()

    # -- Public API -----------------------------------------------------------

    def run(self, request: AgentDecideRequest) -> AgentDecideResponse:
        """Execute the graph synchronously and return the response."""
        result = self._graph.invoke({"request": request})

        if result.get("error"):
            raise ValueError(result["error"])

        return AgentDecideResponse(
            action=result["action"],
            normalized_request=result["normalized_request"],
            profile_context=result["profile_context"],
            search=result["search_result"],
            asset=result.get("asset"),
            job_id=result.get("job_id"),
            remix_job_id=result.get("remix_job_id"),
            reasons=result.get("reasons", []),
            planner_meta=PlannerMeta(**result["planner_meta"]) if result.get("planner_meta") else None,
        )
