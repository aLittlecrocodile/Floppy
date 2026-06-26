from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from floppy_backend.config import Settings
from floppy_backend.models import AudioType, NormalizedAudioRequest
from floppy_backend.providers.audio import GeneratedAudio, GeneratedMusic, MiniMaxTTSProvider, ProviderAPIError
from floppy_backend.utils import sha256_text
from floppy_backend.voice_profiles import VOICE_PROFILES, resolve_voice_id


class HublessAudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioMeta:
    path: Path
    duration_sec: float
    format_name: str | None
    codec_name: str | None
    sample_rate: int | None
    channels: int | None
    bit_rate: int | None
    size_bytes: int

    def model_dump(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "duration_sec": self.duration_sec,
            "format_name": self.format_name,
            "codec_name": self.codec_name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bit_rate": self.bit_rate,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class HublessWorkflowResult:
    speech: GeneratedAudio
    music: GeneratedMusic
    mixed_path: Path
    mixed_object_key: str
    mixed_meta: AudioMeta
    music_prompt: str


BACKGROUND_MUSIC_PROMPTS = {
    "rain_soft": "soft gentle piano, lo-fi ambient, cozy rainy night, warm intimate atmosphere, very slow tempo, minimal, dreamy, reverb, no drums, no vocals",
    "ocean": "ambient pad synths, gentle harp arpeggios, slow ethereal, spacious, meditative, flowing, very slow tempo, minimal, no vocals",
    "forest_night": "soft flute melody, gentle strings, peaceful night forest, ambient, minimal, slow, woodland, no percussion, no vocals",
    "fireplace": "warm acoustic guitar fingerpicking, soft cello, cozy winter evening, intimate, gentle, very slow tempo, no vocals",
    "wind": "ambient drone, soft piano chords, ethereal pads, spacious, contemplative, very slow tempo, minimal, no vocals",
}


def build_sleep_music_prompt(normalized: NormalizedAudioRequest) -> str:
    base = BACKGROUND_MUSIC_PROMPTS.get(
        normalized.background,
        "deep ambient drone, very slow evolving pad, meditative, minimal, low stimulation, no vocals, no sudden changes",
    )
    intent_hint = {
        AudioType.ASMR: "asmr bed layer, sparse texture, whisper-safe, no melody jumps",
        AudioType.MEDITATION: "breathing meditation background, calm, spacious, grounded",
        AudioType.STORY: "bedtime story underscore, warm, simple, unobtrusive",
        AudioType.WHITE_NOISE: "steady sleep sound bed, minimal melodic movement",
        AudioType.MUSIC: "sleep music, very slow tempo, gentle, long reverb",
        AudioType.PODCAST_DIGEST: "quiet spoken-word underscore, subtle, not distracting",
    }.get(normalized.intent, "sleep audio background")
    topics = ", ".join(normalized.content_topic[:3])
    topic_hint = f", inspired by {topics}" if topics else ""
    return f"{base}, {intent_hint}{topic_hint}"


def probe_audio(path: Path) -> AudioMeta:
    if not path.exists():
        raise HublessAudioError(f"audio file not found: {path}")
    if not shutil.which("ffprobe"):
        raise HublessAudioError("ffprobe is required for audio_meta")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise HublessAudioError(f"ffprobe failed: {result.stderr[:300]}")

    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), streams[0] if streams else {})
    fmt = payload.get("format") or {}
    duration_raw = audio_stream.get("duration") or fmt.get("duration") or 0
    bit_rate_raw = audio_stream.get("bit_rate") or fmt.get("bit_rate")
    sample_rate_raw = audio_stream.get("sample_rate")
    return AudioMeta(
        path=path,
        duration_sec=max(0.0, float(duration_raw or 0)),
        format_name=fmt.get("format_name"),
        codec_name=audio_stream.get("codec_name"),
        sample_rate=int(sample_rate_raw) if sample_rate_raw else None,
        channels=int(audio_stream["channels"]) if audio_stream.get("channels") is not None else None,
        bit_rate=int(bit_rate_raw) if bit_rate_raw else None,
        size_bytes=path.stat().st_size,
    )


def ffmpeg_mix(
    foreground_path: Path,
    background_path: Path,
    output_path: Path,
    *,
    foreground_volume: float = 1.0,
    background_volume: float = 0.18,
    fade_out_sec: float = 8.0,
) -> AudioMeta:
    if not shutil.which("ffmpeg"):
        raise HublessAudioError("ffmpeg is required for ffmpeg_mix")

    duration = max(1.0, probe_audio(foreground_path).duration_sec)
    fade_start = max(0.0, duration - fade_out_sec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"[0:a]volume={foreground_volume}[fg];"
        f"[1:a]aloop=loop=-1:size=2147483647,atrim=duration={duration},"
        f"afade=t=out:st={fade_start}:d={fade_out_sec},volume={background_volume}[bg];"
        "[fg][bg]amix=inputs=2:duration=first:dropout_transition=3,"
        "alimiter=limit=0.95[out]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(foreground_path),
        "-i",
        str(background_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-ac",
        "1",
        "-b:a",
        "192k",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise HublessAudioError(f"ffmpeg failed: {result.stderr[:500]}")
    return probe_audio(output_path)


class MiniMaxHublessAudioTools:
    """MiniMax-Hub-free replacements for the audio MCP tools used by asmr-ambient."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = MiniMaxTTSProvider(settings)

    def get_voice_id(self, style_or_voice_id: str | None = None, *, refresh: bool = False, voice_type: str = "all") -> dict[str, Any]:
        if style_or_voice_id in VOICE_PROFILES:
            profile = resolve_voice_id(style_or_voice_id, self.settings.minimax_voice_id)
            return {"voice_id": profile["voice_id"], "source": "voice_profile", "profile": profile}
        if style_or_voice_id and style_or_voice_id.startswith(("Chinese ", "English_", "Japanese_", "Korean_")):
            return {"voice_id": style_or_voice_id, "source": "direct"}
        if not refresh:
            profile = resolve_voice_id(style_or_voice_id, self.settings.minimax_voice_id)
            return {"voice_id": profile["voice_id"], "source": "default_profile", "profile": profile}

        voices = self.provider.list_voices(voice_type=voice_type)
        query = (style_or_voice_id or "").lower()
        for bucket in ("system_voice", "voice_cloning", "voice_generation"):
            for voice in voices.get(bucket, []) or []:
                voice_id = str(voice.get("voice_id") or "")
                voice_name = str(voice.get("voice_name") or "")
                if not query or query in voice_id.lower() or query in voice_name.lower():
                    return {"voice_id": voice_id, "source": bucket, "voice": voice}
        raise ProviderAPIError(f"MiniMax voice not found: {style_or_voice_id}")

    def audio_generation(
        self,
        text: str,
        output_path: Path,
        object_key: str,
        *,
        voice_style: str | None = None,
        voice_id: str | None = None,
        title: str | None = None,
    ) -> GeneratedAudio:
        return self.provider.generate_text_to_file(
            text,
            output_path,
            object_key,
            voice_style=voice_style,
            voice_id=voice_id,
            title=title,
        )

    def audios_batch_generation(
        self,
        items: list[dict[str, Any]],
        output_dir: Path,
        *,
        object_key_prefix: str = "hubless/batch",
    ) -> list[GeneratedAudio]:
        results = []
        for index, item in enumerate(items, start=1):
            stem = item.get("name") or f"clip_{index:03d}"
            object_key = f"{object_key_prefix}/{stem}.mp3"
            output_path = output_dir / f"{stem}.mp3"
            results.append(
                self.audio_generation(
                    str(item["text"]),
                    output_path,
                    object_key,
                    voice_style=item.get("voice_style"),
                    voice_id=item.get("voice_id"),
                    title=item.get("title") or stem,
                )
            )
        return results

    def music_generation_instrumental(
        self,
        prompt: str,
        output_path: Path,
        object_key: str,
        *,
        title: str | None = None,
    ) -> GeneratedMusic:
        return self.provider.generate_instrumental_music(prompt, output_path, object_key, title=title)

    def audio_meta(self, path: Path) -> AudioMeta:
        return probe_audio(path)

    def ffmpeg_mix(
        self,
        foreground_path: Path,
        background_path: Path,
        output_path: Path,
        *,
        foreground_volume: float | None = None,
        background_volume: float | None = None,
    ) -> AudioMeta:
        return ffmpeg_mix(
            foreground_path,
            background_path,
            output_path,
            foreground_volume=foreground_volume if foreground_volume is not None else self.settings.minimax_voice_mix_volume,
            background_volume=background_volume if background_volume is not None else self.settings.minimax_music_mix_volume,
        )

    def asmr_ambient_workflow(
        self,
        script_text: str,
        work_dir: Path,
        *,
        title: str,
        normalized: NormalizedAudioRequest,
        voice_style: str | None = None,
        voice_id: str | None = None,
        object_key_prefix: str = "hubless/asmr",
    ) -> HublessWorkflowResult:
        work_dir.mkdir(parents=True, exist_ok=True)
        stem = sha256_text(f"{title}:{script_text}")[:16]
        speech = self.audio_generation(
            script_text,
            work_dir / f"{stem}_voice.mp3",
            f"{object_key_prefix}/{stem}_voice.mp3",
            voice_style=voice_style or normalized.voice_style,
            voice_id=voice_id,
            title=title,
        )
        music_prompt = build_sleep_music_prompt(normalized)
        music = self.music_generation_instrumental(
            music_prompt,
            work_dir / f"{stem}_music.mp3",
            f"{object_key_prefix}/{stem}_music.mp3",
            title=f"{title} background",
        )
        mixed_path = work_dir / f"{stem}_mixed.mp3"
        mixed_object_key = f"{object_key_prefix}/{stem}_mixed.mp3"
        mixed_meta = self.ffmpeg_mix(speech.path, music.path, mixed_path)
        return HublessWorkflowResult(
            speech=speech,
            music=music,
            mixed_path=mixed_path,
            mixed_object_key=mixed_object_key,
            mixed_meta=mixed_meta,
            music_prompt=music_prompt,
        )
