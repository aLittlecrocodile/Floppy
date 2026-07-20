# Unwind Skill 体系扩展设计

> 状态:设计稿(未实施)。本文档回答两个问题:
> ① 对话记忆会不会"爆"、要不要做压缩;② 产品从"助眠 App"升级为"缓解焦虑陪伴 App",智能体应该长出哪些 skill。

## 1. 背景

当前 Hermes 决策层只有 5 个 action(`chat / play_asset / generate_job / remix_current / no_match`),全部围绕"音频"这一种产物。产品定位是**缓解焦虑的睡前陪伴**,不只是放音频——智能体应该具备一些轻量、即时、有陪伴感的能力,让对话不单调。

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

### 3.2 Skill 清单(按优先级)

#### S1 `weather_brief` — 睡前天气(轻量工具型,首推)

- **场景**:"明天要不要带伞?""今晚冷不冷?" 睡前高频小需求;还能反向联动音频:"今晚有雨,要不要听着真雨声入睡?"→ 顺势 `play_asset` 雨声资产。
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

### 3.3 分期

| 期 | 内容 | 理由 |
|---|---|---|
| 一期 | S1 天气 + S2 CBT 引导 | 一个工具型 + 一个对话型,直接体现"不只是放音频";S2 是产品明确要的 |
| 二期 | S3 定时 + S4 偏好速记 | 需要前端/模型字段配合,打包一起改契约 |
| 观察 | S5 放松引导 | 先靠 prompt 免费获得,看触发数据再投入 |

### 3.4 测试策略

沿用 `tests/test_showcase.py` 模式:fake Hermes client 返回构造好的 `HermesDecision`,断言 `_execute_decision` 的响应字段与事件落库。每个新 action 至少覆盖:正常路径、缺参降级(如 S4 非白名单字段被拒)、S2 危机信号触发 `crisis_flag`。

## 4. 明确不做的

- 长期记忆/用户画像系统(Hermes 自带压缩兜底,产品决定不做深);
- MCP 多步工具调用(与"前台秒回"约束冲突,skill 均为单步);
- 情绪日记、睡眠报告等重运营功能(等轻量 skill 验证后再议)。
