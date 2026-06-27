# Agent Workflow Protocol v0

Floppy 的 Agent 负责决策，Workflow 负责生产。两边通过稳定协议沟通，避免 Agent 直接调用 MiniMax、ffmpeg 或文件系统，也避免 Workflow 反向参与用户对话决策。

## 1. Boundary

Agent owns:

- 理解用户意图和画像上下文
- 判断是否生成、是否可用缓存、是否需要追问
- 产出结构化生成需求
- 向用户解释等待、失败、完成状态

Workflow owns:

- 生成睡眠音频脚本
- 执行 script guard
- 选择最终 voice id
- 调用 TTS / music provider
- 本地 ffmpeg 混音和 audio meta
- 写入音频资产库、任务状态和 provider trace

Workflow 不直接问用户。信息不足时返回 `needs_clarification`，由 Agent 继续对话。

## 2. Submit Request

Agent submits a `SleepAudioWorkflowRequest`:

```json
{
  "protocol_version": "sleep_audio_workflow.v0",
  "request_id": "req_20260626_001",
  "user_id": "u_demo",
  "conversation_id": "conv_abc",
  "workflow_type": "sleep_audio_generation",
  "intent": {
    "content_type": "meditation",
    "language": "zh-CN",
    "target_duration_sec": 1200,
    "title_hint": "雨夜呼吸放松",
    "topic": ["呼吸", "雨夜", "放松"],
    "mood": ["calm", "anxiety_relief"],
    "background": "rain_soft",
    "voice_style": "gentle_female"
  },
  "constraints": {
    "low_stimulation": true,
    "no_medical_claim": true,
    "no_sudden_sound": true,
    "max_cost_usd": 0.5,
    "allow_background_music": true,
    "allow_nature_ambient": true
  },
  "mix_preferences": {
    "preset": "meditation",
    "voice_volume": 1.0,
    "background_volume": 0.18,
    "fade_out_sec": 12
  },
  "generation_policy": {
    "cache_policy": "prefer_cache",
    "force_regenerate": false,
    "quality_level": "standard",
    "provider": "minimax"
  },
  "agent_context": {
    "reason": "用户想要常规入睡冥想，未指定时长，按默认20分钟",
    "profile_segment": "anxiety_relief",
    "user_visible_summary": "我会生成一段约20分钟的雨夜呼吸冥想"
  }
}
```

## 3. Accepted Response

Workflow accepts and returns a run id:

```json
{
  "workflow_run_id": "wf_abc",
  "request_id": "req_20260626_001",
  "status": "queued",
  "estimated": {
    "target_duration_sec": 1200,
    "estimated_cost_usd": 0.12,
    "estimated_wait_sec": 180
  },
  "accepted_intent": {
    "content_type": "meditation",
    "target_duration_sec": 1200,
    "voice_style": "gentle_female",
    "background": "rain_soft",
    "mix_preset": "meditation"
  }
}
```

## 4. Status Response

Agent polls workflow status:

```json
{
  "workflow_run_id": "wf_abc",
  "request_id": "req_20260626_001",
  "status": "mixing",
  "current_step": "mix_audio",
  "steps": [
    {"name": "script", "status": "succeeded"},
    {"name": "speech", "status": "succeeded"},
    {"name": "music", "status": "succeeded"},
    {"name": "mix_audio", "status": "running"}
  ],
  "artifact": null,
  "diagnostics": null,
  "error": null
}
```

Success:

```json
{
  "workflow_run_id": "wf_abc",
  "request_id": "req_20260626_001",
  "status": "succeeded",
  "current_step": "done",
  "steps": [
    {"name": "script", "status": "succeeded"},
    {"name": "speech", "status": "succeeded"},
    {"name": "music", "status": "succeeded"},
    {"name": "mix_audio", "status": "succeeded"},
    {"name": "asset", "status": "succeeded"}
  ],
  "artifact": {
    "asset_id": "aud_xxx",
    "playback_url": "http://127.0.0.1:8000/audio/ondemand/u_demo/xxx.mp3",
    "duration_sec": 1190,
    "title": "雨夜呼吸放松",
    "content_type": "meditation"
  },
  "diagnostics": {
    "script_hash": "sha256...",
    "script_chars": 981,
    "voice_id": "Chinese (Mandarin)_Soft_Girl",
    "voice_object_key": "ondemand/u_demo/xxx_voice.mp3",
    "music_object_key": "ondemand/u_demo/xxx_music.mp3",
    "mixed_object_key": "ondemand/u_demo/xxx.mp3",
    "provider_model": "speech-2.8-hd+music-2.6",
    "estimated_cost_usd": 0.098
  },
  "error": null
}
```

## 5. Clarification Response

Workflow can reject ambiguous requests with fields Agent should ask about:

```json
{
  "workflow_run_id": null,
  "request_id": "req_20260626_002",
  "status": "needs_clarification",
  "questions": [
    {
      "field": "intent.content_type",
      "message": "需要确认用户要冥想、故事还是ASMR"
    }
  ]
}
```

## 6. Cache Key Contract

Workflow cache keys must include:

```text
normalized intent
+ provider
+ script_policy_version
+ voice_profile
+ tts_model
+ music_prompt_policy_version
+ music_model
+ mix_policy_version
+ mix_preset
+ music_mix_enabled
+ voice_mix_volume
+ music_mix_volume
+ target_duration_sec
```

This prevents old and new generations from colliding after script policy, voice, music, or mix changes.

## 7. Status Vocabulary

Top-level `status` values:

```text
queued
script_ready
speech_generating
speech_ready
music_generating
music_ready
mixing
succeeded
failed
needs_clarification
```

Step-level status values:

```text
pending
running
succeeded
failed
skipped
```

## 8. Implementation Notes

Initial integration should use internal Python DTOs in `floppy_backend.workflows.contracts`. Once stable, expose the same contract as HTTP:

```text
POST /workflows/sleep-audio
GET /workflows/{workflow_run_id}
```

P0 can store workflow diagnostics inside `generation_jobs.provider_payload`. P1 should add dedicated tables:

```text
workflow_runs
workflow_steps
workflow_artifacts
```
