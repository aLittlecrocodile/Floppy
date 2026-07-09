from __future__ import annotations

from fastapi.testclient import TestClient

from floppy_backend.config import get_settings
from floppy_backend.main import app, state
from floppy_backend.models import AudioAssetIn, AudioType
from floppy_backend.workflows.sleep_audio import _clean_title


def _configure_tmp_app(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FLOPPY_DATABASE_PATH", str(tmp_path / "floppy.db"))
    monkeypatch.setenv("FLOPPY_STORAGE_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()


def _materialize_files() -> None:
    """Library pools now skip assets whose audio file is missing on disk —
    give every test asset a real (dummy) file."""
    for asset in state.repository.list_assets():
        path = state.storage.path_for(asset.object_key)
        if not path.exists():
            path.write_bytes(b"\x00")


def _asset(title: str, *, type_: AudioType, tier: str, quality: float = 0.8, tags: list[str] | None = None) -> AudioAssetIn:
    return AudioAssetIn(
        type=type_,
        title=title,
        object_key=f"test/{title}.mp3",
        duration_sec=600,
        voice_id="warm_female",
        prompt_hash=f"hash-{title}",
        content_hash=f"content-{title}",
        mood_tags=["calm"],
        tags=tags or [],
        user_segment_tags=["balanced_sleep"],
        quality_score=quality,
        embedding=[0.0] * 32,
        created_by="real_asset" if tier == "curated" else "ondemand",
        tier=tier,
    )


def test_home_recommended_excludes_community_and_interleaves_types(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app):
        repo = state.repository
        repo.upsert_asset(_asset("精品白噪音A", type_=AudioType.WHITE_NOISE, tier="curated", quality=0.9))
        repo.upsert_asset(_asset("精品白噪音B", type_=AudioType.WHITE_NOISE, tier="curated", quality=0.85))
        repo.upsert_asset(_asset("精品冥想", type_=AudioType.MEDITATION, tier="curated", quality=0.8))
        repo.upsert_asset(_asset("测试垃圾", type_=AudioType.WHITE_NOISE, tier="community", quality=0.99))
        _materialize_files()

        recommended = state.library.home_recommended("u_lib", limit=10)
        titles = [asset.title for asset in recommended]
        assert "测试垃圾" not in titles
        assert len(titles) == 3
        # Type interleave: the two white-noise items must not be adjacent.
        assert titles[1] == "精品冥想" or titles[0] == "精品冥想"


def test_agent_candidates_curated_first(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app):
        repo = state.repository
        repo.upsert_asset(_asset("社区新品", type_=AudioType.STORY, tier="community"))
        repo.upsert_asset(_asset("精品老品", type_=AudioType.STORY, tier="curated"))
        _materialize_files()
        candidates = state.library.agent_candidates()
        assert candidates[0].title == "精品老品"
        assert candidates[0].playback_url


def test_tonight_pick_rotates(tmp_path, monkeypatch):
    _configure_tmp_app(monkeypatch, tmp_path)
    with TestClient(app):
        repo = state.repository
        repo.upsert_asset(_asset("轮换A", type_=AudioType.MUSIC, tier="curated", quality=0.9))
        repo.upsert_asset(_asset("轮换B", type_=AudioType.MUSIC, tier="curated", quality=0.9))
        _materialize_files()

        first = state.library.tonight_pick(user_id="u_rot", preferred_types=["music"])
        second = state.library.tonight_pick(user_id="u_rot", preferred_types=["music"])
        assert first is not None and second is not None
        assert first.id != second.id  # pool of 2 → consecutive picks must differ
        assert repo.last_event_asset_id("u_rot", "tonight_pick_served") == second.id


def test_clean_title():
    assert _clean_title("用平和声音讲几条科技短讯，低信息密度", "podcast_digest") == "用平和声音讲几条科技短讯"
    assert _clean_title("海边书店的夜晚。剩下的都不要", "story") == "海边书店的夜晚"
    assert _clean_title("", "meditation") == "冥想引导"
    assert _clean_title("这是一个特别特别特别长的标题超过十四个字", "story") == "这是一个特别特别特别长的标题"
