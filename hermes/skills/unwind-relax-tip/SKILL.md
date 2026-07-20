# Unwind Relax Tip

Use this skill when the user is anxious, tense, or panicky RIGHT NOW and needs immediate relief — "我现在很紧张", "心跳好快", "静不下来", "焦虑得睡不着" — and a full generated meditation audio would be too slow. This delivers an instant guided exercise inside the reply itself.

Backend status: available now (uses the standard `chat` action, no new backend support needed).

## Behavior

Pick ONE exercise that fits the moment. Do not list options; just start guiding.

- **4-7-8 呼吸** (racing heart, can't calm down): guide inhale 4 — hold 7 — exhale 8, two or three rounds.
- **5-4-3-2-1 着地** (spiraling thoughts, panic): guide noticing 5 things seen, 4 touched, 3 heard, 2 smelled, 1 tasted.
- **渐进放松** (body tension): tense-then-release from shoulders down.

Requirements:

- Short sentences with natural pauses ("……"). The voice pipeline reads the reply aloud sentence by sentence.
- One instruction at a time. Never dump the whole exercise as a numbered list.
- Warm, low, unhurried — a friend sitting beside you, not an instructor.
- End by asking softly how they feel, or offer to continue.

## Output Format

Return the standard decision JSON with `action: "chat"`:

```json
{
  "action": "chat",
  "selected_skill": "chat",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reply": "没事,我陪着你。先跟我做一次:轻轻吸气……1、2、3、4……屏住……慢慢来。",
  "reasons": ["用户当下焦虑,进行即时呼吸引导"],
  "confidence": 0.9
}
```

## Decision Priorities

1. Acute anxiety expressed now → this skill, immediately, no selling.
2. If the user instead asks for meditation *audio* to play, defer to the floppy-sleep-audio skill (`play_asset` / `generate_job`).
3. After two or three guided rounds, it is natural to offer a matching asset ("要不要我放一段呼吸冥想陪你继续?").
