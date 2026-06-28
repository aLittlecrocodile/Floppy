# 预置缓存音频生成文案需求

## 背景

Floppy 需要准备一批可直接命中推荐/检索缓存的真实音频资产。当前代码中程序化函数生成的雨声、海浪、钢琴等只适合作为工程占位，不适合作为真实产品音频。第一步先产出可用于 AI 音乐/音效工具手动试生成的文案与提示词，由人工在 ElevenLabs Music、Stable Audio、Suno、Udio 或其他工具中验证音质。

## 目标

先生成一批 P0 试验用提示词，覆盖用户提出的四类内容：

1. 白噪音 / 环境音
2. 轻音乐
3. 冥想
4. 睡前故事及助眠播客

本轮目标不是一次性入库，而是先让人工用生成平台测试音频质量、风格可控性、可商用可行性和后期处理难度。

## 通用生成原则

所有音频都必须符合助眠场景：

- 低刺激、慢节奏、无惊吓、无突兀高潮
- 不出现急促鼓点、强节拍、尖锐高频、大动态爆发
- 适合夜间低音量播放
- 尽量无歌词、无人声喊叫、无强情绪表演
- 可循环、可拼接、适合 10-30 分钟长音频
- 输出后需要人工听感筛选，不直接上线

建议生成格式：

- 环境音：每条先生成 3-10 分钟，再 loop / crossfade 到 20-30 分钟
- 轻音乐：每条先生成 5-10 分钟，再拼接到 15-25 分钟
- 冥想 / 故事 / 播客：先生成脚本文案，再用 TTS 生成 8-20 分钟人声，可后期叠加环境音

## 一、白噪音 / 环境音提示词

> 使用场景：ElevenLabs SFX、Stable Audio、其他 AI sound effect / ambient generator。  
> 优先也可以用 Pixabay / Freesound CC0 找真实录音，AI 生成作为备选。

### 1. 雨声

英文提示词：

```text
A long, gentle nighttime rain ambience for sleep. Soft steady rainfall on leaves and distant rooftops, no thunder, no sudden loud drops, no voices, no music. Calm, warm, low-stimulation, seamless loop, relaxing white noise, suitable for bedtime and anxiety relief. Very smooth dynamics, dark and cozy atmosphere.
```

中文说明：

```text
夜晚轻柔雨声，持续稳定，没有雷声，没有突兀水滴，没有人声和音乐。适合睡前、焦虑舒缓、可循环播放。
```

### 2. 海浪

英文提示词：

```text
A peaceful distant ocean wave ambience for sleep. Slow rolling waves on a quiet beach at night, soft foam, deep and steady rhythm, no seagulls, no people, no wind gusts, no sudden crashes. Minimal, calming, low-frequency natural white noise, seamless loop, suitable for deep sleep.
```

中文说明：

```text
远处海浪，节奏慢、平稳、低频柔和，没有海鸥、游客、强风或突然拍岸声。适合深睡白噪音。
```

### 3. 溪流 / 瀑布

英文提示词：

```text
A gentle mountain stream ambience for sleep. Clear water flowing over small stones, soft continuous bubbling, very natural and soothing, no birds, no insects, no footsteps, no talking. Low-stimulation, peaceful, seamless loop, suitable for relaxation and bedtime.
```

中文说明：

```text
山间溪流或小瀑布，水流清澈连续，气泡声轻，不要鸟鸣、人声、脚步声。适合睡前放松。
```

### 4. 火焰燃烧声

英文提示词：

```text
A warm fireplace crackling ambience for sleep. Soft wood fire, gentle crackles, warm low rumble, cozy cabin atmosphere, no loud pops, no voices, no music, no wind. Calm and safe feeling, slow and minimal, seamless loop for bedtime.
```

中文说明：

```text
温暖壁炉火焰，轻微木柴噼啪声，不要突然爆裂声，不要人声和音乐。氛围安全、温暖、适合陪伴入睡。
```

### 5. 森林环境

英文提示词：

```text
A quiet nighttime forest ambience for sleep. Soft wind through leaves, very gentle distant insects, occasional subtle bird sounds far away, no loud animal calls, no footsteps, no people, no scary atmosphere. Calm, grounded, natural, low-stimulation, seamless loop.
```

中文说明：

```text
安静夜晚森林，树叶微风、远处很轻的虫鸣，鸟声要少且远。不要动物尖叫、脚步、人声、恐怖氛围。
```

### 6. 空调 / 风扇持续低响

英文提示词：

```text
A steady soft fan and air conditioner hum for sleep. Smooth low mechanical white noise, constant airflow, no clicking, no rattling, no sudden changes, no voices, no music. Very stable, neutral, low-frequency, seamless loop, ideal for masking background noise at night.
```

中文说明：

```text
稳定空调/风扇低响，持续气流声，无点击、无异响、无节奏变化。适合屏蔽噪音。
```

## 二、轻音乐提示词

> 使用场景：ElevenLabs Music、Stable Audio、Suno、Udio。  
> 推荐英文提示词。生成时务必选择 instrumental / no vocals。

通用负向提示词：

```text
No vocals, no lyrics, no drums, no percussion, no sudden crescendo, no bright pop melody, no strong rhythm, no dramatic climax, no tension, no suspense, no horror, no fast tempo.
```

### 1. 钢琴声

英文提示词：

```text
A slow solo grand piano sleep piece, extremely soft touch, warm felt piano tone, sparse notes, long natural reverb, around 45-55 BPM, peaceful and minimal. Gentle bedtime atmosphere, no vocals, no drums, no strong melody, no dramatic climax. Designed for deep relaxation and falling asleep.
```

中文说明：

```text
慢速独奏钢琴，弱触键、毛毡感、音符稀疏、长混响，45-55 BPM，适合入睡。
```

### 2. 大提琴 / 小提琴

英文提示词：

```text
A warm slow cello and soft violin sleep music piece. Long sustained notes, gentle legato, low emotional intensity, calm and comforting, no dramatic orchestral build, no sadness, no tension. Minimal chamber music texture, soft reverb, suitable for bedtime and anxiety relief.
```

中文说明：

```text
温暖大提琴与轻柔小提琴，长音、连奏、低情绪强度，不要悲伤或戏剧化，适合焦虑舒缓。
```

### 3. 弦乐合奏

英文提示词：

```text
A soft string ensemble ambient sleep piece. Very slow harmonic movement, warm pads made from violins, viola, and cello, no percussion, no cinematic climax, no tension. Peaceful, safe, floating, low-stimulation, gentle nighttime atmosphere for relaxation and sleep.
```

中文说明：

```text
柔和弦乐合奏，和声缓慢移动，像温暖的弦乐pad，不要电影配乐式高潮。
```

### 4. 吉他独奏

英文提示词：

```text
A gentle solo nylon-string guitar lullaby for sleep. Slow fingerpicking, warm intimate tone, sparse simple harmony, soft room reverb, no vocals, no percussion, no bright rhythmic strumming. Calm, cozy, low-stimulation, suitable for bedtime.
```

中文说明：

```text
尼龙弦吉他独奏，慢速指弹、温暖亲密、和声简单，不要扫弦和节奏感。
```

### 5. 长笛

英文提示词：

```text
A soft breathy flute sleep meditation music piece. Slow floating flute phrases with long pauses, very gentle ambient background, no percussion, no sharp high notes, no dramatic melody. Calm, airy, natural, peaceful, suitable for falling asleep.
```

中文说明：

```text
气息感长笛，乐句缓慢且停顿长，高音不要尖锐，背景很淡。
```

### 6. 口琴曲

英文提示词：

```text
A soft mellow harmonica sleep piece. Warm low-register harmonica, very slow simple phrases, nostalgic but not sad, gentle ambient reverb, no vocals, no guitar rhythm, no blues groove, no strong beat. Quiet, comforting, suitable for bedtime.
```

中文说明：

```text
温和口琴，低音区、慢乐句，有一点怀旧但不要悲伤，不要布鲁斯节奏。
```

### 7. 国风古筝

英文提示词：

```text
A slow traditional Chinese guzheng sleep music piece. Sparse guzheng plucks, gentle pentatonic melody, flowing water-like resonance, very slow tempo, soft ambient reverb, no drums, no percussion, no dramatic martial arts feeling, no fast runs. Peaceful, elegant, meditative, suitable for bedtime.
```

中文说明：

```text
国风古筝，五声音阶、慢速、稀疏拨弦、水流般余韵，不要武侠感、不要快刮奏、不要鼓点。
```

## 三、冥想 TTS 文案

> 使用场景：MiniMax TTS / ElevenLabs TTS。  
> 需要保留停顿标记或在 TTS 工具中用 SSML / pause 控制。  
> 以下文案是短版种子，可扩写到 8-15 分钟。

### 1. 呼吸觉察冥想

```text
现在，找一个舒服的姿势躺好。<#4#>
你不需要立刻睡着。<#5#>
也不需要完成任何练习。<#5#>
只要把注意力，轻轻放到呼吸上。<#6#>

吸气的时候，感受空气经过鼻腔。<#5#>
呼气的时候，让肩膀慢慢松下来。<#6#>

吸气。<#5#>
呼气。<#6#>

如果脑海里还有很多想法，没有关系。<#5#>
你不需要赶走它们。<#5#>
只要知道，它们来了，又会离开。<#7#>

现在，再一次回到呼吸。<#6#>
吸气，身体轻轻展开。<#5#>
呼气，身体慢慢沉下去。<#8#>

今晚，你已经做得足够多了。<#6#>
剩下的事情，可以交给明天。<#8#>
现在，只需要呼吸。<#10#>
```

### 2. 身体扫描冥想

```text
我们从头顶开始，慢慢放松身体。<#4#>

感受头顶。<#4#>
像有一阵很轻的风，经过头皮。<#5#>
额头慢慢舒展开。<#5#>
眉心不再用力。<#5#>
眼睛安静地停在眼皮后面。<#6#>

脸颊变得柔软。<#5#>
嘴角自然放松。<#5#>
下巴松开。<#6#>

现在，注意到脖子。<#5#>
脖子两侧的紧张，正在一点一点散开。<#6#>
肩膀往下沉。<#6#>
手臂变得温暖。<#6#>
手掌安静地放着。<#7#>

胸口随着呼吸，轻轻起伏。<#6#>
腹部柔软。<#6#>
背部被床稳稳托住。<#7#>

髋部放松。<#6#>
大腿放松。<#6#>
膝盖放松。<#6#>
小腿放松。<#6#>
脚踝和脚趾，也慢慢松开。<#8#>

整个身体，都可以休息了。<#10#>
```

### 3. 正念冥想

```text
此刻，你什么都不需要改变。<#5#>

听见声音，就只是知道有声音。<#5#>
感觉到身体，就只是知道身体在这里。<#5#>
想到一些事情，也只是知道，有一个想法经过。<#6#>

你不用跟着它走。<#5#>
也不用评价它。<#5#>
它只是像云一样，慢慢飘过。<#7#>

现在，把注意力放回这个晚上。<#5#>
房间里的空气。<#5#>
身体和床接触的地方。<#5#>
呼吸轻轻进来，又轻轻出去。<#7#>

此刻已经足够安静。<#6#>
你也已经足够安全。<#8#>
```

### 4. 睡眠冥想

```text
今晚，不用努力入睡。<#5#>
睡眠会在合适的时候，自己来到。<#6#>

你只需要把身体交给床。<#5#>
把重量交给枕头。<#5#>
把今天交给夜晚。<#7#>

如果还清醒，也没关系。<#5#>
清醒也可以很安静。<#6#>

让眼皮变得更重一点。<#6#>
让呼吸变得更慢一点。<#6#>
让每一次呼气，都带走一点点紧绷。<#8#>

现在，什么都不用想。<#7#>
什么都不用记。<#7#>
你可以只是躺在这里。<#8#>
慢慢地，越来越轻。<#10#>
```

### 5. 慈心冥想

```text
现在，把一只手轻轻放在胸口。<#5#>
或者，只是在心里想象一个温暖的位置。<#6#>

对自己说：<#4#>
愿我平安。<#6#>
愿我放松。<#6#>
愿我今晚睡得安稳。<#7#>

如果这些话听起来有一点陌生，也没关系。<#5#>
你不需要立刻相信它们。<#5#>
只要让它们，在心里轻轻停一会儿。<#7#>

愿我允许自己休息。<#6#>
愿我对今天的自己温柔一点。<#6#>
愿我把没完成的事情，暂时放下。<#8#>

你值得被温柔对待。<#6#>
也值得拥有一个安静的夜晚。<#10#>
```

## 四、睡前故事 / 助眠播客文案方向

> 使用场景：先用大模型扩写成完整脚本，再用 TTS 生成。  
> 原则：低冲突、低信息密度、无悬疑、无恐怖、无强剧情反转。

### 1. 社会 / 人文助眠播客

提示词：

```text
请写一段适合睡前收听的中文助眠播客脚本，主题是“城市里慢慢消失的小店”。风格参考人文类播客，但信息密度要很低，语气平和、温柔、像夜晚朋友聊天。不要争议观点，不要沉重社会批判，不要强情绪输出。内容可以讲老书店、修鞋铺、早餐摊、照相馆这些日常空间，重点放在气味、灯光、声音、人与人之间的温和连接。适合 TTS 朗读，句子短，停顿多，时长约10分钟。
```

### 2. 趣味杂谈助眠播客

提示词：

```text
请写一段适合睡前收听的中文趣味杂谈播客脚本，主题是“为什么有些声音会让人安心”。语气轻松、平和，不要科普得太硬，不要堆砌术语。可以聊雨声、风扇声、翻书声、远处火车声、猫打呼噜这些生活声音。整体像一个朋友在夜晚小声聊天，信息密度逐渐降低，最后自然过渡到休息。适合 TTS 朗读，句子短，停顿多，时长约8-10分钟。
```

### 3. 故事奇谈

提示词：

```text
请写一个中文睡前故事，主题是“凌晨两点才营业的月光杂货店”。故事要温柔、低刺激、没有恐怖、没有悬疑压迫感。杂货店只卖一些安静的小东西：装着海风的玻璃瓶、会变暖的旧围巾、写给明天的明信片、可以收纳烦恼的小盒子。情节推进很慢，以场景、气味、灯光、触感为主。结尾不要反转，只让主角慢慢感到安心并准备入睡。适合 TTS 朗读，句子短，停顿多，时长约12-15分钟。
```

### 4. 情感陪伴

提示词：

```text
请写一段适合睡前收听的中文情感陪伴音频脚本，主题是“今天已经辛苦了，可以先休息”。不要鸡汤，不要说教，不要承诺一定会变好。语气要像一个温柔、稳定、可靠的朋友，陪用户把今天暂时放下。内容包含：承认疲惫、允许没完成、把明天交给明天、引导身体慢慢放松。适合 TTS 朗读，句子短，停顿多，时长约8-10分钟。
```

### 5. 得到式知识转助眠

提示词：

```text
请写一段适合睡前收听的中文知识类助眠音频脚本，主题是“丝绸之路上的夜晚”。不要像课堂讲课，不要信息密度过高。用温柔的叙述讲沙漠驿站、商队、星空、篝火、远方城市的灯。历史信息只作为背景，重点放在画面感和安静氛围。语速适合慢速 TTS，句子短，停顿多，最后自然过渡到睡眠。时长约10-12分钟。
```

## 试生成建议

### 优先测试顺序

1. 轻音乐：先测钢琴、古筝、弦乐三类，因为最能判断 AI 音乐质量。
2. 环境音：先测雨声、风扇、海浪三类，因为最容易用于真实睡眠。
3. TTS：先测“呼吸觉察冥想”和“情感陪伴”，判断音色是否适合 Floppy。

### 人工听感筛选标准

每条音频打 1-5 分：

- 自然度：是否像真实录音/真实演奏
- 睡前适配：是否低刺激、不过度吸引注意力
- 稳定性：是否有突兀音量变化、突然转折
- 可循环性：是否容易 loop 或拼接
- 商用风险：是否疑似像已有名曲、是否有版权/授权疑虑

只保留：

- 平均分 >= 4
- 睡前适配 >= 4
- 稳定性 >= 4
- 无明显版权疑虑

## 预期输出

人工试生成后，为每条候选记录：

```text
title:
category:
subtype:
tool:
model:
prompt:
duration:
file_path:
license_plan:
quality_score:
notes:
```

后续确认工具和样本质量后，再进入工程落地：

1. 替换 `catalog.py` 中的 placeholder 条目
2. 增加真实音频文件导入脚本
3. 维护素材来源 / prompt / license 元数据
4. 将生成音频写入 `storage/pregen/...`
5. 入库 `audio_assets`，让推荐和缓存可直接命中
