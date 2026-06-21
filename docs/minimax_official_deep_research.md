# MiniMax Official Deep Research

更新时间：2026-06-21  
范围：MiniMax 官网、API Platform、Hub Skill 与 Floppy 助眠音频工作流适配性调研

## 结论

用户提到的 `mixmax` 这里按 MiniMax 理解。MiniMax 这套工作流确实成熟，但要拆成两层看：

1. MiniMax Hub / Skill
   - 适合当作“创作工作流参考”和内部运营工具参考。
   - 不适合直接作为 Floppy 生产后端，因为它依赖本地目录、MCP 工具、人工确认和桌面 Hub 运行时。

2. MiniMax API Platform
   - 适合直接接入 Floppy 后端。
   - 重点能力是 T2A HTTP、T2A Async、File Upload/Retrieve、Get Voice、系统音色和后续声音克隆/声音设计。

推荐策略：借鉴 Hub Skill 的内容生产方法论，用 MiniMax API Platform 做可观测、可缓存、可替换的 TTS provider。Floppy 不应该把 MiniMax Hub 当成主 Agent，而应该自己持有编排、状态、缓存、脚本、质检、入库和推荐。

## 官方资料

- MiniMax API 文档索引：`https://platform.minimax.io/docs/llms.txt`
- T2A HTTP：`https://platform.minimax.io/docs/api-reference/speech-t2a-http`
- Async Long TTS Guide：`https://platform.minimax.io/docs/guides/speech-t2a-async`
- T2A Async Create：`https://platform.minimax.io/docs/api-reference/speech-t2a-async-create`
- T2A Async Query：`https://platform.minimax.io/docs/api-reference/speech-t2a-async-query`
- File Upload：`https://platform.minimax.io/docs/api-reference/file-management-upload`
- File Retrieve：`https://platform.minimax.io/docs/api-reference/file-management-retrieve`
- File Retrieve Content：`https://platform.minimax.io/docs/api-reference/file-management-retrieve-content`
- Get Voice：`https://platform.minimax.io/docs/api-reference/voice-management-get`
- System Voice ID List：`https://platform.minimax.io/docs/faq/system-voice-id`
- Pay as You Go Pricing：`https://platform.minimax.io/docs/guides/pricing-paygo`
- Hub Skill 页面：`https://hub.minimaxi.com/skill/asmr-ambient`
- 已导出官方 skill：`/Users/aooway/Downloads/asmr-ambient.zip`

## 官网能力拆解

### 1. T2A HTTP

适合短文本、试听、低延迟生成。

关键信息：

- Endpoint：`POST https://api.minimax.io/v1/t2a_v2`
- 支持同步非流式和流式输出。
- 文本长度要求小于 10,000 字符。
- 文本超过 3,000 字符时，官方建议使用 streaming。
- 支持 `<#x#>` 停顿标记，范围 `[0.01, 99.99]` 秒，最多两位小数。
- 停顿标记必须放在可朗读文本之间，不能连续使用。
- 支持行内发音修正。
- `speech-2.8-hd` 和 `speech-2.8-turbo` 支持部分语气/拟声标签，例如 `(breath)`、`(sighs)`、`(humming)` 等。
- 非流式输出可以返回 `hex` 或临时 `url`，URL 有时效，不应作为 Floppy 最终播放地址。
- 返回 `extra_info`，包括音频时长、采样率、文件大小、使用字符数等。

Floppy 用法：

- 30 秒到 3 分钟的试听样本走 T2A HTTP。
- App 里“先听一小段”或内部评测样本走 T2A HTTP。
- 生产的 10 分钟以上睡前音频默认不走同步 HTTP。

### 2. T2A Async

适合长文本、批量生成和睡前长音频。

关键信息：

- 创建任务：`POST https://api.minimax.io/v1/t2a_async_v2`
- 查询任务：`GET https://api.minimax.io/v1/query/t2a_async_query_v2`
- 查询接口限制：最多 10 queries/s。
- 直接 text 输入最大 50,000 字符。
- `text_file_id` 输入最大 1,000,000 字符。
- `text_file_id` 支持 `txt`、`zip`。
- `txt` 文件也支持 `<#x#>` 停顿标记。
- `zip` 要求文件同类型；`json` 可按 `title`、`content`、`extra` 字段分别生成音频、字幕和元数据。
- 创建成功返回 `task_id`、`file_id`、`task_token`、`usage_characters`。
- 查询状态包括 `processing`、`success`、`failed`、`expired`。
- 成功后用 `file_id` 调 File Retrieve 下载。
- 下载 URL 官方说明有效期为 9 小时，必须及时转存到 Floppy 自己的对象存储。

Floppy 用法：

- 用户专属长音频生成走 Async。
- 运营侧批量预生成也走 Async。
- `generation_jobs` 需要保存 MiniMax `task_id`、`file_id`、原始状态、用量字符数和错误码。
- Worker 需要在下载 URL 过期前拉取并转存，不能让 App 直接依赖 MiniMax URL 播放。

### 3. File API

长文本和异步结果都依赖 File API。

关键信息：

- 上传：`POST https://api.minimax.io/v1/files/upload`
- `purpose=t2a_async_input` 用于异步长文本输入。
- 支持上传 `txt` / `zip` 作为 T2A Async 输入。
- 检索元数据：`GET /v1/files/retrieve`
- 下载文件内容：`GET /v1/files/retrieve_content`

Floppy 用法：

- 对 50,000 字符以内的脚本，优先直接传 `text`。
- 对超长内容、分章故事、批量预生成，先上传 `txt` / `zip`，再创建 async task。
- 下载后统一落 Floppy 对象存储，记录 `provider_file_id` 和 `object_key`。

### 4. Voice Management

关键信息：

- `POST /v1/get_voice` 可列出当前账号下可用 voice。
- `voice_type` 支持 `system`、`voice_cloning`、`voice_generation`、`all`。
- 系统音色列表里有多种适合 Floppy 首轮测试的中文音色：
  - `Chinese (Mandarin)_Warm_Bestie`
  - `Chinese (Mandarin)_Gentle_Youth`
  - `Chinese (Mandarin)_Warm_Girl`
  - `Chinese (Mandarin)_Gentle_Senior`
  - `Chinese (Mandarin)_Soft_Girl`
  - `Chinese (Mandarin)_Warm_HeartedGirl`
  - `Chinese (Mandarin)_Laid_BackGirl`
  - `Chinese (Mandarin)_Lyrical_Voice`
- 英文 ASMR/助眠可优先测试：
  - `English_Whispering_girl`
  - `English_CalmWoman`
  - `English_Gentle-voiced_man`
  - `English_Graceful_Lady`
  - `English_SereneWoman`
  - `English_CaptivatingStoryteller`

注意：

- 不要把 voice_id 写死在业务逻辑里，应建 `voice_profiles` 配置。
- 不要假设所有模型都支持 `whisper` emotion。官方文档显示 `whisper` 在部分模型上有限制。ASMR 首版应优先靠 whisper-like 音色、慢语速和停顿实现。
- 声音克隆和声音设计后置，涉及授权、用户 consent 和商用使用边界。

### 5. 价格

Pay-as-you-go 音频价格：

| 模型 | 价格 |
| --- | --- |
| `speech-2.8-turbo` | 60 USD / 1M characters |
| `speech-2.8-hd` | 100 USD / 1M characters |
| Rapid Voice Cloning | 1.5 USD / voice |
| Voice Design | 3 USD / voice |

折算：

- Turbo：约 0.06 USD / 1,000 字符。
- HD：约 0.10 USD / 1,000 字符。
- 一条 5,000 字符的睡前脚本，TTS 成本约 0.30 USD 到 0.50 USD，不含 LLM 脚本生成、存储、CDN 和后处理。

对 Floppy 的含义：

- 缓存不是锦上添花，而是核心成本控制能力。
- 用户请求必须先查精确缓存、in-flight job 和近似缓存。
- 热门睡前主题应预生成。
- 专属生成要做配额、频控和异步排队。
- `estimated_cost` 应进入 `generation_jobs` 和评估报表。

## Hub / Skill 工作流评估

MiniMax Hub 的 `asmr-ambient` 官方 skill 是创作工具型 workflow。它导出的包里包含：

```text
asmr-ambient/
├── SKILL.md
├── meta.yaml
├── references/category-music-mapping.md
├── scripts/render_mix_preview.py
├── scripts/validate_nature.py
└── html/preview-mix_feedback.html
```

它的成熟点在于完整覆盖了助眠音频生产链：

```text
选择内容类型
-> 生成脚本和停顿
-> 选音色并 TTS
-> 导入自然音效
-> 生成背景音乐
-> ffmpeg 混音
-> 试听反馈
-> 导出成品
```

这套流程和 Floppy 的目标高度匹配，但它不是后端 API 工作流：

- 官网 skill 页面主要是打开或下载 MiniMax Hub App。
- Skill 依赖 MCP 工具，例如 `audios_generation`、`music_generation_instrumental`、`ffmpeg`、`audio_meta`。
- Skill 使用 `.sleep-audio/{project_name}/` 本地目录和 `.sleep-state.json`。
- 每阶段依赖 `AskUserQuestion` 人工确认。
- 自然音效下载依赖 Playwright 浏览 Pixabay。
- 预览页面是本地 HTTP server，适合创作调音，不适合 App 用户睡前使用。

结论：Hub workflow 可以作为 Floppy 内部“生产方法论”和运营工具原型，但不能直接搬进生产后端。

## 可以直接借鉴的部分

### 1. 内容类型

保留三类一线内容：

| 类型 | 默认时长 | Floppy 用途 |
| --- | --- | --- |
| `meditation` | 5-15 分钟 | 呼吸、身体扫描、场景想象、渐进放松 |
| `story` | 5-10 分钟 | 成人向低刺激睡前故事 |
| `asmr` | 10-20 分钟 | 耳语、白噪音、重复、极慢节奏 |

### 2. 脚本停顿规则

MiniMax 官方 T2A 支持 `<#x#>`，Hub Skill 对不同场景停顿有成熟规则。Floppy 应将其产品化：

| 场景 | 停顿 |
| --- | --- |
| 普通句间 | `<#0.5#>` 到 `<#1#>` |
| 段落过渡 | `<#2#>` 到 `<#3#>` |
| 呼吸引导 | `<#3#>` 到 `<#5#>` |
| 深度放松 | `<#5#>` 到 `<#8#>` |
| ASMR | 几乎每句都有停顿 |

应新增 `SleepScriptService`，由它输出带停顿标记的最终 TTS 脚本。

### 3. 音色 profile

把 skill 中“按内容类型选音色”的思路变成配置：

```json
{
  "meditation": {
    "voice_candidates": [
      "Chinese (Mandarin)_Soft_Girl",
      "Chinese (Mandarin)_Gentle_Senior",
      "Chinese (Mandarin)_Lyrical_Voice"
    ],
    "speed": 0.8,
    "emotion": "calm"
  },
  "story": {
    "voice_candidates": [
      "Chinese (Mandarin)_Warm_Bestie",
      "Chinese (Mandarin)_Radio_Host",
      "Chinese (Mandarin)_Kind-hearted_Elder"
    ],
    "speed": 0.9,
    "emotion": "calm"
  },
  "asmr": {
    "voice_candidates": [
      "Chinese (Mandarin)_Soft_Girl",
      "Chinese (Mandarin)_Laid_BackGirl",
      "English_Whispering_girl"
    ],
    "speed": 0.75,
    "emotion": null
  }
}
```

### 4. 自然音效 taxonomy

可复用 skill 的自然音效分类作为 Floppy 第一版背景声标签：

```text
rain, thunder, fireplace, ocean, river, forest, bird, cricket,
wind, snow, cafe, clock, keyboard, vinyl, train, city, subway,
whitenoise, underwater, space
```

但素材来源不要运行时抓 Pixabay。生产应建立合规 `nature_assets` 库，预先审核授权和质量。

### 5. 混音原则

Hub skill 的混音经验值得直接作为 `AudioPostProcessor` 规则：

- 混音前做 volume analysis。
- 背景声和音乐先预渲染到目标音量。
- 人声比自然音效更靠前。
- 自然音效低于人声约 15-25dB。
- 背景音乐低于人声约 25-35dB。
- 人声延迟进入，先用自然声建立安全感。
- 避免简单 `amix` 导致音量被自动压低。
- 谨慎使用 `loudnorm`，避免在人声停顿时抬高背景。

第一版工程不必一次做完整混音，但至少要保留 `AudioPostProcessor` 边界。

### 6. 反馈闭环

Skill 的试听反馈可以转成 Floppy 用户事件：

- `voice_too_fast`
- `voice_too_slow`
- `voice_too_loud`
- `voice_too_quiet`
- `background_too_loud`
- `background_too_quiet`
- `prefer_voice`
- `dislike_voice`
- `prefer_background`
- `sleep_helpful`
- `skip_early`

这些事件更新用户画像和生成偏好，而不是让睡前用户反复进入创作流程。

## 不能照搬的部分

1. 不能照搬本地状态文件。
   - Skill 的 `.sleep-state.json` 应改成数据库里的 `generation_jobs`、`audio_scripts`、`tts_provider_tasks`。

2. 不能照搬每阶段人工确认。
   - Floppy App 的主场景是睡前，用户不应频繁做选择。
   - 默认自动生成，播放后用轻量反馈修正偏好。

3. 不能照搬 MCP 工具调用。
   - 生产后端应使用 MiniMax REST API、ffmpeg worker、对象存储 SDK。

4. 不能运行时从 Pixabay 下载素材。
   - 生产要有合规素材库、授权记录、质量评分。

5. 不能让 App 播放 MiniMax 临时 URL。
   - 必须下载并转存到 Floppy 自己的云存储/CDN。

6. 不能先做声音克隆。
   - 克隆是后续高级能力，必须先解决授权、合规、可删除和用户 consent。

## Floppy 推荐生产工作流

### 用户专属生成链路

```text
User Request
  -> RequestNormalizer
  -> CacheMatcher
  -> UserProfileResolver
  -> SleepScriptService
  -> ScriptSafetyGuard
  -> VoiceProfileSelector
  -> MiniMaxTTSProvider
       -> T2A HTTP for preview / short audio
       -> T2A Async for long audio
  -> ProviderTaskPoller
  -> FileRetriever
  -> ObjectStorage
  -> AudioPostProcessor
  -> AudioQualityEvaluator
  -> AudioAssetRepository
  -> Recommendation / Playback
```

### 运营预生成链路

```text
Topic Planner
  -> batch script generation
  -> script review
  -> async batch TTS
  -> retrieve files
  -> postprocess
  -> human spot check
  -> publish to audio library
  -> recommendation index
```

这一条最接近 MiniMax Hub 的创作工作流，但要去掉人工多轮确认，改成运营侧批量审核。

### 内部调音链路

保留一个内部 preview 工具，而不是暴露给用户：

```text
sample script
  -> voice candidates
  -> short T2A previews
  -> background variants
  -> mix preview
  -> evaluator feedback
  -> write voice/mix profile
```

这可以借鉴 `render_mix_preview.py` 的思路，但后续应做成内部管理台或 CLI。

## 状态机建议

当前 MVP 的 `queued/generating/succeeded/failed` 太粗。MiniMax 接入后建议扩展：

```text
queued
normalizing
cache_matched
script_generating
script_reviewing
provider_submitting
provider_processing
file_retrieving
postprocessing
qa_reviewing
succeeded
failed
expired
cancelled
```

MiniMax provider 状态映射：

| MiniMax status | Floppy status |
| --- | --- |
| `processing` | `provider_processing` |
| `success` | `file_retrieving` |
| `failed` | `failed` |
| `expired` | `expired` |

## 数据模型建议

### `audio_scripts`

保存最终送 TTS 的脚本，而不是只保存原始用户请求。

```text
id
user_id
title
content_type
language
script_text
script_hash
pause_density
estimated_duration_sec
safety_status
safety_notes
created_at
```

### `generation_jobs` 扩展

```text
provider
provider_model
provider_task_id
provider_task_token
provider_file_id
provider_status
provider_payload
script_id
script_hash
script_chars
usage_characters
estimated_cost_usd
download_deadline_at
error_code
error_message
```

### `voice_profiles`

```text
id
content_type
language
provider
model
voice_id
speed
vol
pitch
emotion
priority
quality_score
is_active
```

### `nature_assets`

```text
id
category
object_key
duration_sec
format
license
source
quality_score
loopable
created_at
```

### `mix_recipes`

```text
id
content_type
nature_category
voice_gain
nature_target_db_delta
music_target_db_delta
voice_delay_ms
fade_in_sec
fade_out_sec
created_at
```

### `tts_eval_runs`

```text
id
provider
model
voice_id
script_id
audio_asset_id
latency_ms
usage_characters
estimated_cost_usd
naturalness_score
sleep_fit_score
stability_score
review_notes
created_at
```

## 工程落地优先级

### P0：MiniMax Provider Skeleton

- 新增 provider factory。
- 新增 `MiniMaxTTSProvider`。
- 环境变量：
  - `FLOPPY_AUDIO_PROVIDER=local|minimax|volcengine|azure`
  - `FLOPPY_MINIMAX_API_KEY`
  - `FLOPPY_MINIMAX_BASE_URL`
  - `FLOPPY_MINIMAX_MODEL`
  - `FLOPPY_MINIMAX_VOICE_ID`
- 无 key 时明确报错，不静默 fallback。

### P0：SleepScriptService

- 输出带 `<#x#>` 的脚本。
- 支持 `meditation/story/asmr` 三类模板。
- 先用规则模板，后续再接 LLM。
- 生成 `script_hash` 并入库。

### P0：Async 任务与文件转存

- 保存 `task_id` 和 `file_id`。
- 轮询查询时做速率限制。
- 下载 URL 9 小时内必须转存。
- provider 临时 URL 不进 App 播放链路。

### P1：Voice Profile 管理

- 用配置表或 YAML 管理 voice profile。
- 先测中文 6 个候选音色。
- 每个内容类型至少保留 2 个可用音色。

### P1：AudioPostProcessor MVP

- 统一输出格式。
- 检测音频时长、大小、采样率。
- 基础 fade-in / fade-out。
- 后续再做自然音效和背景音乐混音。

### P1：评测集

第一批样本：

- 30 秒故事试听。
- 2 分钟故事。
- 8-10 分钟故事。
- 3 分钟冥想。
- 8 分钟 ASMR。
- 内容转睡前音频 3 分钟。

评价维度：

- 中文自然度。
- 睡前适配度。
- 停顿自然度。
- 音色稳定性。
- 长文本稳定性。
- 延迟。
- 成本。
- 失败率。
- 后处理前后音量一致性。

## 关键风险

1. 商用与缓存授权仍需确认。
   - 官方 API 能生成音频不等于我们可以无限期缓存并商业播放。
   - 需要单独确认 Terms、企业合同或官方商务回复。

2. 成本随专属生成快速上升。
   - 必须前置缓存、近似复用、用户配额和预生成策略。

3. 长音频失败重试成本高。
   - 长文本要拆段或至少保存脚本与 provider task，失败后能从中间状态恢复。

4. Hub Skill 的创作流程太重。
   - 用户睡前不适合多轮确认。生产端要自动化，反馈后置。

5. ASMR 不等于简单 whisper 参数。
   - MiniMax 模型 emotion 支持有版本差异。首版重点放在音色、慢语速、停顿和后期混音。

## 建议下一步

1. 先实现 `SleepScriptService` 和 `audio_scripts`。
2. 再实现 `MiniMaxTTSProvider` skeleton。
3. 用 T2A HTTP 生成短样本，验证 key、音色、停顿和音频入库。
4. 接 T2A Async，验证 5-10 分钟长音频。
5. 建立 `tts_eval_runs`，把每次试听结果沉淀下来。
6. 同步确认 MiniMax 商用、缓存、长期存储和用户生成内容条款。
