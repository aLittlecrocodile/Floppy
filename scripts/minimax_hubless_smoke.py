from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from floppy_backend.config import get_settings
from floppy_backend.models import AudioType, NormalizedAudioRequest
from floppy_backend.services.minimax_hubless import MiniMaxHublessAudioTools


def main() -> int:
    settings = get_settings()
    if not settings.minimax_api_key and not os.getenv("FLOPPY_MINIMAX_API_KEY"):
        print("missing env: FLOPPY_MINIMAX_API_KEY")
        return 2

    work_dir = Path("storage/hubless_smoke")
    normalized = NormalizedAudioRequest(
        intent=AudioType.ASMR,
        duration_bucket="short",
        duration_sec=120,
        voice_style="whisper_female",
        background="rain_soft",
        mood=["calm", "sleepy"],
        content_topic=["雨夜", "房间", "慢呼吸"],
    )
    script = (
        "现在，把注意力轻轻放在呼吸上。<#2#>"
        "窗外的雨声很慢，很轻。<#3#>"
        "你不需要努力，只要让肩膀慢慢放下来。<#4#>"
        "每一次呼气，都像把今天的声音放远一点。<#5#>"
    )

    tools = MiniMaxHublessAudioTools(settings)
    voice = tools.get_voice_id("whisper_female")
    result = tools.asmr_ambient_workflow(
        script,
        work_dir,
        title="雨夜慢呼吸",
        normalized=normalized,
        voice_style="whisper_female",
    )
    print("voice_id", voice["voice_id"])
    print("speech_path", result.speech.path)
    print("music_path", result.music.path)
    print("mixed_path", result.mixed_path)
    print("duration_sec", round(result.mixed_meta.duration_sec, 2))
    print("music_prompt", result.music_prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
