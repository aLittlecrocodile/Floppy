"""Shared application state, dependency providers and app startup.

Lives outside main.py so router modules can reach the service singletons
without importing floppy_backend.main (which imports the routers, so that
direction would be a cycle).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI

from floppy_backend import showcase_skills
from floppy_backend.config import Settings, get_settings
from floppy_backend.db import connect, initialize
from floppy_backend.providers.audio import build_audio_provider
from floppy_backend.repositories import Repository
from floppy_backend.seed import seed_assets
from floppy_backend.services.enterprise_search import EnterpriseSearchService
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.hermes_agent import HermesAgentRuntime
from floppy_backend.services.library import LibraryService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.profile import ProfileService
from floppy_backend.services.remix import RemixService
from floppy_backend.services.script import SleepScriptService
from floppy_backend.services.weather import WeatherService
from floppy_backend.storage import LocalFileStorage

# Inline generation runs here so a sync endpoint can enforce a wall-clock
# budget (FIX: /voice/intent must answer inside the app's 60s timeout).
_generation_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="genjob")
# Small dedicated pool for reply TTS so a hung MiniMax call can't stall chat turns.
_reply_tts_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="replytts")


class AppState:
    repository: Repository
    storage: LocalFileStorage
    profile_service: ProfileService
    library: LibraryService
    generation_service: GenerationService
    remix_service: RemixService
    agent_runtime: HermesAgentRuntime
    settings: Settings
    normalizer: RequestNormalizer
    weather: WeatherService
    enterprise_search: EnterpriseSearchService


state = AppState()


def repo() -> Repository:
    return state.repository


def storage() -> LocalFileStorage:
    return state.storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    # services.reply_audio imports this module, so it can only be imported
    # once we're running — at import time that would be a cycle.
    from floppy_backend.services.reply_audio import notify_audio_url, reply_audio_url

    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)
    repository = Repository(conn)
    file_storage = LocalFileStorage(settings.storage_dir, settings.public_base_url)
    library = LibraryService(repository, file_storage, settings)
    state.repository = repository
    state.storage = file_storage
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
        storage=file_storage,
        provider=build_audio_provider(settings),
        normalizer=RequestNormalizer(),
        script_service=SleepScriptService(script_writer=script_writer),
        settings=settings,
        directive_planner=directive_planner,
    )
    state.remix_service = RemixService(repository, file_storage)
    state.settings = settings
    state.normalizer = state.generation_service.normalizer
    state.weather = WeatherService()
    state.enterprise_search = EnterpriseSearchService()
    state.agent_runtime = HermesAgentRuntime(
        repository=repository,
        storage=file_storage,
        normalizer=state.generation_service.normalizer,
        generation_service=state.generation_service,
        remix_service=state.remix_service,
        library=library,
        settings=settings,
        directive_planner=directive_planner,
        weather=state.weather,
        enterprise_search=state.enterprise_search,
    )
    # Seed the catalog once at startup (idempotent) so voice/demo requests
    # don't pay the ~60s seeding cost on their first call.
    try:
        seed_assets(repository, file_storage)
    except Exception:  # noqa: BLE001 — seeding is best-effort at startup
        pass
    # 预热兜底播报语音（固定文案），之后所有播报零延迟命中文件缓存
    _reply_tts_executor.submit(notify_audio_url)

    def _warm_demo_replies() -> None:
        for line in showcase_skills.DEMO_SPOKEN_LINES:
            try:
                reply_audio_url(line)
            except Exception:  # noqa: BLE001 — prewarm is best-effort
                pass

    _reply_tts_executor.submit(_warm_demo_replies)
    yield
    conn.close()
