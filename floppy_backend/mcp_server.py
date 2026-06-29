from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("floppy")


def _backend_base_url() -> str:
    return os.environ.get("FLOPPY_MCP_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def _headers() -> dict[str, str]:
    token = os.environ.get("FLOPPY_MCP_BACKEND_BEARER_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _request(method: str, path: str, **kwargs) -> dict[str, Any] | list[Any]:
    with httpx.Client(base_url=_backend_base_url(), headers=_headers(), timeout=30.0) as client:
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()


@mcp.tool()
def get_user_profile_context(user_id: str) -> dict[str, Any] | list[Any]:
    """Fetch the Floppy profile context and generation budget for a user."""
    return _request("GET", f"/users/{user_id}/profile/context")


@mcp.tool()
def get_user_profile(user_id: str) -> dict[str, Any] | list[Any]:
    """Fetch the persisted Floppy user profile without budget fields."""
    return _request("GET", f"/users/{user_id}/profile")


@mcp.tool()
def update_profile_checkin(
    user_id: str,
    tonight_mood: str | None = None,
    tonight_stress: str | None = None,
    sleep_latency_hint_min: int | None = None,
) -> dict[str, Any] | list[Any]:
    """Update tonight's lightweight profile signals from the dialog."""
    return _request(
        "POST",
        f"/users/{user_id}/profile/checkin",
        json={
            "tonight_mood": tonight_mood,
            "tonight_stress": tonight_stress,
            "sleep_latency_hint_min": sleep_latency_hint_min,
        },
    )


@mcp.tool()
def get_user_questionnaire(user_id: str) -> dict[str, Any] | list[Any]:
    """Fetch the onboarding questionnaire for personalization context."""
    return _request("GET", f"/users/{user_id}/questionnaire")


@mcp.tool()
def save_user_questionnaire(user_id: str, questionnaire: dict[str, Any]) -> dict[str, Any] | list[Any]:
    """Save or update the onboarding questionnaire."""
    return _request("PUT", f"/users/{user_id}/questionnaire", json=questionnaire)


@mcp.tool()
def list_audio_asset_facets(limit: int = 10) -> dict[str, Any] | list[Any]:
    """List catalog facets so Hermes can see available types, tags, voices, and sample assets."""
    return _request("GET", "/assets/facets", params={"limit": max(0, min(limit, 50))})


@mcp.tool()
def search_audio_assets(
    user_id: str,
    query: str | None = None,
    cache_key: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 5,
) -> dict[str, Any] | list[Any]:
    """Search approved assets with structured filters.

    Hermes should translate user intent into filters before calling this tool:
    type, required_tags, preferred_tags, negative_tags, mood_tags, and optional
    duration bounds. The backend executes these filters deterministically; it
    does not infer intent from natural-language query text.
    """
    return _request(
        "POST",
        "/assets/search",
        json={
            "user_id": user_id,
            "query": query,
            "cache_key": cache_key,
            "filters": filters or {},
            "limit": max(1, min(limit, 20)),
        },
    )


@mcp.tool()
def search_audio_asset(user_id: str, request_text: str, limit: int = 3) -> dict[str, Any] | list[Any]:
    """Compatibility alias. Prefer search_audio_assets with structured filters."""
    return search_audio_assets(user_id=user_id, query=request_text, limit=limit)


@mcp.tool()
def get_audio_asset(asset_id: str) -> dict[str, Any] | list[Any]:
    """Fetch one approved audio asset by id, including its playback URL."""
    return _request("GET", f"/assets/{asset_id}")


@mcp.tool()
def generate_sleep_audio(
    user_id: str,
    request_text: str,
    directive: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    """Create a Floppy sleep-audio generation job."""
    return _request(
        "POST",
        f"/users/{user_id}/generation-jobs",
        json={
            "request_text": request_text,
            "force_generate": True,
            "directive": directive,
        },
    )


@mcp.tool()
def get_generation_job(job_id: str) -> dict[str, Any] | list[Any]:
    """Fetch a Floppy generation job and its output asset when available."""
    return _request("GET", f"/generation-jobs/{job_id}")


@mcp.tool()
def get_remix_job(job_id: str) -> dict[str, Any] | list[Any]:
    """Fetch a Floppy remix job and its output asset when available."""
    return _request("GET", f"/remix-jobs/{job_id}")


@mcp.tool()
def start_playback(
    user_id: str,
    asset_id: str,
    source: str = "recommend",
    request_text: str | None = None,
    parent_asset_id: str | None = None,
    ambient_asset_id: str | None = None,
) -> dict[str, Any] | list[Any]:
    """Record that a user started playing an asset."""
    return _request(
        "POST",
        f"/users/{user_id}/playback",
        json={
            "asset_id": asset_id,
            "source": source,
            "request_text": request_text,
            "parent_asset_id": parent_asset_id,
            "ambient_asset_id": ambient_asset_id,
        },
    )


@mcp.tool()
def submit_playback_feedback(
    user_id: str,
    record_id: str,
    feedback_type: str,
    rating: int | None = None,
    progress: float | None = None,
    morning_feedback: str | None = None,
) -> dict[str, Any] | list[Any]:
    """Record feedback such as favorite, dislike, skip, complete, rating, or morning feedback."""
    return _request(
        "POST",
        f"/users/{user_id}/playback/{record_id}/feedback",
        json={
            "feedback_type": feedback_type,
            "rating": rating,
            "progress": progress,
            "morning_feedback": morning_feedback,
        },
    )


@mcp.tool()
def get_playback_history(user_id: str, limit: int = 20) -> dict[str, Any] | list[Any]:
    """Fetch recent playback records for memory and personalization."""
    return _request("GET", f"/users/{user_id}/playback/history", params={"limit": max(1, min(limit, 50))})


@mcp.tool()
def get_active_playback(user_id: str) -> dict[str, Any] | list[Any]:
    """Fetch the latest unfinished playback record, if any."""
    return _request("GET", f"/users/{user_id}/playback/active")


@mcp.tool()
def remix_current(
    user_id: str,
    current_asset_id: str,
    sound_type: str = "rain",
    voice_volume: float = 1.0,
    ambient_volume: float = 0.3,
) -> dict[str, Any] | list[Any]:
    """Add an ambient layer to the current Floppy audio asset."""
    return _request(
        "POST",
        f"/users/{user_id}/remix",
        json={
            "voice_asset_id": current_asset_id,
            "sound_type": sound_type,
            "voice_volume": voice_volume,
            "ambient_volume": ambient_volume,
        },
    )


@mcp.tool()
def list_uploads(user_id: str) -> dict[str, Any] | list[Any]:
    """List a user's uploaded files and generated audio outputs."""
    return _request("GET", f"/users/{user_id}/uploads")


@mcp.tool()
def get_upload(user_id: str, upload_id: str) -> dict[str, Any] | list[Any]:
    """Fetch one upload record and its generated audio output when available."""
    return _request("GET", f"/users/{user_id}/uploads/{upload_id}")


@mcp.tool()
def retry_upload(user_id: str, upload_id: str) -> dict[str, Any] | list[Any]:
    """Reset a failed upload record so the client can retry."""
    return _request("POST", f"/users/{user_id}/uploads/{upload_id}/retry")


@mcp.tool()
def delete_upload(user_id: str, upload_id: str) -> dict[str, Any] | list[Any]:
    """Delete an upload record."""
    return _request("DELETE", f"/users/{user_id}/uploads/{upload_id}")


@mcp.tool()
def generate_audio_from_upload(
    user_id: str,
    upload_id: str,
    request_text: str | None = None,
    audio_intent: str = "podcast_digest",
    tone: str = "低信息密度、温柔、适合睡前",
    duration_sec: int | None = None,
    voice_style: str | None = None,
    force_generate: bool = True,
) -> dict[str, Any] | list[Any]:
    """Create a sleep-audio generation job from an uploaded txt file."""
    return _request(
        "POST",
        f"/users/{user_id}/uploads/{upload_id}/generate-audio",
        json={
            "request_text": request_text,
            "audio_intent": audio_intent,
            "tone": tone,
            "duration_sec": duration_sec,
            "voice_style": voice_style,
            "force_generate": force_generate,
        },
    )


@mcp.tool()
def check_sleep_script_safety(script_text: str, estimated_duration_sec: int = 600) -> dict[str, Any] | list[Any]:
    """Run Floppy's safety and low-stimulation quality gate for a sleep script."""
    return _request(
        "POST",
        "/safety/script/check",
        json={
            "script_text": script_text,
            "estimated_duration_sec": estimated_duration_sec,
        },
    )


if __name__ == "__main__":
    mcp.run()
