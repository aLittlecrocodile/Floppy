from __future__ import annotations

from floppy_backend.config import Settings
from floppy_backend.models import AudioType, NormalizedAudioRequest
from floppy_backend.workflows.cache import build_sleep_audio_cache_key
from floppy_backend.workflows.contracts import (
    AcceptedIntent,
    PROTOCOL_VERSION,
    SleepAudioIntent,
    SleepAudioWorkflowRequest,
    WorkflowAcceptedResponse,
    WorkflowEstimate,
    WorkflowStatus,
)


def test_sleep_audio_intent_from_normalized_request():
    normalized = NormalizedAudioRequest(
        intent=AudioType.MEDITATION,
        duration_bucket="10-20min",
        duration_sec=1200,
        voice_style="gentle_female",
        background="rain_soft",
        mood=["calm", "anxiety_relief"],
        content_topic=["呼吸", "雨夜"],
    )

    intent = SleepAudioIntent.from_normalized(normalized, title_hint="雨夜呼吸放松")

    assert intent.content_type == AudioType.MEDITATION
    assert intent.target_duration_sec == 1200
    assert intent.title_hint == "雨夜呼吸放松"
    assert intent.topic == ["呼吸", "雨夜"]
    assert intent.background == "rain_soft"


def test_sleep_audio_workflow_request_defaults_match_protocol():
    request = SleepAudioWorkflowRequest(
        request_id="req_1",
        user_id="u_demo",
        intent=SleepAudioIntent(
            content_type=AudioType.MEDITATION,
            target_duration_sec=1200,
            background="rain_soft",
            voice_style="gentle_female",
        ),
    )

    body = request.model_dump(mode="json")

    assert body["protocol_version"] == PROTOCOL_VERSION
    assert body["workflow_type"] == "sleep_audio_generation"
    assert body["constraints"]["low_stimulation"] is True
    assert body["constraints"]["allow_background_music"] is True
    assert body["mix_preferences"]["preset"] == "sleep"
    assert body["generation_policy"]["cache_policy"] == "prefer_cache"
    assert body["generation_policy"]["provider"] == "minimax"


def test_workflow_accepted_response_shape():
    response = WorkflowAcceptedResponse(
        workflow_run_id="wf_1",
        request_id="req_1",
        estimated=WorkflowEstimate(target_duration_sec=1200, estimated_cost_usd=0.12, estimated_wait_sec=180),
        accepted_intent=AcceptedIntent(
            content_type=AudioType.MEDITATION,
            target_duration_sec=1200,
            voice_style="gentle_female",
            background="rain_soft",
            mix_preset="meditation",
        ),
    )

    body = response.model_dump(mode="json")

    assert body["status"] == WorkflowStatus.QUEUED.value
    assert body["estimated"]["target_duration_sec"] == 1200
    assert body["accepted_intent"]["content_type"] == "meditation"


def test_sleep_audio_cache_key_includes_policy_and_provider_versions():
    normalized = NormalizedAudioRequest(
        intent=AudioType.MEDITATION,
        duration_bucket="10-20min",
        duration_sec=1200,
        voice_style="gentle_female",
        background="rain_soft",
        mood=["calm"],
        content_topic=["呼吸"],
    )
    settings = Settings(minimax_model="speech-a", minimax_music_model="music-a", minimax_enable_music_mix=True)

    base = build_sleep_audio_cache_key(normalized, provider_name="minimax_t2a", settings=settings)
    model_changed = build_sleep_audio_cache_key(
        normalized,
        provider_name="minimax_t2a",
        settings=Settings(minimax_model="speech-b", minimax_music_model="music-a", minimax_enable_music_mix=True),
    )
    duration_changed = build_sleep_audio_cache_key(
        normalized.model_copy(update={"duration_sec": 900}),
        provider_name="minimax_t2a",
        settings=settings,
    )
    local_base = build_sleep_audio_cache_key(normalized, provider_name="local", settings=settings)
    local_minimax_model_changed = build_sleep_audio_cache_key(
        normalized,
        provider_name="local",
        settings=Settings(minimax_model="speech-b", minimax_music_model="music-b", minimax_enable_music_mix=True),
    )

    assert base != model_changed
    assert base != duration_changed
    assert local_base == local_minimax_model_changed
