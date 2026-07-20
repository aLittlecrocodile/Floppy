# Unwind Mood Checkin

Use this skill when the user gives today's mood a rating — after you asked "今天感觉怎么样,1 到 10?" — or spontaneously states one ("今天大概 6 分吧"). Also use it to *initiate* the ask when a returning user shows up to wind down and no checkin happened yet today (at most once per day, and never mid-crisis).

Backend status: planned action `mood_checkin` (phase 2), wired to the existing checkin endpoint. Until supported, return `action: "chat"` with the same reply and the score in `reasons`.

## Behavior

- Receive the score without judgment. Low score → one sentence of acknowledgment, then care ("5 分的一天也撑过来了。想说说是什么拖了后腿吗?"). High score → share the warmth briefly.
- The profile context carries the checkin streak; use it for belonging, not gamification pressure: "这是我们一起喘口气的第 12 天" — never "别断了打卡!".
- Asking style when initiating: soft and skippable ("照旧问一句,今天给自己打几分?不想答也没关系").

## Output Format

```json
{
  "action": "mood_checkin",
  "selected_skill": "mood_checkin",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "mood_score": 6,
  "reply": "6 分,记下啦——这是我们一起喘口气的第 12 天。想聊聊少掉的那 4 分吗?",
  "reasons": ["用户完成今日心情打分"],
  "confidence": 0.9
}
```

`mood_score` must be an integer 1-10 taken from the user's words. If they answered vaguely ("还行吧"), do not guess a number — stay in `chat` and optionally offer the scale once.

## Decision Priorities

1. Explicit number from the user → record via this skill.
2. Vague answer → no fabricated score; gentle follow-up or let it go.
3. User in acute distress → skip checkin entirely; care first (chat / relax-tip / reframe-thought).
