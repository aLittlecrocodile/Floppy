"""Remix service: mix voice + ambient audio into a single output.

Triggered by user edit requests in conversation ("加点雨声背景", "背景音小一点").
NOT triggered by recommendation score thresholds.
Does NOT consume TTS generation quota.
Supports WAV native mixing and ffmpeg for mp3 foreground.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import wave
from pathlib import Path

from floppy_backend.models import AudioAssetIn, AudioType, MixParams
from floppy_backend.providers.ambient import detect_sound_type, generate_ambient_wav
from floppy_backend.repositories import Repository
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_text, stable_id, utcnow


class RemixError(RuntimeError):
    pass


class RemixService:
    def __init__(self, repository: Repository, storage: LocalFileStorage):
        self.repository = repository
        self.storage = storage

    def run_remix(self, job_id: str) -> None:
        job = self.repository.get_remix_job(job_id)
        if job is None:
            return
        try:
            self.repository.update_remix_job(job_id, status="processing")
            voice_asset = self.repository.get_asset(job.voice_asset_id)
            if voice_asset is None:
                raise RemixError("voice asset not found")

            voice_path = self.storage.existing_path_for(voice_asset.object_key)
            if not voice_path.exists():
                raise RemixError(f"voice audio file missing: {voice_asset.object_key}")

            # Handle remove_background: just copy foreground
            session = self.repository.get_remix_session(job_id)
            if session and session.intent == "remove_background":
                object_key = f"remix/{job_id}{voice_path.suffix}"
                output_path = self.storage.path_for(object_key)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(voice_path, output_path)
                self._finalize(job_id, voice_asset, output_path, object_key, [])
                return

            # Resolve ambient
            ambient_path: Path | None = None
            if job.ambient_asset_id:
                ambient_asset = self.repository.get_asset(job.ambient_asset_id)
                if ambient_asset is None:
                    raise RemixError("ambient asset not found")
                ambient_path = self.storage.existing_path_for(ambient_asset.object_key)
                if not ambient_path.exists():
                    raise RemixError(f"ambient audio file missing: {ambient_asset.object_key}")
            elif job.sound_type:
                duration_sec = self._get_duration(voice_path)
                ambient_path = self.storage.path_for(f"remix/_ambient_{job_id}.wav")
                ambient_path.parent.mkdir(parents=True, exist_ok=True)
                generate_ambient_wav(ambient_path, job.sound_type, duration_sec)

            if ambient_path is None:
                raise RemixError("no ambient source specified")

            # Determine mix params
            bg_vol = job.ambient_volume
            if session and session.mix_params:
                bg_vol = session.mix_params.background_volume

            # Choose mixing strategy based on foreground format
            is_mp3 = voice_path.suffix.lower() == ".mp3"
            ext = ".mp3" if is_mp3 else ".wav"
            object_key = f"remix/{job_id}{ext}"
            output_path = self.storage.path_for(object_key)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if is_mp3:
                _mix_ffmpeg(voice_path, ambient_path, output_path, job.voice_volume, bg_vol)
            else:
                _mix_wav(voice_path, ambient_path, output_path, job.voice_volume, bg_vol)

            extra_tags = [job.sound_type] if job.sound_type else []
            self._finalize(job_id, voice_asset, output_path, object_key, extra_tags)
        except Exception as e:
            self.repository.update_remix_job(job_id, status="failed", error_message=str(e)[:500])

    def _finalize(self, job_id: str, voice_asset, output_path: Path, object_key: str, extra_tags: list[str]) -> None:
        duration_sec = self._get_duration(output_path)
        tags = list(set(voice_asset.tags + extra_tags + ["remix"]))
        output_asset = self.repository.upsert_asset(AudioAssetIn(
            type=voice_asset.type,
            title=f"[Remix] {voice_asset.title}",
            object_key=object_key,
            duration_sec=duration_sec,
            voice_id=voice_asset.voice_id,
            prompt_hash=stable_id("rmx_hash", {"job_id": job_id}),
            content_hash=sha256_text(output_path.read_bytes()[:4096].hex()),
            mood_tags=list(voice_asset.mood_tags),
            tags=tags,
            user_segment_tags=voice_asset.user_segment_tags,
            quality_score=voice_asset.quality_score,
            embedding=voice_asset.embedding,
            created_by="remix",
        ))
        self.repository.update_remix_job(job_id, status="succeeded", output_asset_id=output_asset.id)

    def _get_duration(self, path: Path) -> int:
        if path.suffix.lower() == ".mp3":
            return _ffprobe_duration(path)
        return _wav_duration(path)


def _mix_ffmpeg(voice_path: Path, ambient_path: Path, output_path: Path, voice_vol: float, ambient_vol: float) -> None:
    """Mix using ffmpeg — supports mp3 foreground + wav/mp3 ambient."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_path),
        "-i", str(ambient_path),
        "-filter_complex",
        f"[0:a]volume={voice_vol}[fg];[1:a]aloop=loop=-1:size=2e+09,atrim=duration={_ffprobe_duration(voice_path)},volume={ambient_vol}[bg];[fg][bg]amix=inputs=2:duration=first:dropout_transition=3[out]",
        "-map", "[out]",
        "-ac", "1",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RemixError(f"ffmpeg failed: {result.stderr.decode()[:300]}")


def _ffprobe_duration(path: Path) -> int:
    """Get duration in seconds via ffprobe."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, text=True)
        return max(1, int(float(result.stdout.strip())))
    except (ValueError, subprocess.TimeoutExpired):
        return 20  # fallback


def _mix_wav(voice_path: Path, ambient_path: Path, output_path: Path, voice_vol: float, ambient_vol: float) -> None:
    voice_samples, params = _read_wav_samples(voice_path)
    if not voice_samples:
        raise RemixError("voice WAV is empty")
    ambient_samples, _ = _read_wav_samples(ambient_path)
    if not ambient_samples:
        raise RemixError("ambient WAV is empty")
    mixed = []
    for i, vs in enumerate(voice_samples):
        amb = ambient_samples[i % len(ambient_samples)]
        sample = int(vs * voice_vol + amb * ambient_vol)
        mixed.append(max(-32767, min(32767, sample)))
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(params[0])
        wav.setsampwidth(params[1])
        wav.setframerate(params[2])
        wav.writeframes(struct.pack(f"<{len(mixed)}h", *mixed))


def _read_wav_samples(path: Path) -> tuple[list[int], tuple[int, int, int]]:
    with wave.open(str(path), "rb") as wav:
        nchannels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        framerate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if sampwidth != 2:
        raise RemixError(f"Only 16-bit WAV supported, got {sampwidth * 8}-bit")
    samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    if nchannels == 2:
        samples = samples[::2]
    return samples, (1, 2, framerate)


def _wav_duration(path: Path) -> int:
    with wave.open(str(path), "rb") as wav:
        return max(1, wav.getnframes() // wav.getframerate())
