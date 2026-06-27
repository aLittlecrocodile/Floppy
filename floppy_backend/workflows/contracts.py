from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from floppy_backend.models import AudioType, NormalizedAudioRequest


PROTOCOL_VERSION = "sleep_audio_workflow.v0"


class WorkflowType(StrEnum):
    SLEEP_AUDIO_GENERATION = "sleep_audio_generation"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    SCRIPT_READY = "script_ready"
    SPEECH_GENERATING = "speech_generating"
    SPEECH_READY = "speech_ready"
    MUSIC_GENERATING = "music_generating"
    MUSIC_READY = "music_ready"
    MIXING = "mixing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


class WorkflowStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class CachePolicy(StrEnum):
    PREFER_CACHE = "prefer_cache"
    FORCE_REGENERATE = "force_regenerate"
    BYPASS_CACHE = "bypass_cache"


class WorkflowQualityLevel(StrEnum):
    DRAFT = "draft"
    STANDARD = "standard"
    HIGH = "high"


class WorkflowProvider(StrEnum):
    LOCAL = "local"
    MINIMAX = "minimax"


class SleepAudioIntent(BaseModel):
    content_type: AudioType
    language: str = "zh-CN"
    target_duration_sec: int = Field(ge=60, le=3600)
    title_hint: str | None = Field(default=None, max_length=120)
    topic: list[str] = Field(default_factory=list)
    mood: list[str] = Field(default_factory=list)
    background: str = "none"
    voice_style: str = "warm_female"

    @classmethod
    def from_normalized(
        cls,
        normalized: NormalizedAudioRequest,
        *,
        title_hint: str | None = None,
    ) -> "SleepAudioIntent":
        return cls(
            content_type=normalized.intent,
            language=normalized.language,
            target_duration_sec=normalized.duration_sec,
            title_hint=title_hint,
            topic=list(normalized.content_topic),
            mood=list(normalized.mood),
            background=normalized.background,
            voice_style=normalized.voice_style,
        )


class WorkflowConstraints(BaseModel):
    low_stimulation: bool = True
    no_medical_claim: bool = True
    no_sudden_sound: bool = True
    max_cost_usd: float | None = Field(default=None, ge=0)
    allow_background_music: bool = True
    allow_nature_ambient: bool = True


class MixPreferences(BaseModel):
    preset: str = "sleep"
    voice_volume: float = Field(default=1.0, ge=0.0, le=2.0)
    background_volume: float = Field(default=0.18, ge=0.0, le=2.0)
    fade_out_sec: float = Field(default=12.0, ge=0.0, le=60.0)


class GenerationPolicy(BaseModel):
    cache_policy: CachePolicy = CachePolicy.PREFER_CACHE
    force_regenerate: bool = False
    quality_level: WorkflowQualityLevel = WorkflowQualityLevel.STANDARD
    provider: WorkflowProvider = WorkflowProvider.MINIMAX


class AgentWorkflowContext(BaseModel):
    reason: str = Field(default="", max_length=500)
    profile_segment: str | None = Field(default=None, max_length=80)
    user_visible_summary: str | None = Field(default=None, max_length=240)


class SleepAudioWorkflowRequest(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    request_id: str = Field(min_length=2, max_length=120)
    user_id: str = Field(min_length=1, max_length=120)
    conversation_id: str | None = Field(default=None, max_length=120)
    workflow_type: WorkflowType = WorkflowType.SLEEP_AUDIO_GENERATION
    intent: SleepAudioIntent
    constraints: WorkflowConstraints = Field(default_factory=WorkflowConstraints)
    mix_preferences: MixPreferences = Field(default_factory=MixPreferences)
    generation_policy: GenerationPolicy = Field(default_factory=GenerationPolicy)
    agent_context: AgentWorkflowContext = Field(default_factory=AgentWorkflowContext)


class WorkflowEstimate(BaseModel):
    target_duration_sec: int = Field(ge=1)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    estimated_wait_sec: int | None = Field(default=None, ge=0)


class AcceptedIntent(BaseModel):
    content_type: AudioType
    target_duration_sec: int = Field(ge=1)
    voice_style: str
    background: str
    mix_preset: str


class WorkflowAcceptedResponse(BaseModel):
    workflow_run_id: str
    request_id: str
    status: WorkflowStatus = WorkflowStatus.QUEUED
    estimated: WorkflowEstimate
    accepted_intent: AcceptedIntent


class WorkflowStepState(BaseModel):
    name: str
    status: WorkflowStepStatus
    detail: str | None = None


class WorkflowArtifact(BaseModel):
    asset_id: str
    playback_url: str
    duration_sec: int = Field(ge=1)
    title: str
    content_type: AudioType


class WorkflowDiagnostics(BaseModel):
    script_hash: str | None = None
    script_chars: int | None = Field(default=None, ge=0)
    voice_id: str | None = None
    voice_object_key: str | None = None
    music_object_key: str | None = None
    mixed_object_key: str | None = None
    provider_model: str | None = None
    provider_task_id: str | None = None
    provider_file_id: str | None = None
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class WorkflowError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class WorkflowStatusResponse(BaseModel):
    workflow_run_id: str
    request_id: str
    status: WorkflowStatus
    current_step: str | None = None
    steps: list[WorkflowStepState] = Field(default_factory=list)
    artifact: WorkflowArtifact | None = None
    diagnostics: WorkflowDiagnostics | None = None
    error: WorkflowError | None = None


class ClarificationQuestion(BaseModel):
    field: str
    message: str


class WorkflowClarificationResponse(BaseModel):
    workflow_run_id: str | None = None
    request_id: str
    status: WorkflowStatus = WorkflowStatus.NEEDS_CLARIFICATION
    questions: list[ClarificationQuestion]
