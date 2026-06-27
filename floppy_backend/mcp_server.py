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
        return response.json()


@mcp.tool()
def search_audio_asset(user_id: str, request_text: str, limit: int = 3) -> dict[str, Any] | list[Any]:
    """Search Floppy's approved sleep-audio asset catalog."""
    return _request(
        "POST",
        "/assets/search",
        json={
            "user_id": user_id,
            "query": request_text,
            "limit": max(1, min(limit, 10)),
        },
    )


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


if __name__ == "__main__":
    mcp.run()
