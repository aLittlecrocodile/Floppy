# Floppy 后端 · Android 客户端对接文档

> 面向 **Android 客户端开发**。讲清楚：调哪个接口、请求/响应长什么样、音频怎么播、
> 中文链接怎么处理、生成要不要等。示例用 Kotlin（OkHttp/Retrofit + ExoPlayer），
> 可直接照搬。
>
> Base URL：本地 `http://127.0.0.1:8000`；上云后换成后端给的公网地址（HTTPS 优先）。
> 所有请求/响应均为 `application/json; charset=utf-8`。当前 MVP 无登录鉴权，`user_id` 自定义传入。

---

## 0. 一句话理解

App 给后端发**一句自然语言**（用户想听什么），后端返回**一个可播放的音频地址**。
用户可以用「文字输入框」或「语音」两种方式说话：

| 输入方式 | 用哪个接口 | 形态 |
|---|---|---|
| **文字输入框** | `POST /demo/chat` 或 `POST /agent/decide` | 普通 HTTP，返回音频 URL |
| **语音对话** | `WebSocket /voice/ws` | 流式，边说边识别边播（另见 `voice_dialog_ws.md`） |

本文档讲**文字输入**这条（HTTP）。语音那条看 `docs/contracts/voice_dialog_ws.md`。

---

## 1. 最快接入：文字 → 音频（演示用）

### `POST /demo/chat`

适合快速跑通：发一句话，**后端同步处理完**（命中缓存或现场生成），直接返回可播 URL，
**客户端无需轮询**。内部用固定演示画像，正式版请用第 2 节带 `user_id` 的接口。

**请求体：**
```json
{ "request_text": "放一段海边呼吸冥想，10分钟" }
```

**响应体（关键字段）：**
```json
{
  "action": "play_asset",
  "audio_url": "http://127.0.0.1:8000/audio/ondemand/prewarm_user/海边呼吸冥想.mp3",
  "asset": {
    "id": "aud_xxx",
    "type": "meditation",
    "title": "海边呼吸冥想",
    "duration_sec": 600,
    "playback_url": "http://127.0.0.1:8000/audio/ondemand/prewarm_user/海边呼吸冥想.mp3"
  },
  "hit": true,
  "job_id": null
}
```

| 字段 | 含义 | 客户端怎么用 |
|---|---|---|
| `action` | `play_asset` / `generate_job` / `no_match` | demo 接口一般直接是 `play_asset` |
| `audio_url` | 可播放地址 | **直接喂给播放器**（注意第 4 节中文编码） |
| `asset.title` | 标题（中文） | 显示在界面/做封面标题 |
| `asset.duration_sec` | 时长（秒） | 显示进度条总长 |
| `hit` | 是否命中缓存 | true=秒回；false=刚生成的 |

**Kotlin（OkHttp）示例：**
```kotlin
val client = OkHttpClient()
val body = """{"request_text":"放一段海边呼吸冥想，10分钟"}"""
    .toRequestBody("application/json; charset=utf-8".toMediaType())
val req = Request.Builder()
    .url("$BASE_URL/demo/chat")
    .post(body)
    .build()

client.newCall(req).enqueue(object : Callback {
    override fun onResponse(call: Call, resp: Response) {
        val json = JSONObject(resp.body!!.string())
        val audioUrl = json.optString("audio_url")   // 可能为 null
        val title = json.getJSONObject("asset").getString("title")
        runOnUiThread { play(audioUrl, title) }       // 见第 3 节播放
    }
    override fun onFailure(call: Call, e: IOException) { /* 重试/提示 */ }
})
```

> 演示阶段客户端只接这一个接口就能跑通「输入文字 → 播音频」。

---

## 2. 正式接入：带用户画像（推荐）

正式版用 `user_id` 关联用户画像，决策更准，且生成是**异步**的（不阻塞 UI）。

### 步骤 A：建/更新画像（首次或设置页）

`PUT /users/{user_id}/profile`，字段都可选：
```json
{
  "audio_type_preferences": ["meditation", "story"],
  "voice_preferences": ["warm_female"],
  "duration_preference_min": 15,
  "stress_level": "high",
  "mood_tags": ["anxiety_relief"]
}
```

### 步骤 B：发一句话拿决策

`POST /agent/decide`
```json
{ "user_id": "u_123", "request_text": "讲个关于外婆院子和老槐树的助眠故事", "generation_allowed": true }
```

响应的 `action` 决定客户端下一步：

| `action` | 含义 | 客户端怎么做 |
|---|---|---|
| `play_asset` | 命中已有/已生成的音频 | 直接播 `asset.playback_url`（**结束**） |
| `generate_job` | 没现成的，后端正在生成 | 拿 `job_id`，**轮询**步骤 C 直到完成 |
| `no_match` | 没匹配上也没生成 | 提示用户换个说法 |

```jsonc
// play_asset 响应（直接播）
{ "action": "play_asset", "asset": { "playback_url": "...", "title": "...", "duration_sec": 600 } }

// generate_job 响应（要轮询）
{ "action": "generate_job", "job_id": "job_abc123", "asset": null }
```

### 步骤 C：轮询生成结果（仅 `generate_job` 需要）

`GET /generation-jobs/{job_id}`，每 1~2 秒一次，直到 `status` 为 `succeeded` 或 `failed`：
```json
{ "id": "job_abc123", "status": "succeeded", "asset": { "playback_url": "...", "title": "...", "duration_sec": 900 } }
```

- `status` 取值：`queued` / `generating` / `succeeded` / `failed`
- **首次生成真人声约 10~25 秒**，期间显示 loading；之后**同一句需求会直接走 `play_asset`**（命中缓存）。
- 建议最多轮询 ~30 次（约 60 秒）后超时提示。

**Kotlin 轮询伪代码：**
```kotlin
suspend fun resolveAudio(userId: String, text: String): Asset? {
    val decide = post("/agent/decide",
        mapOf("user_id" to userId, "request_text" to text, "generation_allowed" to true))
    when (decide.getString("action")) {
        "play_asset" -> return decide.asset()
        "no_match"   -> return null
        "generate_job" -> {
            val jobId = decide.getString("job_id")
            repeat(30) {
                delay(2000)
                val job = get("/generation-jobs/$jobId")
                when (job.getString("status")) {
                    "succeeded" -> return job.asset()
                    "failed"    -> return null
                }
            }
            return null  // 超时
        }
    }
    return null
}
```

---

## 3. 音频播放（ExoPlayer）

后端返回的是标准 mp3/wav 的 HTTP URL，用 **ExoPlayer** 流式播放即可（不要等整段下载）：

```kotlin
val player = ExoPlayer.Builder(context).build()
val safeUrl = encodeAudioUrl(audioUrl)             // 见第 4 节，必须先编码
player.setMediaItem(MediaItem.fromUri(safeUrl))
player.prepare()
player.play()
// 进度：player.currentPosition / asset.duration_sec*1000
```

> `MediaPlayer` 也行，但 ExoPlayer 对长音频缓冲、进度控制更稳，睡前音频普遍 10~20 分钟。

---

## 4. ⚠️ 中文 URL 必须编码（最容易踩的坑）

生成的音频文件名是**中文**（如 `海边呼吸冥想.mp3`），返回的 URL 形如：
```
http://host/audio/ondemand/prewarm_user/海边呼吸冥想.mp3
```

Android 的 HTTP 客户端/ExoPlayer **不会自动**对中文路径做百分号编码，直接用可能 **400/404**。
播放前必须对**路径部分**编码（不要整条 encode，否则 `://` `/` 也被转义）：

```kotlin
fun encodeAudioUrl(raw: String): String {
    val u = java.net.URL(raw)
    // 只对 path 的每一段编码，保留分隔符
    val encodedPath = u.path.split("/").joinToString("/") {
        java.net.URLEncoder.encode(it, "UTF-8").replace("+", "%20")
    }
    return "${u.protocol}://${u.authority}$encodedPath"
}
// http://host/audio/ondemand/prewarm_user/%E6%B5%B7%E8%BE%B9%E5%91%BC%E5%90%B8%E5%86%A5%E6%83%B3.mp3
```

> 用 OkHttp 的 `HttpUrl.parse()` 或 Retrofit `@Url` 也能正确处理，关键是**别把已编码的再编码一次**。

---

## 5. 文字 vs 语音，客户端怎么选

- **文字输入框** → 本文档第 1/2 节（HTTP）。简单、无需音频权限。
- **语音对话**（按住说话、边说边播、可打断）→ WebSocket `/voice/ws`，协议见
  `docs/contracts/voice_dialog_ws.md`（已含 Android 采集 PCM、流式播放、打断的要点）。

两条路最终都汇到同一套决策逻辑，后端音频资源/缓存共用。客户端可以两个入口都做。

---

## 6. 字段速查

**AudioAsset（命中或生成出的音频）：**
| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 资产 ID |
| `type` | string | `meditation`/`story`/`white_noise`/`music`/`asmr`/`podcast_digest` |
| `title` | string | 中文标题（做封面/列表用） |
| `duration_sec` | int | 时长（秒） |
| `playback_url` | string | 播放地址（**先编码再播**） |

**画像可选字段（PUT profile）：**
`audio_type_preferences`、`voice_preferences`、`background_preferences`、
`duration_preference_min`(5~60)、`stress_level`/`anxiety_level`(`low`/`medium`/`high`)、`mood_tags`。

---

## 7. 联调清单

1. 后端地址能通：`GET /health` 返回 `{"status":"ok"}`。
2. 文字接口：`POST /demo/chat` 发一句中文 → 拿到 `audio_url` → 编码后能播。
3. 正式链路：建画像 → `/agent/decide` →（命中直接播 / 生成则轮询 job）。
4. 中文 URL 编码后无 404。
5. 上云后把 Base URL 换成公网 HTTPS；如遇跨域由后端配 CORS（HTTP 客户端一般不受同源限制，WebView 才需要）。

> 完整 HTTP 接口清单见 `docs/frontend/backend_api_reference.md`；后端启动见 `docs/STARTUP.md`。

