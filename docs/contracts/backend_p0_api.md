# Backend P0 API Contracts

Base URL: `http://127.0.0.1:8000`

## Existing APIs (unchanged)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/admin/seed` | Seed catalog assets |
| PUT | `/users/{user_id}/profile` | Create/update sleep profile |
| GET | `/users/{user_id}/profile` | Get profile |
| POST | `/users/{user_id}/profile/checkin` | Tonight's mood/stress |
| GET | `/users/{user_id}/profile/context` | Profile + budget |
| POST | `/normalize` | Normalize request text |
| POST | `/assets/search` | Search audio assets |
| GET | `/users/{user_id}/recommendations` | Get recommendations |
| POST | `/users/{user_id}/generate-audio` | Sync generate |
| POST | `/users/{user_id}/generation-jobs` | Async generate (202) |
| GET | `/generation-jobs/{job_id}` | Get job status |
| POST | `/users/{user_id}/events` | Record event |
| POST | `/agent/decide` | Agent decision endpoint |
| POST | `/demo/chat` | Demo chat endpoint |
| GET | `/audio/{object_key}` | Stream audio file |
| WS | `/voice/ws` | 实时语音对话（全双工）— 见 [`voice_dialog_ws.md`](./voice_dialog_ws.md) |

---

## P0 New APIs

### 1. User Questionnaire

#### PUT `/users/{user_id}/questionnaire`

Save/update user questionnaire (onboarding survey).

```json
{
  "gender": "female",
  "age_range": "25-34",
  "occupation": "designer",
  "bedtime": "23:30",
  "main_sleep_problem": "difficulty_falling_asleep",
  "bedtime_habits": ["phone", "reading"],
  "favorite_content_types": ["meditation", "story"],
  "preferred_companion_style": "warm",
  "voice_preferences": ["warm_female", "gentle_female"]
}
```

All fields optional. Response: full `UserQuestionnaire` object with `user_id`, `completed_at`, `updated_at`.

#### GET `/users/{user_id}/questionnaire`

Returns 200 with questionnaire or 404.

---

### 2. Playback History & Feedback

#### POST `/users/{user_id}/playback` → 201

Start a playback session.

```json
{
  "asset_id": "aud_xxx",
  "source": "recommend",
  "request_text": "optional original request"
}
```

`source` enum: `recommend` | `generated` | `remix` | `import`

Response: `{"record_id": "pb_xxx"}`

#### POST `/users/{user_id}/playback/{record_id}/feedback`

Submit feedback for a playback session.

```json
{
  "feedback_type": "trial_rating",
  "rating": 4,
  "progress": 0.3,
  "morning_feedback": null
}
```

`feedback_type` enum: `trial_rating` | `favorite` | `dislike` | `skip` | `complete` | `morning_feedback`

- `rating`: 1-5, optional
- `progress`: 0.0-1.0, optional
- `morning_feedback`: free text, for morning_feedback type

#### GET `/users/{user_id}/playback/history?limit=50`

Returns last N playback records (max 50), newest first.

```json
[
  {
    "id": "pb_xxx",
    "user_id": "u1",
    "asset_id": "aud_xxx",
    "title": "呼吸觉察·雨夜版",
    "request_text": null,
    "source": "recommend",
    "started_at": "2026-06-26T...",
    "completed_at": "2026-06-26T...",
    "progress": 1.0,
    "rating": 4,
    "feedback_type": "complete",
    "morning_feedback": null
  }
]
```

---

### 3. Remix

#### POST `/users/{user_id}/remix` → 202

Create a remix job (voice + ambient mix).

```json
{
  "voice_asset_id": "aud_meditation_xxx",
  "ambient_asset_id": "aud_rain_xxx",
  "ambient_tags": [],
  "voice_volume": 1.0,
  "ambient_volume": 0.3
}
```

- `ambient_asset_id`: optional if using tags to auto-select
- `voice_volume` / `ambient_volume`: 0.0-2.0

Response: `RemixJob` object (status=queued initially, runs in background).

#### GET `/remix-jobs/{job_id}`

Poll remix job status.

```json
{
  "id": "rmx_xxx",
  "status": "succeeded",
  "output_asset_id": "aud_xxx",
  "output_asset": { "playback_url": "...", ... },
  "error_message": null
}
```

`status`: `queued` | `processing` | `succeeded` | `failed`

---

## Data Notes

- `created_by` values: `seed_placeholder` (seed), `pregen_local` (local pregen), `pregen_minimax` (real TTS), `ondemand` (live generate), `remix` (remix output)
- `is_placeholder` in `/demo/chat`: true when `created_by` is seed/pregen_local
- Remix output assets have tag `remix` and are eligible for recommendation
- Generation jobs now track `target_duration_sec` and `actual_duration_sec` fields (nullable, populated when available)
