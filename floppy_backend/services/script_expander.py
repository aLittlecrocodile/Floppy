"""Script expansion for target duration.

Stretches short TTS scripts toward their target duration by:
1. Inflating pause markers proportionally
2. Chapter-based expansion with sensory transitions
3. Increasing pause density toward the end for natural fade-out

For sleep/meditation content, varied transitions and progressive pauses
produce a more natural, less mechanical result.
"""
from __future__ import annotations

import re

PAUSE_RE = re.compile(r"<#(\d+(?:\.\d+)?)#>")

# --- Transition pools by content type ---

_MEDITATION_TRANSITIONS = [
    "吸气。<#5#>呼气。<#5#>",
    "感受身体的重量。<#4#>",
    "让每一次呼吸都更加深沉。<#5#>",
    "感受温暖从头顶缓缓流向全身。<#4#>",
    "放松你的肩膀。<#4#>呼气。<#5#>",
    "静静地感受此刻的宁静。<#6#>",
    "吸气。<#4#>让思绪随呼气慢慢散去。<#5#>",
    "感受大地在你身下稳固地支撑着你。<#4#>",
]

_STORY_TRANSITIONS = [
    "远处传来轻柔的声响。<#4#>",
    "空气中弥漫着淡淡的花香。<#5#>",
    "微风拂过，带来一丝凉意。<#4#>",
    "四周安静下来，只剩下轻微的呼吸声。<#5#>",
    "月光洒在地面上，像铺了一层银纱。<#4#>",
    "远处的星星一闪一闪，仿佛在低语。<#5#>",
    "树叶轻轻摇曳，发出沙沙的声音。<#4#>",
    "一切都变得柔和而宁静。<#5#>",
]

_PODCAST_TRANSITIONS = [
    "让我们稍作停顿。<#6#>",
    "接下来。<#4#>",
    "好，我们继续。<#4#>",
    "稍等片刻。<#5#>",
    "让这些内容沉淀一下。<#6#>",
    "回顾一下刚才的要点。<#5#>",
]
_TRANSITION_POOLS = {
    "meditation": _MEDITATION_TRANSITIONS,
    "story": _STORY_TRANSITIONS,
    "podcast_digest": _PODCAST_TRANSITIONS,
}


def estimate_script_duration(text: str) -> float:
    """Estimate spoken duration in seconds."""
    readable = sum(1 for c in text if "一" <= c <= "鿿" or c.isalnum())
    pauses = sum(float(m.group(1)) for m in PAUSE_RE.finditer(text))
    return readable / 3.2 + pauses


def expand_script(script_text: str, target_duration_sec: int, min_duration_sec: int | None = None) -> str:
    """Expand script to approach target_duration_sec (backward-compatible).

    Now targets 70% of target_duration_sec by default.
    """
    if not script_text:
        return script_text

    target = min_duration_sec or int(target_duration_sec * 0.7)
    current = estimate_script_duration(script_text)
    if current >= target:
        return script_text

    # Step 1: inflate pauses (cap multiplier at 4x, max pause 60s)
    ratio = target / current
    pause_mult = min(4.0, 1.0 + (ratio - 1.0) * 0.4)
    expanded = PAUSE_RE.sub(
        lambda m: f"<#{min(60, float(m.group(1)) * pause_mult):.0f}#>", script_text
    )

    current = estimate_script_duration(expanded)
    if current >= target:
        return expanded

    # Step 2: chapter-based expansion with story transitions as default
    expanded = _chapter_expand(expanded, target, _STORY_TRANSITIONS)

    # Step 3: inflate tail pauses for natural fade-out
    if estimate_script_duration(expanded) < target:
        expanded = _inflate_tail_pauses(expanded)

    return expanded


def expand_script_chapters(
    script_text: str, target_duration_sec: int, content_type: str = "story"
) -> str:
    """Enhanced chapter-based expansion with content-type-aware transitions.

    Args:
        script_text: The raw script with pause markers.
        target_duration_sec: Desired total duration in seconds.
        content_type: One of "story", "meditation", "podcast_digest".

    Returns:
        Expanded script targeting at least 70% of target_duration_sec.
    """
    if not script_text:
        return script_text

    target = int(target_duration_sec * 0.7)
    current = estimate_script_duration(script_text)
    if current >= target:
        return script_text

    transitions = _TRANSITION_POOLS.get(content_type, _STORY_TRANSITIONS)

    # Step 1: moderate pause inflation
    ratio = target / current
    pause_mult = min(3.5, 1.0 + (ratio - 1.0) * 0.35)
    expanded = PAUSE_RE.sub(
        lambda m: f"<#{min(45, float(m.group(1)) * pause_mult):.0f}#>", script_text
    )

    current = estimate_script_duration(expanded)
    if current >= target:
        return expanded

    # Step 2: chapter-based expansion
    expanded = _chapter_expand(expanded, target, transitions)

    # Step 3: increase pause density in last 30% of text
    expanded = _inflate_tail_pauses(expanded)

    return expanded


def _chapter_expand(text: str, target: float, transitions: list[str]) -> str:
    """Expand by inserting transitions between semantic chunks."""
    chunks = _split_sentences(text)
    if len(chunks) < 3:
        # Too short to split meaningfully; just inflate pauses more
        mult = min(5.0, target / max(1, estimate_script_duration(text)))
        return PAUSE_RE.sub(
            lambda m: f"<#{min(60, float(m.group(1)) * mult):.0f}#>", text
        )

    intro = chunks[0]
    outro = chunks[-1]
    body = chunks[1:-1]

    result_parts = [intro]
    trans_idx = 0

    # First pass: body with transitions inserted between chunks
    for i, chunk in enumerate(body):
        result_parts.append(chunk)
        # Insert transition after every 2-3 sentences
        if (i + 1) % 2 == 0 and i < len(body) - 1:
            result_parts.append(transitions[trans_idx % len(transitions)])
            trans_idx += 1

    result_parts.append(outro)
    result = "".join(result_parts)

    current = estimate_script_duration(result)
    if current >= target:
        return result

    # Second pass: add variation round with more transitions
    var_parts = [intro]
    for i, chunk in enumerate(body):
        var_parts.append(chunk)
        if (i + 1) % 2 == 0:
            var_parts.append(transitions[(trans_idx + i) % len(transitions)])

    result_parts_full = [result, f"<#{min(60, 15)}#>"]
    # Append variation body (not duplicating intro/outro)
    var_body = var_parts[1:]  # skip intro
    result_parts_full.extend(var_body)
    result = "".join(result_parts_full)

    current = estimate_script_duration(result)
    if current >= target:
        return result

    # Final pause inflation to close remaining gap
    final_mult = min(2.0, target / max(1, current))
    result = PAUSE_RE.sub(
        lambda m: f"<#{min(60, float(m.group(1)) * final_mult):.0f}#>", result
    )
    return result


def _inflate_tail_pauses(text: str) -> str:
    """Increase pause density in the last 30% of the text by 1.5x."""
    total_len = len(text)
    split_point = int(total_len * 0.7)
    head = text[:split_point]
    tail = text[split_point:]
    tail = PAUSE_RE.sub(
        lambda m: f"<#{min(60, float(m.group(1)) * 1.5):.0f}#>", tail
    )
    return head + tail


def _split_sentences(text: str) -> list[str]:
    """Split script into sentence chunks (preserving pause markers with preceding text)."""
    parts = re.split(r"(?<=[。？！；\n])(?=<#|$)", text)
    result = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if result and len(result[-1]) < 10 and not PAUSE_RE.search(result[-1]):
            result[-1] += p
        else:
            result.append(p)
    return result if result else [text]
