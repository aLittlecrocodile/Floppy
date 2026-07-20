# Hermes Agent Runtime Integration

## Goal

Floppy keeps ownership of product APIs, asset storage, generation jobs, MiniMax audio generation, and remix workflows.

Hermes Agent is used as the agent decision runtime:

```text
App / Voice WS / Demo
  -> Floppy /agent runtime
    -> Hermes Agent API Server decides selected skill
    -> Floppy executes play_asset / generate_sleep_audio / remix_current
```

This avoids binding product workflow state to Hermes internals while replacing the hand-written agent planner with a real agent runtime.

## Runtime (Hermes-only)

Hermes is the sole decision layer — the LangGraph/scoring-based local runtime has been removed. Matching is agent-driven: Hermes receives the (capped, newest-first) asset catalog and autonomously picks `play_asset` / `generate_job` / `remix_current` / `no_match`. There is no similarity score or hit threshold gating its choice.

Two deterministic guards remain outside Hermes:

- **Exact cache short-circuit**: an exact `prompt_hash` hit plays the cached asset without consulting Hermes (same request never regenerates paid TTS).
- **Strict asset_id validation**: a `play_asset` decision must reference a real catalog asset_id, otherwise it is downgraded to `generate_job` / `no_match` (never silently plays a different asset).

```bash
FLOPPY_HERMES_BASE_URL=http://127.0.0.1:8642
FLOPPY_HERMES_API_KEY=change-me-local-dev
FLOPPY_HERMES_MODEL=hermes-agent
FLOPPY_HERMES_API_STYLE=responses  # use chat for OneAPI gateways without /responses
FLOPPY_HERMES_CATALOG_LIMIT=60   # max assets shown to Hermes per decision
```

The client supports both OpenAI Responses and Chat Completions. When using an
OpenAI-compatible gateway that only exposes `/v1/chat/completions`, set
`FLOPPY_HERMES_API_STYLE=chat`; `FLOPPY_QUERY_PLANNER_API_KEY` is used as the
Hermes key when `FLOPPY_HERMES_API_KEY` is empty.

When Hermes is unreachable, the runtime degrades to `no_match` (plus catalog suggestions in `search.results`) and `planner_meta.fallback_reason` starts with `hermes_unavailable:`. `planner_meta.planner_source` is `hermes`, or `exact_cache` when the short-circuit fired.

## Hermes Setup

Hermes API server is configured from Hermes environment variables:

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=change-me-local-dev
hermes gateway
```

Expected endpoint:

```text
POST http://127.0.0.1:8642/v1/responses
```

Floppy sends:

- `Authorization: Bearer <FLOPPY_HERMES_API_KEY>` when configured
- `X-Hermes-Session-Id: floppy-agent:<user_id>`
- `X-Hermes-Session-Key: floppy:user:<user_id>`

## Decision Contract

Hermes must return one JSON object:

```json
{
  "action": "play_asset",
  "selected_skill": "play_asset",
  "asset_id": "aud_xxx",
  "remix_sound_type": null,
  "directive": null,
  "reasons": ["候选资产匹配用户需求"],
  "confidence": 0.86
}
```

Allowed actions:

- `play_asset`
- `generate_job`
- `remix_current`
- `no_match`

Allowed selected skills:

- `play_asset`
- `generate_sleep_audio`
- `remix_current`
- `no_match`

For `generate_job`, Hermes should include a `GenerationDirective` when it can:

```json
{
  "intent": "meditation",
  "tone": "温柔平静",
  "duration_sec": 1200,
  "voice_style": "warm_female",
  "content_brief": "雨声背景下的睡前呼吸冥想",
  "outline": ["安顿身体", "放慢呼吸", "释放紧张", "进入睡眠"],
  "key_elements": ["雨声", "呼吸", "安全感"],
  "confidence": 0.9,
  "source": "hermes"
}
```

The directive is persisted on the generation job, so background workers do not lose the agent plan.

## Response Observability

`AgentDecideResponse` now includes:

- `selected_skill`
- `tool_calls[]`
- `planner_meta.planner_source=hermes` when Hermes handled the decision

Example tool trace:

```json
{
  "selected_skill": "generate_sleep_audio",
  "tool_calls": [
    {
      "name": "hermes_agent",
      "status": "succeeded",
      "latency_ms": 812,
      "output": {"action": "generate_job", "selected_skill": "generate_sleep_audio"}
    },
    {
      "name": "generate_sleep_audio",
      "status": "queued",
      "output": {"job_id": "job_xxx", "match_type": "queued"}
    }
  ]
}
```

## Current Boundary

This migration stage uses Hermes as an HTTP decision runtime. Floppy still executes tools locally after Hermes returns the selected action.

The next stage can expose Floppy workflows as an MCP server and let Hermes call:

- `mcp_floppy_search_audio_asset`
- `mcp_floppy_generate_sleep_audio`
- `mcp_floppy_remix_current`
- `mcp_floppy_get_generation_job`

That MCP server is already scaffolded as an optional entry point.

## Optional Floppy MCP Server

Install the optional MCP dependency in the Floppy environment:

```bash
uv pip install -e ".[mcp]"
```

Start the Floppy backend first, then let Hermes spawn the MCP server over stdio.

Hermes `~/.hermes/config.yaml` example:

```yaml
mcp_servers:
  floppy:
    command: "/path/to/Floppy/.venv/bin/python"
    args: ["-m", "floppy_backend.mcp_server"]
    env:
      FLOPPY_MCP_BACKEND_URL: "http://127.0.0.1:8000"
    tools:
      include:
        - search_audio_asset
        - generate_sleep_audio
        - get_generation_job
        - remix_current
```

Hermes registers MCP tool names with a server prefix:

```text
mcp_floppy_search_audio_asset
mcp_floppy_generate_sleep_audio
mcp_floppy_get_generation_job
mcp_floppy_remix_current
```

The current `FLOPPY_AGENT_RUNTIME=hermes` path does not require MCP. It calls Hermes for a structured decision, then executes the selected Floppy workflow in-process. MCP is the next step when we want Hermes to perform tool calls directly.
