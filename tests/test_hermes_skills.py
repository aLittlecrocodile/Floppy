from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "hermes" / "skills" / "floppy"


def test_floppy_hermes_skill_docs_exist_and_name_core_tools():
    skills = {
        "floppy-sleep-audio": ["mcp_floppy_search_audio_assets", "mcp_floppy_generate_sleep_audio"],
        "floppy-voice-dialog": ["audio_workflow", "remix_current", "stop_audio"],
        "floppy-profile-context": ["mcp_floppy_get_user_profile_context", "mcp_floppy_update_profile_checkin"],
        "floppy-playback-control": ["mcp_floppy_start_playback", "mcp_floppy_get_active_playback"],
        "floppy-content-transform": ["mcp_floppy_generate_audio_from_upload", "podcast_digest"],
        "floppy-safety-quality": ["mcp_floppy_check_sleep_script_safety", '"status": "approved"'],
    }

    for skill_name, needles in skills.items():
        path = SKILL_DIR / skill_name / "SKILL.md"
        assert path.exists(), f"missing {skill_name}"
        text = path.read_text(encoding="utf-8")
        assert f"name: {skill_name}" in text
        for needle in needles:
            assert needle in text


def test_hermes_readme_registers_all_floppy_skills_and_tools():
    text = (ROOT / "hermes" / "README.md").read_text(encoding="utf-8")

    for skill_name in [
        "floppy-sleep-audio",
        "floppy-voice-dialog",
        "floppy-profile-context",
        "floppy-playback-control",
        "floppy-content-transform",
        "floppy-safety-quality",
    ]:
        assert skill_name in text

    for tool_name in [
        "get_user_profile_context",
        "start_playback",
        "get_active_playback",
        "generate_audio_from_upload",
        "check_sleep_script_safety",
    ]:
        assert tool_name in text
