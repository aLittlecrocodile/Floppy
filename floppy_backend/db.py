from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    audio_type_preferences TEXT NOT NULL,
    voice_preferences TEXT NOT NULL,
    background_preferences TEXT NOT NULL,
    duration_preference_min INTEGER NOT NULL,
    stress_level TEXT NOT NULL,
    anxiety_level TEXT NOT NULL,
    avg_sleep_latency_min INTEGER NOT NULL,
    mood_tags TEXT NOT NULL,
    segment TEXT NOT NULL,
    algo_segment TEXT,
    tonight_mood TEXT,
    tonight_stress TEXT,
    profile_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_assets (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    object_key TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    language TEXT NOT NULL,
    voice_id TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mood_tags TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    sleep_stage TEXT NOT NULL,
    user_segment_tags TEXT NOT NULL,
    safety_status TEXT NOT NULL,
    quality_score REAL NOT NULL,
    embedding TEXT NOT NULL,
    created_by TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'community',
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_assets_prompt_hash
ON audio_assets(prompt_hash);

CREATE INDEX IF NOT EXISTS idx_audio_assets_type
ON audio_assets(type);

CREATE TABLE IF NOT EXISTS audio_scripts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content_type TEXT NOT NULL,
    language TEXT NOT NULL,
    script_text TEXT NOT NULL,
    script_hash TEXT NOT NULL,
    pause_density TEXT NOT NULL,
    estimated_duration_sec INTEGER NOT NULL,
    safety_status TEXT NOT NULL,
    safety_notes TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_scripts_hash
ON audio_scripts(script_hash);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_text TEXT NOT NULL,
    normalized_intent TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    asset_id TEXT REFERENCES audio_assets(id),
    script_id TEXT REFERENCES audio_scripts(id),
    script_hash TEXT,
    script_chars INTEGER,
    provider_model TEXT,
    provider_task_id TEXT,
    provider_file_id TEXT,
    provider_status TEXT,
    provider_payload TEXT,
    usage_characters INTEGER,
    estimated_cost_usd REAL,
    error_code TEXT,
    error_message TEXT,
    latency_ms INTEGER,
    directive_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generation_jobs_user_created
ON generation_jobs(user_id, created_at);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    asset_id TEXT REFERENCES audio_assets(id),
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_user_created
ON events(user_id, created_at);

CREATE TABLE IF NOT EXISTS user_questionnaires (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    gender TEXT,
    age_range TEXT,
    occupation TEXT,
    bedtime TEXT,
    main_sleep_problem TEXT,
    bedtime_habits TEXT NOT NULL DEFAULT '[]',
    favorite_content_types TEXT NOT NULL DEFAULT '[]',
    preferred_companion_style TEXT,
    voice_preferences TEXT NOT NULL DEFAULT '[]',
    completed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playback_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES audio_assets(id),
    title TEXT NOT NULL,
    request_text TEXT,
    source TEXT NOT NULL DEFAULT 'recommend',
    script_summary TEXT,
    parent_asset_id TEXT,
    ambient_asset_id TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    progress REAL NOT NULL DEFAULT 0.0,
    rating INTEGER,
    feedback_type TEXT,
    morning_feedback TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_playback_history_user
ON playback_history(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS remix_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    voice_asset_id TEXT NOT NULL REFERENCES audio_assets(id),
    ambient_asset_id TEXT REFERENCES audio_assets(id),
    sound_type TEXT,
    ambient_tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    output_asset_id TEXT REFERENCES audio_assets(id),
    voice_volume REAL NOT NULL DEFAULT 1.0,
    ambient_volume REAL NOT NULL DEFAULT 0.3,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_remix_jobs_user
ON remix_jobs(user_id, created_at DESC);
"""


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    job_cols = {row["name"] for row in conn.execute("PRAGMA table_info(generation_jobs)").fetchall()}
    job_additions = {
        "script_id": "TEXT REFERENCES audio_scripts(id)",
        "script_hash": "TEXT",
        "script_chars": "INTEGER",
        "provider_model": "TEXT",
        "provider_task_id": "TEXT",
        "provider_file_id": "TEXT",
        "provider_status": "TEXT",
        "provider_payload": "TEXT",
        "usage_characters": "INTEGER",
        "estimated_cost_usd": "REAL",
        "error_message": "TEXT",
        "target_duration_sec": "INTEGER",
        "actual_duration_sec": "INTEGER",
        "directive_json": "TEXT",
    }
    for column, definition in job_additions.items():
        if column not in job_cols:
            conn.execute(f"ALTER TABLE generation_jobs ADD COLUMN {column} {definition}")

    profile_cols = {row["name"] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
    profile_additions = {
        "algo_segment": "TEXT",
        "tonight_mood": "TEXT",
        "tonight_stress": "TEXT",
        "profile_version": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, definition in profile_additions.items():
        if column not in profile_cols:
            conn.execute(f"ALTER TABLE user_profiles ADD COLUMN {column} {definition}")

    asset_cols = {row["name"] for row in conn.execute("PRAGMA table_info(audio_assets)").fetchall()}
    if "tags" not in asset_cols:
        conn.execute("ALTER TABLE audio_assets ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
    if "tier" not in asset_cols:
        conn.execute("ALTER TABLE audio_assets ADD COLUMN tier TEXT NOT NULL DEFAULT 'community'")
        # One-time backfill: real recordings and official prewarm generations
        # are the curated pool; everything else is community.
        conn.execute(
            """UPDATE audio_assets SET tier = 'curated'
               WHERE created_by = 'real_asset'
                  OR object_key LIKE 'ondemand/prewarm_user/%'"""
        )
    # Index lives here (not in SCHEMA): on a pre-tier database the SCHEMA
    # script would try to index a column that doesn't exist yet.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audio_assets_tier ON audio_assets(tier)")

    remix_cols = {row["name"] for row in conn.execute("PRAGMA table_info(remix_jobs)").fetchall()}
    remix_additions = {
        "intent": "TEXT",
        "mix_params": "TEXT",
        "foreground_source": "TEXT",
        "generation_job_id": "TEXT",
    }
    for column, definition in remix_additions.items():
        if column not in remix_cols:
            conn.execute(f"ALTER TABLE remix_jobs ADD COLUMN {column} {definition}")

    pb_cols = {row["name"] for row in conn.execute("PRAGMA table_info(playback_history)").fetchall()}
    if "is_active" not in pb_cols:
        conn.execute("ALTER TABLE playback_history ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0")
