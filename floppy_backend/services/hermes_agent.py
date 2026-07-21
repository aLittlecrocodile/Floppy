from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from floppy_backend.config import Settings
from floppy_backend.models import (
    AgentDecideRequest,
    AgentDecideResponse,
    AgentToolCall,
    AssetSearchResponse,
    AssetSearchResult,
    AudioAsset,
    EventIn,
    GenerationBudget,
    GenerationDirective,
    GenerationRequest,
    NormalizedAudioRequest,
    PlannerMeta,
    ProfileCheckinIn,
    ProfileContext,
    UserProfileIn,
)
from floppy_backend.repositories import Repository
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.library import LibraryService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.remix import RemixService
from floppy_backend.storage import LocalFileStorage


_ACTIONS = {
    "chat", "play_asset", "generate_job", "remix_current", "no_match",
    # ritual actions — executed locally, surfaced to clients as action="chat"
    "mood_checkin", "worry_parking", "gratitude_moment", "update_preference", "sleep_timer",
    "neisou_search",
}
_RITUAL_ACTIONS = {"mood_checkin", "worry_parking", "gratitude_moment", "update_preference", "sleep_timer"}
_ACTION_ALIASES = {
    "generate_sleep_audio": "generate_job",
    "play_audio_asset": "play_asset",
    "search_audio_asset": "play_asset",
    "remix_audio": "remix_current",
    "reply": "chat",
    "talk": "chat",
}


def _explicit_generation_requested(text: str) -> bool:
    compact = "".join(text.lower().split())
    if any(negative in compact for negative in ("不用生成", "不要生成", "别生成")):
        return False
    return any(
        phrase in compact
        for phrase in (
            "给我生成",
            "帮我生成",
            "我要生成",
            "生成一",
            "生成个",
            "重新生成",
            "再生成",
            "创作一",
            "写一首",
            "做一段",
        )
    )


class HermesDecision(BaseModel):
    action: str
    selected_skill: str | None = None
    asset_id: str | None = None
    remix_sound_type: str | None = None
    directive: GenerationDirective | None = None
    reply: str | None = None  # user-facing sentence, present on every action
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    # ritual-action payloads
    mood_score: int | None = Field(default=None, ge=1, le=10)
    worry_text: str | None = None
    gratitude_items: list[str] = Field(default_factory=list)
    profile_patch: dict[str, Any] | None = None
    timer_sec: int | None = Field(default=None, ge=60, le=7200)
    fade_out: bool = True
    search_query: str | None = None

    def normalized_action(self) -> str:
        action = _ACTION_ALIASES.get(self.action, self.action)
        if action not in _ACTIONS:
            raise ValueError(f"unsupported Hermes action: {self.action}")
        return action

    def skill_name(self) -> str:
        if self.selected_skill:
            return self.selected_skill
        action = self.normalized_action()
        return {
            "chat": "chat",
            "play_asset": "play_asset",
            "generate_job": "generate_sleep_audio",
            "remix_current": "remix_current",
            "no_match": "no_match",
        }.get(action, action)


class HermesAgentClient:
    """Thin client for Hermes Agent's OpenAI-compatible API server."""

    def __init__(self, settings: Settings):
        self._base_url = settings.hermes_base_url.rstrip("/")
        self._responses_url = f"{self._base_url}/responses" if self._base_url.endswith("/v1") else f"{self._base_url}/v1/responses"
        self._chat_url = f"{self._base_url}/chat/completions" if self._base_url.endswith("/v1") else f"{self._base_url}/v1/chat/completions"
        self._api_key = settings.hermes_api_key or settings.query_planner_api_key
        self._model = settings.hermes_model
        self._api_style = settings.hermes_api_style.strip().lower()
        if self._api_style not in {"responses", "chat"}:
            raise ValueError("FLOPPY_HERMES_API_STYLE must be 'responses' or 'chat'")
        # connect=3s: a black-holed Hermes must fail fast (3s, not 30s);
        # the configured timeout still governs read/write/pool.
        self._timeout = httpx.Timeout(settings.hermes_timeout_sec, connect=3.0)
        self._store = settings.hermes_store_conversation

    def decide(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        candidates: list[AudioAsset],
        extras: dict[str, Any] | None = None,
    ) -> HermesDecision:
        prompt = _build_decision_prompt(request, profile_context, candidates, extras)
        headers = {
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": f"floppy-agent:{request.user_id}",
            "X-Hermes-Session-Key": f"floppy:user:{request.user_id}",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        if self._api_style == "chat":
            response = httpx.post(
                self._chat_url,
                headers=headers,
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _HERMES_DECISION_INSTRUCTIONS},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "max_tokens": 1200,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            text = _chat_output_text(response.json())
        else:
            response = httpx.post(
                self._responses_url,
                headers=headers,
                json={
                    "model": self._model,
                    "input": prompt,
                    "instructions": _HERMES_DECISION_INSTRUCTIONS,
                    "store": self._store,
                    "conversation": f"floppy-agent:{request.user_id}",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            text = _responses_output_text(response.json())

        payload = _extract_json_object(text)
        decision = HermesDecision.model_validate(payload)
        decision.normalized_action()
        return decision


class HermesAgentRuntime:
    """The decision layer: Hermes decides, Floppy executes workflows.

    Matching is agent-driven — Hermes sees the (capped) asset catalog and
    autonomously picks the asset to play; there is no scoring algorithm or
    hit threshold gating its choice. Two deterministic guards remain:

    - exact prompt_hash cache hit short-circuits before Hermes (cost control:
      the same request never regenerates paid TTS audio);
    - a play_asset decision must reference a real catalog asset_id, otherwise
      it is downgraded to generate_job / no_match.

    On Hermes failure the runtime degrades to no_match (with fallback_reason)
    instead of guessing — there is no local rule-based fallback anymore.
    """

    def __init__(
        self,
        *,
        repository: Repository,
        storage: LocalFileStorage,
        normalizer: RequestNormalizer,
        generation_service: GenerationService,
        remix_service: RemixService,
        library: LibraryService,
        settings: Settings,
        directive_planner=None,
        weather=None,
        enterprise_search=None,
    ):
        self._repo = repository
        self._storage = storage
        self._normalizer = normalizer
        self._gen = generation_service
        self._remix = remix_service
        self._library = library
        self._settings = settings
        self._directive_planner = directive_planner
        self._weather = weather
        self._enterprise = enterprise_search
        self._client = HermesAgentClient(settings)

    def run(self, request: AgentDecideRequest) -> AgentDecideResponse:
        started = time.perf_counter()
        profile_context = self._profile_context(request.user_id)
        normalized = self._normalizer.normalize(
            GenerationRequest(request_text=request.request_text), profile_context
        )
        cache_key = self._gen.cache_key_for(normalized, request_text=request.request_text)

        # Short-circuit ONLY on a verbatim repeat of a request that already
        # generated this asset. The cache key comes from lossy normalization —
        # unrelated requests can collapse onto the same key (e.g. "来段脱口秀"
        # and "生成助眠音频" both normalize to profile defaults), and those must
        # go to Hermes, which sees the cached asset among its candidates anyway.
        exact = self._repo.get_asset_by_prompt_hash(cache_key)
        if exact is not None and not self._asset_file_exists(exact):
            exact = None  # stale DB row — the audio file is gone, never serve it
        if (
            exact is not None
            and not _explicit_generation_requested(request.request_text)
            and self._repo.has_generation_request(cache_key, request.request_text)
        ):
            return self._exact_cache_response(request, profile_context, normalized, exact)

        candidates = self._catalog_candidates()
        extras = self._decision_extras(request.user_id)
        decision = None
        last_exc: Exception | None = None
        for _ in range(2):  # one retry — Hermes/LLM cold-start hiccups are transient
            try:
                decision = self._client.decide(
                    request=request, profile_context=profile_context,
                    candidates=candidates, extras=extras,
                )
                break
            except Exception as exc:  # noqa: BLE001 — network/parse/validation errors from Hermes
                last_exc = exc
        if decision is None:
            return self._degraded_response(
                request, profile_context, normalized, candidates, last_exc,
                int((time.perf_counter() - started) * 1000),
            )
        hermes_latency_ms = int((time.perf_counter() - started) * 1000)
        return self._execute_decision(
            request=request,
            profile_context=profile_context,
            normalized=normalized,
            candidates=candidates,
            decision=decision,
            hermes_latency_ms=hermes_latency_ms,
        )

    # -- Context & candidates ---------------------------------------------

    def _profile_context(self, user_id: str) -> ProfileContext:
        profile = self._repo.get_profile(user_id)
        if profile is None:
            raise ValueError("profile not found")
        used_chars, used_count = self._repo.generation_usage_since(user_id)
        return ProfileContext(
            **profile.model_dump(),
            generation_budget=GenerationBudget(
                daily_remaining_chars=max(0, self._settings.daily_char_budget - used_chars),
                daily_generate_count_remaining=max(0, self._settings.daily_generate_count - used_count),
            ),
        )

    def _catalog_candidates(self) -> list[AudioAsset]:
        return self._library.agent_candidates()

    def _asset_file_exists(self, asset: AudioAsset) -> bool:
        try:
            return self._storage.existing_path_for(asset.object_key).exists()
        except (ValueError, OSError):
            return False

    def _decision_extras(self, user_id: str) -> dict[str, Any]:
        """Real-world context injected into the decision prompt: weather,
        recent ritual events, and 7-day listening stats. Each part is
        best-effort — failures degrade to absence, never block a turn."""
        extras: dict[str, Any] = {}
        try:
            if self._weather is not None and self._settings.weather_city:
                snap = self._weather.snapshot(self._settings.weather_city)
                if snap:
                    extras["weather"] = snap
        except Exception:  # noqa: BLE001
            pass
        try:
            rituals = self._repo.recent_events(
                user_id, ["worry_parked", "gratitude", "mood_checkin"], limit=6
            )
            if rituals:
                extras["recent_rituals"] = rituals
        except Exception:  # noqa: BLE001
            pass
        try:
            records = self._repo.list_playback_history(user_id, limit=50)
            week_ago = time.time() - 7 * 86400
            recent = [r for r in records if r.started_at.timestamp() > week_ago]
            if recent:
                extras["listen_stats"] = {
                    "plays_7d": len(recent),
                    "days_7d": len({r.started_at.date().isoformat() for r in recent}),
                    "recent_titles": [r.title for r in recent[:3] if r.title],
                }
        except Exception:  # noqa: BLE001
            pass
        return extras

    def _execute_ritual(
        self,
        *,
        action: str,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        normalized: NormalizedAudioRequest,
        candidates: list[AudioAsset],
        decision: HermesDecision,
        planner_meta: PlannerMeta,
        hermes_call: AgentToolCall,
    ) -> AgentDecideResponse:
        """Execute a ritual action for real (events / profile writes), then
        answer as a chat turn (stable client contract) with a receipt card."""
        started = time.perf_counter()
        skill = action
        card_lines: list[str] = []
        card_title = ""
        card_extra: dict[str, Any] = {}
        tool_input: dict[str, Any] = {}
        tool_output: dict[str, Any] = {}
        timer_sec = None
        fade_out = None

        if action == "mood_checkin":
            score = decision.mood_score or 5
            self._repo.update_profile_checkin(
                request.user_id, ProfileCheckinIn(tonight_mood=f"{score}/10")
            )
            self._repo.record_event(
                request.user_id, EventIn(event_type="mood_checkin", payload={"score": score})
            )
            total = len(self._repo.recent_events(request.user_id, ["mood_checkin"], limit=200))
            card_title = "心情打卡"
            card_lines = [f"今天 {score} / 10 分", f"这是我们一起记下的第 {total} 次"]
            tool_input, tool_output = {"score": score}, {"total_checkins": total}
        elif action == "worry_parking":
            text = (decision.worry_text or request.request_text).strip()[:120]
            self._repo.record_event(
                request.user_id, EventIn(event_type="worry_parked", payload={"text": text})
            )
            card_title = "烦恼寄存"
            card_lines = [f"「{text}」", "已由 Unwind 保管，到点再还给你"]
            card_extra = {"worry_text": text}  # frontend shredder animation
            tool_input, tool_output = {"text": text}, {"parked": True}
        elif action == "gratitude_moment":
            items = [i.strip()[:80] for i in decision.gratitude_items if i.strip()][:3]
            if not items:
                items = [request.request_text.strip()[:80]]
            self._repo.record_event(
                request.user_id, EventIn(event_type="gratitude", payload={"items": items})
            )
            card_title = "今日三件好事"
            card_lines = [f"· {item}" for item in items]
            tool_input, tool_output = {"items": items}, {"count": len(items)}
        elif action == "update_preference":
            patch = _whitelist_profile_patch(decision.profile_patch or {})
            if patch:
                profile = self._repo.get_profile(request.user_id)
                merged = profile.model_dump()
                for key, value in patch.items():
                    if isinstance(merged.get(key), list) and isinstance(value, list):
                        merged[key] = list(dict.fromkeys([*merged[key], *value]))
                    else:
                        merged[key] = value
                profile_in = UserProfileIn(**{k: merged[k] for k in UserProfileIn.model_fields})
                self._repo.upsert_profile(request.user_id, profile_in, profile.segment)
                profile_context = self._profile_context(request.user_id)
            self._repo.record_event(
                request.user_id, EventIn(event_type="preference_updated", payload={"patch": patch})
            )
            card_title = "偏好已更新"
            card_lines = [f"{k}：{v}" for k, v in patch.items()] or ["本次没有可更新的白名单字段"]
            tool_input, tool_output = {"patch": decision.profile_patch}, {"applied": patch}
        elif action == "sleep_timer":
            timer_sec = decision.timer_sec or 1200
            fade_out = decision.fade_out
            self._repo.record_event(
                request.user_id,
                EventIn(event_type="sleep_timer", asset_id=request.current_asset_id,
                        payload={"timer_sec": timer_sec, "fade_out": fade_out}),
            )
            card_title = "定时渐弱"
            card_lines = [f"{timer_sec // 60} 分钟后声音慢慢淡出", "由播放器本地执行，不打扰你"]
            tool_input = {"timer_sec": timer_sec, "fade_out": fade_out}
            tool_output = {"armed": request.current_asset_id is not None}

        return AgentDecideResponse(
            action="chat",
            normalized_request=normalized,
            profile_context=profile_context,
            search=self._search_view(candidates),
            asset=None,
            reply=decision.reply,
            reasons=decision.reasons or [f"执行仪式技能 {skill}"],
            planner_meta=planner_meta,
            selected_skill=skill,
            timer_sec=timer_sec,
            fade_out=fade_out,
            skill_card={
                "skill": skill, "type": "ritual_receipt",
                "title": card_title, "lines": card_lines,
                "stamp": "已写入本地记录",
                **card_extra,
            },
            tool_calls=[
                hermes_call,
                AgentToolCall(
                    name=skill, status="succeeded",
                    input=tool_input, output=tool_output,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                ),
            ],
        )

    def run_neisou(self, request: AgentDecideRequest) -> AgentDecideResponse:
        """Deterministic intranet fast path: obvious 内网 questions skip the
        decision LLM entirely and hit real 内搜 directly (~1s vs ~5s)."""
        started = time.perf_counter()
        profile_context = self._profile_context(request.user_id)
        normalized = self._normalizer.normalize(
            GenerationRequest(request_text=request.request_text), profile_context
        )
        router_call = AgentToolCall(
            name="intranet_router", status="succeeded",
            input={"request_text": request.request_text},
            output={"route": "neisou_search"},
            latency_ms=int((time.perf_counter() - started) * 1000),
            reason="内网问题白名单直达，跳过决策 LLM",
        )
        planner_meta = PlannerMeta(
            planner_source="neisou_fast", planner_confidence=0.95,
            planner_latency_ms=int((time.perf_counter() - started) * 1000),
        )
        decision = HermesDecision(action="neisou_search", search_query=request.request_text[:60])
        return self._execute_neisou(
            request=request, profile_context=profile_context, normalized=normalized,
            candidates=[], decision=decision,
            planner_meta=planner_meta, hermes_call=router_call,
        )

    def _execute_neisou(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        normalized: NormalizedAudioRequest,
        candidates: list[AudioAsset],
        decision: HermesDecision,
        planner_meta: PlannerMeta,
        hermes_call: AgentToolCall,
    ) -> AgentDecideResponse:
        """Real 内搜: query the internal search API and answer with sources.
        Unauthorized/failed searches degrade to an honest reply — never a
        fabricated answer."""
        started = time.perf_counter()
        query = (decision.search_query or request.request_text).strip()[:60]
        outcome = (
            self._enterprise.neisou(query)
            if self._enterprise is not None
            else {"status": "unauthorized", "results": []}
        )
        status = outcome.get("status")
        results = outcome.get("results", [])
        if status == "ok":
            # Speak the ANSWER, not a "查一下稍等" promise — the search has
            # already run by the time this reply reaches the user.
            top = results[0]
            fragment = (top.get("snippet") or top.get("title") or "").strip()[:56]
            reply = f"查到了：{fragment}……来源我放在卡片里了，点开就能看全文。"
            note = None
        elif status == "unauthorized":
            reply = "我还没拿到内网搜索的授权（ugate token），先帮不上这个忙——授权后我就能直接帮你查内网了。"
            note = "内搜未授权：运行 get-ugate-token 完成一次授权即可点亮"
        else:
            reply = f"内网搜索这会儿没能返回「{query}」的结果，稍后我再帮你试一次。"
            note = "内搜请求未成功，已如实告知（不编造答案）"
        return AgentDecideResponse(
            action="chat",
            normalized_request=normalized,
            profile_context=profile_context,
            search=self._search_view(candidates),
            asset=None,
            reply=reply,
            reasons=decision.reasons or ["公司内部信息，交给内搜"],
            planner_meta=planner_meta,
            selected_skill="neisou_answer",
            skill_card={
                "skill": "neisou_answer", "type": "neisou_results",
                "query": query, "status": status, "results": results, "note": note,
            },
            tool_calls=[
                hermes_call,
                AgentToolCall(
                    name="enterprise_search.neisou_search", status="succeeded" if status == "ok" else "failed",
                    input={"word": query}, output={"status": status, "results": len(results)},
                    latency_ms=int((time.perf_counter() - started) * 1000),
                ),
            ],
        )

    def _search_view(
        self,
        candidates: list[AudioAsset],
        *,
        chosen: AudioAsset | None = None,
        chosen_match_type: str = "hermes_selected",
    ) -> AssetSearchResponse:
        """Contract-compatible `search` field: the chosen asset (if any)
        followed by catalog candidates the frontend can use as fallback
        suggestions. Scores are no longer produced by an algorithm."""
        results: list[AssetSearchResult] = []
        if chosen is not None:
            results.append(
                AssetSearchResult(asset=chosen, score=1.0, match_type=chosen_match_type, reasons=["智能体选择"])
            )
        for asset in candidates:
            if chosen is not None and asset.id == chosen.id:
                continue
            results.append(AssetSearchResult(asset=asset, score=0.0, match_type="catalog", reasons=["目录候选"]))
            if len(results) >= 5:
                break
        return AssetSearchResponse(
            results=results,
            hit=chosen is not None,
            best_score=results[0].score if results else None,
            threshold=0.0,
        )

    # -- Responses ----------------------------------------------------------

    def _exact_cache_response(
        self,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        normalized: NormalizedAudioRequest,
        asset: AudioAsset,
    ) -> AgentDecideResponse:
        asset.playback_url = self._storage.public_url(asset.object_key)
        self._repo.record_event(
            request.user_id,
            EventIn(event_type="recommendation_served", asset_id=asset.id, payload={"source": "exact_cache"}),
        )
        return AgentDecideResponse(
            action="play_asset",
            normalized_request=normalized,
            profile_context=profile_context,
            search=self._search_view([], chosen=asset, chosen_match_type="exact"),
            asset=asset,
            reply=f"这就给你放《{asset.title}》，晚安。",
            reasons=["精确缓存命中，同一需求直接复用已生成音频"],
            planner_meta=PlannerMeta(planner_source="exact_cache", planner_confidence=1.0, planner_latency_ms=0),
            selected_skill="play_asset",
            tool_calls=[
                AgentToolCall(
                    name="play_asset",
                    status="succeeded",
                    input={"asset_id": asset.id},
                    output={"asset_id": asset.id, "match_type": "exact"},
                    reason="prompt_hash exact cache hit — Hermes not consulted",
                )
            ],
        )

    def _degraded_response(
        self,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        normalized: NormalizedAudioRequest,
        candidates: list[AudioAsset],
        exc: Exception,
        latency_ms: int,
    ) -> AgentDecideResponse:
        return AgentDecideResponse(
            action="no_match",
            normalized_request=normalized,
            profile_context=profile_context,
            search=self._search_view(candidates),
            asset=None,
            reply="我这会儿有点走神了，可以再跟我说一次吗？",
            reasons=["Hermes 决策层不可用，本次请求未做匹配"],
            planner_meta=PlannerMeta(
                planner_source="hermes",
                planner_confidence=0.0,
                planner_latency_ms=latency_ms,
                fallback_reason=f"hermes_unavailable:{type(exc).__name__}",
            ),
            selected_skill="no_match",
            tool_calls=[
                AgentToolCall(
                    name="hermes_agent",
                    status="failed",
                    input={"user_id": request.user_id, "request_text": request.request_text},
                    output={"error": str(exc)[:240]},
                    latency_ms=latency_ms,
                )
            ],
        )

    # -- Decision execution --------------------------------------------------

    def _execute_decision(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        normalized: NormalizedAudioRequest,
        candidates: list[AudioAsset],
        decision: HermesDecision,
        hermes_latency_ms: int,
    ) -> AgentDecideResponse:
        action = decision.normalized_action()
        selected_skill = decision.skill_name()
        extra_reasons: list[str] = []
        hermes_call = AgentToolCall(
            name="hermes_agent",
            status="succeeded",
            input={"user_id": request.user_id, "request_text": request.request_text},
            output={"action": action, "selected_skill": selected_skill, "asset_id": decision.asset_id},
            latency_ms=hermes_latency_ms,
            reason="Hermes selected the Floppy workflow skill",
        )
        planner_meta = PlannerMeta(
            planner_source="hermes",
            planner_confidence=decision.confidence,
            planner_latency_ms=hermes_latency_ms,
        )

        if request.generation_allowed and _explicit_generation_requested(request.request_text) and action == "play_asset":
            action = "generate_job"
            selected_skill = "generate_sleep_audio"
            extra_reasons.append("用户明确要求生成新内容，已跳过现有资产")
            hermes_call.reason = "explicit generation request overrides catalog playback"
            if hermes_call.output is not None:
                hermes_call.output["action"] = action
                hermes_call.output["selected_skill"] = selected_skill

        if action == "neisou_search":
            return self._execute_neisou(
                request=request, profile_context=profile_context, normalized=normalized,
                candidates=candidates, decision=decision,
                planner_meta=planner_meta, hermes_call=hermes_call,
            )

        if action in _RITUAL_ACTIONS:
            return self._execute_ritual(
                action=action, request=request, profile_context=profile_context,
                normalized=normalized, candidates=candidates, decision=decision,
                planner_meta=planner_meta, hermes_call=hermes_call,
            )

        if action == "chat":
            return AgentDecideResponse(
                action="chat",
                normalized_request=normalized,
                profile_context=profile_context,
                search=self._search_view(candidates),
                asset=None,
                reply=decision.reply or "我在呢，想聊什么都可以。",
                reasons=decision.reasons or ["Hermes 判断本轮为对话，无播放意图"],
                planner_meta=planner_meta,
                selected_skill=selected_skill,
                tool_calls=[hermes_call],
            )

        if action == "play_asset":
            asset = _select_asset(candidates, decision.asset_id)
            if asset is not None:
                self._repo.record_event(
                    request.user_id,
                    EventIn(event_type="recommendation_served", asset_id=asset.id, payload={"source": "hermes"}),
                )
                return AgentDecideResponse(
                    action="play_asset",
                    normalized_request=normalized,
                    profile_context=profile_context,
                    search=self._search_view(candidates, chosen=asset),
                    asset=asset,
                    reply=decision.reply,
                    reasons=decision.reasons or ["Hermes 选择了已有音频资产"],
                    planner_meta=planner_meta,
                    selected_skill=selected_skill,
                    tool_calls=[
                        hermes_call,
                        AgentToolCall(name="play_asset", status="succeeded", input={"asset_id": asset.id}, output={"asset_id": asset.id}),
                    ],
                )
            # Hermes referenced an asset that is not in the catalog: never play
            # something the user didn't ask for — regenerate or admit no match.
            extra_reasons.append(f"Hermes 返回的 asset_id 无效（{decision.asset_id!r}），已降级")
            hermes_call.reason = "invalid asset_id from Hermes — downgraded"
            action = "generate_job" if request.generation_allowed else "no_match"

        if action == "remix_current":
            if request.current_asset_id:
                sound_type = decision.remix_sound_type or "rain"
                remix_started = time.perf_counter()
                job_id = self._repo.create_remix_job(
                    request.user_id,
                    request.current_asset_id,
                    None,
                    [],
                    voice_volume=1.0,
                    ambient_volume=0.3,
                    sound_type=sound_type,
                )
                self._remix.run_remix(job_id)
                job = self._repo.get_remix_job(job_id)
                asset = job.output_asset if job and job.status == "succeeded" else None
                if asset:
                    asset.playback_url = self._storage.public_url(asset.object_key)
                return AgentDecideResponse(
                    action="remix_current",
                    normalized_request=normalized,
                    profile_context=profile_context,
                    search=self._search_view(candidates),
                    asset=asset,
                    remix_job_id=job_id,
                    reply=decision.reply,
                    reasons=decision.reasons or [f"Hermes 选择为当前音频添加{sound_type}背景"],
                    planner_meta=planner_meta,
                    selected_skill=selected_skill,
                    tool_calls=[
                        hermes_call,
                        AgentToolCall(
                            name="remix_current",
                            status="succeeded" if asset else "queued",
                            input={"asset_id": request.current_asset_id, "sound_type": sound_type},
                            output={"remix_job_id": job_id, "asset_id": asset.id if asset else None},
                            latency_ms=int((time.perf_counter() - remix_started) * 1000),
                        ),
                    ],
                )
            extra_reasons.append("remix 需要 current_asset_id，已降级")
            action = "generate_job" if request.generation_allowed else "no_match"

        if action == "no_match" or not request.generation_allowed:
            return AgentDecideResponse(
                action="no_match",
                normalized_request=normalized,
                profile_context=profile_context,
                search=self._search_view(candidates),
                asset=None,
                reply=decision.reply,
                reasons=(decision.reasons or ["Hermes 未选择生成，且当前没有可播放资产"]) + extra_reasons,
                planner_meta=planner_meta,
                selected_skill="no_match",
                tool_calls=[hermes_call],
            )

        self._gen.check_generation_budget(request.user_id)
        # 只用 Hermes 自己给出的 directive；缺失时由后台 worker 补规划
        # （run_job 内），决策路径不再同步等 12s 的规划 LLM —— 前台必须秒回。
        directive = decision.directive
        generate_started = time.perf_counter()
        generation_request = GenerationRequest(
            request_text=request.request_text,
            force_generate=True,
            directive=directive,
        )
        response = self._gen.enqueue_or_match(request.user_id, generation_request)
        return AgentDecideResponse(
            action="generate_job",
            normalized_request=response.normalized_request,
            profile_context=profile_context,
            search=self._search_view(candidates),
            asset=None,
            job_id=response.job_id,
            reply=decision.reply,
            reasons=(decision.reasons or ["Hermes 选择生成新的助眠音频"]) + extra_reasons,
            planner_meta=planner_meta,
            selected_skill="generate_sleep_audio",
            tool_calls=[
                hermes_call,
                AgentToolCall(
                    name="generate_sleep_audio",
                    status=response.status,
                    input={"request_text": request.request_text, "has_directive": directive is not None},
                    output={"job_id": response.job_id, "match_type": response.match_type},
                    latency_ms=int((time.perf_counter() - generate_started) * 1000),
                ),
            ],
        )


_PROFILE_PATCH_WHITELIST = {"voice_preferences", "background_preferences", "mood_tags", "duration_preference_min"}


def _whitelist_profile_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in _PROFILE_PATCH_WHITELIST:
            continue
        if key == "duration_preference_min":
            try:
                out[key] = max(5, min(60, int(value)))
            except (TypeError, ValueError):
                continue
        elif isinstance(value, list):
            out[key] = [str(v)[:40] for v in value][:8]
        elif isinstance(value, str):
            out[key] = [value[:40]]
    return out


def _select_asset(candidates: list[AudioAsset], asset_id: str | None) -> AudioAsset | None:
    """Strict lookup: the agent's asset_id must reference a real catalog asset.
    No silent fallback to the first candidate — a wrong asset played to a user
    trying to sleep is worse than regenerating."""
    if not asset_id:
        return None
    for asset in candidates:
        if asset.id == asset_id:
            return asset
    return None


def _responses_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                    chunks.append(content["text"])
        elif item.get("type") == "output_text" and isinstance(item.get("text"), str):
            chunks.append(item["text"])
    text = "\n".join(chunks).strip()
    if not text:
        raise ValueError("Hermes response did not contain output text")
    return text


def _chat_output_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Hermes chat response did not contain choices")
    content = choices[0].get("message", {}).get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        chunks = [item.get("text", "") for item in content if isinstance(item, dict)]
        text = "".join(chunk for chunk in chunks if isinstance(chunk, str)).strip()
        if text:
            return text
    raise ValueError("Hermes chat response did not contain output text")


def _extract_json_object(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError("Hermes decision did not contain JSON")
    depth = 0
    in_string = False
    escape = False
    for idx, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:idx + 1])
    raise ValueError("Hermes decision JSON was incomplete")


def _build_decision_prompt(
    request: AgentDecideRequest,
    profile_context: ProfileContext,
    candidates: list[AudioAsset],
    extras: dict[str, Any] | None = None,
) -> str:
    catalog = [
        {
            "asset_id": asset.id,
            "title": asset.title,
            "type": asset.type.value,
            "duration_sec": asset.duration_sec,
            "tags": asset.tags,
            "mood_tags": asset.mood_tags,
        }
        for asset in candidates
    ]
    context = {
        "user_request": request.model_dump(mode="json"),
        "profile": profile_context.model_dump(mode="json"),
        "catalog": catalog,
    }
    if extras:
        context.update(extras)
    return json.dumps(context, ensure_ascii=False)


_HERMES_DECISION_INSTRUCTIONS = """
你是 Unwind——一个温柔的减压陪伴智能体。用户在压力大的时候来找你：刚下会、刚发完版、脑子转个不停，或是睡前想放松下来。他们跟你聊天、倾诉，或想听点让人松弛的声音。你同时是资源匹配的唯一裁决者：catalog 是当前全部可播放的音频目录（未经算法过滤）。

每一轮你做两件事：
1) 选择本轮 action；
2) 写 reply——给用户看的回复。温柔、口语化，像坐在旁边陪你喘口气的朋友，不要客服腔。普通回复简短（不超过 40 字）；但引导类对话技能（relax_tip / counting_ritual / reframe_thought）需要完整的节奏，可以写到 100 字左右——数息要一口气数满 6-10 个数（"一……轻轻吸气……二……慢慢呼出去……三……肩膀松下来……"），呼吸引导要给完整的一轮，不要中途截断。每个 action 都必须写 reply。

可选 action：
- chat：用户在闲聊、倾诉、提问，没有想听内容的意图。reply 就是你的聊天回复：先共情、接住情绪，可以自然聊下去；只有当用户表露紧绷/焦虑/睡不着时才顺势轻轻提一句"要不要听点什么"，不要每轮都推销。
- play_asset：用户想听内容（点名要，或对话里明确表达想要声音陪伴），且 catalog 里有合适或相近的资产。必须填写 asset_id，且严格来自 catalog。**库优先**：现成资产即点即播，生成要让用户等一两分钟——同类型且意象相近就直接播（想听海浪→《夜海浪涌》，想听雨→任一雨声资产）。reply 例："给你放一段《夜雨轻敲》，闭上眼睛听听看。"
- generate_job：想听的内容 catalog 里确实没有同类或相近的（把 catalog 从头到尾看完再下结论），才现场生成（generation_allowed=false 时禁止）。意象完全无关的不要硬凑——想听火车声不要拿雨声顶。reply 要告知正在专门为 TA 制作，需要等一小会儿。
- remix_current：用户想给 current_asset_id 对应的当前音频加/换/调背景音。必须存在 current_asset_id。
- no_match：想听但既无合适资产也不能生成。reply 温柔致歉并给个替代建议。
- mood_checkin：用户给今天心情打分（"今天大概 6 分吧"），或你问完分数 TA 回答了。填 mood_score(1-10)。reply 温柔接住这个分数。
- worry_parking：用户在反刍一件未来的具体担心（"明天的汇报怎么办"），需要放下而不是解决方案。填 worry_text（用 TA 的原话概括成短语）。reply 告诉 TA 这件事由你保管，到点再还。
- gratitude_moment：用户说出今天的小确幸（可能是你邀请后回答的）。填 gratitude_items（1-3 条原话短语）。reply 温柔复述并收下。
- update_preference：用户表达长期偏好（"以后别放男声""我不喜欢雷声"）。填 profile_patch，白名单字段：voice_preferences / background_preferences / mood_tags / duration_preference_min（列表字段填要追加的项）。reply 自然确认（"记住了，以后不放雷声"）。仅"今晚/这次"的一次性要求不算。
- sleep_timer：用户要定时停止/渐弱（"播 20 分钟就停"）。填 timer_sec（秒）和 fade_out。需要有 current_asset_id 或本轮正在安排播放。reply 确认（"好，20 分钟后声音会慢慢淡下去"）。
- neisou_search：用户问只有公司内网才知道的事——地点设施（食堂/班车/健身房在哪）、流程制度（报销/请假/晋升/门禁）、内部工具用法等。填 search_query（提炼成简洁关键词，如"食堂 位置"）。reply 简短告知你去内网查了；具体结果由系统以卡片呈现，不要自己编造内网信息。日常闲聊和通用知识不要用它。

chat 之下还有六个「对话技能」：命中时 action 仍为 chat，但把 selected_skill 填成对应技能名，reply 按该技能的方式来写：
- reframe_thought：用户想做认知重构/CBT（"来一次CBT""帮我捋捋这个想法"），或表达灾难化/绝对化想法（"我肯定要被裁了""我什么都做不好"）。用苏格拉底式提问温柔引导，一次只问一个问题，不说教（例："最坏的情况，真的比其他可能都大吗？"）。**CBT 是对话练习，绝不因此生成音频**，除非用户明确说想"听"一段引导音频。用户表露自伤/危机信号时立即停止引导，转为直接关怀并提示求助渠道（如心理援助热线 400-161-9995），reasons 里加 "crisis"。
- relax_tip：用户此刻焦虑紧绷（"现在很紧张""心跳好快""静不下来"）。reply 直接开始引导一段 4-7-8 呼吸或 5-4-3-2-1 感官着地：短句、多停顿（用"……"），一次只给一个动作指令，不罗列步骤。
- counting_ritual：用户想数数/数息/数羊让脑子停下来。缓慢、重复、渐弱（"一……轻轻吸气……二……慢慢呼出去……"），一次 6-10 个数，不提问、不打扰。
- encourage_me：用户求夸求安慰（"夸夸我""鼓励一下我"）。基于 TA 刚说的具体事实夸，最多三句，不空洞。
- destress_knowledge：用户问压力/放松/睡眠的知识问题（"为什么一焦虑就胃疼"）。两三句口语化科普；涉及疾病诊断、用药一律建议就医，不装医生。
- comfort_card：用户告别或对话自然收尾（"去忙了""晚安""给我一张安心签"）。reply 是一句为这次对话定制的安心话（结合 TA 今天说过的事），说完即止，不再追问。

判断"想听"的信号：明确出现"听/放/来一段/讲个故事/生成音频/换一个"等词，或用户说想要声音陪伴入睡。注意：说"做/进行一次 CBT、认知重构、呼吸练习、数个数"是想要上面的对话技能，不是想听音频，选 chat 并填对应 selected_skill；仅仅倾诉情绪、问问题、打招呼时选 chat。

上下文数据（context 里可能出现，主动善用）：
- weather：所在城市实时/明日天气。用户问天气直接据此回答；外面正在下雨时可顺势提议听真雨声。没有该字段就说暂时不知道，不要编造。
- recent_rituals：最近的烦恼寄存/三件好事/心情打卡记录。上次寄存的烦恼可以轻轻回访一次（"上次那件事还压着你吗？"）；不要重复推销打卡。
- listen_stats：近 7 天收听统计。用户问"我最近听了什么"据此回答，语气是陪伴不是报表。

匹配判断要点：
- 以用户这句话的真实意图为准（内容类型、意象、时长、声音风格），profile 只是辅助偏好；结合对话上下文（比如上一轮你刚推荐过什么）。
- 先在 catalog 里找同类意象：点名"海边/篝火/雨声"这类元素时，catalog 里有对应或相近意象的资产就直接播；确实没有同类才 generate_job，绝不用无关意象凑数。
- duration_sec 与用户明确要求相差过大视为不匹配；用户没提时长就不要因时长排除。

如果选择 generate_job，尽量填写 directive：
- intent: white_noise | music | asmr | story | meditation | podcast_digest
- tone: 中文短语
- duration_sec: 通常 1200 秒左右，除非用户明确要求别的时长
- voice_style: warm_female | warm_male | whisper_female 等
- content_brief: 一句话主题
- outline: 3-8 个分段要点
- key_elements: 用户明确要求必须包含的意象或元素
- confidence: 0-1
- source: hermes

只输出一个 JSON 对象，不要 Markdown，不要解释。格式：
{
  "action": "chat|play_asset|generate_job|remix_current|no_match|mood_checkin|worry_parking|gratitude_moment|update_preference|sleep_timer|neisou_search",
  "selected_skill": "chat|reframe_thought|relax_tip|counting_ritual|encourage_me|destress_knowledge|comfort_card|play_asset|generate_sleep_audio|remix_current|no_match",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "mood_score": null,
  "worry_text": null,
  "gratitude_items": [],
  "profile_patch": null,
  "timer_sec": null,
  "fade_out": true,
  "search_query": null,
  "reply": "给用户看的一句话",
  "reasons": ["简短中文原因"],
  "confidence": 0.0
}
""".strip()
