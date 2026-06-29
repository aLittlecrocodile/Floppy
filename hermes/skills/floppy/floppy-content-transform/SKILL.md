---
name: floppy-content-transform
description: Transform user uploaded txt content into low-density Floppy sleep audio generation jobs.
version: 0.1.0
metadata:
  hermes:
    tags: [floppy, uploads, content-transform, podcast-digest, mcp]
    category: product-agents
---

# Floppy Content Transform

## When to Use

Use this skill when the user wants an uploaded article, note, transcript, or
other text content turned into sleep-friendly audio.

The current backend supports txt upload transformation. Audio uploads are
already playable. PDF transformation is not enabled yet; ask the user to upload
txt or return a clear unsupported response.

## Design Rule

Hermes decides how uploaded content should become a sleep-audio request. Floppy
executes upload state, generation jobs, storage, budget enforcement, and safety.

## Available MCP Tools

Hermes registers Floppy MCP tools with the `mcp_floppy_` prefix:

- `mcp_floppy_list_uploads`: list user uploads.
- `mcp_floppy_get_upload`: inspect one upload and generated output.
- `mcp_floppy_generate_audio_from_upload`: enqueue txt-to-sleep-audio job.
- `mcp_floppy_get_generation_job`: poll the generated job.
- `mcp_floppy_start_playback`: record playback after generated output starts.
- `mcp_floppy_delete_upload`: delete an upload record when requested.
- `mcp_floppy_retry_upload`: reset a failed upload state.

## Transform Modes

Default to `podcast_digest` for uploaded text. Use another intent only when the
user explicitly asks:

- `podcast_digest`: low-density article/note digest for bedtime.
- `story`: turn content into a gentle narrative.
- `meditation`: use content as a theme for guided relaxation.
- `asmr`: very soft spoken rendering with short phrases.

Do not use `white_noise` or `music` for text transformation unless the user
explicitly asks to ignore the text and create non-voice ambience.

## Procedure

1. Call `mcp_floppy_list_uploads(user_id)` if the user refers to “刚上传的” or
   does not provide an upload id.
2. Call `mcp_floppy_get_upload(user_id, upload_id)` before transforming.
3. If `fileType` is `txt`, call `mcp_floppy_generate_audio_from_upload` with:
   - concise `request_text`;
   - `audio_intent`, usually `podcast_digest`;
   - optional `tone`, `duration_sec`, and `voice_style`.
4. Return the generation job id if queued. Poll with
   `mcp_floppy_get_generation_job` only when the client needs the completed
   asset in the same interaction.
5. When the generated asset begins playing, call `mcp_floppy_start_playback`
   with `source="generated"` or `source="import"` depending on product surface.

## Output Contract

For a successful transform, return one of:

```json
{
  "action": "generate_job",
  "job_id": "job_xxx",
  "upload_id": "upload_xxx",
  "reply_text": "我会把这篇内容改成更适合睡前听的慢节奏音频。"
}
```

or, if already completed:

```json
{
  "action": "play_asset",
  "asset_id": "aud_xxx",
  "upload_id": "upload_xxx"
}
```

## Pitfalls

- Do not claim PDF transformation works until a PDF parser workflow exists.
- Do not summarize dense information in a stimulating or productivity-oriented
  style.
- Do not preserve upsetting, urgent, violent, or medical-claim wording.
- Do not bypass `floppy-safety-quality` for generated spoken scripts.

## Verification

The upload should move to `Generating` and then `Completed` with a
`generatedAudio` item when generation succeeds.
