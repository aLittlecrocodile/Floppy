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
    AssetSearchRequest,
    AssetSearchResponse,
    AudioAsset,
    EventIn,
    GenerationBudget,
    GenerationDirective,
    GenerationRequest,
    PlannerMeta,
    ProfileContext,
)
from floppy_backend.repositories import Repository
from floppy_backend.services.agent_graph import AgentGraphBuilder
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.recommendation import RecommendationService
from floppy_backend.services.remix import RemixService
from floppy_backend.storage import LocalFileStorage


_ACTIONS = {"play_asset", "generate_job", "remix_current", "no_match"}
_ACTION_ALIASES = {
    "generate_sleep_audio": "generate_job",
    "play_audio_asset": "play_asset",
    "search_audio_asset": "play_asset",
    "remix_audio": "remix_current",
}


class HermesDecision(BaseModel):
    action: str
    selected_skill: str | None = None
    asset_id: str | None = None
    remix_sound_type: str | None = None
    directive: GenerationDirective | None = None
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)

    def normalized_action(self) -> str:
        action = _ACTION_ALIASES.get(self.action, self.action)
        if action not in _ACTIONS:
            raise ValueError(f"unsupported Hermes action: {self.action}")
        return action

    def skill_name(self) -> str:
        if self.selected_skill:
            return self.selected_skill
        return {
            "play_asset": "play_asset",
            "generate_job": "generate_sleep_audio",
            "remix_current": "remix_current",
            "no_match": "no_match",
        }[self.normalized_action()]


class HermesAgentClient:
    """Thin client for Hermes Agent's OpenAI-compatible API server."""

    def __init__(self, settings: Settings):
        self._base_url = settings.hermes_base_url.rstrip("/")
        self._responses_url = f"{self._base_url}/responses" if self._base_url.endswith("/v1") else f"{self._base_url}/v1/responses"
        self._api_key = settings.hermes_api_key
        self._model = settings.hermes_model
        self._timeout = settings.hermes_timeout_sec
        self._store = settings.hermes_store_conversation

    def decide(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        search: AssetSearchResponse,
    ) -> HermesDecision:
        prompt = _build_decision_prompt(request, profile_context, search)
        headers = {
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": f"floppy-agent:{request.user_id}",
            "X-Hermes-Session-Key": f"floppy:user:{request.user_id}",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

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
    """Agent runtime adapter: Hermes decides, Floppy executes workflows."""

    def __init__(
        self,
        *,
        repository: Repository,
        storage: LocalFileStorage,
        normalizer: RequestNormalizer,
        recommendation_service: RecommendationService,
        generation_service: GenerationService,
        remix_service: RemixService,
        settings: Settings,
        local_agent: AgentGraphBuilder,
    ):
        self._repo = repository
        self._storage = storage
        self._normalizer = normalizer
        self._rec = recommendation_service
        self._gen = generation_service
        self._remix = remix_service
        self._settings = settings
        self._local_agent = local_agent
        self._client = HermesAgentClient(settings)

    def run(self, request: AgentDecideRequest) -> AgentDecideResponse:
        started = time.perf_counter()
        try:
            profile_context = self._profile_context(request.user_id)
            normalized = self._normalizer.normalize(GenerationRequest(request_text=request.request_text), profile_context)
            cache_key = self._gen.cache_key_for(normalized)
            search = self._rec.search(
                AssetSearchRequest(user_id=request.user_id, query=request.request_text, cache_key=cache_key, limit=5)
            )
            for result in search.results:
                result.asset.playback_url = self._storage.public_url(result.asset.object_key)

            decision = self._client.decide(request=request, profile_context=profile_context, search=search)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return self._execute_decision(
                request=request,
                profile_context=profile_context,
                normalized=normalized,
                search=search,
                decision=decision,
                hermes_latency_ms=latency_ms,
            )
        except Exception as exc:
            if not self._settings.hermes_fallback_to_local:
                raise
            return self._fallback(request, exc, int((time.perf_counter() - started) * 1000))

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

    def _execute_decision(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        normalized,
        search: AssetSearchResponse,
        decision: HermesDecision,
        hermes_latency_ms: int,
    ) -> AgentDecideResponse:
        action = decision.normalized_action()
        selected_skill = decision.skill_name()
        hermes_call = AgentToolCall(
            name="hermes_agent",
            status="succeeded",
            input={"user_id": request.user_id, "request_text": request.request_text},
            output={"action": action, "selected_skill": selected_skill, "asset_id": decision.asset_id},
            latency_ms=hermes_latency_ms,
            reason="Hermes selected the Floppy workflow skill",
        )

        if action == "play_asset":
            asset = _select_asset(search, decision.asset_id)
            if asset is not None and search.hit:
                self._repo.record_event(
                    request.user_id,
                    EventIn(event_type="recommendation_served", asset_id=asset.id, payload={"source": "hermes"}),
                )
                return AgentDecideResponse(
                    action="play_asset",
                    normalized_request=normalized,
                    profile_context=profile_context,
                    search=search,
                    asset=asset,
                    job_id=None,
                    remix_job_id=None,
                    reasons=decision.reasons or ["Hermes 选择了已有音频资产"],
                    planner_meta=PlannerMeta(
                        planner_source="hermes",
                        planner_confidence=decision.confidence,
                        planner_latency_ms=hermes_latency_ms,
                    ),
                    selected_skill=selected_skill,
                    tool_calls=[
                        hermes_call,
                        AgentToolCall(name="play_asset", status="succeeded", input={"asset_id": asset.id}, output={"asset_id": asset.id}),
                    ],
                )
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
                    search=search,
                    asset=asset,
                    job_id=None,
                    remix_job_id=job_id,
                    reasons=decision.reasons or [f"Hermes 选择为当前音频添加{sound_type}背景"],
                    planner_meta=PlannerMeta(
                        planner_source="hermes",
                        planner_confidence=decision.confidence,
                        planner_latency_ms=hermes_latency_ms,
                    ),
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
            action = "generate_job" if request.generation_allowed else "no_match"

        if action == "no_match" or not request.generation_allowed:
            return AgentDecideResponse(
                action="no_match",
                normalized_request=normalized,
                profile_context=profile_context,
                search=search,
                asset=None,
                job_id=None,
                remix_job_id=None,
                reasons=decision.reasons or ["Hermes 未选择生成，且当前没有可播放资产"],
                planner_meta=PlannerMeta(
                    planner_source="hermes",
                    planner_confidence=decision.confidence,
                    planner_latency_ms=hermes_latency_ms,
                ),
                selected_skill="no_match",
                tool_calls=[hermes_call],
            )

        self._gen.check_generation_budget(request.user_id)
        generate_started = time.perf_counter()
        generation_request = GenerationRequest(
            request_text=request.request_text,
            force_generate=True,
            directive=decision.directive,
        )
        response = self._gen.enqueue_or_match(request.user_id, generation_request)
        return AgentDecideResponse(
            action="generate_job",
            normalized_request=response.normalized_request,
            profile_context=profile_context,
            search=search,
            asset=None,
            job_id=response.job_id,
            remix_job_id=None,
            reasons=decision.reasons or ["Hermes 选择生成新的助眠音频"],
            planner_meta=PlannerMeta(
                planner_source="hermes",
                planner_confidence=decision.confidence,
                planner_latency_ms=hermes_latency_ms,
            ),
            selected_skill="generate_sleep_audio",
            tool_calls=[
                hermes_call,
                AgentToolCall(
                    name="generate_sleep_audio",
                    status=response.status,
                    input={"request_text": request.request_text, "has_directive": decision.directive is not None},
                    output={"job_id": response.job_id, "match_type": response.match_type},
                    latency_ms=int((time.perf_counter() - generate_started) * 1000),
                ),
            ],
        )

    def _fallback(self, request: AgentDecideRequest, exc: Exception, latency_ms: int) -> AgentDecideResponse:
        response = self._local_agent.run(request)
        meta = response.planner_meta or PlannerMeta()
        return response.model_copy(
            update={
                "planner_meta": PlannerMeta(
                    planner_source=meta.planner_source,
                    planner_confidence=meta.planner_confidence,
                    planner_latency_ms=meta.planner_latency_ms,
                    fallback_reason=f"hermes_unavailable:{type(exc).__name__}",
                ),
                "tool_calls": [
                    AgentToolCall(
                        name="hermes_agent",
                        status="failed",
                        input={"user_id": request.user_id, "request_text": request.request_text},
                        output={"error": str(exc)[:240]},
                        latency_ms=latency_ms,
                    ),
                    *response.tool_calls,
                ],
            }
        )


def _select_asset(search: AssetSearchResponse, asset_id: str | None) -> AudioAsset | None:
    if asset_id:
        for result in search.results:
            if result.asset.id == asset_id:
                return result.asset
    if search.results:
        return search.results[0].asset
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
    search: AssetSearchResponse,
) -> str:
    candidates = [
        {
            "asset_id": item.asset.id,
            "title": item.asset.title,
            "type": item.asset.type.value,
            "duration_sec": item.asset.duration_sec,
            "tags": item.asset.tags,
            "score": item.score,
            "match_type": item.match_type,
            "reasons": item.reasons,
        }
        for item in search.results
    ]
    context = {
        "user_request": request.model_dump(mode="json"),
        "profile": profile_context.model_dump(mode="json"),
        "asset_search": {
            "hit": search.hit,
            "best_score": search.best_score,
            "threshold": search.threshold,
            "candidates": candidates,
        },
    }
    return json.dumps(context, ensure_ascii=False)


_HERMES_DECISION_INSTRUCTIONS = """
你是 Floppy 的智能体决策层。你只负责选择下一步 workflow skill；不要生成给用户看的自然语言。

可选 action 只能是：
- play_asset：候选资产已经足够匹配，直接播放。必须填写 asset_id，且只能来自 candidates。
- generate_job：需要生成新的助眠音频。generation_allowed=false 时禁止选择。
- remix_current：用户想给 current_asset_id 对应的当前音频加背景、换背景或调整背景。必须存在 current_asset_id。
- no_match：没有可播放资产，且不能或不应该生成。

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
  "action": "play_asset|generate_job|remix_current|no_match",
  "selected_skill": "play_asset|generate_sleep_audio|remix_current|no_match",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reasons": ["简短中文原因"],
  "confidence": 0.0
}
""".strip()
