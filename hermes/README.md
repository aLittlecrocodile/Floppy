# Floppy Hermes Integration

Floppy uses Hermes in the standard Hermes shape:

- Skills: product policy and tool-use procedure for voice routing and sleep-audio decisions.
- MCP server: Floppy-owned resource and workflow tools.
- Backend APIs: durable execution, quotas, storage, safety, and job state.

## Register the Skill

Expose this repository's skills directory to Hermes:

```yaml
skills:
  external_dirs:
    - /path/to/Floppy/hermes/skills
```

Hermes will discover:

- `floppy-content-transform` from `hermes/skills/floppy/floppy-content-transform/SKILL.md`
- `floppy-playback-control` from `hermes/skills/floppy/floppy-playback-control/SKILL.md`
- `floppy-profile-context` from `hermes/skills/floppy/floppy-profile-context/SKILL.md`
- `floppy-safety-quality` from `hermes/skills/floppy/floppy-safety-quality/SKILL.md`
- `floppy-voice-dialog` from `hermes/skills/floppy/floppy-voice-dialog/SKILL.md`
- `floppy-sleep-audio` from `hermes/skills/floppy/floppy-sleep-audio/SKILL.md`

## Register the MCP Server

Start the Floppy backend first, then add the stdio MCP server:

```bash
hermes mcp add floppy \
  --command /path/to/Floppy/.venv/bin/python \
  --args -m \
  --args floppy_backend.mcp_server \
  --env FLOPPY_MCP_BACKEND_URL=http://127.0.0.1:8000
```

Equivalent `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  floppy:
    command: "/path/to/Floppy/.venv/bin/python"
    args: ["-m", "floppy_backend.mcp_server"]
    env:
      FLOPPY_MCP_BACKEND_URL: "http://127.0.0.1:8000"
    tools:
      include:
        - get_user_profile
        - get_user_profile_context
        - update_profile_checkin
        - get_user_questionnaire
        - save_user_questionnaire
        - list_audio_asset_facets
        - search_audio_assets
        - get_audio_asset
        - generate_sleep_audio
        - get_generation_job
        - start_playback
        - submit_playback_feedback
        - get_playback_history
        - get_active_playback
        - remix_current
        - get_remix_job
        - list_uploads
        - get_upload
        - retry_upload
        - delete_upload
        - generate_audio_from_upload
        - check_sleep_script_safety
      resources: false
      prompts: false
```

Hermes registers those as `mcp_floppy_<tool_name>`, for example
`mcp_floppy_search_audio_assets`.

## Migration Notes

The current `/agent/decide` path uses the same Skill/tool contract through a
local adapter:

1. Hermes turns user wording into a structured asset search plan.
2. Floppy executes the deterministic catalog search tool.
3. Hermes chooses `play_asset`, `generate_sleep_audio`, `remix_current`, or
   `no_match`.
4. Floppy executes the selected workflow in-process.

The current `/voice/intent` path is conversation-first:

1. Hermes `floppy-voice-dialog` routes ASR text to `chat`, `clarify`,
   `audio_workflow`, `remix_current`, or `no_match`.
2. Only `audio_workflow` and `remix_current` continue into `floppy-sleep-audio`.
3. Chat and clarification turns return text only and do not search/generate.

Additional Skills now expose the product surface around the audio workflow:

- `floppy-profile-context` reads profile, questionnaire, behavior memory, and
  budget context.
- `floppy-playback-control` records play starts, active playback, history, and
  feedback.
- `floppy-content-transform` turns txt uploads into sleep-audio generation jobs.
- `floppy-safety-quality` checks custom scripts before TTS.

The direct MCP path is the next runtime step: Hermes loads
Floppy Skills, calls Floppy MCP tools directly, and Floppy keeps backend
enforcement for generation budgets, asset validation, playback state, storage
URLs, safety, and asynchronous job execution.
