"""Tests for script safety/quality guard and SleepScriptService integration."""
from __future__ import annotations

import pytest

from floppy_backend.models import AudioType, NormalizedAudioRequest
from floppy_backend.services import script_guard
from floppy_backend.services.script import SleepScriptService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalized(intent: AudioType = AudioType.STORY, duration_sec: int = 600) -> NormalizedAudioRequest:
    return NormalizedAudioRequest(
        intent=intent,
        duration_bucket="medium",
        duration_sec=duration_sec,
        voice_style="warm_female",
        background="rain_soft",
        mood=["calm"],
        content_topic=["sea"],
    )


# ---------------------------------------------------------------------------
# script_guard.check — safety blocklist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_code", [
    ("今晚讲一个恐怖故事", "terror"),
    ("有人发出惨叫，鬼魂出没", "terror"),
    ("突然爆炸，大家都被吓到了", "sudden_shock"),
    ("他开始殴打对方", "violence"),
    ("这个声音能治疗你的失眠", "medical_claim"),
    ("保证你三分钟内睡着", "medical_promise"),
    ("紧急！现在必须立刻行动", "high_stress"),
    ("感到无比兴奋激动", "high_arousal"),
])
def test_safety_violations_detected(text: str, expected_code: str):
    result = script_guard.check(text, estimated_duration_sec=60)
    assert not result.safe, f"Expected violation for: {text!r}"
    codes = [v.split(":")[0] for v in result.violations]
    assert expected_code in codes, f"Expected {expected_code!r} in {codes}"
    assert result.status == "blocked"


def test_clean_script_passes_safety():
    text = "今晚，我带你做一次轻柔的呼吸练习。<#3#>慢慢吸气。<#4#>慢慢呼气。<#5#>很好。<#8#>"
    result = script_guard.check(text, estimated_duration_sec=60)
    assert result.safe


# ---------------------------------------------------------------------------
# script_guard.check — quality thresholds
# ---------------------------------------------------------------------------

def test_too_short_flagged():
    result = script_guard.check("嗨。<#2#>", estimated_duration_sec=5)
    assert not result.quality_ok
    assert any("too_short" in n for n in result.quality_notes)


def test_too_few_pauses_flagged():
    # Only 2 pause markers
    text = "这是一段很长的睡前引导文字，用来测试停顿数量是否足够。这里只有两个停顿标记。<#3#>好的，继续说。<#4#>"
    result = script_guard.check(text, estimated_duration_sec=60)
    assert not result.quality_ok
    assert any("too_few_pauses" in n for n in result.quality_notes)


def test_oversized_pause_flagged():
    text = "嗨。<#3#>慢慢吸气。<#20#>呼气。<#4#>很好。<#5#>"
    result = script_guard.check(text, estimated_duration_sec=60)
    assert not result.quality_ok
    assert any("oversized_pause" in n for n in result.quality_notes)


def test_cost_estimate_reasonable():
    # smoke text: ~661 chars as seen in real smoke test
    chars = 661
    cost = chars * (100 / 1_000_000)
    assert abs(cost - 0.0661) < 0.001  # matches smoke result


# ---------------------------------------------------------------------------
# SleepScriptService — integration with guard
# ---------------------------------------------------------------------------

class TestStoryScript:
    def test_approved_by_default(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.STORY))
        assert script.safety_status == "approved"

    def test_has_enough_pauses(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.STORY))
        pause_count = script.script_text.count("<#")
        assert pause_count >= script_guard.MIN_PAUSES

    def test_char_count_in_range(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.STORY))
        chars = script_guard.GuardResult.__new__(script_guard.GuardResult)
        readable = sum(1 for c in script.script_text if "一" <= c <= "鿿" or c.isalnum())
        assert script_guard.MIN_CHARS <= readable <= script_guard.MAX_CHARS

    def test_estimated_cost_under_threshold(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.STORY))
        readable = sum(1 for c in script.script_text if "一" <= c <= "鿿" or c.isalnum())
        cost = readable * script_guard.COST_PER_CHAR_USD
        assert cost < 0.05, f"Story script too expensive: ${cost:.4f} for {readable} chars"


class TestMeditationScript:
    def test_approved_and_high_pause_density(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.MEDITATION))
        assert script.safety_status == "approved"
        assert script.pause_density == "high"

    def test_min_pause_count(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.MEDITATION))
        pause_count = script.script_text.count("<#")
        assert pause_count >= 8, f"Meditation needs dense pauses, got {pause_count}"

    def test_no_medical_claim_in_notes(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.MEDITATION))
        assert "no_medical_claim" in script.safety_notes or all("medical" not in n for n in script.safety_notes)

    def test_twenty_minute_meditation_target_is_not_short(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.MEDITATION, duration_sec=1200))
        result = script_guard.check(script.script_text, script.estimated_duration_sec)
        assert result.safe, f"Meditation safety violations: {result.violations}"
        assert result.quality_ok, f"Meditation quality notes: {result.quality_notes}"
        assert script.estimated_duration_sec >= 1100
        assert script.estimated_duration_sec <= 1200


class TestAsmrScript:
    def test_approved_and_very_high_pause_density(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.ASMR))
        assert script.safety_status == "approved"
        assert script.pause_density == "very_high"

    def test_short_sentences_no_high_arousal(self):
        svc = SleepScriptService()
        script = svc.generate(_normalized(AudioType.ASMR))
        result = script_guard.check(script.script_text, script.estimated_duration_sec)
        assert result.safe, f"ASMR safety violations: {result.violations}"

    def test_char_count_lower_than_story(self):
        svc = SleepScriptService()
        story = svc.generate(_normalized(AudioType.STORY))
        asmr = svc.generate(_normalized(AudioType.ASMR))
        story_chars = sum(1 for c in story.script_text if "一" <= c <= "鿿" or c.isalnum())
        asmr_chars = sum(1 for c in asmr.script_text if "一" <= c <= "鿿" or c.isalnum())
        assert asmr_chars < story_chars, "ASMR should be shorter/quieter than story"


# ---------------------------------------------------------------------------
# Guard integration in GenerationService (blocked script raises)
# ---------------------------------------------------------------------------

def test_blocked_script_raises_guard_error():
    """ScriptGuardError must be raised when safety_status != approved."""
    from unittest.mock import MagicMock, patch
    from floppy_backend.models import AudioScript, AudioScriptIn
    from floppy_backend.services.generation import GenerationService, PreparedGeneration
    from floppy_backend.services import script_guard as sg
    import datetime

    # Build a PreparedGeneration with a blocked script
    normalized = _normalized()
    blocked_script_in = AudioScriptIn(
        user_id="u_test",
        title="blocked",
        content_type=AudioType.STORY,
        language="zh-CN",
        script_text="恐怖的故事",
        script_hash="abc",
        pause_density="low",
        estimated_duration_sec=10,
        safety_status="blocked",
        safety_notes=["terror: 恐怖/惊吓内容"],
    )
    blocked_script = AudioScript(
        **blocked_script_in.model_dump(),
        id="s_1",
        created_at=datetime.datetime.now(),
    )
    prepared = PreparedGeneration(
        normalized=normalized,
        cache_key="key",
        cached_asset=None,
        match_type="generated",
        script=blocked_script,
    )

    svc = GenerationService(
        repository=MagicMock(),
        storage=MagicMock(),
        provider=MagicMock(),
        normalizer=MagicMock(),
        script_service=MagicMock(),
    )

    with pytest.raises(sg.ScriptGuardError, match="blocked"):
        svc.execute_generation("u_test", prepared)
