# Unwind Weather Brief

Use this skill when the user asks about weather — "明天要不要带伞?", "今晚冷不冷?", "明天天气怎么样?" — or when tonight's real weather offers a natural bridge to audio ("外面在下雨" → real rain outside pairs with rain audio).

Backend status: available now. The backend injects a `weather` field into the decision context (fetched from Open-Meteo for a server-configured city — `FLOPPY_WEATHER_CITY`, the same for every user; there is currently no per-user city field). No new action — answer weather inside `chat`, or bridge into `play_asset` via the floppy-sleep-audio skill.

## Behavior

- Answer from the `weather` context field only. If it is absent (fetch failed), say you don't have today's weather right now — don't guess, and don't ask the user for their city (there's nowhere to save it yet).
- Keep it glanceable: rain/temperature swing/wind in one or two sentences, no full forecast recitation.
- Bridge to audio only when it is genuinely apt: real rain outside → "外面正好在下雨,要不要听会儿真雨声?" (then `play_asset` on a rain asset). Never force the bridge.

## Output Format

Weather answer inside `chat`:

```json
{
  "action": "chat",
  "selected_skill": "chat",
  "asset_id": null,
  "remix_sound_type": null,
  "directive": null,
  "reply": "明天白天有小雨,出门记得带伞。夜里 18 度,今晚盖好被子刚刚好。",
  "reasons": ["用户询问天气,基于 context 中的 weather 数据回答"],
  "confidence": 0.9
}
```

Weather-to-audio bridge: return a normal `play_asset` decision (see floppy-sleep-audio) with the weather woven into `reply`.

## Decision Priorities

1. Weather question with `weather` context present → answer directly.
2. `weather` context absent → say you don't have it right now, no guessing.
3. Rainy/windy night + user open to audio → optional bridge to `play_asset`.
4. Never invent weather data when the context field is missing.
