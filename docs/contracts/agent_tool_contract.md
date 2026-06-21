# Agent Context / Tool Contract

Floppy 本质是一个 Agent 项目。后端是 Agent 的执行层：用户画像是 Agent 的决策上下文，后端工具是 Agent 可调用的能力边界。

本文档定义最小可落地版本的 Agent 与后端的接口契约。算法侧负责画像字段口径，后端负责数据模型和 API 边界；字段冲突时以**后端 contract 为准**（见第 6 节）。

---

## 1. ProfileContext — Agent 画像上下文 DTO

每次 Agent 处理请求前，后端向其提供一个 `ProfileContext`。Agent **不得直接读取 `user_profiles` 表**，必须通过此结构获取决策信息。

```json
{
  "user_id": "u_demo",
  "segment": "anxiety_relief",
  "algo_segment": "anxiety_relief_v2",
  "audio_type_preferences": ["story", "white_noise"],
  "voice_preferences": ["warm_female"],
  "background_preferences": ["rain_soft"],
  "duration_preference_min": 15,
  "stress_level": "high",
  "anxiety_level": "medium",
  "avg_sleep_latency_min": 35,
  "mood_tags": ["anxiety_relief"],
  "tonight_mood": "tired",
  "tonight_stress": "medium",
  "profile_version": 3,
  "generation_budget": {
    "daily_remaining_chars": 50000,
    "daily_generate_count_remaining": 5
  }
}
```

字段说明：

| 字段 | 来源 | 实时/离线 | Agent 必读 |
|---|---|---|---|
| `segment` | 规则计算（冷启动兜底） | 同步 | 是 |
| `algo_segment` | 算法 worker 写入 | 离线 | 是（优先，fallback 到 segment）|
| `audio_type_preferences` | 冷启动问卷 | 同步 | 是 |
| `mood_tags` | 冷启动问卷 | 同步 | 是 |
| `tonight_mood` | checkin 接口 | 同步 | 是（缺省 null，不影响检索）|
| `tonight_stress` | checkin 接口 | 同步 | 是（缺省 null）|
| `profile_version` | 自增 | 同步 | 用于缓存失效判断 |
| `generation_budget` | 配置 + 事件统计 | 实时计算 | 是（生成前必读）|

后端提供接口：

```
GET /users/{user_id}/profile/context
```

返回上述 `ProfileContext` JSON，响应时间要求 < 50 ms（SQLite 单查询，无需复杂聚合）。

`generation_budget` 当前实现为：读取过去 24h 内 `generation_jobs` 成功记录，计算 `usage_characters` 累计值，与 `config.FLOPPY_DAILY_CHAR_BUDGET`（默认 `200000`）对比。**这是后端强制执行，不依赖 Agent 自觉遵守。**

---

## 2. Agent 可调用后端工具（Tool Definitions）

Agent 通过 HTTP 调用后端工具。每个工具对应一个具体接口。以下是最小工具集。

### 工具 1：`normalize_request`

**作用**：将用户自然语言归一化为结构化标签，供检索和生成使用。

```
POST /normalize
```

入参：
```json
{
  "request_text": "我想听一个温柔女声讲海边书店的睡前故事，15分钟",
  "user_id": "u_demo"
}
```

出参：
```json
{
  "intent": "story",
  "duration_sec": 900,
  "duration_bucket": "long",
  "voice_style": "warm_female",
  "background": "rain_soft",
  "mood": ["calm", "gentle"],
  "content_topic": ["海边", "书店"],
  "cache_key": "sha256..."
}
```

当前 `RequestNormalizer` 已实现此能力，只需暴露为独立接口。Agent 拿到 `cache_key` 和 `intent` 后，再决定是检索还是生成。

### 工具 2：`search_audio_assets`

**作用**：用标签、画像、embedding 检索候选音频资产，返回排序结果和匹配分数。

```
POST /assets/search
```

入参：
```json
{
  "user_id": "u_demo",
  "query": "温柔女声睡前故事雨声",
  "cache_key": "sha256...",
  "filters": {
    "type": "story",
    "mood_tags": ["calm"],
    "min_duration_sec": 600,
    "max_duration_sec": 1200
  },
  "limit": 5
}
```

出参：
```json
{
  "results": [
    {
      "asset_id": "aud_abc",
      "title": "...",
      "score": 0.83,
      "match_type": "exact",
      "reasons": ["精确缓存命中"],
      "playback_url": "http://..."
    }
  ],
  "hit": true,
  "best_score": 0.83,
  "threshold": 0.58
}
```

- `cache_key` 命中 `prompt_hash` → `match_type: exact`，`hit: true`
- 向量+画像评分 >= 阈值 → `match_type: asset_match`，`hit: true`
- 均未达到 → `hit: false`，`results` 为空或包含低分候选（Agent 可用于展示"相关推荐"）

**Agent 必须以 `hit` 字段决定是否进入生成流程，不得自行判断 `score`。**

### 工具 3：`create_generation_job`

**作用**：当 `search_audio_assets` 返回 `hit: false` 时，Agent 提交生成任务。

```
POST /users/{user_id}/generation-jobs
```

入参（现有接口，无需改动）：
```json
{
  "request_text": "...",
  "force_generate": false
}
```

出参（现有 `GenerationJobCreateResponse`）：
```json
{
  "job_id": "job_xxx",
  "status": "queued",
  "cache_hit": false,
  "match_type": "queued",
  "asset": null,
  "normalized_request": {...}
}
```

**前置约束（后端强制）**：
- `generation_budget.daily_remaining_chars <= 0` → 拒绝，返回 429
- `force_generate: false` 时，后端仍然执行内部检索（防止 Agent 遗漏缓存命中）
- Agent 传入 `force_generate: true` 仅在用户明确要求"重新生成"时允许

### 工具 4：`get_job_status`

**作用**：查询生成任务状态，判断是否可播放。

```
GET /generation-jobs/{job_id}
```

出参（现有 `GenerationJob`），关键字段：

```json
{
  "status": "succeeded",
  "asset": { "playback_url": "..." },
  "latency_ms": 3200,
  "usage_characters": 661,
  "estimated_cost_usd": 0.0661
}
```

Agent 在 status 为 `queued`/`generating` 时应轮询（建议间隔 2-3s），超时后向用户反馈生成耗时。

### 工具 5：`record_event`

**作用**：Agent 在播放开始、结束、跳出、反馈等节点上报事件，驱动画像更新。

```
POST /users/{user_id}/events
```

入参（现有接口，增加字段规范）：
```json
{
  "event_type": "audio_play_completed",
  "asset_id": "aud_abc",
  "payload": {
    "play_duration_sec": 780,
    "completion_rate": 0.87,
    "source": "agent_recommendation"
  }
}
```

Agent **必须**在以下节点调用 `record_event`：
- 检索命中并返回播放 → `recommendation_served`（含 `match_type`、`score`）
- 用户开始播放 → `audio_play_started`
- 用户中途退出 → `audio_skipped`（含 `skip_at_sec`）
- 用户播放完成 → `audio_play_completed`（含 `completion_rate`）
- 用户点赞/不喜欢 → `audio_liked` / `audio_disliked`

这些事件是画像离线更新的数据来源。**Agent 不调用事件 → 画像无法更新。**

### 工具 6：`update_profile_signal`

**作用**：Agent 在会话中捕获到用户当晚状态信息时，立即更新 checkin 字段。不更新长期偏好（长期偏好走 `PUT /users/{id}/profile`）。

```
POST /users/{user_id}/profile/checkin
```

入参：
```json
{
  "tonight_mood": "tired",
  "tonight_stress": "medium",
  "sleep_latency_hint_min": 40
}
```

所有字段可选，部分更新。出参返回更新后的 `ProfileContext`。

**使用时机**：Agent 从用户自然语言中识别到情绪/压力信号（如"我今天很焦虑"），应先调用此工具更新画像，再调用 `search_audio_assets`，使检索评分融入当晚状态。

---

## 3. 入参/出参关键约束

| 工具 | 必填入参 | 关键出参 | 失败时 Agent 行为 |
|---|---|---|---|
| `normalize_request` | `request_text` | `cache_key`, `intent` | 返回错误，不进行后续调用 |
| `search_audio_assets` | `user_id`, `query` 或 `cache_key` | `hit`, `best_score` | 按 `hit: false` 处理 |
| `create_generation_job` | `user_id`, `request_text` | `job_id`, `status` | 展示生成失败，不静默跳过 |
| `get_job_status` | `job_id` | `status`, `asset.playback_url` | 超时后告知用户 |
| `record_event` | `user_id`, `event_type`, `asset_id` | `event_id` | 记录失败不阻断播放，但需重试 |
| `update_profile_signal` | `user_id`, 至少一个信号字段 | 更新后 `ProfileContext` | 降级为不更新，继续检索 |

---

## 4. Agent 检索 vs 生成的决策规则

```
用户请求
  ↓
normalize_request → 得到 cache_key + tags
  ↓
（可选）识别到当晚状态信号 → update_profile_signal
  ↓
search_audio_assets
  ├── hit: true  → record_event(recommendation_served) → 返回播放 URL
  └── hit: false
        ↓
       检查 generation_budget.daily_remaining_chars
        ├── <= 0         → 返回"今日生成额度已用完，推荐相似内容" + 低分候选
        ├── > 0          → create_generation_job
        │                  → 轮询 get_job_status
        │                  → succeeded → record_event(recommendation_served) → 返回
        └── 用户取消/超时 → 告知用户，提供低分候选兜底
```

**Agent 不得跳过 `search_audio_assets` 直接调用 `create_generation_job`**（除非 `force_generate=true` 且用户明确触发"重新生成"）。

---

## 5. 安全与成本限制：后端强制，不依赖 Agent

Agent 是不可信调用方。以下限制在后端强制执行，不靠 Agent 自觉遵守：

| 限制 | 后端实现位置 | 当前状态 |
|---|---|---|
| 每日字符额度 | `create_generation_job` 检查 daily usage | 待实现（P0） |
| 每日生成次数上限 | 同上 | 待实现（P0） |
| `force_generate: true` 频率限制 | `create_generation_job` 检查 | 待实现（P1） |
| 内容安全检查 | `SleepScriptService` 生成脚本后 guard | 当前为 approved 占位，待实现（P0） |
| MiniMax 直接调用封锁 | `build_audio_provider` 只通过 `GenerationService` 调用，不暴露 HTTP 接口 | 已满足 |
| 路径穿越防护 | `LocalFileStorage.existing_path_for` | 已实现 |

**Agent 无法直接访问 `MiniMaxTTSProvider`**。唯一路径是：`create_generation_job` → `GenerationService.run_job()` → `provider.generate()`。中间层负责配额检查和内容安全。

---

## 6. 与 algo 画像字段对齐规则

| 场景 | 以谁为准 | 原因 |
|---|---|---|
| 字段命名冲突（如 algo 叫 `user_cluster`，后端叫 `segment`）| **后端 contract 为准** | API 和数据库已上线，algo 字段通过 `algo_segment` 单独列存入，不替换现有字段 |
| 字段含义扩展（如 algo 希望 `mood_tags` 增加新枚举值）| **双方对齐后后端落地** | mood_tags 存 JSON，无 DB enum 约束，后端可直接接受新值 |
| 新增画像字段 | **算法定义口径，后端添加 DB 列** | `_migrate` 轻量新增，兼容现有数据 |
| 分群计算逻辑 | **算法主导，后端保留规则兜底** | `algo_segment` 由 worker 异步写入，冷启动时 fallback 到规则 `segment` |
| 实时请求必读字段 | **后端 `ProfileContext` 接口输出为准** | Agent 只读 `GET /profile/context`，不直接读 DB |
| 特征更新口径（哪些字段可实时更新，哪些离线）| **算法标注，后端 contract 确认** | 见第 1 节字段表，待算法方案后补全 |

**原则：算法定义字段语义和更新口径；后端定义字段在 API 和 DB 中的存储形式、默认值和兼容迁移路径。两者不一致时，以不破坏现有 API 和已有数据为底线。**

---

## 7. 最小落地改造清单

以下是从当前 MVP 到 Agent-ready 的最小改造，按优先级排列：

**P0（阻塞 Agent 接入）**：

1. 新增 `GET /users/{user_id}/profile/context` 返回 `ProfileContext`（含 `generation_budget`）。
2. 新增 `POST /normalize` 暴露 `RequestNormalizer`。
3. 新增 `POST /assets/search`，复用 `RecommendationService` + 精确 hash 检查，返回 `hit` 字段。
4. `create_generation_job` 增加每日额度检查，超额返回 429。
5. `POST /users/{user_id}/profile/checkin` 支持 `tonight_mood`/`tonight_stress` 部分更新。
6. `user_profiles` 表增加 `algo_segment`、`tonight_mood`、`tonight_stress`、`profile_version` 字段（通过 `_migrate`）。

**P1（Agent 质量提升）**：

7. `record_event` 增加对 `recommendation_served`、`audio_play_completed` 的 payload 字段校验。
8. `force_generate: true` 增加频率限制（每用户每小时上限）。
9. `SleepScriptService` 接入真实内容安全 guard。
10. `search_audio_assets` 支持 `min_duration_sec`/`max_duration_sec` 过滤。
