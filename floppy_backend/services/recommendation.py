from __future__ import annotations

from floppy_backend.models import AudioAsset, Recommendation, UserProfile
from floppy_backend.repositories import Repository
from floppy_backend.utils import cosine_similarity, text_embedding


class RecommendationService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def recommend(self, user_id: str, limit: int = 5, query: str | None = None) -> list[Recommendation]:
        profile = self.repository.get_profile(user_id)
        assets = self.repository.list_assets()
        query_embedding = text_embedding(query or self._profile_text(profile))
        recommendations = [self._score(asset, profile, query_embedding) for asset in assets]
        recommendations.sort(key=lambda item: item.score, reverse=True)
        return recommendations[:limit]

    def nearest(self, query: str, limit: int = 5) -> list[Recommendation]:
        assets = self.repository.list_assets()
        query_embedding = text_embedding(query)
        recommendations = [self._score(asset, None, query_embedding) for asset in assets]
        recommendations.sort(key=lambda item: item.score, reverse=True)
        return recommendations[:limit]

    def _score(self, asset: AudioAsset, profile: UserProfile | None, query_embedding: list[float]) -> Recommendation:
        reasons: list[str] = []
        score = 0.0

        similarity = cosine_similarity(query_embedding, asset.embedding)
        score += similarity * 0.35
        if similarity > 0.2:
            reasons.append("语义相似")

        score += asset.quality_score * 0.25
        if asset.quality_score >= 0.8:
            reasons.append("质量评分高")

        if profile:
            preferred_types = {item.value for item in profile.audio_type_preferences}
            if asset.type.value in preferred_types:
                score += 0.2
                reasons.append("匹配音频偏好")
            if profile.segment in asset.user_segment_tags:
                score += 0.15
                reasons.append("匹配用户分层")
            if set(profile.mood_tags).intersection(asset.mood_tags):
                score += 0.1
                reasons.append("匹配当晚情绪")
            if abs(asset.duration_sec / 60 - profile.duration_preference_min) <= 5:
                score += 0.05
                reasons.append("匹配时长偏好")

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
