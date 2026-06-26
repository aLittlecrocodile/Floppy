from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import json
import time

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

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
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.profile import ProfileService
from floppy_backend.services.query_planner import build_query_planner
from floppy_backend.services.recommendation import RecommendationService
from floppy_backend.services.remix import RemixService
from floppy_backend.services.script import SleepScriptService
from floppy_backend.services.agent_graph import AgentGraphBuilder
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json


class AppState:
    repository: Repository
    storage: LocalFileStorage
    profile_service: ProfileService
    recommendation_service: RecommendationService
    generation_service: GenerationService
    remix_service: RemixService
    agent_graph: AgentGraphBuilder


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)
    repository = Repository(conn)
    storage = LocalFileStorage(settings.storage_dir, settings.public_base_url)
    recommendation_service = RecommendationService(repository, settings=settings)
    state.repository = repository
    state.storage = storage
    state.profile_service = ProfileService(repository)
    state.recommendation_service = recommendation_service
    state.generation_service = GenerationService(
        repository=repository,
        storage=storage,
        provider=build_audio_provider(settings),
        normalizer=RequestNormalizer(),
        recommendation_service=recommendation_service,
        script_service=SleepScriptService(),
        settings=settings,
    )
    state.remix_service = RemixService(repository, storage)
    state.agent_graph = AgentGraphBuilder(
        repository=repository,
        storage=storage,
        normalizer=state.generation_service.normalizer,
        recommendation_service=recommendation_service,
        generation_service=state.generation_service,
        settings=settings,
        query_planner=build_query_planner(
            settings.query_planner,
            api_key=settings.query_planner_api_key,
            base_url=settings.query_planner_base_url,
            model=settings.query_planner_model,
            timeout_sec=settings.query_planner_timeout_sec,
            max_tokens=settings.query_planner_max_tokens,
        ),
        remix_service=state.remix_service,
    )
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


@app.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket):
    """Realtime full-duplex voice dialog.

    Protocol (see docs/contracts/voice_dialog_ws.md):
      - Client connects with ?token=<shared-secret> when FLOPPY_VOICE_WS_TOKEN is set.
      - Client sends binary frames = raw PCM (16k/mono/16bit) audio chunks.
      - Client sends text frame {"type":"stop"} to end the audio stream.
      - Server sends text frames for transcripts/assistant text/control, and
        binary frames for TTS audio (mp3 chunks).
    """
    settings = get_settings()
    token = websocket.query_params.get("token")
    if settings.voice_ws_token and token != settings.voice_ws_token:
        await websocket.close(code=4401)
        return
    await websocket.accept()

    # Lazy imports keep optional voice deps out of the core startup path.
    from floppy_backend.providers.minimax_stream_tts import MiniMaxStreamTTS
    from floppy_backend.providers.volc_asr import VolcStreamASR
    from floppy_backend.services.dialog_llm import DialogLLM
    from floppy_backend.services.voice_session import EVENT_AUDIO, OutboundEvent, VoiceSession

    try:
        session = VoiceSession(
            asr=VolcStreamASR(settings),
            llm=DialogLLM(settings),
            tts=MiniMaxStreamTTS(settings),
            voice_style=websocket.query_params.get("voice_style"),
        )
    except Exception as exc:  # noqa: BLE001 — config/credential errors
        await websocket.send_text(json.dumps({"type": "error", "text": str(exc)}))
        await websocket.close(code=1011)
        return

    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def _audio_in():
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                return
            yield chunk

    async def _emit(event: OutboundEvent) -> None:
        if event.type == EVENT_AUDIO and event.audio is not None:
            await websocket.send_bytes(event.audio)
        else:
            await websocket.send_text(
                json.dumps({"type": event.type, "text": event.text, "is_final": event.is_final}, ensure_ascii=False)
            )

    session_task = asyncio.create_task(session.run(_audio_in(), _emit))
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                await audio_queue.put(data)
            elif (text := message.get("text")) is not None:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if ctrl.get("type") == "stop":
                    await audio_queue.put(None)
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await audio_queue.put(None)
        try:
            await asyncio.wait_for(session_task, timeout=30)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            session_task.cancel()


@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    return DEMO_HTML


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

    response = state.agent_graph.run(AgentDecideRequest(user_id=demo_user, request_text=request_text, generation_allowed=True))
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
    return NormalizedRequestOut(normalized_request=normalized, cache_key=sha256_json(normalized.model_dump(mode="json")))


@app.post("/assets/search", response_model=AssetSearchResponse)
def search_audio_assets(request: AssetSearchRequest):
    response = state.recommendation_service.search(request)
    for result in response.results:
        result.asset.playback_url = state.storage.public_url(result.asset.object_key)
    return response


@app.get("/users/{user_id}/recommendations", response_model=list[Recommendation])
def recommend(user_id: str, limit: int = 5, query: str | None = None):
    recommendations = state.recommendation_service.recommend(user_id, limit=limit, query=query)
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
        response = state.agent_graph.run(req)
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
