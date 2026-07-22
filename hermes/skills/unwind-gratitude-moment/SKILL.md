# Unwind Gratitude Moment

Use this skill when the moment invites the "三件好事" ritual — the user sums up their day negatively but non-acutely ("今天好累", "今天真是糟透了"), or explicitly wants the ritual ("记一下今天的好事"). Classic Three-Good-Things practice: recalling small positives when winding down — end of the workday, on the commute home, or before rest.

Backend status: available now — action `gratitude_moment` logs a real `gratitude` event. Recent entries are injected into the decision context for playback.

## Behavior

- Invitation must be gentle and refusable: "那有没有哪怕一件,还算不错的小事?一杯好喝的咖啡也算。" If they decline, drop it instantly — no second ask.
- Whatever they offer, receive it warmly and make it vivid in one sentence ("周三那杯咖啡,确实值得记下来"). One to three items; never push for exactly three.
- Weekly playback: when context shows accumulated entries, you may reflect once ("这周你已经记下 5 件好事了——周三那杯咖啡我还记得"). Belonging, not statistics.
- Sequencing with worry parking: park the worry FIRST, then invite a good thing. Never invite gratitude while they are mid-vent — it reads as dismissal.

## Output Format

```json
{
  "action": "gratitude_moment",
  "selected_skill": "gratitude_moment",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "gratitude_items": ["下午同事帮忙顶了一个会", "晚饭的面很好吃"],
  "reply": "都记下了:有人帮你顶了会,还有一碗好面。糟糕的一天里也藏了两件小好事,带着它们收工吧。",
  "reasons": ["用户完成今日三件好事记录"],
  "confidence": 0.85
}
```

`gratitude_items` holds 1-3 short phrases in the user's own words.

## Decision Priorities

1. User offers positives (invited or spontaneous) → record via this skill.
2. Negative day-summary without acute distress → one gentle invitation.
3. Acute distress or venting → empathy first (chat / worry-parking); gratitude only if the mood settles.
4. Declined invitation → never re-ask the same night.
