from __future__ import annotations

import math
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

from floppy_backend.config import Settings
from floppy_backend.models import AudioType, NormalizedAudioRequest
from floppy_backend.providers.ambient import detect_sound_type, generate_ambient_wav
from floppy_backend.utils import sha256_text
from floppy_backend.voice_profiles import resolve_voice_id


@dataclass(frozen=True)
class GeneratedAudio:
    object_key: str
    path: Path
    duration_sec: int
    title: str
    content_hash: str
    provider_model: str | None = None
    provider_task_id: str | None = None
    provider_file_id: str | None = None
    provider_status: str | None = None
    provider_payload: dict | None = None
    usage_characters: int | None = None
    estimated_cost_usd: float | None = None


@dataclass(frozen=True)
class GeneratedMusic:
    object_key: str
    path: Path
    duration_sec: int
    title: str
    content_hash: str
    provider_model: str
    provider_status: str
    provider_payload: dict | None = None


class AudioGenerationProvider:
    name = "abstract"

    def generate(
        self,
        normalized: NormalizedAudioRequest,
        output_path: Path,
        object_key: str,
        *,
        script_text: str | None = None,
        title: str | None = None,
    ) -> GeneratedAudio:
        raise NotImplementedError


class LocalToneAudioProvider(AudioGenerationProvider):
    """Deterministic local WAV generator for integration testing.

    For white_noise/music: generates distinguishable procedural ambient audio.
    For other types: generates simple tones as placeholder.
    """

    name = "local_tone_v1"

    def __init__(self, delay_sec: float = 0.0, max_duration_sec: int | None = None):
        self.delay_sec = delay_sec
        self.max_duration_sec = max_duration_sec

    def generate(
        self,
        normalized: NormalizedAudioRequest,
        output_path: Path,
        object_key: str,
        *,
        script_text: str | None = None,
        title: str | None = None,
    ) -> GeneratedAudio:
        if self.delay_sec > 0:
            time.sleep(self.delay_sec)
        default_cap = 120 if normalized.intent.value in ("white_noise", "music") else 20
        duration_cap = min(default_cap, max(1, self.max_duration_sec)) if self.max_duration_sec else default_cap
        duration_sec = min(normalized.duration_sec, duration_cap)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Use procedural ambient for white_noise/music
        if normalized.intent.value in ("white_noise", "music"):
            sound_type = detect_sound_type(title or "", normalized.content_topic or [])
            generate_ambient_wav(output_path, sound_type, duration_sec)
        else:
            self._generate_tone(normalized, output_path, duration_sec)

        title = title or self._title(normalized)
        return GeneratedAudio(
            object_key=object_key,
            path=output_path,
            duration_sec=duration_sec,
            title=title,
            content_hash=sha256_text(output_path.read_bytes().hex()),
            provider_model="local_tone",
            provider_status="succeeded",
        )

    def _generate_tone(self, normalized: NormalizedAudioRequest, output_path: Path, duration_sec: int) -> None:
        sample_rate = 16_000
        base_frequency = self._frequency(normalized)
        amplitude = 6000
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for index in range(sample_rate * duration_sec):
                t = index / sample_rate
                envelope = min(1.0, index / sample_rate / 2.0, (sample_rate * duration_sec - index) / sample_rate / 2.0)
                sample = int(amplitude * envelope * math.sin(2 * math.pi * base_frequency * t))
                wav.writeframesraw(sample.to_bytes(2, byteorder="little", signed=True))

    def _frequency(self, normalized: NormalizedAudioRequest) -> float:
        by_intent = {
            "white_noise": 174.0,
            "music": 220.0,
            "asmr": 196.0,
            "story": 246.94,
            "meditation": 185.0,
            "podcast_digest": 207.65,
        }
        return by_intent.get(normalized.intent.value, 220.0)

    def _title(self, normalized: NormalizedAudioRequest) -> str:
        topics = "、".join(normalized.content_topic[:2]) if normalized.content_topic else "今晚"
        return f"{topics} {normalized.intent.value} · {normalized.background}"


def build_voice_setting(
    settings: Settings,
    *,
    voice_style: str | None = None,
    voice_id: str | None = None,
) -> dict:
    """Construct a MiniMax voice_setting dict from style/profile/config defaults.

    Shared by the HTTP T2A provider and the streaming WebSocket provider so both
    resolve voice_id/emotion/speed/pitch the same way.
    """
    if voice_id:
        profile = {"voice_id": voice_id, "speed": settings.minimax_speed, "emotion": settings.minimax_emotion}
    else:
        profile = resolve_voice_id(voice_style, settings.minimax_voice_id)
    voice_setting = {
        "voice_id": profile["voice_id"],
        "speed": profile.get("speed", settings.minimax_speed),
        "vol": settings.minimax_volume,
        "pitch": settings.minimax_pitch,
    }
    emotion = profile.get("emotion", settings.minimax_emotion)
    if emotion:
        voice_setting["emotion"] = emotion
    return voice_setting


def build_audio_setting(settings: Settings) -> dict:
    """Construct a MiniMax audio_setting dict (mp3) from config defaults."""
    return {
        "sample_rate": settings.minimax_sample_rate,
        "bitrate": settings.minimax_bitrate,
        "format": "mp3",
        "channel": settings.minimax_channel,
    }


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MiniMaxAsyncTask:
    task_id: str
    file_id: str | None
    task_token: str | None
    usage_characters: int | None
    provider_payload: dict


@dataclass(frozen=True)
class MiniMaxAsyncStatus:
    task_id: str
    status: str
    file_id: str | None
    provider_payload: dict


class MiniMaxTTSProvider(AudioGenerationProvider):
    name = "minimax_t2a"

    COST_PER_MILLION_CHARS = {
        "speech-2.8-turbo": 60.0,
        "speech-2.8-hd": 100.0,
        "speech-2.6-turbo": 60.0,
        "speech-2.6-hd": 100.0,
        "speech-02-turbo": 60.0,
        "speech-02-hd": 100.0,
    }

    def __init__(self, settings: Settings):
        if not settings.minimax_api_key:
            raise ProviderConfigurationError("FLOPPY_MINIMAX_API_KEY is required when FLOPPY_AUDIO_PROVIDER=minimax")
        self.settings = settings

    def generate(
        self,
        normalized: NormalizedAudioRequest,
        output_path: Path,
        object_key: str,
        *,
        script_text: str | None = None,
        title: str | None = None,
    ) -> GeneratedAudio:
        text = script_text or self._fallback_text(normalized)
        voice_style = normalized.voice_style if normalized else None
        if len(text) > self.settings.minimax_sync_max_chars:
            return self.generate_async_and_wait(normalized, output_path, object_key, script_text=text, title=title)

        payload = self._build_payload(text, voice_style=voice_style)
        response = self._post_json("/v1/t2a_v2", payload)
        base_resp = response.get("base_resp") or {}
        if base_resp.get("status_code") not in (0, None):
            self._raise_base_resp_error(base_resp, "MiniMax T2A request failed")

        audio_hex = ((response.get("data") or {}).get("audio") or "").strip()
        if not audio_hex:
            raise ProviderAPIError("MiniMax T2A response did not include audio data")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes.fromhex(audio_hex))
        extra = response.get("extra_info") or {}
        usage_characters = extra.get("usage_characters") or len(text)
        return GeneratedAudio(
            object_key=object_key,
            path=output_path,
            duration_sec=max(1, int((extra.get("audio_length") or 0) / 1000)),
            title=title or self._title(normalized),
            content_hash=sha256_text(output_path.read_bytes().hex()),
            provider_model=self.settings.minimax_model,
            provider_status="succeeded",
            provider_payload={
                "trace_id": response.get("trace_id"),
                "extra_info": extra,
                "base_resp": base_resp,
            },
            usage_characters=usage_characters,
            estimated_cost_usd=self.estimate_cost(usage_characters, self.settings.minimax_model),
        )

    def create_async_task(self, text: str, voice_style: str | None = None) -> MiniMaxAsyncTask:
        if len(text) > 50_000:
            raise ProviderConfigurationError("MiniMax async direct text supports up to 50,000 characters; upload text file for longer input")
        payload = self._build_payload(text, voice_style=voice_style)
        payload.pop("stream", None)
        payload.pop("output_format", None)
        payload["audio_setting"] = {
            "audio_sample_rate": self.settings.minimax_sample_rate,
            "bitrate": self.settings.minimax_bitrate,
            "format": "mp3",
            "channel": self.settings.minimax_channel,
        }
        response = self._post_json("/v1/t2a_async_v2", payload)
        base_resp = response.get("base_resp") or {}
        if base_resp.get("status_code") not in (0, None):
            self._raise_base_resp_error(base_resp, "MiniMax async task creation failed")
        task_id = str(response.get("task_id") or "")
        if not task_id:
            raise ProviderAPIError("MiniMax async response did not include task_id")
        file_id = response.get("file_id")
        return MiniMaxAsyncTask(
            task_id=task_id,
            file_id=str(file_id) if file_id is not None else None,
            task_token=response.get("task_token"),
            usage_characters=response.get("usage_characters"),
            provider_payload=self._safe_payload(response),
        )

    def query_async_task(self, task_id: str) -> MiniMaxAsyncStatus:
        response = self._get_json("/v1/query/t2a_async_query_v2", {"task_id": task_id})
        base_resp = response.get("base_resp") or {}
        if base_resp.get("status_code") not in (0, None):
            self._raise_base_resp_error(base_resp, "MiniMax async query failed")
        file_id = response.get("file_id")
        return MiniMaxAsyncStatus(
            task_id=str(response.get("task_id") or task_id),
            status=str(response.get("status") or "").lower(),
            file_id=str(file_id) if file_id is not None else None,
            provider_payload=self._safe_payload(response),
        )

    def retrieve_file_content(self, file_id: str) -> bytes:
        return self._get_bytes("/v1/files/retrieve_content", {"file_id": file_id})

    def generate_async_and_wait(
        self,
        normalized: NormalizedAudioRequest,
        output_path: Path,
        object_key: str,
        *,
        script_text: str,
        title: str | None = None,
    ) -> GeneratedAudio:
        voice_style = normalized.voice_style if normalized else None
        task = self.create_async_task(script_text, voice_style=voice_style)
        status = MiniMaxAsyncStatus(task_id=task.task_id, status="processing", file_id=task.file_id, provider_payload=task.provider_payload)
        for _ in range(self.settings.minimax_async_max_polls):
            time.sleep(self.settings.minimax_async_poll_interval_sec)
            status = self.query_async_task(task.task_id)
            if status.status in {"success", "failed", "expired"}:
                break
        if status.status != "success":
            raise ProviderAPIError(f"MiniMax async task ended with status={status.status or 'unknown'}")

        file_id = status.file_id or task.file_id
        if not file_id:
            raise ProviderAPIError("MiniMax async success response did not include file_id")
        audio_bytes = self.retrieve_file_content(file_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        usage_characters = task.usage_characters or len(script_text)
        # Async responses don't carry audio_length — probe the real duration
        # instead of estimating from text (long content is exactly this path,
        # and Hermes matches on duration).
        duration_sec = self._estimate_duration_from_text(script_text)
        try:
            from floppy_backend.services.minimax_hubless import probe_audio
            duration_sec = int(probe_audio(output_path).duration_sec) or duration_sec
        except Exception:  # noqa: BLE001 — ffprobe missing/unreadable file: keep estimate
            pass
        return GeneratedAudio(
            object_key=object_key,
            path=output_path,
            duration_sec=max(1, duration_sec),
            title=title or self._title(normalized),
            content_hash=sha256_text(output_path.read_bytes().hex()),
            provider_model=self.settings.minimax_model,
            provider_task_id=task.task_id,
            provider_file_id=file_id,
            provider_status=status.status,
            provider_payload={
                "task": task.provider_payload,
                "status": status.provider_payload,
            },
            usage_characters=usage_characters,
            estimated_cost_usd=self.estimate_cost(usage_characters, self.settings.minimax_model),
        )

    def list_voices(self, voice_type: str = "all") -> dict:
        response = self._post_json("/v1/get_voice", {"voice_type": voice_type})
        base_resp = response.get("base_resp") or {}
        if base_resp.get("status_code") not in (0, None):
            self._raise_base_resp_error(base_resp, "MiniMax get_voice request failed")
        return response

    def generate_text_to_file(
        self,
        text: str,
        output_path: Path,
        object_key: str,
        *,
        voice_style: str | None = None,
        voice_id: str | None = None,
        title: str | None = None,
        timeout: float | None = None,
    ) -> GeneratedAudio:
        if len(text) > self.settings.minimax_sync_max_chars and voice_id is None:
            normalized = NormalizedAudioRequest(
                intent=AudioType.STORY,
                duration_bucket="custom",
                duration_sec=self._estimate_duration_from_text(text),
                voice_style=voice_style or "warm_female",
                background="custom",
                mood=[],
                content_topic=[],
            )
            return self.generate_async_and_wait(normalized, output_path, object_key, script_text=text, title=title)

        payload = self._build_payload(text, voice_style=voice_style, voice_id=voice_id)
        response = self._post_json("/v1/t2a_v2", payload, timeout=timeout or 60)
        base_resp = response.get("base_resp") or {}
        if base_resp.get("status_code") not in (0, None):
            self._raise_base_resp_error(base_resp, "MiniMax T2A request failed")

        audio_hex = ((response.get("data") or {}).get("audio") or "").strip()
        if not audio_hex:
            raise ProviderAPIError("MiniMax T2A response did not include audio data")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes.fromhex(audio_hex))
        extra = response.get("extra_info") or {}
        usage_characters = extra.get("usage_characters") or len(text)
        return GeneratedAudio(
            object_key=object_key,
            path=output_path,
            duration_sec=max(1, int((extra.get("audio_length") or self._estimate_duration_from_text(text) * 1000) / 1000)),
            title=title or "MiniMax speech",
            content_hash=sha256_text(output_path.read_bytes().hex()),
            provider_model=self.settings.minimax_model,
            provider_status="succeeded",
            provider_payload={
                "trace_id": response.get("trace_id"),
                "extra_info": extra,
                "base_resp": base_resp,
            },
            usage_characters=usage_characters,
            estimated_cost_usd=self.estimate_cost(usage_characters, self.settings.minimax_model),
        )

    def generate_instrumental_music(
        self,
        prompt: str,
        output_path: Path,
        object_key: str,
        *,
        title: str | None = None,
        model: str | None = None,
    ) -> GeneratedMusic:
        music_model = model or self.settings.minimax_music_model
        payload = {
            "model": music_model,
            "prompt": prompt,
            "stream": False,
            "output_format": "hex",
            "is_instrumental": True,
            "audio_setting": {
                "sample_rate": self.settings.minimax_music_sample_rate,
                "bitrate": self.settings.minimax_music_bitrate,
                "format": "mp3",
            },
        }
        response = self._post_json("/v1/music_generation", payload, timeout=180)
        base_resp = response.get("base_resp") or {}
        if base_resp.get("status_code") not in (0, None):
            self._raise_base_resp_error(base_resp, "MiniMax music_generation request failed")

        data = response.get("data") or {}
        audio_hex = (data.get("audio") or "").strip()
        if not audio_hex:
            raise ProviderAPIError("MiniMax music_generation response did not include audio data")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes.fromhex(audio_hex))
        extra = response.get("extra_info") or {}
        return GeneratedMusic(
            object_key=object_key,
            path=output_path,
            duration_sec=max(1, int((extra.get("music_duration") or 0) / 1000)),
            title=title or "MiniMax instrumental music",
            content_hash=sha256_text(output_path.read_bytes().hex()),
            provider_model=music_model,
            provider_status="succeeded",
            provider_payload={
                "trace_id": response.get("trace_id"),
                "extra_info": extra,
                "analysis_info": response.get("analysis_info"),
                "base_resp": base_resp,
                "data_status": data.get("status"),
            },
        )

    def estimate_cost(self, usage_characters: int, model: str) -> float:
        price = self.COST_PER_MILLION_CHARS.get(model, 100.0)
        return round((usage_characters / 1_000_000) * price, 6)

    def _raise_base_resp_error(self, base_resp: dict, fallback_message: str) -> None:
        status_code = base_resp.get("status_code")
        status_msg = base_resp.get("status_msg") or fallback_message
        if "invalid api key" in status_msg.lower() and "minimax.io" in self.settings.minimax_base_url:
            status_msg += " (hint: Chinese-account keys require FLOPPY_MINIMAX_BASE_URL=https://api.minimaxi.com)"
        raise ProviderAPIError(status_msg, status_code=status_code)

    def _build_payload(self, text: str, voice_style: str | None = None, voice_id: str | None = None) -> dict:
        return {
            "model": self.settings.minimax_model,
            "text": text,
            "stream": False,
            "language_boost": "auto",
            "output_format": "hex",
            "voice_setting": build_voice_setting(self.settings, voice_style=voice_style, voice_id=voice_id),
            "audio_setting": build_audio_setting(self.settings),
        }

    # Transient failures worth one retry: rate limit, server errors, network blips.
    # Generation calls are idempotent (same text → same audio), so retrying is safe.
    _RETRYABLE_STATUS = {429, 500, 502, 503, 504}
    _RETRY_DELAY_SEC = 2.0

    def _post_json(self, path: str, payload: dict, timeout: float = 60) -> dict:
        url = f"{self.settings.minimax_base_url.rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.minimax_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if attempt == 1 and exc.code in self._RETRYABLE_STATUS:
                    time.sleep(self._RETRY_DELAY_SEC)
                    continue
                detail = exc.read().decode("utf-8", errors="replace")
                msg = f"MiniMax HTTP {exc.code}: {detail}"
                if exc.code == 401 and "minimax.io" in self.settings.minimax_base_url:
                    msg += " (hint: Chinese-account keys require FLOPPY_MINIMAX_BASE_URL=https://api.minimaxi.com)"
                raise ProviderAPIError(msg, status_code=exc.code) from exc
            except urllib.error.URLError as exc:
                if attempt == 1:
                    time.sleep(self._RETRY_DELAY_SEC)
                    continue
                raise ProviderAPIError(f"MiniMax request failed: {exc.reason}") from exc
        raise ProviderAPIError("MiniMax request failed after retry")  # unreachable

    def _get_json(self, path: str, params: dict[str, str]) -> dict:
        raw = urllib.parse.urlencode(params)
        url = f"{self.settings.minimax_base_url.rstrip('/')}{path}?{raw}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.settings.minimax_api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderAPIError(f"MiniMax HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except urllib.error.URLError as exc:
            raise ProviderAPIError(f"MiniMax request failed: {exc.reason}") from exc

    def _get_bytes(self, path: str, params: dict[str, str]) -> bytes:
        raw = urllib.parse.urlencode(params)
        url = f"{self.settings.minimax_base_url.rstrip('/')}{path}?{raw}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.settings.minimax_api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderAPIError(f"MiniMax HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except urllib.error.URLError as exc:
            raise ProviderAPIError(f"MiniMax request failed: {exc.reason}") from exc

    def _safe_payload(self, payload: dict) -> dict:
        safe = dict(payload)
        if "task_token" in safe:
            safe["task_token"] = "<redacted>"
        return safe

    def _estimate_duration_from_text(self, text: str) -> int:
        readable_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff" or char.isalnum())
        pause_seconds = 0.0
        for marker in text.split("<#")[1:]:
            value = marker.split("#>", 1)[0]
            try:
                pause_seconds += float(value)
            except ValueError:
                continue
        return int(max(1, readable_chars / 3.2 + pause_seconds))

    def _fallback_text(self, normalized: NormalizedAudioRequest) -> str:
        return f"今晚，听一段安静的{normalized.intent.value}。<#3#>慢慢放松。<#5#>"

    def _title(self, normalized: NormalizedAudioRequest) -> str:
        topics = "、".join(normalized.content_topic[:2]) if normalized.content_topic else "今晚"
        return f"{topics} {normalized.intent.value}"


def build_audio_provider(settings: Settings) -> AudioGenerationProvider:
    provider = settings.audio_provider.strip().lower()
    if provider in {"local", "local_tone"}:
        return LocalToneAudioProvider(delay_sec=settings.local_provider_delay_sec, max_duration_sec=settings.local_provider_max_duration_sec)
    if provider == "minimax":
        return MiniMaxTTSProvider(settings)
    raise ProviderConfigurationError(f"Unsupported FLOPPY_AUDIO_PROVIDER={settings.audio_provider!r}")
