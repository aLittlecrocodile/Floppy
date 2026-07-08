# Floppy 后端接口文档（前端对接版）

> 版本：基于当前 `floppy_backend/main.py` 实现整理（2026-06 更新：智能体指挥生成 + 真人声缓存 + 关额度）
> Base URL（本地）：`http://127.0.0.1:8000`（如用其它端口启动则替换；上云后替换为公网地址）
> 实时语音对话另见 WebSocket 文档：`docs/contracts/voice_dialog_ws.md`
> 编码：请求与响应均为 `application/json; charset=utf-8`
> 鉴权：当前 MVP 无鉴权，`user_id` 由前端在路径中传入

---

## 0. 快速上手

- 最简单的演示链路只需一个接口：`POST /demo/chat`，输入一句话，返回可播放的 `audio_url`，后端同步完成检索/生成，前端无需轮询。
- 生产链路（可控、异步）建议用：`PUT /users/{user_id}/profile` → `POST /agent/decide` →（命中直接播放 / 未命中拿 `job_id` 轮询 `GET /generation-jobs/{job_id}`）→ 上报 `POST /users/{user_id}/events`。
- 实时语音对话（ASR→对话→TTS，含听音频意图）：WebSocket `/voice/ws`，浏览器 Demo 页 `GET /voice`，协议见 `docs/contracts/voice_dialog_ws.md`。
- 音频播放：所有返回的 `playback_url` / `audio_url` 都可直接作为 `<audio src>` 使用。

### 生成与缓存（重要变更）

- 未命中资产时，智能体**先把用户需求+画像提炼成内容指令（GenerationDirective，含分段要点）**，再由 workflow 用真人声（MiniMax TTS）写出贴合用户的脚本——不再是套通用模板。
- 生成产物按 `prompt_hash` 入库缓存。**同一需求第二次请求会精确命中缓存（`action=play_asset`，不再生成）**；换了内容（不同意象/时长/类型）才重新生成。
- 缓存音频存于服务器 `storage/audio/ondemand/{user_id}/`，前端只认返回的 `playback_url`，无需关心路径。
- meditation/story/podcast 已**预热**了一批真人声缓存；white_noise/music 是真实素材，直接命中。

通用错误响应（FastAPI 标准）：

```json
{ "detail": "错误描述" }
```

常见状态码：

| 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 201 | 创建成功（playback start） |
| 202 | 已受理，异步处理中（生成任务 / remix） |
| 400 | 参数错误 |
| 404 | 资源不存在（profile / asset / job 未找到） |
| 429 | remix 频率限制（生成额度默认**已关闭**，见第 9 节） |

---

## 1. 基础

### GET `/health`

健康检查。

响应：

```json
{ "status": "ok", "app": "Floppy Backend MVP" }
```

### POST `/admin/seed`

初始化/重置预置音频资产（开发用）。

响应：

```json
{ "created_or_updated": 24 }
```

### GET `/audio/{object_key}`

流式获取音频文件。`object_key` 形如 `pregen/meditation/xxxx.wav`，一般不需要手动拼，直接用响应里的 `playback_url`。返回音频二进制（`audio/wav` 或 `audio/mpeg`）。

---

## 2. Demo 一站式接口（最快接入）

### POST `/demo/chat`

输入一句自然语言，后端用 AI Planner 理解需求，命中缓存直接返回音频，未命中则同步生成。**前端只需调用这一个接口，无需轮询。**

请求：

```json
{ "request_text": "我今晚压力很大，想听一个温柔的呼吸冥想，最好有轻微雨声，15分钟" }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `request_text` | string | 是 | 用户输入，至少 2 个字符 |

响应：

```json
{
  "action": "play_asset",
  "audio_url": "http://127.0.0.1:8000/audio/ondemand/demo_user/3f2a1c9e8b7d6543.mp3",
  "asset": {
    "id": "aud_xxx",
    "type": "meditation",
    "title": "呼吸觉察·雨夜版",
    "duration_sec": 600,
    "playback_url": "http://127.0.0.1:8000/audio/ondemand/demo_user/3f2a1c9e8b7d6543.mp3"
  },
  "is_placeholder": false,
  "job_id": null,
  "job_status": null,
  "best_score": 1.0,
  "hit": true,
  "threshold": 0.58,
  "reasons": ["精确缓存命中"],
  "planner_meta": {
    "planner_source": "ai",
    "planner_confidence": 0.9,
    "planner_latency_ms": 1200,
    "fallback_reason": null
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `action` | string | `play_asset`（命中播放）/ `generate_job`（生成）/ `no_match` |
| `audio_url` | string \| null | 可播放 URL，前端播放器主用 |
| `asset` | object \| null | 命中或生成成功的资产 |
| `is_placeholder` | boolean | true 表示当前是占位音频（非真实成品） |
| `job_id` / `job_status` | string \| null | 生成路径才有；Demo 接口已同步等待完成 |
| `best_score` | number \| null | 检索最高分 |
| `hit` | boolean | 是否命中缓存资产 |
| `threshold` | number | 命中阈值（默认 0.58） |
| `reasons` | string[] | 推荐/生成原因 |
| `planner_meta` | object \| null | Planner 元信息（来源/置信度/耗时/降级原因） |

> 注意：`/demo/chat` 内部使用固定的 `demo_user` 画像，仅用于演示。生产请走第 4、5 节接口。

---

## 3. 用户画像

### PUT `/users/{user_id}/profile`

创建或更新长期睡眠画像。

请求（所有字段可选，有默认值）：

```json
{
  "audio_type_preferences": ["story", "white_noise"],
  "voice_preferences": ["warm_female"],
  "background_preferences": ["rain_soft"],
  "duration_preference_min": 15,
  "stress_level": "high",
  "anxiety_level": "medium",
  "avg_sleep_latency_min": 35,
  "mood_tags": ["anxiety_relief"]
}
```

| 字段 | 类型 | 取值/约束 |
|---|---|---|
| `audio_type_preferences` | string[] | `white_noise` `music` `asmr` `story` `meditation` `podcast_digest` |
| `voice_preferences` | string[] | 自由文本，如 `warm_female` |
| `background_preferences` | string[] | 自由文本，如 `rain_soft` |
| `duration_preference_min` | int | 5–60，默认 15 |
| `stress_level` / `anxiety_level` | string | `low` `medium` `high` |
| `avg_sleep_latency_min` | int | 0–180，默认 25 |
| `mood_tags` | string[] | 自由文本标签 |

响应：完整 `UserProfile`（含 `user_id` `segment` `algo_segment` `tonight_mood` `tonight_stress` `profile_version` `updated_at`）。

### GET `/users/{user_id}/profile`

返回 `UserProfile`，不存在返回 404。

### POST `/users/{user_id}/profile/checkin`

更新「今晚」临时状态（不影响长期偏好）。

```json
{ "tonight_mood": "tired", "tonight_stress": "medium", "sleep_latency_hint_min": 40 }
```

字段均可选。响应返回更新后的 `UserProfile`。

### GET `/users/{user_id}/profile/context`

返回画像 + 实时生成预算，Agent 决策上下文。

```json
{
  "user_id": "u1",
  "segment": "anxiety_relief",
  "algo_segment": null,
  "audio_type_preferences": ["story"],
  "voice_preferences": ["warm_female"],
  "background_preferences": ["rain_soft"],
  "duration_preference_min": 15,
  "stress_level": "high",
  "anxiety_level": "medium",
  "avg_sleep_latency_min": 35,
  "mood_tags": ["anxiety_relief"],
  "tonight_mood": "tired",
  "tonight_stress": "medium",
  "profile_version": 2,
  "updated_at": "2026-06-26T12:00:00",
  "generation_budget": {
    "daily_remaining_chars": 198000,
    "daily_generate_count_remaining": 9
  }
}
```

---

## 4. 问卷（冷启动 onboarding）

### PUT `/users/{user_id}/questionnaire`

```json
{
  "gender": "female",
  "age_range": "25-34",
  "occupation": "designer",
  "bedtime": "23:30",
  "main_sleep_problem": "difficulty_falling_asleep",
  "bedtime_habits": ["phone", "reading"],
  "favorite_content_types": ["meditation", "story"],
  "preferred_companion_style": "warm",
  "voice_preferences": ["warm_female"]
}
```

所有字段可选。响应：`UserQuestionnaire`（含 `user_id` `completed_at` `updated_at`）。

### GET `/users/{user_id}/questionnaire`

返回 `UserQuestionnaire`，不存在返回 404。

---

## 5. 检索、推荐与生成

### POST `/normalize`

将自然语言归一化为结构化请求 + 缓存键。

```json
{ "request_text": "温柔女声讲海边书店的睡前故事，15分钟", "user_id": "u1", "duration_preference_min": 15 }
```

响应：

```json
{
  "normalized_request": {
    "intent": "story",
    "language": "zh-CN",
    "duration_bucket": "long",
    "duration_sec": 900,
    "voice_style": "warm_female",
    "background": "rain_soft",
    "mood": ["calm", "gentle"],
    "content_topic": ["海边", "书店"]
  },
  "cache_key": "sha256..."
}
```

### POST `/assets/search`

按标签/画像/向量检索候选资产。

```json
{
  "user_id": "u1",
  "query": "温柔女声睡前故事雨声",
  "cache_key": "sha256...（可选）",
  "filters": {
    "type": "story",
    "mood_tags": ["calm"],
    "preferred_tags": [],
    "negative_tags": [],
    "min_duration_sec": 600,
    "max_duration_sec": 1200
  },
  "limit": 5
}
```

响应：

```json
{
  "results": [
    {
      "asset": { "id": "aud_abc", "title": "海边书店的夜晚", "type": "story", "duration_sec": 900, "playback_url": "http://..." },
      "score": 0.83,
      "match_type": "asset_match",
      "reasons": ["标签命中", "质量评分高"]
    }
  ],
  "hit": true,
  "best_score": 0.83,
  "threshold": 0.58
}
```

> 前端是否进入「生成」流程，请以 `hit` 字段为准，不要自行用 `score` 判断。

### GET `/users/{user_id}/recommendations?limit=5&query=`

返回推荐列表（`query` 可选）：

```json
[
  { "asset": { "id": "aud_abc", "title": "...", "playback_url": "http://..." }, "score": 0.81, "reasons": ["..."] }
]
```

### POST `/users/{user_id}/generate-audio`

同步生成或命中缓存（会阻塞等待）。

```json
{ "request_text": "温柔女声讲海边书店的睡前故事，15分钟", "duration_preference_min": 15, "force_generate": false }
```

响应（`GenerationResponse`）：

```json
{
  "job_id": "job_xxx",
  "status": "succeeded",
  "cache_hit": false,
  "match_type": "generated",
  "asset": { "id": "aud_xxx", "playback_url": "http://..." },
  "normalized_request": { "intent": "story", "duration_sec": 900, "...": "..." }
}
```

超出每日额度返回 `429`。

### POST `/users/{user_id}/generation-jobs` → 202

异步生成（推荐生产使用）。请求体同上。响应：

```json
{
  "job_id": "job_xxx",
  "status": "queued",
  "cache_hit": false,
  "match_type": "queued",
  "asset": null,
  "normalized_request": { "...": "..." }
}
```

> 若 `cache_hit` 为 true，`status` 会直接是命中状态、`asset` 非空，无需轮询。

### GET `/generation-jobs/{job_id}`

轮询生成任务（建议间隔 2–3 秒）。

```json
{
  "id": "job_xxx",
  "user_id": "u1",
  "status": "succeeded",
  "asset": { "id": "aud_xxx", "playback_url": "http://..." },
  "usage_characters": 661,
  "estimated_cost_usd": 0.0661,
  "latency_ms": 3200,
  "error_code": null,
  "error_message": null
}
```

`status`：`queued` | `generating` | `succeeded` | `failed`。不存在返回 404。

---

## 6. Agent 决策（生产主链路）

### POST `/agent/decide`

输入一句话，返回决策动作。命中直接给 asset；未命中且允许生成则后台创建生成任务并返回 `job_id`；识别到 remix 意图则返回 `remix_job_id`。

```json
{
  "user_id": "u1",
  "request_text": "给当前这首加点雨声",
  "generation_allowed": true,
  "current_asset_id": "aud_playing_xxx"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `user_id` | string | 是 | 需已创建画像，否则 404 |
| `request_text` | string | 是 | ≥2 字符 |
| `generation_allowed` | boolean | 否 | 默认 true，false 时未命中只返回 `no_match` |
| `current_asset_id` | string | 否 | 当前播放资产，用于 remix 上下文 |

响应：

```json
{
  "action": "play_asset",
  "asset": { "id": "aud_xxx", "playback_url": "http://..." },
  "job_id": null,
  "remix_job_id": null,
  "normalized_request": { "...": "..." },
  "profile_context": { "...": "..." },
  "search": { "hit": true, "best_score": 0.83, "threshold": 0.58, "results": [] },
  "reasons": ["..."],
  "planner_meta": { "planner_source": "ai", "planner_confidence": 0.9, "planner_latency_ms": 1200, "fallback_reason": null }
}
```

`action`：`play_asset` | `generate_job` | `remix_current` | `no_match`。

> 2026-07 起决策层全量迁移至 Hermes 智能体：资源匹配由智能体在资产目录中自主裁决，不再有相似度打分/阈值门槛。`planner_meta.planner_source` 为 `hermes`（或 `exact_cache` 精确缓存短路）；此接口返回的 `search.threshold` 恒为 0，`search.results` 仅作展示/兜底推荐用。Hermes 不可用时返回 `no_match`，`fallback_reason` 以 `hermes_unavailable:` 开头。

前端处理建议：
- `play_asset` → 直接播 `asset.playback_url`
- `generate_job` → 用 `job_id` 轮询 `GET /generation-jobs/{job_id}`
- `remix_current` → 用 `remix_job_id` 轮询 `GET /remix-jobs/{job_id}`
- `no_match` → 提示无结果，可用 `search.results` 做相关推荐兜底

---

## 7. 播放历史与反馈

### POST `/users/{user_id}/playback` → 201

开始一次播放会话。

```json
{
  "asset_id": "aud_xxx",
  "source": "recommend",
  "request_text": "可选原始请求",
  "parent_asset_id": null,
  "ambient_asset_id": null
}
```

`source`：`recommend` | `generated` | `remix` | `import`。响应：`{ "record_id": "pb_xxx" }`。asset 不存在返回 404。

### POST `/users/{user_id}/playback/{record_id}/feedback`

```json
{ "feedback_type": "trial_rating", "rating": 4, "progress": 0.3, "morning_feedback": null }
```

`feedback_type`：`trial_rating` | `favorite` | `dislike` | `skip` | `complete` | `morning_feedback`。
- `rating` 1–5（可选）；`progress` 0.0–1.0（可选）；`morning_feedback` 自由文本。

响应：`{ "status": "ok" }`。

### GET `/users/{user_id}/playback/history?limit=50`

返回最近 N 条（最多 50），最新在前。

```json
[
  {
    "id": "pb_xxx", "user_id": "u1", "asset_id": "aud_xxx", "title": "呼吸觉察·雨夜版",
    "source": "recommend", "started_at": "2026-06-26T...", "completed_at": "2026-06-26T...",
    "progress": 1.0, "rating": 4, "feedback_type": "complete", "morning_feedback": null
  }
]
```

### POST `/users/{user_id}/events`

上报行为事件（驱动画像优化）。

```json
{
  "event_type": "audio_play_completed",
  "asset_id": "aud_xxx",
  "payload": { "play_duration_sec": 780, "completion_rate": 0.87, "source": "agent_recommendation" }
}
```

响应：`{ "event_id": "evt_xxx" }`。常用 `event_type`：`audio_play_started` `audio_skipped` `audio_play_completed` `audio_liked` `audio_disliked`。

---

## 8. Remix（人声 + 环境音混音）

### POST `/users/{user_id}/remix` → 202（旧版，简单）

```json
{
  "voice_asset_id": "aud_meditation_xxx",
  "ambient_asset_id": "aud_rain_xxx",
  "sound_type": null,
  "ambient_tags": [],
  "voice_volume": 1.0,
  "ambient_volume": 0.3
}
```

`ambient_asset_id` 和 `sound_type` 至少给一个（`sound_type` 可选值：`rain/ocean/fire/forest/stream/fan/piano/wind`）。音量 0.0–2.0。响应：`RemixJob`（初始 `status=queued`）。

### GET `/remix-jobs/{job_id}`

```json
{
  "id": "rmx_xxx",
  "status": "succeeded",
  "output_asset_id": "aud_xxx",
  "output_asset": { "playback_url": "http://...", "...": "..." },
  "error_message": null
}
```

`status`：`queued` | `processing` | `succeeded` | `failed`。

### POST `/remix/sessions` → 202（新版，推荐）

```json
{
  "foreground_asset_id": "aud_voice_xxx",
  "ambient_asset_id": null,
  "sound_type": "rain",
  "intent": "add_background",
  "mix_params": { "background_volume": 0.3, "crossfade_in_sec": 2, "crossfade_out_sec": 3, "duck_on_speech": true }
}
```

`intent`：`add_background` | `change_background` | `adjust_volume` | `remove_background` | `voice_plus_ambient`。`foreground_asset_id` 当前必填（否则 400）。每用户每小时上限 20，超出返回 429。响应：`RemixSession`。

### PATCH `/remix/sessions/{session_id}`

调整进行中的 remix（换背景/调音量/移除背景），会重新跑混音。请求字段均可选：`intent` `sound_type` `ambient_asset_id` `mix_params`。响应：更新后的 `RemixSession`。

### GET `/remix/sessions/{session_id}`

返回 `RemixSession`，含 `output_asset.playback_url`。不存在返回 404。

### GET `/assets/{asset_id}/remixable`

判断某资产是否可被 remix（占位音频/文件缺失不可）。

```json
{ "asset_id": "aud_xxx", "remixable": true, "reason": null, "format": "wav" }
```

---

## 9. 枚举与数据说明

音频类型 `AudioType`：`white_noise` `music` `asmr` `story` `meditation` `podcast_digest`

资产来源 `created_by`：
- `real_asset` 真实素材音频（white_noise/music，公版录音/演奏）
- `ondemand` 智能体按需生成的真人声（含预热缓存）
- `remix` 混音输出
- `seed_placeholder` / `pregen_local` 旧版占位（已弃用，不再 seed）

其他：
- `is_placeholder`（仅 `/demo/chat`）：占位音频时为 true（现网已无占位资产）
- remix 输出资产带 `remix` 标签，可参与推荐
- 默认命中阈值 `threshold = 0.58`
- **生成额度默认已关闭**（`FLOPPY_ENFORCE_GENERATION_BUDGET=false`），不再因每日次数/字数返回 429；如需开启，置为 `true`，默认上限字符 200000、生成次数 10。

---

## 10. 前端最小接入流程（生产）

```text
1. PUT  /users/{user_id}/profile           # 首次/更新画像
2. POST /agent/decide                       # 输入一句话拿决策
   ├─ action=play_asset   → 播 asset.playback_url（命中缓存/已有资产，含已生成过的真人声）
   ├─ action=generate_job → 智能体已组装内容指令并入队，轮询 GET /generation-jobs/{job_id} 到 succeeded（首次生成真人声，约 10-25s；之后同需求会走 play_asset）
   ├─ action=remix_current→ 轮询 GET /remix-jobs/{remix_job_id} 到 succeeded
   └─ action=no_match     → 提示无结果 + search.results 兜底
3. POST /users/{user_id}/playback           # 开始播放
4. POST /users/{user_id}/playback/{id}/feedback   # 反馈
5. POST /users/{user_id}/events             # 播放事件上报
```

> Demo 阶段可直接只用 `POST /demo/chat`，无需上面这套流程。
> 实时语音对话用 WebSocket `/voice/ws`，协议另见 `docs/contracts/voice_dialog_ws.md`。
> 后端启动/部署/环境变量见 `docs/STARTUP.md`。
