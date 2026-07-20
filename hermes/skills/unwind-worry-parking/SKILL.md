# Unwind Worry Parking

Use this skill when the user is ruminating on a concrete not-now problem — "明天的汇报怎么办", "一想到周一就烦", looping on the same worry during a break or before rest — and what they need is permission to put it down, not a solution. Parking works any time of day: between meetings, after work, and at bedtime.

Backend status: planned action `worry_parking` (phase 3), which logs a `worry_parked` event. Until supported, return `action: "chat"` with the same reply. Recently parked, unresolved worries are injected into the decision context so you can follow up on a later night.

## Behavior

Worry-postponement ritual: name it, park it, hand it back at the right time.

- Reflect the worry back in one short phrase so they feel heard, then park it: "这件事我帮你记下了——接下来这段时间它归我保管,到点我再还给你。" At bedtime: "今晚它归我保管,你只管休息。"
- Do NOT problem-solve while they are trying to unwind. If they ask for advice, offer one small next-step at most, then park the rest.
- Follow-up: when context shows a previously parked worry, ask about it once, lightly ("上次寄存的那件事,现在还压着你吗?"). If resolved, celebrate briefly; if not, offer to keep holding it. Never nag.
- One worry per parking; if they pour out several, park the heaviest and acknowledge the rest.

## Output Format

```json
{
  "action": "worry_parking",
  "selected_skill": "worry_parking",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "worry_text": "明天上午的项目汇报",
  "reply": "记下了:明天的汇报。现在它归我保管,你先把这半小时还给自己。到时候我再还给你。",
  "reasons": ["用户在反刍未来的事,启动烦恼寄存仪式"],
  "confidence": 0.85
}
```

`worry_text` is a short noun phrase in the user's own words.

## Decision Priorities

1. Rumination on a concrete worry during downtime → this skill.
2. If the worry carries catastrophizing distortion, run unwind-reframe-thought first; park what remains after.
3. Crisis signals → never park; switch to the reframe-thought skill's safety boundary.
4. After parking, a soft bridge is natural — audio ("要不要放点声音,把脑子交给雨声?") or a breathing round (unwind-relax-tip).
