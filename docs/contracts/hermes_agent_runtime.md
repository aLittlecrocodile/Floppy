# Hermes Agent Runtime Integration

## Goal

Floppy keeps ownership of product APIs, asset storage, generation jobs, MiniMax audio generation, and remix workflows.

Hermes Agent is used as the agent decision runtime:

```text
App / Voice WS / Demo
  -> Floppy /agent runtime
    -> Hermes plans structured catalog search
    -> Floppy executes deterministic resource tools
    -> Hermes decides selected workflow skill
    -> Floppy executes play_asset / generate_sleep_audio / remix_current
```

This avoids binding product workflow state to Hermes internals while replacing the hand-written agent planner with a real agent runtime.

## Runtime Switch

Hermes is the only supported agent runtime:

```bash
FLOPPY_AGENT_RUNTIME=hermes
FLOPPY_HERMES_BASE_URL=http://127.0.0.1:8642
FLOPPY_HERMES_API_KEY=change-me-local-dev
FLOPPY_HERMES_MODEL=DeepSeek-V4-Flash
```

`FLOPPY_AGENT_RUNTIME=local` is no longer supported. Old local fallback env vars are ignored by settings compatibility, but the runtime factory will reject non-Hermes runtimes.

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

## Search Plan Contract

Hermes first translates user wording into a structured catalog search plan:

```json
{
  "query": "雨声",
  "filters": {
    "type": "white_noise",
    "mood_tags": [],
    "required_tags": ["rain", "no_voice"],
    "preferred_tags": ["ambient", "low_stimulation"],
    "negative_tags": ["thunder", "voice_present", "meditation"],
    "min_duration_sec": null,
    "max_duration_sec": null
  },
  "limit": 10,
  "reasons": ["用户要非人声雨声，且排除雷声"],
  "confidence": 0.95
}
```

The backend catalog does not translate Chinese phrases into tags. It only
executes `type`, `required_tags`, `preferred_tags`, `negative_tags`, `mood_tags`,
and duration filters.

## Decision Contract

After Floppy executes the search plan, Hermes returns one workflow JSON object:

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

This migration stage uses Hermes as an HTTP Skill runtime with two structured
calls:

1. Hermes produces the catalog search plan.
2. Floppy executes the resource search tool locally.
3. Hermes selects the workflow action.

This keeps user intent logic in Hermes while Floppy keeps quota, storage, safety,
and job enforcement. Floppy still executes tools locally after Hermes returns the
selected action.

The standard Hermes target is:

```text
Hermes Skill: floppy-sleep-audio
  -> Hermes MCP toolset: mcp-floppy
    -> Floppy backend APIs
      -> asset search / generation jobs / remix jobs / storage / quotas
```

The Skill owns product policy and tool-use procedure. The MCP server exposes resource and workflow tools. Floppy backend APIs remain the enforcement boundary for quotas, safety, storage URLs, and asynchronous job state.

The next stage lets Hermes call:

- `mcp_floppy_get_user_profile_context`
- `mcp_floppy_list_audio_asset_facets`
- `mcp_floppy_search_audio_assets`
- `mcp_floppy_search_audio_asset`
- `mcp_floppy_get_audio_asset`
- `mcp_floppy_generate_sleep_audio`
- `mcp_floppy_remix_current`
- `mcp_floppy_get_generation_job`
- `mcp_floppy_get_remix_job`

That MCP server is scaffolded as an optional entry point. The repository also includes a Hermes Skill at `hermes/skills/floppy/floppy-sleep-audio/SKILL.md`.

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
        - get_user_profile_context
        - list_audio_asset_facets
        - search_audio_assets
        - get_audio_asset
        - generate_sleep_audio
        - get_generation_job
        - remix_current
        - get_remix_job
      resources: false
      prompts: false
```

Hermes registers MCP tool names with a server prefix:

```text
mcp_floppy_get_user_profile_context
mcp_floppy_list_audio_asset_facets
mcp_floppy_search_audio_assets
mcp_floppy_get_audio_asset
mcp_floppy_generate_sleep_audio
mcp_floppy_get_generation_job
mcp_floppy_remix_current
mcp_floppy_get_remix_job
```

The current Hermes adapter path does not require direct MCP tool calling. It
uses the same Skill/tool contracts, asks Hermes for structured plans and
decisions, then executes the selected Floppy workflow in-process. Direct Hermes
MCP tool calling is the next step when the gateway is wired to invoke the MCP
server itself.

## Hermes Skill Registration

Expose this repository's skill directory through Hermes config:

```yaml
skills:
  external_dirs:
    - /path/to/Floppy/hermes/skills
```

Hermes will discover the `floppy-sleep-audio` skill and load it on demand. The skill tells Hermes to read profile context, inspect catalog facets when needed, search assets before ordinary playback, generate only when appropriate, and keep all execution through Floppy MCP tools.
