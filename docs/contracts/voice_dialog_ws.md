# 实时语音对话 WebSocket 接口（前端对接）

Floppy 智能体的**实时语音对话**接口。一条 WebSocket 连接承载全双工：客户端上行麦克风音频，服务端下行「识别文本 + 助手文本 + 合成语音」。边说边识别、边回边播，支持说话打断（barge-in）。

> 后端部署、环境变量、联调脚本、安全须知见 [`voice_dialog_ws_backend.md`](./voice_dialog_ws_backend.md)。本文档只讲前端怎么对接。

## 连接

```
ws(s)://<host>/voice/ws?user_id=<user_id>&token=<token>&voice_style=<style>
```

| Query 参数 | 必填 | 说明 |
| --- | --- | --- |
| `user_id` | 建议必填 | App 当前用户 ID，用于下行事件关联和后续持久化 |
| `token` | demo 阶段必填 | 接入凭证（demo 为后端下发的 shared-secret；正式版换成登录 token）。不匹配会以 close code `4401` 断开 |
| `voice_style` | 可选 | 音色风格，如 `warm_female` / `gentle_female` / `warm_male`，缺省走后端默认音色 |

连接成功后即可开始推音频；连接被关闭时 code `4401`=鉴权失败，`1011`=后端配置/上游错误（错误详情会先以一条 `error` 文本帧下发）。

## 上行（客户端 → 服务端）

| 帧类型 | 内容 | 说明 |
| --- | --- | --- |
| **二进制帧** | 原始 PCM 音频分片 | **16kHz / 单声道 / 16bit 小端（PCM s16le）**，建议每 200ms 推一帧 |
| **文本帧** | `{"type":"stop"}` | 结束本次音频流；服务端处理完最后一轮后关闭连接 |

要点：
- 用户开口即持续推 PCM 帧，不要等录完整段。
- **打断（barge-in）**：助手正在播报时，客户端继续推新的语音即可——服务端识别到新的「最终结果」会自动取消正在进行的回复、转而响应新一句。前端在检测到用户开口时应**立即停止本地播放**正在播的助手音频。

## 下行（服务端 → 客户端）

**二进制帧** = TTS 合成音频分片（默认 **mp3**）。按到达顺序拼接，边收边播。

**文本帧** = JSON 事件：

```jsonc
{
  "type": "session_started",
  "session_id": "vs_abc",
  "user_id": "u_demo",
  "turn_id": null,
  "seq": 1,
  "text": null,
  "is_final": true,
  "created_at": "2026-06-27T10:00:00.000000+00:00"
}
{
  "type": "user_text",
  "session_id": "vs_abc",
  "user_id": "u_demo",
  "turn_id": "turn_0001",
  "seq": 2,
  "text": "我今天睡不着",
  "is_final": false,
  "created_at": "2026-06-27T10:00:01.000000+00:00"
}
{
  "type": "assistant_text",
  "session_id": "vs_abc",
  "user_id": "u_demo",
  "turn_id": "turn_0001",
  "seq": 4,
  "text": "别担心，我陪着你。",
  "is_final": false,
  "created_at": "2026-06-27T10:00:02.000000+00:00"
}
{"type": "turn_end", "session_id": "vs_abc", "turn_id": "turn_0001", "seq": 8, "text": null, "is_final": true}
{"type": "error", "session_id": "vs_abc", "turn_id": null, "seq": 9, "text": "<错误信息>", "is_final": false}
```

字段说明：
- `session_id` 是本次 WebSocket 对话 ID；同一连接内保持不变。
- `turn_id` 是一轮用户输入 + 助手回复的 ID；同一句 ASR partial/final 和对应助手回复使用同一个 `turn_id`。
- `seq` 是服务端递增序号；App 可用它做去重、排序和调试。
- `created_at` 是服务端 UTC ISO 时间。
- `user_text.text` 是**累计文本**，不是 delta——前端展示识别字幕时直接用最新值覆盖，不要拼接。
- `user_text.is_final=true` 表示这句识别定稿（此时服务端开始生成回复）。
- `assistant_text` 与该句对应的音频二进制帧大致同时到达，用于字幕；只想播声音可忽略它。

## 一轮对话的事件时序

```
[上行] 持续推 PCM 帧 ...
[下行] user_text(is_final:false) × N        ← 实时识别字幕（覆盖更新）
[下行] user_text(is_final:true)             ← 识别定稿，触发回复
[下行] assistant_text("第一句") + 二进制音频帧 ← 边生成边合成边下发
[下行] assistant_text("第二句") + 二进制音频帧
[下行] turn_end                             ← 本轮播报结束
（用户再次说话 → 重复；说话中打断会取消上一轮）
[上行] {"type":"stop"}                       ← 结束会话
```

## 客户端实现要点（移动 App）

1. **采集**：麦克风采 16k/mono/16bit PCM，每 ~200ms 一帧通过二进制帧发出。多数平台需把默认采样率重采样到 16k。
2. **播放**：收到二进制帧即送入流式音频播放器（mp3 解码后播放），不要等 `turn_end` 才整段播——那样会丢掉低延迟优势。
3. **打断**：用本地 VAD 或「用户开始推音频」作为信号，一旦用户开口就**立即停掉当前助手音频播放**，服务端会同步取消该轮回复。
4. **字幕（可选）**：`user_text` 显示用户说的话，`assistant_text` 显示助手回复，提升可感知度。

## 最小伪代码

```text
ws = connect("wss://host/voice/ws?token=...&voice_style=warm_female")

// 上行
onMicFrame(pcm16k):  ws.sendBinary(pcm16k)        // 每 200ms
onUserStopTalking(): ws.sendText({type:"stop"})   // 结束会话

// 下行
ws.onBinary(bytes):  audioPlayer.feed(bytes)       // 边收边播
ws.onText(json):
  switch json.type:
    "session_started": rememberSession(json.session_id)
    "user_text":      subtitleUser.set(json.text)  // 覆盖更新
    "assistant_text": subtitleBot.append(json.text)
    "turn_end":       markTurnDone()
    "error":          showError(json.text)
```

> 联调可参考 `scripts/voice_ws_client.py`（推 wav 模拟说话、收音频落盘、打印首响延迟）。
