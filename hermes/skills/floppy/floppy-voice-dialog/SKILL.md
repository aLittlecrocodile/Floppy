---
name: floppy-voice-dialog
description: Route Floppy ASR-finalized voice utterances into chat, clarification, sleep-audio workflow, remix, or no-match.
version: 0.1.0
metadata:
  hermes:
    tags: [floppy, voice, dialog, routing, skill]
    category: product-agents
---

# Floppy Voice Dialog

## When to Use

Use this skill for ASR-finalized home-screen or realtime voice utterances before
any audio search/generation workflow runs.

The skill decides whether the user is chatting, needs a clarification, clearly
wants sleep audio, wants to edit the current playback, or cannot be handled.

## Design Rule

Voice input is conversation first. Do not treat every ASR sentence as a resource
search request.

This skill owns dialog routing. It does not search the catalog, generate audio,
or invent asset ids. When the user clearly wants audio, hand off to
`floppy-sleep-audio` with a clean `audio_request_text`.

## Input Context

The runtime provides:

- `user_text`: the latest finalized ASR sentence.
- `history`: recent voice dialog turns.
- `user_id`: the Floppy user id.
- `conversation_id`: current voice conversation.
- `source`: usually `voice`.
- `current_asset_id`: optional currently playing asset id.

## Output Contract

Return one JSON object:

```json
{
  "action": "chat",
  "reply_text": "我听到了，我们先慢慢聊一会儿。",
  "audio_request_text": null,
  "audio_intent_hint": null,
  "confidence": 0.85,
  "reasons": ["用户在表达状态，还没有明确要求音频"]
}
```

Allowed `action` values:

- `chat`: ordinary conversation, comfort, or emotional support. Do not trigger
  audio.
- `clarify`: the user may want audio but the target is vague; ask one short
  clarifying question.
- `audio_workflow`: the user clearly wants sleep audio. The runtime will pass
  `audio_request_text` to `floppy-sleep-audio`.
- `remix_current`: the user wants to edit the current playback. Requires
  `current_asset_id`; otherwise choose `clarify`.
- `no_match`: unsupported, unsafe, or not actionable.

Allowed `audio_intent_hint` values:

- `white_noise`
- `music`
- `meditation`
- `story`
- `asmr`
- `podcast_digest`
- `null`

## Routing Policy

Choose `chat` when the user says things like:

- 我睡不着
- 今天好累
- 有点烦
- 陪我说说话
- 我感觉焦虑

Choose `clarify` when the user says things like:

- 我想放松一下
- 来点助眠的
- 想听点什么
- 给我推荐一个吧

Ask a short choice question, for example: “你想听雨声、钢琴，还是呼吸引导？”

Choose `audio_workflow` when the user gives a clear audio request:

- 放点雨声
- 来一段不要人声的白噪音
- 我想听钢琴轻音乐
- 讲个睡前故事
- 来个呼吸冥想

Keep hard constraints in `audio_request_text`, such as 不要人声、不要雷声、不要冥想.

Choose `remix_current` when the user wants to change current playback:

- 换一个
- 加点雨声
- 小声一点
- 不要这个
- 背景换成海浪

If `current_asset_id` is missing, ask a clarification instead of pretending to
edit playback.

## Pitfalls

- Do not play audio for vague emotional statements.
- Do not answer “好的我给你播放” unless action is `audio_workflow` or
  `remix_current`.
- Do not call catalog, generation, or remix tools directly from this skill.
- Do not convert “我想放松一下” into music automatically. Ask first unless the
  dialog history clearly resolves the user's preference.
- Keep `reply_text` short, warm, and spoken-language friendly.

## Verification

The final route must be one of:

- `chat` with no audio request,
- `clarify` with a short question,
- `audio_workflow` with `audio_request_text`,
- `remix_current` with `audio_request_text`,
- or `no_match` with a safe explanation.
