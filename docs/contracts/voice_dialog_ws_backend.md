# 实时语音对话 — 后端部署与运维

`/voice/ws` 的后端侧文档：链路、环境变量、联调脚本、安全须知。前端对接协议见 [`voice_dialog_ws.md`](./voice_dialog_ws.md)。

## 链路

```
App麦克风 → /voice/ws → 火山流式ASR → 流式对话LLM → MiniMax流式TTS → App扬声器
```

句子级流水线重叠（LLM 出第一句即送 TTS 合成播放），支持 barge-in（新最终识别取消进行中的回复）。

实现文件：
- `floppy_backend/main.py` — `@app.websocket("/voice/ws")` 端点
- `floppy_backend/services/voice_session.py` — 全双工编排 + barge-in
- `floppy_backend/providers/volc_asr.py` — 火山大模型流式 ASR（二进制帧协议）
- `floppy_backend/services/dialog_llm.py` — 流式对话 LLM（复用 query planner 配置）
- `floppy_backend/providers/minimax_stream_tts.py` — MiniMax WebSocket 流式 TTS

## 音频格式约定

| 方向 | 默认格式 | 配置项 |
| --- | --- | --- |
| 上行（识别） | PCM 16k/mono/16bit | `FLOPPY_VOLC_ASR_SAMPLE_RATE` |
| 下行（合成） | mp3 | `FLOPPY_MINIMAX_SAMPLE_RATE` / `_BITRATE` / `_CHANNEL` |

上行格式由火山 ASR 决定，**必须** 16k PCM；下行格式按 App 播放器能力，PoC 默认 mp3，联调时可改。

## 所需环境变量

```bash
# 对话 LLM（复用 query planner 配置，或单独覆盖）
export FLOPPY_QUERY_PLANNER_API_KEY="<llm_key>"        # 或 FLOPPY_DIALOG_LLM_API_KEY
export FLOPPY_QUERY_PLANNER_BASE_URL="https://..."     # OpenAI 兼容
export FLOPPY_QUERY_PLANNER_MODEL="DeepSeek-V4-Flash"
# 火山流式 ASR
export FLOPPY_VOLC_ASR_API_KEY="<api_key>"
# 或旧版 app/access 双 Key:
# export FLOPPY_VOLC_ASR_APP_KEY="<app_key>"
# export FLOPPY_VOLC_ASR_ACCESS_KEY="<access_key>"
export FLOPPY_VOLC_ASR_RESOURCE_ID="volc.bigasr.sauc.duration"
# MiniMax 流式 TTS
export FLOPPY_MINIMAX_API_KEY="<minimax_key>"
export FLOPPY_MINIMAX_STREAM_MODEL="speech-2.6-turbo"
# WS 鉴权（PoC）
export FLOPPY_VOICE_WS_TOKEN="<shared-secret>"
```

## 联调

```bash
# 1. 单独验证 TTS 流式
.venv/bin/python scripts/minimax_stream_tts_smoke.py
# 2. 单独验证 ASR 流式（喂 16k wav）
.venv/bin/python scripts/volc_asr_smoke.py sample_16k.wav
# 3. 启服务
.venv/bin/uvicorn floppy_backend.main:app --port 8000
# 4. 全链路（推 wav 模拟说话，收回复音频，打印首响延迟）
.venv/bin/python scripts/voice_ws_client.py sample_16k.wav --token <shared-secret>
```

## 待确认 / 风险

- 火山 `bigmodel sauc` 的二进制帧/字段细节按公开文档与示例实现，真实凭证下需用 `volc_asr_smoke.py` 验证；若 `resource_id` 或返回结构有出入，以火山控制台为准调整 `volc_asr.py`。
- MiniMax WS 鉴权按 `Authorization: Bearer` header 实现；若 smoke 报 401，改为 query token。
- `/voice/ws` 当前仅 shared-secret，**生产必须接平台鉴权**。

## ⚠️ 上线前安全须知

`/voice/ws` 目前的 `token` 是**共享密钥（shared-secret）**，只够内部联调 / demo：

- 它只能挡住「不知道密钥的陌生人」，**无法识别具体是哪个用户**，也无法按用户限流 / 计费 / 封禁。
- 密钥写在客户端，一旦泄露等于人人可用，且每次对话都会真实消耗 **火山 ASR + 对话 LLM + MiniMax TTS** 三套付费 API。

因此：

1. **demo / 联调阶段务必只在本地或内网受控环境运行，切勿把该端点暴露到公网生产环境**，以免被刷量、刷爆账单或拖垮服务。
2. 正式对外上线前，必须把 `voice_ws` 的 `token` 校验替换为**接入 App 真实登录体系的鉴权**（百度统一身份，或自建 JWT/OAuth）：后端验签后解出 `user_id`，据此做按用户限流与计费，拒绝未登录请求。
