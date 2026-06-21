# Floppy Backend And Algorithm Research

更新时间：2026-06-21  
范围：后端、音频资产库、AI 生成链路、用户画像、推荐算法、Agent/工作流框架选型

## 结论摘要

Floppy 的后端不建议从“一个大 Agent”开始。更稳妥的 MVP 架构是：

1. 云上音频资产库做中心资产层，存 AI 预生成音频、按需生成音频、元数据、生成参数和版权/安全状态。
2. 推荐服务先做“画像规则召回 + 向量相似召回 + 可解释重排 + 生成兜底”，不要一开始上复杂深度推荐。
3. 生成服务异步化，优先命中缓存；特殊需求进入生成队列；生成完成后入库，后续复用。
4. 用户画像先分两层：冷启动问卷画像和行为画像。画像只提供推荐和生成参数，不直接替代用户明确需求。
5. Agent 框架层建议保持可替换。MVP 可以用普通后端编排 + 小型 Agent SDK；不要把音频生产、推荐、播放状态和用户数据都绑死在某个 Agent 框架里。

建议技术路线：

- 后端：Python FastAPI 或 Node.js/NestJS 均可，算法侧更建议 Python。
- 存储：对象存储保存音频文件，PostgreSQL 保存业务数据，Redis 保存热缓存/任务状态，向量库先用 pgvector，数据量变大后再迁到 Milvus/Qdrant/VikingDB 等专用向量库。
- 生成：TTS/音乐/ASMR/故事脚本分成独立 provider，统一封装成 `AudioGenerationProvider`。
- 推荐：先用可解释 pipeline，不直接上黑盒深度模型。
- Agent 框架：优先候选 VeADK、OpenAI Agents SDK、LangGraph；短期不建议使用即将下线或产品边界不稳定的可视化 Agent Builder 作为核心依赖。

## 目标能力拆解

### 1. 云上音频库

音频库要解决三类问题：

- 低延迟分发：用户睡前场景不能等待长时间生成，常见需求必须直接播放。
- 资产复用：AI 内容一次生成，多次消费，降低边际成本。
- 可控治理：每条音频都要知道来源、生成参数、安全状态、适用用户和质量评分。

建议把音频资产拆成两张核心表：

`audio_asset`

| 字段 | 说明 |
| --- | --- |
| id | 音频资产 ID |
| type | white_noise / music / asmr / story / meditation / podcast_digest |
| title | 展示标题 |
| object_key | 对象存储路径 |
| duration_sec | 时长 |
| language | 语言 |
| voice_id | TTS 音色或声音配置 |
| prompt_hash | 生成 prompt 的 hash |
| content_hash | 内容文本或音频指纹 hash，用于去重 |
| mood_tags | 放松、焦虑缓解、温暖、安静等标签 |
| sleep_stage | 入睡前、放松期、深睡背景等 |
| user_segment_tags | 适合的人群标签 |
| safety_status | pending / approved / rejected |
| quality_score | 人工或模型评分 |
| created_by | pregen / ondemand / uploaded |
| created_at | 创建时间 |

`audio_generation_job`

| 字段 | 说明 |
| --- | --- |
| id | 生成任务 ID |
| user_id | 请求用户 |
| request_text | 用户原始需求 |
| normalized_intent | 归一化意图 |
| status | queued / generating / succeeded / failed |
| provider | TTS/音频生成供应商 |
| asset_id | 成功后关联资产 |
| error_code | 失败原因 |
| cost_estimate | 估算成本 |
| latency_ms | 生成耗时 |

对象存储层建议使用：

- 国内优先：火山引擎 TOS、阿里云 OSS、腾讯云 COS。
- 海外或通用：AWS S3、Cloudflare R2。
- 统一要求：支持私有 bucket、签名 URL、生命周期管理、CDN 加速、对象元数据。

文件路径建议：

```text
audio/
  pregen/{type}/{asset_id}.{ext}
  ondemand/{yyyy}/{mm}/{dd}/{user_hash}/{job_id}.{ext}
  preview/{asset_id}_30s.{ext}
```

### 2. 缓存命中与按需生成

用户发起需求后，后端应走四级决策：

1. 精确缓存命中：同样的标准化需求、音色、语言、时长、场景，直接返回已有音频。
2. 近似缓存命中：用 embedding 查找语义相近的音频，再根据用户画像和音频标签重排。
3. 模板化生成：需求落在常见模板里，只替换少量槽位，比如“雨声 + 低语引导 + 20 分钟”。
4. 全量按需生成：用户要求特别具体，比如“用温柔男声讲一个关于海边书店的故事，背景是轻微雨声”。

缓存 key 不要只用用户原文。建议使用归一化后的结构：

```json
{
  "intent": "sleep_story",
  "language": "zh-CN",
  "duration_bucket": "15-20min",
  "voice_style": "warm_female",
  "background": "rain_soft",
  "mood": ["anxiety_relief", "safe"],
  "content_topic": ["sea", "bookstore"]
}
```

缓存命中策略：

- `prompt_hash` 用于精确命中。
- `embedding` 用于近似命中。
- `content_hash` 用于去重。
- `quality_score` 和用户反馈用于排序。
- 针对睡前内容，宁可返回稳定、低刺激内容，也不要为了“相关性”返回过于兴奋或信息密度过高的内容。

生成链路建议异步化：

```text
API Gateway
  -> Request Normalizer
  -> Cache Matcher
    -> hit: return signed playback URL
    -> miss: enqueue generation job
  -> Generation Worker
  -> Safety/Quality Check
  -> Object Storage + Metadata DB
  -> Notify client / return polling result
```

对于用户体验，MVP 可做两种返回：

- 快速兜底：先播放一条相似缓存音频，同时后台生成专属版本。
- 等待生成：对用户明确要求“专门生成”的内容，返回任务进度。

### 3. 用户画像与分层

Floppy 是睡眠场景，画像必须克制。不要过早收集敏感健康信息，不要做医疗诊断。

MVP 用户画像建议分三类字段：

基础偏好：

- 音频类型偏好：白噪音、轻音乐、ASMR、故事、冥想、播客摘要。
- 音色偏好：男声、女声、童话感、自然、低语。
- 背景声偏好：雨声、海浪、风声、壁炉、森林、无背景声。
- 时长偏好：5、10、20、30 分钟。

状态画像：

- 睡前压力：低/中/高。
- 焦虑程度：低/中/高。
- 平均入睡时长。
- 最近睡眠满意度。
- 当晚心情标签。

行为画像：

- 播放完成率。
- 跳出时间点。
- 收藏/不喜欢。
- 是否中途互动。
- 是否重复收听。
- 入睡后是否自动停止。

初始分层可以用规则，不必一开始训练聚类模型：

| 分层 | 特征 | 推荐倾向 |
| --- | --- | --- |
| 焦虑舒缓型 | 压力/焦虑高，入睡时间长 | 冥想引导、低语、稳定背景声 |
| 声音陪伴型 | 喜欢故事/聊天，互动多 | 睡前故事、轻量陪伴、连续剧情 |
| 环境助眠型 | 喜欢白噪音，互动少 | 雨声、海浪、风声、长时播放 |
| 内容转化型 | 输入书籍/文章/播客需求 | 文章摘要、播客精简、TTS 改写 |
| 快速入睡型 | 播放时长短，完成率高 | 短音频、固定 routine、少打扰 |

画像更新建议：

```text
问卷画像权重：冷启动高，后续逐步降低
行为画像权重：随播放和反馈逐步升高
当晚状态权重：只影响当天推荐，不永久改写长期偏好
```

### 4. 推荐算法

推荐系统先做可解释 pipeline：

```text
Candidate Generation
  1. 画像规则召回
  2. 标签召回
  3. 向量相似召回
  4. 热门高质量召回
  5. 新内容探索召回

Ranking
  score = user_preference_match
        + intent_match
        + quality_score
        + completion_rate_score
        + freshness_score
        - overstimulation_penalty
        - repeated_recently_penalty

Fallback
  no good candidate -> trigger generation
```

MVP 打分可以先使用手写权重：

| 因子 | 含义 |
| --- | --- |
| `profile_match` | 与长期偏好匹配 |
| `state_match` | 与当晚压力/焦虑/心情匹配 |
| `intent_match` | 与用户明确需求匹配 |
| `quality_score` | 内容质量 |
| `sleep_safety_score` | 是否低刺激、低信息密度、少突兀变化 |
| `novelty_score` | 避免总是推同一条 |
| `cost_score` | 命中缓存优先，降低生成成本 |

短期不建议直接上复杂深度推荐，原因：

- 初期数据量小，深度模型容易过拟合。
- 睡前场景对“安全、稳定、可解释”要求高于纯点击率。
- 推荐失败的代价不是少一次点击，而是打扰用户入睡。

中期可演进为：

- 用双塔模型做用户和音频 embedding。
- 用 contextual bandit 做探索/利用平衡。
- 用学习排序模型替代手写权重。
- 加入 session-level 推荐，识别用户今晚处于“想被陪伴”还是“只想安静播放”。

关键指标：

| 指标 | 说明 |
| --- | --- |
| 推荐点击率 | 是否愿意开始播放 |
| 播放 30 秒留存 | 是否明显不合适 |
| 完播率 | 对短内容有效 |
| 中途停止率 | 是否打扰 |
| 重复收听率 | 是否形成偏好 |
| 入睡前互动次数 | 陪伴需求强弱 |
| 次日满意度 | 最核心的质量反馈 |
| 生成命中率 | 缓存复用效率 |
| 平均生成成本 | 成本控制 |

### 5. AI 生成与安全质量

睡前音频生成不只是 TTS。建议拆成四步：

1. 需求理解：把用户原文转为结构化生成参数。
2. 内容脚本：生成睡前故事、冥想词、播客摘要等文本。
3. 音频合成：TTS、背景声混音、音量归一化、淡入淡出。
4. 安全质量检查：低刺激、无恐怖/惊吓/负面强化、无医疗承诺。

生成规则：

- 明确禁止恐怖、惊悚、冲突强、悬疑强内容。
- 避免过多事实密度、任务提醒和强互动提问。
- 对焦虑用户避免“你必须睡着”等压力表达。
- 情绪疏导只能做支持性表达，不能做医疗诊断或治疗承诺。
- 对用户明显严重心理危机内容，要走安全兜底和求助建议。

TTS/音频 provider 要抽象：

```text
AudioGenerationProvider
  - synthesize_text(script, voice, speed, background)
  - generate_background_sound(prompt, duration)
  - mix_tracks(voice_track, background_track)
  - estimate_cost(request)
```

候选供应商：

- OpenAI：适合多模态 Agent、语音和实时交互能力，但国内网络、成本和合规需要确认。
- 火山引擎：与 VeADK、AgentKit、TOS、豆包模型生态一致，国内部署和企业资源更便利。
- Azure Speech：TTS 成熟、企业能力强。
- ElevenLabs / MiniMax：音色表现强，但要评估授权、成本、国内可用性和商用条款。

MVP 可以先只接一个 provider，但代码结构必须支持替换。

### 6. Agent/工作流框架调研

Floppy 的 Agent 需求不是“多 Agent 炫技”，而是稳定地完成：

- 需求理解。
- 内容生成。
- 推荐解释。
- 轻量陪伴对话。
- 任务编排和工具调用。
- 可观测、可评估、可回放。

#### VeADK

当前状态：可继续作为候选。调研发现 volcengine/veadk-python 在 2026-06-18 发布了 0.5.40，说明不是半年前停滞项目。README 显示其集成火山引擎能力，支持 Feishu bot channel、A2UI、VeFaaS 部署、PromptPilot 优化、AgentKit Runtime 等；`pyproject.toml` 依赖 Google ADK、LiteLLM、MCP、VikingDB、TOS、AgentKit SDK 等。

优点：

- 与火山引擎模型、TOS、VikingDB、AgentKit 生态契合。
- 如果团队已有 VeADK 经验，上手成本低。
- 有 Feishu channel，对内部 demo/运营调试方便。
- 有 AgentKit Runtime 部署方向。

风险：

- 生态相对 OpenAI/LangGraph 更小。
- 框架依赖较多，版本演进较快，需要锁版本。
- 如果未来不用火山生态，迁移成本可能偏高。

适用建议：

- 如果 Floppy 主要面向国内云和豆包/火山生态，VeADK 可以做 MVP Agent 层。
- 不建议让推荐、任务队列、音频资产库强依赖 VeADK；只把它放在“对话/内容生成编排层”。

#### OpenAI Agents SDK

当前状态：官方 Python SDK 仍活跃，GitHub release 在 2026-06-19 有 v0.17.6。适合用代码构建 Agent，有 handoff、guardrail、tracing、tool 调用等能力。需要注意：OpenAI 曾推出的部分 AgentKit 可视化能力正在进入下线周期，不能把长期核心架构绑在即将下线的 Builder/Evals 产品上。

优点：

- Agent 抽象清晰，工具调用和 tracing 适合后端调试。
- 与 OpenAI 模型、Realtime、语音能力衔接好。
- 文档和生态成熟度高。

风险：

- 国内网络、合规、成本和模型可用性需要确认。
- 如果 TTS/LLM 主力在火山，OpenAI SDK 不是最自然的底座。

适用建议：

- 适合做高质量原型或海外版本。
- 如果使用 OpenAI 实时语音对话，可优先评估。

#### LangGraph

优点：

- 擅长有状态工作流、可控图编排、human-in-the-loop。
- 比通用 Agent 更适合表达“推荐 -> 生成 -> 质检 -> 入库 -> 通知”的确定性流程。
- Provider 相对中立。

风险：

- 学习成本高于简单 SDK。
- 对移动端实时陪伴体验，需要额外封装会话层。

适用建议：

- 如果我们希望把“生成工作流”和“推荐/质检流程”画成明确状态机，LangGraph 很合适。
- 可以和 FastAPI + Celery/RQ 搭配。

#### Google ADK

VeADK 本身依赖 Google ADK，因此如果直接用 Google ADK，需要评估是否绕过 VeADK 的火山封装。它适合标准 Agent 编排，但对 Floppy 的国内云集成不如 VeADK 直接。

#### AutoGen / Microsoft Agent Framework

适合复杂多 Agent 协作和研究型场景。Floppy MVP 当前不需要多 Agent 互相辩论或复杂群聊式协作，不建议作为第一优先级。

#### Dify / Coze

适合快速搭 demo 和运营可视化流程，但后端核心推荐、资产库、生成缓存、质量治理不应完全放在低代码平台里。可作为运营后台或 prompt 调试工具，不建议做核心服务边界。

### 7. 推荐架构

```text
Mobile App
  -> API Gateway
  -> Auth/User Service
  -> Profile Service
  -> Recommendation Service
       -> PostgreSQL metadata
       -> Vector Store
       -> Redis hot cache
  -> Audio Service
       -> Object Storage
       -> CDN / signed URL
  -> Generation Service
       -> Queue
       -> LLM/TTS Provider
       -> Safety/Quality Checker
       -> Audio Asset Store
  -> Agent/Companion Service
       -> Agent SDK / workflow framework
       -> tools: recommend_audio, create_generation_job, record_todo
  -> Analytics/Event Pipeline
```

服务边界建议：

| 服务 | 职责 |
| --- | --- |
| User/Profile Service | 用户、问卷、画像、偏好 |
| Audio Asset Service | 音频元数据、签名 URL、播放权限 |
| Recommendation Service | 召回、排序、生成兜底决策 |
| Generation Service | 异步生成、混音、质检、入库 |
| Companion Agent Service | 轻量对话、需求理解、工具调用 |
| Event Service | 播放、反馈、睡眠报告事件 |

MVP 不一定物理拆成多个服务，但代码模块边界应按这个拆。

### 8. 数据闭环

必须从第一天埋点，否则推荐系统无法进化。

核心事件：

```text
onboarding_completed
recommendation_shown
recommendation_clicked
audio_play_started
audio_play_paused
audio_play_stopped
audio_completed
audio_liked
audio_disliked
generation_requested
generation_succeeded
generation_failed
sleep_session_started
sleep_session_ended
morning_feedback_submitted
```

次日反馈比当晚点击更重要。建议次日只问 1 到 3 个问题：

- 昨晚入睡是否更轻松？
- 这段声音是否适合你？
- 今晚还想听类似的吗？

### 9. MVP 开发计划

第一阶段：2 周内可验证

- 音频资产表和对象存储接入。
- 手工导入 30 到 100 条 AI 预生成音频。
- 问卷画像。
- 规则推荐。
- 播放事件上报。
- 简单按需生成任务，先不追求实时。

第二阶段：3 到 5 周

- embedding 近似召回。
- 音频标签体系。
- 生成缓存命中。
- 质量评分和安全检查。
- 用户反馈驱动重排。

第三阶段：6 到 8 周

- 个性化故事/冥想生成。
- 内容转睡前音频。
- Agent 陪伴对话。
- 任务队列和生成成本控制。
- 推荐 A/B 实验。

第四阶段：数据增长后

- bandit 探索策略。
- 学习排序。
- 用户/音频双塔模型。
- 更精细的睡眠报告。

### 10. 技术风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 生成延迟过高 | 睡前体验差 | 缓存优先、异步生成、播放兜底 |
| 生成成本不可控 | 商业不可持续 | 生成配额、缓存复用、热门需求预生成 |
| 推荐过度刺激 | 影响入睡 | sleep_safety_score、内容质检、黑名单 |
| 用户画像敏感 | 隐私与合规风险 | 最小化采集、不做医疗诊断、可删除 |
| 框架绑定过深 | 后期迁移困难 | Agent 层只做编排，核心业务服务框架无关 |
| 音频版权/音色授权 | 商用风险 | 记录来源和授权，避免未授权声音克隆 |
| 质量不可评估 | 推荐无法优化 | 从 MVP 第一天埋点和次日反馈 |

## 自审结论

本方案符合当前产品需求的地方：

- 覆盖了“云上音频库 + 缓存命中 + 特殊需求按需生成”的主链路。
- 把“以用户为中心”的画像、分层、推荐闭环拆成可实现模块。
- 推荐算法从可解释 MVP 开始，后续可演进到 bandit 和深度模型。
- 框架调研没有默认押注单一框架，VeADK 被保留为强候选，但避免把核心业务绑死。
- 架构能同时支持 App 形态和后续玩具硬件形态，因为播放 URL、推荐、生成、画像都在服务端。

需要进一步确认的地方：

- 目标部署云：火山、阿里、腾讯、AWS 或混合云。
- 第一版 TTS/音频供应商：这会影响成本、音色质量和合规。
- 是否必须支持实时语音对话；如果必须，框架和 provider 选型会明显变化。
- 是否已有内部用户体系和埋点平台。
- 产品是否面向中国大陆用户；如果是，OpenAI 能力只能作为参考或海外方案，不能默认作为生产依赖。

## 参考来源

已核对的一手资料：

- Floppy 产品文档：`/Users/aooway/Downloads/Floppy.md`
- VeADK GitHub README：`https://github.com/volcengine/veadk-python`
- VeADK 最新 release：`https://github.com/volcengine/veadk-python/releases/tag/0.5.40`
- VeADK `pyproject.toml`：`https://github.com/volcengine/veadk-python/blob/main/pyproject.toml`
- Volcengine AgentKit SDK README：`https://github.com/volcengine/agentkit-sdk-python`
- OpenAI Agents Python release：`https://github.com/openai/openai-agents-python/releases/tag/v0.17.6`
- OpenAI AgentKit/Agents 官方公告：`https://openai.com/index/introducing-agentkit/`
- OpenAI deprecations：`https://developers.openai.com/api/docs/deprecations`
- AutoGen GitHub：`https://github.com/microsoft/autogen`
- pgvector README：`https://github.com/pgvector/pgvector/blob/master/README.md`
- Milvus filtered search：`https://milvus.io/docs/filtered-search.md`
- Qdrant filtering/search docs：`https://qdrant.tech/documentation/search/filtering/`
- Redis vector search docs：`https://redis.io/docs/latest/develop/ai/search-and-query/vectors/`
- AWS S3 presigned URL docs：`https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html`
- AWS S3 lifecycle docs：`https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html`
- Alibaba Cloud OSS presigned URL docs：`https://www.alibabacloud.com/help/en/oss/user-guide/how-to-obtain-the-url-of-a-single-object-or-the-urls-of-multiple-objects`
- Volcengine TOS presigned URL docs：`https://www.volcengine.com/docs/6349/515810?lang=en`

这些来源用于确认框架活跃度、官方定位和生态关系。云存储、向量库、TTS 供应商的具体价格、地域、合规和 SLA 需要在确定云厂商后单独做选型表。
