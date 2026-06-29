from __future__ import annotations

import re

from floppy_backend.config import Settings
from floppy_backend.models import (
    AssetSearchFilters,
    AssetSearchRequest,
    AssetSearchResponse,
    AssetSearchResult,
    AudioAssetFacets,
    AudioAsset,
    AudioType,
    CatalogQueryAnalysis,
)
from floppy_backend.repositories import Repository
from floppy_backend.services.assets import is_placeholder_created_by


NON_VOICE_TYPES = {AudioType.WHITE_NOISE, AudioType.MUSIC}


class AssetCatalogService:
    """Deterministic catalog access for the agent and frontend.

    This service intentionally does not decide what the user wants. It exposes
    approved assets with lightweight lexical ordering so Hermes can make the
    actual workflow decision.
    """

    def __init__(self, repository: Repository, settings: Settings | None = None):
        self.repository = repository
        self._settings = settings

    def search(self, request: AssetSearchRequest) -> AssetSearchResponse:
        results: list[AssetSearchResult] = []
        seen_asset_ids: set[str] = set()

        if request.cache_key:
            exact = self.repository.get_asset_by_prompt_hash(request.cache_key)
            if exact and self._matches_filters(exact, request) and self._allow_exact_cache_asset(exact, request):
                results.append(
                    AssetSearchResult(
                        asset=exact,
                        score=1.0,
                        match_type="exact",
                        reasons=["exact cache asset"],
                    )
                )
                seen_asset_ids.add(exact.id)

        query_analysis = _catalog_query_analysis(request)
        candidates: list[AssetSearchResult] = []
        for asset in self.repository.list_assets():
            if asset.id in seen_asset_ids:
                continue
            if not self._matches_filters(asset, request):
                continue
            score, reasons = _catalog_match(asset, request)
            if request.query and not _filters_active(request.filters) and score <= 0:
                continue
            candidates.append(
                AssetSearchResult(
                    asset=asset,
                    score=round(score, 4),
                    match_type="catalog_match",
                    reasons=reasons or ["approved catalog asset"],
                )
            )

        candidates.sort(key=lambda item: (-item.score, self._asset_rank(item.asset), -item.asset.quality_score, item.asset.title))
        results.extend(candidates)
        results = results[: request.limit]
        best_score = results[0].score if results else None
        return AssetSearchResponse(
            results=results,
            hit=bool(results),
            best_score=best_score,
            threshold=0.0,
            query_analysis=query_analysis,
        )

    def facets(self, limit: int = 10) -> AudioAssetFacets:
        assets = self.repository.list_assets(limit=500)
        limit = max(0, min(limit, 50))

        def collect(field: str) -> list[str]:
            values: set[str] = set()
            for asset in assets:
                raw = getattr(asset, field)
                if isinstance(raw, list):
                    values.update(str(item) for item in raw if item)
                elif isinstance(raw, AudioType):
                    values.add(raw.value)
                elif raw:
                    values.add(str(raw))
            return sorted(values)

        return AudioAssetFacets(
            total_assets=len(assets),
            asset_types=collect("type"),
            mood_tags=collect("mood_tags"),
            tags=collect("tags"),
            voice_ids=collect("voice_id"),
            user_segment_tags=collect("user_segment_tags"),
            top_assets=assets[:limit],
        )

    def _matches_filters(self, asset: AudioAsset, request: AssetSearchRequest) -> bool:
        filters = request.filters
        asset_terms = _asset_terms(asset)
        if filters.type and asset.type != filters.type:
            return False
        if filters.required_tags and not set(filters.required_tags).issubset(asset_terms):
            return False
        if filters.mood_tags and not set(filters.mood_tags).intersection([*asset.mood_tags, *asset.user_segment_tags]):
            return False
        if filters.negative_tags and set(filters.negative_tags).intersection(asset_terms):
            return False
        if filters.min_duration_sec is not None and asset.duration_sec < filters.min_duration_sec:
            return False
        if filters.max_duration_sec is not None and asset.duration_sec > filters.max_duration_sec:
            return False
        return True

    def _allow_exact_cache_asset(self, asset: AudioAsset, request: AssetSearchRequest) -> bool:
        requested_type = request.filters.type
        if (requested_type in NON_VOICE_TYPES or asset.type in NON_VOICE_TYPES) and asset.created_by != "real_asset":
            return False
        return True

    def _asset_rank(self, asset: AudioAsset) -> int:
        if asset.type in NON_VOICE_TYPES:
            return 0 if asset.created_by == "real_asset" else 2
        return 1 if is_placeholder_created_by(asset.created_by) else 0


def _catalog_query_analysis(request: AssetSearchRequest) -> CatalogQueryAnalysis | None:
    filters = request.filters
    active_filters = _filters_active(filters)
    if not request.query and not active_filters:
        return None

    recognized = sorted(
        {
            *(filters.required_tags or []),
            *(filters.preferred_tags or []),
            *([filters.type.value] if filters.type else []),
        }
    )
    negative = sorted(set(filters.negative_tags or []))
    audio_type_values = {item.value for item in AudioType}
    excluded = sorted((AudioType(tag) for tag in negative if tag in audio_type_values), key=lambda item: item.value)
    no_voice = "no_voice" in recognized or "voice_present" in negative or any(tag in negative for tag in audio_type_values - {AudioType.WHITE_NOISE.value, AudioType.MUSIC.value})
    no_thunder = "thunder" in negative
    unknown_terms = [] if active_filters else [request.query.strip()[:80]] if request.query else []
    confidence = 1.0 if active_filters else 0.0
    return CatalogQueryAnalysis(
        recognized_tags=recognized,
        negative_tags=negative,
        excluded_types=excluded,
        hard_constraints={
            "required_tags": bool(filters.required_tags),
            "negative_tags": bool(filters.negative_tags),
            "no_voice": no_voice,
            "no_thunder": no_thunder,
        },
        unknown_terms=unknown_terms,
        confidence=confidence,
    )


def _catalog_match(asset: AudioAsset, request: AssetSearchRequest) -> tuple[float, list[str]]:
    filters = request.filters
    score = asset.quality_score
    reasons: list[str] = []
    if filters.required_tags:
        score += 0.2
        reasons.append(f"matches required tags: {', '.join(filters.required_tags[:4])}")
    preferred = sorted(set(filters.preferred_tags).intersection(_asset_terms(asset)))
    if preferred:
        score += min(0.12, 0.04 * len(preferred))
        reasons.append(f"matches preferred tags: {', '.join(preferred[:4])}")
    literal_matches = _literal_query_matches(asset, request.query or "")
    if literal_matches:
        score += min(0.12, 0.04 * len(literal_matches))
        reasons.append(f"literal match: {', '.join(literal_matches[:4])}")
    if not _filters_active(filters) and request.query and not literal_matches:
        return 0.0, []
    if asset.created_by == "real_asset" and asset.type in NON_VOICE_TYPES:
        score += 0.05
        reasons.append("real non-voice catalog asset")
    return score, reasons or ["approved catalog asset"]


def _asset_terms(asset: AudioAsset) -> set[str]:
    return {
        asset.type.value,
        asset.voice_id,
        *asset.tags,
        *asset.mood_tags,
        *asset.user_segment_tags,
    }


def _filters_active(filters: AssetSearchFilters) -> bool:
    return bool(
        filters.type
        or filters.mood_tags
        or filters.required_tags
        or filters.preferred_tags
        or filters.negative_tags
        or filters.min_duration_sec is not None
        or filters.max_duration_sec is not None
    )


def _literal_query_matches(asset: AudioAsset, query: str) -> list[str]:
    text = query.strip().lower()
    if not text:
        return []
    matches: list[str] = []
    title = asset.title.lower()
    if text == title:
        matches.append("title")
    tokens = set(re.findall(r"[a-z0-9_]+", text))
    tag_matches = sorted(tokens.intersection(_asset_terms(asset)))
    matches.extend(tag_matches)
    return matches
