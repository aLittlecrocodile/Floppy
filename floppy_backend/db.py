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
    sleep_stage TEXT NOT NULL,
    user_segment_tags TEXT NOT NULL,
    safety_status TEXT NOT NULL,
    quality_score REAL NOT NULL,
    embedding TEXT NOT NULL,
    created_by TEXT NOT NULL,
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
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(generation_jobs)").fetchall()}
    additions = {
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
    }
    for column, definition in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE generation_jobs ADD COLUMN {column} {definition}")
