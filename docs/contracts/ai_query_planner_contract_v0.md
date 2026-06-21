# AI Query Planner Contract v0

> 2026-06-21 | 主路径 = LLM structured output；规则仅作 fallback/安全兜底

---

## 1. Input Schema

```python
class QueryPlannerInput(BaseModel):
    request_text: str                          # 用户自然语言（中文）
    profile: ProfileContext                    # 长期偏好 + 当晚状态 + 行为信号
    history: list[RecentPlayback]              # 最近5条播放记录（asset_id, completion_rate, feedback）
    available_tags: list[str]                  # 当前系统 tag taxonomy（动态传入）
    budget_remaining: GenerationBudget         # 剩余预算
    safety_constraints: list[str]              # 固定: ["no_horror","no_medical_claim","no_high_stimulation"]
```

`available_tags` 从 DB 动态加载，AI 只能从此列表选择 tag（防幻觉）。

---

## 2. AI Output JSON Schema

```json
{
  "intent": "meditation",
  "audio_type": "meditation",
  "preferred_tags": ["rain", "breathing", "slow_pace", "warm_voice"],
  "negative_tags": ["suspense", "high_energy"],
  "mood": ["anxious", "tired"],
  "duration_bucket": "medium",
  "voice_style": "warm_female",
  "background": "rain_soft",
  "generation_allowed_hint": true,
  "confidence": 0.85,
  "reason_codes": ["mood_detected:anxious", "explicit_request:rain", "segment_boost:anxiety_relief"]
}
```

| Field | Type | Constraint |
|-------|------|-----------|
| intent | AudioType enum | 必填，从 story/meditation/asmr/white_noise/podcast_digest/music |
| audio_type | AudioType enum | = intent（冗余，兼容现有字段）|
| preferred_tags | list[str] | 必须 ⊆ available_tags，max 8 |
| negative_tags | list[str] | 必须 ⊆ available_tags，max 6 |
| mood | list[str] | 自由文本，max 3 |
| duration_bucket | "short"\|"medium"\|"long" | short≤10min, medium≤20, long>20 |
| voice_style | str | 从已知声线列表选 |
| background | str | 从已知背景音列表选 |
| generation_allowed_hint | bool | AI 建议是否生成（backend 仍独立校验 budget）|
| confidence | float 0-1 | AI 自评置信度 |
| reason_codes | list[str] | 可审计的决策原因标签 |

---

## 3. Prompt Contract

System prompt 核心约束（伪代码）：

```
你是 Floppy 音频检索规划器。

输入：用户睡前请求（中文）+ 用户画像 + 可用标签列表。
输出：严格 JSON，schema 如上。

规则：
1. preferred_tags 和 negative_tags 只能从 available_tags 选择，不得编造。
2. 不要生成音频文本/脚本内容，只做检索规划。
3. 不要绕过安全约束：{safety_constraints} 中的标签必须出现在 negative_tags。
4. 不要承诺入睡效果，confidence 如实反映不确定性。
5. 如果用户意图不明确，confidence 设为 <0.5 并在 reason_codes 加 "ambiguous_intent"。
6. duration_bucket 优先从用户输入提取，其次从画像 preferred_duration 推断。
7. generation_allowed_hint=false 当: 用户明确要已有内容、白噪音类型、或 budget 不足。
```

---

## 4. Confidence Strategy

| confidence | Action | Route |
|------------|--------|-------|
| ≥ 0.7 | 正常检索 | search → play_asset / generate_job |
| [0.5, 0.7) | 检索但标记 low_confidence，优先库命中，generation_allowed=false | search → play_asset / no_match |
| [0.3, 0.5) | 追问澄清（返回 clarification 选项给前端）| → clarification |
| < 0.3 | 走 fallback 规则映射 | → fallback_rule_match |

---

## 5. Fallback Boundary

Fallback（规则映射）**仅在以下情况启用**：

1. AI 调用失败（超时/5xx/rate limit）
2. AI 返回 confidence < 0.3
3. AI 输出 JSON 校验失败（tag 不在 available_tags）
4. 安全兜底：AI 未将 safety_constraints 放入 negative_tags → 系统强制注入

Fallback 执行当前 `profile_agent_schema_v0.md §1` 的 segment→tag 规则映射。

**标记要求：** response 中必须包含 `reason_codes: ["fallback:ai_unavailable"]` 或 `["fallback:low_confidence"]`，前端/日志可审计。

---

## 6. Acceptance Examples

### 6.1 焦虑助眠

```
Input:  request="今晚特别焦虑睡不着，想听点放松的"
        profile: segment=anxiety_relief, tonight_mood=anxious, stress=high

AI Output:
  intent: meditation
  preferred_tags: [breathing, grounding, slow_pace, rain, low_stimulation, warm_voice]
  negative_tags: [suspense, high_energy, sudden_sound, narrative_heavy]
  mood: [anxious, restless]
  duration_bucket: medium
  confidence: 0.92
  reason_codes: [mood_detected:anxious, stress:high, explicit:放松]
```

### 6.2 白噪音

```
Input:  request="下雨声"
        profile: segment=environmental_sleep

AI Output:
  intent: white_noise
  preferred_tags: [rain, ambient, nature, minimal_voice]
  negative_tags: [voice_heavy, narrative_heavy]
  mood: [calm]
  duration_bucket: long
  generation_allowed_hint: false
  confidence: 0.95
  reason_codes: [explicit:rain, type:white_noise, prefer_library]
```

### 6.3 故事陪伴

```
Input:  request="讲一个温暖的海边小镇故事，声音温柔一点"
        profile: segment=companionship, preferred_voices=[warm_female]

AI Output:
  intent: story
  preferred_tags: [warm_voice, narrative, gentle_story, sea, emotional_safe]
  negative_tags: [no_voice, abstract, high_density, mechanical]
  mood: [lonely, seeking_comfort]
  duration_bucket: long
  voice_style: warm_female
  background: ocean_soft
  confidence: 0.88
  reason_codes: [explicit:海边, explicit:温柔, profile:warm_female, segment:companionship]
```

### 6.4 快速入睡

```
Input:  request="今天太累了，最快的方式让我睡着"
        profile: segment=quick_sleep, avg_sleep_latency=12min

AI Output:
  intent: white_noise
  preferred_tags: [short_duration, fade_out, monotone, high_pause_density, minimal_words]
  negative_tags: [long_narrative, complex_story, energetic, high_info_density]
  mood: [exhausted]
  duration_bucket: short
  generation_allowed_hint: false
  confidence: 0.82
  reason_codes: [explicit:快, profile:quick_sleep, latency:12min]
```

### 6.5 播客消化

```
Input:  request="把今天的科技新闻整理成助眠版播客"
        profile: segment=content_transform, mood_tags=[curious]

AI Output:
  intent: podcast_digest
  preferred_tags: [structured, moderate_pace, informative, calm_narration, gradual_fade]
  negative_tags: [high_stimulation, suspense, abstract, mechanical]
  mood: [curious, winding_down]
  duration_bucket: medium
  generation_allowed_hint: true
  confidence: 0.78
  reason_codes: [explicit:科技新闻, explicit:助眠版, type:podcast_digest, segment:content_transform]
```

---

## 7. Integration Notes

- Backend 调用 LLM 时传入 `available_tags` = `SELECT DISTINCT tag FROM asset_tags`
- Response 校验：`preferred_tags ⊆ available_tags` AND `negative_tags ⊆ available_tags`，否则 strip 非法 tag 并 log
- Safety 强制注入：无论 AI 是否输出，`negative_tags` 始终合并 `safety_constraints`
- Budget 独立校验：`generation_allowed_hint` 是建议，backend 仍执行 `check_generation_budget()`
- Latency budget：AI planner 调用 ≤ 2s timeout，超时走 fallback
