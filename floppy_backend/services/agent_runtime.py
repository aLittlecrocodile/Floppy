from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from floppy_backend.config import Settings
from floppy_backend.models import AgentDecideRequest, AgentDecideResponse
from floppy_backend.repositories import Repository
from floppy_backend.services.asset_catalog import AssetCatalogService
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.request_defaults import RequestDefaults
from floppy_backend.services.remix import RemixService
from floppy_backend.storage import LocalFileStorage


class AgentRuntime(Protocol):
    def run(self, request: AgentDecideRequest) -> AgentDecideResponse:
        ...


@dataclass(frozen=True)
class AgentRuntimeDeps:
    repository: Repository
    storage: LocalFileStorage
    request_defaults: RequestDefaults
    asset_catalog_service: AssetCatalogService
    generation_service: GenerationService
    remix_service: RemixService
    settings: Settings


@dataclass(frozen=True)
class BuiltAgentRuntime:
    runtime: AgentRuntime


def build_agent_runtime(deps: AgentRuntimeDeps) -> BuiltAgentRuntime:
    """Build the Hermes agent runtime behind a stable run() interface."""
    settings = deps.settings
    if settings.agent_runtime != "hermes":
        raise RuntimeError(
            "FLOPPY_AGENT_RUNTIME only supports 'hermes'; "
            "the local LangGraph runtime has been removed"
        )

    from floppy_backend.services.hermes_agent import HermesAgentRuntime

    runtime = HermesAgentRuntime(
        repository=deps.repository,
        storage=deps.storage,
        request_defaults=deps.request_defaults,
        asset_catalog_service=deps.asset_catalog_service,
        generation_service=deps.generation_service,
        remix_service=deps.remix_service,
        settings=settings,
    )
    return BuiltAgentRuntime(runtime=runtime)
