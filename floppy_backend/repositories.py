from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from threading import RLock

from floppy_backend.models import AudioAsset, AudioAssetIn, AudioScript, AudioScriptIn, AudioType, EventIn, GenerationJob, ProfileCheckinIn, UserProfile, UserProfileIn
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
        asset_id = stable_id(
            "aud",
            {
                "prompt_hash": asset.prompt_hash,
                "object_key": asset.object_key,
                "content_hash": asset.content_hash,
            },
        )
        created_at = utcnow()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO audio_assets (
                    id, type, title, object_key, duration_sec, language, voice_id, prompt_hash,
                    content_hash, mood_tags, tags, sleep_stage, user_segment_tags, safety_status,
                    quality_score, embedding, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    created_by=excluded.created_by
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

    def list_assets(self, limit: int = 500) -> list[AudioAsset]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM audio_assets WHERE safety_status = 'approved' ORDER BY quality_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def list_available_tags(self) -> set[str]:
        with self._lock:
            rows = self.conn.execute("SELECT tags FROM audio_assets WHERE safety_status = 'approved'").fetchall()
        tags: set[str] = set()
        for row in rows:
            if row["tags"]:
                tags.update(loads(row["tags"]))
        return tags

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
                    latency_ms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (job_id, user_id, request_text, normalized_intent, cache_key, status, provider, now, now),
            )
            self.conn.commit()
            created = self.conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._job_from_row(created), True

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
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            asset=asset,
            script=script,
        )
