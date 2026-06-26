"""Voice style -> MiniMax voice_id mapping.

Use POST /v1/get_voice with voice_type=system to query voices available to the
current account. These IDs were selected from the Mandarin system voices that
are available in the local MiniMax account used for the demo.
"""
from __future__ import annotations

# voice_style -> MiniMax voice_id
VOICE_PROFILES: dict[str, dict] = {
    "warm_female": {
        "voice_id": "Chinese (Mandarin)_Warm_Bestie",
        "speed": 0.85,
        "emotion": "calm",
    },
    "gentle_female": {
        "voice_id": "Chinese (Mandarin)_Soft_Girl",
        "speed": 0.80,
        "emotion": "calm",
    },
    "warm_male": {
        "voice_id": "Chinese (Mandarin)_Gentleman",
        "speed": 0.85,
        "emotion": "calm",
    },
    "storyteller_female": {
        "voice_id": "Chinese (Mandarin)_Wise_Women",
        "speed": 0.82,
        "emotion": "calm",
    },
    "storyteller_male": {
        "voice_id": "Chinese (Mandarin)_Radio_Host",
        "speed": 0.80,
        "emotion": "calm",
    },
    "podcast_male": {
        "voice_id": "Chinese (Mandarin)_Male_Announcer",
        "speed": 0.85,
        "emotion": None,
    },
    "podcast_female": {
        "voice_id": "Chinese (Mandarin)_News_Anchor",
        "speed": 0.85,
        "emotion": None,
    },
    "whisper_female": {
        "voice_id": "Chinese (Mandarin)_Warm_Girl",
        "speed": 0.75,
        "emotion": "calm",
    },
}

AVAILABLE_MANDARIN_VOICE_IDS = {item["voice_id"] for item in VOICE_PROFILES.values()}

DEFAULT_VOICE_STYLE = "warm_female"
CONFIRMED_MANDARIN_SYSTEM_VOICE_IDS = {
    "Chinese (Mandarin)_Reliable_Executive",
    "Chinese (Mandarin)_News_Anchor",
    "Chinese (Mandarin)_Mature_Woman",
    "Chinese (Mandarin)_Unrestrained_Young_Man",
    "Chinese (Mandarin)_Kind-hearted_Antie",
    "Chinese (Mandarin)_HK_Flight_Attendant",
    "Chinese (Mandarin)_Humorous_Elder",
    "Chinese (Mandarin)_Gentleman",
    "Chinese (Mandarin)_Warm_Bestie",
    "Chinese (Mandarin)_Male_Announcer",
    "Chinese (Mandarin)_Sweet_Lady",
    "Chinese (Mandarin)_Southern_Young_Man",
    "Chinese (Mandarin)_Wise_Women",
    "Chinese (Mandarin)_Gentle_Youth",
    "Chinese (Mandarin)_Warm_Girl",
    "Chinese (Mandarin)_Kind-hearted_Elder",
    "Chinese (Mandarin)_Cute_Spirit",
    "Chinese (Mandarin)_Radio_Host",
    "Chinese (Mandarin)_Lyrical_Voice",
    "Chinese (Mandarin)_Straightforward_Boy",
    "Chinese (Mandarin)_Sincere_Adult",
    "Chinese (Mandarin)_Gentle_Senior",
    "Chinese (Mandarin)_Stubborn_Friend",
    "Chinese (Mandarin)_Crisp_Girl",
    "Chinese (Mandarin)_Pure-hearted_Boy",
    "Chinese (Mandarin)_Soft_Girl",
}


def resolve_voice_id(voice_style: str | None, fallback_voice_id: str) -> dict:
    """Return voice settings dict for the given style, falling back to config default."""
    profile = VOICE_PROFILES.get(voice_style or DEFAULT_VOICE_STYLE)
    if profile:
        return profile
    return {"voice_id": fallback_voice_id, "speed": 0.85, "emotion": "calm"}
