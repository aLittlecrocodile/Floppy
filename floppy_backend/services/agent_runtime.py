from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from floppy_backend.config import Settings
from floppy_backend.models import AgentDecideRequest, AgentDecideResponse
from floppy_backend.repositories import Repository
from floppy_backend.services.directive_planner import DirectivePlanner
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.recommendation import RecommendationService
from floppy_backend.services.remix import RemixService
from floppy_backend.storage import LocalFileStorage


class AgentRuntime(Protocol):
    def run(self, request: AgentDecideRequest) -> AgentDecideResponse:
        ...


@dataclass(frozen=True)
class AgentRuntimeDeps:
    repository: Repository
    storage: LocalFileStorage
    normalizer: RequestNormalizer
    recommendation_service: RecommendationService
    generation_service: GenerationService
    remix_service: RemixService
    settings: Settings
    directive_planner: DirectivePlanner | None


@dataclass(frozen=True)
class BuiltAgentRuntime:
    runtime: AgentRuntime
    local_agent: AgentRuntime | None


def build_agent_runtime(deps: AgentRuntimeDeps) -> BuiltAgentRuntime:
    """Build the configured agent runtime behind a stable run() interface."""
    settings = deps.settings
    local_agent = _build_local_agent(deps) if _needs_local_agent(settings) else None

    if settings.agent_runtime == "local":
        if local_agent is None:
            raise RuntimeError("local agent runtime was not built")
        return BuiltAgentRuntime(runtime=local_agent, local_agent=local_agent)

    if settings.agent_runtime == "hermes":
        from floppy_backend.services.hermes_agent import HermesAgentRuntime

        runtime = HermesAgentRuntime(
            repository=deps.repository,
            storage=deps.storage,
            normalizer=deps.normalizer,
            recommendation_service=deps.recommendation_service,
            generation_service=deps.generation_service,
            remix_service=deps.remix_service,
            settings=settings,
            local_agent=local_agent,
        )
        return BuiltAgentRuntime(runtime=runtime, local_agent=local_agent)

    raise RuntimeError(f"unsupported FLOPPY_AGENT_RUNTIME={settings.agent_runtime!r}")


def _needs_local_agent(settings: Settings) -> bool:
    return settings.agent_runtime == "local" or (
        settings.agent_runtime == "hermes" and settings.hermes_fallback_to_local
    )


def _build_local_agent(deps: AgentRuntimeDeps) -> AgentRuntime:
    from floppy_backend.services.agent_graph import AgentGraphBuilder
    from floppy_backend.services.query_planner import build_query_planner

    settings = deps.settings

    return AgentGraphBuilder(
        repository=deps.repository,
        storage=deps.storage,
        normalizer=deps.normalizer,
        recommendation_service=deps.recommendation_service,
        generation_service=deps.generation_service,
        settings=settings,
        query_planner=build_query_planner(
            settings.query_planner,
            api_key=settings.query_planner_api_key,
            base_url=settings.query_planner_base_url,
            model=settings.query_planner_model,
            timeout_sec=settings.query_planner_timeout_sec,
            max_tokens=settings.query_planner_max_tokens,
        ),
        remix_service=deps.remix_service,
        directive_planner=deps.directive_planner,
    )
