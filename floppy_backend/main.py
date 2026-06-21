from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from floppy_backend.config import Settings, get_settings
from floppy_backend.db import connect, initialize
from floppy_backend.models import (
    EventIn,
    GenerationJob,
    GenerationJobCreateResponse,
    GenerationRequest,
    GenerationResponse,
    Recommendation,
    UserProfile,
    UserProfileIn,
)
from floppy_backend.providers.audio import build_audio_provider
from floppy_backend.repositories import Repository
from floppy_backend.seed import seed_assets
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.profile import ProfileService
from floppy_backend.services.recommendation import RecommendationService
from floppy_backend.services.script import SleepScriptService
from floppy_backend.storage import LocalFileStorage


class AppState:
    repository: Repository
    storage: LocalFileStorage
    profile_service: ProfileService
    recommendation_service: RecommendationService
    generation_service: GenerationService


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)
    repository = Repository(conn)
    storage = LocalFileStorage(settings.storage_dir, settings.public_base_url)
    recommendation_service = RecommendationService(repository)
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


@app.get("/users/{user_id}/recommendations", response_model=list[Recommendation])
def recommend(user_id: str, limit: int = 5, query: str | None = None):
    recommendations = state.recommendation_service.recommend(user_id, limit=limit, query=query)
    for item in recommendations:
        item.asset.playback_url = state.storage.public_url(item.asset.object_key)
    return recommendations


@app.post("/users/{user_id}/generate-audio", response_model=GenerationResponse)
def generate_audio(user_id: str, request: GenerationRequest):
    return state.generation_service.generate_or_match(user_id, request)


@app.post("/users/{user_id}/generation-jobs", response_model=GenerationJobCreateResponse, status_code=202)
def create_generation_job(user_id: str, request: GenerationRequest, background_tasks: BackgroundTasks):
    response = state.generation_service.enqueue_or_match(user_id, request)
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
