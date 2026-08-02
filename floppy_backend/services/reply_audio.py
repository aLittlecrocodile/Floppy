"""Cross-domain helpers shared by the chat, showcase, voice and mobile routes.

These live outside main.py so router modules — and `lifespan`'s reply-TTS
prewarm — can use them without importing floppy_backend.main (which imports
the routers, so that direction would be a cycle).
"""

from __future__ import annotations

import hashlib

from fastapi import BackgroundTasks, HTTPException

from floppy_backend.app_state import _reply_tts_executor, state
from floppy_backend.models import (
    AgentDecideRequest,
    AgentDecideResponse,
    AudioType,
    GenerationRequest,
    ProfileLevel,
    UserProfileIn,
)
from floppy_backend.services.generation import BudgetExceededError

NOTIFY_LINE_TEXT = "刚刚你想听的音频生成完成了，现在来听听吧"


def ensure_demo_profile(user_id: str) -> None:
    """Make sure a user has a profile (catalog is seeded at startup).

    Voice dialog and /demo/chat both need a profile for the agent runtime to run;
    new ad-hoc users (e.g. a browser session) get a sensible sleep default.
    """
    if state.repository.get_profile(user_id) is None:
        state.profile_service.upsert_profile(
            user_id,
            UserProfileIn(
                audio_type_preferences=[AudioType.MEDITATION, AudioType.WHITE_NOISE, AudioType.STORY],
                voice_preferences=["warm_female"],
                background_preferences=["rain_soft"],
                duration_preference_min=15,
                stress_level=ProfileLevel.HIGH,
                anxiety_level=ProfileLevel.HIGH,
                avg_sleep_latency_min=40,
                mood_tags=["anxiety_relief"],
            ),
        )


def run_agent_decide(req: AgentDecideRequest, background_tasks: BackgroundTasks) -> AgentDecideResponse:
    try:
        response = state.agent_runtime.run(req)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        if "profile not found" in str(exc):
            raise HTTPException(status_code=404, detail="profile not found") from exc
        raise

    if response.action == "generate_job" and response.job_id:
        # A job already in flight is being executed by whoever enqueued it —
        # scheduling a second run would only tie up a worker waiting on it.
        in_flight = any(
            call.name == "generate_sleep_audio" and (call.output or {}).get("match_type") == "in_flight"
            for call in response.tool_calls
        )
        if not in_flight:
            background_tasks.add_task(
                state.generation_service.run_job,
                response.job_id,
                req.user_id,
                GenerationRequest(request_text=req.request_text, force_generate=True),
            )
    return response


def reply_audio_url(reply: str) -> str | None:
    """Synthesize the agent's spoken reply (MiniMax TTS), cached by reply text.

    Best-effort: any failure falls back to text-only. Short replies (≤40 chars)
    cost ~$0.002 and ~1-2s; repeated phrasings hit the file cache."""
    text = (reply or "").strip()
    if not text:
        return None
    provider = state.generation_service.provider
    if not hasattr(provider, "generate_text_to_file"):
        return None  # local tone provider — no real voice
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    object_key = f"replies/{digest}.mp3"
    try:
        path = state.storage.path_for(object_key)
        if not path.exists():
            # Hard 5s wall-clock budget: a hung MiniMax call must never stall a
            # chat turn. The abandoned worker (capped by its own 8s socket
            # timeout) may still finish and warm the cache for next time.
            future = _reply_tts_executor.submit(
                provider.generate_text_to_file,
                text, path, object_key,
                voice_style="warm_female", title="floppy_reply", timeout=8,
            )
            future.result(timeout=5)
        return state.storage.public_url(object_key)
    except Exception:  # noqa: BLE001 — voice reply is an enhancement, never a blocker
        return None


def attach_reply_audio(response: AgentDecideResponse) -> None:
    """Synthesize the spoken reply — but only when no real audio track is
    about to play. A response with `asset` already set (play_asset, a
    synchronous remix) has its own audio starting immediately; speaking the
    "here's your track" reply over it means two tracks play at once."""
    if response.reply and response.asset is None:
        response.reply_audio_url = reply_audio_url(response.reply)


def notify_audio_url() -> str | None:
    """兜底播报语音。文案固定 → 首次合成后按文本哈希永久缓存，之后零延迟。"""
    return reply_audio_url(NOTIFY_LINE_TEXT)
