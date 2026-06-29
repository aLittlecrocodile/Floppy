---
name: floppy-safety-quality
description: Check Floppy sleep scripts for safety, low stimulation, pause quality, and cost risk before audio generation.
version: 0.1.0
metadata:
  hermes:
    tags: [floppy, safety, quality, script, mcp]
    category: product-agents
---

# Floppy Safety Quality

## When to Use

Use this skill before sending any custom spoken script to TTS, when reviewing an
LLM-written script, or when a user asks why a generation request was rejected.

The backend generation workflow already runs this gate. This skill is for
explicit Hermes-side checks and repair loops.

## Available MCP Tools

Hermes registers Floppy MCP tools with the `mcp_floppy_` prefix:

- `mcp_floppy_check_sleep_script_safety`: run the script guard.
- `mcp_floppy_generate_sleep_audio`: create a generation job after a script or
  directive is safe enough for backend execution.
- `mcp_floppy_get_generation_job`: inspect script status and generated asset.

## Safety Policy

Block or repair content containing:

- terror, horror, sudden shock, screams, alarms, explosions;
- violence, war, weapons, blood, injury;
- medical diagnosis, treatment, cure, clinical claims, or guaranteed sleep;
- urgent/high-pressure language;
- explicit sexual content;
- high-arousal language that conflicts with sleep.

## Quality Policy

A good sleep script should:

- have enough readable content for a useful audio segment;
- use MiniMax pause markers like `<#3#>` naturally;
- include at least a few pauses;
- avoid very long single pauses;
- keep cost and length within product limits;
- sound low-stimulation, slow, and non-demanding.

## Procedure

1. For any custom script, call `mcp_floppy_check_sleep_script_safety` with the
   script and estimated duration.
2. If status is `approved`, continue to generation.
3. If status is `low_quality`, repair the script by adding slow pacing,
   breathing room, or reducing length, then check again.
4. If status is `blocked`, remove unsafe content or refuse when the unsafe
   request is central to the user's ask.
5. If the backend generation job later returns failed with a script guard
   message, explain it briefly and offer a safer alternative.

## Repair Guidance

- Replace urgent language with optional, gentle wording.
- Replace medical promises with non-clinical relaxation language.
- Remove horror, violence, shock, and explicit material entirely.
- Add short pauses every one or two short sentences.
- Keep the user free from pressure: “不需要马上睡着，只要慢慢休息”.

## Pitfalls

- Do not weaken the safety gate to satisfy a specific request.
- Do not promise treatment, diagnosis, or guaranteed sleep.
- Do not send a blocked script to TTS.
- Do not hide the fact that content was changed for safety.

## Verification

Before TTS, the final script check should return:

```json
{
  "status": "approved",
  "safe": true,
  "quality_ok": true
}
```
