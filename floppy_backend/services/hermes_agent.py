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
    ProfileContext,
)
from floppy_backend.repositories import Repository
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.library import LibraryService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.remix import RemixService
from floppy_backend.storage import LocalFileStorage


_ACTIONS = {"chat", "play_asset", "generate_job", "remix_current", "no_match"}
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

    def normalized_action(self) -> str:
        action = _ACTION_ALIASES.get(self.action, self.action)
        if action not in _ACTIONS:
            raise ValueError(f"unsupported Hermes action: {self.action}")
        return action

    def skill_name(self) -> str:
        if self.selected_skill:
            return self.selected_skill
        return {
            "chat": "chat",
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
    ) -> HermesDecision:
        prompt = _build_decision_prompt(request, profile_context, candidates)
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
    ):
        self._repo = repository
        self._storage = storage
        self._normalizer = normalizer
        self._gen = generation_service
        self._remix = remix_service
        self._library = library
        self._settings = settings
        self._directive_planner = directive_planner
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
        decision = None
        last_exc: Exception | None = None
        for _ in range(2):  # one retry — Hermes/LLM cold-start hiccups are transient
            try:
                decision = self._client.decide(request=request, profile_context=profile_context, candidates=candidates)
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
                selected_skill="chat",
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
    return json.dumps(context, ensure_ascii=False)


_HERMES_DECISION_INSTRUCTIONS = """
你是 Unwind——一个温柔的睡前陪伴智能体。用户在睡前跟你聊天、倾诉，或想听点助眠的声音。你同时是资源匹配的唯一裁决者：catalog 是当前全部可播放的音频目录（未经算法过滤）。

每一轮你做两件事：
1) 选择本轮 action；
2) 写 reply——给用户看的一句话回复。温柔、口语化、简短（不超过 40 字），像深夜里坐在旁边的朋友，不要客服腔。每个 action 都必须写 reply。

可选 action：
- chat：用户在闲聊、倾诉、提问，没有想听内容的意图。reply 就是你的聊天回复：先共情、接住情绪，可以自然聊下去；只有当用户表露睡不着/焦虑时才顺势轻轻提一句"要不要听点什么"，不要每轮都推销。
- play_asset：用户想听内容（点名要，或对话里明确表达想要声音陪伴），且 catalog 里有合适或相近的资产。必须填写 asset_id，且严格来自 catalog。**库优先**：现成资产即点即播，生成要让用户等一两分钟——同类型且意象相近就直接播（想听海浪→《夜海浪涌》，想听雨→任一雨声资产）。reply 例："给你放一段《夜雨轻敲》，闭上眼睛听听看。"
- generate_job：想听的内容 catalog 里确实没有同类或相近的（把 catalog 从头到尾看完再下结论），才现场生成（generation_allowed=false 时禁止）。意象完全无关的不要硬凑——想听火车声不要拿雨声顶。reply 要告知正在专门为 TA 制作，需要等一小会儿。
- remix_current：用户想给 current_asset_id 对应的当前音频加/换/调背景音。必须存在 current_asset_id。
- no_match：想听但既无合适资产也不能生成。reply 温柔致歉并给个替代建议。

判断"想听"的信号：出现"听/放/来一段/讲个/生成/换一个"等词，或用户说睡不着、想要人陪着说话入睡。仅仅是倾诉情绪、问问题、打招呼时选 chat。

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
  "action": "chat|play_asset|generate_job|remix_current|no_match",
  "selected_skill": "chat|play_asset|generate_sleep_audio|remix_current|no_match",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reply": "给用户看的一句话",
  "reasons": ["简短中文原因"],
  "confidence": 0.0
}
""".strip()
