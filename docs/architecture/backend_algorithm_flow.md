# Floppy 后端与算法流程架构图

本文描述当前 Floppy 后端和算法决策链路，并补充一个目标态的 Multi-Agent、Dream Loop 和多层记忆架构。
当前已经落地的部分以在线请求链路为主；Dream 和多层记忆属于下一阶段产品/算法架构设计。

当前设计原则是：

- Hermes 负责用户意图理解、Skill 路由、结构化检索计划和 workflow 选择。
- Floppy 后端负责 API、资源检索执行、任务状态、预算、安全、存储、播放历史和真实音频生产。
- 资源检索层只执行结构化 filters，不再把中文自然语言硬编码翻译成标签。
- 生成和混音是异步任务，客户端通过 `job_id` 或 `remix_job_id` 轮询结果。
- 目标态里，在线 Agent 只处理当下请求；离线 Dream Loop 在受控预算内整理记忆、发现矛盾、模拟未来请求和生成改进任务。

## 总体分层

```mermaid
flowchart LR
  subgraph Client["客户端入口"]
    Demo["Web Demo /demo"]
    App["App HTTP 接口"]
    Voice["实时语音 /voice/ws"]
    Upload["上传内容 /uploads"]
  end

  subgraph API["FastAPI 后端层"]
    DemoChat["/demo/chat"]
    VoiceIntent["/voice/intent"]
    VoiceWs["/voice/ws"]
    AgentDecide["/agent/decide"]
    AssetAPI["/assets/search /assets/facets"]
    GenerationAPI["/generation-jobs"]
    PlaybackAPI["/playback /feedback"]
    UploadAPI["/uploads/.../generate-audio"]
    SafetyAPI["/safety/script/check"]
  end

  subgraph Agent["Hermes 算法决策层"]
    VoiceDialog["floppy-voice-dialog Skill"]
    SleepAudio["floppy-sleep-audio Skill"]
    ProfileSkill["floppy-profile-context Skill"]
    PlaybackSkill["floppy-playback-control Skill"]
    TransformSkill["floppy-content-transform Skill"]
    SafetySkill["floppy-safety-quality Skill"]
    MemorySkill["floppy-memory-weaver Skill\n目标态"]
    DreamSkill["floppy-dream-loop Skill\n目标态"]
  end

  subgraph Exec["Floppy 执行层"]
    Runtime["HermesAgentRuntime"]
    Catalog["AssetCatalogService"]
    Generation["GenerationService"]
    Workflow["SleepAudioWorkflowService"]
    Script["SleepScriptService + ScriptGuard"]
    Remix["RemixService"]
    MCP["mcp_server.py"]
    MemorySvc["MemoryStoreService\n目标态"]
    DreamRunner["DreamRunner\n目标态"]
  end

  subgraph Data["数据与外部资源"]
    DB[("SQLite: profiles/assets/jobs/playback/uploads")]
    MemoryDB[("Memory tables / vector index\n目标态")]
    Storage[("storage/: audio/uploads/logs")]
    HermesGateway["Hermes Gateway /v1/responses"]
    AudioProvider["MiniMax 或 Local Provider"]
    ASR["Volc ASR"]
    TTS["MiniMax Stream TTS"]
  end

  Demo --> DemoChat
  App --> VoiceIntent
  App --> AgentDecide
  Voice --> VoiceWs
  Upload --> UploadAPI

  DemoChat --> Runtime
  VoiceIntent --> VoiceDialog
  VoiceWs --> ASR
  ASR --> VoiceDialog
  AgentDecide --> Runtime
  UploadAPI --> TransformSkill
  SafetyAPI --> Script

  Runtime --> HermesGateway
  VoiceDialog --> HermesGateway
  HermesGateway --> SleepAudio
  HermesGateway --> ProfileSkill
  HermesGateway --> PlaybackSkill
  HermesGateway --> TransformSkill
  HermesGateway --> SafetySkill
  HermesGateway --> MemorySkill
  HermesGateway --> DreamSkill

  SleepAudio --> Catalog
  SleepAudio --> Generation
  TransformSkill --> Generation
  PlaybackSkill --> PlaybackAPI
  ProfileSkill --> DB
  SafetySkill --> Script
  MemorySkill --> MemorySvc
  DreamSkill --> DreamRunner

  Catalog --> DB
  Generation --> Workflow
  Workflow --> Script
  Workflow --> AudioProvider
  Workflow --> Storage
  Workflow --> DB
  Remix --> Storage
  Remix --> DB
  PlaybackAPI --> DB
  PlaybackAPI --> MemorySvc
  MemorySvc --> DB
  MemorySvc --> MemoryDB
  DreamRunner --> MemorySvc
  DreamRunner --> Catalog
  DreamRunner --> Generation
  MCP --> API
  VoiceWs --> TTS
```

## 文本对话与推荐/生成流程

```mermaid
sequenceDiagram
  autonumber
  participant C as Client
  participant API as FastAPI
  participant R as HermesAgentRuntime
  participant H as Hermes
  participant Cat as AssetCatalogService
  participant Gen as GenerationService
  participant DB as SQLite
  participant S as Storage

  C->>API: POST /demo/chat 或 /agent/decide
  API->>R: AgentDecideRequest(user_id, request_text, current_asset_id)
  R->>DB: get profile + generation budget
  R->>Cat: list facets
  R->>H: plan_search(user_request, profile, facets)
  H-->>R: SearchPlan(filters, reasons, confidence)
  R->>Cat: search_audio_assets(filters)
  Cat->>DB: read approved audio_assets
  Cat-->>R: candidates + query_analysis
  R->>H: decide(user_request, search_plan, candidates)
  H-->>R: action: play_asset / generate_job / remix_current / no_match

  alt play_asset
    R-->>API: asset + playback_url
    API-->>C: action=play_asset, audio_url
  else generate_job
    R->>Gen: enqueue_or_match(...)
    Gen->>DB: create or claim generation_job
    API-->>C: action=generate_job, job_id
    API-)Gen: background run_job
    Gen->>S: write generated audio
    Gen->>DB: update job + asset
    C->>API: GET /generation-jobs/{job_id}
    API-->>C: status=succeeded, asset.playback_url
  else remix_current
    R->>DB: create remix_job
    R->>S: run remix
    R-->>API: remix_job_id + optional output_asset
  else no_match
    R-->>API: no playable or safe action
    API-->>C: action=no_match
  end
```

### 关键点

- `plan_search` 是算法侧的第一阶段：把自然语言变成 `type`、`required_tags`、`negative_tags` 等结构化 filters。
- `AssetCatalogService` 是执行器，不做中文语义推断，只做过滤、排序和 URL 补全。
- `decide` 是算法侧的第二阶段：基于候选资产和用户约束选择 `play_asset`、`generate_job`、`remix_current` 或 `no_match`。
- 生成任务不阻塞请求线程。接口先返回 `job_id`，后台执行音频生产。

## 语音入口流程

```mermaid
flowchart TD
  Mic["用户语音 PCM"] --> WS["/voice/ws"]
  WS --> ASR["VolcStreamASR"]
  ASR --> FinalText["ASR final text"]
  FinalText --> Dialog["HermesVoiceDialogClient\nfloppy-voice-dialog"]

  Dialog -->|chat| ChatReply["只回复文本 + TTS"]
  Dialog -->|clarify| Clarify["追问一句 + TTS"]
  Dialog -->|audio_workflow| AudioReq["整理 audio_request_text"]
  Dialog -->|remix_current| RemixReq["带 current_asset_id 的编辑请求"]

  AudioReq --> Resolve["agent runtime / sleep-audio workflow"]
  RemixReq --> Resolve
  Resolve -->|命中资产| AssetEvent["audio_asset(url, asset_id, audio_type)"]
  Resolve -->|需要生成| JobEvent["audio_job(job_id, job_status)"]

  ChatReply --> TTS["MiniMaxStreamTTS"]
  Clarify --> TTS
  AssetEvent --> AppPlayer["App 播放 sleep audio"]
  JobEvent --> Poll["轮询 /generation-jobs/{job_id}"]
  Poll --> AppPlayer
```

### 关键点

- 语音入口先走 `floppy-voice-dialog`，不会把“我睡不着”“今天好烦”直接当成推荐请求。
- `audio_workflow` 和 `remix_current` 才会继续进入 sleep-audio workflow。
- `/voice/ws` 会维护本连接的 `current_asset_id`，因此“加点雨声”“换一个”可以作用于当前播放资产。
- 当生成较慢时，WebSocket 返回 `audio_job`，客户端轮询 job，不阻塞整轮语音对话。

## 音频生成工作流

```mermaid
flowchart TD
  Req["GenerationRequest\nrequest_text + directive"] --> Normalize["RequestDefaults.normalize"]
  Normalize --> CacheKey["build_sleep_audio_cache_key"]
  CacheKey --> Job["generation_jobs: queued/generating"]

  Job --> NeedScript{"是否需要脚本?\nmeditation/story/asmr/podcast"}
  NeedScript -->|是| ScriptWriter["LLMScriptWriter 或模板"]
  ScriptWriter --> Guard["ScriptGuard\n安全 + 低刺激 + pause 质量"]
  Guard -->|blocked/low_quality| Fail["job failed 或回退模板"]
  Guard -->|approved| TTS["MiniMax TTS / LocalTone"]

  NeedScript -->|否| Ambient["procedural ambient\nwhite_noise/music"]
  Ambient --> AudioFile["写入 storage/audio"]
  TTS --> AudioFile
  AudioFile --> Asset["audio_assets: approved"]
  Asset --> Done["generation_jobs: succeeded"]
```

### 关键点

- `GenerationDirective` 由 Hermes 产出并持久化到 job，后台 worker 不会丢失算法意图。
- 人声内容会经过 `ScriptGuard`。白噪音和音乐不走脚本。
- `storage/` 是真实产物目录，保留生成音频、上传文件、日志和 smoke 输出。
- `run_job()` 在 prepare 或 provider 阶段异常时会把 job 标记为 `failed`，避免卡在 `generating`。

## Hermes Skill 与 MCP 工具边界

```mermaid
flowchart LR
  subgraph Skills["Hermes Skills"]
    VD["floppy-voice-dialog"]
    SA["floppy-sleep-audio"]
    PC["floppy-profile-context"]
    PB["floppy-playback-control"]
    CT["floppy-content-transform"]
    SQ["floppy-safety-quality"]
  end

  subgraph MCPTools["mcp_floppy_* tools"]
    Profile["get_user_profile_context\nupdate_profile_checkin"]
    Search["list_audio_asset_facets\nsearch_audio_assets\nget_audio_asset"]
    Gen["generate_sleep_audio\nget_generation_job"]
    Playback["start_playback\nsubmit_playback_feedback\nget_active_playback"]
    Upload["list_uploads\nget_upload\ngenerate_audio_from_upload"]
    Safety["check_sleep_script_safety"]
    Remix["remix_current\nget_remix_job"]
  end

  subgraph Backend["Floppy Backend APIs"]
    APIs["FastAPI routes"]
    Services["Repository + Services"]
    Store["SQLite + storage"]
  end

  VD --> SA
  SA --> Search
  SA --> Gen
  SA --> Remix
  PC --> Profile
  PB --> Playback
  CT --> Upload
  CT --> Gen
  SQ --> Safety

  MCPTools --> APIs
  APIs --> Services
  Services --> Store
```

### 关键点

- Skill 写产品策略和工具调用步骤。
- MCP 工具只是 Floppy 后端 API 的稳定外壳。
- 后端仍然是最终 enforcement boundary：预算、权限、播放反馈归属、安全检查、任务状态和存储路径都在后端校验。

## 目标态：Multi-Agent + Dream Loop + 多层记忆

这个部分是概念架构，借用“睡眠”的类比：

- NREM：整理当天会话，把重复、矛盾、过期的信息合并成稳定记忆。
- REM：让 Agent 自己生成假设场景、没遇到过的请求和边界 case，用来改进 Skill、工具和测试集。
- 梦醒门禁：Dream 产物不能直接污染用户画像，必须经过证据、成本、安全和可解释性检查。

### Multi-Agent 编排

```mermaid
flowchart TB
  User["用户文本/语音/上传"] --> Supervisor["Hermes Supervisor\n意图识别 + Skill 路由"]

  subgraph Online["在线 Agent：服务当下请求"]
    DialogAgent["Voice Dialog Agent\n聊天/追问/音频入口判断"]
    AudioAgent["Sleep Audio Agent\n搜索计划 + 播放/生成/混音决策"]
    PlaybackAgent["Playback Agent\n当前播放 + 反馈"]
    ProfileAgent["Profile Agent\n画像上下文"]
    TransformAgent["Content Transform Agent\n上传内容转音频"]
    SafetyAgent["Safety Agent\n脚本安全 + 低刺激"]
  end

  subgraph Tools["MCP / Backend Tools"]
    CatalogTool["catalog search"]
    GenTool["generation jobs"]
    PlaybackTool["playback history"]
    ProfileTool["profile context"]
    UploadTool["uploads"]
    SafetyTool["script guard"]
  end

  subgraph Offline["离线 Agent：睡眠时学习"]
    MemoryAgent["Memory Weaver\nNREM consolidation"]
    DreamAgent["Dream Simulator\nREM exploration"]
    EvalAgent["Evaluator\n证据/安全/成本门禁"]
    ProductAgent["Product Backlog Agent\n生成待办/测试/Skill 修订建议"]
  end

  subgraph Store["状态与记忆"]
    TurnBuffer["L0 turn buffer"]
    SessionMemory["L1 session memory"]
    EpisodicMemory["L2 episodic memory"]
    ProfileMemory["L3 profile memory"]
    CatalogMemory["L4 catalog memory"]
    ProductMemory["L5 product memory"]
  end

  Supervisor --> DialogAgent
  Supervisor --> AudioAgent
  Supervisor --> PlaybackAgent
  Supervisor --> ProfileAgent
  Supervisor --> TransformAgent
  Supervisor --> SafetyAgent

  DialogAgent --> ProfileTool
  AudioAgent --> CatalogTool
  AudioAgent --> GenTool
  AudioAgent --> PlaybackTool
  PlaybackAgent --> PlaybackTool
  ProfileAgent --> ProfileTool
  TransformAgent --> UploadTool
  SafetyAgent --> SafetyTool

  Tools --> TurnBuffer
  Tools --> EpisodicMemory
  ProfileTool --> ProfileMemory
  CatalogTool --> CatalogMemory

  TurnBuffer --> SessionMemory
  SessionMemory --> MemoryAgent
  EpisodicMemory --> MemoryAgent
  ProfileMemory --> MemoryAgent
  CatalogMemory --> MemoryAgent

  MemoryAgent --> EvalAgent
  MemoryAgent --> DreamAgent
  DreamAgent --> EvalAgent
  EvalAgent --> ProfileMemory
  EvalAgent --> ProductMemory
  ProductMemory --> ProductAgent
```

### Hermes Dream Loop

```mermaid
sequenceDiagram
  autonumber
  participant Scheduler as Sleep Scheduler
  participant Events as Session/Event Log
  participant NREM as Memory Weaver (NREM)
  participant Store as Memory Store
  participant REM as Dream Simulator (REM)
  participant Eval as Evaluator
  participant Backlog as Product/Skill Backlog

  Scheduler->>Events: collect ended sessions, playback, feedback, failures
  Events->>NREM: build daily memory bundle
  NREM->>NREM: dedupe, merge, expire, resolve conflicts
  NREM->>Eval: candidate stable memories
  Eval-->>Store: approved profile/session/catalog memory
  Eval-->>NREM: reject weak or unsafe memory

  Store->>REM: unresolved patterns + weak signals + failed tasks
  REM->>REM: simulate future requests and edge cases
  REM->>Eval: dream artifacts: hypotheses, test cases, skill patches
  Eval-->>Backlog: approved product tasks / regression cases
  Eval-->>Store: approved non-user-fact learning
  Eval-->>REM: discard hallucinated or costly artifacts
```

### 多层记忆模式

```mermaid
flowchart LR
  L0["L0 Turn Buffer\n本轮上下文，分钟级"] --> L1["L1 Session Memory\n会话摘要，小时级"]
  L1 --> L2["L2 Episodic Memory\n播放/反馈/上传/生成历史，天到周"]
  L2 --> L3["L3 Profile Memory\n稳定偏好/禁忌/睡眠习惯，周到月"]
  L2 --> L4["L4 Catalog Memory\n资产质量/标签/命中表现"]
  L3 --> Prompt["Hermes Prompt Context\n按需检索注入"]
  L4 --> Prompt
  L1 --> Prompt

  L1 --> NREM["NREM Consolidation\n压缩与合并"]
  L2 --> NREM
  NREM --> Gate["Memory Gate\n证据/隐私/安全/过期"]
  Gate --> L3
  Gate --> L4

  L2 --> REM["REM Dream Simulation\n模拟新任务和边界 case"]
  L3 --> REM
  L4 --> REM
  REM --> Product["L5 Product Memory\n测试集/Skill建议/工具缺口"]
  Product --> Prompt
```

### 目标态新增职责

| 模块 | 负责什么 | 保护边界 |
| --- | --- | --- |
| `floppy-memory-weaver` | 会话结束后整理短期记忆，合并重复偏好，标记冲突和过期信息 | 不能把单次表达直接写成长期事实 |
| `floppy-dream-loop` | 在空闲窗口模拟未来请求、失败 case、内容缺口和 Skill 改写建议 | Dream 结果默认是候选假设，不直接影响线上决策 |
| `MemoryStoreService` | 管理 L0-L5 记忆读写、TTL、证据计数、隐私过滤 | 所有长期写入必须可追溯到事件证据 |
| `DreamRunner` | 按预算触发 NREM/REM 批处理，记录 token 成本和产物 | 用户活跃、预算不足或安全风险时跳过 |
| `Evaluator` | 审核 Dream 产物是否能进入画像、目录记忆或产品待办 | 拦截幻觉、过拟合、隐私和高刺激内容 |

## 当前数据流与状态

```mermaid
erDiagram
  users ||--o| user_profiles : owns
  users ||--o| user_questionnaires : answers
  users ||--o{ generation_jobs : requests
  users ||--o{ playback_history : listens
  users ||--o{ uploads : owns
  audio_assets ||--o{ generation_jobs : output
  audio_assets ||--o{ playback_history : played
  audio_assets ||--o{ remix_jobs : voice_or_output
  audio_scripts ||--o{ generation_jobs : script
  uploads }o--o| audio_assets : generated_asset

  users {
    string id
    datetime created_at
  }
  user_profiles {
    string user_id
    json preferences
    string segment
    int profile_version
  }
  audio_assets {
    string id
    string type
    string object_key
    json tags
    string safety_status
  }
  generation_jobs {
    string id
    string status
    string cache_key
    json directive_json
    string asset_id
  }
  playback_history {
    string id
    string user_id
    string asset_id
    string feedback_type
    float progress
  }
  uploads {
    string id
    string file_type
    string object_key
    string generated_asset_id
  }
```

## 当前算法职责拆分

| 模块 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| `floppy-voice-dialog` | 判断语音是聊天、追问、音频请求还是改当前播放 | 不检索资产，不生成音频 |
| `floppy-sleep-audio` | 结构化搜索计划、播放/生成/混音决策 | 不直接写文件，不绕过后端安全/预算 |
| `AssetCatalogService` | 执行 filters、排序候选、回显 query analysis | 不理解中文语义，不做推荐策略 |
| `GenerationService` | job 创建、缓存、预算、后台生成状态 | 不决定用户到底想要什么 |
| `SleepAudioWorkflowService` | 脚本、TTS/环境音、资产入库 | 不做用户对话路由 |
| `ScriptGuard` | 安全、低刺激、停顿质量、成本风险 | 不替代 Hermes 的意图判断 |
| `PlaybackControl` | 播放开始、反馈、active playback、历史记忆 | 不选择内容 |

## 一句话总结

当前在线架构是“薄后端规则 + Hermes 意图判断 + Floppy 强执行边界”。
目标态架构再加一条“离线 Dream Loop + 多层记忆”的学习回路：

```text
用户自然语言
  -> Hermes 识别意图和选择 Skill
  -> Floppy 执行资源检索、生成、混音、安全和状态管理
  -> 客户端播放资产或轮询异步任务

会话结束/低峰窗口
  -> NREM 整理会话、播放反馈和失败任务
  -> REM 模拟未来请求、边界 case 和内容缺口
  -> Evaluator 审核后写入长期记忆、测试集或产品待办
```
