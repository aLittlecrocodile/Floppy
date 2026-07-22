# Unwind Sleep Timer

Use this skill when the user wants playback to stop or fade after a while — "播 20 分钟就停", "半小时后关掉", "声音慢慢变小", "午休放 15 分钟", "别放一整晚".

Backend status: available now — action `sleep_timer` is live. The timer executes on the frontend player (countdown + volume fade); the backend only logs an event.

## Behavior

- Parse the duration from the user's words into seconds. "二十分钟" → 1200; "半小时" → 1800; "一小时" → 3600.
- No duration stated ("放一会儿就停") → default 1200 and say so in the reply so they can correct it.
- "慢慢变小 / 渐弱" without a stop request → timer with `fade_out: true` and a default 900s.
- Reply confirms in sleep-friendly terms: "好,20 分钟后它会慢慢安静下来,你不用管了。"
- Requires something playing or about to play (`current_asset_id` present, or combined with a `play_asset` this turn — then set the timer fields on that play decision instead).

## Output Format

```json
{
  "action": "sleep_timer",
  "selected_skill": "sleep_timer",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "timer_sec": 1200,
  "fade_out": true,
  "reply": "好,20 分钟后声音会慢慢淡下去,像有人帮你关灯。安心睡。",
  "reasons": ["用户要求定时停止播放"],
  "confidence": 0.9
}
```

`timer_sec` is an integer in seconds; `fade_out` defaults to true.

## Decision Priorities

1. Explicit timer request with something playing → this skill.
2. Timer + new content in one utterance ("放雨声,20分钟后停") → `play_asset` / `generate_job` decision carrying `timer_sec` + `fade_out`.
3. Nothing playing and no play request → clarify gently what they'd like to hear first.
