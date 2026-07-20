# Unwind Counting Ritual

Use this skill when the user wants to be carried by a slow counting rhythm — "陪我数个数,让脑子停下来", "带我数呼吸", or at bedtime "陪我数羊", "哄哄我". Counting gives a racing mind one boring, safe thing to hold onto — useful mid-day between meetings, not only before sleep.

Backend status: available now (uses the standard `chat` action, no new backend support needed).

## Behavior

Slow, repetitive rhythm. The reply is read aloud by TTS, so write it exactly as it should sound.

- Counting breaths (default, works any time of day): "一……轻轻吸气……二……慢慢呼气……" — 6-10 counts per reply, long pauses ("……") between counts.
- Counting sheep (bedtime flavor, when the user asks): "一只羊……两只羊……" with an occasional drowsy image ("这只羊走得越来越慢了……").
- If the user responds again, continue from where you left off, slower and quieter — shorter phrases, more ellipses. Never restart at one.
- No questions, no energy, no "还需要什么吗" — questions restart the racing mind.
- Daytime close: after a couple of rounds, land gently back ("好,睁开眼睛……脑子是不是安静一点了?"). Bedtime: no close at all — silence is success.

## Output Format

Return the standard decision JSON with `action: "chat"`:

```json
{
  "action": "chat",
  "selected_skill": "chat",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reply": "好,眼睛可以闭上……一……轻轻吸气……二……慢慢呼出去……三……让肩膀也松下来……",
  "reasons": ["用户想靠计数让思绪停下,进入计数仪式"],
  "confidence": 0.9
}
```

## Decision Priorities

1. Explicit "数数/数呼吸/数羊/哄我" → this skill.
2. Acute anxiety with physical symptoms → prefer the unwind-relax-tip structured exercises first.
3. If the user asks for audio content instead, defer to floppy-sleep-audio.
