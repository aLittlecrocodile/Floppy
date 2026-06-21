from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AudioType(StrEnum):
    WHITE_NOISE = "white_noise"
    MUSIC = "music"
    ASMR = "asmr"
    STORY = "story"
    MEDITATION = "meditation"
    PODCAST_DIGEST = "podcast_digest"


class ProfileLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class UserProfileIn(BaseModel):
    audio_type_preferences: list[AudioType] = Field(default_factory=list)
    voice_preferences: list[str] = Field(default_factory=list)
    background_preferences: list[str] = Field(default_factory=list)
    duration_preference_min: int = Field(default=15, ge=5, le=60)
    stress_level: ProfileLevel = ProfileLevel.MEDIUM
    anxiety_level: ProfileLevel = ProfileLevel.MEDIUM
    avg_sleep_latency_min: int = Field(default=25, ge=0, le=180)
    mood_tags: list[str] = Field(default_factory=list)


class UserProfile(UserProfileIn):
    user_id: str
    segment: str
    algo_segment: str | None = None
    tonight_mood: str | None = None
    tonight_stress: ProfileLevel | None = None
    profile_version: int = 1
    updated_at: datetime


class ProfileCheckinIn(BaseModel):
    tonight_mood: str | None = Field(default=None, max_length=80)
    tonight_stress: ProfileLevel | None = None
    sleep_latency_hint_min: int | None = Field(default=None, ge=0, le=180)


class GenerationBudget(BaseModel):
    daily_remaining_chars: int
    daily_generate_count_remaining: int


class ProfileContext(UserProfile):
    generation_budget: GenerationBudget


class NormalizeRequestIn(BaseModel):
    request_text: str = Field(min_length=2, max_length=1000)
    user_id: str | None = None
    duration_preference_min: int | None = Field(default=None, ge=5, le=60)


class NormalizedRequestOut(BaseModel):
    normalized_request: "NormalizedAudioRequest"
    cache_key: str


class AssetSearchFilters(BaseModel):
    type: AudioType | None = None
    mood_tags: list[str] = Field(default_factory=list)
    preferred_tags: list[str] = Field(default_factory=list)
    negative_tags: list[str] = Field(default_factory=list)
    min_duration_sec: int | None = Field(default=None, ge=1)
    max_duration_sec: int | None = Field(default=None, ge=1)


class AssetSearchRequest(BaseModel):
    user_id: str
    query: str | None = Field(default=None, min_length=2, max_length=1000)
    cache_key: str | None = None
    filters: AssetSearchFilters = Field(default_factory=AssetSearchFilters)
    limit: int = Field(default=5, ge=1, le=20)


class AssetSearchResult(BaseModel):
    asset: "AudioAsset"
    score: float
    match_type: str
    reasons: list[str]


class AssetSearchResponse(BaseModel):
    results: list[AssetSearchResult]
    hit: bool
    best_score: float | None
    threshold: float


class AudioAssetIn(BaseModel):
    type: AudioType
    title: str
    object_key: str
    duration_sec: int
    language: str = "zh-CN"
    voice_id: str
    prompt_hash: str
    content_hash: str
    mood_tags: list[str]
    tags: list[str] = Field(default_factory=list)
    sleep_stage: str = "pre_sleep"
    user_segment_tags: list[str]
    safety_status: str = "approved"
    quality_score: float = Field(ge=0, le=1)
    embedding: list[float]
    created_by: str


class AudioAsset(AudioAssetIn):
    id: str
    created_at: datetime
    playback_url: str | None = None


class AudioScriptIn(BaseModel):
    user_id: str
    title: str
    content_type: AudioType
    language: str = "zh-CN"
    script_text: str
    script_hash: str
    pause_density: str
    estimated_duration_sec: int
    safety_status: str = "approved"
    safety_notes: list[str] = Field(default_factory=list)


class AudioScript(AudioScriptIn):
    id: str
    created_at: datetime


class Recommendation(BaseModel):
    asset: AudioAsset
    score: float
    reasons: list[str]


class GenerationRequest(BaseModel):
    request_text: str = Field(min_length=2, max_length=1000)
    duration_preference_min: int | None = Field(default=None, ge=5, le=60)
    force_generate: bool = False


class NormalizedAudioRequest(BaseModel):
    intent: AudioType
    language: str = "zh-CN"
    duration_bucket: str
    duration_sec: int
    voice_style: str
    background: str
    mood: list[str]
    content_topic: list[str]


class GenerationResponse(BaseModel):
    job_id: str
    status: str
    cache_hit: bool
    match_type: str
    asset: AudioAsset | None
    normalized_request: NormalizedAudioRequest


class GenerationJob(BaseModel):
    id: str
    user_id: str
    request_text: str
    normalized_intent: str
    cache_key: str
    status: str
    provider: str
    asset_id: str | None = None
    script_id: str | None = None
    script_hash: str | None = None
    script_chars: int | None = None
    provider_model: str | None = None
    provider_task_id: str | None = None
    provider_file_id: str | None = None
    provider_status: str | None = None
    provider_payload: dict[str, Any] | None = None
    usage_characters: int | None = None
    estimated_cost_usd: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: int | None = None
    created_at: datetime
    updated_at: datetime
    asset: AudioAsset | None = None
    script: AudioScript | None = None


class GenerationJobCreateResponse(BaseModel):
    job_id: str
    status: str
    cache_hit: bool
    match_type: str
    asset: AudioAsset | None
    normalized_request: NormalizedAudioRequest


class EventIn(BaseModel):
    event_type: str = Field(min_length=2, max_length=80)
    asset_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentDecideRequest(BaseModel):
    user_id: str
    request_text: str = Field(min_length=2, max_length=1000)
    generation_allowed: bool = True


class PlannerMeta(BaseModel):
    planner_source: str = "rule"
    planner_confidence: float = 1.0
    planner_latency_ms: int = 0
    fallback_reason: str | None = None


class AgentDecideResponse(BaseModel):
    action: str  # play_asset | generate_job | no_match
    normalized_request: NormalizedAudioRequest
    profile_context: ProfileContext
    search: AssetSearchResponse
    asset: AudioAsset | None = None
    job_id: str | None = None
    reasons: list[str]
    planner_meta: PlannerMeta | None = None
