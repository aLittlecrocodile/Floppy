# Floppy MiniMax Audio Workflow

更新时间：2026-06-21  
目标：设计 Floppy 如何配合 MiniMax T2A 搭建睡前音频生成工作流/智能体

## 结论

MiniMax 不应被当成“全流程 Agent”，而应作为 Floppy 音频生成工作流中的 TTS/T2A provider。Floppy 自己负责需求理解、脚本生成、缓存、任务状态、质量检查、音频资产管理和推荐；MiniMax 负责把最终脚本合成为音频。

推荐架构：

```text
User Request
  -> Floppy Orchestrator
  -> Request Normalizer
  -> Cache Matcher
  -> Sleep Script Agent
  -> Safety/Quality Guard
  -> MiniMax T2A Provider
  -> Audio Post Processor
  -> Audio Asset Store
  -> Recommendation / Playback
```

## MiniMax 能力边界

根据 MiniMax 官方文档，当前需要重点使用这些接口：

1. T2A HTTP
   - 适合短文本、快速生成、PoC。
   - 可配置模型、音色、语速、音量、音高、输出格式等参数。
   - 单次文本小于 10,000 字符。
   - 文本超过 3,000 字符时官方建议使用 streaming。
   - 支持 `<#x#>` 停顿标记，范围 `[0.01, 99.99]` 秒。

2. T2A Async
   - 适合长文本和睡前长音频。
   - 返回 provider 侧任务信息，后续轮询任务状态，完成后通过文件接口下载音频。
   - 与 Floppy 当前 `generation_jobs` 模型天然匹配。
   - 直接 text 输入最大 50,000 字符。
   - `text_file_id` 输入最大 1,000,000 字符。
   - 查询状态接口最多 10 queries/s。

3. File API
   - `purpose=t2a_async_input` 可上传 txt/zip 作为长文本异步输入。
   - 异步成功后用 `file_id` retrieve/download。
   - MiniMax 下载 URL 有时效，必须及时转存到 Floppy 自己的对象存储。

4. Voice API
   - `POST /v1/get_voice` 可查询当前账号可用系统音色、克隆音色和生成音色。
   - 第一版应把音色沉淀成 Floppy `voice_profile` 配置，不要把 `voice_id` 写死在业务代码里。

官方参考：

- `https://platform.minimax.io/docs/api-reference/speech-t2a-http`
- `https://platform.minimax.io/docs/api-reference/speech-t2a-async-create`
- `https://platform.minimax.io/docs/api-reference/speech-t2a-async-query`
- `https://platform.minimax.io/docs/api-reference/file-management-upload`
- `https://platform.minimax.io/docs/api-reference/file-management-retrieve`
- `https://platform.minimax.io/docs/api-reference/voice-management-get`
- `https://platform.minimax.io/docs/guides/pricing-paygo`

补充深度调研：`docs/minimax_official_deep_research.md`

## Hub Workflow 判断

MiniMax Hub 的 `asmr-ambient` 官方 skill 是成熟的创作工作流，不是可直接部署的后端服务。它的价值在于给 Floppy 提供“助眠音频生产方法论”：

```text
内容类型选择
-> 脚本生成和停顿
-> 音色选择和 TTS
-> 自然音效
-> 背景音乐
-> ffmpeg 混音
-> 试听反馈
-> 导出
```

但生产后端不能照搬：

- Hub skill 依赖 MCP 工具和 MiniMax Hub App 运行时。
- 使用 `.sleep-audio/` 本地目录和 `.sleep-state.json`。
- 每个阶段都要求人工确认。
- 自然音效下载依赖 Playwright 浏览器。
- 预览服务器适合内部调音，不适合睡前用户。

Floppy 应借鉴它的脚本、停顿、音色、自然音效分类、混音和反馈闭环，把这些能力改造成数据库驱动、异步 worker 驱动、可缓存、可观测的服务端 workflow。

## 成本判断

MiniMax T2A 当前按字符计费：

| 模型 | 价格 |
| --- | --- |
| `speech-2.8-turbo` | 60 USD / 1M characters |
| `speech-2.8-hd` | 100 USD / 1M characters |

这意味着：

- 约 5,000 字符的睡前脚本，单条 TTS 成本约 0.30 到 0.50 USD。
- 缓存、近似复用、in-flight 去重和预生成必须作为 P0 能力。
- `generation_jobs` 需要记录 `usage_characters` 和 `estimated_cost_usd`。
- 专属长音频生成要有配额和频控。

## 工作流设计

### 1. 用户请求归一化

输入：

```text
我想听一个温柔女声讲海边书店的睡前故事，背景有轻微雨声，15分钟
```

归一化输出：

```json
{
  "intent": "story",
  "language": "zh-CN",
  "duration_bucket": "10-20min",
  "duration_sec": 900,
  "voice_style": "warm_female",
  "background": "rain_soft",
  "mood": ["gentle", "safe"],
  "content_topic": ["sea", "bookstore", "rain"]
}
```

当前 MVP 已有 `RequestNormalizer`，后续可以把它升级为：

- 规则优先：时长、音色、背景声、音频类型。
- 小模型/LLM 辅助：复杂用户需求解析。
- 输出固定 schema，不能让 Agent 随意扩展字段。

### 2. 缓存匹配

MiniMax 生成前必须先查缓存：

```text
cache_key = hash(normalized_request + script_policy + voice_config)
```

命中策略：

1. 精确命中：直接返回已有音频。
2. in-flight 命中：已有相同请求正在生成，返回同一个 job。
3. 近似命中：如果用户没有强制专属生成，可以返回相似缓存音频。
4. 未命中：进入脚本生成和 MiniMax T2A。

当前 MVP 已经支持精确缓存、近似缓存和 in-flight 去重。

### 3. Sleep Script Agent

这里可以用“智能体”，但它只负责生成睡前脚本，不直接调用 TTS。

输入：

- normalized_request
- 用户画像
- 内容安全规则
- 目标时长
- MiniMax voice_config

输出：

```json
{
  "title": "海边书店的雨夜",
  "script": "...",
  "estimated_duration_sec": 900,
  "style_notes": {
    "speed": "slow",
    "tone": "gentle",
    "arousal_level": "low"
  },
  "safety_tags": ["low_stimulation", "no_medical_claim"]
}
```

脚本生成约束：

- 不能惊吓、恐怖、悬疑强反转。
- 避免冲突强、信息密度高、任务压力强的表达。
- 不做医疗诊断或治疗承诺。
- 不要频繁问用户问题。
- 句子短，停顿自然，节奏慢。
- 结尾逐渐收束，不突然结束。

### 4. 安全和质量检查

TTS 前必须检查脚本：

```text
script_guard(script)
  -> pass / reject / rewrite
```

检查项：

- 是否含惊吓、恐怖、暴力、极端情绪。
- 是否有医疗承诺。
- 是否有过强互动要求。
- 是否过度提及“必须睡着”等压力表达。
- 是否适合目标用户状态。

如果失败：

- 自动改写一次。
- 仍失败则返回安全兜底脚本。

### 5. MiniMax T2A Provider

Provider 层只负责和 MiniMax 通信，不写业务策略。

接口建议：

```python
class MiniMaxTTSProvider(AudioGenerationProvider):
    name = "minimax_t2a"

    def generate(self, normalized, output_path, object_key):
        script = build_sleep_script(normalized)
        if should_use_async(script, normalized):
            return self._generate_async(script, normalized, output_path, object_key)
        return self._generate_sync(script, normalized, output_path, object_key)
```

短文本策略：

```text
script_chars <= threshold
duration_sec <= 180
-> T2A HTTP
```

长文本策略：

```text
script_chars > threshold
duration_sec > 180
-> T2A Async
```

建议 Floppy 默认长音频都走 async，即使 MiniMax 同步接口能跑，也不要让用户请求线程阻塞太久。

### 6. Provider Task 映射

MiniMax async 会有 provider 侧任务状态。Floppy 需要保存映射关系。

建议在 `generation_jobs` 增加字段：

| 字段 | 说明 |
| --- | --- |
| provider_task_id | MiniMax async task id |
| provider_file_id | MiniMax 完成后的 file id |
| provider_status | MiniMax 原始状态 |
| provider_payload | MiniMax 原始响应摘要 |
| script_hash | 最终脚本 hash |
| script_chars | 脚本字符数 |
| estimated_cost | 估算成本 |

当前 MVP 还没有这些字段，下一步接 MiniMax 时应补。

### 7. 音频下载与入库

MiniMax async 完成后：

```text
poll task status
  -> succeeded
  -> retrieve file by file_id
  -> save to storage/audio/...
  -> run postprocess
  -> upsert audio_assets
  -> update generation_jobs.succeeded
```

入库时记录：

- provider = `minimax_t2a`
- model
- voice_id
- speed
- volume
- pitch
- output_format
- script_hash
- content_hash
- latency_ms
- estimated_cost

### 8. 音频后处理

MiniMax 生成音频后仍建议统一后处理：

1. 转码到统一格式，建议 MVP 先用 mp3，内部处理可保留 wav。
2. 响度归一，避免不同 provider 音量差异大。
3. 开头 fade-in，结尾 fade-out。
4. 根据需求混入背景声：雨声、海浪、森林、壁炉。
5. 生成 30 秒 preview，便于推荐和试听。

后处理建议用 `ffmpeg`，不要自己写音频 DSP。

## 智能体边界

建议只做 3 个小 agent/tool，不做大而全 Agent。

### 1. Intent/Request Agent

职责：

- 解析复杂用户需求。
- 输出固定 `NormalizedAudioRequest`。
- 不调用 TTS。

当前可以先用规则实现，复杂时再接 LLM。

### 2. Sleep Script Agent

职责：

- 生成睡前故事、冥想引导、内容转化稿。
- 遵守睡前安全规则。
- 输出固定脚本 schema。

这是最适合用 LLM/Agent 的部分。

### 3. Quality Review Agent

职责：

- 检查脚本是否低刺激、安全、适合睡前。
- 检查 MiniMax 生成后的音频元数据是否异常。
- 不直接决定推荐，只给质量标签和评分。

## API 工作流

### 创建生成任务

```http
POST /users/{user_id}/generation-jobs
```

流程：

```text
1. normalize request
2. calculate cache_key
3. exact cache hit -> succeeded
4. active job hit -> in_flight
5. create queued job
6. background worker starts
7. script agent creates script
8. script guard approves
9. MiniMax T2A starts
10. async task id saved
```

### 查询任务

```http
GET /generation-jobs/{job_id}
```

返回状态：

```text
queued
script_generating
script_reviewing
provider_submitted
provider_processing
postprocessing
succeeded
failed
```

当前 MVP 只有 `queued/generating/succeeded/failed`，MiniMax 接入后建议扩展状态。

## MiniMax PoC 实施计划

### Phase 1: Skeleton

目标：不调用真实 MiniMax，但打通接口结构。

- 新增 `floppy_backend/providers/tts/minimax.py`
- 新增 `MiniMaxTTSProvider`
- 新增配置：
  - `FLOPPY_AUDIO_PROVIDER=minimax`
  - `FLOPPY_MINIMAX_API_KEY`
  - `FLOPPY_MINIMAX_GROUP_ID`
  - `FLOPPY_MINIMAX_MODEL`
  - `FLOPPY_MINIMAX_VOICE_ID`
- 增加 provider factory。
- 测试无 key 时明确失败，不静默 fallback。

### Phase 2: Sync T2A

目标：短脚本真实生成。

- 使用 T2A HTTP。
- 生成 4 条短样本：故事、冥想、内容转化、压力舒缓。
- 保存音频到本地 storage。
- 写入 `audio_assets`。
- 记录 latency 和字符数。

### Phase 3: Async T2A

目标：长脚本真实生成。

- 创建 MiniMax async task。
- 保存 `provider_task_id`。
- 轮询 provider task。
- 下载 file。
- 入库。
- 失败重试和错误码映射。

### Phase 4: Evaluation

目标：判断 MiniMax 是否适合作为主 provider 或高质量 provider。

评估样本：

- 30 秒短故事。
- 2 分钟故事。
- 10 分钟故事。
- 3 分钟冥想。
- 5 分钟内容转化。

记录指标：

- 音质主观评分。
- 睡前适配度。
- 长文本稳定性。
- 延迟。
- 成本。
- 失败率。
- 是否允许缓存和商用播放。

## 和当前 MVP 的改造点

必须改：

- 增加 provider factory。
- 增加 MiniMax provider skeleton。
- 增加脚本生成层，不要把用户原始需求直接丢给 TTS。
- 扩展 `generation_jobs` 保存 provider task 信息。

建议改：

- 增加 `audio_scripts` 表，保存最终脚本和 hash。
- 增加 `tts_eval_runs` 表，保存 PoC 样本评估结果。
- 增加 `ffmpeg` 后处理步骤。
- 增加 provider-specific error mapping。

暂时不改：

- 推荐算法。
- 用户画像结构。
- 音频资产表主结构。
- 现有 in-flight 去重逻辑。

## 默认 MiniMax 参数建议

第一轮先用保守参数，避免过度戏剧化：

```json
{
  "model": "speech-2.8-hd",
  "voice_setting": {
    "voice_id": "<to_be_selected>",
    "speed": 0.85,
    "vol": 1.0,
    "pitch": 0
  },
  "audio_setting": {
    "sample_rate": 24000,
    "bitrate": 128000,
    "format": "mp3",
    "channel": 1
  }
}
```

需要实际试听后调整：

- `speed`: 睡前建议 0.8 到 0.95。
- `pitch`: 不要过高。
- `vol`: 和后处理响度归一配合。
- `voice_id`: 需要选 2 到 3 个温柔女声/男声做样本。

## 风险

1. 把 TTS 当 Agent
   - 风险：业务不可控。
   - 处理：MiniMax 只做 provider，Floppy 控制脚本和流程。

2. 长文本一次性提交
   - 风险：失败后成本高、重试慢。
   - 处理：长文本切片或走 async，保存 provider task。

3. 睡前内容过度戏剧化
   - 风险：不适合入睡。
   - 处理：脚本和 voice 参数都做低刺激约束。

4. 授权不清
   - 风险：缓存和商用播放出问题。
   - 处理：PoC 阶段就确认 MiniMax 生成音频使用权和声音克隆条款。

5. 缺少音频后处理
   - 风险：不同样本音量、开头结尾体验不一致。
   - 处理：统一 ffmpeg 后处理。
