# Agent Framework Evaluation (Algo Perspective)

> 2026-06-21 | Scope: ProfileContext → StructuredQuery → RetrievalDecision pipeline

---

## 1. Framework Fit for Profile→Query→Retrieval Flow

| Framework | Fit | Rationale |
|-----------|-----|-----------|
| **LangGraph** | ⭐⭐⭐⭐ Best | Native state machine with typed state; ProfileContext→StructuredQuery→RetrievalDecision maps directly to nodes with conditional edges (hit→return, miss→generate). Checkpointing gives free session resume. |
| OpenAI Agents SDK | ⭐⭐ | Handoff model is agent-to-agent; our flow is sequential state transform, not peer delegation. Structured output via response_format works but state passing is manual. |
| CrewAI | ⭐⭐ | Role-based multi-agent overkill for deterministic pipeline. Good for brainstorming/research, poor for typed state flows. |
| MS Agent Framework | ⭐⭐ | Enterprise-oriented, heavy infra dependency. Semantic Kernel tools are useful but framework overhead unjustified at MVP scale. |

**Winner: LangGraph** — state-first design matches our typed pipeline exactly.

---

## 2. Multi-Agent vs Single Orchestrator

**Recommendation: Single Orchestrator + deterministic tools for P0.**

Reasoning:
- ProfileContext→StructuredQuery is a pure function (no LLM needed)
- StructuredQuery→RetrievalDecision is retrieval + threshold logic (deterministic)
- Only the NLU step (request_text → intent/mood/topic extraction) benefits from LLM
- True multi-agent adds latency (agent handoff ~200-500ms each) with no quality gain

Architecture:
```
[LLM NLU Node] → [Profile Enrichment (deterministic)] → [Query Builder (deterministic)] → [Retrieval (deterministic)] → [Generate Decision]
```

Only 1 LLM call in the hot path. The rest are typed state transforms as LangGraph nodes.

---

## 3. StructuredQuery in Framework State/Tool Output

### LangGraph State Definition

```python
class FloppyState(TypedDict):
    # Input
    user_id: str
    request_text: str
    
    # After NLU node (LLM output, structured)
    intent: AudioType
    mood: list[str]
    content_topic: list[str]
    duration_hint: int | None
    voice_hint: str | None
    background_hint: str | None
    
    # After Profile Enrichment node (deterministic)
    profile: ProfileContext
    required_tags: list[str]
    preferred_tags: list[str]
    negative_tags: list[str]
    
    # After Query Builder node (deterministic)
    query: StructuredQuery  # full schema
    
    # After Retrieval node
    retrieval_result: AssetSearchResponse
    decision: Literal["exact_hit", "tag_hit", "semantic_hit", "generate", "budget_exceeded"]
    
    # Output
    asset: AudioAsset | None
    generation_job_id: str | None
```

Tags flow:
- `required_tags`: set by segment mapping (deterministic node)
- `preferred_tags`: segment defaults + NLU extracted keywords (merged in query builder)
- `negative_tags`: profile.negative_tags + segment exclusions (deterministic)
- `mood`: from NLU extraction + tonight_mood fallback

---

## 4. Framework Memory vs Backend DB

| Concern | Framework handles | Backend DB handles |
|---------|------------------|-------------------|
| Session state (within one request) | ✅ LangGraph checkpointer | — |
| Tonight state (session-level) | ✅ LangGraph memory (short-term) | ✅ user_profiles.tonight_* |
| Long-term preferences | ❌ Not suitable | ✅ user_profiles + user_behavior_signals |
| Behavior aggregation (7d windows) | ❌ | ✅ SQL aggregation |
| Profile versioning/audit | ❌ | ✅ profile_version + updated_at |
| Segment reclassification | ❌ | ✅ Event-driven update in repository |
| Conversation history (for NLU context) | ✅ LangGraph message state | Optionally persist |

**Verdict:** Framework memory is useful only for intra-session context (multi-turn conversation before generating). All durable profile/behavior state stays in backend DB. Do not dual-write.

---

## 5. Recommended Migration Path

### P0 (This sprint — no framework dependency)

Keep current architecture. Refactor into clear function boundaries that mirror future LangGraph nodes:

1. `extract_intent(request_text, profile) → NLUResult` — wraps current normalizer, future LLM
2. `enrich_from_profile(nlu_result, profile) → StructuredQuery` — deterministic tag mapping
3. `retrieve_or_decide(query, repository) → RetrievalDecision` — current recommendation logic
4. `execute_generation(decision, ...) → Asset` — current generation service

No new dependency. Just clean interfaces.

### P1 (Next sprint — LangGraph integration)

1. Install `langgraph>=0.2`
2. Define `FloppyState` TypedDict (above)
3. Wrap P0 functions as LangGraph nodes
4. Add conditional edges: hit→return, miss→generate, budget_exceeded→reject
5. Replace normalizer NLU with LLM node (structured output via tool_call)
6. Add LangGraph checkpointer (SQLite for MVP, Postgres later)

### P2 (Future — multi-agent if needed)

Only if these prove necessary:
- Separate "Script Writer Agent" (LLM-heavy, async)
- Separate "Quality Review Agent" (adversarial check on generated scripts)
- Use LangGraph subgraphs, not separate framework agents

---

## Summary

| Decision | Choice |
|----------|--------|
| Framework | LangGraph (state machine + typed state) |
| Architecture | Single orchestrator + deterministic tools |
| LLM calls in hot path | 1 (NLU extraction only) |
| Profile/behavior state | Backend DB only |
| Session context | LangGraph checkpointer |
| Migration | P0 refactor interfaces → P1 LangGraph wrap → P2 subgraphs if needed |

---

## Implementation Contract v1

### 1. FloppyState Fields

| Field | Required | Source | Type |
|-------|----------|--------|------|
| user_id | ✅ | input | str |
| request_text | ✅ | input | str |
| profile | ✅ | profile_node (DB read) | ProfileContext |
| intent | ✅ | normalizer_node | AudioType |
| mood | ✅ | normalizer_node | list[str] |
| content_topic | optional | normalizer_node | list[str] |
| duration_hint | optional | normalizer_node (from input or profile) | int \| None |
| voice_hint | optional | normalizer_node | str \| None |
| background_hint | optional | normalizer_node | str \| None |
| query | ✅ | query_builder_node | StructuredQuery |
| search_response | ✅ | search_node | AssetSearchResponse |
| route | ✅ | decision_node | GraphRoute |
| asset | optional | search_node or generation_node | AudioAsset \| None |
| generation_job_id | optional | generation_node | str \| None |
| error | optional | any node on failure | str \| None |

### 2. StructuredQuery v1

```python
class StructuredQuery(BaseModel):
    intent: AudioType
    mood: list[str]
    required_tags: list[str]       # from segment mapping, AND logic
    preferred_tags: list[str]      # segment + input keywords, weighted OR
    negative_tags: list[str]       # profile.negative_tags + segment exclusions
    duration_bucket: Literal["short", "medium", "long"]  # short≤10min, medium≤20, long>20
    voice_style: str               # resolved: input > profile > segment default
    background: str                # resolved: input > profile > segment default
    generation_allowed: bool       # False when budget_exceeded or white_noise priority
```

### 3. GraphRoute Enum

```python
class GraphRoute(StrEnum):
    PLAY_ASSET = "play_asset"           # exact/tag/semantic hit → return asset
    NO_MATCH = "no_match"               # miss + generation_allowed=False → sorry
    GENERATE_JOB = "generate_job"       # miss + generation_allowed=True → create job
    BUDGET_EXCEEDED = "budget_exceeded"  # daily limit hit → reject with reason
```

### 4. Node Classification

| Node | Deterministic? | LLM allowed? | MVP impl |
|------|---------------|-------------|----------|
| profile_node | ✅ | ❌ | DB read → ProfileContext |
| normalizer_node | ✅ (P0) | ✅ (P1 swap) | Rule-based RequestNormalizer (current) |
| query_builder_node | ✅ | ❌ | segment→tags mapping + field resolution |
| search_node | ✅ | ❌ | RecommendationService.search() |
| decision_node | ✅ | ❌ | threshold checks → GraphRoute |
| generation_node | ✅ | ❌ | GenerationService.enqueue_or_match() |

P0: All nodes deterministic. P1: normalizer_node swappable to LLM (structured output).

### 5. Backend Response Mapping (`/agent/decide`)

```python
# POST /agent/decide request body = {user_id, request_text, force_generate?}
# Response maps FloppyState → existing response models:

class AgentDecideResponse(BaseModel):
    route: GraphRoute
    # When route=play_asset:
    asset: AudioAsset | None                    # same as GenerationResponse.asset
    match_type: str                             # "exact" | "tag_hit" | "semantic_hit"
    # When route=generate_job:
    job_id: str | None                          # same as GenerationJobCreateResponse.job_id
    status: str                                 # "queued" | "generating"
    # Always present:
    query: StructuredQuery                      # transparency: what the agent decided
    normalized_request: NormalizedAudioRequest   # backward compat with existing clients
    cache_hit: bool                             # backward compat
```

**Backward compatibility:** existing `/users/{uid}/generate-audio` and `/users/{uid}/generation-jobs` remain unchanged. `/agent/decide` is a new endpoint that wraps the graph; it returns a superset (adds `route` + `query`) while preserving `asset`, `job_id`, `status`, `cache_hit`, `normalized_request` fields.
