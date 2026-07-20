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
    tier: str = "community"  # "curated" (real/prewarm, Home-eligible) | "community"


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


class GenerationDirective(BaseModel):
    """Structured generation instruction produced by the agent (LLM) before
    it commands the workflow. Carries the *content intent* (outline + key
    elements) that template-based normalization throws away, so the workflow
    can write a personalized script instead of selecting a generic template.

    All fields optional/defaulted: an empty directive (or a None one) lets the
    workflow fall back to the existing templates, keeping the old path intact.
    """
    intent: AudioType | None = None
    tone: str | None = None                              # 基调，如 "温柔平静"
    duration_sec: int | None = Field(default=None, ge=30, le=3600)
    voice_style: str | None = None
    content_brief: str = ""                              # 一句话主题
    outline: list[str] = Field(default_factory=list)     # 分段要点
    key_elements: list[str] = Field(default_factory=list)  # 必含意象，如「祖母/老花园」
    confidence: float = 1.0
    source: str = "agent"                                # "agent" | "agent_fallback"

    @property
    def has_outline(self) -> bool:
        return bool(self.outline) or bool(self.content_brief)

    def cache_signature(self) -> dict:
        """Stable subset for cache_key — excludes free-form outline text so
        minor LLM wording drift doesn't tank the cache hit rate. Same need
        (intent/duration/voice/brief/elements) → same key → cache hit."""
        return {
            "intent": self.intent.value if self.intent else None,
            "tone": (self.tone or "").strip(),
            "duration_sec": self.duration_sec,
            "voice_style": self.voice_style,
            "content_brief": self.content_brief.strip(),
            "key_elements": sorted(e.strip() for e in self.key_elements if e.strip()),
        }


class GenerationRequest(BaseModel):
    request_text: str = Field(min_length=2, max_length=1000)
    duration_preference_min: int | None = Field(default=None, ge=5, le=60)
    force_generate: bool = False
    directive: GenerationDirective | None = None


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
    directive: GenerationDirective | None = None
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
    current_asset_id: str | None = None  # currently playing/just played asset (for remix context)


class PlannerMeta(BaseModel):
    planner_source: str = "rule"
    planner_confidence: float = 1.0
    planner_latency_ms: int = 0
    fallback_reason: str | None = None


class AgentToolCall(BaseModel):
    name: str
    status: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    latency_ms: int = 0
    reason: str | None = None


class AgentDecideResponse(BaseModel):
    action: str  # chat | play_asset | generate_job | remix_current | no_match
    normalized_request: NormalizedAudioRequest
    profile_context: ProfileContext
    search: AssetSearchResponse
    asset: AudioAsset | None = None
    job_id: str | None = None
    remix_job_id: str | None = None
    reply: str | None = None  # agent's user-facing sentence (Hermes-written)
    reasons: list[str]
    planner_meta: PlannerMeta | None = None
    selected_skill: str | None = None
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    # Structured payload for frontend skill cards (weekly draft, OKR progress,
    # neisou answer, ritual receipts ...). None for plain decisions.
    skill_card: dict[str, Any] | None = None
    # Spoken reply (MiniMax TTS, cached by text) — frontend auto-plays when on.
    reply_audio_url: str | None = None
    # sleep_timer: executed by the frontend player (countdown + volume fade).
    timer_sec: int | None = None
    fade_out: bool | None = None


# --- P0: Questionnaire ---


class UserQuestionnaireIn(BaseModel):
    gender: str | None = None
    age_range: str | None = None  # e.g. "18-24", "25-34"
    occupation: str | None = None
    bedtime: str | None = None  # e.g. "23:00"
    main_sleep_problem: str | None = None  # e.g. "difficulty_falling_asleep", "light_sleep"
    bedtime_habits: list[str] = Field(default_factory=list)  # e.g. ["phone", "reading"]
    favorite_content_types: list[str] = Field(default_factory=list)
    preferred_companion_style: str | None = None  # e.g. "warm", "professional", "playful"
    voice_preferences: list[str] = Field(default_factory=list)


class UserQuestionnaire(UserQuestionnaireIn):
    user_id: str
    completed_at: datetime | None = None
    updated_at: datetime


# --- P0: Playback History & Feedback ---


class PlaybackSource(StrEnum):
    RECOMMEND = "recommend"
    GENERATED = "generated"
    REMIX = "remix"
    IMPORT = "import"


class PlaybackFeedbackType(StrEnum):
    TRIAL_RATING = "trial_rating"
    FAVORITE = "favorite"
    DISLIKE = "dislike"
    SKIP = "skip"
    COMPLETE = "complete"
    MORNING_FEEDBACK = "morning_feedback"


class PlaybackStartIn(BaseModel):
    asset_id: str
    source: PlaybackSource = PlaybackSource.RECOMMEND
    request_text: str | None = None
    parent_asset_id: str | None = None  # for remix: the original voice asset
    ambient_asset_id: str | None = None  # for remix: the ambient layer


class PlaybackFeedbackIn(BaseModel):
    feedback_type: PlaybackFeedbackType
    rating: int | None = Field(default=None, ge=1, le=5)
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    morning_feedback: str | None = None


class PlaybackRecord(BaseModel):
    id: str
    user_id: str
    asset_id: str
    title: str
    request_text: str | None = None
    source: str
    script_summary: str | None = None
    parent_asset_id: str | None = None
    ambient_asset_id: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    progress: float = 0.0
    rating: int | None = None
    feedback_type: str | None = None
    morning_feedback: str | None = None


# --- P0: Remix ---


class RemixIntent(StrEnum):
    ADD_BACKGROUND = "add_background"
    CHANGE_BACKGROUND = "change_background"
    ADJUST_VOLUME = "adjust_volume"
    REMOVE_BACKGROUND = "remove_background"
    VOICE_PLUS_AMBIENT = "voice_plus_ambient"


class MixParams(BaseModel):
    background_volume: float = Field(default=0.3, ge=0.0, le=2.0)
    crossfade_in_sec: int = Field(default=2, ge=0, le=10)
    crossfade_out_sec: int = Field(default=3, ge=0, le=10)
    duck_on_speech: bool = True


class RemixRequestIn(BaseModel):
    """Legacy remix request. Deprecated — use POST /remix/sessions instead."""
    voice_asset_id: str
    ambient_asset_id: str | None = None
    sound_type: str | None = None
    ambient_tags: list[str] = Field(default_factory=list)
    voice_volume: float = Field(default=1.0, ge=0.0, le=2.0)
    ambient_volume: float = Field(default=0.3, ge=0.0, le=2.0)


class RemixSessionCreateIn(BaseModel):
    """Create a remix session (§3.4 of algo contract)."""
    foreground_asset_id: str | None = None  # if None, inferred from active playback
    ambient_asset_id: str | None = None
    sound_type: str | None = None  # rain/ocean/fire/forest/stream/fan/piano/wind
    intent: RemixIntent = RemixIntent.ADD_BACKGROUND
    mix_params: MixParams = Field(default_factory=MixParams)


class RemixSessionPatchIn(BaseModel):
    """Adjust an ongoing remix session."""
    intent: RemixIntent | None = None  # change_background/adjust_volume/remove_background
    sound_type: str | None = None
    ambient_asset_id: str | None = None
    mix_params: MixParams | None = None


class RemixSession(BaseModel):
    id: str
    user_id: str
    voice_asset_id: str
    ambient_asset_id: str | None = None
    sound_type: str | None = None
    intent: str | None = None
    mix_params: MixParams | None = None
    foreground_source: str | None = None
    generation_job_id: str | None = None
    status: str
    output_asset_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    output_asset: AudioAsset | None = None


class AssetRemixable(BaseModel):
    asset_id: str
    remixable: bool
    reason: str | None = None
    format: str | None = None  # wav/mp3


class RemixJob(BaseModel):
    id: str
    user_id: str
    voice_asset_id: str
    ambient_asset_id: str | None = None
    sound_type: str | None = None
    ambient_tags: list[str] = Field(default_factory=list)
    status: str
    output_asset_id: str | None = None
    voice_volume: float = 1.0
    ambient_volume: float = 0.3
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    output_asset: AudioAsset | None = None
