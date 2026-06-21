# MiniMax POC Checklist

Use this checklist before and during a real MiniMax text-to-audio proof of concept. Real API calls are intentionally kept out of default `pytest`; run the smoke command manually only when you intend to spend provider credits.

## Configuration checklist

- Set required environment variables:
  - `FLOPPY_AUDIO_PROVIDER=minimax`
  - `FLOPPY_MINIMAX_API_KEY=<your MiniMax API key>`
- Confirm the correct API host for the account region:
  - Default: `FLOPPY_MINIMAX_BASE_URL=https://api.minimaxi.com`
  - If testing another host and auth fails, retry Chinese-account keys with `https://api.minimaxi.com`.
- Confirm model and voice settings:
  - `FLOPPY_MINIMAX_MODEL=speech-2.8-hd` or another supported MiniMax speech model
  - `FLOPPY_MINIMAX_VOICE_ID=Chinese (Mandarin)_Warm_Bestie` or the selected voice
  - Optional tuning: `FLOPPY_MINIMAX_SPEED`, `FLOPPY_MINIMAX_VOLUME`, `FLOPPY_MINIMAX_PITCH`, `FLOPPY_MINIMAX_EMOTION`
- Confirm audio output settings:
  - `FLOPPY_MINIMAX_SAMPLE_RATE=32000`
  - `FLOPPY_MINIMAX_BITRATE=128000`
  - `FLOPPY_MINIMAX_CHANNEL=1`
- Use a dedicated database/storage path for the POC if you want isolated results:
  - `FLOPPY_DATABASE_PATH=data/minimax_smoke.db`
  - `FLOPPY_STORAGE_DIR=storage/audio`

## Manual smoke command

Default `pytest` must not call the real MiniMax API. Run the real API smoke manually:

```bash
FLOPPY_MINIMAX_API_KEY=<your-key> \
FLOPPY_AUDIO_PROVIDER=minimax \
python scripts/minimax_smoke.py
```

Optional isolated run:

```bash
FLOPPY_MINIMAX_API_KEY=<your-key> \
FLOPPY_AUDIO_PROVIDER=minimax \
FLOPPY_DATABASE_PATH=data/minimax_smoke.db \
FLOPPY_STORAGE_DIR=storage/audio \
python scripts/minimax_smoke.py
```

## Success criteria

- Script exits with status code `0`.
- The profile request returns HTTP `200`.
- The generation request returns HTTP `200`.
- The generation body has `status=succeeded` and `match_type=generated` or another expected non-failure match.
- The generation job records:
  - `provider=minimax_t2a`
  - `provider_model` matching the configured MiniMax model
  - `provider_status=succeeded` for sync generation, or `success` for async generation
  - `script_chars` greater than `0`
  - `usage_characters` greater than `0`
  - `estimated_cost_usd` greater than or equal to `0`
- The audio endpoint returns HTTP `200` with a non-empty response body.
- The audio content type is `audio/mpeg` for MiniMax-generated `.mp3` assets.

## Failure scenarios to verify

- Missing API key:
  - Expected: provider setup fails with a message mentioning `FLOPPY_MINIMAX_API_KEY`.
- Wrong API host for the account/key:
  - Expected: auth failure includes a hint to try `FLOPPY_MINIMAX_BASE_URL=https://api.minimaxi.com` when using the international `minimax.io` host.
- Invalid or expired API key:
  - Expected: job response is `failed`; job details include `error_code` and `error_message`.
- Provider task failure or expiration for async generation:
  - Expected: job response is `failed`; job details include the MiniMax task status in `error_message`.
- Empty or malformed provider response:
  - Expected: job response is `failed` and no audio asset is created.
- File retrieval failure for async generation:
  - Expected: job response is `failed`; `provider_task_id`/`provider_file_id` may be absent depending on when retrieval failed.

## Audio file checks

- Confirm generated files are stored under the configured `FLOPPY_STORAGE_DIR`.
- Confirm object keys for on-demand MiniMax generation use the `.mp3` extension.
- Confirm generated audio files are non-empty.
- Confirm `/audio/{object_key}` returns the generated file.
- Confirm the response content type starts with `audio/mpeg` for MiniMax output.
- Listen to the sample and check:
  - Voice matches the selected voice/style.
  - Speech is intelligible and in the expected language.
  - Pause markers are rendered naturally.
  - No clipping, silence-only output, truncation, or obvious artifacts.

## Cost recording

- For each successful generation job, inspect `/generation-jobs/{job_id}`.
- Confirm `usage_characters` is populated from MiniMax response metadata or falls back to script length.
- Confirm `estimated_cost_usd` is populated using the configured model rate.
- Confirm `provider_payload` keeps useful diagnostics such as `trace_id`, `extra_info`, or async task/status payloads without storing secrets.
- Record the final POC cost using the sum of `estimated_cost_usd` for MiniMax jobs in the POC database.
