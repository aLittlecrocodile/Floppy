# Floppy Backend MVP

工程级 MVP，覆盖 Floppy 后端与算法主链路：

- 音频资产库：SQLite 元数据 + 本地对象存储目录，接口上可替换为 TOS/OSS/S3。
- 用户画像：冷启动问卷 + 轻量行为画像。
- 推荐算法：规则召回、标签匹配、向量近似、可解释重排、生成兜底。
- 生成缓存：归一化请求、精确缓存、近似缓存、按需生成入库。
- 音频生成：本地 deterministic WAV provider，用于验证工程链路；后续替换真实 TTS/音乐 provider。
- 睡前脚本：生成带 MiniMax `<#x#>` 停顿标记的故事、冥想、ASMR 脚本，并入库保存 hash。
- Provider 抽象：默认本地 provider，可通过环境变量切换 MiniMax T2A skeleton。
- 事件闭环：播放、反馈、生成事件入库，为推荐优化提供数据。

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

默认 Agent runtime 是 Hermes，需要先启动 Hermes Agent API Server：

```bash
export FLOPPY_AGENT_RUNTIME=hermes
export FLOPPY_HERMES_BASE_URL=http://127.0.0.1:8642
export FLOPPY_HERMES_API_KEY=change-me-local-dev
uvicorn floppy_backend.main:app --reload
```

如果只想本地开发、不依赖 Hermes，可显式切回 LangGraph fallback：

```bash
FLOPPY_AGENT_RUNTIME=local uvicorn floppy_backend.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

初始化种子音频：

```bash
curl -X POST http://127.0.0.1:8000/admin/seed
```

创建或更新画像：

```bash
curl -X PUT http://127.0.0.1:8000/users/u_demo/profile \
  -H "content-type: application/json" \
  -d '{
    "audio_type_preferences": ["story", "white_noise"],
    "voice_preferences": ["warm_female"],
    "background_preferences": ["rain_soft"],
    "duration_preference_min": 15,
    "stress_level": "high",
    "anxiety_level": "medium",
    "avg_sleep_latency_min": 35,
    "mood_tags": ["anxiety_relief"]
  }'
```

获取推荐：

```bash
curl "http://127.0.0.1:8000/users/u_demo/recommendations?limit=3"
```

请求生成或命中缓存：

```bash
curl -X POST http://127.0.0.1:8000/users/u_demo/generate-audio \
  -H "content-type: application/json" \
  -d '{"request_text":"我想听一个温柔女声讲海边书店的睡前故事，背景有轻微雨声，15分钟"}'
```

工程推荐的生成任务接口：

```bash
curl -X POST http://127.0.0.1:8000/users/u_demo/generation-jobs \
  -H "content-type: application/json" \
  -d '{"request_text":"我想听一个温柔女声讲海边书店的睡前故事，背景有轻微雨声，15分钟","force_generate":true}'
```

查询任务状态：

```bash
curl http://127.0.0.1:8000/generation-jobs/<job_id>
```

## Test

```bash
pytest
```

## MiniMax Provider

默认仍使用本地 tone provider：

```bash
FLOPPY_AUDIO_PROVIDER=local uvicorn floppy_backend.main:app --reload
```

接 MiniMax 前需要准备：

1. MiniMax API Key。
2. 账号有可用余额或企业额度。
3. 先选定 2-3 个中文睡前音色。当前默认是 `Chinese (Mandarin)_Warm_Bestie`。
4. 确认生成音频的商用、缓存、长期存储和分发授权。

启用 MiniMax 同步 T2A：

```bash
export FLOPPY_AUDIO_PROVIDER=minimax
export FLOPPY_MINIMAX_API_KEY="<your_key>"
export FLOPPY_MINIMAX_BASE_URL="https://api.minimaxi.com"
export FLOPPY_MINIMAX_MODEL="speech-2.8-hd"
export FLOPPY_MINIMAX_VOICE_ID="Chinese (Mandarin)_Warm_Bestie"
uvicorn floppy_backend.main:app --reload
```

MiniMax 中文站 API Key 必须使用 `https://api.minimaxi.com`。如果误用英文站 `https://api.minimax.io`，当前 key 可能返回 `invalid api key`。

MiniMax 快速验证：

```bash
export FLOPPY_MINIMAX_API_KEY="<your_key>"
export FLOPPY_MINIMAX_BASE_URL="https://api.minimaxi.com"
.venv/bin/python scripts/minimax_smoke.py
```

当前 MiniMax provider 已支持短文本 T2A HTTP，也提供 T2A Async 创建任务、查询状态和下载文件能力。默认短文本走 HTTP，超过 `FLOPPY_MINIMAX_SYNC_MAX_CHARS` 会走 async 等待并下载。

### MiniMax Hubless ASMR Workflow

已提供不依赖 MiniMax Hub App/MCP 的直连工具层：`floppy_backend.services.minimax_hubless.MiniMaxHublessAudioTools`。

它覆盖 `asmr-ambient` workflow 里关键的 MCP 语义：`get_voice_id`、`audio_generation`、`audios_batch_generation`、`music_generation_instrumental`、`audio_meta` 和 `ffmpeg_mix`。背景音乐使用 MiniMax `music_generation` 的 `is_instrumental=true`，混音使用本地 `ffmpeg`。

启用 agent 生成任务里的 TTS + 纯音乐混音：

```bash
export FLOPPY_AUDIO_PROVIDER=minimax
export FLOPPY_MINIMAX_API_KEY="<your_key>"
export FLOPPY_MINIMAX_BASE_URL="https://api.minimaxi.com"
export FLOPPY_MINIMAX_ENABLE_MUSIC_MIX=true
```

只跑 Hubless smoke：

```bash
.venv/bin/python scripts/minimax_hubless_smoke.py
```

详细映射见 `docs/contracts/minimax_hubless_audio_tools.md`。

## Engineering Notes

当前 MVP 使用标准库 `sqlite3`，避免早期引入重 ORM。模块边界按未来服务拆分设计：

- `floppy_backend.repositories`：数据访问。
- `floppy_backend.services.profile`：用户画像。
- `floppy_backend.services.recommendation`：推荐召回和排序。
- `floppy_backend.services.generation`：缓存命中、生成任务、入库。
- `floppy_backend.services.script`：睡前脚本生成、停顿标记和脚本 hash。
- `floppy_backend.services.agent_runtime`：Agent runtime 统一入口，默认装配 Hermes。
- `floppy_backend.services.hermes_agent`：Hermes 决策适配器，Floppy 本地执行 workflow。
- `floppy_backend.services.agent_graph`：可选本地 LangGraph fallback。
- `floppy_backend.providers.audio`：音频生成 provider 抽象。

真实生产替换点：

- `LocalAudioProvider` -> 火山/其它 TTS 和音频生成服务。
- `LocalFileStorage` -> TOS/OSS/S3 + CDN + 签名 URL。
- SQLite vector cosine -> pgvector / VikingDB / Milvus / Qdrant。
- in-process generation -> Celery/RQ/云队列异步 worker。

当前 `/generate-audio` 为了本地端到端验证采用同步生成，但数据模型已经保留 `generation_jobs`。接真实 TTS 后应改为：

1. API 创建 `queued` job。
2. Worker 消费队列并更新任务状态。
3. 客户端轮询 job 或通过 WebSocket/Push 接收完成通知。
4. 生成成功后写入音频资产库，后续同类请求走缓存命中。

当前已经提供 `/users/{user_id}/generation-jobs` 和 `/generation-jobs/{job_id}`，本地用 FastAPI `BackgroundTasks` 模拟 worker。生产环境应把 `BackgroundTasks` 替换为持久队列，避免进程重启导致 queued job 丢失。
