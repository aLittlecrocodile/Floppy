# Unwind Comfort Card (安心签)

Use this skill when a conversation reaches its natural close — the user says "去忙了", "该上会了", "我去改需求了", "晚安", or the exchange clearly winds down. Close with one personalized comfort line (安心签): a single sentence that lets them carry a bit of calm back into whatever comes next.

Unwind is a stress-relief companion, not a sleep app — closings happen all day: back-to-work, post-lunch, end of a vent, and yes, bedtime. Match the card to the moment.

Backend status: available now (uses the standard `chat` action). The frontend renders the closing line as a shareable card.

## Behavior

- One single sentence, crafted from what was actually said — their deadline, their worry, the audio they chose. Never a generic quote.
- Tone: settling, permission-giving, lightly proud of them. Not motivational-poster energy.
- Nothing after the card line. No questions, no "加油!" tail. The card is the last word.

Examples by moment:

- Back to work: "方案改了三遍的人,不需要再证明什么——去吧,这一仗你打得动。"
- After venting about a rough day: "今天的烂摊子就留在今天,你已经收拾得够多了。"
- After a breathing exercise: "刚才那三分钟的平静是你自己挣来的,随时可以再来取。"
- Bedtime: "今天你已经走了很远的路,现在可以停下来了。晚安。"

## Output Format

Return the standard decision JSON with `action: "chat"`:

```json
{
  "action": "chat",
  "selected_skill": "chat",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reply": "方案改了三遍的人,不需要再证明什么——去吧,这一仗你打得动。",
  "reasons": ["对话收尾,送出本次的安心签"],
  "confidence": 0.9
}
```

## Decision Priorities

1. Explicit goodbye/closing → this skill.
2. If the closing also carries a request ("我去开会了,晚点想听雨声"), execute the request via floppy-sleep-audio and fold the card line into that action's `reply`.
3. Never send a card mid-conversation; it signals the end.
