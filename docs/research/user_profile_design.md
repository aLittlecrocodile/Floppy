# Floppy 用户画像落地方案

> 版本: v1.0 | 日期: 2026-06-21 | 作者: algo agent

---

## 1. 用户画像分层方案

### 1.1 冷启动画像 (Cold-Start Profile)

来源: 首次注册问卷 + 设备时区

| 字段 | 类型 | 说明 |
|------|------|------|
| audio_type_preferences | list[AudioType] | 偏好音频类型（最多3项）|
| voice_preferences | list[str] | 偏好声线 |
| background_preferences | list[str] | 偏好背景音 |
| duration_preference_min | int | 期望时长(分钟) |
| stress_level | low/medium/high | 自述压力水平 |
| anxiety_level | low/medium/high | 自述焦虑水平 |
| avg_sleep_latency_min | int | 平均入睡时间(分钟) |
| timezone | str | 设备时区（推断夜间时段）|

### 1.2 长期偏好画像 (Long-Term Preference)

来源: 累积行为衰减加权

| 字段 | 类型 | 说明 |
|------|------|------|
| preferred_types_weighted | dict[AudioType, float] | 类型权重（播放+完播加权）|
| preferred_voices | list[str] | 高完播声线 top-3 |
| preferred_backgrounds | list[str] | 高完播背景 top-3 |
| preferred_duration_sec | int | 加权平均完播时长 |
| negative_tags | list[str] | 明确标记"不喜欢"的标签 |
| favorite_asset_ids | list[str] | 收藏列表 |
| segment | str | 长期分群标签（见§2）|
| algo_segment | str | 算法侧分群（可独立于规则分群）|
| profile_version | int | 画像版本号（每次更新+1）|

### 1.3 当晚状态画像 (Tonight State)

来源: 每晚 check-in 或 Agent 对话推断

| 字段 | 类型 | 说明 |
|------|------|------|
| tonight_mood | str | 当晚情绪标签(anxious/calm/tired/overthinking/...) |
| tonight_stress | low/medium/high | 当晚压力 |
| tonight_energy | low/medium/high | 当晚精力余量 |
| sleep_latency_hint_min | int | "今晚预计多久能睡着" |
| session_start_ts | datetime | 本次会话开始时间 |

### 1.4 行为画像 (Behavioral Signals)

来源: 事件流实时聚合

| 字段 | 类型 | 说明 |
|------|------|------|
| play_count_7d | int | 近7日播放次数 |
| avg_completion_rate_7d | float | 近7日平均完播率 |
| skip_rate_7d | float | 近7日跳过率（<30s停止）|
| last_played_asset_ids | list[str] | 最近3次播放资产ID |
| last_play_ts | datetime | 最近播放时间 |
| morning_feedback_avg | float | 次日反馈平均分(1-5) |
| consecutive_skip_count | int | 连续跳过计数（触发策略切换）|

---

## 2. 初版用户分群

### 分群定义与判定规则

| 分群 | segment 值 | 判定规则 | 推荐倾向 |
|------|-----------|---------|---------|
| 焦虑舒缓型 | anxiety_relief | stress=high OR anxiety=high OR tonight_mood∈{anxious,overthinking} | meditation优先，高pause密度，breathing引导，低语速声线 |
| 声音陪伴型 | companionship | preferred_types含story/asmr且完播率>70% | story/asmr，warm声线，长时长(20-30min)，轻叙事 |
| 环境助眠型 | environmental_sleep | preferred_types含white_noise/music且skip_rate低 | white_noise/music，无人声或极少人声，匹配背景偏好 |
| 快速入睡型 | quick_sleep | avg_sleep_latency≤15min OR avg_completion<40% | 短时长(5-10min)，高密度pause，快速进入安静段 |
| 内容转化型 | content_transform | preferred_types含podcast_digest | podcast_digest，信息密度适中，渐入催眠节奏 |
| 通用助眠型 | balanced_sleep | 不满足以上任何规则 | 均衡推荐，探索多类型 |

### 分群更新触发

```python
def reclassify(profile, behavior_signals) -> str:
    # 优先级: 当晚状态 > 行为信号 > 问卷
    if profile.tonight_stress == "high" or profile.tonight_mood in ("anxious", "overthinking"):
        return "anxiety_relief"
    if behavior_signals.consecutive_skip_count >= 3:
        return "balanced_sleep"  # 探索模式
    if behavior_signals.avg_completion_rate_7d > 0.7:
        # 高完播说明当前分群有效，保持
        return profile.segment
    # 否则根据长期偏好重算
    return classify_from_preferences(profile)
```

---

## 3. 画像更新策略

### 事件→画像权重映射

| 事件类型 | 影响字段 | 权重/衰减规则 |
|---------|---------|-------------|
| questionnaire_submitted | 冷启动全量覆写 | 直接覆盖 |
| audio_play_started | play_count, last_played | +1 计数 |
| audio_play_completed | preferred_types_weighted, preferred_voices, preferred_backgrounds, avg_completion | 完播: type权重+0.1, voice权重+0.05 |
| audio_play_stopped (pos<30s) | skip_rate, consecutive_skip_count | 跳过: type权重-0.05, 连续跳过+1 |
| audio_play_stopped (pos>60%) | 同completed但权重×0.7 | 视为部分完播 |
| asset_favorited | favorite_asset_ids, preferred_types | type权重+0.15 |
| asset_disliked | negative_tags | 提取asset标签加入negative_tags |
| morning_feedback (1-5) | morning_feedback_avg, segment | 1-2分: 触发分群重评估; 4-5分: 强化当前偏好 |
| tonight_checkin | tonight_* 字段 | 直接覆盖当晚状态 |

### 时间衰减

```
weight_effective = weight_raw × decay^(days_since_event)
decay = 0.95  # 半衰期 ≈ 14天
```

长期偏好每日凌晨批量重算（SQLite: 应用层; Postgres: 定时任务/触发器）。

---

## 4. 画像→音频标签映射

### Tag 分类

| 画像字段 | → required_tags | → preferred_tags | → negative_tags |
|---------|----------------|-----------------|----------------|
| segment=anxiety_relief | ["low_stimulation"] | ["breathing", "meditation", "slow_pace"] | ["high_energy", "suspense"] |
| segment=companionship | ["voice_present"] | ["warm_voice", "narrative", "story"] | ["no_voice"] |
| segment=environmental_sleep | ["ambient"] | ["nature", "rain", "wind"] | ["voice_heavy", "narrative"] |
| segment=quick_sleep | ["short_duration"] | ["high_pause_density", "minimal_words"] | ["long_narrative"] |
| tonight_mood=anxious | ["low_stimulation", "safe"] | ["breathing", "grounding"] | ["suspense", "horror"] |
| negative_tags (用户标记) | — | — | 直接映射 |

### 映射函数签名

```python
@dataclass
class TagQuery:
    required_tags: list[str]    # 必须匹配（AND）
    preferred_tags: list[str]   # 加分项（加权OR）
    negative_tags: list[str]    # 排除项（NOT）

def profile_to_tag_query(profile: UserProfile, tonight: TonightState | None) -> TagQuery:
    ...
```

---

## 5. Agent 输出 Schema 字段来源

| Agent输出字段 | 来源 | 说明 |
|-------------|------|------|
| intent (AudioType) | 用户当次输入 | Agent NLU 从 request_text 提取 |
| duration_sec | 用户输入 > 画像 preferred_duration > 默认15min | 优先级链 |
| voice_style | 用户输入 > 画像 preferred_voices[0] > segment默认 | |
| background | 用户输入 > 画像 preferred_backgrounds[0] > segment默认 | |
| mood | 当晚状态 tonight_mood > 用户输入情绪词 > 画像 mood_tags | 合并 |
| content_topic | 用户当次输入 | 完全来自用户描述 |
| language | 画像 > 设备区域 | 几乎不变 |
| required_tags | 画像分群映射(§4) | 用于资产库检索过滤 |
| preferred_tags | 画像分群+长期偏好映射 | 用于检索排序加分 |
| negative_tags | 画像 negative_tags + 分群排除 | 用于排除 |

---

## 6. 后端需要支持的数据模型/API/事件字段

### 6.1 数据模型增量

**user_profiles 表新增列:**

```sql
ALTER TABLE user_profiles ADD COLUMN tonight_energy TEXT;        -- low/medium/high
ALTER TABLE user_profiles ADD COLUMN preferred_types_weighted TEXT;  -- JSON dict
ALTER TABLE user_profiles ADD COLUMN preferred_voices_learned TEXT;  -- JSON list
ALTER TABLE user_profiles ADD COLUMN preferred_backgrounds_learned TEXT; -- JSON list
ALTER TABLE user_profiles ADD COLUMN preferred_duration_sec INTEGER;
ALTER TABLE user_profiles ADD COLUMN negative_tags TEXT;         -- JSON list
ALTER TABLE user_profiles ADD COLUMN timezone TEXT DEFAULT 'Asia/Shanghai';
ALTER TABLE user_profiles ADD COLUMN last_reclassify_at TEXT;
```

**新表: user_behavior_signals**

```sql
CREATE TABLE user_behavior_signals (
    user_id TEXT PRIMARY KEY,
    play_count_7d INTEGER DEFAULT 0,
    avg_completion_rate_7d REAL DEFAULT 0.0,
    skip_rate_7d REAL DEFAULT 0.0,
    last_played_asset_ids TEXT DEFAULT '[]',  -- JSON
    last_play_ts TEXT,
    morning_feedback_avg REAL,
    consecutive_skip_count INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);
```

### 6.2 API 增量

| 方法 | 路径 | 说明 |
|------|------|------|
| PUT | /users/{uid}/tonight-checkin | 当晚状态签到（已有，确认字段扩展）|
| GET | /users/{uid}/profile-context | 返回完整画像+行为信号+generation budget |
| POST | /users/{uid}/events | 新增事件类型: morning_feedback, asset_favorited, asset_disliked |
| GET | /internal/users/{uid}/tag-query | 算法内部: 画像→TagQuery 转换 |

### 6.3 事件类型扩展

现有 EventIn schema 已足够，需新增约定的 event_type 值:

| event_type | payload 字段 | 触发画像更新 |
|-----------|-------------|------------|
| audio_play_started | {source, position} | play_count +1 |
| audio_play_stopped | {position, duration_sec, completion_rate} | skip/completion判定 |
| audio_play_completed | {duration_sec} | 完播统计 |
| asset_favorited | {} | favorite_asset_ids 追加 |
| asset_disliked | {reason?} | negative_tags 追加 |
| morning_feedback | {score: 1-5, note?} | morning_feedback_avg |
| tonight_checkin | {mood, stress, energy} | tonight_* 覆写 |

---

## 7. MVP 阶段落地方案

### 7.1 SQLite 当前可做

1. **user_profiles 表扩列** — 上述 ALTER TABLE 直接执行
2. **user_behavior_signals 新表** — 纯 SQLite，应用层聚合
3. **画像更新逻辑在 Python 层** — Repository 新增:
   - `update_behavior_signals(user_id, event)` — 事件驱动增量更新
   - `reclassify_segment(user_id)` — 分群重算
   - `get_profile_context(user_id)` — 聚合返回
4. **TagQuery 在 RecommendationService 层生成** — 检索前调用 `profile_to_tag_query()`
5. **行为信号7日窗口** — 每次更新时检查时间窗口，过期数据归零（无需 cron）

### 7.2 Postgres/pgvector 演进路径

| 阶段 | 变更 |
|------|------|
| 迁移准备 | SQLAlchemy models 定义（当前 raw SQL → ORM）|
| Phase 1 | Postgres + pgvector 替代 embedding JSON列 |
| Phase 2 | 行为信号→ materialized view (7日滑窗聚合) |
| Phase 3 | 向量索引 IVFFlat/HNSW 替代全表扫描 |
| Phase 4 | 画像特征向量化 — 用户embedding(偏好+行为) 做 user-to-asset ANN |

---

## 8. 风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| **隐私** | 画像含健康相关数据(焦虑/压力/睡眠) | 1. 所有字段本地存储不上传第三方 2. 用户可随时清除画像 3. 不记录原始对话文本到画像 |
| **医疗边界** | 分群名含"焦虑"可能暗示诊断 | 1. 分群仅影响内容推荐，不输出给用户 2. UI 措辞避免医学术语 3. script_guard 已拦截医疗承诺 |
| **过拟合** | 完播加权导致推荐窄化 | 1. 推荐池保留20%探索位 2. consecutive_skip触发分群重评估 3. 新内容曝光保底 |
| **冷启动误判** | 问卷填写随意导致首次推荐差 | 1. 前3次播放加大探索权重 2. 快速跳过触发分群切换 3. 默认balanced_sleep兜底 |
| **睡眠场景安全** | 恐怖/惊吓/高刺激内容在夜间播放 | 1. script_guard 已实现 blocklist 拦截 2. 所有生成内容默认过 guard 3. negative_tags 阻止个人敏感内容 |
| **时间衰减失效** | SQLite无定时任务，衰减不实时 | MVP: 每次读取时惰性衰减; Postgres: pg_cron 定时重算 |

---

## 9. 需与 Backend 对齐的项

### 必须对齐

1. **user_profiles 表新增列的命名和类型** — 特别是 `preferred_types_weighted` (JSON dict) 和 `negative_tags` (JSON list)
2. **user_behavior_signals 表是否独立建表** vs 嵌入 user_profiles
3. **`/users/{uid}/tonight-checkin` 扩展字段**: 新增 `tonight_energy`
4. **事件 payload 契约**: `audio_play_stopped.completion_rate` 由前端算还是后端算
5. **`/internal/users/{uid}/tag-query` 路由**: 是否需要或直接在算法层内部调用
6. **画像重算时机**: 事件写入时同步更新 vs 异步队列

### 建议对齐

7. **morning_feedback 事件入口**: 是复用 `/users/{uid}/events` 还是独立端点
8. **profile_version 语义**: 当前自增，是否需要支持回滚
9. **行为信号聚合窗口**: 7天是否合适，是否需要可配置
