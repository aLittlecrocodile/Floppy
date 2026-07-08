from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import json
import time

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from floppy_backend.config import Settings, get_settings
from floppy_backend.db import connect, initialize
from floppy_backend.demo_page import DEMO_HTML
from floppy_backend.models import (
    AgentDecideRequest,
    AgentDecideResponse,
    AssetRemixable,
    AssetSearchRequest,
    AssetSearchResponse,
    AudioType,
    EventIn,
    GenerationBudget,
    GenerationJob,
    GenerationJobCreateResponse,
    GenerationRequest,
    GenerationResponse,
    MixParams,
    NormalizeRequestIn,
    NormalizedRequestOut,
    PlaybackFeedbackIn,
    PlaybackRecord,
    PlaybackStartIn,
    ProfileCheckinIn,
    ProfileContext,
    ProfileLevel,
    Recommendation,
    RemixJob,
    RemixRequestIn,
    RemixSession,
    RemixSessionCreateIn,
    RemixSessionPatchIn,
    UserProfile,
    UserProfileIn,
    UserQuestionnaire,
    UserQuestionnaireIn,
)
from floppy_backend.providers.audio import build_audio_provider
from floppy_backend.repositories import Repository
from floppy_backend.seed import seed_assets
from floppy_backend.services.generation import BudgetExceededError, GenerationService
from floppy_backend.services.assets import is_placeholder_created_by
from floppy_backend.services.hermes_agent import HermesAgentRuntime
from floppy_backend.services.library import LibraryService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.profile import ProfileService
from floppy_backend.services.remix import RemixService
from floppy_backend.services.script import SleepScriptService
from floppy_backend.storage import LocalFileStorage


class AppState:
    repository: Repository
    storage: LocalFileStorage
    profile_service: ProfileService
    library: LibraryService
    generation_service: GenerationService
    remix_service: RemixService
    agent_runtime: HermesAgentRuntime


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)
    repository = Repository(conn)
    storage = LocalFileStorage(settings.storage_dir, settings.public_base_url)
    library = LibraryService(repository, storage, settings)
    state.repository = repository
    state.storage = storage
    state.profile_service = ProfileService(repository)
    state.library = library

    # Resolve a shared LLM credential for the directive planner + script writer.
    # They reuse the query planner / dialog creds; falls back to template-only
    # generation when no key is configured.
    _llm_key = settings.query_planner_api_key or settings.dialog_llm_api_key
    _llm_base = settings.dialog_llm_base_url or settings.query_planner_base_url
    _llm_model = settings.dialog_llm_model or settings.query_planner_model
    script_writer = None
    directive_planner = None
    if settings.directive_planner_enabled and _llm_key:
        from floppy_backend.services.directive_planner import DirectivePlanner
        from floppy_backend.services.script_writer import LLMScriptWriter
        script_writer = LLMScriptWriter(
            api_key=_llm_key,
            base_url=_llm_base,
            model=_llm_model,
            timeout_sec=settings.script_writer_timeout_sec,
            max_tokens=settings.script_writer_max_tokens,
        )
        directive_planner = DirectivePlanner(
            api_key=_llm_key,
            base_url=_llm_base,
            model=_llm_model,
            timeout_sec=settings.directive_planner_timeout_sec,
            max_tokens=settings.directive_planner_max_tokens,
            confidence_threshold=settings.directive_planner_confidence_threshold,
        )

    state.generation_service = GenerationService(
        repository=repository,
        storage=storage,
        provider=build_audio_provider(settings),
        normalizer=RequestNormalizer(),
        script_service=SleepScriptService(script_writer=script_writer),
        settings=settings,
    )
    state.remix_service = RemixService(repository, storage)
    state.agent_runtime = HermesAgentRuntime(
        repository=repository,
        storage=storage,
        normalizer=state.generation_service.normalizer,
        generation_service=state.generation_service,
        remix_service=state.remix_service,
        library=library,
        settings=settings,
        directive_planner=directive_planner,
    )
    # Seed the catalog once at startup (idempotent) so voice/demo requests
    # don't pay the ~60s seeding cost on their first call.
    try:
        seed_assets(repository, storage)
    except Exception:  # noqa: BLE001 — seeding is best-effort at startup
        pass
    yield
    conn.close()


app = FastAPI(title="Floppy Backend MVP", version="0.1.0", lifespan=lifespan)


def repo() -> Repository:
    return state.repository


def storage() -> LocalFileStorage:
    return state.storage


@app.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {"status": "ok", "app": settings.app_name}


def _ensure_demo_profile(user_id: str) -> None:
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


def _resolve_audio_asset(user_id: str, request_text: str) -> dict | None:
    """Run the Hermes agent runtime to match/generate a playable sleep-audio asset.

    Returns {"url", "title", "audio_type"} or None. Mirrors /demo/chat's
    play_asset / generate_job handling. Runs synchronously (call via
    asyncio.to_thread from the async ws handler).
    """
    response = state.agent_runtime.run(
        AgentDecideRequest(user_id=user_id, request_text=request_text, generation_allowed=True)
    )
    if response.action == "play_asset" and response.asset:
        return {"url": response.asset.playback_url, "title": response.asset.title}
    if response.action == "generate_job" and response.job_id:
        state.generation_service.run_job(
            response.job_id, user_id, GenerationRequest(request_text=request_text, force_generate=True)
        )
        for _ in range(10):
            job = state.repository.get_generation_job(response.job_id)
            if job and job.status in {"succeeded", "failed"}:
                if job.status == "succeeded" and job.asset:
                    return {"url": state.storage.public_url(job.asset.object_key), "title": job.asset.title}
                break
            time.sleep(0.2)
    return None


@app.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket):
    """Realtime full-duplex voice dialog.

    Protocol (see docs/contracts/voice_dialog_ws.md):
      - Client connects with ?token=<shared-secret> when FLOPPY_VOICE_WS_TOKEN is set.
      - Client sends binary frames = raw PCM (16k/mono/16bit) audio chunks.
      - Client sends {"type":"utterance_end"} to finalize the CURRENT utterance
        (triggers recognition + reply) while keeping the connection open for the
        next turn — multi-turn dialog with shared history.
      - Client sends {"type":"stop"} to end the whole session.
      - Server sends text frames for transcripts/assistant text/control, and
        binary frames for TTS audio (mp3 chunks).
    """
    settings = get_settings()
    token = websocket.query_params.get("token")
    user_id = websocket.query_params.get("user_id")
    if settings.voice_ws_token and token != settings.voice_ws_token:
        await websocket.close(code=4401)
        return
    await websocket.accept()

    # Lazy imports keep optional voice deps out of the core startup path.
    from floppy_backend.providers.minimax_stream_tts import MiniMaxStreamTTS
    from floppy_backend.providers.volc_asr import VolcStreamASR
    from floppy_backend.services.dialog_llm import DialogLLM
    from floppy_backend.services.voice_session import EVENT_AUDIO, OutboundEvent, VoiceSession

    # Resolve a sleep-audio asset via the agent runtime (off the event loop).
    resolve_user_id = user_id or "voice_demo_user"
    await asyncio.to_thread(_ensure_demo_profile, resolve_user_id)

    async def _audio_resolver(request_text: str, audio_type: str) -> dict | None:
        asset = await asyncio.to_thread(_resolve_audio_asset, resolve_user_id, request_text)
        if asset:
            asset.setdefault("audio_type", audio_type)
        return asset

    try:
        session = VoiceSession(
            asr=VolcStreamASR(settings),
            llm=DialogLLM(settings),
            tts=MiniMaxStreamTTS(settings),
            user_id=user_id,
            voice_style=websocket.query_params.get("voice_style"),
            audio_resolver=_audio_resolver,
        )
    except Exception as exc:  # noqa: BLE001 — config/credential errors
        await websocket.send_text(json.dumps({"type": "error", "text": str(exc)}))
        await websocket.close(code=1011)
        return

    async def _emit(event: OutboundEvent) -> None:
        if event.type == EVENT_AUDIO and event.audio is not None:
            await websocket.send_bytes(event.audio)
        else:
            await websocket.send_text(json.dumps(event.text_payload(), ensure_ascii=False))

    await _emit(session.start_event())

    # One audio queue per utterance; a new queue starts when the previous
    # utterance is finalized. The session processes utterances serially.
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    utterance_task: asyncio.Task | None = None

    async def _audio_in(queue: asyncio.Queue[bytes | None]):
        while True:
            chunk = await queue.get()
            if chunk is None:
                return
            yield chunk

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                # Start an utterance lazily on first audio frame.
                if utterance_task is None or utterance_task.done():
                    audio_queue = asyncio.Queue()
                    utterance_task = asyncio.create_task(session.run_utterance(_audio_in(audio_queue), _emit))
                await audio_queue.put(data)
            elif (text := message.get("text")) is not None:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                ctrl_type = ctrl.get("type")
                if ctrl_type == "utterance_end":
                    # Finalize current utterance; wait for the full reply so the
                    # next utterance sees updated history.
                    await audio_queue.put(None)
                    if utterance_task:
                        await utterance_task
                elif ctrl_type == "stop":
                    await audio_queue.put(None)
                    if utterance_task:
                        await utterance_task
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await audio_queue.put(None)
        if utterance_task and not utterance_task.done():
            try:
                await asyncio.wait_for(utterance_task, timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                utterance_task.cancel()


@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    return DEMO_HTML


@app.get("/voice", response_class=HTMLResponse)
def voice_page():
    from floppy_backend.voice_page import VOICE_HTML
    from floppy_backend.voice_script import VOICE_SCRIPT
    return VOICE_HTML.replace("__SCRIPT__", VOICE_SCRIPT)


@app.post("/demo/chat")
def demo_chat(payload: dict):
    request_text = str(payload.get("request_text", "")).strip()
    if len(request_text) < 2:
        raise HTTPException(status_code=400, detail="request_text is required")

    seed_assets(state.repository, state.storage)
    demo_user = "demo_user"
    state.profile_service.upsert_profile(
        demo_user,
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

    response = state.agent_runtime.run(AgentDecideRequest(user_id=demo_user, request_text=request_text, generation_allowed=True))
    audio_url = response.asset.playback_url if response.asset else None

    job = None
    if response.action == "generate_job" and response.job_id:
        state.generation_service.run_job(response.job_id, demo_user, GenerationRequest(request_text=request_text, force_generate=True))
        for _ in range(5):
            job = state.repository.get_generation_job(response.job_id)
            if job and job.status in {"succeeded", "failed"}:
                break
            time.sleep(0.2)
        if job and job.asset:
            audio_url = state.storage.public_url(job.asset.object_key)

    asset_data = response.asset.model_dump(mode="json") if response.asset else (job.asset.model_dump(mode="json") if job and job.asset else None)
    is_placeholder = bool(asset_data and is_placeholder_created_by(asset_data.get("created_by")))

    return {
        "action": response.action,
        "audio_url": audio_url,
        "asset": asset_data,
        "is_placeholder": is_placeholder,
        "job_id": response.job_id,
        "job_status": job.status if job else None,
        "best_score": response.search.best_score,
        "hit": response.search.hit,
        "threshold": response.search.threshold,
        "reasons": response.reasons,
        "planner_meta": response.planner_meta.model_dump(mode="json") if response.planner_meta else None,
    }


@app.post("/admin/seed")
def seed():
    created = seed_assets(state.repository, state.storage)
    return {"created_or_updated": created}


@app.put("/users/{user_id}/profile", response_model=UserProfile)
def upsert_profile(user_id: str, profile: UserProfileIn):
    return state.profile_service.upsert_profile(user_id, profile)


@app.get("/users/{user_id}/profile", response_model=UserProfile)
def get_profile(user_id: str, repository: Repository = Depends(repo)):
    profile = repository.get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@app.post("/users/{user_id}/profile/checkin", response_model=UserProfile)
def update_profile_signal(user_id: str, checkin: ProfileCheckinIn, repository: Repository = Depends(repo)):
    return repository.update_profile_checkin(user_id, checkin)


@app.get("/users/{user_id}/profile/context", response_model=ProfileContext)
def get_profile_context(user_id: str, settings: Settings = Depends(get_settings), repository: Repository = Depends(repo)):
    profile = repository.get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    used_chars, used_count = repository.generation_usage_since(user_id)
    return ProfileContext(
        **profile.model_dump(),
        generation_budget=GenerationBudget(
            daily_remaining_chars=max(0, settings.daily_char_budget - used_chars),
            daily_generate_count_remaining=max(0, settings.daily_generate_count - used_count),
        ),
    )


@app.post("/normalize", response_model=NormalizedRequestOut)
def normalize_request(payload: NormalizeRequestIn, repository: Repository = Depends(repo)):
    profile = repository.get_profile(payload.user_id) if payload.user_id else None
    normalized = state.generation_service.normalizer.normalize(
        GenerationRequest(request_text=payload.request_text, duration_preference_min=payload.duration_preference_min),
        profile,
    )
    return NormalizedRequestOut(normalized_request=normalized, cache_key=state.generation_service.cache_key_for(normalized))


@app.post("/assets/search", response_model=AssetSearchResponse)
def search_audio_assets(request: AssetSearchRequest):
    response = state.library.search(request)
    for result in response.results:
        result.asset.playback_url = state.storage.public_url(result.asset.object_key)
    return response


@app.get("/users/{user_id}/recommendations", response_model=list[Recommendation])
def recommend(user_id: str, limit: int = 5, query: str | None = None):
    recommendations = state.library.recommend(user_id, limit=limit, query=query)
    for item in recommendations:
        item.asset.playback_url = state.storage.public_url(item.asset.object_key)
    return recommendations


@app.post("/users/{user_id}/generate-audio", response_model=GenerationResponse)
def generate_audio(user_id: str, request: GenerationRequest):
    try:
        return state.generation_service.generate_or_match(user_id, request)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.post("/users/{user_id}/generation-jobs", response_model=GenerationJobCreateResponse, status_code=202)
def create_generation_job(user_id: str, request: GenerationRequest, background_tasks: BackgroundTasks):
    try:
        response = state.generation_service.enqueue_or_match(user_id, request)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if response.status == "queued":
        background_tasks.add_task(state.generation_service.run_job, response.job_id, user_id, request)
    return response


@app.get("/generation-jobs/{job_id}", response_model=GenerationJob)
def get_generation_job(job_id: str, repository: Repository = Depends(repo)):
    job = repository.get_generation_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation job not found")
    if job.asset:
        job.asset.playback_url = state.storage.public_url(job.asset.object_key)
    return job


@app.post("/users/{user_id}/events")
def record_event(user_id: str, event: EventIn, repository: Repository = Depends(repo)):
    event_id = repository.record_event(user_id, event)
    return {"event_id": event_id}


@app.post("/agent/decide", response_model=AgentDecideResponse)
def agent_decide(req: AgentDecideRequest, background_tasks: BackgroundTasks):
    try:
        response = state.agent_runtime.run(req)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        if "profile not found" in str(exc):
            raise HTTPException(status_code=404, detail="profile not found") from exc
        raise

    if response.action == "generate_job" and response.job_id:
        background_tasks.add_task(
            state.generation_service.run_job,
            response.job_id,
            req.user_id,
            GenerationRequest(request_text=req.request_text, force_generate=True),
        )
    return response


@app.get("/audio/{object_key:path}")
def get_audio(object_key: str, file_storage: LocalFileStorage = Depends(storage)):
    try:
        path = file_storage.existing_path_for(object_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid object key") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(Path(path), media_type=media_type)


# --- P0: Questionnaire ---


@app.put("/users/{user_id}/questionnaire", response_model=UserQuestionnaire)
def save_questionnaire(user_id: str, data: UserQuestionnaireIn):
    return state.repository.upsert_questionnaire(user_id, data)


@app.get("/users/{user_id}/questionnaire", response_model=UserQuestionnaire)
def get_questionnaire(user_id: str):
    q = state.repository.get_questionnaire(user_id)
    if q is None:
        raise HTTPException(status_code=404, detail="questionnaire not found")
    return q


# --- P0: Playback History & Feedback ---


@app.post("/users/{user_id}/playback", status_code=201)
def start_playback(user_id: str, payload: PlaybackStartIn):
    asset = state.repository.get_asset(payload.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    record_id = state.repository.record_playback_start(
        user_id, payload.asset_id, asset.title, payload.source.value, payload.request_text,
        parent_asset_id=payload.parent_asset_id, ambient_asset_id=payload.ambient_asset_id,
    )
    return {"record_id": record_id}


@app.post("/users/{user_id}/playback/{record_id}/feedback")
def submit_playback_feedback(user_id: str, record_id: str, feedback: PlaybackFeedbackIn):
    completed = feedback.feedback_type in ("complete", "morning_feedback")
    state.repository.update_playback_feedback(
        record_id, feedback_type=feedback.feedback_type.value,
        rating=feedback.rating, progress=feedback.progress,
        morning_feedback=feedback.morning_feedback, completed=completed,
    )
    return {"status": "ok"}


@app.get("/users/{user_id}/playback/history", response_model=list[PlaybackRecord])
def get_playback_history(user_id: str, limit: int = 50):
    return state.repository.list_playback_history(user_id, limit=min(limit, 50))


# --- P0: Remix ---


@app.post("/users/{user_id}/remix", response_model=RemixJob, status_code=202)
def create_remix(user_id: str, payload: RemixRequestIn, background_tasks: BackgroundTasks):
    voice_asset = state.repository.get_asset(payload.voice_asset_id)
    if voice_asset is None:
        raise HTTPException(status_code=404, detail="voice asset not found")
    if payload.ambient_asset_id:
        ambient_asset = state.repository.get_asset(payload.ambient_asset_id)
        if ambient_asset is None:
            raise HTTPException(status_code=404, detail="ambient asset not found")
    if not payload.ambient_asset_id and not payload.sound_type:
        raise HTTPException(status_code=400, detail="either ambient_asset_id or sound_type is required")
    job_id = state.repository.create_remix_job(
        user_id, payload.voice_asset_id, payload.ambient_asset_id,
        payload.ambient_tags, payload.voice_volume, payload.ambient_volume,
        sound_type=payload.sound_type,
    )
    background_tasks.add_task(state.remix_service.run_remix, job_id)
    job = state.repository.get_remix_job(job_id)
    return job


@app.get("/remix-jobs/{job_id}", response_model=RemixJob)
def get_remix_job(job_id: str):
    job = state.repository.get_remix_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="remix job not found")
    if job.output_asset:
        job.output_asset.playback_url = state.storage.public_url(job.output_asset.object_key)
    return job


# --- P0: Remix Sessions (algo §3) ---

REMIX_HOURLY_LIMIT = 20


@app.post("/remix/sessions", response_model=RemixSession, status_code=202)
def create_remix_session(payload: RemixSessionCreateIn, background_tasks: BackgroundTasks):
    # Resolve foreground asset
    foreground_asset_id = payload.foreground_asset_id
    foreground_source = "asset_id"
    user_id: str | None = None

    if not foreground_asset_id:
        raise HTTPException(status_code=400, detail="foreground_asset_id is required (active playback inference requires user_id via /agent/decide)")

    asset = state.repository.get_asset(foreground_asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="foreground asset not found")

    # Determine user from recent playback or require explicit
    # For session API, we need user context — get from active playback
    with state.repository._lock:
        row = state.repository.conn.execute(
            "SELECT user_id FROM playback_history WHERE asset_id = ? ORDER BY started_at DESC LIMIT 1",
            (foreground_asset_id,),
        ).fetchone()
    if row is None:
        # Fallback: use a system user for direct API calls
        user_id = "api_user"
        state.repository.ensure_user(user_id)
    else:
        user_id = row["user_id"]

    # Rate limit
    count = state.repository.count_remix_last_hour(user_id)
    if count >= REMIX_HOURLY_LIMIT:
        raise HTTPException(status_code=429, detail=f"remix rate limit exceeded ({REMIX_HOURLY_LIMIT}/hour)")

    # Validate ambient source
    if not payload.ambient_asset_id and not payload.sound_type and payload.intent.value != "remove_background":
        raise HTTPException(status_code=400, detail="ambient_asset_id or sound_type required for this intent")

    job_id = state.repository.create_remix_job(
        user_id, foreground_asset_id, payload.ambient_asset_id, [],
        voice_volume=1.0, ambient_volume=payload.mix_params.background_volume,
        sound_type=payload.sound_type, intent=payload.intent.value,
        mix_params=payload.mix_params, foreground_source=foreground_source,
    )
    background_tasks.add_task(state.remix_service.run_remix, job_id)
    session = state.repository.get_remix_session(job_id)
    return session


@app.patch("/remix/sessions/{session_id}", response_model=RemixSession)
def patch_remix_session(session_id: str, patch: RemixSessionPatchIn, background_tasks: BackgroundTasks):
    session = state.repository.get_remix_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="remix session not found")

    intent = patch.intent.value if patch.intent else session.intent
    mix_params = patch.mix_params or session.mix_params or MixParams()

    # Update session metadata
    state.repository.update_remix_job(
        session_id, status="queued",
        intent=intent,
        mix_params=mix_params,
        sound_type=patch.sound_type,
        ambient_asset_id=patch.ambient_asset_id,
    )
    # Re-run remix with updated params
    background_tasks.add_task(state.remix_service.run_remix, session_id)
    return state.repository.get_remix_session(session_id)


@app.get("/remix/sessions/{session_id}", response_model=RemixSession)
def get_remix_session(session_id: str):
    session = state.repository.get_remix_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="remix session not found")
    if session.output_asset:
        session.output_asset.playback_url = state.storage.public_url(session.output_asset.object_key)
    return session


@app.get("/assets/{asset_id}/remixable", response_model=AssetRemixable)
def check_asset_remixable(asset_id: str):
    from floppy_backend.services.assets import is_placeholder_created_by
    asset = state.repository.get_asset(asset_id)
    if asset is None:
        return AssetRemixable(asset_id=asset_id, remixable=False, reason="asset not found")
    if is_placeholder_created_by(asset.created_by):
        return AssetRemixable(asset_id=asset_id, remixable=False, reason="placeholder asset")
    try:
        path = state.storage.existing_path_for(asset.object_key)
        if not path.exists():
            return AssetRemixable(asset_id=asset_id, remixable=False, reason="audio file missing")
        fmt = "mp3" if path.suffix.lower() == ".mp3" else "wav"
        return AssetRemixable(asset_id=asset_id, remixable=True, format=fmt)
    except ValueError:
        return AssetRemixable(asset_id=asset_id, remixable=False, reason="invalid object key")


# ---------------------------------------------------------------------------
# Mobile (Home / Chat) adapter endpoints — frontend contract, see
# docs/frontend/home_chat_integration.md
# ---------------------------------------------------------------------------

_CATEGORY_BY_TYPE = {
    "white_noise": "White Noise",
    "music": "Music",
    "asmr": "ASMR",
    "story": "Story",
    "meditation": "Meditation",
    "podcast_digest": "Podcast",
}


def _audio_item(asset, progress: float = 0.0) -> dict:
    """Map a backend AudioAsset onto the frontend AudioItem shape."""
    if asset.playback_url is None:
        asset.playback_url = state.storage.public_url(asset.object_key)
    category = _CATEGORY_BY_TYPE.get(asset.type.value, "Sleep")
    is_generated = asset.created_by in {"ondemand", "remix"}
    minutes = max(1, round(asset.duration_sec / 60))
    return {
        "id": asset.id,
        "title": asset.title,
        "subtitle": f"{minutes} min · {category}",
        "durationSeconds": asset.duration_sec,
        "streamUrl": asset.playback_url,
        "coverUrl": None,
        "source": "Generated" if is_generated else "Library",
        "category": category,
        "playbackProgress": progress,
        "isGenerated": is_generated,
    }


class VoiceIntentIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    source: str = "chat"  # "chat" | "voice"
    conversationId: str | None = None
    clientRequestId: str | None = None
    turnIndex: int | None = None
    supersedesRequestId: str | None = None
    user_id: str = "mobile_user"


@app.post("/voice/intent")
def voice_intent(payload: VoiceIntentIn):
    """Unified text/voice intent for Home & Chat.

    Synchronous by design (hackathon): a cache/catalog hit returns instantly;
    a generation runs inline (~10-25s with real TTS) so the frontend never
    polls — one request, one playable answer.
    """
    echo = {
        "conversationId": payload.conversationId,
        "clientRequestId": payload.clientRequestId,
        "turnIndex": payload.turnIndex,
    }
    text = payload.text.strip()
    if len(text) < 2:
        reply = "我没听清楚，能再说一遍吗?"
        return {"action": "no_match", "reply": reply, "replyAudioUrl": _reply_audio_url(reply), "audio": None, **echo}

    _ensure_demo_profile(payload.user_id)
    response = state.agent_runtime.run(
        AgentDecideRequest(user_id=payload.user_id, request_text=text, generation_allowed=True)
    )

    # Pure conversation turn — the agent chatted, nothing to play.
    if response.action == "chat":
        reply = response.reply or "我在呢，想聊什么都可以。"
        return {"action": "chat", "reply": reply, "replyAudioUrl": _reply_audio_url(reply), "audio": None, **echo}

    asset = response.asset
    generated_now = False
    if response.action == "generate_job" and response.job_id:
        state.generation_service.run_job(
            response.job_id, payload.user_id, GenerationRequest(request_text=text, force_generate=True)
        )
        job = state.repository.get_generation_job(response.job_id)
        if job and job.status == "succeeded" and job.asset:
            asset = job.asset
            asset.playback_url = state.storage.public_url(asset.object_key)
            generated_now = True

    if asset is not None:
        if generated_now:
            reply = f"我为你专门做了一段新的音频：《{asset.title}》，希望你喜欢。"
        else:
            reply = response.reply or f"我给你找了一段适合现在听的音频：《{asset.title}》。"
        return {"action": "play_asset", "reply": reply, "replyAudioUrl": _reply_audio_url(reply), "audio": _audio_item(asset), **echo}

    no_match_reply = response.reply or "暂时没有找到合适的内容，换个说法再试试？"
    return {
        "action": "no_match",
        "reply": no_match_reply,
        "replyAudioUrl": _reply_audio_url(no_match_reply),
        "audio": None,
        **echo,
    }


@app.get("/users/{user_id}/audio-library")
def audio_library(user_id: str, limit: int = 10):
    """Home initial data: recommended / uploads / history as AudioItem lists.

    Recommended = curated pool (real recordings + official prewarm) with
    profile-aware rule ranking and type diversity — community/test generations
    never reach the Home shelf.
    """
    recommended = [_audio_item(asset) for asset in state.library.home_recommended(user_id, limit=limit)]
    prefix = f"uploads/{user_id}/"
    uploads = [
        _upload_item(asset)
        for asset in state.repository.list_assets()
        if "upload" in asset.tags and asset.object_key.startswith(prefix)
    ]
    history = []
    for record in state.repository.list_playback_history(user_id, limit=limit):
        asset = state.repository.get_asset(record.asset_id)
        if asset is None:
            continue
        history.append(_audio_item(asset, progress=record.progress or 0.0))
    return {"recommended": recommended, "uploads": uploads, "history": history}


@app.websocket("/v1/speech/stream")
async def speech_stream_ws(websocket: WebSocket):
    """Realtime speech-to-text only (no dialog/TTS — that's /voice/ws).

    Client: {"type":"start",...} JSON, then binary PCM 16k/mono/s16le frames,
    then {"type":"stop"}. Server: {"type":"partial"|"final"|"error", ...}.
    """
    await websocket.accept()
    from floppy_backend.providers.volc_asr import VolcStreamASR

    try:
        asr = VolcStreamASR(get_settings())
    except Exception as exc:  # noqa: BLE001 — missing ASR credentials
        await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
        await websocket.close(code=1011)
        return

    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def _audio_iter():
        while True:
            chunk = await queue.get()
            if chunk is None:
                return
            yield chunk

    async def _recognize() -> None:
        last_text = ""
        try:
            async for result in asr.stream_recognize(_audio_iter()):
                if result.text:
                    last_text = result.text
                    await websocket.send_text(
                        json.dumps({"type": "partial", "text": result.text}, ensure_ascii=False)
                    )
            await websocket.send_text(json.dumps({"type": "final", "text": last_text}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001 — surface ASR failures to the client
            try:
                await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
            except Exception:  # noqa: BLE001
                pass

    recognize_task = asyncio.create_task(_recognize())
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                await queue.put(data)
            elif (text := message.get("text")) is not None:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if ctrl.get("type") == "stop":
                    await queue.put(None)
                    await recognize_task
                    break
                # "start" is acknowledged implicitly; upstream format is fixed
                # (16k/mono/pcm_s16le — the only format Volc ASR accepts).
    except WebSocketDisconnect:
        pass
    finally:
        await queue.put(None)
        if not recognize_task.done():
            try:
                await asyncio.wait_for(recognize_task, timeout=15)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                recognize_task.cancel()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


@app.post("/v1/speech/transcriptions")
async def speech_transcriptions(
    file: UploadFile = File(...),
    locale: str = Form("zh-CN"),
    source: str | None = Form(None),
):
    """File-based transcription fallback (m4a/mp4/wav → text) via ffmpeg + Volc ASR."""
    import shutil
    import subprocess
    import tempfile

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty audio file")
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="ffmpeg not available on server")

    # m4a/mp4 need seekable input (moov atom) — decode from a temp file, not a pipe.
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "audio.m4a").suffix or ".m4a") as tmp:
        tmp.write(data)
        tmp.flush()
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", tmp.name,
                "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
                "pipe:1",
            ],
            capture_output=True,
        )
    if proc.returncode != 0 or not proc.stdout:
        raise HTTPException(status_code=400, detail=f"audio decode failed: {proc.stderr.decode()[:200]}")
    pcm = proc.stdout

    from floppy_backend.providers.volc_asr import VolcStreamASR

    try:
        asr = VolcStreamASR(get_settings())
    except Exception as exc:  # noqa: BLE001 — missing ASR credentials
        raise HTTPException(status_code=500, detail=f"ASR unavailable: {exc}") from exc

    async def _chunks():
        step = 3200  # 100ms of 16k/mono/s16le
        for i in range(0, len(pcm), step):
            yield pcm[i : i + step]

    text = ""
    try:
        async for result in asr.stream_recognize(_chunks()):
            if result.text:
                text = result.text
    except Exception as exc:  # noqa: BLE001 — provider/network errors
        raise HTTPException(status_code=502, detail=f"ASR failed: {exc}") from exc

    return {"text": text, "language": locale, "duration_ms": len(pcm) // 32}


# ---------------------------------------------------------------------------
# Frontend-app compat endpoints — shapes match front/Floppy's FloppyApi.kt
# (RemoteFloppyRepository). Enum-like strings (status/source) must match the
# Kotlin enum constant names exactly (Gson deserializes by name).
# ---------------------------------------------------------------------------

_MOBILE_DEFAULT_USER = "mobile_user"

_TYPE_BY_CONTENT_PREF = {
    "Story": "story",
    "Asmr": "asmr",
    "WhiteNoise": "white_noise",
    "Meditation": "meditation",
    "PsychologicalHealing": "meditation",
    "PopularKnowledge": "podcast_digest",
}

_GEN_STATUS_MAP = {"queued": "Pending", "generating": "Generating", "succeeded": "Success", "failed": "Failed"}

_PLAYBACK_SOURCE_MAP = {"Library": "recommend", "Generated": "generated", "Upload": "import"}


def _upload_item(asset, *, file_name: str | None = None, size_label: str = "") -> dict:
    audio = _audio_item(asset)
    audio["source"] = "Upload"
    audio["category"] = "My upload"
    name = file_name or f"{asset.title}{Path(asset.object_key).suffix}"
    return {
        "id": asset.id,
        "fileName": name,
        "fileType": Path(asset.object_key).suffix.lstrip(".") or "audio",
        "sizeLabel": size_label,
        "progress": 1.0,
        "status": "Completed",
        "message": None,
        "generatedAudio": audio,
    }


@app.post("/v1/recommendations")
def mobile_recommend(profile: dict):
    """Tonight's one-tap recommendation for the app Home — curated pool with
    rotation (no consecutive repeats)."""
    preferred = [_TYPE_BY_CONTENT_PREF.get(p) for p in (profile.get("contentPreferences") or [])]
    preferred = [p for p in preferred if p]
    asset = state.library.tonight_pick(user_id=_MOBILE_DEFAULT_USER, preferred_types=preferred)
    if asset is None:
        return {
            "action": "generate_job",
            "generation_prompt": "生成一段适合今晚入睡的睡前音频",
            "message": "曲库为空，需要现场生成",
        }
    return {"action": "play_asset", "audio": _audio_item(asset), "message": "已找到适合今晚的音频"}


class MobileGenerationTaskIn(BaseModel):
    prompt: str = Field(min_length=2, max_length=1000)
    profile: dict | None = None


def _generation_task_view(job_id: str) -> dict:
    job = state.repository.get_generation_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="task not found")
    status = _GEN_STATUS_MAP.get(job.status, "Generating")
    audio = None
    if job.asset is not None:
        job.asset.playback_url = state.storage.public_url(job.asset.object_key)
        audio = _audio_item(job.asset)
    message = {
        "Pending": "已排队，Floppy 正在准备生成",
        "Generating": "Floppy 正在为你生成音频",
        "Success": "音频已生成",
        "Failed": job.error_message or "生成失败，请稍后再试",
    }[status]
    return {"id": job.id, "status": status, "message": message, "audio": audio}


@app.post("/v1/generation-tasks")
def mobile_create_generation_task(payload: MobileGenerationTaskIn, background_tasks: BackgroundTasks):
    _ensure_demo_profile(_MOBILE_DEFAULT_USER)
    request = GenerationRequest(request_text=payload.prompt)
    try:
        response = state.generation_service.enqueue_or_match(_MOBILE_DEFAULT_USER, request)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if response.status == "queued":
        background_tasks.add_task(state.generation_service.run_job, response.job_id, _MOBILE_DEFAULT_USER, request)
    return _generation_task_view(response.job_id)


@app.get("/v1/generation-tasks/{task_id}")
def mobile_get_generation_task(task_id: str):
    return _generation_task_view(task_id)


class MobileFeedbackIn(BaseModel):
    audioId: str
    rating: int = Field(ge=1, le=5)
    reason: str | None = None


@app.post("/v1/feedback")
def mobile_feedback(payload: MobileFeedbackIn):
    event_type = "audio_liked" if payload.rating >= 4 else ("audio_disliked" if payload.rating <= 2 else "audio_rated")
    state.repository.record_event(
        _MOBILE_DEFAULT_USER,
        EventIn(event_type=event_type, asset_id=payload.audioId, payload={"rating": payload.rating, "reason": payload.reason or ""}),
    )
    return {"accepted": True, "message": "已收到你的反馈，Floppy 会越来越懂你"}


class MobileHistoryIn(BaseModel):
    audioId: str
    source: str = "Library"
    positionSeconds: int = 0
    durationSeconds: int = 0
    playbackProgress: float = 0.0
    event: str = "play"


@app.post("/users/{user_id}/audio/history")
def mobile_report_history(user_id: str, payload: MobileHistoryIn):
    asset = state.repository.get_asset(payload.audioId)
    if asset is None:
        raise HTTPException(status_code=404, detail="audio not found")
    record_id = state.repository.record_playback_start(
        user_id, asset.id, asset.title, _PLAYBACK_SOURCE_MAP.get(payload.source, "recommend")
    )
    if payload.playbackProgress:
        state.repository.update_playback_feedback(record_id, progress=min(1.0, max(0.0, payload.playbackProgress)))
    return _audio_item(asset, progress=payload.playbackProgress)


@app.post("/v1/settings")
def mobile_update_settings(settings_payload: dict):
    # Settings live client-side for now; echo back so the app state machine advances.
    return settings_payload


@app.post("/users/{user_id}/uploads")
async def mobile_upload(user_id: str, file: UploadFile = File(...)):
    import hashlib
    import uuid

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    filename = Path(file.filename or "upload.bin").name
    suffix = Path(filename).suffix.lower() or ".mp3"
    object_key = f"uploads/{user_id}/{uuid.uuid4().hex[:12]}{suffix}"
    path = state.storage.path_for(object_key)
    path.write_bytes(data)

    duration_sec = 0
    try:
        from floppy_backend.services.minimax_hubless import probe_audio
        duration_sec = int(probe_audio(path).duration_sec)
    except Exception:  # noqa: BLE001 — duration is cosmetic
        pass

    from floppy_backend.models import AudioAssetIn
    from floppy_backend.utils import text_embedding

    asset = state.repository.upsert_asset(
        AudioAssetIn(
            type=AudioType.MUSIC,
            title=Path(filename).stem,
            object_key=object_key,
            duration_sec=duration_sec,
            voice_id="user_upload",
            prompt_hash=f"upload:{uuid.uuid4().hex}",
            content_hash=hashlib.sha256(data).hexdigest(),
            mood_tags=[],
            tags=["upload"],
            user_segment_tags=[],
            quality_score=0.5,
            embedding=text_embedding(Path(filename).stem),
            created_by="import",
        )
    )
    size_label = f"{len(data) / (1024 * 1024):.1f} MB"
    return _upload_item(asset, file_name=filename, size_label=size_label)


@app.get("/users/{user_id}/uploads")
def mobile_list_uploads(user_id: str):
    prefix = f"uploads/{user_id}/"
    return [
        _upload_item(asset)
        for asset in state.repository.list_assets()
        if "upload" in asset.tags and asset.object_key.startswith(prefix)
    ]


@app.post("/users/{user_id}/uploads/{upload_id}/retry")
@app.post("/users/{user_id}/uploads/{upload_id}/complete")
def mobile_upload_noop(user_id: str, upload_id: str):
    asset = state.repository.get_asset(upload_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return _upload_item(asset)


def _reply_audio_url(reply: str) -> str | None:
    """Synthesize the agent's spoken reply (MiniMax TTS), cached by reply text.

    Best-effort: any failure falls back to text-only. Short replies (≤40 chars)
    cost ~$0.002 and ~1-2s; repeated phrasings hit the file cache."""
    text = (reply or "").strip()
    if not text:
        return None
    provider = state.generation_service.provider
    if not hasattr(provider, "generate_text_to_file"):
        return None  # local tone provider — no real voice
    import hashlib
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    object_key = f"replies/{digest}.mp3"
    try:
        path = state.storage.path_for(object_key)
        if not path.exists():
            provider.generate_text_to_file(text, path, object_key, voice_style="warm_female", title="floppy_reply")
        return state.storage.public_url(object_key)
    except Exception:  # noqa: BLE001 — voice reply is an enhancement, never a blocker
        return None


@app.websocket("/voice/realtime")
async def voice_realtime_ws(websocket: WebSocket):
    """「和 Floppy 打电话」— 豆包端到端实时语音的代理通道（纯陪聊模式）。

    App 侧协议（简单）：
      上行：binary = PCM 16k/mono/s16le 麦克风流；{"type":"stop"} 结束
      下行：binary = PCM 24k/mono/s16le 回复音频（AudioTrack 直接播）
            JSON  = {"type":"ready"|"asr"|"asr_info"|"chat"|"tts_end"|"error", ...}
    上游豆包二进制协议、人设注入全部由本端点处理（providers/volc_realtime.py）。
    """
    import websockets as ws_client
    from floppy_backend.providers import volc_realtime as vr

    await websocket.accept()
    settings = get_settings()
    user_id = websocket.query_params.get("user_id") or "realtime_user"
    session_id = str(__import__("uuid").uuid4())

    try:
        headers = vr.upstream_headers(settings)
    except RuntimeError as exc:
        await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
        await websocket.close(code=1011)
        return

    try:
        upstream = await ws_client.connect(vr.REALTIME_URL, additional_headers=headers, open_timeout=10, max_size=10 * 1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        await websocket.send_text(json.dumps({"type": "error", "message": f"豆包连接失败: {exc}"}, ensure_ascii=False))
        await websocket.close(code=1011)
        return

    async def _emit(obj: dict) -> None:
        await websocket.send_text(json.dumps(obj, ensure_ascii=False))

    try:
        # 握手序列: StartConnection → ConnectionStarted → StartSession → SessionStarted
        await upstream.send(vr.start_connection_frame())
        evt = vr.parse_server_frame(await upstream.recv())
        if evt.event != vr.EV_CONNECTION_STARTED:
            raise RuntimeError(f"unexpected connect event {evt.event}: {evt.json()}")
        await upstream.send(vr.start_session_frame(session_id, vr.session_config(settings)))
        evt = vr.parse_server_frame(await upstream.recv())
        if evt.event != vr.EV_SESSION_STARTED:
            raise RuntimeError(f"session start failed {evt.event}: {evt.json()}")
        await _emit({"type": "ready", "dialogId": evt.json().get("dialog_id", "")})
    except Exception as exc:  # noqa: BLE001
        await _emit({"type": "error", "message": f"会话建立失败: {exc}"})
        await upstream.close()
        await websocket.close(code=1011)
        return

    async def _pump_upstream() -> None:
        """豆包事件 → App 简单协议"""
        try:
            async for raw in upstream:
                evt = vr.parse_server_frame(raw)
                if evt.event == vr.EV_TTS_RESPONSE:
                    await websocket.send_bytes(evt.payload)
                elif evt.event == vr.EV_ASR_INFO:
                    await _emit({"type": "asr_info"})  # 用户开口 → 客户端立刻停播（打断）
                elif evt.event == vr.EV_ASR_RESPONSE:
                    results = evt.json().get("results") or []
                    if results:
                        await _emit({"type": "asr", "text": results[0].get("text", ""), "interim": bool(results[0].get("is_interim"))})
                elif evt.event == vr.EV_CHAT_RESPONSE:
                    await _emit({"type": "chat", "text": evt.json().get("content", "")})
                elif evt.event == vr.EV_TTS_ENDED:
                    await _emit({"type": "tts_end"})
                elif evt.event in (vr.EV_SESSION_FINISHED,):
                    break
                elif evt.event in (vr.EV_SESSION_FAILED, vr.EV_DIALOG_ERROR, vr.EV_CONNECTION_FAILED):
                    await _emit({"type": "error", "message": str(evt.json())})
                    break
        except Exception:  # noqa: BLE001 — upstream closed
            pass
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass

    pump_task = asyncio.create_task(_pump_upstream())
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                await upstream.send(vr.audio_frame(session_id, data))
            elif (text := message.get("text")) is not None:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if ctrl.get("type") == "stop":
                    break
                if ctrl.get("type") == "text_query" and ctrl.get("text"):
                    # 文本旁路（调试/无麦克风环境用）
                    await upstream.send(vr.chat_text_query_frame(session_id, str(ctrl["text"])))
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await upstream.send(vr.finish_session_frame(session_id))
            await upstream.send(vr.finish_connection_frame())
        except Exception:  # noqa: BLE001
            pass
        await upstream.close()
        pump_task.cancel()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
