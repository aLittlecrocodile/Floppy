# Unwind Update Preference

Use this skill when the user states a durable preference or fact about themselves that should shape future nights — "别放男声", "我不喜欢雷声", "我在杭州", "以后都用轻一点的音乐" — as opposed to a one-night request ("今晚想听点不一样的").

Backend status: planned action `update_preference` (phase 4), which patches whitelisted `UserProfile` fields. Until supported, return `action: "chat"` acknowledging you'll keep it in mind (conversation memory still helps within the session).

## Behavior

- Distinguish durable ("以后/别再/我不喜欢/我在") from tonight-only ("今晚/这次") — only durable statements update the profile.
- Confirm naturally in the reply, showing the change took hold: "好,记住了,以后不放雷声。" No settings-menu tone.
- Patch only whitelisted fields; put anything else in the reply as acknowledgment without a patch:
  - `preferred_voice_style` — e.g. `warm_female`, `warm_male`, `whisper_female`
  - `disliked_elements` — imagery/sounds to avoid, e.g. `["雷声", "男声"]` (append, don't overwrite)
  - `city` — for the weather brief skill
- If the preference conflicts with what's currently playing (playing thunder rain, "我不喜欢雷声"), also offer the fix ("现在这段有雷声,要换成纯雨声吗?") — the swap itself is a floppy-sleep-audio decision next turn.

## Output Format

```json
{
  "action": "update_preference",
  "selected_skill": "update_preference",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "profile_patch": {"disliked_elements": ["雷声"]},
  "reply": "记住了,以后不会再给你放雷声。",
  "reasons": ["用户表达长期偏好,更新画像"],
  "confidence": 0.9
}
```

`profile_patch` contains only whitelisted keys; values in the user's own terms mapped to known enums where applicable.

## Decision Priorities

1. Durable preference statement → this skill.
2. Tonight-only wish → ordinary content decision, no patch.
3. Non-whitelisted facts ("我属猫头鹰型作息") → acknowledge in reply, no patch.
4. When a patch obsoletes current playback, offer the swap in the same reply.
