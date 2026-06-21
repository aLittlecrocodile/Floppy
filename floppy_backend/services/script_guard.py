"""Script safety and quality guard.

Catches high-stimulation, harmful, or medically irresponsible content before
a script reaches the TTS provider. Designed for sleep/ASMR content — extremely
low stimulation tolerance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Safety blocklists
# ---------------------------------------------------------------------------

# Each entry: (pattern, violation_code, description)
# Patterns are searched case-insensitively in the rendered script text.
_SAFETY_RULES: list[tuple[str, str, str]] = [
    # Terror / horror / sudden-shock
    (r"恐怖|鬼[魂故]|噩梦|惨叫|尖叫|怪物|僵尸|鲜血|血腥|死亡", "terror", "恐怖/惊吓内容"),
    (r"突然[爆炸发出]|巨响|爆炸|警报声", "sudden_shock", "突发高刺激事件"),
    # Violence
    (r"打架|殴打|攻击|刺伤|割破|枪|暴力|战争|战场", "violence", "暴力内容"),
    # Medical promises
    (r"治疗|治愈|临床|药物|诊断|医疗|cure|therapy|clinical", "medical_claim", "医疗声称"),
    (r"保证.{0,6}(睡着|入睡|入眠)|一定.{0,6}(睡着|入睡|入眠)", "medical_promise", "保证入睡承诺"),
    # High arousal / stress language
    (r"紧急|赶快|快跑|警告|危险|必须.{0,4}现在|不能等", "high_stress", "高压/紧急语言"),
    (r"兴奋|激动|刺激|热血|沸腾|澎湃", "high_arousal", "高唤醒情绪语言"),
    # Explicit content
    (r"色情|裸体|性感|情欲", "explicit", "不适宜内容"),
]

_SAFETY_RE = [(re.compile(pat, re.IGNORECASE), code, desc) for pat, code, desc in _SAFETY_RULES]

# ---------------------------------------------------------------------------
# Quality thresholds
# ---------------------------------------------------------------------------

MIN_CHARS = 80          # minimum readable Chinese chars for useful audio
MAX_CHARS = 1_800       # above this, cost-per-request > ~$0.18 at speech-2.8-hd
MIN_PAUSES = 3          # too few pauses → no room to breathe
MAX_SINGLE_PAUSE_SEC = 15   # a pause > 15s is likely a bug
COST_PER_CHAR_USD = 100 / 1_000_000  # speech-2.8-hd: $100 / 1M chars

# ---------------------------------------------------------------------------


class ScriptGuardError(ValueError):
    """Raised when a script must not be sent to the audio provider."""


@dataclass
class GuardResult:
    safe: bool
    quality_ok: bool
    violations: list[str] = field(default_factory=list)   # safety violation codes
    quality_notes: list[str] = field(default_factory=list)  # quality issue descriptions
    estimated_chars: int = 0
    estimated_duration_sec: int = 0
    estimated_cost_usd: float = 0.0

    @property
    def status(self) -> str:
        if not self.safe:
            return "blocked"
        if not self.quality_ok:
            return "low_quality"
        return "approved"

    @property
    def all_notes(self) -> list[str]:
        return self.violations + self.quality_notes


def _readable_chars(text: str) -> int:
    return sum(1 for c in text if "一" <= c <= "鿿" or c.isalnum())


def _parse_pauses(text: str) -> list[float]:
    pauses = []
    for segment in text.split("<#")[1:]:
        val = segment.split("#>", 1)[0]
        try:
            pauses.append(float(val))
        except ValueError:
            continue
    return pauses


def check(script_text: str, estimated_duration_sec: int) -> GuardResult:
    """Run all safety and quality checks on a rendered script string."""
    violations: list[str] = []
    quality_notes: list[str] = []

    # -- Safety checks
    for regex, code, desc in _SAFETY_RE:
        if regex.search(script_text):
            violations.append(f"{code}: {desc}")

    # -- Quality checks
    chars = _readable_chars(script_text)
    pauses = _parse_pauses(script_text)
    total_pause_sec = sum(pauses)

    if chars < MIN_CHARS:
        quality_notes.append(f"too_short: {chars} readable chars (min {MIN_CHARS})")
    if chars > MAX_CHARS:
        quality_notes.append(f"too_long: {chars} readable chars (max {MAX_CHARS}, cost risk)")
    if len(pauses) < MIN_PAUSES:
        quality_notes.append(f"too_few_pauses: {len(pauses)} (min {MIN_PAUSES})")
    for p in pauses:
        if p > MAX_SINGLE_PAUSE_SEC:
            quality_notes.append(f"oversized_pause: {p}s (max {MAX_SINGLE_PAUSE_SEC}s)")

    estimated_cost = chars * COST_PER_CHAR_USD

    return GuardResult(
        safe=len(violations) == 0,
        quality_ok=len(quality_notes) == 0,
        violations=violations,
        quality_notes=quality_notes,
        estimated_chars=chars,
        estimated_duration_sec=estimated_duration_sec,
        estimated_cost_usd=round(estimated_cost, 6),
    )
