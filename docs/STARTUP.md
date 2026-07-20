# Unwind 后端启动指南

> 给接手的 agent / 同事：如何在本机或服务器启动 Unwind 后端并完成前端联调。
> 当前仓库包含 Unwind 后端、体验页和音频生成链路；当前对接文档从 `docs/README.md` 开始。

## 0. 这是什么

Unwind 是 AI 减压陪伴后端（FastAPI）。能力：

- **智能体决策**（`/agent/decide`）：理解用户需求 → 命中已有音频直接播 / 未命中则**智能体提炼内容指令 → workflow 生成真人声**。
- **实时语音对话**（WebSocket `/voice/ws`）：火山 ASR → 对话 LLM → MiniMax 流式 TTS，支持「听故事/放雨声/冥想」音频意图。
- **缓存复用**：生成产物按 `prompt_hash` 入库，同需求第二次直接命中、不再生成。

## 1. 一次性准备

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

依赖在 `pyproject.toml`，已含 `websockets` / `httpx`（语音链路需要）。

## 2. 环境变量（关键）

**`.env` 不在 git 里**（`.gitignore` 已忽略），需在项目根目录自备。模板见 `.env.example`。
最小可用配置（智能体生成 + 语音对话都要 LLM/TTS/ASR 三个 key）：

```bash
# 音频生成 provider：真人声走 minimax
FLOPPY_AUDIO_PROVIDER=minimax
FLOPPY_MINIMAX_API_KEY=<minimax_key>          # 中文站，必须 api.minimaxi.com
FLOPPY_MINIMAX_BASE_URL=https://api.minimaxi.com

# 查询规划 + 内容指令 + 写脚本 共用这套 LLM 凭证
FLOPPY_QUERY_PLANNER=ai
FLOPPY_QUERY_PLANNER_API_KEY=<llm_key>
FLOPPY_QUERY_PLANNER_BASE_URL=https://oneapi-comate.baidu-int.com/v1
FLOPPY_QUERY_PLANNER_MODEL=DeepSeek-V4-Flash

# 对话 LLM（不填则复用 query_planner_*）
FLOPPY_DIALOG_LLM_API_KEY=<llm_key>

# 实时语音对话才需要：火山流式 ASR
FLOPPY_VOLC_ASR_API_KEY=<volc_key>
```

| 变量 | 默认 | 说明 |
|---|---|---|
| `FLOPPY_AUDIO_PROVIDER` | `local` | **真人声必须设 `minimax`**；`local` 只出哔声占位 |
| `FLOPPY_DIRECTIVE_PLANNER_ENABLED` | `true` | 智能体「先想内容要点再生成」总开关；无 LLM key 时自动退化为模板 |
| `FLOPPY_ENFORCE_GENERATION_BUDGET` | `false` | **已关闭**每日生成额度限制（开发/预热用）；上线如要限流置 `true` |
| `FLOPPY_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | **上云后改成公网地址**，否则返回的 `playback_url` 前端访问不到 |
| `FLOPPY_VOICE_WS_TOKEN` | 空 | 语音 WS 接入凭证；为空则不校验 token |
| `FLOPPY_DATABASE_PATH` | `data/floppy.db` | SQLite，不在 git，需随机器保留 |
| `FLOPPY_STORAGE_DIR` | `storage/audio` | 音频文件根目录，不在 git，需随机器保留 |

完整字段见 `floppy_backend/config.py`（前缀统一 `FLOPPY_`，68 个）。

## 3. 启动

```bash
source .venv/bin/activate
uvicorn floppy_backend.main:app --host 127.0.0.1 --port 8000
```

- 启动时会幂等 seed 真实音频资产（white_noise/music），不阻塞首个请求。
- 健康检查：`curl http://127.0.0.1:8000/health` → `{"status":"ok",...}`
- 浏览器语音 Demo：打开 `http://127.0.0.1:8000/voice`（`voice_ws_token` 为空时 URL 无需带 token）。

上云/对外暴露时：
- `--host 0.0.0.0`，并把 `FLOPPY_PUBLIC_BASE_URL` 设为公网域名/IP。
- 前端跨域：如前端独立域名，需在 `main.py` 加 FastAPI `CORSMiddleware`（当前未配）。

## 4. 数据与缓存（必须随服务器保留）

git 里**只有代码**。下面三样在本地/服务器、不进仓库，迁移机器要一起带上：

- `data/floppy.db` —— 资产/画像/任务记录（缓存命中靠它的 `prompt_hash`）
- `storage/audio/` —— 所有音频文件
  - `real/` 真实白噪音/音乐（26 条）
  - `ondemand/{user_id}/` 智能体生成的真人声缓存（含预热的冥想/故事/播客）
  - `remix/` 混音产物
- `.env` —— 密钥

> 缓存命中靠 DB 的 `prompt_hash`，不扫目录。**DB 和 storage 必须配套迁移**：只带 DB 不带文件→播放 404；只带文件不带 DB→成孤儿。

## 5. 预热缓存（可选）

把 catalog 里的 meditation/story/podcast 用真人声提前生成入库，用户首次问就能命中：

```bash
.venv/bin/python scripts/prewarm_cache.py                       # 全部
.venv/bin/python scripts/prewarm_cache.py --types meditation    # 指定类型
```

幂等：已缓存的会跳过（`⏭️`）。

## 6. 验证联调

- 前端 HTTP 接口：见 `docs/frontend/backend_api_reference.md`
- 实时语音 WS 协议：见 `docs/contracts/voice_dialog_ws.md`（后端运维见 `voice_dialog_ws_backend.md`）
- 智能体如何指挥生成：见 `.claude/skills/floppy-generation/SKILL.md`

快速冒烟（命中缓存应秒回 `play_asset`）：

```bash
curl -s -X POST http://127.0.0.1:8000/agent/decide \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"prewarm_user","request_text":"海边呼吸冥想引导，10分钟","generation_allowed":true}'
```

## 7. 注意

- 当前测试覆盖脚本安全、语音会话、workflow 契约、showcase 页面和后端 smoke 场景；运行 `pytest` 可执行完整测试集。
- 安全/鉴权当前是 PoC 级（无 HTTP 鉴权、WS 用 shared-secret）；上线前需替换为正式登录鉴权。
