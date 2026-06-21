# Floppy Development Log

长期开发记录。每次后端/算法方向有重要变更时，在本文件追加一条记录，保留任务、验证证据、当前边界和下一步计划。

## 2026-06-21 Backend/Algorithm MVP

### 背景

基于产品文档 `/Users/aooway/Downloads/Floppy.md`，先验证 Floppy 后端和算法方向是否可行，并搭建一个工程级 MVP。当前阶段重点不是 App UI，而是跑通：

- 云上音频库的本地等价实现。
- 用户画像和分层。
- 推荐算法 pipeline。
- 缓存命中与按需生成。
- 异步生成任务和任务状态。
- 后续替换真实 TTS、对象存储、向量库的工程边界。

### 已完成

1. 完成后端/算法调研文档。
   - 文件：`docs/research/backend_algorithm_research.md`
   - 覆盖：音频资产库、缓存策略、用户画像、推荐算法、生成安全、Agent/工作流框架选型、风险和 MVP 路线。

2. 搭建 FastAPI 后端 MVP。
   - 入口：`floppy_backend/main.py`
   - 运行说明：`README.md`
   - 依赖配置：`pyproject.toml`

3. 建立核心数据模型和 SQLite schema。
   - 文件：`floppy_backend/db.py`
   - 表：`users`、`user_profiles`、`audio_assets`、`generation_jobs`、`events`

4. 实现用户画像与分层。
   - 文件：`floppy_backend/services/profile.py`
   - 当前分层：`anxiety_relief`、`companionship`、`environmental_sleep`、`content_transform`、`quick_sleep`、`balanced_sleep`

5. 实现推荐算法 MVP。
   - 文件：`floppy_backend/services/recommendation.py`
   - 能力：画像偏好匹配、用户分层匹配、情绪标签匹配、向量近似、质量分排序、推荐理由返回。

6. 实现请求归一化。
   - 文件：`floppy_backend/services/normalizer.py`
   - 能力：从中文需求中提取意图、时长、音色、背景声、情绪和主题。

7. 实现音频资产库和本地对象存储。
   - 文件：`floppy_backend/storage.py`
   - 能力：本地文件路径、安全路径校验、播放 URL 生成。
   - 已加入路径穿越防护。

8. 实现本地音频生成 provider。
   - 文件：`floppy_backend/providers/audio.py`
   - 当前为 deterministic WAV 生成器，用于验证工程链路。
   - 支持 `FLOPPY_LOCAL_PROVIDER_DELAY_SEC` 模拟真实 TTS 延迟。

9. 实现同步生成链路。
   - 接口：`POST /users/{user_id}/generate-audio`
   - 能力：归一化请求、精确缓存命中、近似缓存命中、按需生成、入库、返回播放 URL。

10. 实现异步生成任务链路。
    - 创建任务：`POST /users/{user_id}/generation-jobs`
    - 查询任务：`GET /generation-jobs/{job_id}`
    - 能力：`queued`、`generating`、`succeeded`、`failed` 状态管理。
    - 本地使用 FastAPI `BackgroundTasks` 模拟 worker。

11. 实现 in-flight 去重。
    - 文件：`floppy_backend/repositories.py`
    - 能力：同一用户、同一 cache key 的生成任务如果已经处于 `queued` 或 `generating`，不会重复创建新任务。
    - 目的：避免真实 TTS 场景重复生成和重复扣成本。

12. 实现事件上报。
    - 接口：`POST /users/{user_id}/events`
    - 用途：记录播放、反馈、生成等行为，为推荐优化提供数据。

13. 补充自动化测试。
    - 文件：`tests/test_mvp_flow.py`
    - 覆盖：健康检查、种子音频、画像、推荐、同步生成、缓存命中、音频播放、防路径穿越、异步 job、in-flight 去重。

### 验证记录

自动化测试：

```text
.venv/bin/pytest
3 passed
```

真实服务 HTTP 冒烟验证已完成：

- `GET /health`
- `POST /admin/seed`
- `PUT /users/{user_id}/profile`
- `GET /users/{user_id}/recommendations`
- `POST /users/{user_id}/generation-jobs`
- `GET /generation-jobs/{job_id}`
- 重复提交同一生成请求时返回 `match_type = in_flight`
- 生成完成后同请求返回 `cache_hit = true`、`match_type = exact`

### 当前工程边界

当前 MVP 可用于验证后端/算法主链路，但不是生产版本。

已刻意保留的替换点：

- `LocalToneAudioProvider` 后续替换为火山/其它 TTS 或音频生成 provider。
- `LocalFileStorage` 后续替换为 TOS/OSS/S3 + CDN + 签名 URL。
- SQLite 后续替换为 PostgreSQL。
- 当前内置向量计算后续替换为 pgvector、VikingDB、Milvus 或 Qdrant。
- FastAPI `BackgroundTasks` 后续替换为持久队列和独立 worker，例如 Celery/RQ/云队列。

### 已知限制

- 当前音频是本地 mock WAV，不是真实 TTS。
- 当前推荐算法是可解释规则和轻量向量相似，不是训练出的深度推荐模型。
- 当前 BackgroundTasks 不具备生产级可靠性，服务重启可能丢失 queued job。
- 当前用户认证、权限、限流、配额、计费和内容安全审核还没有接入。
- 当前没有真实云对象存储、CDN、签名 URL 和音频生命周期策略。

### 建议下一步

1. 接入真实 TTS provider。
   - 优先评估火山引擎 TTS/豆包生态。
   - 保持 `AudioGenerationProvider` 接口不变。

2. 把生成任务切到持久队列。
   - API 只负责创建 job。
   - Worker 负责生成、质检、入库和状态更新。

3. 切换生产数据库和对象存储。
   - PostgreSQL + pgvector 可以作为下一阶段默认组合。
   - 对象存储优先按目标部署云选择 TOS/OSS/S3。

4. 建立内容安全和质量检查。
   - 睡前内容要限制惊吓、恐怖、高刺激、高信息密度、医疗承诺。

5. 扩展事件体系和推荐指标。
   - 播放完成率、跳出点、收藏/不喜欢、次日满意度。

6. 开始做 API 契约。
   - 给移动端/硬件端明确请求和响应字段。
   - 后续可生成 OpenAPI client。

## 2026-06-21 TTS Vendor Research

### 背景

明确不自训练 TTS 模型，改为调研第三方音频/TTS 服务，选择适合 Floppy 的真实音频生成 provider。

### 已完成

1. 新增 TTS 厂商调研文档。
   - 文件：`docs/research/tts_vendor_research.md`

2. 覆盖候选厂商。
   - 第一轮 shortlist 收敛为：豆包/火山引擎、MiniMax、微软 Azure AI Speech。
   - 其他厂商暂不进入第一轮，避免评估和工程接入发散。

3. 给出 Floppy 选型建议。
   - 豆包/火山引擎作为国内默认 provider 候选。
   - MiniMax 作为高自然度和情绪化语音候选。
   - 微软 Azure AI Speech 作为企业级稳定、SSML、多语言候选。

4. 给出 PoC 验证方案。
   - 同一批故事、冥想、内容转化、压力舒缓文本。
   - 统一评估中文自然度、睡前适配度、长文本稳定性、可控性、延迟、成本、合规授权。

### 下一步

1. 在当前 MVP 中新增真实 provider skeleton。
2. Provider skeleton 先覆盖豆包、MiniMax、微软三家。
3. 通过环境变量切换 `local`、`volcengine`、`minimax`、`azure`。
4. 生成样本并记录耗时、字符数、音频质量和成本估算。

## 2026-06-21 MiniMax Audio Workflow Design

### 背景

在 TTS 厂商 shortlist 收敛到豆包、MiniMax、微软后，进一步设计如何配合 MiniMax 搭建睡前音频生成工作流/智能体。

### 已完成

1. 新增 MiniMax 音频工作流设计文档。
   - 文件：`docs/research/minimax_audio_workflow.md`

2. 明确 MiniMax 的定位。
   - MiniMax 作为 TTS/T2A provider，不作为全流程 Agent。
   - Floppy 自己负责需求理解、脚本生成、安全检查、缓存、任务状态、音频入库和推荐。

3. 设计工作流。
   - 用户请求归一化。
   - 缓存匹配和 in-flight 去重。
   - Sleep Script Agent 生成睡前脚本。
   - Safety/Quality Guard 检查脚本。
   - MiniMax T2A HTTP/Async 合成。
   - 音频后处理和资产入库。

4. 明确下一步工程改造点。
   - 增加 provider factory。
   - 增加 `MiniMaxTTSProvider` skeleton。
   - 增加脚本生成层。
   - 扩展 `generation_jobs` 保存 provider task 信息。
   - 后续增加 `audio_scripts` 和 `tts_eval_runs`。

### 下一步

1. 先实现 MiniMax provider skeleton，不直接写死到业务服务里。
2. 增加无密钥环境下的明确失败提示。
3. 用同步 T2A 生成短样本，再接 async T2A 处理长文本。

## 2026-06-21 Official ASMR Ambient Skill Review

### 背景

用户从 MiniMax Hub 导出了官方 skill：`/Users/aooway/Downloads/asmr-ambient.zip`，希望评估它是否适合 Floppy。

### 已完成

1. 静态检查 zip 内容。
   - 未执行其中脚本。
   - 解压到 `/tmp/floppy_asmr_skill` 后只读取文本和源码。

2. 新增评审文档。
   - 文件：`docs/research/asmr_ambient_skill_review.md`

3. 评估结论。
   - 该 skill 对 Floppy 很有参考价值。
   - 适合吸收脚本停顿、三类内容类型、音色策略、自然音分类、混音原则和反馈闭环。
   - 不适合直接作为服务端生产逻辑，因为它面向 MiniMax Hub 本地创作流程，依赖 MCP 工具、本地目录和多阶段人工确认。

4. 明确可迁移能力。
   - `SleepScriptService`
   - `<#X#>` 停顿标记
   - `AudioPostProcessor`
   - 自然音效资产库
   - 用户音频偏好沉淀
   - MiniMax async 任务状态扩展

### 下一步

1. 优先把 `SKILL.md` 中的脚本规则迁移为 Floppy 的脚本生成规则。
2. 先做 `SleepScriptService`，再接 `MiniMaxTTSProvider`。
3. 第一版后处理只做格式统一、音量检查和淡入淡出，完整混音后置。

## 2026-06-21 MiniMax Official Deep Research

### 背景

用户希望进一步调研 MiniMax 官网，判断它的成熟工作流是否可以直接借鉴到 Floppy 后端和算法方向。

### 已完成

1. 新增 MiniMax 官网深度调研文档。
   - 文件：`docs/research/minimax_official_deep_research.md`

2. 调研 MiniMax API Platform。
   - T2A HTTP：适合短文本、试听和 PoC。
   - T2A Async：适合长文本、批量生成和睡前长音频。
   - File Upload/Retrieve：用于长文本输入和生成结果下载。
   - Get Voice：用于查询系统音色、克隆音色和生成音色。
   - Pricing：确认 T2A 按字符计费，`speech-2.8-turbo` 为 60 USD / 1M characters，`speech-2.8-hd` 为 100 USD / 1M characters。

3. 调研 MiniMax Hub / Skill 工作流。
   - 官网 skill 页面主要是打开或下载 MiniMax Hub App。
   - 官方 `asmr-ambient` skill 是创作工具型 workflow，不是后端 API。
   - 可借鉴脚本停顿、三类内容、音色策略、自然音效 taxonomy、混音原则和反馈闭环。
   - 不建议照搬 MCP 工具、本地状态文件、多阶段人工确认、运行时下载 Pixabay 素材和本地预览服务器。

4. 更新 MiniMax 音频工作流设计文档。
   - 文件：`docs/research/minimax_audio_workflow.md`
   - 补充官方接口限制、File API、Voice API、成本判断和 Hub workflow 取舍。

### 关键结论

MiniMax 的工作流值得借鉴，但不能直接把 Hub Skill 作为 Floppy 后端。生产方案应是：

```text
Floppy Orchestrator
  -> SleepScriptService
  -> ScriptSafetyGuard
  -> MiniMaxTTSProvider
  -> FileRetriever
  -> ObjectStorage
  -> AudioPostProcessor
  -> AudioAssetRepository
```

MiniMax 只作为 TTS/T2A provider。Floppy 自己保留需求理解、脚本生成、缓存、任务状态、音频入库、推荐和用户反馈闭环。

### 下一步

1. 实现 `SleepScriptService`，先用规则模板生成带 `<#x#>` 停顿标记的脚本。
2. 增加 `audio_scripts` 表，保存最终送 TTS 的脚本和 `script_hash`。
3. 增加 `MiniMaxTTSProvider` skeleton 和 provider factory。
4. 扩展 `generation_jobs`，保存 `provider_task_id`、`provider_file_id`、`usage_characters`、`estimated_cost_usd`。
5. 用 T2A HTTP 先生成短样本，再接 T2A Async 验证 5-10 分钟长音频。
6. 单独确认 MiniMax 商用、缓存、长期存储和声音克隆授权边界。

## 2026-06-21 MiniMax Skeleton And Sleep Script Layer

### 背景

用户确认可以大胆推进，先实现不依赖 MiniMax 密钥也能本地验证的工程骨架，并明确真实接入前置条件。

### 已完成

1. 新增 `SleepScriptService`。
   - 文件：`floppy_backend/services/script.py`
   - 支持 `story`、`meditation`、`asmr` 三类内容。
   - 输出带 MiniMax `<#x#>` 停顿标记的脚本。
   - 输出 `title`、`pause_density`、`estimated_duration_sec`、`script_hash` 和安全说明。
   - 当前为 deterministic/template 版本，后续可替换为 LLM-backed script agent。

2. 新增脚本入库能力。
   - 表：`audio_scripts`
   - Repository：`upsert_audio_script`、`get_audio_script`、`get_audio_script_by_hash`
   - `generation_jobs` 返回中会带上 `script`。

3. 扩展 `generation_jobs` 元数据。
   - 新增字段：`script_id`、`script_hash`、`script_chars`、`provider_model`、`provider_task_id`、`provider_file_id`、`provider_status`、`provider_payload`、`usage_characters`、`estimated_cost_usd`、`error_message`。
   - SQLite 初始化增加轻量 migration，兼容已有本地数据库。

4. 新增 provider factory。
   - 文件：`floppy_backend/providers/audio.py`
   - 配置：`FLOPPY_AUDIO_PROVIDER=local|minimax`
   - 默认仍为本地 `LocalToneAudioProvider`。

5. 新增 `MiniMaxTTSProvider` skeleton。
   - 使用 MiniMax T2A HTTP。
   - 显式要求 `FLOPPY_MINIMAX_API_KEY`。
   - 支持配置 model、voice_id、speed、volume、pitch、emotion、sample_rate、bitrate、channel。
   - 短文本返回 mp3 并记录 provider payload、usage characters 和估算成本。
   - 对超过同步接口限制的脚本明确要求后续走 async workflow。

6. 更新应用初始化和音频输出。
   - `main.py` 改为通过 `build_audio_provider(settings)` 创建 provider。
   - `/audio/{object_key}` 根据文件后缀返回 `audio/wav` 或 `audio/mpeg`。

7. 更新 README。
   - 增加 MiniMax 接入前置条件。
   - 增加环境变量启动方式。
   - 明确当前 skeleton 先验证 T2A HTTP，长音频 async 下一阶段补。

8. 补充自动化测试。
   - 验证生成 job 写入脚本和停顿标记。
   - 验证异步 job 返回脚本元数据。
   - 验证 in-flight 去重仍有效。
   - 验证 MiniMax provider 在无 key 时明确失败。

### 验证记录

```text
.venv/bin/pytest
4 passed, 1 warning
```

唯一 warning 来自 FastAPI/TestClient 底层依赖的 Starlette deprecation，不影响当前功能。

### 当前边界

- MiniMax skeleton 当前只接 T2A HTTP，还没有接 T2A Async 创建、轮询、文件下载和转存。
- 当前 `SleepScriptService` 是规则模板版，适合验证工程链路，不代表最终内容质量。
- 当前没有真实调用 MiniMax，因为缺少 API Key 和账号额度。
- 商用、缓存、长期存储、声音克隆授权还需要用户侧确认。

### 用户需要准备

1. MiniMax API Key。
2. MiniMax 账号余额或企业额度。
3. 第一批测试 voice_id，建议先用：
   - `Chinese (Mandarin)_Warm_Bestie`
   - `Chinese (Mandarin)_Soft_Girl`
   - `Chinese (Mandarin)_Gentle_Senior`
4. 确认 MiniMax 生成音频是否允许商用播放、缓存复用、长期存储和 CDN 分发。

### 下一步

1. 用户提供 MiniMax API Key 后，生成第一批短样本。
2. 记录音质、停顿自然度、耗时、字符数和估算成本。
3. 实现 T2A Async workflow：
   - create task
   - query status
   - retrieve file
   - save to Floppy storage
   - update job provider metadata
4. 建立 `tts_eval_runs`，沉淀评测结果。

## 2026-06-21 MiniMax Chinese Host Smoke

### 背景

MiniMax 真实生成 smoke 已跑通，确认当前中文站 API Key 必须使用中文站 host。

### 验证事实

- 成功 provider：`minimax_t2a`
- 成功 model：`speech-2.8-hd`
- 成功 host：`https://api.minimaxi.com`
- `usage_characters=661`
- `estimated_cost_usd=0.0661`
- `audio_content_type=audio/mpeg`
- 英文站 `https://api.minimax.io` 对当前 key 返回 `invalid api key`。

### 已完成

1. 将默认 `FLOPPY_MINIMAX_BASE_URL` 调整为 `https://api.minimaxi.com`。
2. 更新 README，明确中文站 API Key 必须配置：

   ```bash
   export FLOPPY_MINIMAX_BASE_URL="https://api.minimaxi.com"
   ```

3. MiniMax provider 在英文站 host 遇到 `invalid api key` 或 HTTP 401 时，会提示中文站 key 可能需要切到 `https://api.minimaxi.com`。
4. 未在仓库写入任何 API Key。

### 当前边界

- MiniMax 商用、缓存、长期存储、CDN 分发和声音克隆授权仍需单独确认。
- 真实 provider 成本和延迟需要继续沉淀到评测数据中。

## 2026-06-21 Agent Tool Contract

### 背景

产品方向确认：Floppy 是 Agent 项目，后端是 Agent 的执行层，用户画像是 Agent 的决策上下文。需要在后端方案中明确 Agent 与后端的接口契约。

### 已完成

1. 新增 Agent Tool Contract 文档。
   - 文件：`docs/contracts/agent_tool_contract.md`
   - 覆盖：ProfileContext DTO、6 个后端工具定义、检索 vs 生成决策规则、安全/成本后端强制执行、与 algo 画像字段对齐原则。

2. 定义 ProfileContext（Agent 画像上下文 DTO）。
   - 包含：segment、algo_segment、mood_tags、tonight_mood、tonight_stress、generation_budget。
   - 提供 `GET /users/{id}/profile/context` 接口。

3. 定义 6 个 Agent 工具：
   - `normalize_request` → `POST /normalize`
   - `search_audio_assets` → `POST /assets/search`（返回 `hit` 字段，Agent 以此决定是否生成）
   - `create_generation_job` → 现有接口（后端强制额度检查）
   - `get_job_status` → 现有接口
   - `record_event` → 现有接口（规范 payload schema）
   - `update_profile_signal` → `POST /users/{id}/profile/checkin`

4. 明确安全/成本限制后端强制执行，Agent 不可信调用。

5. 明确与 algo 字段对齐规则：字段命名冲突以后端 contract 为准，algo segment 通过 `algo_segment` 独立列写入。

### P0 落地改造清单

1. `GET /users/{id}/profile/context`（含 `generation_budget`）
2. `POST /normalize`
3. `POST /assets/search`（返回 `hit` + `best_score`）
4. `create_generation_job` 增加每日额度检查（429）
5. `POST /users/{id}/profile/checkin`
6. `user_profiles` 增加 `algo_segment`、`tonight_mood`、`tonight_stress`、`profile_version` 列

### 下一步

1. 实现 P0 改造清单中的 3 个新接口 + 1 个额度检查 + DB migration。
2. 等算法同学确认 `ProfileContext` 字段后补全 `生成_budget` 口径和 `algo_segment` 枚举。
3. 补充集成测试：Agent 工具链 happy path + 额度拒绝场景。
