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
    AssetSearchFilters,
    AssetSearchRequest,
    AssetSearchResponse,
    AudioAssetFacets,
    AudioAsset,
    EventIn,
    GenerationBudget,
    GenerationDirective,
    GenerationRequest,
    PlannerMeta,
    ProfileContext,
)
from floppy_backend.repositories import Repository
from floppy_backend.services.asset_catalog import AssetCatalogService
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.request_defaults import RequestDefaults
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


class HermesSearchPlan(BaseModel):
    query: str | None = None
    filters: AssetSearchFilters = Field(default_factory=AssetSearchFilters)
    limit: int = Field(default=10, ge=1, le=20)
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)

    def has_structured_filters(self) -> bool:
        return bool(
            self.filters.type
            or self.filters.mood_tags
            or self.filters.required_tags
            or self.filters.preferred_tags
            or self.filters.negative_tags
            or self.filters.min_duration_sec is not None
            or self.filters.max_duration_sec is not None
        )


class HermesAgentClient:
    """Thin client for Hermes Agent's OpenAI-compatible API server."""

    def __init__(self, settings: Settings):
        self._base_url = settings.hermes_base_url.rstrip("/")
        self._responses_url = f"{self._base_url}/responses" if self._base_url.endswith("/v1") else f"{self._base_url}/v1/responses"
        self._api_key = settings.hermes_api_key or _local_hermes_api_key(settings.hermes_base_url)
        self._model = settings.hermes_model
        self._timeout = settings.hermes_timeout_sec
        self._store = settings.hermes_store_conversation

    def plan_search(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        facets: AudioAssetFacets,
    ) -> HermesSearchPlan:
        prompt = _build_search_plan_prompt(request, profile_context, facets)
        payload = self._request_json(
            request=request,
            prompt=prompt,
            instructions=_HERMES_SEARCH_PLAN_INSTRUCTIONS,
        )
        plan = HermesSearchPlan.model_validate(payload)
        if plan.confidence >= 0.6 and not plan.has_structured_filters():
            repair_payload = self._request_json(
                request=request,
                prompt=_build_search_plan_repair_prompt(request, profile_context, facets, plan),
                instructions=_HERMES_SEARCH_PLAN_REPAIR_INSTRUCTIONS,
            )
            repaired = HermesSearchPlan.model_validate(repair_payload)
            if repaired.has_structured_filters() or repaired.confidence < plan.confidence:
                return repaired
        return plan

    def decide(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        search: AssetSearchResponse,
        search_plan: HermesSearchPlan | None = None,
    ) -> HermesDecision:
        prompt = _build_decision_prompt(request, profile_context, search, search_plan)
        payload = self._request_json(
            request=request,
            prompt=prompt,
            instructions=_HERMES_DECISION_INSTRUCTIONS,
        )
        decision = HermesDecision.model_validate(payload)
        decision.normalized_action()
        return decision

    def _request_json(
        self,
        *,
        request: AgentDecideRequest,
        prompt: str,
        instructions: str,
    ) -> dict[str, Any]:
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
                "instructions": instructions,
                "store": self._store,
                "conversation": f"floppy-agent:{request.user_id}",
                "tools": [],
                "tool_choice": "none",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        text = _responses_output_text(response.json())
        return _extract_json_object(text)


class HermesAgentRuntime:
    """Agent runtime adapter: Hermes decides, Floppy executes workflows."""

    def __init__(
        self,
        *,
        repository: Repository,
        storage: LocalFileStorage,
        request_defaults: RequestDefaults,
        asset_catalog_service: AssetCatalogService,
        generation_service: GenerationService,
        remix_service: RemixService,
        settings: Settings,
    ):
        self._repo = repository
        self._storage = storage
        self._defaults = request_defaults
        self._catalog = asset_catalog_service
        self._gen = generation_service
        self._remix = remix_service
        self._settings = settings
        self._client = HermesAgentClient(settings)

    def run(self, request: AgentDecideRequest) -> AgentDecideResponse:
        started = time.perf_counter()
        profile_context = self._profile_context(request.user_id)
        facets = self._catalog.facets(limit=12)
        search_plan = self._client.plan_search(
            request=request,
            profile_context=profile_context,
            facets=facets,
        )
        planned_query = (search_plan.query or request.request_text).strip()
        if len(planned_query) < 2:
            planned_query = request.request_text
        search = self._catalog.search(
            AssetSearchRequest(
                user_id=request.user_id,
                query=planned_query,
                filters=search_plan.filters,
                limit=search_plan.limit,
            )
        )
        for result in search.results:
            result.asset.playback_url = self._storage.public_url(result.asset.object_key)

        decision = self._client.decide(
            request=request,
            profile_context=profile_context,
            search=search,
            search_plan=search_plan,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._execute_decision(
            request=request,
            profile_context=profile_context,
            search=search,
            search_plan=search_plan,
            decision=decision,
            hermes_latency_ms=latency_ms,
        )

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
        search: AssetSearchResponse,
        search_plan: HermesSearchPlan,
        decision: HermesDecision,
        hermes_latency_ms: int,
    ) -> AgentDecideResponse:
        action = decision.normalized_action()
        selected_skill = decision.skill_name()
        hermes_call = AgentToolCall(
            name="hermes_agent",
            status="succeeded",
            input={"user_id": request.user_id, "request_text": request.request_text},
            output={
                "search_plan": search_plan.model_dump(mode="json"),
                "action": action,
                "selected_skill": selected_skill,
                "asset_id": decision.asset_id,
            },
            latency_ms=hermes_latency_ms,
            reason="Hermes selected the Floppy workflow skill",
        )

        selected_asset = _select_asset(search, decision.asset_id)
        normalized = self._normalized_for_decision(
            request=request,
            profile_context=profile_context,
            decision=decision,
            selected_asset=selected_asset,
        )

        if action == "play_asset":
            asset = selected_asset
            if asset is not None:
                self._repo.record_event(
                    request.user_id,
                    EventIn(event_type="asset_served", asset_id=asset.id, payload={"source": "hermes"}),
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

    def _normalized_for_decision(
        self,
        *,
        request: AgentDecideRequest,
        profile_context: ProfileContext,
        decision: HermesDecision,
        selected_asset: AudioAsset | None,
    ):
        if decision.normalized_action() == "play_asset" and selected_asset is not None:
            return self._defaults.from_asset(selected_asset, profile_context)
        return self._defaults.normalize(
            GenerationRequest(request_text=request.request_text, directive=decision.directive),
            profile_context,
            decision.directive,
        )

def _select_asset(search: AssetSearchResponse, asset_id: str | None) -> AudioAsset | None:
    if asset_id:
        for result in search.results:
            if result.asset.id == asset_id:
                return result.asset
    if search.results:
        return search.results[0].asset
    return None


def _local_hermes_api_key(base_url: str) -> str | None:
    if "127.0.0.1" in base_url or "localhost" in base_url:
        return "change-me-local-dev"
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
    search_plan: HermesSearchPlan | None = None,
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
        "search_plan": search_plan.model_dump(mode="json") if search_plan else None,
        "asset_search": {
            "hit": search.hit,
            "best_score": search.best_score,
            "threshold": search.threshold,
            "query_analysis": search.query_analysis.model_dump(mode="json") if search.query_analysis else None,
            "candidates": candidates,
        },
    }
    return json.dumps(context, ensure_ascii=False)


def _build_search_plan_prompt(
    request: AgentDecideRequest,
    profile_context: ProfileContext,
    facets: AudioAssetFacets,
) -> str:
    top_assets = [
        {
            "asset_id": asset.id,
            "title": asset.title,
            "type": asset.type.value,
            "duration_sec": asset.duration_sec,
            "tags": asset.tags,
            "mood_tags": asset.mood_tags,
            "user_segment_tags": asset.user_segment_tags,
            "voice_id": asset.voice_id,
            "quality_score": asset.quality_score,
        }
        for asset in facets.top_assets
    ]
    context = {
        "user_request": request.model_dump(mode="json"),
        "profile": profile_context.model_dump(mode="json"),
        "catalog_facets": {
            "asset_types": facets.asset_types,
            "tags": facets.tags,
            "mood_tags": facets.mood_tags,
            "voice_ids": facets.voice_ids,
            "user_segment_tags": facets.user_segment_tags,
            "top_assets": top_assets,
        },
    }
    return json.dumps(context, ensure_ascii=False)


def _build_search_plan_repair_prompt(
    request: AgentDecideRequest,
    profile_context: ProfileContext,
    facets: AudioAssetFacets,
    invalid_plan: HermesSearchPlan,
) -> str:
    payload = json.loads(_build_search_plan_prompt(request, profile_context, facets))
    payload["invalid_search_plan"] = invalid_plan.model_dump(mode="json")
    payload["repair_reason"] = "previous plan had high confidence but empty structured filters"
    return json.dumps(payload, ensure_ascii=False)


_HERMES_SEARCH_PLAN_INSTRUCTIONS = """
你是 Floppy 的 Hermes Skill 规划阶段。你的任务是把用户原话分类成 Floppy MCP 资源检索参数；不要选择最终 action，不要写用户回复。

后端资源库不会理解中文语义，也不会把“雨声/钢琴/不要人声”翻译成标签。这个理解必须由你完成，并输出结构化 search plan。

资源检索 filters 字段含义：
- type: white_noise | music | asmr | story | meditation | podcast_digest | null
- required_tags: 必须全部命中的标签。只放硬条件，例如 rain、piano、no_voice。
- preferred_tags: 加分标签。只放软偏好，例如 ambient、low_stimulation、slow_pace。
- negative_tags: 必须排除的标签或类型，例如 thunder、voice_present、meditation、story、asmr。
- mood_tags: 与用户画像/情绪有关的软过滤；不确定时留空。
- min_duration_sec / max_duration_sec: 只有用户明确时长范围时填写。

意图分类规范：
- 用户要雨声、海浪、风扇、溪流、壁炉、森林、棕噪、粉噪等环境音时，通常 type=white_noise，并要求 no_voice。
- 用户要钢琴、弦乐、小提琴、长笛、轻音乐时，通常 type=music，并要求 no_voice。
- 用户要冥想、呼吸引导、身体扫描、正念时，type=meditation，允许 voice_present，除非用户明确不要人声。
- 用户要故事、讲述、童话、陪伴叙事时，type=story。
- 用户要 ASMR、耳语、轻声陪伴时，type=asmr。
- 用户要文章/播客/知识内容助眠时，type=podcast_digest。
- 用户明确“不要人声/不要说话/不要冥想/不要故事/不要雷声”等，是硬约束，必须写入 required_tags 或 negative_tags。
- 不要为了凑结果把白噪音请求转成冥想、故事或音乐；不确定时保持窄搜索，允许后续生成或 no_match。
- 只优先使用 catalog_facets.tags 中存在的标签。用户提出 catalog 完全没有的声音词时，不要编新标签；把 filters 保持较窄或留空，并降低 confidence。
- 如果你在 reasons 中提到了 rain、no_voice、thunder、piano 等资源标签，必须同时把它们写入 filters；禁止只在 reasons 中解释却让 filters 为空。
- confidence >= 0.6 时，filters 不能全空，除非用户请求是 remix_current 或 no_match 类的非资源搜索请求。

常见中文到标签示例：
- 雨声/下雨/夜雨 -> required_tags: ["rain", "no_voice"]，negative_tags 包含 "voice_present"；无雷声时加 "thunder"。
- 海浪/海边浪声 -> required_tags: ["ocean", "no_voice"]
- 溪流/流水/瀑布 -> required_tags: ["stream", "no_voice"]
- 森林/虫鸣/林间 -> required_tags: ["forest", "no_voice"]
- 风扇/空调底噪 -> required_tags: ["fan", "no_voice"]
- 壁炉/篝火/柴火 -> required_tags: ["fire", "no_voice"]
- 棕噪 -> required_tags: ["brown_noise", "no_voice"]
- 钢琴轻音乐 -> type=music, required_tags: ["piano", "no_voice"]
- 弦乐/小提琴/长笛 -> type=music，按需 required_tags 使用 strings、violin、flute 和 no_voice

只输出一个 JSON 对象，不要 Markdown，不要解释。格式：
{
  "query": "可选的原始或简短规范化检索词",
  "filters": {
    "type": null,
    "mood_tags": [],
    "required_tags": [],
    "preferred_tags": [],
    "negative_tags": [],
    "min_duration_sec": null,
    "max_duration_sec": null
  },
  "limit": 10,
  "reasons": ["简短中文原因"],
  "confidence": 0.0
}
""".strip()


_HERMES_SEARCH_PLAN_REPAIR_INSTRUCTIONS = """
你是 Floppy Hermes search_plan 修复器。上一轮 search_plan 高置信但 filters 为空，这是格式错误。

只根据 user_request、profile、catalog_facets 和 invalid_search_plan.reasons 重新输出一个合法 search_plan JSON。

规则：
- 如果 invalid_search_plan.reasons 或用户原话提到雨声/下雨/夜雨，且 catalog_facets.tags 包含 rain，则 filters.required_tags 必须包含 rain。
- 如果用户要求不要人声，且 catalog_facets.tags 包含 no_voice，则 filters.required_tags 必须包含 no_voice，并在 negative_tags 中排除 voice_present。
- 如果用户要求不要雷声，且 catalog_facets.tags 包含 thunder，则 negative_tags 必须包含 thunder。
- 如果用户要求不要冥想，negative_tags 必须包含 meditation；如果请求是非人声环境音，也应排除 story、asmr、podcast_digest 等人声类型。
- 如果是明确环境音，type 应为 white_noise；如果是明确钢琴/弦乐等助眠音乐，type 应为 music。
- 不要选择最终 action，不要输出 Markdown。

只输出一个 JSON 对象，格式：
{
  "query": "简短检索词",
  "filters": {
    "type": null,
    "mood_tags": [],
    "required_tags": [],
    "preferred_tags": [],
    "negative_tags": [],
    "min_duration_sec": null,
    "max_duration_sec": null
  },
  "limit": 10,
  "reasons": ["修复后的简短中文原因"],
  "confidence": 0.0
}
""".strip()


_HERMES_DECISION_INSTRUCTIONS = """
你是 Floppy 的智能体决策层。你只负责选择下一步 workflow skill；不要生成给用户看的自然语言。

Floppy 已经按你的 search_plan 查询 approved catalog。后端只执行结构化过滤，不再做用户语义理解；你需要根据用户原话、search_plan、画像和候选资产决定播放、生成、改背景或不匹配。

asset_search.query_analysis 只是 search_plan 的回显和执行摘要，不代表后端替你理解了用户。search_plan.confidence 低、candidates 为空、或候选违反硬约束时，不要随便播放弱相关候选；当用户需求清楚且 generation_allowed=true 时选择 generate_job，否则选择 no_match。
用户明确要求“不要人声/不要冥想/不要雷声”等限制时，这些是硬约束，禁止选择违反约束的候选。尤其是白噪音/环境音请求，不能播放含人声的冥想或故事。

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
