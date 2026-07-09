"""Library engine — the rule-based half of the hybrid recommendation design.

Home lists and "tonight's pick" come from the curated pool (real recordings +
official prewarm generations) with millisecond-fast rule ranking; free-form
requests go through the Hermes agent runtime instead (hermes_agent.py), which
consumes this module's agent_candidates(). Replaces the legacy embedding-score
RecommendationService.
"""

from __future__ import annotations

import random

from floppy_backend.config import Settings
from floppy_backend.models import (
    AssetSearchRequest,
    AssetSearchResponse,
    AssetSearchResult,
    AudioAsset,
    EventIn,
    Recommendation,
    UserProfile,
)
from floppy_backend.repositories import Repository
from floppy_backend.services.assets import is_placeholder_created_by
from floppy_backend.storage import LocalFileStorage

TIER_CURATED = "curated"
TONIGHT_PICK_EVENT = "tonight_pick_served"


class LibraryService:
    def __init__(self, repository: Repository, storage: LocalFileStorage, settings: Settings):
        self._repo = repository
        self._storage = storage
        self._settings = settings

    # -- pools ---------------------------------------------------------------

    def _has_local_file(self, asset: AudioAsset) -> bool:
        """Cheap guard against stale DB rows: never surface an asset whose
        audio file is gone from local storage."""
        try:
            return self._storage.existing_path_for(asset.object_key).exists()
        except (ValueError, OSError):
            return False

    def _curated_pool(self) -> list[AudioAsset]:
        assets = [
            asset
            for asset in self._repo.list_assets(tier=TIER_CURATED)
            if not is_placeholder_created_by(asset.created_by)
            and "upload" not in asset.tags
            and self._has_local_file(asset)
        ]
        for asset in assets:
            asset.playback_url = self._storage.public_url(asset.object_key)
        return assets

    def agent_candidates(self) -> list[AudioAsset]:
        """Candidate catalog for the Hermes decision layer: curated first,
        newest-first within each tier, capped."""
        assets = [
            asset
            for asset in self._repo.list_assets()
            if not is_placeholder_created_by(asset.created_by) and self._has_local_file(asset)
        ]
        assets.sort(key=lambda asset: (asset.tier != TIER_CURATED, -asset.created_at.timestamp()))
        assets = assets[: self._settings.hermes_catalog_limit]
        for asset in assets:
            asset.playback_url = self._storage.public_url(asset.object_key)
        return assets

    # -- ranking -------------------------------------------------------------

    def _rule_score(self, asset: AudioAsset, profile: UserProfile | None) -> float:
        score = asset.quality_score
        if profile is None:
            return score
        preferred = [item.value for item in profile.audio_type_preferences]
        if asset.type.value in preferred:
            score += (0.15, 0.10, 0.05)[min(preferred.index(asset.type.value), 2)]
        if profile.segment in asset.user_segment_tags:
            score += 0.05
        if set(profile.mood_tags).intersection(asset.mood_tags):
            score += 0.05
        return score

    @staticmethod
    def _interleave_by_type(assets: list[AudioAsset]) -> list[AudioAsset]:
        """Round-robin across audio types so Home isn't a wall of one category."""
        buckets: dict[str, list[AudioAsset]] = {}
        for asset in assets:
            buckets.setdefault(asset.type.value, []).append(asset)
        order = sorted(buckets, key=lambda t: -buckets[t][0].quality_score)
        result: list[AudioAsset] = []
        idx = 0
        while any(buckets.values()):
            bucket = buckets[order[idx % len(order)]]
            if bucket:
                result.append(bucket.pop(0))
            idx += 1
        return result

    # -- public API ------------------------------------------------------------

    def home_recommended(self, user_id: str, limit: int = 10) -> list[AudioAsset]:
        profile = self._repo.get_profile(user_id)
        pool = self._curated_pool()
        pool.sort(key=lambda asset: -self._rule_score(asset, profile))
        return self._interleave_by_type(pool)[:limit]

    def tonight_pick(self, *, user_id: str, preferred_types: list[str]) -> AudioAsset | None:
        pool = self._curated_pool()
        if preferred_types:
            typed = [asset for asset in pool if asset.type.value in preferred_types]
            pool = typed or pool
        if not pool:
            return None
        last_served = self._repo.last_event_asset_id(user_id, TONIGHT_PICK_EVENT)
        fresh = [asset for asset in pool if asset.id != last_served] or pool
        fresh.sort(key=lambda asset: -asset.quality_score)
        pick = random.choice(fresh[:5])
        self._repo.record_event(
            user_id, EventIn(event_type=TONIGHT_PICK_EVENT, asset_id=pick.id, payload={"source": "library"})
        )
        return pick

    def recommend(self, user_id: str, limit: int = 5, query: str | None = None) -> list[Recommendation]:
        """Legacy GET /users/{id}/recommendations shape, backed by rule ranking."""
        profile = self._repo.get_profile(user_id)
        recommendations = [
            Recommendation(asset=asset, score=round(self._rule_score(asset, profile), 4), reasons=self._reasons(asset, profile))
            for asset in self._curated_pool()
        ]
        recommendations.sort(key=lambda item: -item.score)
        return recommendations[:limit]

    def search(self, request: AssetSearchRequest) -> AssetSearchResponse:
        """POST /assets/search — exact prompt_hash hit plus rule-filtered
        catalog results. Response shape unchanged (MCP proxy depends on it)."""
        results: list[AssetSearchResult] = []
        seen: set[str] = set()

        if request.cache_key:
            exact = self._repo.get_asset_by_prompt_hash(request.cache_key)
            if exact is not None and self._matches_filters(exact, request):
                exact.playback_url = self._storage.public_url(exact.object_key)
                results.append(AssetSearchResult(asset=exact, score=1.0, match_type="exact", reasons=["精确缓存命中"]))
                seen.add(exact.id)

        preferred_tags = set(request.filters.preferred_tags or [])
        scored: list[AssetSearchResult] = []
        for asset in self._repo.list_assets():
            if asset.id in seen or is_placeholder_created_by(asset.created_by):
                continue
            if not self._matches_filters(asset, request):
                continue
            tag_hits = len(preferred_tags.intersection(asset.tags))
            score = asset.quality_score + 0.06 * tag_hits + (0.1 if request.filters.type and asset.type == request.filters.type else 0.0)
            reasons = ["标签命中"] if tag_hits else ["目录匹配"]
            if asset.tier == TIER_CURATED:
                reasons.append("精品内容")
            asset.playback_url = self._storage.public_url(asset.object_key)
            scored.append(AssetSearchResult(asset=asset, score=round(min(score, 0.99), 4), match_type="asset_match", reasons=reasons))
        scored.sort(key=lambda item: (item.asset.tier != TIER_CURATED, -item.score))
        results.extend(scored[: max(0, request.limit - len(results))])

        best_score = results[0].score if results else None
        hit = bool(results and (results[0].match_type == "exact" or results[0].score >= self._settings.asset_hit_threshold))
        return AssetSearchResponse(results=results, hit=hit, best_score=best_score, threshold=self._settings.asset_hit_threshold)

    # -- helpers ---------------------------------------------------------------

    def _reasons(self, asset: AudioAsset, profile: UserProfile | None) -> list[str]:
        reasons: list[str] = []
        if asset.tier == TIER_CURATED:
            reasons.append("精品内容")
        if profile and asset.type in profile.audio_type_preferences:
            reasons.append("匹配音频偏好")
        if profile and set(profile.mood_tags).intersection(asset.mood_tags):
            reasons.append("匹配当晚情绪")
        return reasons or ["通用睡前内容"]

    @staticmethod
    def _matches_filters(asset: AudioAsset, request: AssetSearchRequest) -> bool:
        filters = request.filters
        if filters.type and asset.type != filters.type:
            return False
        if filters.mood_tags and not set(filters.mood_tags).intersection(asset.mood_tags):
            return False
        if filters.negative_tags and set(filters.negative_tags).intersection(asset.tags):
            return False
        if filters.min_duration_sec is not None and asset.duration_sec < filters.min_duration_sec:
            return False
        if filters.max_duration_sec is not None and asset.duration_sec > filters.max_duration_sec:
            return False
        return True
