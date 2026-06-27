# Floppy Sleep Audio

Use this skill when the user wants sleep audio, bedtime stories, meditation guidance, ASMR ambience, white noise, relaxing music, or wants to change the background of the currently playing sleep audio.

Hermes is the decision layer. Floppy is the workflow executor. Do not invent playback URLs or job IDs. Select one Floppy workflow action and return the structured decision JSON expected by Floppy.

When the Floppy MCP server is enabled, the corresponding tools are:

- `mcp_floppy_search_audio_asset`
- `mcp_floppy_generate_sleep_audio`
- `mcp_floppy_get_generation_job`
- `mcp_floppy_remix_current`

## Available Actions

### `play_asset`

Use when Floppy provides candidate assets and one candidate already matches the request well enough.

Requirements:

- `asset_id` must be one of the provided candidate IDs.
- `selected_skill` must be `play_asset`.

### `generate_job`

Use when no candidate asset satisfies the user or the request is personalized enough that new audio should be generated.

Requirements:

- Only use when `generation_allowed=true`.
- `selected_skill` must be `generate_sleep_audio`.
- Include a `directive` whenever possible.
- Default meditation guidance should be around 20 minutes (`duration_sec=1200`) unless the user asks for a different duration.

Directive shape:

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

Allowed intent values:

- `white_noise`
- `music`
- `asmr`
- `story`
- `meditation`
- `podcast_digest`

### `remix_current`

Use when the user asks to add, change, reduce, increase, or remove a background layer on the currently playing audio.

Requirements:

- Only use when `current_asset_id` exists.
- `selected_skill` must be `remix_current`.
- Set `remix_sound_type` when the user mentions rain, ocean, forest, wind, fire, cafe, or similar ambience.

### `no_match`

Use when no candidate should be played and generation is not allowed.

## Output Format

Return exactly one JSON object. Do not return Markdown.

```json
{
  "action": "play_asset|generate_job|remix_current|no_match",
  "selected_skill": "play_asset|generate_sleep_audio|remix_current|no_match",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reasons": ["简短中文原因"],
  "confidence": 0.0
}
```

## Decision Priorities

1. If the user is modifying current playback and `current_asset_id` exists, prefer `remix_current`.
2. If a candidate asset has a strong match and does not conflict with the user request, use `play_asset`.
3. If the user asks for a specific personalized story, meditation, or voice/content combination, use `generate_job`.
4. If generation is not allowed and no candidate works, use `no_match`.
