from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Floppy Backend MVP"
    database_path: Path = Path("data/floppy.db")
    storage_dir: Path = Path("storage/audio")
    public_base_url: str = "http://127.0.0.1:8000"
    seed_asset_count: int = 12
    local_provider_delay_sec: float = 0.0
    audio_provider: str = "local"
    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimaxi.com"
    minimax_model: str = "speech-2.8-hd"
    minimax_voice_id: str = "Chinese (Mandarin)_Warm_Bestie"
    minimax_speed: float = 0.85
    minimax_volume: float = 1.0
    minimax_pitch: int = 0
    minimax_emotion: str | None = "calm"
    minimax_sample_rate: int = 32000
    minimax_bitrate: int = 128000
    minimax_channel: int = 1
    minimax_sync_max_chars: int = 3000
    minimax_async_poll_interval_sec: float = 2.0
    minimax_async_max_polls: int = 60
    asset_hit_threshold: float = 0.58
    daily_char_budget: int = 200_000
    daily_generate_count: int = 10
    query_planner: str = "rule"  # "rule" | "ai"
    query_planner_confidence_threshold: float = 0.6
    query_planner_api_key: str | None = None
    query_planner_base_url: str = "https://api.openai.com/v1"
    query_planner_model: str = "DeepSeek-V4-Flash"
    query_planner_timeout_sec: float = 8.0
    query_planner_max_tokens: int = 5000

    model_config = SettingsConfigDict(env_prefix="FLOPPY_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
