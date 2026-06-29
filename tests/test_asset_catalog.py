from __future__ import annotations

from datetime import datetime, timezone

from floppy_backend.catalog import AUDIO_CATALOG
from floppy_backend.models import AssetSearchFilters, AssetSearchRequest, AudioAsset, AudioType
from floppy_backend.services.asset_catalog import AssetCatalogService
from floppy_backend.utils import text_embedding


def _asset(
    *,
    asset_id: str,
    title: str,
    audio_type: AudioType = AudioType.WHITE_NOISE,
    created_by: str,
    prompt_hash: str,
    quality_score: float,
    tags: list[str] | None = None,
) -> AudioAsset:
    return AudioAsset(
        id=asset_id,
        type=audio_type,
        title=title,
        object_key=f"{created_by}/{asset_id}.mp3",
        duration_sec=1200,
        language="zh-CN",
        voice_id="none" if audio_type in {AudioType.WHITE_NOISE, AudioType.MUSIC} else "warm_female",
        prompt_hash=prompt_hash,
        content_hash=f"content_{asset_id}",
        mood_tags=["calm"],
        tags=tags or [],
        sleep_stage="pre_sleep",
        user_segment_tags=["environmental_sleep"],
        safety_status="approved",
        quality_score=quality_score,
        embedding=text_embedding(f"{title} {' '.join(tags or [])}"),
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
    )


class FakeRepository:
    def __init__(self, exact: AudioAsset | None, assets: list[AudioAsset]):
        self._exact = exact
        self._assets = assets

    def get_asset_by_prompt_hash(self, prompt_hash: str) -> AudioAsset | None:
        return self._exact if self._exact and prompt_hash == self._exact.prompt_hash else None

    def list_assets(self, limit: int = 500) -> list[AudioAsset]:
        return self._assets[:limit]


def test_structured_filters_skip_ondemand_exact_cache_for_non_voice_assets():
    bad_cached = _asset(
        asset_id="aud_bad_tts_noise",
        title="持续雨声",
        created_by="ondemand",
        prompt_hash="same_white_noise_cache",
        quality_score=0.99,
        tags=["rain", "voice_present"],
    )
    real_rain = _asset(
        asset_id="aud_real_rain",
        title="夜雨轻敲",
        created_by="real_asset",
        prompt_hash="real_rain_catalog",
        quality_score=0.86,
        tags=["rain", "ambient", "no_voice"],
    )
    service = AssetCatalogService(FakeRepository(exact=bad_cached, assets=[bad_cached, real_rain]))

    result = service.search(
        AssetSearchRequest(
            user_id="u_demo",
            query="雨声白噪音",
            cache_key="same_white_noise_cache",
            filters=AssetSearchFilters(
                type=AudioType.WHITE_NOISE,
                required_tags=["rain", "no_voice"],
                negative_tags=["voice_present"],
            ),
            limit=3,
        )
    )

    assert result.results
    assert result.results[0].asset.id == "aud_real_rain"
    assert result.results[0].match_type != "exact"
    assert result.query_analysis is not None
    assert result.query_analysis.hard_constraints["no_voice"] is True


def test_structured_filters_keep_rain_noise_over_meditation_voice():
    real_rain = _asset(
        asset_id="aud_real_rain",
        title="夜雨轻敲",
        created_by="real_asset",
        prompt_hash="real_rain_catalog",
        quality_score=0.86,
        tags=["rain", "ambient", "no_voice"],
    )
    meditation = _asset(
        asset_id="aud_meditation_rain",
        title="呼吸觉察·雨夜版",
        audio_type=AudioType.MEDITATION,
        created_by="pregen_minimax",
        prompt_hash="meditation_rain",
        quality_score=0.95,
        tags=["rain", "breathing", "voice_present"],
    )
    meditation_music = _asset(
        asset_id="aud_meditation_music",
        title="小提琴冥想曲与长笛",
        audio_type=AudioType.MUSIC,
        created_by="real_asset",
        prompt_hash="music_meditation",
        quality_score=0.99,
        tags=["ambient", "no_voice"],
    )
    service = AssetCatalogService(FakeRepository(exact=None, assets=[meditation, meditation_music, real_rain]))

    result = service.search(
        AssetSearchRequest(
            user_id="u_demo",
            query="给我放雨声，不要冥想，不要人声",
            filters=AssetSearchFilters(
                type=AudioType.WHITE_NOISE,
                required_tags=["rain", "no_voice"],
                negative_tags=["voice_present", "meditation", "breathing"],
            ),
            limit=5,
        )
    )

    assert [item.asset.id for item in result.results] == ["aud_real_rain"]
    assert result.query_analysis is not None
    assert "rain" in result.query_analysis.recognized_tags
    assert "meditation" in result.query_analysis.negative_tags


def test_catalog_does_not_infer_chinese_intent_without_hermes_filters():
    real_rain = _asset(
        asset_id="aud_real_rain",
        title="夜雨轻敲",
        created_by="real_asset",
        prompt_hash="real_rain_catalog",
        quality_score=0.86,
        tags=["rain", "ambient", "no_voice"],
    )
    fan = _asset(
        asset_id="aud_fan",
        title="轻柔风扇",
        created_by="real_asset",
        prompt_hash="fan_catalog",
        quality_score=0.82,
        tags=["fan", "ambient", "no_voice"],
    )
    service = AssetCatalogService(FakeRepository(exact=None, assets=[real_rain, fan]))

    result = service.search(
        AssetSearchRequest(
            user_id="u_demo",
            query="给我放深舱噪音，不要人声",
            limit=5,
        )
    )

    assert result.results == []
    assert result.query_analysis is not None
    assert result.query_analysis.recognized_tags == []
    assert result.query_analysis.unknown_terms == ["给我放深舱噪音，不要人声"]
    assert result.query_analysis.hard_constraints["no_voice"] is False


def test_structured_filters_match_brown_noise_by_canonical_tag():
    brown_noise = _asset(
        asset_id="aud_brown_noise",
        title="棕噪低吟",
        created_by="real_asset",
        prompt_hash="brown_noise_catalog",
        quality_score=0.81,
        tags=["brown_noise", "ambient", "no_voice"],
    )
    real_rain = _asset(
        asset_id="aud_real_rain",
        title="夜雨轻敲",
        created_by="real_asset",
        prompt_hash="real_rain_catalog",
        quality_score=0.86,
        tags=["rain", "ambient", "no_voice"],
    )
    service = AssetCatalogService(FakeRepository(exact=None, assets=[real_rain, brown_noise]))

    result = service.search(
        AssetSearchRequest(
            user_id="u_demo",
            query="棕噪音",
            filters=AssetSearchFilters(
                type=AudioType.WHITE_NOISE,
                required_tags=["brown_noise", "no_voice"],
            ),
            limit=5,
        )
    )

    assert result.results
    assert result.results[0].asset.id == "aud_brown_noise"
    assert result.query_analysis is not None
    assert "brown_noise" in result.query_analysis.recognized_tags


def test_structured_filters_match_piano_without_generic_music_flood():
    piano = _asset(
        asset_id="aud_piano",
        title="肖邦钢琴夜曲集",
        audio_type=AudioType.MUSIC,
        created_by="real_asset",
        prompt_hash="piano_catalog",
        quality_score=0.85,
        tags=["piano", "ambient", "slow_pace", "no_voice"],
    )
    strings = _asset(
        asset_id="aud_strings",
        title="德沃夏克美国弦乐四重奏",
        audio_type=AudioType.MUSIC,
        created_by="real_asset",
        prompt_hash="strings_catalog",
        quality_score=0.86,
        tags=["strings", "ambient", "slow_pace", "no_voice"],
    )
    service = AssetCatalogService(FakeRepository(exact=None, assets=[strings, piano]))

    result = service.search(
        AssetSearchRequest(
            user_id="u_demo",
            query="钢琴轻音乐",
            filters=AssetSearchFilters(
                type=AudioType.MUSIC,
                required_tags=["piano", "no_voice"],
                preferred_tags=["ambient", "slow_pace"],
            ),
            limit=5,
        )
    )

    assert [item.asset.id for item in result.results] == ["aud_piano"]
    assert result.query_analysis is not None
    assert "piano" in result.query_analysis.recognized_tags


def test_catalog_facets_expose_current_resource_surface():
    rain = _asset(
        asset_id="aud_real_rain",
        title="夜雨轻敲",
        created_by="real_asset",
        prompt_hash="real_rain_catalog",
        quality_score=0.86,
        tags=["rain", "ambient", "no_voice"],
    )
    service = AssetCatalogService(FakeRepository(exact=None, assets=[rain]))

    facets = service.facets(limit=1)

    assert facets.total_assets == 1
    assert facets.asset_types == ["white_noise"]
    assert "rain" in facets.tags
    assert facets.top_assets[0].id == "aud_real_rain"


def test_mood_filter_can_match_user_segment_tags():
    rain = _asset(
        asset_id="aud_real_rain",
        title="夜雨轻敲",
        created_by="real_asset",
        prompt_hash="real_rain_catalog",
        quality_score=0.86,
        tags=["rain", "ambient", "no_voice"],
    )
    rain.mood_tags = ["calm", "safe"]
    rain.user_segment_tags = ["environmental_sleep", "anxiety_relief"]
    service = AssetCatalogService(FakeRepository(exact=None, assets=[rain]))

    result = service.search(
        AssetSearchRequest(
            user_id="u_demo",
            query="雨声",
            filters=AssetSearchFilters(
                type=AudioType.WHITE_NOISE,
                mood_tags=["anxiety_relief"],
                required_tags=["rain", "no_voice"],
            ),
            limit=5,
        )
    )

    assert [item.asset.id for item in result.results] == ["aud_real_rain"]


def test_seed_catalog_uses_clear_voice_tags():
    for item in AUDIO_CATALOG:
        tags = set(item["tags"])
        assert "minimal_voice" not in tags
        if item["audio_type"] in {"white_noise", "music"}:
            assert "no_voice" in tags
            assert "voice_present" not in tags
        else:
            assert "voice_present" in tags
            assert "no_voice" not in tags
