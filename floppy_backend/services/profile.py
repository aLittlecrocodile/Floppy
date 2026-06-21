from __future__ import annotations

from floppy_backend.models import ProfileLevel, UserProfileIn
from floppy_backend.repositories import Repository


class ProfileService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def upsert_profile(self, user_id: str, profile: UserProfileIn):
        segment = classify_segment(profile)
        return self.repository.upsert_profile(user_id, profile, segment)


def classify_segment(profile: UserProfileIn) -> str:
    audio_types = {item.value for item in profile.audio_type_preferences}
    if "podcast_digest" in audio_types:
        return "content_transform"
    if profile.stress_level == ProfileLevel.HIGH or profile.anxiety_level == ProfileLevel.HIGH:
        return "anxiety_relief"
    if "story" in audio_types or "asmr" in audio_types:
        return "companionship"
    if "white_noise" in audio_types or "music" in audio_types:
        return "environmental_sleep"
    if profile.avg_sleep_latency_min <= 15:
        return "quick_sleep"
    return "balanced_sleep"
