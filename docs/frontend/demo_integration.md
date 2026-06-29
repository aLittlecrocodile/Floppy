# Floppy Demo 前端对接文档

本文档面向前端同学，说明当前 Floppy 助眠音频 Demo 的页面对接方式。

当前目标是支持一个最小可演示页面：

1. 用户输入一句助眠需求。
2. 前端提交给后端。
3. Hermes Skill 理解需求并选择播放、生成或混音 workflow。
4. 命中资源则直接返回播放地址。
5. 未命中且允许生成时返回生成任务。
6. 前端播放音频或轮询任务结果。

---

## 1. 本地服务

后端服务：

```bash
.venv/bin/uvicorn floppy_backend.main:app --host 127.0.0.1 --port 8010
```

Demo 页面：

```text
http://127.0.0.1:8010/demo
```

当前 Demo 页面已经挂在后端服务内，前端也可以自行实现页面，只对接本文档中的接口。

---

## 2. 核心接口

### POST `/demo/chat`

用于 Demo 页面的一站式接口。前端只需要调用这个接口，不需要直接调用 MiniMax、Agent、用户画像、任务轮询等内部接口。

#### Request

```json
{
  "request_text": "我今晚压力很大，一直胡思乱想，想听一个温柔的呼吸冥想，最好有轻微雨声，15分钟"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `request_text` | string | 是 | 用户输入的自然语言需求 |

#### Response

```json
{
  "action": "play_asset",
  "audio_url": "http://127.0.0.1:8010/audio/pregen/meditation/xxx.wav",
  "asset": {
    "id": "aud_xxx",
    "type": "meditation",
    "title": "rain meditation · rain_soft",
    "duration_sec": 900,
    "playback_url": "http://127.0.0.1:8010/audio/pregen/meditation/xxx.wav"
  },
  "job_id": null,
  "job_status": null,
  "best_score": 0.63,
  "hit": true,
  "threshold": 0.58,
  "reasons": [
    "标签命中: breathing, rain, short_duration",
    "质量评分高",
    "匹配音频偏好"
  ],
  "planner_meta": {
    "planner_source": "hermes",
    "planner_confidence": 0.9,
    "planner_latency_ms": 6500,
    "fallback_reason": null
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `action` | string | 决策结果。当前可能为 `play_asset` / `generate_job` / `no_match` |
| `audio_url` | string \| null | 可播放音频 URL。前端播放器主要使用这个字段 |
| `asset` | object \| null | 音频资产信息。命中缓存或生成成功时返回 |
| `job_id` | string \| null | 生成任务 ID。仅生成路径存在 |
| `job_status` | string \| null | 生成任务状态。需要生成时前端用 `job_id` 轮询结果 |
| `best_score` | number \| null | 检索最高分 |
| `hit` | boolean | 是否命中缓存资产 |
| `threshold` | number | 当前命中阈值，默认 `0.58` |
| `reasons` | string[] | 播放或生成原因 |
| `planner_meta` | object \| null | Hermes 决策元信息 |

`planner_meta` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `planner_source` | string | `hermes` 表示 Hermes 完成决策 |
| `planner_confidence` | number | Hermes 对动作选择的置信度 |
| `planner_latency_ms` | number | Hermes 调用耗时 |
| `fallback_reason` | string \| null | fallback 原因 |

---

## 3. 前端页面流程

查找/播放最小流程：

```text
用户输入 request_text
    ↓
点击按钮
    ↓
按钮 disabled，展示“处理中”
    ↓
POST /demo/chat
    ↓
拿到 response.audio_url
    ↓
设置 audio.src = audio_url
    ↓
展示 action / best_score / planner_meta / reasons
```

前端伪代码：

```js
async function submit(requestText) {
  setLoading(true);
  const resp = await fetch("/demo/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({request_text: requestText})
  });

  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || "请求失败");
  }

  audio.src = data.audio_url;
  actionText.textContent = data.action;
  scoreText.textContent = data.best_score ?? "-";
  plannerText.textContent = data.planner_meta?.planner_source ?? "-";
  reasonText.textContent = data.reasons.join(" / ");
  setLoading(false);
}
```

---

## 4. 状态展示建议

| 状态 | 触发条件 | 前端文案 |
|---|---|---|
| idle | 初始状态 | 就绪 |
| loading | 请求已发出，未返回 | 处理中... |
| success with audio | `audio_url` 非空 | 完成，可播放 |
| success without audio | `audio_url` 为空且 `job_id` 非空 | 已创建生成任务，轮询 job |
| success without audio | `audio_url` 为空且无 `job_id` | 完成，但没有音频 |
| error | HTTP 4xx/5xx 或网络错误 | 失败：错误信息 |

当前 `/demo/chat` 是 Demo 友好接口：命中已有音频会直接返回 `audio_url`；需要新生成时返回 `job_id`，前端轮询：

```text
POST /agent/decide
  -> action=generate_job
GET /generation-jobs/{job_id}
  -> status=succeeded
  -> asset.playback_url
```

这部分暂时 TBD。

---

## 5. 架构说明

```text
[Web Demo 页面]
      |
      | POST /demo/chat
      v
[FastAPI Demo API]
      |
      v
[Hermes Agent Runtime]
      |
      +--> [资源目录候选 + profile context]
      |
      v
[AssetCatalogService 资源目录查询]
      |
      +-- 命中 --> [Audio Asset DB + Local Storage] --> 返回 audio_url
      |
      +-- 未命中 --> [GenerationService]
                         |
                         v
                  [MiniMax T2A API]
                         |
                         v
                [保存音频 + 写入资产库]
                         |
                         v
                    返回 audio_url
```

---

## 6. 当前能力边界

已实现：

- 页面输入一句自然语言。
- Hermes Skill 生成结构化资源检索计划并选择 workflow。
- 命中资产库后返回可播放音频 URL。
- 未命中时调用 MiniMax 生成音频。
- 音频保存到本地并通过 `/audio/{object_key}` 播放。

当前 Demo 限制：

- `play_asset` 命中的缓存资产可能是本地预生成占位音频，不一定是真实雨声混音。
- MiniMax 当前生成的是语音音频，不是视频。
- 背景雨声目前主要是文本/标签语义，不代表一定混入真实雨声音轨。
- Demo 用户画像是后端默认写死的 `demo_user`，还没有前端画像编辑页。
- 生成任务由 `/demo/chat` 返回 `job_id` 后异步执行；前端应轮询 job 直到完成。

TBD：

- 前端画像配置页。
- 真实用户登录态和 `user_id`。
- 生成任务进度条。
- 多音频候选列表。
- 用户反馈入口：喜欢、不喜欢、跳过、睡眠反馈。
- 播放事件上报。

---

## 7. 前端建议页面结构

最小版：

```text
┌──────────────────────────────┐
│ 输入框：用户助眠需求          │
│ [播放 / 生成音频]             │
│ 状态：处理中 / 完成 / 失败    │
│                              │
│ 指标：action / score / planner│
│ <audio controls />            │
│ reasons/debug JSON            │
└──────────────────────────────┘
```

后续增强：

- 增加“强制生成”开关。
- 增加“只用缓存”开关。
- 增加“用户画像”侧栏。
- 增加生成历史列表。
- 增加反馈按钮：喜欢 / 不喜欢 / 太短 / 没有背景声。
