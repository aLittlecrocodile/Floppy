# Unwind Skill 体系扩展设计

> 状态:设计稿(未实施)。**定位基线:Unwind 是减压产品,不是催眠/助眠产品——睡前只是场景之一,skill 触发与文案都不以"晚安/入睡"为中心。**本文档回答两个问题:
>
> ① 对话记忆会不会"爆"、要不要做压缩;② 产品从"助眠 App"升级为"全天候减压陪伴 App",智能体应该长出哪些 skill。

## 1. 背景

当前 Hermes 决策层只有 5 个 action(`chat / play_asset / generate_job / remix_current / no_match`),全部围绕"音频"这一种产物。产品定位是**帮工作人群随时把压力降下来的减压陪伴**,不只是放音频——智能体应该具备一些轻量、即时、有陪伴感的能力,让对话不单调。

本轮方向(已与产品对齐):

- **轻量优先**:做"看天气"这类简单、见效快的小能力,不做深度长期记忆型功能;
- 增加一个对话型 skill:**CBT 式认知重构引导**;
- 记忆机制**暂不改动**(调研结论见下)。

## 2. 记忆机制调研结论:暂无爆对话风险

| 路径 | 机制 | 结论 |
|---|---|---|
| 语音对话(`DialogLLM`) | 滑动窗口,只取最近 8 轮(`config.py` `dialog_history_max_turns=8`,`dialog_llm.py _build_messages`) | 安全,不会爆;超窗信息直接丢弃(无摘要) |
| Hermes 决策(`/agent/decide`) | 历史托管在 Hermes 侧,`conversation: floppy-agent:{user_id}` 永不轮换 | **安全**:Hermes agent 运行时内置 `ContextCompressor` —— token 预算启发式压缩 + `context_overflow` 时自动压缩重试 + 长会话自动轮换 continuation id。API server(`/v1/responses`)走同一运行时 |

实证位置(hermes-agent 0.18.2,homebrew 安装):

- `agent/agent_runtime_helpers.py:1201` — agent 持有 `context_compressor`,可配置独立压缩模型;
- `agent/bedrock_adapter.py:1267` — `context_overflow` → "agent should compress context and retry";
- `hermes_cli/web_server.py:3788` — 长会话 "auto-compresses into a fresh continuation id";
- `hermes_cli/partial_compress.py` 模块注释 — 确认存在 `/compress` 全量压缩 + 自动 token 预算尾部保护。

**残留风险(接受,不处理)**:压缩时保留哪些信息由 Hermes 内部启发式决定,Floppy 无法控制,可能丢失早期用户偏好信息。若未来"越用越懂你"成为重点,再评估把记忆收回 Floppy 端自管。

## 3. Skill 体系设计

### 3.1 扩展架构:沿用现有 action 分发,不上 MCP

新增 skill = 三处改动,模式与现有 5 个 action 完全一致:

1. `services/hermes_agent.py`:`_ACTIONS` 集合 + `_HERMES_DECISION_INSTRUCTIONS` prompt 里的 action 说明 + `_execute_decision` 里一个分支;
2. `models.py`:`HermesDecision` / `AgentDecideResponse` 按需加字段(尽量复用现有 `reply/reasons/tool_calls`);
3. `docs/contracts/hermes_agent_runtime.md`:契约文档同步;前端 `showcase_script.py` 按 action 渲染。

不引入 MCP 多步工具调用:决策路径要求"前台秒回"(单次 LLM 调用),本轮 skill 都是单步动作,现有分发模式够用。

### 3.2 Skill 清单

全景一览(S1-S5 为第一批,S6-S13 为扩充批;"改动量"指后端改动):

| # | Skill | 类型 | 一句话 | 改动量 |
|---|---|---|---|---|
| S1 | `weather_brief` | 工具 | 天气速报,顺势联动雨声等资产 | 小(新服务) |
| S2 | `reframe_thought` | 对话 | CBT 式认知重构引导 | 小(prompt+action) |
| S3 | `sleep_timer` | 控制 | 定时停播/音量渐弱 | 小(前端执行) |
| S4 | `update_preference` | 记忆 | "别放男声"写回 profile | 小 |
| S5 | `relax_tip` | 对话 | 即时呼吸/着地引导 | 仅 prompt |
| S6 | `worry_parking` | 仪式 | 烦恼寄存:把反刍的担心"存起来",到点再还 | 小(复用 events) |
| S7 | `gratitude_moment` | 仪式 | 今日三件好事 | 小(复用 events) |
| S8 | `mood_checkin` | 仪式 | 每日心情打卡+打分 | 极小(端点已存在) |
| S9 | `listen_recap` | 工具 | "这周来喘了 3 次气":收听回顾 | 小(复用播放历史) |
| S10 | `counting_ritual` | 仪式 | 数息/数羊,让脑子停下来 | 仅 prompt |
| S11 | `comfort_card` | 仪式 | 安心签:收尾时的一句话卡片 | 仅 prompt |
| S12 | `encourage_me` | 对话 | "夸夸我":定向鼓励 | 仅 prompt |
| S13 | `destress_knowledge` | 对话 | 减压小知识问答(含睡眠) | 仅 prompt |

#### 分类说明

- **工具型**(S1/S9):给对话提供"聊天之外的实用感",数据都在本地或免费 API。
- **对话型**(S2/S5/S12/S13):零新基建,纯 prompt 工程,靠决策指令里的触发信号和话术模板区分。
- **仪式型**(S6/S7/S8/S10/S11):减压 App 的差异化所在——把心理学上有效的"减压小仪式"做成可重复的互动,让用户每天有理由回来。全部复用 `record_event`/checkin 现有表。
- **控制/记忆型**(S3/S4):补齐播放体验闭环。

### 3.2.1 第一批详述(按优先级)

#### S1 `weather_brief` — 天气速报(轻量工具型,首推)

- **场景**:"明天要不要带伞?""今晚冷不冷?" 高频小需求;还能反向联动音频:"外面正好在下雨,要不要听会儿真雨声?"→ 顺势 `play_asset` 雨声资产。
- **实现**:新增 `services/weather.py`,调用免费天气 API(推荐 Open-Meteo,无需 key);城市来源:profile 加 `city` 字段(用户说"我在杭州"时由 Hermes 写入,见 S4)。结果注入决策 prompt 的 context(`_build_decision_prompt` 加 `weather` 字段),Hermes 在 reply 里自然引用——**不需要新 action**,chat 就能说天气;仅当需要实时查询时加 `get_weather` 分支。
- **改动面**:weather.py 新服务 + prompt context 拼装 + config 加开关。最小。

#### S2 `reframe_thought` — CBT 式认知重构引导(对话型,产品已选)

- **场景**:用户表达灾难化/绝对化想法("我肯定要被裁了""我什么都做不好")时,不直接安慰,而是温柔引导换角度:"最坏的情况真的会发生吗?""有没有一次你其实做成了的?"
- **实现**:本质是 **prompt 工程 + 一个新 action**。`_ACTIONS` 加 `reframe_thought`,prompt 里给出触发信号(灾难化、以偏概全、"肯定/永远/全都"类措辞)和引导话术风格(苏格拉底式提问,每轮只问一个问题,不说教)。执行侧与 `chat` 相同(纯 reply,无资产操作),单独立 action 是为了:观测(tool_calls 里可见)、前端可做差异化展示(如柔和的引导卡片)、后续可统计触发率。
- **安全边界(必须写进 prompt)**:不自称心理咨询/治疗;不做诊断;用户表露自伤/危机信号时,停止引导,回复关怀 + 提示求助渠道(如心理援助热线),并触发 `crisis_flag` 事件落库(复用 `record_event`)。
- **改动面**:hermes_agent.py(action + prompt)+ 事件埋点。无新服务。

#### S3 `sleep_timer` — 定时停止/渐弱(播放控制型)

- **场景**:"播 20 分钟就停""声音慢慢变小"。助眠刚需,改动小。
- **实现**:新 action `sleep_timer`,决策输出 `timer_sec` 字段;执行侧不需要后端计时——把 timer 作为响应字段回给前端,由播放器本地执行(倒计时+音量渐弱)。后端只落一条 event 用于观测。
- **改动面**:HermesDecision 加 `timer_sec`、AgentDecideResponse 加 `timer_sec`、prompt 说明、前端播放器支持。

#### S4 `update_preference` — 偏好速记(轻量记忆,非长期记忆系统)

- **场景**:"别放男声""我不喜欢雷声""我在杭州"。说一次,写进 profile,下轮生效——这不是深度记忆系统,只是把现有 `UserProfile` 字段的更新入口交给 Hermes。
- **实现**:新 action `update_preference`,决策输出 `profile_patch`(白名单字段:`preferred_voice_style / disliked_elements / city` 等);执行侧调 `repository.upsert_profile` 打补丁,reply 确认("好,以后不放雷声了")。profile 本来就每轮进决策 prompt,自动闭环。
- **改动面**:models.py profile 加 1-2 字段、hermes_agent.py 分支、repositories 复用现有 upsert。

#### S5 `relax_tip` — 即时放松引导(可并入 chat,最低优先)

- **场景**:"我现在很紧张怎么办" → 用一段 4-7-8 呼吸或 5-4-3-2-1 着地练习的**文字/语音引导**即时响应,不生成音频文件、不排队。
- **实现**:先不做独立 action——在 chat 的 prompt 里内置 2-3 个引导脚本模板,Hermes 直接在 reply 里带出来即可(语音路径由现有 TTS 流式管线朗读)。数据验证有需求后,再升级为带节奏控制的独立 skill。
- **改动面**:仅 prompt。

### 3.2.2 扩充批详述

#### S6 `worry_parking` — 烦恼寄存(仪式型,扩充批首推)

- **场景**:用户在休息时段反刍("明天的汇报怎么办")——会议间隙、下班路上、睡前都会发生。心理学上的"担忧延迟"(worry postponement)技术:把担心的事说出来、"存起来",约定之后再处理——给大脑一个"可以放下了"的仪式。
- **对话流**:用户倾诉 → Hermes 识别为"反刍未来的事"→ reply:"我帮你把这件事记下来了,这段时间它归我保管。" 用户下次回来时可自然带一句"上次寄存的事,现在还压着你吗?"
- **实现**:新 action `worry_parking`,执行侧 `record_event(event_type="worry_parked", payload={"text": ...})`;"次日回访"不需要调度器——决策 prompt 的 context 里注入最近 1-2 条未销账的 worry(新增一个 `list_recent_events(type)` 查询即可),Hermes 自己决定要不要提。
- **改动面**:action 分支 + events 查询注入 prompt。**与 S2 CBT 引导是天然组合**:寄存时若发现灾难化想法,可衔接 reframe。

#### S7 `gratitude_moment` — 今日三件好事(仪式型)

- **场景**:经典积极心理学练习("Three Good Things"):在一天收尾时回忆 1-3 件小确幸,被验证能改善情绪与睡眠质量。用户说"今天好累/今天糟透了"之后,Hermes 可轻轻发起:"那有没有哪怕一件还不错的小事?"
- **实现**:同 S6 模式:action + `record_event("gratitude", ...)`。积累一周后 Hermes 可在 reply 里回放("这周你记下了 5 件好事,周三那杯咖啡我还记得")——同样靠 prompt 注入最近 events,不建报表系统。
- **改动面**:action 分支 + events 查询。与 S6 共享基建,两个 skill 一份成本。

#### S8 `mood_checkin` — 每日心情打卡+打分(仪式型,改动最小)

- **场景**:"今天感觉怎么样,1 到 10?" 一句话完成打卡。连续打卡数即陪伴感("这是我们一起喘口气的第 12 天")。
- **实现**:**checkin 端点已存在**(`POST /users/{id}/profile/checkin`),只需让 Hermes 能触发它:action `mood_checkin` + 决策输出 `mood_score`,执行侧调现有 repo 方法。连续天数注入 profile context 即可被 reply 引用。
- **改动面**:极小,基本是接线。

#### S9 `listen_recap` — 收听回顾(工具型)

- **场景**:"我最近都听了什么?" / 每周一次 Hermes 主动轻提:"这周你来喘了 3 次气,每次都选雨声,看来它最能安抚你。" 用数据体现"它了解我",替代做深长期记忆。
- **实现**:`list_playback_history` 已存在;新增一个聚合查询(按类型/时长汇总最近 7 天),结果注入决策 prompt context,chat 即可引用——**可以不加新 action**,先做纯 context 注入版。
- **改动面**:一个聚合查询 + prompt 拼装。

#### S10 `counting_ritual` — 数息/数羊(仪式型,纯 prompt)

- **场景**:"陪我数个数,让脑子停下来"(白天)或"睡不着,陪我数羊吧"(睡前)。Hermes 用缓慢、重复、渐弱的节奏引导数呼吸或数羊("一…… 吸气…… 二…… 呼气……"),语音路径由现有 TTS 流式管线朗读,天然适合。
- **实现**:仅 prompt:给出节奏模板(短句、多停顿、句间留白),文字端渐隐由前端样式配合。不落库、无新 action(归入 chat 或复用 S5 的引导框架)。
- **改动面**:仅 prompt(语音端可调 TTS 语速参数,若 provider 支持)。

#### S11 `comfort_card` — 安心签(仪式型,纯 prompt)

- **场景**:对话收尾时的固定小仪式:一句为这次对话定制的安心话——"去忙了"时是"这一仗你打得动",睡前是"剩下的交给睡眠"。结合聊过的内容生成,有"专属感";前端渲染成可保存/分享的卡片。
- **实现**:仅 prompt:在决策指令中约定"用户告别/对话自然收尾时,reply 以一句安心签结束"。前端识别收尾场景做卡片样式。
- **改动面**:prompt + 前端卡片(可选)。

#### S12 `encourage_me` — 夸夸我(对话型,纯 prompt)

- **场景**:"今天被老板骂了,夸夸我吧。" 定向鼓励,基于用户刚说的具体事实夸(不是空洞彩虹屁);若 S6/S7 的 events 里有素材,夸得更有依据。
- **实现**:仅 prompt:触发词("夸夸我/鼓励一下/安慰我")+ 话术要求(具体、真诚、不超过三句)。
- **改动面**:仅 prompt。

#### S13 `destress_knowledge` — 减压小知识(对话型,纯 prompt)

- **场景**:"为什么一焦虑就胃疼?""深呼吸真的有用吗?""为什么越累越睡不着?" 用温和科普替代生硬拒答,建立专业信任感。
- **实现**:仅 prompt:约定回答风格(两三句、口语化、不装医生),并明确边界——涉及疾病诊断/用药一律建议就医,不给医疗建议。
- **改动面**:仅 prompt。

### 3.2.3 Skill 规范文件

全部 13 个 skill 已按 Hermes skill 规范落成文件:`hermes/skills/unwind-<name>/SKILL.md`(与 `floppy-sleep-audio` 同格式:触发时机 → 行为要求 → 输出 JSON → 决策优先级)。纯 prompt 型 skill 走现有 `chat` action、当前即可生效;带新 action 的 skill 在文件中注明了后端支持状态(phase)与"后端未支持时降级为 `chat`"的规则,契约字段(`mood_score`/`worry_text`/`gratitude_items`/`timer_sec`/`fade_out`/`profile_patch`)以 SKILL.md 为准。

### 3.3 分期

| 期 | 内容 | 理由 |
|---|---|---|
| 一期(纯 prompt 包) | S5 放松引导 + S10 数息 + S11 安心签 + S12 夸夸 + S13 减压知识 | **五个 skill 一次 prompt 改动**,零新代码、零风险,立刻让对话不单调——性价比最高,先发这批 |
| 二期(体验闭环) | S1 天气 + S2 CBT 引导 + S8 心情打卡 | 一个新服务(天气)+ 两个小 action;S2 是产品明确要的,S8 基本是接线 |
| 三期(仪式闭环) | S6 烦恼寄存 + S7 三件好事 + S9 收听回顾 | 共享"events 写入 + prompt 注入"一套基建,打包做 |
| 四期(契约变更) | S3 定时 + S4 偏好速记 | 需要前端播放器/模型字段配合,单独排期联调 |

### 3.4 测试策略

沿用 `tests/test_showcase.py` 模式:fake Hermes client 返回构造好的 `HermesDecision`,断言 `_execute_decision` 的响应字段与事件落库。每个新 action 至少覆盖:正常路径、缺参降级(如 S4 非白名单字段被拒)、S2 危机信号触发 `crisis_flag`。

## 4. 厂内能力整合(OneTool)

> 已与产品对齐:方向全部通过,授权范围可以放开做。黑客松演示优先。

本地已验证的厂内 skill(OneTool 平台,SKILL.md + 脚本格式,与 Hermes skill 同构):`get-ugate-token`(认证地基)、`enterprise-search`(内搜/会议/周报/OKR/通讯录 9 个脚本)、`daily-report`(会话痕迹→日报→写入如流知识库)、`ku-doc-manage`(知识库 CRUD)、`skill-recommender`(远端 skill 目录)。

接线模式(与现有架构一致,不引入新机制):**轻数据 context 注入**(日历密度、天气、OKR 进度→决策 prompt),**重动作异步 job**(周报草稿、知识库写入→队列+轮询)。

六个整合方向(优先级序):

1. **下会缓冲舱**(calendar_sense):日程密度感知,连轴会后主动递 90 秒呼吸;
2. **周报代写**(weekly_ghostwriter):daily-report 模式平移到周报——把压力源直接消掉;
3. **OKR 实据重构**(okr_reframe):reframe_thought 引用真实 KR 进度,让 CBT 有实锤;
4. **内搜兜底**(neisou_answer):流程类焦虑给确定性答案+可求助入口;
5. **情绪账本**(ku_journal):打卡/寄存同步到用户私人知识库表格;
6. **安心签送同事**(card_to_peer):通讯录+如流消息,减压社交化。

**黑客松演示实现**(已落地,`floppy_backend/showcase_skills.py`):`/showcase/skills` 输出全量技能矩阵(前端"技能矩阵"面板,live/demo/planned 三态,决策触发实时脉冲);`/showcase/chat` 前置确定性技能路由,1/2/3/4 号方向以真实 tool_calls 轨迹 + `skill_card` 结构化卡片(周报草稿/OKR 进度条/内搜答案)演示;`/showcase/nudge` 提供"刚下会/周报未交"主动关怀情境,由前端"情境演示"入口触发。演示路由在 Hermes 之前短路,舞台环境无网络依赖;非演示请求照常走 Hermes。

## 5. 明确不做的

- 长期记忆/用户画像系统(Hermes 自带压缩兜底,产品决定不做深);
- MCP 多步工具调用(与"前台秒回"约束冲突,skill 均为单步);
- 完整的情绪日记/睡眠报告等重运营功能(S8 打卡、S9 回顾是它们的轻量替身:一句话交互 + prompt 注入,不做报表页面和趋势分析,验证有需求后再升级)。
