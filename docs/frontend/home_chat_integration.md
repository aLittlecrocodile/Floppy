# Home / Chat 对接文档（移动端）

> Base URL（当前联调）：`http://172.22.159.11:8000`（后端开发机 LAN 地址，手机需与其在同一 Wi-Fi）
> 上公网 / 换网络后 Base URL 会变，以后端同学通知为准；音频 `streamUrl` 由后端按当前 Base URL 生成，前端不要自己拼。
> 编码：`application/json; charset=utf-8`；MVP 无鉴权，`user_id` 由客户端本地生成并保持稳定。

以下 4 个接口均已实现并联调通过。

---

## 1. POST `/voice/intent` — 文本/语音统一意图

Chat 发文字（`source="chat"`）和 Home 语音识别完成后（`source="voice"`）都调这个。

**同步接口**：命中已有音频立即返回；需要现场生成时后端同步等待生成完成（真人声约 10–25 秒），前端**无需轮询**，但请把请求超时设到 **60 秒** 并在 UI 上做等待态。

请求：

```json
{
  "text": "我今晚想听一点放松的内容",
  "source": "chat",
  "conversationId": "android-home-xxx",
  "clientRequestId": "uuid",
  "turnIndex": 1,
  "supersedesRequestId": null,
  "user_id": "本地生成的用户id"
}
```

响应（`action` 只有两种）：

```json
{
  "action": "play_asset",
  "reply": "我给你找了一段适合现在听的音频：《经典冥想音乐》。",
  "audio": {
    "id": "aud_920cc3004e606c72af6f",
    "title": "经典冥想音乐",
    "subtitle": "8 min · Meditation",
    "durationSeconds": 462,
    "streamUrl": "http://172.22.159.11:8000/audio/ondemand/xxx.mp3",
    "coverUrl": null,
    "source": "Generated",
    "category": "Meditation",
    "playbackProgress": 0.0,
    "isGenerated": true
  },
  "conversationId": "android-home-xxx",
  "clientRequestId": "uuid",
  "turnIndex": 1
}
```

| 字段 | 说明 |
|---|---|
| `action` | `play_asset`（audio 可直接播）/ `generate_job`（**异步生成已开始**，见下两行）/ `chat`（纯聊天轮，只显示 reply）/ `no_match`（只显示 reply 文案） |
| `reply` | 给用户看的一句话回复，Chat 气泡直接用。**智能体现在支持多轮闲聊**（倾诉/提问会得到共情回复而不是硬塞音频），聊天中表达想听时才触发播放——前端无需改动，continue 展示 reply、audio 非空才播即可 |
| `replyAudioUrl` | **Floppy 语音回复**（MiniMax 温柔女声念出 reply），string \| null。建议前端：非空则先播这段（几秒），`audio` 非空再接主音频。不播也不影响任何功能 |
| `job_id` | 仅 `action=generate_job` 时返回。**生成不再同步等待**：接口秒回承诺回复，前端每 3s 轮询 `GET /v1/generation-tasks/{job_id}`（建议上限 5 分钟），`status=Success` 时响应带完整 `audio` + `notify_audio_url` |
| `notify_audio_url` | 兜底播报语音 mp3（固定文案「刚刚你想听的音频生成完成了，现在来听听吧」），string \| null。生成完成后建议：等当前对话轮次结束（不在录音/不在等回复）→ 播这段 → 自动播放 `audio` |
| `audio.streamUrl` | 可直接作为播放器 source |
| `audio.coverUrl` | 当前恒为 `null`，前端用本地占位图 |
| `audio.category` | `White Noise` `Music` `ASMR` `Story` `Meditation` `Podcast` |
| `audio.source` | `Library`（真实素材）/ `Generated`（AI 生成） |
| `conversationId` / `clientRequestId` / `turnIndex` | 原样回显，用于前端关联请求 |

---

## 2. WebSocket `/v1/speech/stream` — 实时语音识别（优先）

`ws://172.22.159.11:8000/v1/speech/stream`

协议（纯识别，不含对话/TTS）：

1. 连接后先发一条 JSON：
   ```json
   { "type": "start", "locale": "zh-CN", "sample_rate": 16000, "encoding": "pcm_s16le", "channels": 1 }
   ```
   ⚠️ 上行格式固定 **16kHz / 单声道 / 16bit PCM**（ASR 供应商硬性要求），start 里传别的值不会生效。
2. 之后连续发送 **binary 帧**（建议每帧 100ms = 3200 字节）。
3. 说完发 `{ "type": "stop" }`（兜底路径，见下）。
4. 服务端下行（均为 JSON 文本帧）：
   ```json
   { "type": "partial", "text": "我今晚想听" }        // 累积式中间结果，会多次推送
   { "type": "final",   "text": "我今晚想听一点放松的内容" }  // 见触发时机，推送一次后连接关闭
   { "type": "error",   "message": "xxx" }
   ```

**final 触发时机（服务端 VAD）**：转写文本 **1.2 秒**无变化即判定用户说完，服务端**主动**推 `final` 并关连接——正常情况下无需客户端发 stop。注意：用户从未开口（无任何转写文本）时不会推 VAD final，请保留客户端静音兜底（当前 3s，与 1.2s 距离充分，无需调整）。`{"type":"stop"}` 仍然全量支持：收到后立即结束识别并回一条 `final`（只会推一次，VAD 已推过则 stop 不重复推）。

`partial.text` 是**累积全文**（不是增量），直接整体替换显示即可。拿到 `final.text` 后再调 `/voice/intent`（`source="voice"`）。

---

## 3. POST `/v1/speech/transcriptions` — 录音文件转文字（兜底）

实时识别失败时上传整段录音。`multipart/form-data`：

| 字段 | 说明 |
|---|---|
| `file` | 音频文件，m4a / mp4 / wav / mp3 均可（服务端 ffmpeg 解码） |
| `locale` | 如 `zh-CN`（可选，默认 zh-CN） |
| `source` | 如 `android_home`（可选） |

响应：

```json
{ "text": "我今晚想听一点放松的内容", "language": "zh-CN", "duration_ms": 6016 }
```

错误：`400` 空文件/解码失败，`502` ASR 服务失败（body 为 `{"detail": "..."}`）。

---

## 4. GET `/users/{userId}/audio-library` — 首页初始数据

`GET /users/{userId}/audio-library?limit=10`

```json
{
  "recommended": [ AudioItem, ... ],   // 音频目录，最新在前
  "uploads": [],                        // 用户上传功能未上线，恒为空数组
  "history": [ AudioItem, ... ]         // 播放历史，AudioItem.playbackProgress 为上次进度 0~1
}
```

`AudioItem` 结构与 `/voice/intent` 的 `audio` 完全一致。

> history 需要前端在播放时上报：`POST /users/{userId}/playback`（开始）和 `POST /users/{userId}/playback/{recordId}/feedback`（进度/评分），见 [backend_api_reference.md](./backend_api_reference.md) 第 7 节。不上报则 history 为空。

---

## 5. WebSocket `/voice/realtime` — 和 Floppy 打电话（豆包端到端实时语音）

`ws://<BASE>/voice/realtime?user_id=xxx` — 纯陪聊语音通话（亚秒级响应、可打断），Android 端已实现（`RealtimeCallClient.kt` + 右下角 📞 悬浮按钮）。

协议（后端已把豆包二进制协议全部封装掉）：
- **上行**：binary = 麦克风 PCM 16k/mono/s16le（20ms/包）；`{"type":"stop"}` 挂断
- **下行**：binary = Floppy 回复语音 PCM **24k**/mono/s16le（AudioTrack 直接播）
  JSON：`{"type":"ready"}`（接通，开始推麦克风）/ `{"type":"asr","text","interim"}`（你的话）/ `{"type":"chat","text"}`（Floppy 字幕）/ `{"type":"asr_info"}`（**用户开口信号，客户端立刻停播实现打断**）/ `{"type":"tts_end"}`（Floppy 这轮说完 = 轮次边界）/ `{"type":"session_end"}`（会话正常结束）/ `{"type":"error","message"}`

**通话中点播/生成（新）**：后端代理会从用户的话里识别「想听 XX」并自动派单，前端无需发任何请求：
- `{"type":"generation_started","jobId"}` — 已开始后台生成（豆包会口头承诺「我去准备，好了叫你」，继续陪聊）
- `{"type":"generation_done","jobId","audio":{AudioItem},"notifyAudioUrl"}` — 做好了（缓存命中则秒到，此时 `jobId` 为 null）。客户端建议流程：等下一个 `tts_end` 轮次边界 → **温柔自动挂断** → 播 `notifyAudioUrl` → 自动播放 `audio`。若用户提前挂断且只收到过 `generation_started`，拿 `jobId` 轮询 `GET /v1/generation-tasks/{jobId}` 兜底

## 推荐接入流程

```text
Home 首屏   → GET /users/{uid}/audio-library
Home 语音   → WS /v1/speech/stream（失败则 POST /v1/speech/transcriptions）
            → 拿到 text 后 POST /voice/intent (source=voice)
Chat 文字   → POST /voice/intent (source=chat)
播放        → audio.streamUrl 直接给播放器；开始/结束上报 playback 接口
```

## App 兼容层接口（对齐 front/Floppy 的 FloppyApi.kt，已全部实现）

除上述 4 个核心接口外，后端已按 `RemoteFloppyRepository` 的实际调用补齐：

| 接口 | 说明 |
|---|---|
| `POST /v1/recommendations` | 今晚推荐：body 为前端 UserProfile，按 contentPreferences 从目录选一条，返回 `{action:"play_asset", audio}` |
| `POST /v1/generation-tasks` / `GET /v1/generation-tasks/{id}` | 生成任务：status 为 `Pending/Generating/Success/Failed`（对齐 Kotlin 枚举），Success 时带 `audio` |
| `POST /v1/feedback` | `{audioId, rating, reason?}` → `{accepted, message}` |
| `POST /users/{uid}/audio/history` | 播放上报，落播放历史（驱动 audio-library 的 history） |
| `POST /v1/settings` | 原样回显（设置暂存客户端） |
| `POST /users/{uid}/uploads` | 上传音频文件，入库可播，出现在 audio-library 的 uploads；`GET /users/{uid}/uploads` 与 retry/complete 同步实现 |
| `PUT /users/{uid}/questionnaire` / `PUT /users/{uid}/profile` / `POST /users/{uid}/events` | 原有接口，onboarding 直接可用 |

前端零改动：`gradle.properties` 的 `floppy.apiBaseUrl` 已指向当前后端，重新 build 即可。

## 已知约束

- `/voice/intent` 生成路径最长约 25s，务必做等待 UI + 60s 超时。
- `coverUrl` 恒为 null；`uploads` 恒为空数组（本期无上传功能）。
- 决策依赖 Hermes 智能体服务；Hermes 未启动时非缓存请求返回 `no_match`（接口不报错）。
- 无鉴权，仅限内网联调，勿把 Base URL 暴露到公网。
