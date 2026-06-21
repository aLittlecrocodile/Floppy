# Floppy TTS Vendor Research

更新时间：2026-06-21  
范围：第三方 TTS/音频生成服务调研，不包含自训练模型

## 结论摘要

Floppy 不建议自训练 TTS 模型。当前阶段应采用“多厂商可替换 provider + 缓存音频资产库”的架构：

1. 第一阶段先接 1 个国内 TTS 服务，跑通真实睡前故事/冥想音频生成、入库、缓存、播放。
2. 第二阶段增加 1 个高质量海外/国际 provider，用于对比音质、情绪表达和英文内容。
3. 所有厂商都必须经过同一套 `AudioGenerationProvider` 抽象，不能把业务逻辑写死在某个 SDK 里。
4. TTS 只负责“把脚本读出来”，Floppy 仍需要自己的睡前脚本生成、音频后处理、质量评估和缓存治理。

第一轮 shortlist 收敛为三家：

- 豆包/火山引擎：国内主候选，和当前技术生态最顺。
- 微软 Azure AI Speech：企业级稳定候选，多语言、SSML 和风格控制成熟。
- MiniMax：高自然度和情绪化语音候选，T2A 同步/异步接口适合做长音频 PoC。

其他厂商暂不进入第一轮。阿里、腾讯、讯飞可以作为国内备选池；ElevenLabs、OpenAI、Google、AWS 可以作为后续国际化或质量 benchmark，不建议现在分散接入。

## Floppy 对 TTS 的核心要求

睡前场景和普通短视频配音不同，TTS 需要满足：

| 要求 | 说明 |
| --- | --- |
| 中文自然度 | 普通话自然，语气柔和，不机械 |
| 长文本稳定性 | 10 到 30 分钟内容不能明显断裂、跳字、音色漂移 |
| 情绪控制 | 支持温柔、平静、低语、安抚等风格 |
| 语速控制 | 睡前语速需要偏慢 |
| 流式/异步 | 即时试听可流式，长音频应走异步任务 |
| 成本可控 | 大量内容应预生成和缓存 |
| 商用合规 | 音色授权、声音克隆授权、地域合规必须清楚 |
| 输出格式 | mp3/wav/ogg/pcm 至少支持一种，后续统一转码 |
| API 稳定 | 支持服务端批量生成、错误码明确、限流明确 |

## 候选厂商对比

### 三家 shortlist 总览

| 厂商 | 当前定位 | Floppy 适配点 | 主要风险 | 第一轮优先级 |
| --- | --- | --- | --- | --- |
| 豆包/火山引擎 | 国内主 provider | 中文、国内部署、火山生态、TOS/VeADK/AgentKit 路线顺 | 长文本稳定性、睡前音色、价格和缓存授权要实测 | P0 |
| MiniMax | 高自然度/情绪化 provider | T2A 同步与异步、声音表现、长文本异步能力 | 商用条款、国内部署方式、成本、中文睡前音色要实测 | P0 |
| 微软 Azure AI Speech | 企业级稳定 provider | 多语言、SSML、风格控制、全球云稳定性 | 国内账号/区域、中文睡前自然度、成本要实测 | P1 |

### 火山引擎豆包语音合成

适配度：高，建议作为国内 PoC 第一候选。

适合原因：

- 国内云资源和豆包生态匹配。
- 与当前方案里的 VeADK/AgentKit/TOS/VikingDB 路线兼容。
- 适合中文场景，后续接对象存储和国内部署阻力较小。
- 官方有语音合成、WebSocket/HTTP、价格和模型相关文档。

需要验证：

- 睡前长文本 10 到 30 分钟是否稳定。
- 是否支持足够柔和、低刺激的音色。
- 大模型语音合成和传统 TTS 的价格差异。
- 生成内容是否允许商用和缓存复用。
- 是否支持音色复刻；如果支持，授权流程和用户 consent 如何处理。

建议用途：

- 中文睡前故事。
- 冥想引导。
- 内容转睡前音频。
- 国内生产默认 provider。
- 与当前 Floppy MVP 的对象存储、任务队列、缓存资产库路线最顺。

官方参考：

- `https://www.volcengine.com/docs/6561/97465`
- `https://www.volcengine.com/docs/6561/1257544`
- `https://www.volcengine.com/pricing/10007`

### MiniMax T2A / Speech

适配度：高，建议作为第一轮 P0 候选。

适合原因：

- 官方提供 Text-to-Audio 能力，适合文本到语音的睡前故事、冥想和内容转化。
- 同步 HTTP 接口适合短内容和快速 PoC。
- 官方 overview 中列出 T2A Async，适合长文本异步生成，和 Floppy 当前 `generation_jobs` 模型匹配。
- 支持音色、语速、音量、音高和输出格式等参数，适合做睡前风格调优。

需要验证：

- 中文睡前故事和冥想的自然度是否稳定。
- 长文本异步接口的真实耗时、失败率、任务查询机制。
- 单次请求、并发、QPS、价格和账号额度。
- 生成音频是否允许缓存、商用播放和长期复用。
- 如果使用声音克隆，必须确认授权和 consent 流程。

建议用途：

- 睡前故事高质量候选。
- 情绪安抚类冥想/陪伴音色候选。
- 与豆包做中文自然度和睡前适配度 A/B。

官方参考：

- `https://platform.minimax.io/docs/api-reference/speech-t2a-http`
- `https://platform.minimax.io/docs/api-reference/speech-t2a-async`
- `https://platform.minimax.io/docs/introduction/overview`
- `https://platform.minimax.io/docs/billing`

### 阿里云智能语音交互 / CosyVoice

适配度：中高，适合作为国内备选和对比项。

适合原因：

- 阿里云语音服务成熟，国内部署和企业采购路径清晰。
- CosyVoice 方向和中文自然语音能力值得评估。
- 如果后续基础设施选 OSS/RDS，接入链路会比较顺。

需要验证：

- 官方托管服务中可用音色和开源 CosyVoice 能力并不完全等同，需要以实际 API 为准。
- 长文本稳定性和异步生成支持。
- 价格、并发、限流和商用缓存条款。

建议用途：

- 国内备选 provider。
- 与火山做中文音质和成本 A/B。

官方参考：

- `https://help.aliyun.com/zh/isi/developer-reference/speech-synthesis`
- `https://help.aliyun.com/zh/isi/product-overview/billing-of-speech-synthesis`
- `https://help.aliyun.com/zh/model-studio/cosyvoice-java-sdk`

### 腾讯云语音合成

适配度：中，适合作为国内稳态备选。

适合原因：

- 国内云服务成熟。
- 适合做标准 TTS 兜底。
- 如果后续部署在腾讯云，集成成本较低。

需要验证：

- 睡前风格音色是否足够自然。
- 长文本、并发和价格。
- 情绪控制能力是否满足 Floppy。

建议用途：

- 标准中文 TTS 备选。
- 成本或可用性兜底。

官方参考：

- `https://cloud.tencent.com/document/product/1073`
- `https://cloud.tencent.com/document/product/1073/37995`
- `https://cloud.tencent.com/document/product/1073/34392`

### 讯飞开放平台语音合成

适配度：中，适合作为中文语音质量备选。

适合原因：

- 中文语音技术积累深。
- 音色选择和中文场景较丰富。

需要验证：

- 当前开放平台 API 的价格、并发和商用条款。
- 低刺激睡前音色表现。
- 长文本合成稳定性。

建议用途：

- 中文音色质量对比。
- 国内备选 provider。

官方参考：

- `https://www.xfyun.cn/services/online_tts`
- `https://www.xfyun.cn/doc/tts/online_tts/API.html`

### ElevenLabs

适配度：高质量候选，但国内生产需谨慎。

适合原因：

- 情绪化、自然度和声音表现强。
- API 和流式能力成熟。
- 适合英文睡前内容、品牌音色 demo 和高质量语音评估。

风险：

- 国内网络、合规、价格和授权需要单独确认。
- 声音克隆必须严格处理授权和 consent。
- 中文表现需要实际测试，不能只按英文效果判断。

建议用途：

- 英文/国际版本。
- 高质量 benchmark。
- 品牌音色方向的参考上限。

官方参考：

- `https://elevenlabs.io/docs/api-reference/text-to-speech/convert`
- `https://elevenlabs.io/pricing`
- `https://elevenlabs.io/docs/product-guides/voices/voice-cloning`

### OpenAI TTS

适配度：高质量原型和国际版候选。

适合原因：

- 官方 TTS 能力与多模态/Agent 生态衔接好。
- 支持语音风格指令，适合快速原型。
- 如果后续有 Realtime 语音陪伴，生态一致性较好。

风险：

- 国内网络、合规和生产可用性要谨慎。
- 价格和模型可用性可能变化，需以上线时官方价格为准。

建议用途：

- 海外版原型。
- 多模态语音陪伴 PoC。
- 与国内 TTS 做质量对比。

官方参考：

- `https://developers.openai.com/api/docs/guides/text-to-speech`
- `https://developers.openai.com/api/docs/pricing`

### Azure AI Speech

适配度：中高，适合企业级国际备选。

适合原因：

- 企业级稳定性强。
- 支持多语言、多音色、SSML、语速和风格控制。
- 全球云部署成熟。

风险：

- 国内和国际 Azure 资源、账号、价格和模型可用性要分开确认。
- 中文睡前音色需要实际测试。

建议用途：

- 企业级稳定 provider。
- 多语言版本。
- SSML 控制对比。

官方参考：

- `https://learn.microsoft.com/azure/ai-services/speech-service/text-to-speech`
- `https://azure.microsoft.com/pricing/details/cognitive-services/speech-services/`

### Google Cloud Text-to-Speech

适配度：中高，适合国际版和高质量 benchmark。

适合原因：

- WaveNet/Neural/Chirp 等语音能力成熟。
- 多语言和全球部署能力强。
- 文档和价格透明。

风险：

- 国内生产可用性和合规需要评估。
- 中文睡前音色表现需要实测。

建议用途：

- 国际版本。
- 多语言 benchmark。

官方参考：

- `https://cloud.google.com/text-to-speech/docs`
- `https://cloud.google.com/text-to-speech/pricing`

### AWS Polly

适配度：中，适合稳定云服务备选。

适合原因：

- 稳定、成熟、全球云生态强。
- 支持 Neural、Long-form、Generative 等类别的语音。
- 适合批量生成和云上工作流。

风险：

- 中文情绪化表达和睡前氛围需要实测。
- 国内生产需要云区和合规确认。

建议用途：

- 国际云备选。
- 大规模批量生成备选。

官方参考：

- `https://docs.aws.amazon.com/polly/latest/dg/what-is.html`
- `https://aws.amazon.com/polly/pricing/`

## 推荐 PoC 方案

### 第一轮只测 3 家

为了高效，不建议一开始接 8 家。第一轮只测：

1. 豆包/火山引擎：国内主候选。
2. MiniMax：高自然度和情绪化语音候选。
3. 微软 Azure AI Speech：企业级稳定和 SSML 控制候选。

第一轮目标不是立刻确定最终唯一厂商，而是用同一批睡前内容样本判断三件事：谁的中文睡前音色最合适、谁的长文本任务最稳、谁的成本和授权最适合缓存资产库。

### 测试脚本

每家厂商用同一批文本，不要主观听一两句就下结论。

故事类：

```text
今晚，我们来到一间靠近海边的小书店。窗外有很轻的雨声，灯光柔和，书页慢慢翻动。你不需要做任何事，只需要跟着声音，慢慢放松下来。
```

冥想类：

```text
现在，把注意力放在呼吸上。吸气的时候，不用刻意用力。呼气的时候，让肩膀一点点松下来。你已经完成了今天最重要的部分，现在可以休息了。
```

内容转化类：

```text
这篇文章的核心意思可以慢慢地听。我们不需要记住每一个细节，只保留几个温和的画面，让大脑逐渐安静下来。
```

压力舒缓类：

```text
如果今天还有一些没有完成的事情，也可以先放在明天。现在不是解决问题的时间，而是让身体恢复的时间。
```

### 评估指标

| 指标 | 权重 | 说明 |
| --- | --- | --- |
| 中文自然度 | 25% | 是否像真实、稳定的人声 |
| 睡前适配度 | 25% | 是否柔和、低刺激、不抢注意力 |
| 长文本稳定性 | 15% | 10 分钟以上是否音色稳定 |
| 可控性 | 10% | 语速、音色、情绪、停顿控制 |
| 延迟 | 10% | 是否适合按需生成 |
| 成本 | 10% | 批量预生成和用户按需生成成本 |
| 合规/授权 | 5% | 商用、缓存、音色授权是否清楚 |

### 技术验证标准

每个 provider 必须输出：

- 5 到 10 条真实音频样本。
- 生成耗时。
- 输入字符数和估算成本。
- 输出格式、采样率、码率。
- 错误码和失败重试行为。
- 是否支持长文本。
- 是否支持 SSML 或语音风格参数。
- 是否允许缓存复用生成结果。

## 接入当前 MVP 的设计

新增 provider 时保持当前接口：

```python
class AudioGenerationProvider:
    name = "abstract"

    def generate(self, normalized, output_path, object_key):
        raise NotImplementedError
```

建议新增：

```text
floppy_backend/providers/tts/
  __init__.py
  base.py
  volcengine.py
  minimax.py
  azure.py
```

配置项建议：

```text
FLOPPY_AUDIO_PROVIDER=local|volcengine|minimax|azure
FLOPPY_TTS_API_KEY=...
FLOPPY_TTS_APP_ID=...
FLOPPY_TTS_VOICE_ID=...
FLOPPY_TTS_SAMPLE_RATE=24000
FLOPPY_TTS_OUTPUT_FORMAT=mp3
```

生成流程：

```text
GenerationService
  -> build_sleep_script(normalized)
  -> provider.synthesize(script, voice_config)
  -> audio_postprocess(output)
  -> upsert audio_asset
```

当前 MVP 的 `LocalToneAudioProvider` 只用于测试和无密钥环境，不应作为生产音频质量参考。

## 关键工程风险

1. 长文本切分
   - 许多 TTS 对单次输入字符数有限制。
   - 需要统一做文本切片、分段合成、拼接、停顿控制。

2. 音频后处理
   - 不同厂商输出格式、响度、采样率不同。
   - 需要统一转码、响度归一、淡入淡出、背景声混音。

3. 成本控制
   - 按需生成必须走 in-flight 去重。
   - 热门内容要预生成并缓存。
   - 对超长文本做时长和字符数限制。

4. 授权与缓存
   - 必须确认生成音频是否可以长期缓存、商用播放、二次分发。
   - 声音克隆必须有明确授权。

5. 内容安全
   - TTS 前脚本要过安全检查。
   - 睡前内容禁止惊吓、恐怖、医疗承诺、高刺激表达。

## 当前建议

下一步工程动作：

1. 先在现有 MVP 中新增三个 provider skeleton：`VolcengineTTSProvider`、`MiniMaxTTSProvider`、`AzureSpeechProvider`。
2. 用 `FLOPPY_AUDIO_PROVIDER` 切换 `local`、`volcengine`、`minimax`、`azure`。
3. 第一轮只实现最小可用 TTS：输入脚本，输出音频文件，记录耗时、字符数、provider、voice_id。
4. 生成 4 类样本：故事、冥想、内容转化、压力舒缓。
5. 每家至少生成短文本和长文本两组样本。
6. 把样本路径、耗时、字符数、成本估算写入 `audio_assets` 或新的 `tts_eval_runs` 表。

推荐决策：

- 如果豆包音质达标且成本/授权清晰：优先作为国内默认 provider。
- 如果 MiniMax 的睡前自然度明显更好：可作为高质量内容生成 provider，豆包作为稳定兜底。
- 如果 Azure 的 SSML 和稳定性明显更好：适合多语言、企业级、国际化路线。
- 第一轮结束前不要引入第四家，避免工程和评估发散。

## 参考来源

- 火山引擎语音合成文档：`https://www.volcengine.com/docs/6561/97465`
- 火山引擎大模型语音合成：`https://www.volcengine.com/docs/6561/1257544`
- 火山引擎价格页：`https://www.volcengine.com/pricing/10007`
- MiniMax T2A HTTP：`https://platform.minimax.io/docs/api-reference/speech-t2a-http`
- MiniMax T2A Async：`https://platform.minimax.io/docs/api-reference/speech-t2a-async`
- MiniMax overview：`https://platform.minimax.io/docs/introduction/overview`
- MiniMax billing：`https://platform.minimax.io/docs/billing`
- 阿里云语音合成文档：`https://help.aliyun.com/zh/isi/developer-reference/speech-synthesis`
- 阿里云语音合成计费：`https://help.aliyun.com/zh/isi/product-overview/billing-of-speech-synthesis`
- 腾讯云语音合成文档：`https://cloud.tencent.com/document/product/1073`
- 讯飞在线语音合成：`https://www.xfyun.cn/services/online_tts`
- ElevenLabs TTS API：`https://elevenlabs.io/docs/api-reference/text-to-speech/convert`
- ElevenLabs pricing：`https://elevenlabs.io/pricing`
- OpenAI text-to-speech：`https://developers.openai.com/api/docs/guides/text-to-speech`
- OpenAI pricing：`https://developers.openai.com/api/docs/pricing`
- Azure AI Speech TTS：`https://learn.microsoft.com/azure/ai-services/speech-service/text-to-speech`
- Azure Speech pricing：`https://azure.microsoft.com/pricing/details/cognitive-services/speech-services/`
- Google Cloud Text-to-Speech：`https://cloud.google.com/text-to-speech/docs`
- Google Cloud Text-to-Speech pricing：`https://cloud.google.com/text-to-speech/pricing`
- Amazon Polly docs：`https://docs.aws.amazon.com/polly/latest/dg/what-is.html`
- Amazon Polly pricing：`https://aws.amazon.com/polly/pricing/`
