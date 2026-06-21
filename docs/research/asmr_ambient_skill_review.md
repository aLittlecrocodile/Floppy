# ASMR Ambient Skill Review

来源：`/Users/aooway/Downloads/asmr-ambient.zip`  
SHA256：`155e502f0907f254a6f98c9ea58203f47ba8dbbacae42f8e8a0547709d456a87`  
评审日期：2026-06-21

## 结论

这个 MiniMax Hub 官方 skill 很有参考价值，尤其适合 Floppy 的“睡前内容生产工作流”设计。它不是单纯 TTS 示例，而是一套比较完整的助眠音频生产流程：

```text
内容类型选择
-> 脚本生成和停顿标记
-> 音色选择和 TTS
-> 自然音效导入
-> 背景音乐生成
-> ffmpeg 混音
-> 试听反馈
-> 导出
```

但它不适合直接作为 Floppy 后端核心使用，原因是：

- 它面向 MiniMax Hub/本地创作工具，依赖 MCP 工具和人工确认流程。
- 它使用 `.sleep-audio/{project_name}/` 本地目录和 `.sleep-state.json` 状态文件，不适合服务端多用户生产。
- 它假设用户参与每个阶段确认，而 Floppy App 需要更自动化、更可缓存、更可观测。
- 它包含素材下载、预览服务器、用户反馈页面等创作工具能力，不应直接放进生产生成 worker。

正确做法是：吸收它的内容生产方法论，把它改造成 Floppy 后端的可控 workflow。

## 文件结构

```text
asmr-ambient/
├── SKILL.md
├── meta.yaml
├── references/category-music-mapping.md
├── scripts/render_mix_preview.py
├── scripts/validate_nature.py
└── html/preview-mix_feedback.html
```

## 值得吸收的能力

### 1. 三类内容类型划分

Skill 将助眠内容分成三类：

| 类型 | 时长 | 特征 |
| --- | --- | --- |
| 引导冥想 | 5-15 分钟 | 呼吸、身体扫描、场景想象、渐进放松 |
| 睡前故事 | 5-10 分钟 | 成人向、缓慢叙事、低冲突、感官描写 |
| ASMR | 10-20 分钟 | 耳语/气声、白噪音、重复、极慢节奏 |

这和 Floppy 当前的 `AudioType` 很匹配。建议后续把 `meditation/story/asmr` 作为第一批真实 TTS 生成重点。

### 2. 智能停顿标记

Skill 明确要求在脚本里插入 MiniMax TTS 支持的 `<#X#>` 停顿标记。

这是非常关键的产品能力。睡前内容的自然度不只取决于音色，也取决于节奏、停顿、呼吸感。

建议 Floppy 的 `SleepScriptAgent` 输出脚本时保留：

```text
普通句间：<#0.5#> 到 <#1#>
段落过渡：<#2#> 到 <#3#>
呼吸引导：<#3#> 到 <#5#>
深度放松：<#5#> 到 <#8#>
ASMR：几乎每句都有停顿
```

### 3. 内容安全和低刺激原则

Skill 对三类内容都强调：

- 节奏慢。
- 不要突兀转折。
- 不要明确结束感。
- 成人向睡前故事要文学性但不晦涩。
- ASMR 内容本身次要，声音质感和节奏更重要。

这些原则应并入 Floppy 的脚本生成 guardrail。

### 4. 音色策略

Skill 对不同内容类型给了音色选择策略：

- 冥想：柔和、气声、类耳语、平静。
- 故事：温暖、有叙事感、不紧张。
- ASMR：耳语、气声、极轻柔。

这说明 Floppy 不应该只有一个默认 voice。建议至少维护：

```text
voice_profile.meditation
voice_profile.story
voice_profile.asmr
```

并把用户反馈沉淀到用户画像或偏好表。

### 5. 自然音效分类

`validate_nature.py` 和 `category-music-mapping.md` 提供了自然音分类和音乐 prompt 映射。

可直接吸收分类：

```text
rain, thunder, fireplace, ocean, river, forest, bird, cricket,
wind, snow, cafe, clock, keyboard, vinyl, train, city, subway,
whitenoise, underwater, space
```

这可以映射到 Floppy 的 `background_preferences` 和音频标签系统。

### 6. 混音原则

Skill 里的混音经验很有价值：

- 不建议使用 `amix`，避免自动除以输入数量导致人声变小。
- 不建议使用 `loudnorm`，避免人声停顿时背景被自动抬高。
- 建议先分析音量，再预渲染背景轨。
- 使用 `amerge + pan` 直接叠加。
- 人声延迟进入，让环境音先建立安全感。
- 背景淡出，人声不淡出，避免结尾话语被削弱。

这些应成为 Floppy 后续 `AudioPostProcessor` 的设计基础。

### 7. 反馈闭环

Skill 的预览页面允许用户反馈：

- 人声太快/太慢。
- 人声太大/太小。
- 换音色。
- 背景声音量。
- 换自然音效。
- 音乐音量/风格。

这正好可以转成 Floppy App 后续的用户反馈事件和画像更新。

## 不建议直接照搬的部分

### 1. 每阶段人工确认

MiniMax Hub skill 是创作工具，适合用户参与每个阶段确认。Floppy App 的主场景是睡前，不能让用户反复选择。

Floppy 应采用：

```text
默认自动生成
-> 播放
-> 简单反馈
-> 下次优化
```

### 2. 本地目录状态

Skill 使用：

```text
.sleep-audio/{project_name}/
.sleep-state.json
preferences.md
```

Floppy 服务端应改成：

```text
generation_jobs
audio_assets
audio_scripts
user_audio_preferences
tts_eval_runs
```

### 3. Pixabay 下载自然素材

这个适合本地创作，不适合生产服务直接浏览网页下载。

Floppy 应维护自己的合规自然音效库：

- 预先审核素材。
- 记录授权。
- 入库标签化。
- 通过推荐和生成流程复用。

### 4. 预览服务器

`render_mix_preview.py` 适合内部创作/运营调音，不适合 App 用户直接使用。

可以保留为内部运营工具思路，但生产端应提供更简单的反馈 UI。

## 对 Floppy 的改造建议

### 1. 新增脚本层

当前 MVP 直接从 normalized request 进入 provider。接 MiniMax 前应增加：

```text
SleepScriptService
  -> generate_script(normalized, profile, content_type)
  -> insert_pause_marks(script)
  -> validate_script(script)
```

输出：

```json
{
  "title": "海边书店的雨夜",
  "script_text": "...<#3#>...",
  "content_type": "story",
  "language": "zh-CN",
  "pause_density": "medium",
  "estimated_duration_sec": 900,
  "script_hash": "..."
}
```

### 2. 新增音频后处理层

建议新增：

```text
AudioPostProcessor
  -> analyze_volume()
  -> render_background()
  -> mix_voice_nature_music()
  -> fade_in_out()
  -> export_mp3()
```

第一阶段可以先不做复杂混音，只做：

- 统一格式。
- 音量检查。
- 淡入淡出。

### 3. 新增自然音效资产库

建立预置自然音效表：

```text
nature_assets
  id
  category
  object_key
  duration_sec
  license
  quality_score
```

先不要运行时下载素材。

### 4. 扩展用户偏好

把 skill 的 `preferences.md` 思路变成数据库字段或事件聚合：

```text
preferred_voice_by_type
preferred_speed_by_type
preferred_background_by_type
voice_gain_preference
nature_volume_preference
music_volume_preference
```

### 5. 扩展 generation job 状态

为了支持 MiniMax async 和混音，建议状态增加：

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

## 推荐落地顺序

1. 先吸收 `SKILL.md` 的脚本规则，做 `SleepScriptService`。
2. 做 `MiniMaxTTSProvider`，支持 `<#X#>` 停顿标记。
3. 用 MiniMax 同步 T2A 生成短样本。
4. 增加 `audio_scripts` 表，保存最终脚本和 `script_hash`。
5. 增加简单 `AudioPostProcessor`，至少做格式统一和 fade。
6. 后续再做自然音效库、背景音乐和完整混音。

## 适合直接加入 Floppy prompt 的规则

```text
你是 Floppy 的睡前脚本生成器。输出适合 TTS 合成的脚本。

要求：
- 全文使用同一种语言。
- 开头必须有 2-4 句柔和引导，说明即将听到的内容。
- 使用 <#X#> 插入停顿，X 为秒数。
- 不要出现惊吓、恐怖、强冲突、强悬疑、医疗承诺。
- 避免“你必须睡着”等带压力的表达。
- 句子短，节奏慢，结尾自然消散。

停顿规则：
- 普通句间：<#0.5#> 到 <#1#>
- 段落过渡：<#2#> 到 <#3#>
- 呼吸引导：<#3#> 到 <#5#>
- 深度放松：<#5#> 到 <#8#>
- ASMR：每句都应有停顿，整体更慢。
```

## 评估

这个 skill 对 Floppy 的价值很高，建议作为我们 MiniMax 音频工作流设计的主要参考。但要把它“产品化/服务端化”，而不是直接运行原 skill。
