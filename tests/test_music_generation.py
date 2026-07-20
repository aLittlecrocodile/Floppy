from __future__ import annotations

from floppy_backend.config import Settings
from floppy_backend.db import connect, initialize
from floppy_backend.models import AudioType, GenerationRequest, UserProfileIn
from floppy_backend.providers.audio import GeneratedMusic
from floppy_backend.repositories import Repository
from floppy_backend.services.generation import GenerationService
from floppy_backend.services.hermes_agent import _explicit_generation_requested
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.storage import LocalFileStorage


class _InstrumentalMiniMaxProvider:
    name = "minimax_t2a"

    def __init__(self) -> None:
        self.music_calls: list[dict] = []

    def generate(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("pure music must not use text-to-speech")

    def generate_instrumental_music(self, prompt, output_path, object_key, *, title=None):  # noqa: ANN001
        self.music_calls.append({"prompt": prompt, "object_key": object_key, "title": title})
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-mp3")
        return GeneratedMusic(
            object_key=object_key,
            path=output_path,
            duration_sec=30,
            title=title or "instrumental",
            content_hash="music-hash",
            provider_model="music-2.6",
            provider_status="succeeded",
            provider_payload={"trace_id": "music-trace"},
        )


class _NoScriptForMusic:
    def generate(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("pure music must not create a spoken script")


def test_music_generation_uses_instrumental_provider_and_skips_speech(tmp_path):
    conn = connect(tmp_path / "floppy.db")
    initialize(conn)
    repository = Repository(conn)
    storage = LocalFileStorage(tmp_path / "audio", public_base_url="http://test")
    provider = _InstrumentalMiniMaxProvider()
    repository.upsert_profile(
        "showcase_user",
        UserProfileIn(audio_type_preferences=[AudioType.MEDITATION]),
        "balanced_sleep",
    )
    service = GenerationService(
        repository=repository,
        storage=storage,
        provider=provider,
        normalizer=RequestNormalizer(),
        script_service=_NoScriptForMusic(),  # type: ignore[arg-type]
        settings=Settings(minimax_api_key="test-key", audio_provider="minimax"),
    )

    response = service.generate_or_match(
        "showcase_user",
        GenerationRequest(request_text="给我生成一段钢琴曲", force_generate=True),
    )

    assert response.status == "succeeded"
    assert response.asset is not None
    assert response.asset.playback_url == f"http://test/audio/{response.asset.object_key}"
    assert storage.existing_path_for(response.asset.object_key).read_bytes() == b"fake-mp3"
    assert len(provider.music_calls) == 1
    assert "piano" in provider.music_calls[0]["prompt"]

    job = repository.get_generation_job(response.job_id)
    assert job is not None
    assert job.script is None
    assert job.provider_model == "music-2.6"
    workflow = job.provider_payload["workflow"]
    steps = {step["name"]: step["status"] for step in workflow["steps"]}
    assert steps == {
        "script": "skipped",
        "speech": "skipped",
        "music": "succeeded",
        "mix_audio": "skipped",
        "asset": "succeeded",
    }
    assert workflow["diagnostics"]["voice_object_key"] is None
    assert workflow["diagnostics"]["music_object_key"] == response.asset.object_key


def test_explicit_generation_detection_respects_negation():
    assert _explicit_generation_requested("给我生成一段钢琴曲") is True
    assert _explicit_generation_requested("不要生成，放一首现成的") is False
