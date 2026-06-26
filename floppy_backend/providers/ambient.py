"""Procedural ambient audio generator.

Generates distinguishable WAV files for white_noise and music catalog items
using different synthesis techniques per sound type. Not production quality,
but each item sounds clearly different for demo evaluation.
"""
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path


def generate_ambient_wav(output_path: Path, sound_type: str, duration_sec: int, sample_rate: int = 16000) -> None:
    """Generate a distinguishable ambient WAV for the given sound_type."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generator = GENERATORS.get(sound_type, _generate_pink_noise)
    samples = generator(duration_sec, sample_rate)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _generate_rain(duration_sec: int, sr: int) -> list[int]:
    rng = random.Random(42)
    n = sr * duration_sec
    samples = [0.0] * n
    # Pink-filtered base noise
    prev = 0.0
    for i in range(n):
        t = i / sr
        # Slow gust modulation (0.03-0.08 Hz combined)
        gust = 0.6 + 0.25 * math.sin(2 * math.pi * 0.04 * t) + 0.15 * math.sin(2 * math.pi * 0.07 * t)
        white = rng.gauss(0, 5000) * gust
        prev = 0.96 * prev + 0.04 * white
        # Low-frequency rumble
        rumble = 800 * math.sin(2 * math.pi * 40 * t + rng.gauss(0, 0.1))
        samples[i] = prev + rumble * gust
    # Drip transients with variable density
    num_drips = duration_sec * 12
    for _ in range(num_drips):
        pos = rng.randint(0, n - sr // 8)
        freq = rng.uniform(1500, 4000)
        amp = rng.uniform(1000, 3000)
        length = rng.randint(sr // 80, sr // 20)
        for j in range(min(length, n - pos)):
            env = (1.0 - j / length) ** 2
            samples[pos + j] += amp * env * math.sin(2 * math.pi * freq * j / sr)
    return _clip(_normalize([int(s) for s in samples], target_rms=3000, max_peak=22000))


def _generate_ocean(duration_sec: int, sr: int) -> list[int]:
    rng = random.Random(123)
    n = sr * duration_sec
    samples = [0.0] * n
    prev = 0.0
    prev2 = 0.0
    for i in range(n):
        t = i / sr
        # Slow surge cycle (0.05-0.12 Hz combined)
        surge = 0.3 + 0.5 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.06 * t)) + 0.2 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.11 * t))
        white = rng.gauss(0, 6000) * surge
        prev = 0.94 * prev + 0.06 * white
        # Deeper filter for low rumble
        prev2 = 0.99 * prev2 + 0.01 * white
        # Foam/spray bursts at wave peaks
        foam = 0.0
        if surge > 0.75:
            foam = rng.gauss(0, 3500) * (surge - 0.75) * 4
        samples[i] = prev + prev2 * 0.4 + foam
    return _clip(_normalize([int(s) for s in samples], target_rms=3000, max_peak=24000))


def _generate_stream(duration_sec: int, sr: int) -> list[int]:
    rng = random.Random(77)
    n = sr * duration_sec
    samples = [0.0] * n
    prev1 = prev2 = 0.0
    # Pre-generate irregular bubble events
    bubble_events = []
    t_pos = 0.0
    while t_pos < duration_sec:
        t_pos += rng.uniform(0.1, 0.6)
        freq = rng.uniform(8, 20)
        dur = rng.uniform(0.05, 0.2)
        amp = rng.uniform(400, 1200)
        bubble_events.append((t_pos, freq, dur, amp))
    # Occasional splashes
    splash_events = []
    for _ in range(duration_sec // 5):
        splash_events.append((rng.uniform(0, duration_sec), rng.uniform(1500, 2500)))
    for i in range(n):
        t = i / sr
        white = rng.gauss(0, 5000)
        prev1 = 0.7 * prev1 + 0.3 * white
        prev2 = 0.85 * prev2 + 0.15 * prev1
        # Irregular bubbles
        bubble = 0.0
        for bt, bf, bd, ba in bubble_events:
            dt = t - bt
            if 0 <= dt < bd:
                bubble += ba * math.sin(2 * math.pi * bf * dt) * (1 - dt / bd)
        # Splashes
        splash = 0.0
        for st, sa in splash_events:
            dt = t - st
            if 0 <= dt < 0.15:
                splash += sa * (1 - dt / 0.15) * rng.gauss(0, 1)
        samples[i] = prev2 + bubble + splash
    return _clip(_normalize([int(s) for s in samples], target_rms=3000, max_peak=22000))


def _generate_fire(duration_sec: int, sr: int) -> list[int]:
    rng = random.Random(55)
    n = sr * duration_sec
    samples = [0.0] * n
    prev = 0.0
    # Low continuous rumble base
    for i in range(n):
        t = i / sr
        white = rng.gauss(0, 3000)
        prev = 0.985 * prev + 0.015 * white
        rumble = 1500 * math.sin(2 * math.pi * 40 * t) + 1000 * math.sin(2 * math.pi * 55 * t)
        samples[i] = prev + rumble * 0.5
    # Clustered crackles: clusters then silence
    t_pos = 0.0
    while t_pos < duration_sec:
        # Cluster of crackles
        cluster_dur = rng.uniform(0.5, 2.0)
        num_crackles = rng.randint(3, 10)
        for _ in range(num_crackles):
            ct = t_pos + rng.uniform(0, cluster_dur)
            pos = int(ct * sr)
            if pos >= n:
                break
            amp = rng.uniform(1500, 4000)
            length = rng.randint(sr // 400, sr // 100)
            for j in range(min(length, n - pos)):
                env = (1.0 - j / length) ** 3
                samples[pos + j] += amp * env * (1 if rng.random() > 0.5 else -1)
        # Silence gap
        t_pos += cluster_dur + rng.uniform(1.0, 3.0)
    return _clip(_normalize([int(s) for s in samples], target_rms=3000, max_peak=22000))


def _generate_forest(duration_sec: int, sr: int) -> list[int]:
    rng = random.Random(99)
    n = sr * duration_sec
    samples = [0.0] * n
    prev = 0.0
    for i in range(n):
        t = i / sr
        # Very slow wind modulation (0.01-0.03 Hz)
        wind_mod = 0.4 + 0.35 * math.sin(2 * math.pi * 0.015 * t) + 0.25 * math.sin(2 * math.pi * 0.028 * t)
        white = rng.gauss(0, 2500) * wind_mod
        prev = 0.97 * prev + 0.03 * white
        # Subtle continuous crickets (3000-4500 Hz, very quiet)
        cricket = 400 * math.sin(2 * math.pi * 3800 * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 7 * t))
        samples[i] = prev + cricket
    # Bird chirps with trills and varied frequency
    for _ in range(duration_sec * 2):
        pos = rng.randint(0, n - sr)
        base_freq = rng.uniform(2000, 6000)
        chirp_len = rng.randint(sr // 16, sr // 5)
        # Trill: rapid on-off
        trill_rate = rng.uniform(15, 30)
        for j in range(min(chirp_len, n - pos)):
            tj = j / sr
            trill = 0.5 + 0.5 * math.sin(2 * math.pi * trill_rate * tj)
            env = (1.0 - j / chirp_len) * trill
            freq_sweep = base_freq + rng.uniform(-200, 200) * (j / chirp_len)
            samples[pos + j] += 2500 * env * math.sin(2 * math.pi * freq_sweep * tj)
    return _clip(_normalize([int(s) for s in samples], target_rms=3000, max_peak=24000))


def _generate_fan(duration_sec: int, sr: int) -> list[int]:
    rng = random.Random(33)
    n = sr * duration_sec
    samples = [0.0] * n
    # Pink noise base (dominant sound)
    b = [0.0] * 7
    for i in range(n):
        t = i / sr
        white = rng.gauss(0, 5000)
        b[0] = 0.99886 * b[0] + white * 0.0555179
        b[1] = 0.99332 * b[1] + white * 0.0750759
        b[2] = 0.96900 * b[2] + white * 0.1538520
        b[3] = 0.86650 * b[3] + white * 0.3104856
        b[4] = 0.55000 * b[4] + white * 0.5329522
        b[5] = -0.7616 * b[5] - white * 0.0168980
        pink = (b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + white * 0.5362) * 0.12
        b[6] = white * 0.115926
        # Subtle motor wobble (0.5-1 Hz)
        wobble = 1.0 + 0.06 * math.sin(2 * math.pi * 0.7 * t)
        # Very subtle 60/120 Hz hum
        hum = 200 * math.sin(2 * math.pi * 60 * t) + 100 * math.sin(2 * math.pi * 120 * t)
        samples[i] = pink * wobble + hum
    return _clip(_normalize([int(s) for s in samples], target_rms=3000, max_peak=22000))


def _generate_instrument(duration_sec: int, sr: int, notes: list[float], decay: float,
                         interval: float, seed: int, vibrato_hz: float = 0,
                         vibrato_depth: float = 0, breathy: float = 0,
                         harmonics: list[float] | None = None,
                         amp: float = 2000) -> list[int]:
    """Shared helper for music generators."""
    rng = random.Random(seed)
    harmonics = harmonics or [1.0, 0.3]
    n = sr * duration_sec
    samples = [0.0] * n
    # Schedule notes with random intervals
    note_starts = []
    t_pos = rng.uniform(0.5, 1.5)
    while t_pos < duration_sec - decay:
        note_starts.append((t_pos, notes[rng.randint(0, len(notes) - 1)]))
        t_pos += rng.uniform(interval * 0.7, interval * 1.3)
    for ns, freq in note_starts:
        start_i = int(ns * sr)
        note_len = int(decay * sr * 1.5)
        for j in range(min(note_len, n - start_i)):
            t = j / sr
            # Envelope
            env = math.exp(-j / (decay * sr))
            # Vibrato
            f = freq
            if vibrato_hz > 0:
                f += vibrato_depth * math.sin(2 * math.pi * vibrato_hz * t)
            # Harmonics
            val = 0.0
            for h_idx, h_amp in enumerate(harmonics):
                val += h_amp * math.sin(2 * math.pi * f * (h_idx + 1) * (ns + t))
            # Breathy noise
            if breathy > 0:
                val += rng.gauss(0, breathy) * env
            samples[start_i + j] += val * amp * env
    return [int(s) for s in samples]

def _generate_piano(duration_sec: int, sr: int) -> list[int]:
    # C4 D4 E4 G4 A4 C5 pentatonic
    notes = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25]
    samples = _generate_instrument(duration_sec, sr, notes, decay=4.0, interval=3.0,
                                   seed=10, harmonics=[1.0, 0.4, 0.15, 0.05], amp=4000)
    # Simple room reverb (feedback delay)
    n = len(samples)
    delay = int(0.08 * sr)
    for i in range(delay, n):
        samples[i] += int(samples[i - delay] * 0.25)
    return _clip(_normalize(samples, target_rms=2500, max_peak=18000))

def _generate_cello(duration_sec: int, sr: int) -> list[int]:
    # C3 G2 D3 A2 - low notes
    notes = [130.81, 98.00, 146.83, 110.00]
    rng = random.Random(20)
    n = sr * duration_sec
    samples = [0.0] * n
    harmonics = [1.0, 0.7, 0.5, 0.3, 0.15]
    # Long sustain notes with crossfade (legato)
    note_dur = rng.uniform(6.0, 8.0)
    t_pos = 0.5
    prev_end = 0
    while t_pos < duration_sec - 4:
        freq = notes[rng.randint(0, len(notes) - 1)]
        start_i = int(t_pos * sr)
        dur_samples = int(note_dur * sr)
        for j in range(min(dur_samples, n - start_i)):
            t = j / sr
            # Fade in/out for legato
            fade_in = min(1.0, j / (sr * 1.5))
            fade_out = min(1.0, (dur_samples - j) / (sr * 1.5))
            env = fade_in * fade_out
            # Strong vibrato (4-6 Hz, +/-3 Hz)
            vib = 3.0 * math.sin(2 * math.pi * 5.0 * t)
            f = freq + vib
            val = sum(h * math.sin(2 * math.pi * f * (k + 1) * (t_pos + t)) for k, h in enumerate(harmonics))
            samples[start_i + j] += val * 3500 * env
        t_pos += note_dur * 0.8  # Overlap for legato
        note_dur = rng.uniform(6.0, 8.0)
    return _clip(_normalize([int(s) for s in samples], target_rms=2500, max_peak=18000))


def _generate_guzheng(duration_sec: int, sr: int) -> list[int]:
    # Chinese pentatonic: D4 E4 G4 A4 D5 E5
    notes = [293.66, 329.63, 392.00, 440.00, 587.33, 659.25]
    rng = random.Random(30)
    harmonics = [1.0, 0.5, 0.3, 0.15]
    n = sr * duration_sec
    samples = [0.0] * n
    t_pos = 0.8
    while t_pos < duration_sec - 2:
        freq = notes[rng.randint(0, len(notes) - 1)]
        start_i = int(t_pos * sr)
        decay = 1.5
        note_len = int(decay * 3 * sr)
        # Quick grace note (brief note a step up, before main note)
        if rng.random() > 0.5:
            grace_freq = freq * 1.12
            grace_len = int(0.06 * sr)
            for j in range(min(grace_len, n - start_i)):
                t = j / sr
                env = 1.0 - j / grace_len
                val = sum(h * math.sin(2 * math.pi * grace_freq * (k + 1) * t) for k, h in enumerate(harmonics))
                samples[start_i + j] += val * 3000 * env
            start_i += grace_len
        # Main note
        for j in range(min(note_len, n - start_i)):
            t = j / sr
            env = math.exp(-j / (decay * sr))
            val = sum(h * math.sin(2 * math.pi * freq * (k + 1) * (t_pos + t)) for k, h in enumerate(harmonics))
            samples[start_i + j] += val * 3800 * env
        t_pos += rng.uniform(1.0, 3.0)
    return _clip(_normalize([int(s) for s in samples], target_rms=2500, max_peak=18000))


def _generate_guitar(duration_sec: int, sr: int) -> list[int]:
    # Nylon guitar: E3 A3 B3 E4 G#3 C#4
    notes = [164.81, 220.00, 246.94, 329.63, 207.65, 277.18]
    samples = _generate_instrument(duration_sec, sr, notes, decay=3.0, interval=2.0,
                                   seed=40, harmonics=[1.0, 0.8, 0.5, 0.2], amp=3500)
    return _clip(_normalize(samples, target_rms=2500, max_peak=18000))


def _generate_flute(duration_sec: int, sr: int) -> list[int]:
    # G5 A5 B5 D5 E5
    notes = [783.99, 880.00, 987.77, 587.33, 659.25]
    rng = random.Random(50)
    n = sr * duration_sec
    samples = [0.0] * n
    t_pos = 1.0
    while t_pos < duration_sec - 6:
        freq = notes[rng.randint(0, len(notes) - 1)]
        start_i = int(t_pos * sr)
        sustain = rng.uniform(4.0, 6.0)
        note_len = int(sustain * sr)
        for j in range(min(note_len, n - start_i)):
            t = j / sr
            # Gentle attack and release
            attack = min(1.0, j / (sr * 0.3))
            release = min(1.0, (note_len - j) / (sr * 0.5))
            env = attack * release
            # Slow vibrato (4 Hz, +/-2 Hz)
            f = freq + 2.0 * math.sin(2 * math.pi * 4.0 * t)
            val = math.sin(2 * math.pi * f * (t_pos + t))
            # Breathy noise component
            breath = rng.gauss(0, 0.3) * env
            samples[start_i + j] += (val + breath) * 3200 * env
        # Long pauses between phrases
        t_pos += sustain + rng.uniform(3.0, 6.0)
    return _clip(_normalize([int(s) for s in samples], target_rms=2500, max_peak=18000))


def _generate_strings(duration_sec: int, sr: int) -> list[int]:
    # Ensemble chords: C-E-G, A-C-E, F-A-C, G-B-D
    chords = [[261.63, 329.63, 392.00], [220.00, 261.63, 329.63],
              [174.61, 220.00, 261.63], [196.00, 246.94, 293.66]]
    rng = random.Random(60)
    n = sr * duration_sec
    samples = [0.0] * n
    hold_dur = 8.0
    crossfade = 2.0
    t_pos = 0.0
    chord_idx = 0
    while t_pos < duration_sec:
        chord = chords[chord_idx % len(chords)]
        start_i = int(t_pos * sr)
        total_len = int((hold_dur + crossfade) * sr)
        # Slight detuning per voice for ensemble width
        detunings = [rng.uniform(-0.8, 0.8) for _ in chord]
        for j in range(min(total_len, n - start_i)):
            t = j / sr
            fade_in = min(1.0, j / (crossfade * sr))
            fade_out = min(1.0, (total_len - j) / (crossfade * sr))
            env = fade_in * fade_out
            val = 0.0
            for fi, f in enumerate(chord):
                det_f = f + detunings[fi]
                val += math.sin(2 * math.pi * det_f * (t_pos + t))
            samples[start_i + j] += val * 2500 * env / len(chord)
        t_pos += hold_dur
        chord_idx += 1
    return _clip(_normalize([int(s) for s in samples], target_rms=2500, max_peak=18000))


def _generate_pink_noise(duration_sec: int, sr: int) -> list[int]:
    rng = random.Random(0)
    n = sr * duration_sec
    samples = [0] * n
    b = [0.0] * 7
    for i in range(n):
        white = rng.gauss(0, 3000)
        b[0] = 0.99886 * b[0] + white * 0.0555179
        b[1] = 0.99332 * b[1] + white * 0.0750759
        b[2] = 0.96900 * b[2] + white * 0.1538520
        b[3] = 0.86650 * b[3] + white * 0.3104856
        b[4] = 0.55000 * b[4] + white * 0.5329522
        b[5] = -0.7616 * b[5] - white * 0.0168980
        samples[i] = int((b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + white * 0.5362) * 0.11)
        b[6] = white * 0.115926
    return _clip(_normalize(samples, target_rms=3000, max_peak=22000))

def _clip(samples: list[int], limit: int = 30000) -> list[int]:
    return [max(-limit, min(limit, s)) for s in samples]


def _normalize(samples: list[int], target_rms: int = 3000, max_peak: int = 25000) -> list[int]:
    """Normalize samples to target RMS while keeping peak under max_peak."""
    n = len(samples)
    if n == 0:
        return samples
    rms = math.sqrt(sum(s * s for s in samples) / n)
    if rms < 1:
        return samples
    gain = target_rms / rms
    # Limit gain so peak doesn't exceed max_peak
    peak = max(abs(s) for s in samples)
    if peak * gain > max_peak:
        gain = max_peak / peak
    return [int(s * gain) for s in samples]


GENERATORS: dict[str, callable] = {
    "rain": _generate_rain,
    "ocean": _generate_ocean,
    "stream": _generate_stream,
    "fire": _generate_fire,
    "forest": _generate_forest,
    "fan": _generate_fan,
    "piano": _generate_piano,
    "cello": _generate_cello,
    "guzheng": _generate_guzheng,
    "guitar": _generate_guitar,
    "flute": _generate_flute,
    "strings": _generate_strings,
}


def detect_sound_type(title: str, tags: list[str]) -> str:
    """Detect which generator to use from title/tags."""
    text = title.lower() + " " + " ".join(tags)
    mapping = [
        ("雨", "rain"), ("rain", "rain"),
        ("海", "ocean"), ("浪", "ocean"), ("ocean", "ocean"),
        ("溪", "stream"), ("stream", "stream"),
        ("壁炉", "fire"), ("炉", "fire"), ("fire", "fire"),
        ("森林", "forest"), ("forest", "forest"), ("虫", "forest"),
        ("空调", "fan"), ("风扇", "fan"), ("fan", "fan"),
        ("钢琴", "piano"), ("piano", "piano"),
        ("大提琴", "cello"), ("cello", "cello"),
        ("古筝", "guzheng"), ("guzheng", "guzheng"),
        ("吉他", "guitar"), ("guitar", "guitar"),
        ("长笛", "flute"), ("笛", "flute"), ("flute", "flute"),
        ("弦乐", "strings"), ("小夜曲", "strings"), ("strings", "strings"),
    ]
    for keyword, sound in mapping:
        if keyword in text:
            return sound
    return "rain"

