---
name: floppy-playback-control
description: Record Floppy playback starts, active playback, feedback, and listening history through MCP tools.
version: 0.1.0
metadata:
  hermes:
    tags: [floppy, playback, feedback, history, mcp]
    category: product-agents
---

# Floppy Playback Control

## When to Use

Use this skill when an asset starts playing, when the user reacts to playback,
when the user asks to continue or edit the current playback, or when a workflow
needs listening history.

This skill records and reads playback state. It does not choose audio content;
use `floppy-sleep-audio` for content decisions.

## Available MCP Tools

Hermes registers Floppy MCP tools with the `mcp_floppy_` prefix:

- `mcp_floppy_start_playback`: record a playback start.
- `mcp_floppy_submit_playback_feedback`: record skip, favorite, dislike,
  complete, trial rating, progress, or morning feedback.
- `mcp_floppy_get_playback_history`: fetch recent playback records.
- `mcp_floppy_get_active_playback`: fetch the latest unfinished playback.
- `mcp_floppy_get_audio_asset`: validate an asset before recording playback.

## Playback Sources

Use one of:

- `recommend`: catalog search result.
- `generated`: newly generated sleep audio.
- `remix`: remix output.
- `import`: user uploaded audio.

## Procedure

1. When `floppy-sleep-audio`, `floppy-content-transform`, or remix returns a
   playable asset, call `mcp_floppy_start_playback` with asset id, source, and
   the user request text.
2. If the user says “这个不错”, “收藏”, “不喜欢”, “跳过”, “播完了”, or gives a
   rating, call `mcp_floppy_submit_playback_feedback`.
3. If the user asks to change current playback, first call
   `mcp_floppy_get_active_playback`. Pass the active asset id to
   `floppy-sleep-audio` for remix decisions.
4. Use `mcp_floppy_get_playback_history` when the user asks for “上次那个”,
   “类似刚才的”, or when preference memory is needed.

## Feedback Mapping

- “收藏 / 喜欢 / 这个不错” -> `favorite`.
- “不喜欢 / 别放这个” -> `dislike`.
- “跳过 / 换一个” -> `skip`, then route to `floppy-sleep-audio`.
- “播完了 / 听完了” -> `complete`.
- “早上感觉...” -> `morning_feedback`.
- “给 4 分” -> `trial_rating` with `rating=4`.

## Pitfalls

- Do not record playback for chat-only or clarify-only turns.
- Do not mark playback complete unless the user or client event indicates
  completion.
- Do not remix without an active playback or explicit current asset id.
- Do not invent record ids; use the returned `record_id`.

## Verification

After a playback action, the system should have:

- a playback record id for started audio,
- active playback available until completion,
- and feedback/history available for future personalization.
