# Unwind 桌面前端对接契约（打工小人 ↔ 后端）

前后端分离后，桌面端（Swift 6 + AppKit 原生「打工小人」，仓库 [aLittlecrocodile/unwind](https://github.com/aLittlecrocodile/unwind) 的 `native/`）只依赖本文档描述的接口面。改动任何一侧前先对照这里。

> 早期 Electron + React 原型已下线，不再维护；本文档已随之改写为原生客户端的契约。

**文档分工**：本文 = 桌面端实际用到的最小契约（怎么调、拿到什么、该做什么）；全量 API 参考见 [backend_api_reference.md](backend_api_reference.md)；语音 WS 的逐事件详规见 [../contracts/voice_dialog_ws.md](../contracts/voice_dialog_ws.md)。

## 0. 总览

原生进程直连后端，`URLSession`/`URLSessionWebSocketTask` 没有跨域概念，不需要任何代理层（这点和网页渲染进程不同）。桌宠（`PetWindowController`）只用文字对话和语音两条路径；"喘口气"完整主窗（`UnwindWindowController`）是**原生重实现**，不是加载 `/showcase` 网页，因此直接消费了更多接口：

| 用途 | 接口 | 调用方（`native/Sources/UnwindApp/`） |
| --- | --- | --- |
| 文字对话（决策智能体） | `POST /showcase/chat` | `Networking/BackendClient.swift` |
| 按住/点按说话 | `WS /voice/ws?user_id=` | `Networking/VoiceClients.swift`（`PushToTalkClient`） |
| 语音通话（连续双工） | `WS /voice/realtime?user_id=` | `Networking/VoiceClients.swift`（`CallWindowController` 用） |
| 技能矩阵 | `GET /showcase/skills` | `BackendClient.skills()` |
| 场景 nudge 文案 | `GET /showcase/nudge?scenario=` | `BackendClient.nudge()` |
| 推荐 | `GET /users/{id}/recommendations?limit=` | `BackendClient.recommendations()` |
| 生成任务轮询 | `GET /generation-jobs/{id}` | `BackendClient.generationJob()` |
| remix 任务轮询 | `GET /remix-jobs/{id}` | `BackendClient.remixJob()` |
| 音频文件 | `GET /audio/{object_key}` | `AudioCoordinator`（`AVAudioPlayer`，响应里给的都是完整 URL） |
| 健康检查 | `GET /health` | `BackendClient.health()`，启动时探活 |

后 5 项（技能矩阵/nudge/推荐/两种任务轮询）字段级契约不在本文范围，去 [backend_api_reference.md](backend_api_reference.md) 对应小节查；这里只负责标注"桌面端确实在用"。

- **Base URL**：`http://127.0.0.1:8000`（写死在 `BackendClient` 默认参数里；原生进程直连本机回环地址，没有网页的跨域/证书限制）。
- **兼容性约定**：响应字段只增不改；所有可空字段都可能为 `null`；遇到不认识的字段/卡片类型**静默忽略**，不要报错。

## 1. 文字对话 `POST /showcase/chat`

请求（JSON）：

```jsonc
{
  "request_text": "来点雨声",        // 必填，去空白后 ≥2 字符，否则 400
  "current_asset_id": "ast_xxx"      // 可选：当前正在播的资产 id，remix 场景需要
}
```

不需要传 `user_id`——showcase 通道固定为演示用户。多用户形态请改走 `POST /agent/decide`（见全量参考 §6）。

响应是 `AgentDecideResponse`。桌面端需要消费的字段（其余字段是决策轨迹可视化用的，桌宠可忽略）：

```ts
interface UnwindReply {
  action: 'chat' | 'play_asset' | 'generate_job' | 'remix_current' | 'no_match'
  reply: string | null            // 小人要说的话（气泡文案）
  reply_audio_url: string | null  // reply 的 TTS 语音，完整 URL
  selected_skill: string | null   // 命中的技能名（打点/调试用）
  asset: { title?: string; playback_url?: string | null } | null  // 要播放的环境音
  skill_card: Record<string, unknown> | null  // 结构化卡片，见 §2
  job_id: string | null           // generate_job：轮询 GET /generation-jobs/{job_id}
  timer_sec: number | null        // 睡眠定时器：前端自己倒计时
  fade_out: boolean | null        //   到点是否淡出（默认按 true 处理）
}
```

**前端行为规范（按 `action` 分支）**：

| action | 前端该做什么 |
| --- | --- |
| `chat` | 气泡展示 `reply`；有 `reply_audio_url` 就自动播；有 `skill_card` 按 §2 渲染 |
| `play_asset` | 播 `asset.playback_url`，气泡展示 `reply`。**此时 `reply_audio_url` 恒为 `null`**（后端保证语音和音轨不叠播），不要自己再合成 |
| `generate_job` | 展示 `reply`（"我去做一段…"），拿 `job_id` 轮询 `GET /generation-jobs/{job_id}`（建议 2s 间隔），`status=succeeded` 后从返回的 asset 播放 |
| `remix_current` | 同 `play_asset`（同步 remix 直接带 `asset`），带 `remix_job_id` 时轮询 `GET /remix-jobs/{id}` |
| `no_match` | 展示 `reply` 的婉拒/引导文案即可 |

仪式类技能（心情打卡/烦恼寄存/感恩/偏好/定时器）和内搜**都以 `action: "chat"` + `skill_card` 的形式返回**，客户端不需要新增分支。

`timer_sec` 可能搭在任何带播放的响应上：前端起倒计时，到点停止播放（`fade_out` 为真时先做几秒音量渐弱）。后端只记事件，不会替你停。

**错误处理**：`request_text` 过短返回 `400 {"detail": "..."}`；后端整体不可用时桌面端应给"后端没起"的友好文案（当前实现：15s 超时 + 人话提示）。

## 2. skill_card 卡片类型

`skill_card.type` 决定渲染方式。当前会出现的类型：

| type | 关键字段 | 场景 |
| --- | --- | --- |
| `ritual_receipt` | `title`, `lines[]`（回执文案行） | 心情打卡/烦恼寄存/感恩/偏好更新/定时器的落库回执 |
| `neisou_answer` | `question`, `answer`, `owner`, `results[] {title,url,snippet}` | 内搜快答（食堂/班车/流程） |
| `neisou_results` | `results[] {title,url,snippet}` | 内搜多结果列表 |
| `weekly_draft` | `rows[] {section,content}` | 周报代笔 demo |
| `okr_progress` | `objective`, `krs[] {name,progress}` | OKR 重构 demo |

桌宠形态可以只渲染 `reply` 而忽略卡片（当前实现）；Unwind 主窗按类型出卡。**未知 type 一律忽略**。

## 3. 语音对话 `WS /voice/ws`

连接：`ws://127.0.0.1:8000/voice/ws?user_id=<id>`，可选 `&voice_style=`；服务端设置了 `FLOPPY_VOICE_WS_TOKEN` 时必须带 `&token=`（对不上直接 close 4401）。

**上行（客户端 → 服务端）**

| 帧 | 含义 |
| --- | --- |
| 二进制帧 | 裸 PCM：16kHz / 单声道 / s16le。建议 ~200ms 一帧（3200 采样 = 6400 字节） |
| `{"type":"utterance_end"}` | 本句说完，触发识别+回复；**连接保持**，多轮共享对话历史 |
| `{"type":"stop"}` | 结束整个会话 |

第一帧音频会隐式开启一轮 utterance，不需要显式 start。

**下行（服务端 → 客户端）**

文本帧统一结构 `{type, session_id, user_id, turn_id, seq, text, is_final, created_at}`（`audio_asset` 额外带 `url`、`audio_type`）：

| type | 含义 / 前端动作 |
| --- | --- |
| `session_started` | 会话就绪 |
| `user_text` | ASR 结果；`is_final=false` 是流式中间稿（气泡实时上屏），`true` 为定稿 |
| `assistant_text` | 小人回复的一句话（流式追加到气泡） |
| （二进制帧） | 回复的 TTS mp3 分块。简单做法：攒到 `turn_end` 拼 Blob 一次性播（桌面端现行）；要更低延迟可用 MSE 流播 |
| `audio_asset` | 要播放的环境音：`url`（完整地址）+ `audio_type` + `text`（展示名）。交给常驻 `<audio>`，并给出可停止的 UI |
| `turn_end` | 本轮结束：播放攒下的 TTS、解除"思考中"状态 |
| `error` | `text` 是错误说明。凭证/配置缺失时会在连上后立刻收到一条并被 close 1011——前端要把这种"语音链路没配好"降级成文字提示，不要重连风暴 |

**依赖注意**：`/voice/ws` 需要后端配好火山 ASR + MiniMax TTS 凭证（`backend/.env`），没配时文字链路（§1）完全可用，语音会走上面的 error 降级。

## 4. 音频播放约定

- `asset.playback_url`、`reply_audio_url`、`audio_asset.url` 都是**完整 URL**（由 `FLOPPY_PUBLIC_BASE_URL` 拼出，默认 `http://127.0.0.1:8000`），`<audio src>` 直接用，无鉴权。
- 同一时刻至多一路"语音"（TTS）+ 一路"环境音"。环境音是长内容：**必须给用户可见的播放状态和停止入口**（桌宠现行：「♪ 曲名 · 停」胶囊）。
- 新环境音到来时先 `pause()` 旧的再播新的，避免叠音。

## 5. 联调与排障

```bash
# 起后端
cd backend && source .venv/bin/activate
uvicorn floppy_backend.main:app --host 127.0.0.1 --port 8000

# 冒烟：文字链路
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/showcase/chat \
  -H 'content-type: application/json' \
  -d '{"request_text":"来点雨声"}' | python3 -m json.tool
```

- 小人不回话 → 先 `GET /health`；再看 `action`/`reply` 是否正常返回。
- 有字没声 → `reply_audio_url` 为 `null` 说明 TTS 未配置（`FLOPPY_MINIMAX_API_KEY`），属正常降级。
- 内搜答不上 → 需要厂内网络 + `~/.config/uuap` 下的 ugate token，缺了会退回预置演示答案。

---

维护约定：后端改到本文覆盖的任何接口时，同一个 PR 里更新本文；桌面端消费字段以 `native/Sources/UnwindApp/Models/BackendModels.swift` 为准，两边不一致时以本文为仲裁。
