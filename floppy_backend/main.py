from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import time

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from floppy_backend.config import Settings, get_settings
from floppy_backend.db import connect, initialize
from floppy_backend.demo_page import DEMO_HTML
from floppy_backend.models import (
    AgentDecideRequest,
    AgentDecideResponse,
    AssetSearchRequest,
    AssetSearchResponse,
    AudioType,
    EventIn,
    GenerationBudget,
    GenerationJob,
    GenerationJobCreateResponse,
    GenerationRequest,
    GenerationResponse,
    NormalizeRequestIn,
    NormalizedRequestOut,
    ProfileCheckinIn,
    ProfileContext,
    ProfileLevel,
    Recommendation,
    UserProfile,
    UserProfileIn,
)
from floppy_backend.providers.audio import build_audio_provider
from floppy_backend.repositories import Repository
from floppy_backend.seed import seed_assets
from floppy_backend.services.generation import BudgetExceededError, GenerationService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.profile import ProfileService
from floppy_backend.services.query_planner import build_query_planner
from floppy_backend.services.recommendation import RecommendationService
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

    return {
        "action": response.action,
        "audio_url": audio_url,
        "asset": response.asset.model_dump(mode="json") if response.asset else (job.asset.model_dump(mode="json") if job and job.asset else None),
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
