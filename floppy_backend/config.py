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
    minimax_music_model: str = "music-2.6"
    minimax_music_sample_rate: int = 44100
    minimax_music_bitrate: int = 256000
    minimax_enable_music_mix: bool = False
    minimax_voice_mix_volume: float = 1.0
    minimax_music_mix_volume: float = 0.18
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

    # --- Realtime voice dialog ---
    # MiniMax streaming TTS (WebSocket)
    minimax_ws_url: str = "wss://api.minimaxi.com/ws/v1/t2a_v2"
    minimax_stream_model: str = "speech-2.6-turbo"
    # Volcengine streaming ASR (WebSocket)
    volc_asr_app_key: str | None = None
    volc_asr_access_key: str | None = None
    volc_asr_resource_id: str = "volc.bigasr.sauc.duration"
    volc_asr_ws_url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    volc_asr_sample_rate: int = 16000
    # Dialog LLM (reuses query_planner_* base_url/key/model unless overridden)
    dialog_llm_api_key: str | None = None
    dialog_llm_base_url: str | None = None
    dialog_llm_model: str | None = None
    dialog_max_tokens: int = 512
    dialog_temperature: float = 0.7
    dialog_history_max_turns: int = 8
    dialog_system_prompt: str = (
        "你是一个温柔、有耐心的助眠陪伴助手。用户正准备入睡，可能感到疲惫、焦虑或孤单。"
        "请用简短、轻柔、口语化的中文回应，每次回复控制在1-3句话以内，语气放松、舒缓，"
        "引导用户慢慢放松下来。不要使用列表、表情符号或书面化的长句。"
    )
    # /voice/ws shared-secret (PoC auth; replace with platform auth in prod)
    voice_ws_token: str | None = None

    model_config = SettingsConfigDict(env_prefix="FLOPPY_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
