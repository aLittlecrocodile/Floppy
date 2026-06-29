# Floppy 后端接口文档（前端对接版）

> 版本：基于当前 `floppy_backend/main.py` 实现整理
> Base URL：`http://10.27.33.19:8000`
> 　所有返回的音频地址（`audio_url` / `playback_url` / `streamUrl`）由后端用环境变量 `FLOPPY_PUBLIC_BASE_URL` 拼出，已统一为该地址，**不会出现 `127.0.0.1` / `localhost`**。换部署环境（公网/转发）时只需改 `.env` 里的 `FLOPPY_PUBLIC_BASE_URL` 并重启，接口代码无需改动。
> 编码：请求与响应均为 `application/json; charset=utf-8`（上传接口为 `multipart/form-data`）
> 鉴权：当前 MVP 无鉴权，CORS 全开，`user_id` 由前端在路径中传入（仅用于开发联调）

---

## 0. 快速上手

- 最简单的演示链路可用 `POST /demo/chat`：命中时直接返回可播放 `audio_url`；需要生成时返回 `job_id`，前端轮询 `GET /generation-jobs/{job_id}`。
- 生产链路（可控、异步）建议用：`PUT /users/{user_id}/profile` → `POST /agent/decide` →（命中直接播放 / 未命中拿 `job_id` 轮询 `GET /generation-jobs/{job_id}`）→ 上报 `POST /users/{user_id}/events`。
- 音频播放：所有返回的 `playback_url` / `audio_url` 都可直接作为 `<audio src>` 使用。

通用错误响应（FastAPI 标准）：

```json
{ "detail": "错误描述" }
```

常见状态码：

| 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 201 | 创建成功（playback start / upload） |
| 202 | 已受理，异步处理中（生成任务 / remix） |
| 204 | 成功无返回体（删除 upload） |
| 400 | 参数错误 / 上传文件类型不支持 |
| 404 | 资源不存在（profile / asset / job / upload 未找到） |
| 422 | 请求体校验失败（FastAPI 校验，如缺必填字段） |
| 429 | 超出每日生成额度 / remix 频率限制 |

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

输入一句自然语言，Hermes Skill 理解需求并选择播放/生成/混音 workflow。命中资源直接返回音频，未命中且允许生成时返回生成任务。**前端只需调用这一个接口。**

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
  "audio_url": "http://10.27.33.19:8000/audio/pregen/meditation/xxx.wav",
  "asset": {
    "id": "aud_xxx",
    "type": "meditation",
    "title": "呼吸觉察·雨夜版",
    "duration_sec": 600,
    "playback_url": "http://10.27.33.19:8000/audio/pregen/meditation/xxx.wav"
  },
  "reply_text": "好的，把注意力轻轻放在呼吸上，吸气时感受平静进来，呼气时让紧张慢慢流走。",
  "is_placeholder": false,
  "job_id": null,
  "job_status": null,
  "best_score": 0.63,
  "hit": true,
  "threshold": 0.58,
  "reasons": ["标签命中: breathing, rain", "质量评分高"],
  "planner_meta": {
    "planner_source": "hermes",
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
| `reply_text` | string | 聊天机器人口吻的自然语言回复，供 Chat「转文字」展示。始终返回；LLM 失败时回退模板文案，不会为空 |
| `is_placeholder` | boolean | true 表示当前是占位音频（非真实成品） |
| `job_id` / `job_status` | string \| null | 生成路径才有；前端用 `job_id` 轮询生成结果 |
| `best_score` | number \| null | 检索最高分 |
| `hit` | boolean | 是否命中缓存资产 |
| `threshold` | number | 命中阈值（默认 0.58） |
| `reasons` | string[] | 播放/生成原因 |
| `planner_meta` | object \| null | Planner 元信息（来源/置信度/耗时/降级原因） |

> 注意：`/demo/chat` 内部使用固定的 `demo_user` 画像，仅用于演示。生产请走第 4、5 节接口。
> `reply_text` 由对话 LLM 实时生成（复用 `dialog_system_prompt` 人设），会给本接口增加一次 LLM 往返延迟。

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

响应：完整 `UserProfile`（含 `user_id` `segment` `tonight_mood` `tonight_stress` `profile_version` `updated_at`）。

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

## 5. 检索与生成

### POST `/assets/search`

按 Hermes 产出的结构化 filters 查询 approved 资源目录。`query` 只用于可读上下文和极轻量字面匹配；后端不再把用户原话翻译成标签。

```json
{
  "user_id": "u1",
  "query": "温柔女声睡前故事雨声",
  "cache_key": "sha256...（可选）",
  "filters": {
    "type": "story",
    "mood_tags": ["calm"],
    "required_tags": ["rain", "no_voice"],
    "preferred_tags": ["ambient"],
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
  "threshold": 0.0,
  "query_analysis": {
    "recognized_tags": ["rain", "no_voice"],
    "negative_tags": ["voice_present"],
    "excluded_types": ["asmr", "meditation", "podcast_digest", "story"],
    "hard_constraints": { "required_tags": true, "negative_tags": true, "no_voice": true, "no_thunder": false },
    "unknown_terms": [],
    "confidence": 1.0
  }
}
```

> 前端是否进入「生成」流程，请以 `/agent/decide` 的 `action` 为准。直接调用 `/assets/search` 时，必须传 Hermes/前端自己明确的 filters，不要期待后端理解自然语言。

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

异步生成。请求体同上。响应：

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
  "planner_meta": { "planner_source": "hermes", "planner_confidence": 0.9, "planner_latency_ms": 1200, "fallback_reason": null }
}
```

`action`：`play_asset` | `generate_job` | `remix_current` | `no_match`。

前端处理建议：
- `play_asset` → 直接播 `asset.playback_url`
- `generate_job` → 用 `job_id` 轮询 `GET /generation-jobs/{job_id}`
- `remix_current` → 用 `remix_job_id` 轮询 `GET /remix-jobs/{job_id}`
- `no_match` → 提示无结果，可根据 `reasons` 和 `search.results` 决定是否让用户换一个说法

---

## 6.5 首页语音意图（latest-wins）

### POST `/voice/intent`

首页语音输入专用。前端在一句话**说完**后调用（不发 partial），并自行实现 latest-wins：用户再说一句时把上一条标记为过期。

后端先走 Hermes `floppy-voice-dialog` Skill 做对话路由：普通倾诉/闲聊只返回 `chat`，模糊需求返回 `clarify`，只有明确音频意图才继续进入 `floppy-sleep-audio` 播放/生成/混音 workflow。

请求：

```json
{
  "text": "我今晚想听放松一点的",
  "conversationId": "home-session-xxx",
  "clientRequestId": "uuid-12",
  "turnIndex": 12,
  "source": "voice",
  "supersedesRequestId": "uuid-11",
  "user_id": "demo_user",
  "current_asset_id": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `text` | string | 是 | 完整一句话，≥1 字符（注意字段名是 `text`，不是 `request_text`） |
| `conversationId` | string | 是 | 同一会话内稳定不变，用于服务端按会话判断最新 turn |
| `clientRequestId` | string | 是 | 本次请求唯一 id，后端原样回显 |
| `turnIndex` | int | 是 | 单调递增的轮次号，服务端据此判断是否被取代 |
| `source` | string | 否 | 默认 `voice` |
| `supersedesRequestId` | string \| null | 否 | 被本次取代的上一条 id（当前仅作信息透传/日志） |
| `user_id` | string | 否 | 默认 `demo_user` |
| `current_asset_id` | string \| null | 否 | 当前播放资产 id，用于“换一个/加雨声”等 playback edit |

响应：

```json
{
  "conversationId": "home-session-xxx",
  "clientRequestId": "uuid-12",
  "turnIndex": 12,
  "reply": "好的，给你放一段轻柔的海浪声，闭上眼睛，让身体慢慢沉下去。",
  "audio_url": "http://10.27.33.19:8000/audio/xxx.mp3",
  "asset": { "id": "aud_xxx", "title": "...", "durationSeconds": 600, "streamUrl": "http://10.27.33.19:8000/audio/xxx.mp3", "source": "Library", "category": "...", "artwork": { "...": "..." } },
  "action": "play_asset",
  "audio_type": "white_noise",
  "job_id": null,
  "job_status": null,
  "hit": true,
  "best_score": 1.0,
  "reasons": ["精确缓存命中"]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `conversationId` / `clientRequestId` / `turnIndex` | — | 原样回显，前端据此匹配当前 active 请求 |
| `reply` | string | 自然语言回复（同 `/demo/chat` 的 reply_text） |
| `audio_url` | string \| null | 可播放 URL |
| `asset` | object \| null | camelCase 的 `AudioItem`（同 Audio 页结构，见第 11 节） |
| `action` | string | `chat` / `clarify` / `play_asset` / `generate_job` / `remix_current` / `no_match` / **`superseded`** |
| `audio_type` | string \| null | voice-dialog 识别的音频意图，仅进入音频 workflow 时通常有值 |
| `job_id` / `job_status` | string \| null | `generate_job` 时返回，前端轮询 `GET /generation-jobs/{job_id}` |

**latest-wins 关键约定：**
- 前端只处理当前 active 请求的返回，靠 `clientRequestId` / `turnIndex` 匹配；旧请求即使晚回来也丢弃，不更新首页状态。
- 服务端额外保护：若某个 turn 在到达或生成完成时已被同会话更新的 turn 取代，直接返回 `action="superseded"`、`reply=""`、`audio_url=null`、`reasons=["已被更新的语音请求取代"]`，**不消耗生成额度**。前端收到 `superseded` 直接忽略即可。
- 服务端 tracker 为进程内内存（不持久化），重启丢失无影响——客户端才是 latest-wins 的最终裁决者。

---

## 6.6 语音转文字（ASR）

> 主路用 WebSocket 实时流式，兜底用 HTTP 整段文件上传。两者后端都走火山引擎大模型流式 ASR。

### WebSocket `/v1/speech/stream`（主路，实时）

App 连接 `ws://10.27.245.10:8000/v1/speech/stream`。

**协议时序：**

1. 客户端连接成功后先发首包：
```json
{ "type": "start", "locale": "zh-CN", "sample_rate": 16000, "encoding": "pcm_s16le", "channels": 1 }
```
2. 之后持续发 **binary** WebSocket 帧：PCM 16-bit little-endian、16000 Hz、单声道。
3. 用户停止时发：
```json
{ "type": "stop" }
```

**服务端返回（text 帧）：**
- 边识别边返回（实时显示）：
```json
{ "type": "partial", "text": "我今晚想" }
```
- 一句话结束（句子 definite / 收到 stop）：
```json
{ "type": "final", "text": "我今晚想听一点放松的内容" }
```
- 失败：
```json
{ "type": "error", "message": "识别失败" }
```

约定：后端收到 `stop` 后**先返回 final 或 error，再结束本轮**，不会直接断开。App 收到 `final` 后调用现有 `completeSpeechListening(text)` → `submitTextIntent(text, source="voice")`；收到 `error` 自动 fallback 到下面的整段上传接口。

### POST `/v1/speech/transcriptions`（兜底，整段文件）

`Content-Type: multipart/form-data`

| 字段 | 说明 |
|---|---|
| `file` | 音频文件，Android 录的是 m4a（`mime=audio/mp4`，AAC 编码）。后端用 ffmpeg 解码，支持 m4a/aac/mp3/wav 等 |
| `locale` | `zh-CN` |
| `source` | `android_home` |

返回固定格式：
```json
{ "text": "识别出来的文字" }
```

- 没识别到内容返回 `{ "text": "" }`。
- 失败返回 `5xx` + `{ "detail": "transcription failed: ..." }`，App 提示「语音转文字失败」。

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
  "payload": { "play_duration_sec": 780, "completion_rate": 0.87, "source": "hermes" }
}
```

响应：`{ "event_id": "evt_xxx" }`。常用 `event_type`：`audio_play_started` `audio_skipped` `audio_play_completed` `audio_liked` `audio_disliked`。

播放反馈会写入历史记录，供后续体验分析和产品策略使用。

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

## 8.5 Android Audio 页（Library / Uploads / History）

> 这一组接口返回 **camelCase 的 `AudioItem` / `UploadItem`**，直接对接 Android 客户端模型，与上面 snake_case 的 `asset` 结构不同。

### AudioItem 结构（camelCase）

```json
{
  "id": "aud_xxx",
  "title": "轻柔的雨声呼吸放松",
  "subtitle": "anxiety_relief",
  "durationSeconds": 1133,
  "streamUrl": "http://10.27.33.19:8000/audio/xxx.mp3",
  "coverUrl": null,
  "artwork": { "imageUrl": null, "seedColor": 4284246976, "prompt": "...", "status": "Ready" },
  "source": "Library",
  "category": "Meditation",
  "playbackProgress": 0.0,
  "isGenerated": false
}
```

- `streamUrl` 必为非空可播地址（空会被前端过滤掉）。支持 HTTP Range（ExoPlayer 可直接播）。
- `source`：`Library` | `Upload` | `Generated`。
- `category`：由音频类型映射（Sleep stories / Meditation / White noise / Sleep music / ASMR / Podcast）。
- `artwork.seedColor`：按类型生成的稳定 ARGB 色值；`coverUrl`/`imageUrl` 暂为 null，前端用 seedColor 渲染封面背景。
- `durationSeconds`：库内音频为真实秒数；用户上传的音频暂为 0（后端未解码），前端可用 ExoPlayer 读真实时长。

### GET `/users/{user_id}/audio-library`

聚合接口，一次拉全三个 tab：

```json
{ "recommended": [AudioItem], "uploads": [UploadItem], "history": [AudioItem] }
```

- Library tab 用 `recommended`。无画像时回退展示 catalog，保证不空。
- 也可分别调 `GET /users/{user_id}/audio/recommended?limit=30`。

### Uploads

```text
POST   /users/{user_id}/uploads                  # multipart/form-data，字段名必须是 file
GET    /users/{user_id}/uploads
GET    /users/{user_id}/uploads/{upload_id}
POST   /users/{user_id}/uploads/{upload_id}/complete
POST   /users/{user_id}/uploads/{upload_id}/retry
DELETE /users/{user_id}/uploads/{upload_id}       # 204
```

UploadItem：

```json
{
  "id": "upload_xxx",
  "fileName": "demo.mp3",
  "fileType": "mp3",
  "sizeLabel": "2.4M",
  "progress": 1.0,
  "status": "Completed",
  "message": null,
  "generatedAudio": { "...AudioItem...": "source=Upload" }
}
```

- 支持类型：`mp3` `wav` `m4a` `pdf` `txt`。其他（如 jpg/png）返回 **400**。
- mp3/wav/m4a：上传后 `status="Completed"`，**`generatedAudio` 非空**（即上传文件本身，`source="Upload"`，`streamUrl` 可播）——前端可直接点击播放。
- pdf/txt：`status="Completed"`、`generatedAudio=null`、`message="待生成音频"`（生成流水线未接，前端显示「待处理」、点击无效，符合预期）。

### History

```text
GET   /users/{user_id}/audio/history?limit=50      # 返回 AudioItem[]
POST  /users/{user_id}/audio/history               # 上报播放
PATCH /users/{user_id}/audio/history/{audio_id}    # 更新进度
```

上报请求体（POST）：

```json
{ "audioId": "aud_xxx", "source": "Library", "positionSeconds": 0, "durationSeconds": 180, "playbackProgress": 0.45, "event": "play" }
```

- `event`：`play` | `progress` | `complete`。
- 返回完整 `AudioItem`（含 `streamUrl`/`title`/`subtitle`/`source`/`playbackProgress`），不只 audioId。
- `source` 由后端按播放来源准确映射：recommend→Library、generated/remix→Generated、import→Upload。
- `playbackProgress` 范围 0.0–1.0。

---

## 9. 枚举与数据说明

音频类型 `AudioType`：`white_noise` `music` `asmr` `story` `meditation` `podcast_digest`

资产来源 `created_by`：
- `seed_placeholder` 种子占位
- `pregen_local` 本地预生成占位
- `pregen_minimax` 真实 TTS 预生成
- `ondemand` 实时生成
- `remix` 混音输出

其他：
- `is_placeholder`（仅 `/demo/chat`）：`created_by` 为 seed/pregen_local 时为 true
- remix 输出资产带 `remix` 标签，可在资源库中检索
- 默认命中阈值 `threshold = 0.58`
- 默认每日额度：字符 200000、生成次数 10（超出返回 429）

camelCase（Audio 页/语音意图）相关：
- `source`：`Library` | `Upload` | `Generated`
- `UploadItem.status`：`Idle` | `Uploading` | `Failed` | `Completed`
- `artwork.status`：`Pending` | `Generating` | `Ready` | `Failed`
- `/voice/intent` 的 `action` 额外有 `superseded`（被更新的 turn 取代，前端忽略）

---

## 10. 前端最小接入流程（生产）

```text
1. PUT  /users/{user_id}/profile           # 首次/更新画像
2. POST /agent/decide                       # 输入一句话拿决策
   ├─ action=play_asset   → 播 asset.playback_url
   ├─ action=generate_job → 轮询 GET /generation-jobs/{job_id} 到 succeeded
   ├─ action=remix_current→ 轮询 GET /remix-jobs/{remix_job_id} 到 succeeded
   └─ action=no_match     → 提示无结果 + search.results 兜底
3. POST /users/{user_id}/playback           # 开始播放
4. POST /users/{user_id}/playback/{id}/feedback   # 反馈
5. POST /users/{user_id}/events             # 播放事件上报
```

> Demo 阶段可直接只用 `POST /demo/chat`，无需上面这套流程。
