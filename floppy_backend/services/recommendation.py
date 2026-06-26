from __future__ import annotations

from floppy_backend.config import Settings
from floppy_backend.models import AssetSearchRequest, AssetSearchResponse, AssetSearchResult, AudioAsset, Recommendation, UserProfile
from floppy_backend.repositories import Repository
from floppy_backend.services.assets import is_placeholder_created_by
from floppy_backend.utils import cosine_similarity, text_embedding


class RecommendationService:
    def __init__(self, repository: Repository, settings: Settings | None = None):
        self.repository = repository
        self._settings = settings

    @property
    def asset_hit_threshold(self) -> float:
        return self._settings.asset_hit_threshold if self._settings else 0.58

    def search(self, request: AssetSearchRequest) -> AssetSearchResponse:
        results: list[AssetSearchResult] = []
        seen_asset_ids: set[str] = set()

        if request.cache_key:
            exact = self.repository.get_asset_by_prompt_hash(request.cache_key)
            if exact and self._matches_filters(exact, request):
                results.append(AssetSearchResult(asset=exact, score=1.0, match_type="exact", reasons=["精确缓存命中"]))
                seen_asset_ids.add(exact.id)

        if request.query:
            preferred_tags = request.filters.preferred_tags or []
            negative_tags = request.filters.negative_tags or []
            for item in self.recommend(request.user_id, limit=max(request.limit * 3, request.limit), query=request.query, preferred_tags=preferred_tags, negative_tags=negative_tags):
                if item.asset.id in seen_asset_ids or not self._matches_filters(item.asset, request):
                    continue
                results.append(AssetSearchResult(asset=item.asset, score=item.score, match_type="asset_match", reasons=item.reasons))
                seen_asset_ids.add(item.asset.id)
                if len(results) >= request.limit:
                    break

        results = results[: request.limit]
        best_score = results[0].score if results else None
        hit = bool(results and (results[0].match_type == "exact" or results[0].score >= self.asset_hit_threshold))
        return AssetSearchResponse(results=results, hit=hit, best_score=best_score, threshold=self.asset_hit_threshold)

    def _matches_filters(self, asset: AudioAsset, request: AssetSearchRequest) -> bool:
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

    CANDIDATE_MIN_SCORE = 0.40

    def recommend(self, user_id: str, limit: int = 5, query: str | None = None, preferred_tags: list[str] | None = None, negative_tags: list[str] | None = None) -> list[Recommendation]:
        profile = self.repository.get_profile(user_id)
        assets = self.repository.list_assets()
        query_embedding = text_embedding(query or self._profile_text(profile))
        recommendations: list[Recommendation] = []
        for asset in assets:
            # Hard filter: negative_tags exclude
            if negative_tags and set(negative_tags).intersection(asset.tags):
                continue
            rec = self._score(asset, profile, query_embedding, preferred_tags=preferred_tags)
            if rec.score >= self.CANDIDATE_MIN_SCORE:
                recommendations.append(rec)
        # Prefer real assets over local placeholders once both clear the minimum score.
        recommendations.sort(key=lambda item: (is_placeholder_created_by(item.asset.created_by), -item.score))
        return recommendations[:limit]

    def nearest(self, query: str, limit: int = 5) -> list[Recommendation]:
        assets = self.repository.list_assets()
        query_embedding = text_embedding(query)
        recommendations = [self._score(asset, None, query_embedding) for asset in assets]
        recommendations = [r for r in recommendations if r.score >= self.CANDIDATE_MIN_SCORE]
        recommendations.sort(key=lambda item: (is_placeholder_created_by(item.asset.created_by), -item.score))
        return recommendations[:limit]

    def _score(self, asset: AudioAsset, profile: UserProfile | None, query_embedding: list[float], preferred_tags: list[str] | None = None) -> Recommendation:
        reasons: list[str] = []
        score = 0.0

        # Semantic: 0.35
        similarity = cosine_similarity(query_embedding, asset.embedding)
        score += similarity * 0.35
        if similarity > 0.2:
            reasons.append("语义相似")

        # Tag: 0.30
        asset_tags = set(asset.tags)
        if preferred_tags:
            matched_preferred = set(preferred_tags).intersection(asset_tags)
            if matched_preferred:
                tag_bonus = min(0.30, len(matched_preferred) * 0.06)
                score += tag_bonus
                reasons.append(f"标签命中: {', '.join(sorted(matched_preferred)[:3])}")

        # Quality: 0.20
        score += asset.quality_score * 0.20
        if asset.quality_score >= 0.8:
            reasons.append("质量评分高")

        # Profile: 0.15
        if profile:
            profile_score = 0.0
            preferred_types = {item.value for item in profile.audio_type_preferences}
            if asset.type.value in preferred_types:
                profile_score += 0.06
                reasons.append("匹配音频偏好")
            if profile.segment in asset.user_segment_tags:
                profile_score += 0.04
                reasons.append("匹配用户分层")
            if set(profile.mood_tags).intersection(asset.mood_tags):
                profile_score += 0.03
                reasons.append("匹配当晚情绪")
            if abs(asset.duration_sec / 60 - profile.duration_preference_min) <= 5:
                profile_score += 0.02
                reasons.append("匹配时长偏好")
            score += min(0.15, profile_score)

        if not reasons:
            reasons.append("通用睡前内容")
        return Recommendation(asset=asset, score=round(score, 4), reasons=reasons)

    def _profile_text(self, profile: UserProfile | None) -> str:
        if profile is None:
            return "calm sleep gentle night"
        return " ".join(
            [
                profile.segment,
                *[item.value for item in profile.audio_type_preferences],
                *profile.voice_preferences,
                *profile.background_preferences,
                *profile.mood_tags,
                profile.stress_level.value,
                profile.anxiety_level.value,
            ]
        )
