"""Query Planner abstraction for AI-driven tag extraction.

The planner takes user request + profile context and outputs structured tags
for asset search. Default is rule-based fallback; AI planner enabled via
FLOPPY_QUERY_PLANNER=ai.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from floppy_backend.models import ProfileContext


@dataclass(frozen=True)
class StructuredQuery:
    preferred_tags: list[str] = field(default_factory=list)
    negative_tags: list[str] = field(default_factory=list)
    mood: list[str] = field(default_factory=list)
    duration_hint_sec: int | None = None
    confidence: float = 1.0
    source: str = "rule"  # "rule" | "ai" | "ai_fallback"
    reason_codes: list[str] = field(default_factory=list)


class QueryPlanner(Protocol):
    def plan(self, request_text: str, profile_context: ProfileContext, available_tags: set[str] | None = None) -> StructuredQuery: ...


class PlannerTruncatedError(RuntimeError):
    """Raised when LLM output is truncated (finish_reason=length) with no usable JSON."""
    pass


# ---------------------------------------------------------------------------
# Available tag taxonomy (shared between planners and validation)
# ---------------------------------------------------------------------------

AVAILABLE_TAGS: set[str] = {
    "rain", "ocean", "nature", "ambient", "no_voice", "minimal_voice",
    "voice_present", "voice_heavy", "warm_voice", "narrative",
    "gentle_story", "breathing", "grounding", "slow_pace",
    "high_pause_density", "low_stimulation", "high_energy", "suspense",
    "short_duration", "long_narrative",
}


# ---------------------------------------------------------------------------
# Rule-based fallback (deterministic, no external calls)
# ---------------------------------------------------------------------------

_SEGMENT_PREFERRED = {
    "anxiety_relief": ["low_stimulation", "breathing", "grounding", "slow_pace"],
    "companionship": ["warm_voice", "narrative", "gentle_story", "voice_present"],
    "environmental_sleep": ["ambient", "nature", "rain", "no_voice"],
    "quick_sleep": ["short_duration", "high_pause_density", "minimal_voice"],
    "content_transform": ["voice_present", "narrative", "slow_pace"],
    "balanced_sleep": ["low_stimulation", "ambient"],
}

_SEGMENT_NEGATIVE = {
    "anxiety_relief": ["high_energy", "suspense"],
    "companionship": ["no_voice"],
    "environmental_sleep": ["voice_heavy", "narrative"],
    "quick_sleep": ["long_narrative"],
}

_MOOD_TAG_MAP = {"anxiety_relief": "low_stimulation", "safe": "grounding", "gentle": "slow_pace", "calm": "low_stimulation"}


class RuleQueryPlanner:
    """Deterministic fallback planner using segment/mood maps."""

    def plan(self, request_text: str, profile_context: ProfileContext, available_tags: set[str] | None = None) -> StructuredQuery:
        segment = profile_context.algo_segment or profile_context.segment
        preferred: list[str] = list(_SEGMENT_PREFERRED.get(segment, []))
        negative: list[str] = list(_SEGMENT_NEGATIVE.get(segment, []))

        if profile_context.tonight_mood in ("anxious", "overthinking"):
            preferred.extend(["low_stimulation", "breathing", "grounding"])
            negative.extend(["suspense", "high_energy"])

        if profile_context.mood_tags:
            for m in profile_context.mood_tags:
                if m in _MOOD_TAG_MAP:
                    preferred.append(_MOOD_TAG_MAP[m])

        return StructuredQuery(
            preferred_tags=sorted(set(preferred)),
            negative_tags=sorted(set(negative)),
            mood=list(profile_context.mood_tags or []),
            confidence=1.0,
            source="rule",
            reason_codes=["rule_segment_map"],
        )


# ---------------------------------------------------------------------------
# AI Query Planner (real LLM implementation)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Output ONLY a JSON object. No explanation, no reasoning, no markdown.

Select audio tags for a sleep audio request from this allowed set: {tags}

JSON schema (output exactly this structure):
{{"preferred_tags":["tag1","tag2"],"negative_tags":["tag1"],"mood":["calm"],"duration_hint_sec":900,"confidence":0.85,"reason_codes":["extracted_from_request"]}}

Rules: preferred_tags 3-6 from allowed set. negative_tags 0-3 from allowed set. confidence 0.0-1.0."""


def _extract_json(text: str) -> dict:
    """Extract first JSON object from text, handling noise/fences."""
    import re
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first { ... } block
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text)
    if match:
        return json.loads(match.group(0))
    raise json.JSONDecodeError("No JSON object found", text, 0)


class AIQueryPlanner:
    """AI-backed planner calling OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "DeepSeek-V4-Flash", timeout_sec: float = 8.0, max_tokens: int = 5000):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_sec = timeout_sec
        self._max_tokens = max_tokens

    def plan(self, request_text: str, profile_context: ProfileContext, available_tags: set[str] | None = None) -> StructuredQuery:
        tags_set = available_tags or AVAILABLE_TAGS
        user_msg = self._build_user_message(request_text, profile_context)
        system_msg = _SYSTEM_PROMPT.format(tags=", ".join(sorted(tags_set)))

        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.1,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
        }

        url = f"{self._base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self._timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason", "")
        content = (choice["message"].get("content") or "").strip()
        if not content:
            # Some providers put output in reasoning_content
            content = (choice["message"].get("reasoning_content") or "").strip()
        if not content:
            if finish_reason == "length":
                raise PlannerTruncatedError(f"finish_reason=length with no parseable content (max_tokens={self._max_tokens})")
            raise ValueError("LLM returned empty content")

        try:
            parsed = _extract_json(content)
        except (json.JSONDecodeError, ValueError):
            if finish_reason == "length":
                raise PlannerTruncatedError(f"finish_reason=length, content not valid JSON (max_tokens={self._max_tokens})")
            raise

        return self._validate(parsed, tags_set)

    def _build_user_message(self, request_text: str, ctx: ProfileContext) -> str:
        return (
            f"User request: {request_text}\n"
            f"Segment: {ctx.algo_segment or ctx.segment}\n"
            f"Mood tags: {ctx.mood_tags}\n"
            f"Tonight mood: {ctx.tonight_mood or 'unknown'}\n"
            f"Audio preferences: {[t.value for t in ctx.audio_type_preferences]}\n"
            f"Duration pref: {ctx.duration_preference_min}min"
        )

    def _validate(self, parsed: dict, tags_set: set[str]) -> StructuredQuery:
        preferred = [t for t in parsed.get("preferred_tags", []) if t in tags_set]
        negative = [t for t in parsed.get("negative_tags", []) if t in tags_set]
        confidence = float(parsed.get("confidence", 0.5))
        mood = parsed.get("mood", [])
        duration = parsed.get("duration_hint_sec")
        reason_codes = parsed.get("reason_codes", ["ai_tag_extraction"])

        # If ALL tags were invalid, signal low confidence
        raw_preferred = parsed.get("preferred_tags", [])
        if raw_preferred and not preferred:
            confidence = 0.0
            reason_codes.append("all_tags_invalid")

        return StructuredQuery(
            preferred_tags=sorted(set(preferred)),
            negative_tags=sorted(set(negative)),
            mood=mood if isinstance(mood, list) else [],
            duration_hint_sec=int(duration) if duration else None,
            confidence=confidence,
            source="ai",
            reason_codes=reason_codes,
        )


def build_query_planner(planner_type: str = "rule", **kwargs) -> QueryPlanner:
    if planner_type == "ai":
        api_key = kwargs.get("api_key")
        if not api_key:
            raise RuntimeError("FLOPPY_QUERY_PLANNER_API_KEY required when FLOPPY_QUERY_PLANNER=ai")
        return AIQueryPlanner(
            api_key=api_key,
            base_url=kwargs.get("base_url", "https://api.openai.com/v1"),
            model=kwargs.get("model", "DeepSeek-V4-Flash"),
            timeout_sec=kwargs.get("timeout_sec", 8.0),
            max_tokens=kwargs.get("max_tokens", 5000),
        )
    return RuleQueryPlanner()
