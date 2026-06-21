# Profile → Agent Tag Retrieval v0

> 算法契约草案 | 2026-06-21

---

## 1. 用户分群 v0

| segment_id | 判定规则 | preferred_tags | negative_tags | 推荐内容类型 |
|---|---|---|---|---|
| anxiety_relief | stress=high OR anxiety=high OR tonight_mood∈{anxious,overthinking} | slow_pace, breathing, grounding, warm_voice, low_stimulation, nature | suspense, high_energy, sudden_sound, narrative_heavy | meditation, asmr, white_noise |
| companionship | preferred_types含story/asmr AND avg_completion>60% AND skip_rate<30% | warm_voice, narrative, gentle_story, soft_whisper, long_form, emotional_safe | no_voice, abstract, high_density, mechanical | story, asmr, podcast_digest |
| environmental_sleep | preferred_types含white_noise/music OR background_preferences≥2项 | rain, ocean, wind, nature, ambient, minimal_voice | voice_heavy, narrative_heavy, high_energy, sudden_sound | white_noise, meditation, asmr |
| quick_sleep | avg_sleep_latency≤15min OR preferred_duration≤10min OR avg_completion<40% | short_duration, high_pause_density, minimal_words, fade_out, monotone, repetitive | long_narrative, complex_story, high_info_density, energetic | white_noise, meditation, asmr |
| content_transform | preferred_types含podcast_digest OR mood_tags含{curious,learning} | structured, moderate_pace, informative, calm_narration, gradual_fade, digestible | high_stimulation, suspense, abstract, mechanical | podcast_digest, story, meditation |

兜底: `balanced_sleep` — 均衡探索，无硬 negative_tags。

---

## 2. ProfileContext 算法字段

```
ProfileContext:
  # 长期偏好 (从累积行为衰减计算)
  preferred_types_weighted: dict[AudioType, float]
  preferred_voices: list[str]          # top-3
  preferred_backgrounds: list[str]     # top-3
  preferred_duration_sec: int
  negative_tags: list[str]
  segment: str                         # 规则分群
  algo_segment: str                    # 算法侧分群(可覆盖规则)

  # 当晚状态 (tonight checkin / Agent 推断)
  tonight_mood: str | None
  tonight_stress: low/medium/high | None
  tonight_energy: low/medium/high | None

  # 行为画像 (事件流聚合)
  avg_completion_rate_7d: float
  skip_rate_7d: float
  consecutive_skip_count: int
  last_played_asset_ids: list[str]     # 最近3条，去重用
  morning_feedback_avg: float | None
```

---

## 3. StructuredQuery Schema

Agent 输出的检索结构：

```json
{
  "intent": "meditation",
  "required_tags": ["low_stimulation"],
  "preferred_tags": ["breathing", "rain", "warm_voice"],
  "negative_tags": ["suspense", "high_energy"],
  "duration_bucket": "medium",
  "voice_style": "warm_female",
  "background": "rain_soft",
  "mood": ["anxious", "calm"],
  "generation_allowed": true
}
```

| 字段 | 来源 | 说明 |
|------|------|------|
| intent | 用户当次输入 | Agent NLU 提取 |
| required_tags | 画像分群映射 | 必须匹配(AND) |
| preferred_tags | 画像分群 + 用户输入关键词 | 加分项 |
| negative_tags | 画像 negative_tags + 分群排除 | 排除项 |
| duration_bucket | 用户输入 > 画像 > 默认medium | short/medium/long |
| voice_style | 用户输入 > 画像 preferred_voices[0] | |
| background | 用户输入 > 画像 preferred_backgrounds[0] | |
| mood | 当晚状态 tonight_mood + 用户输入情绪词 | 用于生成参数 |
| generation_allowed | budget检查 + 无cache命中时 | 是否允许调TTS |

---

## 4. 画像更新信号

| 事件 | 影响字段 | 规则 |
|------|---------|------|
| questionnaire | 冷启动全量 | 直接覆写 segment/preferences |
| tonight_checkin | tonight_mood, tonight_stress, tonight_energy | 覆写当晚状态，session粒度 |
| play_started | play_count_7d, last_played_asset_ids | +1, FIFO保留最近3条 |
| play_completed | preferred_types_weighted(+0.1), preferred_voices(+0.05), avg_completion | 完播强化偏好 |
| skipped (<30s) | skip_rate_7d, consecutive_skip_count, preferred_types(-0.05) | 连续skip≥3触发分群重评估 |
| liked/favorited | preferred_types(+0.15), preferred_tags追加asset标签 | 强化信号 |
| disliked | negative_tags追加asset标签, preferred_types(-0.1) | 明确排斥 |
| next_day_feedback | morning_feedback_avg | 1-2分→分群重评估; 4-5分→强化当前偏好×1.2 |

衰减: `weight × 0.95^days_since_event`（半衰期≈14天）

---

## 5. 缓存命中阈值 v0

检索按优先级链判定 hit/miss：

| 层级 | 匹配方式 | 阈值 | 命中条件 |
|------|---------|------|---------|
| exact | prompt_hash 精确匹配 | — | cache_key完全一致 |
| tag | required_tags全命中 + ≥2个preferred_tags命中 | tag_score≥0.6 | 标签交集/并集比 |
| semantic | embedding cosine similarity | ≥0.58 | 向量相似度 |
| profile | segment匹配 + duration_bucket匹配 | — | 两项同时满足 |
| quality | quality_score | ≥0.7 | 最终过滤门槛 |

**判定逻辑：**
- exact命中 → 直接返回，skip生成
- tag+semantic+profile+quality 全通过 → asset_match，skip生成
- 任一层miss → generation_allowed=true时触发生成

---

## 6. 示例

### 6.1 焦虑用户请求雨声冥想

```
用户输入: "今晚很焦虑，想听雨声冥想放松"
画像: segment=anxiety_relief, tonight_mood=anxious

→ StructuredQuery:
  intent: meditation
  required_tags: [low_stimulation]
  preferred_tags: [rain, breathing, grounding, slow_pace]
  negative_tags: [suspense, high_energy, sudden_sound]
  duration_bucket: medium
  background: rain_soft
  generation_allowed: true
```

### 6.2 陪伴型用户请求睡前故事

```
用户输入: "讲一个海边书店的温暖故事"
画像: segment=companionship, preferred_voices=[warm_female]

→ StructuredQuery:
  intent: story
  required_tags: [emotional_safe]
  preferred_tags: [warm_voice, narrative, gentle_story, sea, bookstore]
  negative_tags: [no_voice, abstract, high_density]
  duration_bucket: long
  voice_style: warm_female
  generation_allowed: true
```

### 6.3 环境型用户请求白噪音

```
用户输入: "森林白噪音"
画像: segment=environmental_sleep, preferred_backgrounds=[forest_night, rain_soft]

→ StructuredQuery:
  intent: white_noise
  required_tags: [ambient]
  preferred_tags: [nature, forest, wind, minimal_voice]
  negative_tags: [voice_heavy, narrative_heavy]
  duration_bucket: long
  background: forest_night
  generation_allowed: false  # 白噪音优先库命中
```

---

## 7. Tag Matching Contract v0

### 7.1 Input Merge Rules

```
final_required_tags  = segment_required_tags
final_preferred_tags = segment_preferred_tags ∪ nlu_extracted_keywords(request_text) ∪ profile.preferred_tags_learned[:3]
final_negative_tags  = segment_negative_tags ∪ profile.negative_tags
final_mood           = tonight_mood ? [tonight_mood] : nlu_mood(request_text)
```

Dedup after merge. Max cardinality: required≤3, preferred≤8, negative≤6.

### 7.2 Scoring Formula

For each candidate asset, compute:

```
score = w_exact * exact_hit
      + w_tag   * tag_score
      + w_sem   * semantic_score
      + w_prof  * profile_score
      + w_qual  * quality_score
      - penalty_negative

Weights (sum=1.0):
  w_exact = 1.0 (short-circuit: if exact_hit → return immediately, score=1.0)
  w_tag   = 0.30  (tag_score = |matched_preferred| / |final_preferred_tags|, 0 if any required missing)
  w_sem   = 0.35  (cosine similarity of query embedding vs asset embedding)
  w_prof  = 0.15  (1.0 if segment∈asset.user_segment_tags AND duration_bucket matches, else 0.0)
  w_qual  = 0.20  (asset.quality_score, range 0-1)

penalty_negative = 0.5 per matched negative tag (hard filter: if any negative tag matched → asset excluded)
```

### 7.3 Negative Tags Handling

**Hard filter (exclude), not soft penalty.**

- If `asset.tags ∩ final_negative_tags ≠ ∅` → asset removed from candidate pool before scoring.
- Rationale: sleep safety — user explicitly rejected content must never surface.
- No threshold needed; any single negative tag match = exclude.

### 7.4 Hit/Miss Boundary

| Condition | Route |
|-----------|-------|
| exact_hit (cache_key match) | → `play_asset` |
| score ≥ 0.58 AND no required_tag missing | → `play_asset` (match_type=tag_hit or semantic_hit) |
| score ∈ [0.40, 0.58) AND generation_allowed=false | → `play_asset` (best-effort, log low_confidence) |
| score < 0.40 AND generation_allowed=true | → `generate_job` |
| score < 0.40 AND generation_allowed=false | → `no_match` |
| budget check fails | → `budget_exceeded` |

**Key threshold: 0.58 = confident hit, 0.40 = minimum acceptable.**

### 7.5 Acceptance Examples

**Example A: anxiety_relief user**

```
Input:  segment=anxiety_relief, tonight_mood=anxious, request="轻柔雨声冥想"
Query:  required=[low_stimulation], preferred=[rain, breathing, grounding, slow_pace, warm_voice], negative=[suspense, high_energy, sudden_sound]

✅ Hit asset:  tags=[low_stimulation, rain, breathing, ambient], quality=0.82 → tag_score=3/5=0.6, included
❌ Excluded:   tags=[suspense, narrative_heavy] → negative match → filtered out
```

**Example B: environmental_sleep user**

```
Input:  segment=environmental_sleep, request="下雨的声音"
Query:  required=[ambient], preferred=[rain, ocean, nature, minimal_voice], negative=[voice_heavy, narrative_heavy, high_energy, sudden_sound]

✅ Hit asset:  tags=[ambient, rain, nature], quality=0.78 → tag_score=3/4=0.75, included
❌ Excluded:   tags=[voice_heavy, narrative, story] → negative match → filtered out
```

**Example C: quick_sleep user**

```
Input:  segment=quick_sleep, preferred_duration=8min, request="快速入睡白噪音"
Query:  required=[short_duration], preferred=[high_pause_density, minimal_words, fade_out, monotone], negative=[long_narrative, complex_story, high_info_density, energetic]

✅ Hit asset:  tags=[short_duration, monotone, ambient], duration=8min, quality=0.75 → tag_score=2/4=0.5 + profile_score=1.0 (duration match) → total≥0.58
❌ Excluded:   tags=[long_narrative], duration=25min → negative match + duration mismatch → filtered out
```
