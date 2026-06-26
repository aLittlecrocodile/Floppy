# 算法侧 P0 设计契约 v1

> 2026-06-26 | Floppy 算法契约，供后端直接实现

---

## 1. 用户画像 v1 Schema

### 1.1 冷启动问卷字段

| 字段名 | 类型 | 枚举/约束 | 默认值 | 必填 | 说明 |
|--------|------|-----------|--------|------|------|
| `gender` | str | `male`, `female`, `other`, `prefer_not_to_say` | `prefer_not_to_say` | 否 | 不影响推荐权重，仅统计 |
| `age_group` | str | `18_24`, `25_34`, `35_44`, `45_54`, `55_plus` | `25_34` | 否 | 影响内容风格偏好 |
| `occupation` | str | `student`, `white_collar`, `blue_collar`, `freelancer`, `retired`, `other` | `other` | 否 | 影响压力类型推断 |
| `bedtime` | str | `before_22`, `22_23`, `23_00`, `00_01`, `after_01` | `23_00` | 否 | 影响推送时机 |
| `sleep_trouble` | str | `hard_to_fall_asleep`, `wake_up_often`, `anxiety_before_sleep`, `irregular_schedule`, `noise_sensitive`, `none` | `hard_to_fall_asleep` | 是 | 主分群信号 |
| `bedtime_habits` | list[str] | `phone`, `reading`, `music`, `meditation`, `podcast`, `nothing` | `[]` | 否 | max 3, 影响内容类型偏好 |
| `content_preferences` | list[str] | `white_noise`, `story`, `meditation`, `music`, `asmr`, `podcast_digest` | `[]` | 是 | 直接映射 `audio_type_preferences` |
| `companion_style` | str | `voice_companion`, `ambient_only`, `guided_relaxation`, `story_immersion` | `ambient_only` | 是 | 主分群信号 |
| `voice_preference` | str | `warm_female`, `gentle_female`, `warm_male`, `storyteller_female`, `storyteller_male`, `no_preference` | `no_preference` | 否 | 映射 `voice_preferences` |

### 1.2 问卷 → ProfileContext 转换规则

```python
def questionnaire_to_profile(q: Questionnaire) -> UserProfileIn:
    # content_preferences → audio_type_preferences (直接映射)
    audio_type_preferences = q.content_preferences

    # companion_style → segment 初始分群
    COMPANION_TO_SEGMENT = {
        "voice_companion": "companionship",
        "ambient_only": "environmental_sleep",
        "guided_relaxation": "anxiety_relief",
        "story_immersion": "companionship",
    }
    segment = COMPANION_TO_SEGMENT[q.companion_style]

    # sleep_trouble 叠加修正
    if q.sleep_trouble == "anxiety_before_sleep":
        segment = "anxiety_relief"
        stress_level = "high"
    elif q.sleep_trouble == "hard_to_fall_asleep":
        stress_level = "medium"
    else:
        stress_level = "low"

    # voice_preference → voice_preferences
    voice_preferences = [] if q.voice_preference == "no_preference" else [q.voice_preference]

    # bedtime_habits → background_preferences 推断
    HABIT_TO_BG = {"music": "piano_soft", "meditation": "rain_soft", "reading": "forest_night"}
    background_preferences = [HABIT_TO_BG[h] for h in q.bedtime_habits if h in HABIT_TO_BG][:3]

    return UserProfileIn(
        audio_type_preferences=audio_type_preferences,
        voice_preferences=voice_preferences,
        background_preferences=background_preferences,
        duration_preference_min=15,
        stress_level=stress_level,
        anxiety_level="high" if q.sleep_trouble == "anxiety_before_sleep" else "medium",
        avg_sleep_latency_min=25,  # 默认，后续行为更新
        mood_tags=["calm"],  # 冷启动默认
    )
```

### 1.3 后端落地要求

- `user_profiles` 表新增列: `gender`, `age_group`, `occupation`, `bedtime`, `sleep_trouble`, `bedtime_habits`(JSON), `companion_style`, `voice_preference_raw`
- 新增接口: `PUT /users/{user_id}/questionnaire` 接收问卷原始数据 + 调用转换逻辑写入 profile
- 转换逻辑在后端执行，非 Agent 侧

---

## 2. 画像更新与记忆策略

### 2.1 事件 Payload Schema

| event_type | payload 必填字段 | payload 类型 |
|---|---|---|
| `play_started` | `asset_id`, `asset_type`, `source` | `{asset_id: str, asset_type: AudioType, source: "recommendation"\|"search"\|"history"\|"remix", voice_id: str\|null}` |
| `play_completed` | `asset_id`, `play_duration_sec`, `completion_rate` | `{asset_id: str, play_duration_sec: int, completion_rate: float[0-1], asset_type: AudioType}` |
| `audio_skipped` | `asset_id`, `skip_at_sec` | `{asset_id: str, skip_at_sec: int, asset_type: AudioType, reason: str\|null}` |
| `asset_disliked` | `asset_id` | `{asset_id: str, asset_type: AudioType, asset_tags: list[str]}` |
| `asset_favorited` | `asset_id` | `{asset_id: str, asset_type: AudioType, asset_tags: list[str]}` |
| `listen_1min_rating` | `asset_id`, `rating` | `{asset_id: str, rating: int[1-5], asset_type: AudioType}` |
| `morning_feedback` | `rating`, `slept_well` | `{rating: int[1-5], slept_well: bool, sleep_duration_hours: float\|null, asset_id: str\|null}` |
| `conversation_signal` | `signal_type`, `value` | `{signal_type: "mood"\|"stress"\|"preference", value: str, confidence: float[0-1]}` |
| `questionnaire_updated` | `fields_changed` | `{fields_changed: list[str], trigger: "onboarding"\|"settings"\|"periodic"}` |

### 2.2 权重更新规则

| 事件 | 影响字段 | 变化量 | 条件 |
|------|---------|--------|------|
| `play_completed` (completion≥0.7) | `preferred_types_weighted[type]` | +0.10 | — |
| `play_completed` (completion≥0.7) | `preferred_voices` | +0.05 boost | 有 voice_id 时 |
| `play_completed` (completion<0.3) | `preferred_types_weighted[type]` | -0.03 | — |
| `audio_skipped` (skip_at<30s) | `preferred_types_weighted[type]` | -0.05 | — |
| `audio_skipped` (skip_at<30s) | `consecutive_skip_count` | +1 | — |
| `asset_favorited` | `preferred_types_weighted[type]` | +0.15 | — |
| `asset_favorited` | 资产 tags → `preferred_tags` | 追加 top-3 tags | — |
| `asset_disliked` | `preferred_types_weighted[type]` | -0.10 | — |
| `asset_disliked` | 资产 tags → `negative_tags` | 追加 all tags | — |
| `listen_1min_rating` ≥4 | `preferred_types_weighted[type]` | +0.08 | — |
| `listen_1min_rating` ≤2 | `preferred_types_weighted[type]` | -0.05 | — |
| `morning_feedback` rating≥4 | 前一晚全部偏好 | ×1.2 强化 | — |
| `morning_feedback` rating≤2 | 前一晚全部偏好 | ×0.8 衰减 | 触发重新分群 |
| `conversation_signal` mood | `tonight_mood` | 覆写 | confidence≥0.6 |
| `conversation_signal` stress | `tonight_stress` | 覆写 | confidence≥0.6 |

### 2.3 衰减策略

```
weight_effective = weight_raw × 0.95^(days_since_event)
```

- 半衰期 ≈ 14 天
- 权重 floor: 0.0（不会负数，negative 信号通过 `negative_tags` 表达）
- 权重 ceiling: 1.0
- 衰减计算时机: 每次 `GET /profile/context` 请求时实时计算（基于 events 表最近 30 天事件）

### 2.4 重新分群触发条件

以下任一满足时，后端 worker 触发 `algo_segment` 重新计算:

| 触发条件 | 说明 |
|---------|------|
| `consecutive_skip_count >= 3` | 连续跳过说明当前分群不准 |
| `morning_feedback` rating ≤ 2 连续 2 天 | 睡眠质量差，策略需调整 |
| `questionnaire_updated` 且 `sleep_trouble` 或 `companion_style` 变化 | 核心偏好主动变更 |
| 累计 `dislike` ≥ 5 次/7天 | 高频负反馈 |
| 7 天无任何播放事件 | 用户回流，画像可能过期 |

重新分群逻辑: 基于最近 14 天事件流重新执行分群规则（复用 `profile_agent_schema_v0.md` §1 判定规则），写入 `algo_segment`。

---

## 3. 推荐/生成/Remix 决策策略

### 3.1 Agent Decision Schema

```json
{
  "decision": "play_asset" | "generate_job" | "remix_current" | "generate_then_remix" | "ask_clarify" | "refuse",
  "confidence": 0.0-1.0,
  "reasoning": "string",
  "structured_query": { /* StructuredQuery */ },
  "remix_request": { /* 仅 remix_current / generate_then_remix 时 */ } | null,
  "fallback_asset_ids": ["asset_id_1"],
  "generation_params": { /* 仅 generate_job / generate_then_remix 时 */ } | null
}
```

### 3.2 决策阈值与路由

```
用户请求 → normalize_request → 判断 intent 类型
                                      ↓
              ┌──────────────────────────────────────────────┐
              │ intent = content_request (新内容请求)         │
              │   → search_audio_assets                      │
              │     best_score ≥ 0.58 → play_asset           │
              │     best_score < 0.58 + budget ok → generate_job │
              │     budget exhausted → refuse + 推荐已有      │
              │                                              │
              │ intent = remix_edit (编辑型，见 §3.3)         │
              │   → remix 决策流程                            │
              │                                              │
              │ intent = unclear → ask_clarify               │
              │ intent = unsafe  → refuse                    │
              └──────────────────────────────────────────────┘
```

### 3.3 Remix 定义与触发条件

**Remix = 用户在对话中对当前播放/待生成内容提出的编辑型需求。** Agent 在当前 voice 内容上叠加/替换/移除背景音层，并继续播放或生成。Remix 不是推荐兜底策略。

**触发 intent（NLU 识别）：**

| remix_intent | 用户话术示例 | 说明 |
|---|---|---|
| `add_background` | "加一点雨声背景"、"能配上海浪声吗" | 在当前 voice 上叠加 ambient |
| `change_background` | "把雨声换成篝火声" | 替换背景音层 |
| `adjust_volume` | "背景音小一点"、"把白噪音调大" | 调整 mix level |
| `remove_background` | "去掉背景音"、"只要人声" | 移除 ambient 层 |
| `voice_plus_ambient` | "讲故事的时候配着白噪音" | 初始请求即包含 remix 意图 |

**前置条件：**
- 必须存在"当前内容上下文"：正在播放的 asset、或刚生成/即将生成的 voice content
- 无当前上下文时，Agent 应 `ask_clarify`（"你想给什么内容加背景音？"）

### 3.4 Remix Request Schema

```json
{
  "remix_intent": "add_background" | "change_background" | "adjust_volume" | "remove_background" | "voice_plus_ambient",
  "foreground": {
    "source": "current_playing" | "pending_generation" | "asset_id",
    "asset_id": "aud_story_01" | null,
    "generation_job_id": "job_xxx" | null
  },
  "background": {
    "sound_type": "rain" | "ocean" | "fire" | "forest" | "stream" | "fan" | "piano" | "wind",
    "asset_id": "aud_rain_01" | null,
    "source": "catalog_match" | "generate"
  },
  "mix_params": {
    "background_volume": 0.25,
    "crossfade_in_sec": 2,
    "crossfade_out_sec": 3,
    "duck_on_speech": true
  }
}
```

字段说明：
- `foreground.source`: Agent 判断当前 voice 内容来源 — 正在播放(`current_playing`)、待生成(`pending_generation`)、或指定资产(`asset_id`)
- `background.sound_type`: 从用户话术 NLU 提取的目标背景音类型
- `background.source`: `catalog_match` = 从已有 ambient 库匹配；`generate` = 需要先生成 ambient（当前不支持，预留）
- `mix_params.duck_on_speech`: 人声时自动降低背景音量（默认 true）

### 3.5 Remix 决策路由

```
用户 remix 编辑请求
  ↓
识别 remix_intent + 提取 background sound_type
  ↓
检查当前播放/生成上下文
  ├── 无上下文 → ask_clarify
  ├── 有 current_playing asset
  │     ├── catalog 有匹配 ambient → remix_current
  │     └── catalog 无匹配 → ask_clarify（"暂不支持该背景音"）
  └── 用户同时请求新 voice + background（voice_plus_ambient）
        ├── voice 库命中 → remix_current（foreground=asset_id）
        └── voice 库未命中 + budget ok → generate_then_remix
```

### 3.6 配额消耗规则

| 决策 | TTS 生成配额 | Remix job 资源 | 说明 |
|------|-------------|---------------|------|
| `remix_current` | ❌ 不消耗 | ✅ 消耗 | 两个已有 asset 混合，仅消耗混音计算资源 |
| `generate_then_remix` | ✅ 消耗（voice 部分）| ✅ 消耗 | 先 TTS 生成 voice asset，再混合 |
| `adjust_volume` / `remove_background` | ❌ 不消耗 | ❌ 不消耗 | 纯客户端/播放器参数调整 |

后端约束：
- `remix_current` 不检查 `generation_budget`，但限制每用户每小时 remix 次数上限（建议 20 次）
- `generate_then_remix` 先走 `create_generation_job` 正常配额检查，生成完成后自动触发 remix

### 3.7 Clarify 触发条件

Agent 追问而非猜测:

| 条件 | 示例 |
|------|------|
| intent 无法确定（NLU confidence < 0.5）| "来点什么" → 追问偏好 |
| 用户请求矛盾（如 "安静的播客"）| 追问优先级 |
| 当晚状态未知 + 首次使用 | 追问今晚感受 |
| remix 无当前播放上下文 | "加雨声" 但没有正在播放的内容 |
| remix background 不明确 | "加点背景" 但未指定类型 |

### 3.8 Refuse 触发条件

| 条件 | Agent 行为 |
|------|-----------|
| 请求触及安全禁区（§4 列表）| 拒绝 + 解释 + 推荐安全替代 |
| 请求完全超出产品范围 | 引导回睡眠场景 |
| generation_budget 耗尽 + 无候选 | 告知额度情况 + 推荐已有内容 |

### 3.9 后端需实现的接口

| 接口 | 方法 | 用途 | 优先级 |
|------|------|------|--------|
| `POST /remix/sessions` | POST | 创建 remix 会话：接收 RemixRequest，匹配 background asset，返回混合播放 URL | P1 |
| `PATCH /remix/sessions/{id}` | PATCH | 调整进行中 remix（change_background, adjust_volume, remove_background）| P1 |
| `GET /remix/sessions/{id}` | GET | 查询 remix 会话状态 | P1 |
| `GET /assets/{id}/remixable` | GET | 检查资产是否可用于 remix（有 object_key，非 placeholder，类型兼容）| P1 |
| `POST /remix/sessions/{id}/switch-background` | POST | 热切换背景音（不中断 foreground 播放）| P2 |

---

## 4. 长内容生成与安全策略

### 4.1 章节结构 (15-20 分钟睡前故事)

```
[引入段] 1-2 分钟 / 200-300 字
  - 场景建立，感官描写为主
  - 语速缓慢，多停顿
  - 目的: 将听者从清醒世界过渡到故事世界

[发展段] 5-7 分钟 / 800-1100 字
  - 轻情节推进，无冲突无悬念
  - 重复性感官描写（波浪、风声、脚步）
  - 长句为主，节奏逐渐放慢

[舒缓段] 5-7 分钟 / 700-1000 字
  - 情节几乎静止，纯环境描写
  - 语速明显降低
  - 停顿密度提高 (每 50-80 字一个 2-4 秒停顿)

[收尾段] 2-3 分钟 / 200-400 字
  - 轻声总结，暗示睡眠
  - 最高停顿密度 (每 30-50 字一个 3-6 秒停顿)
  - 最后 30 秒可以是纯静音 fade-out
```

### 4.2 Prompt 模板

```
你是一位温柔的睡前故事讲述者。请为一位{tonight_mood_desc}的听众创作一个{duration_min}分钟的睡前故事。

## 要求
- 主题: {content_topic}
- 风格: 温暖、安全、没有冲突和悬念
- 结构: 引入(1-2min) → 发展(5-7min) → 舒缓(5-7min) → 收尾(2-3min)
- 目标字数: {target_words} 字（含停顿标记）
- 停顿标记: 使用 <#2#> 表示2秒停顿，<#4#> 表示4秒停顿，<#6#> 表示6秒停顿
- 停顿密度: 前半段每100字1-2个停顿，后半段每50字1-2个停顿
- 语言: 简单句为主，避免从句嵌套
- 感官: 多用触觉、听觉、嗅觉描写，少用视觉刺激

## 禁止内容
- 任何形式的冲突、追逐、危险场景
- 死亡、疾病、分离等负面情节
- 需要思考或记忆的信息密集内容
- 惊吓、反转、悬念
- 时事、争议话题
- 财经、政治内容

## 输出格式
直接输出故事正文，用停顿标记分隔。每段之间空一行。
```

### 4.3 目标参数

| 参数 | 15 分钟 | 20 分钟 | 说明 |
|------|---------|---------|------|
| 目标字数 | 2000-2500 | 2800-3500 | 含停顿标记 |
| 停顿占时比 | 25-35% | 30-40% | 后半段更高 |
| 平均语速 | 150-180 字/分钟 | 140-170 字/分钟 | MiniMax TTS 实际输出 |
| 停顿标记数 | 40-60 个 | 55-80 个 | — |
| 最大单段无停顿字数 | 120 字 | 100 字 | 超过需插入停顿 |

### 4.4 安全禁区 (Content Safety Guard)

**硬禁止（生成时 prompt 禁止 + 生成后正则/关键词过滤）：**

| 类别 | 关键词/模式示例 | 处理 |
|------|---------------|------|
| 财经投资 | 股票、基金、涨跌、理财、比特币 | 拒绝生成，推荐白噪音 |
| 血腥暴力 | 血、杀、伤、打斗、武器 | 拒绝生成 |
| 恐怖惊悚 | 鬼、灵异、恐怖、诅咒、黑暗仪式 | 拒绝生成 |
| 争议政治 | 政治人物、政策争议、国际冲突 | 拒绝生成 |
| 强刺激新闻 | 灾难、事故、犯罪、疫情 | 拒绝生成 |
| 性暗示 | 色情、性、裸露相关 | 拒绝生成 |
| 宗教敏感 | 特定宗教贬低、邪教 | 拒绝生成 |
| 药物酒精 | 毒品、酗酒、药物滥用 | 拒绝生成 |

**软限制（生成可以包含但需降权/警告）：**

| 类别 | 说明 | 处理 |
|------|------|------|
| 轻度悲伤情节 | 离别、思念（不涉及死亡） | 允许但 quality_score -0.1 |
| 信息密集内容 | podcast_digest 中数据过多 | 警告，建议拆分 |
| 快节奏叙事 | 情节推进过快 | 要求 script_expander 拉长停顿 |

### 4.5 Safety Guard 实现规则

```python
HARD_BLOCK_PATTERNS = [
    r"(股票|基金|涨停|跌停|理财|比特币|炒股)",
    r"(杀[了死害]|血[腥淋]|暴力|武器|枪|刀[刺砍])",
    r"(鬼[怪魂]|灵异|恐怖|诅咒|闹鬼)",
    r"(政[治府]|选举|党[派]|外交争议)",
    r"(地震[死伤]|车祸|犯罪|恐袭|疫[情]死)",
    r"(色情|性[爱交]|裸[体露])",
    r"(邪教|极端宗教)",
    r"(毒品|吸毒|酗酒)",
]

def safety_check(script_text: str) -> tuple[bool, str]:
    """Returns (is_safe, reason). 后端在 script 生成后、TTS 调用前执行。"""
    for pattern in HARD_BLOCK_PATTERNS:
        if re.search(pattern, script_text):
            return False, f"触及安全禁区: {pattern}"
    return True, "pass"
```

- Guard 执行位置: `SleepScriptService` 生成脚本后，`GenerationService` 调用 TTS 前
- 未通过时: 返回 `safety_status: "blocked"`，不调用 TTS，不扣配额
- 日志记录: 记录被拦截的 `request_text` 和匹配 pattern，用于后续优化

---

## 5. 后端落地摘要

### 5.1 新增字段

| 表 | 新增列 | 类型 | 默认值 |
|----|--------|------|--------|
| `user_profiles` | `gender` | TEXT | `prefer_not_to_say` |
| `user_profiles` | `age_group` | TEXT | `25_34` |
| `user_profiles` | `occupation` | TEXT | `other` |
| `user_profiles` | `bedtime` | TEXT | `23_00` |
| `user_profiles` | `sleep_trouble` | TEXT | `hard_to_fall_asleep` |
| `user_profiles` | `bedtime_habits` | TEXT(JSON) | `[]` |
| `user_profiles` | `companion_style` | TEXT | `ambient_only` |
| `user_profiles` | `voice_preference_raw` | TEXT | `no_preference` |
| `user_profiles` | `preferred_types_weighted` | TEXT(JSON) | `{}` |
| `user_profiles` | `negative_tags` | TEXT(JSON) | `[]` |
| `user_profiles` | `preferred_tags_learned` | TEXT(JSON) | `[]` |
| `user_profiles` | `consecutive_skip_count` | INTEGER | `0` |
| `user_profiles` | `last_played_asset_ids` | TEXT(JSON) | `[]` |
| `user_profiles` | `morning_feedback_avg` | REAL | `null` |

### 5.2 新增/修改接口

| 接口 | 方法 | 说明 | 优先级 |
|------|------|------|--------|
| `/users/{id}/questionnaire` | PUT | 问卷提交 + 画像初始化 | P0 |
| `/users/{id}/profile/context` | GET | 含衰减计算的 ProfileContext | P0 |
| `/users/{id}/profile/checkin` | POST | tonight 状态更新 | P0 (已定义) |
| `/assets/remix` | — | — | 已删除，由 `/remix/sessions` 替代 |
| `/remix/sessions` | POST | 创建 remix 会话（叠加/替换背景音）| P1 |
| `/remix/sessions/{id}` | PATCH | 调整 remix（volume/switch/remove）| P1 |
| `/assets/{id}/remixable` | GET | Remix 可用性检查 | P1 |
| `/admin/resegment` | POST | 手动触发重新分群 | P2 |

### 5.3 事件处理 Worker

后端需实现异步 worker（可先同步 in-process），消费 events 表，执行:
1. 权重更新（§2.2 规则）
2. 重新分群判定（§2.4 条件）
3. negative_tags / preferred_tags_learned 维护

---

## 6. 核心决策与风险

### 核心决策

1. **衰减半衰期 14 天** — 平衡新偏好响应速度与稳定性，可后续 A/B 调整
2. **Remix 是对话编辑行为，非推荐兜底** — 用户主动请求叠加/替换背景音，remix_current 不消耗 TTS 配额，generate_then_remix 消耗
3. **Safety guard 后端强制** — 不信任 Agent prompt 约束，正则硬拦截
4. **问卷转换后端执行** — 逻辑固定、可审计，不走 Agent

### 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 正则安全过滤误杀率 | 合理内容被拦截 | 建立白名单 + 人工审核队列 |
| 衰减实时计算性能 | ProfileContext 接口延迟 | 事件量小（单用户/天<50），SQLite 可接受；量大后预计算 |
| Remix 播放上下文丢失 | 用户说"加雨声"但 session 无当前播放记录 | 后端维护 active_playback_session，Agent 读取后决策 |
| Remix 音频时长不匹配 | background 短于 foreground | 后端 loop background 至 foreground 结束 |
| 连续 skip 误触发重分群 | 用户随意浏览被误判 | skip_at<30s 才计入，30s 以上视为正常试听 |
