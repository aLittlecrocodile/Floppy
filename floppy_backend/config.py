from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Floppy Backend MVP"
    database_path: Path = Path("data/floppy.db")
    storage_dir: Path = Path("storage/audio")
    public_base_url: str = "http://127.0.0.1:8000"
    seed_asset_count: int = 12
    local_provider_delay_sec: float = 0.0
    local_provider_max_duration_sec: int | None = None
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
    enforce_generation_budget: bool = False  # 关闭后不限制每日生成次数/字数（开发/预热用）
    daily_char_budget: int = 200_000
    daily_generate_count: int = 10
    # Shared OpenAI-compatible LLM config for lightweight text generation
    # around the Hermes runtime (chat replies and script writing).
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "DeepSeek-V4-Flash"
    llm_timeout_sec: float = 8.0

    # Agent runtime. Hermes is the only supported decision runtime.
    agent_runtime: str = "hermes"
    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_api_key: str | None = None
    hermes_model: str = "DeepSeek-V4-Flash"
    hermes_timeout_sec: float = 30.0
    hermes_store_conversation: bool = True

    # LLM script writer. Hermes supplies the directive; Floppy may turn it into
    # a voice script for spoken content. Disabled (templates only) when no key
    # is resolvable.
    script_writer_timeout_sec: float = 20.0
    script_writer_max_tokens: int = 2000

    # --- Realtime voice dialog ---
    # MiniMax streaming TTS (WebSocket)
    minimax_ws_url: str = "wss://api.minimaxi.com/ws/v1/t2a_v2"
    minimax_stream_model: str = "speech-2.6-turbo"
    # Volcengine streaming ASR (WebSocket)
    volc_asr_api_key: str | None = None           # 新版控制台：单 X-Api-Key
    volc_asr_app_key: str | None = None           # 旧版控制台：X-Api-App-Key (App ID)
    volc_asr_access_key: str | None = None        # 旧版控制台：X-Api-Access-Key (Access Token)
    volc_asr_resource_id: str = "volc.bigasr.sauc.duration"
    volc_asr_ws_url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    volc_asr_sample_rate: int = 16000
    # Dialog LLM (reuses LLM base_url/key/model unless overridden)
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
        "\n\n"
        "重要：当用户想听一段助眠音频（例如想听故事、冥想引导、雨声/海浪/白噪音、助眠音乐、"
        "播客等），请在回复的最开头单独输出一个标记 [AUDIO:类型]，类型只能是以下之一："
        "story（故事）、meditation（冥想/呼吸引导）、white_noise（雨声/海浪/自然白噪音）、"
        "music（助眠音乐）、podcast（播客/音频节目）。标记后紧跟一句温柔的引导语，"
        "例如：「[AUDIO:story]好的，给你放一段安静的助眠故事，慢慢闭上眼睛。」"
        "如果用户只是想聊天、倾诉或寻求安慰，不要输出任何标记，正常温柔回应即可。"
    )
    # /voice/ws shared-secret (PoC auth; replace with platform auth in prod)
    voice_ws_token: str | None = None

    model_config = SettingsConfigDict(env_prefix="FLOPPY_", env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def legacy_llm_api_key() -> str | None:
    return _legacy_env_value("FLOPPY_QUERY_PLANNER_API_KEY")


def _legacy_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    if os.environ.get("FLOPPY_DISABLE_LEGACY_ENV_FILE") == "1":
        return None
    env_path = Path(".env")
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        if key.strip() == name:
            value = raw_value.strip().strip("\"'")
            return value or None
    return None
