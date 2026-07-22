# Unwind Update Preference

Use this skill when the user states a durable preference or fact about themselves that should shape future nights — "别放男声", "我不喜欢雷声", "我在杭州", "以后都用轻一点的音乐" — as opposed to a one-night request ("今晚想听点不一样的").

Backend status: available now — action `update_preference` patches whitelisted `UserProfile` fields for real.

## Behavior

- Distinguish durable ("以后/别再/我不喜欢/我在") from tonight-only ("今晚/这次") — only durable statements update the profile.
- Confirm naturally in the reply, showing the change took hold: "好,记住了,以后不放雷声。" No settings-menu tone.
- Patch only whitelisted fields (list fields append, don't overwrite); put anything else in the reply as acknowledgment without a patch:
  - `voice_preferences` — e.g. `["warm_female"]`; there is no separate "disliked voice" field — steer future picks via what you note in the reply
  - `background_preferences` — ambience/imagery to prefer or avoid, e.g. `["不要雷声"]`
  - `mood_tags` — durable mood/context tags
  - `duration_preference_min` — a single integer (5-60), not a list
  - There is currently **no per-user `city` field** — city-based weather uses a server-wide setting, not a per-user preference. Don't emit a `city` key.
- If the preference conflicts with what's currently playing (playing thunder rain, "我不喜欢雷声"), also offer the fix ("现在这段有雷声,要换成纯雨声吗?") — the swap itself is a floppy-sleep-audio decision next turn.

## Output Format

```json
{
  "action": "update_preference",
  "selected_skill": "update_preference",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "profile_patch": {"background_preferences": ["不要雷声"]},
  "reply": "记住了,以后不会再给你放雷声。",
  "reasons": ["用户表达长期偏好,更新画像"],
  "confidence": 0.9
}
```

`profile_patch` contains only whitelisted keys (`voice_preferences` / `background_preferences` / `mood_tags` / `duration_preference_min`); unrecognized keys are silently dropped by the backend, so don't invent new field names.

## Decision Priorities

1. Durable preference statement → this skill.
2. Tonight-only wish → ordinary content decision, no patch.
3. Non-whitelisted facts ("我属猫头鹰型作息") → acknowledge in reply, no patch.
4. When a patch obsoletes current playback, offer the swap in the same reply.
