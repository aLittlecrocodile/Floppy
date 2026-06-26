# MiniMax Hubless Audio Tools

目标：把 MiniMax Hub `asmr-ambient` skill 里依赖的音频 MCP 工具，替换为 Floppy 自己持有的 MiniMax API + 本地 ffmpeg/ffprobe 工具层。生产链路不依赖 MiniMax Hub App、本地 Hub gateway 或 Hub MCP server。

## MCP 替换映射

| Hub MCP / 能力 | Floppy 直连实现 | 说明 |
| --- | --- | --- |
| `get_voice_id` | `MiniMaxHublessAudioTools.get_voice_id()` | 优先用本地 `voice_profiles`；需要刷新时调用 MiniMax `POST /v1/get_voice` |
| `audio_generation` | `MiniMaxHublessAudioTools.audio_generation()` | 调用 MiniMax `POST /v1/t2a_v2`，长文本可复用已有 async T2A provider |
| `audios_batch_generation` | `MiniMaxHublessAudioTools.audios_batch_generation()` | 本地循环批量生成，逐条落盘，便于失败重试 |
| `music_generation_instrumental` | `MiniMaxHublessAudioTools.music_generation_instrumental()` | 调用 MiniMax `POST /v1/music_generation`，参数 `is_instrumental=true` |
| `audio_meta` | `MiniMaxHublessAudioTools.audio_meta()` | 本地 `ffprobe` 读取格式、时长、码率、采样率 |
| `ffmpeg` | `MiniMaxHublessAudioTools.ffmpeg_mix()` | 本地 `ffmpeg` 混合人声和背景音乐，自动 loop/trim/fade/limit |
| `AskUserQuestion` | 后端决策 / Agent state | Hub 人工确认机制不搬进生产链路；由 Agent/运营审核决定 |
| `download_audios` | 后端资产库 / 下载 worker | 不再依赖浏览器下载；生成结果立即转存到 Floppy storage |

## Agent 工作流

默认 `/agent/decide` 仍然只调用后端工具，不直接持有 MiniMax key：

```text
/agent/decide
-> GenerationService.enqueue_or_match
-> GenerationService.run_job
-> MiniMaxTTSProvider.generate
-> optional MiniMax music_generation
-> local ffmpeg mix
-> AudioAsset 入库
```

启用 MiniMax 背景音乐混音：

```bash
export FLOPPY_AUDIO_PROVIDER=minimax
export FLOPPY_MINIMAX_API_KEY="<your_key>"
export FLOPPY_MINIMAX_BASE_URL="https://api.minimaxi.com"
export FLOPPY_MINIMAX_ENABLE_MUSIC_MIX=true
export FLOPPY_MINIMAX_MUSIC_MODEL="music-2.6"
```

开关关闭时，行为和原有 MiniMax TTS provider 一致，只生成语音 mp3。开关打开时，同一个生成任务会额外生成 instrumental music，并把最终 mixed mp3 作为 `AudioAsset.object_key`。

## 本地 Smoke

不启动 MiniMax Hub，只用 MiniMax API key：

```bash
export FLOPPY_MINIMAX_API_KEY="<your_key>"
export FLOPPY_MINIMAX_BASE_URL="https://api.minimaxi.com"
.venv/bin/python scripts/minimax_hubless_smoke.py
```

输出文件默认写入：

```text
storage/hubless_smoke/
```

## 依赖

- Python 3.11
- `ffmpeg`
- `ffprobe`
- MiniMax API key
- MiniMax 账号需要有 Speech T2A 与 Music Generation 可用额度
