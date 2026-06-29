---
name: floppy-sleep-audio
description: Decide and execute Floppy sleep-audio playback, generation, and remix workflows through Floppy MCP tools.
version: 0.1.0
metadata:
  hermes:
    tags: [floppy, sleep-audio, mcp, agent]
    category: product-agents
---

# Floppy Sleep Audio

## When to Use

Use this skill when a user asks Floppy to play, find, generate, or remix sleep
audio, including bedtime stories, meditation, white noise, music, ASMR, or a
request to add or change background ambience.

## Design Rule

Hermes owns user intent understanding. Floppy backend tools are deterministic
resource and workflow executors:

- the Skill classifies user wording into intent, constraints, and workflow;
- MCP tools expose catalog facets, structured asset search, generation jobs, and
  remix jobs;
- Floppy backend enforces quotas, storage URLs, safety, job state, and exact
  asset validation;
- do not rely on the backend to translate Chinese phrases like 雨声, 钢琴, or
  不要人声 into tags.

## Available MCP Tools

Hermes registers Floppy MCP tools with the `mcp_floppy_` prefix:

- `mcp_floppy_get_user_profile_context`: read the user profile and generation budget.
- `mcp_floppy_list_audio_asset_facets`: inspect the current catalog surface:
  asset types, tags, mood tags, voices, user segments, and sample assets.
- `mcp_floppy_search_audio_assets`: search approved playable assets using
  structured filters. The backend executes the filters; it does not infer user
  intent from free text.
- `mcp_floppy_get_audio_asset`: fetch one approved asset by id.
- `mcp_floppy_generate_sleep_audio`: enqueue a generation job when no asset satisfies the request.
- `mcp_floppy_get_generation_job`: poll a generation job and read its output asset.
- `mcp_floppy_remix_current`: add an ambient layer to the current foreground asset.
- `mcp_floppy_get_remix_job`: poll a remix job and read its output asset.

## Intent Classes

Classify every request into one primary `audio_intent`:

- `white_noise`: rain, ocean, stream, forest, fan, fire, brown noise, pink noise,
  or other non-voice environmental sound.
- `music`: piano, strings, violin, flute, slow instrumental music, or light
  music.
- `meditation`: guided breathing, body scan, mindfulness, grounding, countdown,
  or other spoken practice.
- `story`: bedtime story, gentle narrative, fairy tale, scene-based companion
  story.
- `asmr`: whisper, close-mic comfort, ear-level spoken ambience, texture-based
  sleepy sound.
- `podcast_digest`: article, news, knowledge, or podcast transformed into
  low-density sleep audio.

Also classify the workflow goal:

- `play_existing`: user wants an existing playable asset if one matches.
- `generate_new`: user explicitly wants a new/custom asset, or no catalog asset
  satisfies a clear request and generation is allowed.
- `remix_current`: user wants to add/change/remove/adjust background ambience
  for the current asset.
- `no_match`: request is unsupported, unsafe, too ambiguous, or generation is
  not allowed and no asset matches.

## Structured Search Contract

Call `mcp_floppy_search_audio_assets` with:

```json
{
  "user_id": "<user id>",
  "query": "<short original or normalized wording>",
  "filters": {
    "type": "white_noise",
    "required_tags": ["rain", "no_voice"],
    "preferred_tags": ["ambient", "low_stimulation"],
    "negative_tags": ["thunder", "voice_present", "meditation"],
    "mood_tags": [],
    "min_duration_sec": null,
    "max_duration_sec": null
  },
  "limit": 10
}
```

Filter semantics:

- `required_tags`: all tags must exist on the asset.
- `preferred_tags`: soft ranking hints.
- `negative_tags`: exclude assets with any tag or type in this list. Type names
  such as `meditation`, `story`, `asmr`, and `podcast_digest` may be used here.
- `type`: strict asset type when the user intent is clear.
- `mood_tags`: use only when a mood is explicit or strongly supported by the
  user profile.
- duration bounds: use only when the user gives a duration/range.

Use `mcp_floppy_list_audio_asset_facets` before search when you are unsure what
tags exist. Prefer tags returned by facets; do not invent catalog tags.

Common mappings:

- 雨声 / 下雨 / 夜雨 / 细雨 -> `type=white_noise`,
  `required_tags=["rain","no_voice"]`.
- 无雷声 / 不要雷 -> add `negative_tags=["thunder"]`.
- 不要人声 / 不要说话 / 不要旁白 -> require `no_voice` and exclude
  `voice_present`; for non-voice requests also exclude spoken types.
- 海浪 / 海边浪声 -> `required_tags=["ocean","no_voice"]`.
- 溪流 / 流水 / 瀑布 -> `required_tags=["stream","no_voice"]`.
- 森林 / 林间 / 虫鸣 -> `required_tags=["forest","no_voice"]`.
- 风扇 / 空调底噪 -> `required_tags=["fan","no_voice"]`.
- 壁炉 / 篝火 / 柴火 -> `required_tags=["fire","no_voice"]`.
- 棕噪 -> `required_tags=["brown_noise","no_voice"]`.
- 钢琴轻音乐 -> `type=music`, `required_tags=["piano","no_voice"]`.
- 弦乐 / 小提琴 / 长笛 -> `type=music`, require `strings`, `violin`, or
  `flute` plus `no_voice`.
- 冥想 / 呼吸 / 身体扫描 -> `type=meditation`; do not add `no_voice` unless the
  user explicitly forbids voice.
- 睡前故事 / 讲故事 -> `type=story`.
- 文章 / 播客 / 简报 -> `type=podcast_digest`.

## Procedure

1. Read `mcp_floppy_get_user_profile_context(user_id)` before deciding. Treat
   `generation_budget` as mandatory context, but rely on the backend to enforce
   final quotas.
2. For ordinary playback and generation fallback decisions, call
   `mcp_floppy_list_audio_asset_facets(limit=12)` to learn the current catalog
   surface.
3. Classify the user request into `audio_intent`, workflow goal, hard
   constraints, and soft preferences. Build structured search filters from that
   classification.
4. For normal play requests, call `mcp_floppy_search_audio_assets` with the
   structured filters. Keep searches narrow when the user gives hard
   constraints.
5. Prefer playing an approved asset when a result clearly satisfies the request.
   Use the returned `asset.id` and `playback_url`; do not invent asset ids or
   URLs.
6. If the request is a remix/edit and `current_asset_id` is available, call
   `mcp_floppy_remix_current`. Poll with `mcp_floppy_get_remix_job` when the
   client needs the final output.
7. If no asset is good enough and generation is allowed, call
   `mcp_floppy_generate_sleep_audio` with a concise `directive` describing
   intent, tone, duration, voice style, content brief, outline, and key
   elements. Poll with `mcp_floppy_get_generation_job` when needed.
8. If generation is not allowed and search has no suitable result, return a
   no-match answer instead of creating a job.

## Pitfalls

- Do not skip catalog search for ordinary playback requests unless the user
  explicitly asks to generate a fresh audio asset.
- Do not play meditation/story/podcast assets for a white-noise request just
  because they mention rain or ocean.
- Do not call generation or remix tools just because a score is imperfect; use
  the user request, profile context, and catalog facets to judge the best
  action.
- Do not play a weak candidate when the requested sound is not represented in
  catalog facets. Generate when allowed and the request is clear; otherwise
  return no-match.
- Do not bypass Floppy backend APIs for storage, quotas, safety, or job state.
- Generation and remix are asynchronous. A queued job is a valid successful
  action; the client can poll for completion.

## Verification

Confirm the final answer or API payload contains one of:

- a playable approved asset for playback,
- a generation job id for newly generated sleep audio,
- a remix job id for ambient edits,
- or a no-match result when no safe/actionable path is available.
