"""Shared application state and dependency providers.

Lives outside main.py so router modules can reach the service singletons
without importing floppy_backend.main (which imports the routers, so that
direction would be a cycle).

`lifespan` intentionally stays in main.py: it also kicks off reply-TTS
prewarming, which depends on helpers defined there.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from floppy_backend.config import Settings
from floppy_backend.repositories import Repository
from floppy_backend.services.enterprise_search import EnterpriseSearchService
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.hermes_agent import HermesAgentRuntime
from floppy_backend.services.library import LibraryService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.profile import ProfileService
from floppy_backend.services.remix import RemixService
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
