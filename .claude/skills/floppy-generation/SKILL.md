---
name: floppy-generation
description: Floppy 助眠音频生成的"指挥手册"——智能体如何把用户需求提炼成结构化生成指令（GenerationDirective）并命令生成 workflow 写出个性化脚本，而不是套通用模板。涉及助眠音频生成、自定义故事/冥想/ASMR、缓存复用、内容要点编排时使用。
---

# Floppy 生成指挥（GenerationDirective）

## 这份文档解决什么

Floppy 的音频来源有两条：**命中已有资产**（首选）和**未命中→生成**。生成这条以前是
"normalizer 把用户原话压成几个标签 → script.py 套模板"，结果内容通用、会重复
（20 分钟冥想里同一句"把注意力带到双手/腹部/双腿"循环好几遍）。

现在的链路是：**智能体先想清楚，再指挥 workflow**。智能体把"用户需求 + 画像"提炼成一份
结构化的 `GenerationDirective`（含内容要点 outline），workflow 按要点用 LLM 写出贴合用户
的脚本。要点智能、成稿可控、可缓存复用。

## 决策：什么时候该生成

智能体决策入口是 `agent_graph`（`/agent/decide`）。路由顺序：

1. **remix 意图**（"加点雨声背景""背景音小一点"）→ 走 remix，不消耗生成额度。
2. **命中资产**（exact `prompt_hash` 缓存 / 向量+标签分数 ≥ 阈值）→ 直接播放，**不生成**。
3. **未命中 + 允许生成** → 创建生成任务，此时才组装 `GenerationDirective`。
4. 未命中 + 不允许生成 → no_match。

**核心原则：能命中就别生成。** 缓存命中直接调用，省钱省时。只有用户要的内容
（具体的故事/意象/主题）资产库里真的没有时，才生成。

## GenerationDirective：怎么组装

`floppy_backend/models.py:GenerationDirective`。智能体（`DirectivePlanner`，LLM）把用户原话 +
画像提炼成这份指令：

| 字段 | 含义 | 怎么填 |
|---|---|---|
| `intent` | 音频类型 | story / meditation / white_noise / music / asmr / podcast_digest，选最贴合用户想听的 |
| `tone` | 基调 | 如"温柔平静""安心绵长"，助眠场景永远低刺激 |
| `duration_sec` | 目标时长 | 用户明说（"20分钟"=1200）或按画像偏好（分钟×60） |
| `voice_style` | 音色 | gentle_female / warm_female / storyteller_female 等 |
| `content_brief` | 一句话主题 | 贴合用户原话概括这次生成什么 |
| `outline` | 分段要点 | **4-8 条**，把用户提的意象/人物/场景拆进去，按助眠节奏推进（开场轻→中段展开→结尾越来越静），**绝不重复同一画面** |
| `key_elements` | 必含意象 | 用户**点名**的具体东西（"外婆""老槐树""灯塔"），脚本必须出现；没点名就留空 |
| `confidence` | 置信度 | < 阈值（默认 0.5）则丢弃指令、走模板兜底 |

### outline 怎么写好（关键）

- **抓住用户的具体意象**：用户说"讲个关于外婆的院子和老槐树的故事"，outline 里必须有
  院子、老槐树、外婆，而不是泛泛的"一个安静的夜晚"。
- **按助眠节奏排**：第 1 条开场（轻、引入场景）；中间几条展开（画面缓慢推进）；
  最后 1-2 条收尾（越来越静、引导入睡）。
- **每条只讲一个画面**，不同条之间不重复意象或句式——这是解决"模板循环"的根本。
- **低刺激**：不要冲突、悬念、惊吓、医疗承诺、兴奋情绪。

## 数据流（代码层）

```
agent_graph._create_generation_job
  → DirectivePlanner.plan(request_text, profile_ctx)   # services/directive_planner.py
      → GenerationDirective（LLM 提炼；失败返回 None）
  → generation_service.enqueue_or_match(..., GenerationRequest(directive=...))
      → directive 持久化到 generation_jobs.directive_json（异步 worker 取回用）
  → workflow.prepare_script(..., directive)            # workflows/sleep_audio.py
      → SleepScriptService.generate(normalized, profile, directive)  # services/script.py
          ├─ directive.has_outline + 有 writer
          │     → LLMScriptWriter.write(...)            # services/script_writer.py
          │        要点→成稿（带 <#秒#> 停顿）→ 过 script_guard
          │        guard 不通过 → 回退模板
          └─ 否则 → 现有 _story/_meditation/_asmr 模板（兜底，永不破坏老路径）
  → TTS 合成 → 入库（prompt_hash = cache_key）
  → 下次同需求：search 精确命中 → play_asset，不再生成
```

## 缓存复用规则（重要）

- 生成产物入库时 `prompt_hash = cache_key`；下次同需求 `recommendation.search` 精确命中
  （score=1.0）→ 直接播放，**不调 LLM、不调 TTS、不走 workflow**。
- `cache_key` 已纳入 directive 的**稳定签名**（`GenerationDirective.cache_signature()`：
  intent/tone/duration/voice/content_brief/key_elements），**不含 outline 全文**——
  所以"相同需求"命中缓存、"不同需求"重新生成，而 LLM 写要点时的措辞微小漂移不会
  让缓存白白失效。
- 含义：换一个意象（"外婆的院子"→"海边灯塔"）→ cache_key 变 → 重新生成；
  同一意象再问一次 → 命中 → 直接调用。

## 兜底与配置

- **任何 LLM 环节失败都回退模板**：DirectivePlanner 失败→无 directive→模板；
  ScriptWriter 失败或 guard 不通过→模板。生成永远不崩。
- 开关：`FLOPPY_DIRECTIVE_PLANNER_ENABLED`（默认 true）。无可用 LLM key 时自动退化为
  纯模板生成。
- LLM 凭证复用 `FLOPPY_QUERY_PLANNER_*` / `FLOPPY_DIALOG_LLM_*`。
- 阈值/超时：`FLOPPY_DIRECTIVE_PLANNER_CONFIDENCE_THRESHOLD`、
  `FLOPPY_DIRECTIVE_PLANNER_TIMEOUT_SEC`、`FLOPPY_SCRIPT_WRITER_TIMEOUT_SEC`。

## 调用接口

智能体不直接调 workflow，而是通过决策图：

- `POST /agent/decide`（`AgentDecideRequest`：user_id / request_text / generation_allowed）
  → 自动走上面的数据流，未命中时 agent_graph 内部组装 directive。
- 语音对话链路（`/voice/ws`）里的 `_resolve_audio_asset` 同样走 `agent_graph.run`。
- 直接生成端点 `POST /users/{user_id}/generation-jobs` 接收 `GenerationRequest`，
  可显式带 `directive` 字段（程序化场景）。
