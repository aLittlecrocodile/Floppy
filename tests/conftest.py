import pytest

from floppy_backend.config import Settings, get_settings


class TestSettings(Settings):
    """Settings that ignores .env file — avoids calling real APIs in tests."""
    agent_runtime: str = "hermes"
    local_provider_max_duration_sec: int | None = 1

    model_config = Settings.model_config.copy()
    model_config["env_file"] = None


@pytest.fixture(autouse=True)
def _use_test_settings(monkeypatch):
    """Override get_settings to use TestSettings (no .env), so tests use local audio and mocked Hermes."""
    monkeypatch.setenv("FLOPPY_DISABLE_LEGACY_ENV_FILE", "1")
    monkeypatch.setattr("floppy_backend.config.Settings", TestSettings)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
