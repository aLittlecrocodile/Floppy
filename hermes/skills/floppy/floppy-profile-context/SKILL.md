---
name: floppy-profile-context
description: Read and update Floppy user profile, questionnaire, nightly check-in, and generation budget context.
version: 0.1.0
metadata:
  hermes:
    tags: [floppy, profile, context, memory, mcp]
    category: product-agents
---

# Floppy Profile Context

## When to Use

Use this skill before personalization-heavy decisions, before generation, and
when the user shares durable sleep preferences or tonight-specific state.

This skill prepares context. It should not decide which audio to play by itself.
Hand the prepared context to `floppy-voice-dialog`, `floppy-sleep-audio`, or
`floppy-content-transform` as needed.

## Design Rule

Hermes interprets user meaning. Floppy stores structured profile state and
budget state.

Use profile fields as hints, not hard rules. Explicit user constraints in the
current turn override profile preferences.

## Available MCP Tools

Hermes registers Floppy MCP tools with the `mcp_floppy_` prefix:

- `mcp_floppy_get_user_profile_context`: profile plus daily generation budget.
- `mcp_floppy_get_user_profile`: persisted profile without budget.
- `mcp_floppy_update_profile_checkin`: tonight mood, stress, or sleep latency hint.
- `mcp_floppy_get_user_questionnaire`: onboarding answers.
- `mcp_floppy_save_user_questionnaire`: save onboarding answers.
- `mcp_floppy_get_playback_history`: recent behavior memory for preference inference.

## Procedure

1. Call `mcp_floppy_get_user_profile_context(user_id)` when a downstream
   workflow may generate or personalize audio.
2. Call `mcp_floppy_get_user_questionnaire(user_id)` when the user asks for
   personalized suggestions, onboarding is in progress, or profile context
   feels sparse. If the tool returns 404, continue without questionnaire data.
3. Call `mcp_floppy_get_playback_history(user_id, limit=20)` when past behavior
   matters, such as “再来一个类似的”, dislikes, favorites, or morning feedback.
4. When the user gives tonight-only state, call
   `mcp_floppy_update_profile_checkin`. Examples: “今晚很焦虑”, “我大概要半小时才睡着”.
5. When the user gives durable preferences, update the questionnaire or profile
   only when the user clearly indicates a stable preference.

## Interpretation Policy

- Tonight check-in is short-lived context: mood, stress, sleep latency hint.
- Questionnaire is durable context: bedtime, habits, preferred content style,
  favorite content types, and voice preference.
- Playback history is behavioral context: skips, completions, favorites,
  dislikes, progress, ratings, and morning feedback.
- Generation budget is mandatory before creating jobs, but backend enforcement
  remains authoritative.

## Pitfalls

- Do not override an explicit current request with profile preference.
- Do not infer medical conditions from casual wording.
- Do not save a durable preference from one ambiguous utterance.
- Do not expose raw internal profile fields to the user unless they ask.

## Verification

The downstream workflow should receive:

- profile context or a graceful missing-profile explanation,
- optional questionnaire and playback history when useful,
- and an updated check-in when the user gave tonight-specific state.
