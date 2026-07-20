from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from threading import RLock

from floppy_backend.models import AudioAsset, AudioAssetIn, AudioScript, AudioScriptIn, AudioType, EventIn, GenerationDirective, GenerationJob, MixParams, PlaybackRecord, ProfileCheckinIn, RemixJob, RemixSession, UserProfile, UserProfileIn, UserQuestionnaire, UserQuestionnaireIn
from floppy_backend.utils import dumps, loads, stable_id, utcnow


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._lock = RLock()

    def ensure_user(self, user_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO users(id, created_at) VALUES (?, ?)",
                (user_id, utcnow().isoformat()),
            )
            self.conn.commit()

    def upsert_profile(self, user_id: str, profile: UserProfileIn, segment: str) -> UserProfile:
        self.ensure_user(user_id)
        updated_at = utcnow()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO user_profiles (
                    user_id, audio_type_preferences, voice_preferences, background_preferences,
                    duration_preference_min, stress_level, anxiety_level, avg_sleep_latency_min,
                    mood_tags, segment, profile_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    audio_type_preferences=excluded.audio_type_preferences,
                    voice_preferences=excluded.voice_preferences,
                    background_preferences=excluded.background_preferences,
                    duration_preference_min=excluded.duration_preference_min,
                    stress_level=excluded.stress_level,
                    anxiety_level=excluded.anxiety_level,
                    avg_sleep_latency_min=excluded.avg_sleep_latency_min,
                    mood_tags=excluded.mood_tags,
                    segment=excluded.segment,
                    profile_version=profile_version + 1,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    dumps([item.value for item in profile.audio_type_preferences]),
                    dumps(profile.voice_preferences),
                    dumps(profile.background_preferences),
                    profile.duration_preference_min,
                    profile.stress_level.value,
                    profile.anxiety_level.value,
                    profile.avg_sleep_latency_min,
                    dumps(profile.mood_tags),
                    segment,
                    updated_at.isoformat(),
                ),
            )
            self.conn.commit()
        existing = self.get_profile(user_id)
        if existing is None:
            raise RuntimeError("failed to read user profile after upsert")
        return existing

    def get_profile(self, user_id: str) -> UserProfile | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return UserProfile(
            user_id=row["user_id"],
            audio_type_preferences=[AudioType(item) for item in loads(row["audio_type_preferences"])],
            voice_preferences=loads(row["voice_preferences"]),
            background_preferences=loads(row["background_preferences"]),
            duration_preference_min=row["duration_preference_min"],
            stress_level=row["stress_level"],
            anxiety_level=row["anxiety_level"],
            avg_sleep_latency_min=row["avg_sleep_latency_min"],
            mood_tags=loads(row["mood_tags"]),
            segment=row["segment"],
            algo_segment=row["algo_segment"],
            tonight_mood=row["tonight_mood"],
            tonight_stress=row["tonight_stress"],
            profile_version=row["profile_version"],
            updated_at=_dt(row["updated_at"]),
        )

    def update_profile_checkin(self, user_id: str, checkin: ProfileCheckinIn) -> UserProfile:
        self.ensure_user(user_id)
        profile = self.get_profile(user_id)
        if profile is None:
            profile = self.upsert_profile(user_id, UserProfileIn(), "balanced_sleep")
        now = utcnow()
        with self._lock:
            self.conn.execute(
                """
                UPDATE user_profiles
                SET tonight_mood = COALESCE(?, tonight_mood),
                    tonight_stress = COALESCE(?, tonight_stress),
                    avg_sleep_latency_min = COALESCE(?, avg_sleep_latency_min),
                    profile_version = profile_version + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    checkin.tonight_mood,
                    checkin.tonight_stress.value if checkin.tonight_stress else None,
                    checkin.sleep_latency_hint_min,
                    now.isoformat(),
                    user_id,
                ),
            )
            self.conn.commit()
        updated = self.get_profile(user_id)
        if updated is None:
            raise RuntimeError("failed to read user profile after checkin")
        return updated

    def upsert_asset(self, asset: AudioAssetIn) -> AudioAsset:
        existing_asset = self.get_asset_by_prompt_hash(asset.prompt_hash)
        asset_id = existing_asset.id if existing_asset else stable_id(
            "aud",
            {
                "prompt_hash": asset.prompt_hash,
                "object_key": asset.object_key,
            },
        )
        created_at = utcnow()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO audio_assets (
                    id, type, title, object_key, duration_sec, language, voice_id, prompt_hash,
                    content_hash, mood_tags, tags, sleep_stage, user_segment_tags, safety_status,
                    quality_score, embedding, created_by, tier, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,
                    title=excluded.title,
                    object_key=excluded.object_key,
                    duration_sec=excluded.duration_sec,
                    language=excluded.language,
                    voice_id=excluded.voice_id,
                    prompt_hash=excluded.prompt_hash,
                    content_hash=excluded.content_hash,
                    mood_tags=excluded.mood_tags,
                    tags=excluded.tags,
                    sleep_stage=excluded.sleep_stage,
                    user_segment_tags=excluded.user_segment_tags,
                    safety_status=excluded.safety_status,
                    quality_score=excluded.quality_score,
                    embedding=excluded.embedding,
                    created_by=excluded.created_by,
                    tier=excluded.tier
                """,
                (
                    asset_id,
                    asset.type.value,
                    asset.title,
                    asset.object_key,
                    asset.duration_sec,
                    asset.language,
                    asset.voice_id,
                    asset.prompt_hash,
                    asset.content_hash,
                    dumps(asset.mood_tags),
                    dumps(asset.tags),
                    asset.sleep_stage,
                    dumps(asset.user_segment_tags),
                    asset.safety_status,
                    asset.quality_score,
                    dumps(asset.embedding),
                    asset.created_by,
                    asset.tier,
                    created_at.isoformat(),
                ),
            )
            self.conn.commit()
        existing = self.get_asset(asset_id)
        if existing is None:
            raise RuntimeError("failed to read audio asset after upsert")
        return existing

    def get_asset(self, asset_id: str) -> AudioAsset | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM audio_assets WHERE id = ?", (asset_id,)).fetchone()
        return self._asset_from_row(row) if row is not None else None

    def get_asset_by_prompt_hash(self, prompt_hash: str) -> AudioAsset | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM audio_assets WHERE prompt_hash = ?", (prompt_hash,)).fetchone()
        return self._asset_from_row(row) if row is not None else None

    def upsert_audio_script(self, script: AudioScriptIn) -> AudioScript:
        self.ensure_user(script.user_id)
        script_id = stable_id("scr", {"script_hash": script.script_hash})
        created_at = utcnow()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO audio_scripts (
                    id, user_id, title, content_type, language, script_text, script_hash,
                    pause_density, estimated_duration_sec, safety_status, safety_notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(script_hash) DO UPDATE SET
                    title=excluded.title,
                    content_type=excluded.content_type,
                    language=excluded.language,
                    script_text=excluded.script_text,
                    pause_density=excluded.pause_density,
                    estimated_duration_sec=excluded.estimated_duration_sec,
                    safety_status=excluded.safety_status,
                    safety_notes=excluded.safety_notes
                """,
                (
                    script_id,
                    script.user_id,
                    script.title,
                    script.content_type.value,
                    script.language,
                    script.script_text,
                    script.script_hash,
                    script.pause_density,
                    script.estimated_duration_sec,
                    script.safety_status,
                    dumps(script.safety_notes),
                    created_at.isoformat(),
                ),
            )
            self.conn.commit()
        existing = self.get_audio_script_by_hash(script.script_hash)
        if existing is None:
            raise RuntimeError("failed to read audio script after upsert")
        return existing

    def get_audio_script(self, script_id: str) -> AudioScript | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM audio_scripts WHERE id = ?", (script_id,)).fetchone()
        return self._script_from_row(row) if row is not None else None

    def get_audio_script_by_hash(self, script_hash: str) -> AudioScript | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM audio_scripts WHERE script_hash = ?", (script_hash,)).fetchone()
        return self._script_from_row(row) if row is not None else None

    def list_assets(self, limit: int = 500, tier: str | None = None) -> list[AudioAsset]:
        # Older builds mislabeled TTS speech as music. Keep those invalid rows
        # for job diagnostics, but never expose them as playable catalog items.
        query = """
            SELECT * FROM audio_assets
            WHERE safety_status = 'approved'
              AND id NOT IN (
                  SELECT asset_id FROM generation_jobs
                  WHERE normalized_intent = 'music'
                    AND provider_model LIKE 'speech-%'
                    AND asset_id IS NOT NULL
              )
        """
        params: list = []
        if tier is not None:
            query += " AND tier = ?"
            params.append(tier)
        query += " ORDER BY quality_score DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def has_generation_request(self, cache_key: str, request_text: str) -> bool:
        """True when this exact wording already produced this cache key — the
        only case where serving the cached asset without consulting the agent
        is safe (the lossy normalizer collapses unrelated requests onto the
        same key)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM generation_jobs WHERE cache_key = ? AND request_text = ? LIMIT 1",
                (cache_key, request_text),
            ).fetchone()
        return row is not None

    def last_event_asset_id(self, user_id: str, event_type: str) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT asset_id FROM events WHERE user_id = ? AND event_type = ? ORDER BY created_at DESC LIMIT 1",
                (user_id, event_type),
            ).fetchone()
        return row["asset_id"] if row is not None else None

    def create_generation_job(
        self,
        *,
        user_id: str,
        request_text: str,
        normalized_intent: str,
        cache_key: str,
        status: str,
        provider: str,
        asset_id: str | None = None,
        script_id: str | None = None,
        script_hash: str | None = None,
        script_chars: int | None = None,
        provider_model: str | None = None,
        provider_task_id: str | None = None,
        provider_file_id: str | None = None,
        provider_status: str | None = None,
        provider_payload: dict | None = None,
        usage_characters: int | None = None,
        estimated_cost_usd: float | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        latency_ms: int | None = None,
    ) -> str:
        self.ensure_user(user_id)
        now = utcnow().isoformat()
        job_id = stable_id("job", {"user_id": user_id, "request_text": request_text, "cache_key": cache_key, "at": now})
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO generation_jobs (
                    id, user_id, request_text, normalized_intent, cache_key, status,
                    provider, asset_id, script_id, script_hash, script_chars, provider_model,
                    provider_task_id, provider_file_id, provider_status, provider_payload,
                    usage_characters, estimated_cost_usd, error_code, error_message,
                    latency_ms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    user_id,
                    request_text,
                    normalized_intent,
                    cache_key,
                    status,
                    provider,
                    asset_id,
                    script_id,
                    script_hash,
                    script_chars,
                    provider_model,
                    provider_task_id,
                    provider_file_id,
                    provider_status,
                    dumps(provider_payload) if provider_payload is not None else None,
                    usage_characters,
                    estimated_cost_usd,
                    error_code,
                    error_message,
                    latency_ms,
                    now,
                    now,
                ),
            )
            self.conn.commit()
        return job_id

    def claim_generation_job(
        self,
        *,
        user_id: str,
        request_text: str,
        normalized_intent: str,
        cache_key: str,
        status: str,
        provider: str,
        directive_json: str | None = None,
    ) -> tuple[GenerationJob, bool]:
        self.ensure_user(user_id)
        with self._lock:
            existing = self.conn.execute(
                """
                SELECT * FROM generation_jobs
                WHERE user_id = ?
                  AND cache_key = ?
                  AND status IN ('queued', 'generating')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, cache_key),
            ).fetchone()
            if existing is not None:
                return self._job_from_row(existing), False

            now = utcnow().isoformat()
            job_id = stable_id("job", {"user_id": user_id, "request_text": request_text, "cache_key": cache_key, "at": now})
            self.conn.execute(
                """
                INSERT INTO generation_jobs (
                    id, user_id, request_text, normalized_intent, cache_key, status,
                    provider, asset_id, script_id, script_hash, script_chars, provider_model,
                    provider_task_id, provider_file_id, provider_status, provider_payload,
                    usage_characters, estimated_cost_usd, error_code, error_message,
                    latency_ms, directive_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)
                """,
                (job_id, user_id, request_text, normalized_intent, cache_key, status, provider, directive_json, now, now),
            )
            self.conn.commit()
            created = self.conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._job_from_row(created), True

    def claim_job_for_run(self, job_id: str) -> bool:
        """Atomically claim a job for execution. Returns False when the job is
        already generating (someone else runs it) or already succeeded —
        callers must NOT run the pipeline in that case. 'queued' and 'failed'
        jobs claim successfully (prewarm / retry-of-failed keep working)."""
        with self._lock:
            cursor = self.conn.execute(
                """
                UPDATE generation_jobs
                SET status = 'generating', updated_at = ?
                WHERE id = ? AND status NOT IN ('generating', 'succeeded')
                """,
                (utcnow().isoformat(), job_id),
            )
            self.conn.commit()
            return cursor.rowcount == 1

    def update_generation_job(
        self,
        job_id: str,
        *,
        status: str,
        asset_id: str | None = None,
        script_id: str | None = None,
        script_hash: str | None = None,
        script_chars: int | None = None,
        provider_model: str | None = None,
        provider_task_id: str | None = None,
        provider_file_id: str | None = None,
        provider_status: str | None = None,
        provider_payload: dict | None = None,
        usage_characters: int | None = None,
        estimated_cost_usd: float | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        with self._lock:
            self.conn.execute(
                """
                UPDATE generation_jobs
                SET status = ?,
                    asset_id = COALESCE(?, asset_id),
                    script_id = COALESCE(?, script_id),
                    script_hash = COALESCE(?, script_hash),
                    script_chars = COALESCE(?, script_chars),
                    provider_model = COALESCE(?, provider_model),
                    provider_task_id = COALESCE(?, provider_task_id),
                    provider_file_id = COALESCE(?, provider_file_id),
                    provider_status = COALESCE(?, provider_status),
                    provider_payload = COALESCE(?, provider_payload),
                    usage_characters = COALESCE(?, usage_characters),
                    estimated_cost_usd = COALESCE(?, estimated_cost_usd),
                    error_code = COALESCE(?, error_code),
                    error_message = COALESCE(?, error_message),
                    latency_ms = COALESCE(?, latency_ms),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    asset_id,
                    script_id,
                    script_hash,
                    script_chars,
                    provider_model,
                    provider_task_id,
                    provider_file_id,
                    provider_status,
                    dumps(provider_payload) if provider_payload is not None else None,
                    usage_characters,
                    estimated_cost_usd,
                    error_code,
                    error_message,
                    latency_ms,
                    utcnow().isoformat(),
                    job_id,
                ),
            )
            self.conn.commit()

    def get_generation_job(self, job_id: str) -> GenerationJob | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._job_from_row(row)

    def record_event(self, user_id: str, event: EventIn) -> str:
        self.ensure_user(user_id)
        now = utcnow()
        event_id = stable_id(
            "evt",
            {"user_id": user_id, "event_type": event.event_type, "asset_id": event.asset_id, "payload": event.payload, "at": now.isoformat()},
        )
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO events(id, user_id, event_type, asset_id, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, user_id, event.event_type, event.asset_id, dumps(event.payload), now.isoformat()),
            )
            self.conn.commit()
        return event_id

    def generation_usage_since(self, user_id: str, *, hours: int = 24) -> tuple[int, int]:
        since = (utcnow() - timedelta(hours=hours)).isoformat()
        with self._lock:
            row = self.conn.execute(
                """
                SELECT COALESCE(SUM(usage_characters), 0) AS chars,
                       COUNT(*) AS count
                FROM generation_jobs
                WHERE user_id = ?
                  AND status = 'succeeded'
                  AND asset_id IS NOT NULL
                  AND usage_characters IS NOT NULL
                  AND created_at >= ?
                """,
                (user_id, since),
            ).fetchone()
        return int(row["chars"] or 0), int(row["count"] or 0)

    def _asset_from_row(self, row: sqlite3.Row) -> AudioAsset:
        return AudioAsset(
            id=row["id"],
            type=AudioType(row["type"]),
            title=row["title"],
            object_key=row["object_key"],
            duration_sec=row["duration_sec"],
            language=row["language"],
            voice_id=row["voice_id"],
            prompt_hash=row["prompt_hash"],
            content_hash=row["content_hash"],
            mood_tags=loads(row["mood_tags"]),
            tags=loads(row["tags"]) if row["tags"] else [],
            sleep_stage=row["sleep_stage"],
            user_segment_tags=loads(row["user_segment_tags"]),
            safety_status=row["safety_status"],
            quality_score=row["quality_score"],
            embedding=loads(row["embedding"]),
            created_by=row["created_by"],
            tier=row["tier"] if "tier" in row.keys() else "community",
            created_at=_dt(row["created_at"]),
        )

    def _script_from_row(self, row: sqlite3.Row) -> AudioScript:
        return AudioScript(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            content_type=AudioType(row["content_type"]),
            language=row["language"],
            script_text=row["script_text"],
            script_hash=row["script_hash"],
            pause_density=row["pause_density"],
            estimated_duration_sec=row["estimated_duration_sec"],
            safety_status=row["safety_status"],
            safety_notes=loads(row["safety_notes"]),
            created_at=_dt(row["created_at"]),
        )

    def _job_from_row(self, row: sqlite3.Row) -> GenerationJob:
        asset = self.get_asset(row["asset_id"]) if row["asset_id"] else None
        script = self.get_audio_script(row["script_id"]) if row["script_id"] else None
        directive = None
        directive_raw = row["directive_json"] if "directive_json" in row.keys() else None
        if directive_raw:
            try:
                directive = GenerationDirective.model_validate(loads(directive_raw))
            except Exception:  # noqa: BLE001 — tolerate legacy/garbled rows
                directive = None
        return GenerationJob(
            id=row["id"],
            user_id=row["user_id"],
            request_text=row["request_text"],
            normalized_intent=row["normalized_intent"],
            cache_key=row["cache_key"],
            status=row["status"],
            provider=row["provider"],
            asset_id=row["asset_id"],
            script_id=row["script_id"],
            script_hash=row["script_hash"],
            script_chars=row["script_chars"],
            provider_model=row["provider_model"],
            provider_task_id=row["provider_task_id"],
            provider_file_id=row["provider_file_id"],
            provider_status=row["provider_status"],
            provider_payload=loads(row["provider_payload"]) if row["provider_payload"] else None,
            usage_characters=row["usage_characters"],
            estimated_cost_usd=row["estimated_cost_usd"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            latency_ms=row["latency_ms"],
            directive=directive,
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            asset=asset,
            script=script,
        )

    # --- Questionnaire ---

    def upsert_questionnaire(self, user_id: str, data: UserQuestionnaireIn) -> UserQuestionnaire:
        self.ensure_user(user_id)
        now = utcnow()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO user_questionnaires (
                    user_id, gender, age_range, occupation, bedtime, main_sleep_problem,
                    bedtime_habits, favorite_content_types, preferred_companion_style,
                    voice_preferences, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    gender=excluded.gender, age_range=excluded.age_range,
                    occupation=excluded.occupation, bedtime=excluded.bedtime,
                    main_sleep_problem=excluded.main_sleep_problem,
                    bedtime_habits=excluded.bedtime_habits,
                    favorite_content_types=excluded.favorite_content_types,
                    preferred_companion_style=excluded.preferred_companion_style,
                    voice_preferences=excluded.voice_preferences,
                    completed_at=excluded.completed_at, updated_at=excluded.updated_at
                """,
                (
                    user_id, data.gender, data.age_range, data.occupation, data.bedtime,
                    data.main_sleep_problem, dumps(data.bedtime_habits),
                    dumps(data.favorite_content_types), data.preferred_companion_style,
                    dumps(data.voice_preferences), now.isoformat(), now.isoformat(),
                ),
            )
            self.conn.commit()
        return self.get_questionnaire(user_id)  # type: ignore[return-value]

    def get_questionnaire(self, user_id: str) -> UserQuestionnaire | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM user_questionnaires WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return UserQuestionnaire(
            user_id=row["user_id"], gender=row["gender"], age_range=row["age_range"],
            occupation=row["occupation"], bedtime=row["bedtime"],
            main_sleep_problem=row["main_sleep_problem"],
            bedtime_habits=loads(row["bedtime_habits"]),
            favorite_content_types=loads(row["favorite_content_types"]),
            preferred_companion_style=row["preferred_companion_style"],
            voice_preferences=loads(row["voice_preferences"]),
            completed_at=_dt(row["completed_at"]) if row["completed_at"] else None,
            updated_at=_dt(row["updated_at"]),
        )

    # --- Playback History ---

    def record_playback_start(self, user_id: str, asset_id: str, title: str, source: str, request_text: str | None = None, parent_asset_id: str | None = None, ambient_asset_id: str | None = None) -> str:
        self.ensure_user(user_id)
        now = utcnow()
        record_id = stable_id("pb", {"user_id": user_id, "asset_id": asset_id, "at": now.isoformat()})
        with self._lock:
            self.conn.execute(
                """INSERT INTO playback_history (id, user_id, asset_id, title, request_text, source, parent_asset_id, ambient_asset_id, started_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record_id, user_id, asset_id, title, request_text, source, parent_asset_id, ambient_asset_id, now.isoformat(), now.isoformat()),
            )
            self.conn.commit()
        return record_id

    def touch_recent_playback(self, user_id: str, asset_id: str, *, progress: float | None = None, within_hours: int = 6) -> str | None:
        """If the newest history row for (user_id, asset_id) is recent (same
        listening session), update its progress and return its id; else None
        (caller inserts a fresh row). Keeps repeated progress reports from
        flooding the history list with duplicates."""
        since = (utcnow() - timedelta(hours=within_hours)).isoformat()
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id FROM playback_history
                WHERE user_id = ? AND asset_id = ? AND started_at >= ?
                ORDER BY started_at DESC LIMIT 1
                """,
                (user_id, asset_id, since),
            ).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "UPDATE playback_history SET progress = COALESCE(?, progress) WHERE id = ?",
                (progress, row["id"]),
            )
            self.conn.commit()
        return row["id"]

    def update_playback_feedback(self, record_id: str, *, feedback_type: str | None = None, rating: int | None = None, progress: float | None = None, morning_feedback: str | None = None, completed: bool = False) -> None:
        now = utcnow()
        with self._lock:
            self.conn.execute(
                """UPDATE playback_history SET
                    feedback_type = COALESCE(?, feedback_type),
                    rating = COALESCE(?, rating),
                    progress = COALESCE(?, progress),
                    morning_feedback = COALESCE(?, morning_feedback),
                    completed_at = CASE WHEN ? THEN ? ELSE completed_at END
                WHERE id = ?""",
                (feedback_type, rating, progress, morning_feedback, completed, now.isoformat() if completed else None, record_id),
            )
            self.conn.commit()

    def recent_events(self, user_id: str, event_types: list[str], limit: int = 10) -> list[dict]:
        """Most-recent events of the given types — feeds ritual context into
        the agent decision prompt (parked worries, gratitude, mood checkins)."""
        if not event_types:
            return []
        placeholders = ",".join("?" for _ in event_types)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT event_type, payload, created_at FROM events "
                f"WHERE user_id = ? AND event_type IN ({placeholders}) "
                f"ORDER BY created_at DESC LIMIT ?",
                (user_id, *event_types, limit),
            ).fetchall()
        out = []
        for r in rows:
            try:
                payload = loads(r["payload"])
            except (TypeError, ValueError):
                payload = {}
            out.append({"event_type": r["event_type"], "payload": payload, "created_at": r["created_at"]})
        return out

    def list_playback_history(self, user_id: str, limit: int = 50) -> list[PlaybackRecord]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM playback_history WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [PlaybackRecord(
            id=r["id"], user_id=r["user_id"], asset_id=r["asset_id"], title=r["title"],
            request_text=r["request_text"], source=r["source"], script_summary=r["script_summary"],
            parent_asset_id=r["parent_asset_id"], ambient_asset_id=r["ambient_asset_id"],
            started_at=_dt(r["started_at"]), completed_at=_dt(r["completed_at"]) if r["completed_at"] else None,
            progress=r["progress"], rating=r["rating"], feedback_type=r["feedback_type"],
            morning_feedback=r["morning_feedback"],
        ) for r in rows]

    # --- Remix Jobs / Sessions ---

    def create_remix_job(self, user_id: str, voice_asset_id: str, ambient_asset_id: str | None, ambient_tags: list[str], voice_volume: float, ambient_volume: float, sound_type: str | None = None, intent: str | None = None, mix_params: MixParams | None = None, foreground_source: str | None = None, generation_job_id: str | None = None) -> str:
        self.ensure_user(user_id)
        now = utcnow()
        job_id = stable_id("rmx", {"user_id": user_id, "voice": voice_asset_id, "at": now.isoformat()})
        with self._lock:
            self.conn.execute(
                """INSERT INTO remix_jobs (id, user_id, voice_asset_id, ambient_asset_id, sound_type, ambient_tags, voice_volume, ambient_volume, status, intent, mix_params, foreground_source, generation_job_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)""",
                (job_id, user_id, voice_asset_id, ambient_asset_id, sound_type, dumps(ambient_tags), voice_volume, ambient_volume, intent, dumps(mix_params.model_dump()) if mix_params else None, foreground_source, generation_job_id, now.isoformat(), now.isoformat()),
            )
            self.conn.commit()
        return job_id

    def update_remix_job(self, job_id: str, *, status: str, output_asset_id: str | None = None, error_message: str | None = None, sound_type: str | None = None, ambient_asset_id: str | None = None, mix_params: MixParams | None = None, intent: str | None = None) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE remix_jobs SET status=?, output_asset_id=COALESCE(?, output_asset_id),
                error_message=COALESCE(?, error_message), sound_type=COALESCE(?, sound_type),
                ambient_asset_id=COALESCE(?, ambient_asset_id), mix_params=COALESCE(?, mix_params),
                intent=COALESCE(?, intent), updated_at=? WHERE id=?""",
                (status, output_asset_id, error_message, sound_type, ambient_asset_id, dumps(mix_params.model_dump()) if mix_params else None, intent, utcnow().isoformat(), job_id),
            )
            self.conn.commit()

    def get_remix_job(self, job_id: str) -> RemixJob | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM remix_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        output_asset = self.get_asset(row["output_asset_id"]) if row["output_asset_id"] else None
        return RemixJob(
            id=row["id"], user_id=row["user_id"], voice_asset_id=row["voice_asset_id"],
            ambient_asset_id=row["ambient_asset_id"], sound_type=row["sound_type"],
            ambient_tags=loads(row["ambient_tags"]),
            status=row["status"], output_asset_id=row["output_asset_id"],
            voice_volume=row["voice_volume"], ambient_volume=row["ambient_volume"],
            error_message=row["error_message"], created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]), output_asset=output_asset,
        )

    def get_remix_session(self, job_id: str) -> RemixSession | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM remix_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        output_asset = self.get_asset(row["output_asset_id"]) if row["output_asset_id"] else None
        mp = MixParams(**loads(row["mix_params"])) if row["mix_params"] else None
        return RemixSession(
            id=row["id"], user_id=row["user_id"], voice_asset_id=row["voice_asset_id"],
            ambient_asset_id=row["ambient_asset_id"], sound_type=row["sound_type"],
            intent=row["intent"], mix_params=mp, foreground_source=row["foreground_source"],
            generation_job_id=row["generation_job_id"], status=row["status"],
            output_asset_id=row["output_asset_id"], error_message=row["error_message"],
            created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]),
            output_asset=output_asset,
        )

    def count_remix_last_hour(self, user_id: str) -> int:
        since = (utcnow() - timedelta(hours=1)).isoformat()
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM remix_jobs WHERE user_id = ? AND created_at >= ?",
                (user_id, since),
            ).fetchone()
        return int(row["cnt"] or 0)

    def get_active_playback(self, user_id: str) -> PlaybackRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM playback_history WHERE user_id = ? AND completed_at IS NULL ORDER BY started_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return PlaybackRecord(
            id=row["id"], user_id=row["user_id"], asset_id=row["asset_id"], title=row["title"],
            request_text=row["request_text"], source=row["source"], script_summary=row["script_summary"],
            parent_asset_id=row["parent_asset_id"], ambient_asset_id=row["ambient_asset_id"],
            started_at=_dt(row["started_at"]), completed_at=None,
            progress=row["progress"], rating=row["rating"], feedback_type=row["feedback_type"],
            morning_feedback=row["morning_feedback"],
        )
