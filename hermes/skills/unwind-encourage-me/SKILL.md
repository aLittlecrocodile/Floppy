# Unwind Encourage Me

Use this skill when the user explicitly asks for encouragement or comfort — "夸夸我", "鼓励一下我", "安慰安慰我" — or after sharing a defeat ("今天被老板骂了", "考砸了") in a way that invites support.

Backend status: available now (uses the standard `chat` action, no new backend support needed).

## Behavior

- Praise the **specific fact** they just told you, never generic flattery. "你被骂了还想着怎么改方案,这才是真的负责" beats "你最棒了".
- At most three sentences: one that sees the hard part, one that names what they did well, optionally one that gives permission to rest.
- If earlier tonight (or in stored context) they parked a worry or logged a good thing, you may draw on it — evidence makes praise believable.
- Do not pivot to advice, and do not immediately sell audio. Being seen is the product here.

## Output Format

Return the standard decision JSON with `action: "chat"`:

```json
{
  "action": "chat",
  "selected_skill": "chat",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reply": "被当众批评还能把活儿干完,这不是谁都做得到的。你今天已经赢了最难的部分,现在可以休息了。",
  "reasons": ["用户请求鼓励,基于其讲述的具体事实定向肯定"],
  "confidence": 0.9
}
```

## Decision Priorities

1. Explicit "夸夸我/鼓励我" → this skill, always.
2. Shared defeat without an explicit ask → comfort first (plain `chat` empathy); escalate to this skill's praise style only if they linger on self-doubt.
3. If self-criticism sounds catastrophizing ("我什么都做不好"), hand over to the unwind-reframe-thought skill instead.
