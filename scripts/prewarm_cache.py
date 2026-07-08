#!/usr/bin/env python3
"""预热缓存：把 catalog 里的 meditation/story/podcast 条目用"智能体指挥 workflow"
的同一条路径生成真人声音频并入库，作为缓存。

为什么走这条路径而不是直接用 catalog 的 script_text：
  - cache_key 必须与线上真实请求（agent_graph → enqueue_or_match）一致，否则用户
    问同样的需求时命中不了。这里复用 GenerationService.enqueue_or_match + run_job，
    并为每条用 DirectivePlanner 产出 directive（内容智能、与线上一致）。
  - 幂等：已命中缓存的条目会被 enqueue_or_match 直接返回 cache_hit，不重复生成。

用法:
  .venv/bin/python scripts/prewarm_cache.py
  .venv/bin/python scripts/prewarm_cache.py --types meditation podcast_digest
  .venv/bin/python scripts/prewarm_cache.py --user prewarm_user
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from floppy_backend.catalog import AUDIO_CATALOG  # noqa: E402
from floppy_backend.config import get_settings  # noqa: E402
from floppy_backend.db import connect, initialize  # noqa: E402
from floppy_backend.models import (  # noqa: E402
    AudioType,
    GenerationRequest,
    ProfileLevel,
    UserProfileIn,
)
from floppy_backend.providers.audio import build_audio_provider  # noqa: E402
from floppy_backend.repositories import Repository  # noqa: E402
from floppy_backend.services.directive_planner import DirectivePlanner  # noqa: E402
from floppy_backend.services.generation import GenerationService  # noqa: E402
from floppy_backend.services.normalizer import RequestNormalizer  # noqa: E402
from floppy_backend.services.profile import ProfileService  # noqa: E402
from floppy_backend.services.script import SleepScriptService  # noqa: E402
from floppy_backend.services.script_writer import LLMScriptWriter  # noqa: E402
from floppy_backend.storage import LocalFileStorage  # noqa: E402

DEFAULT_TYPES = ["meditation", "story", "podcast_digest"]


def main() -> int:
    parser = argparse.ArgumentParser(description="预热生成缓存（真人声）")
    parser.add_argument("--types", nargs="*", default=DEFAULT_TYPES, help="要预热的 audio_type")
    parser.add_argument("--user", default="prewarm_user", help="预热使用的 user_id")
    args = parser.parse_args()

    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)
    repository = Repository(conn)
    storage = LocalFileStorage(settings.storage_dir, settings.public_base_url)

    llm_key = settings.query_planner_api_key or settings.dialog_llm_api_key
    if not llm_key:
        print("没有可用的 LLM key（FLOPPY_QUERY_PLANNER_API_KEY / FLOPPY_DIALOG_LLM_API_KEY），无法智能生成。", file=sys.stderr)
        return 2
    llm_base = settings.dialog_llm_base_url or settings.query_planner_base_url
    llm_model = settings.dialog_llm_model or settings.query_planner_model

    writer = LLMScriptWriter(api_key=llm_key, base_url=llm_base, model=llm_model,
                             timeout_sec=settings.script_writer_timeout_sec, max_tokens=settings.script_writer_max_tokens)
    planner = DirectivePlanner(api_key=llm_key, base_url=llm_base, model=llm_model,
                               timeout_sec=settings.directive_planner_timeout_sec,
                               max_tokens=settings.directive_planner_max_tokens,
                               confidence_threshold=settings.directive_planner_confidence_threshold)
    gen = GenerationService(
        repository=repository, storage=storage, provider=build_audio_provider(settings),
        normalizer=RequestNormalizer(),
        script_service=SleepScriptService(script_writer=writer), settings=settings,
    )

    # Ensure a sleep-default profile exists so directive planner has context.
    ProfileService(repository).upsert_profile(
        args.user,
        UserProfileIn(
            audio_type_preferences=[AudioType.MEDITATION, AudioType.STORY],
            voice_preferences=["warm_female"], background_preferences=["rain_soft"],
            duration_preference_min=15, stress_level=ProfileLevel.HIGH,
            anxiety_level=ProfileLevel.HIGH, avg_sleep_latency_min=40, mood_tags=["anxiety_relief"],
        ),
    )
    profile_ctx = _profile_context(repository, gen, args.user)

    items = [i for i in AUDIO_CATALOG if i["audio_type"] in args.types and not i.get("is_real")]
    print(f"预热 {len(items)} 条（types={args.types}）-> 真人声入库\n")
    done = hit = failed = 0
    for item in items:
        req_text = item["request_text"]
        title = item["title"]
        try:
            directive = planner.plan(req_text, profile_ctx)
            request = GenerationRequest(request_text=req_text, force_generate=False, directive=directive)
            # 1) 先看缓存是否已有（幂等）
            prepared = gen.prepare(args.user, request, allow_cache=True)
            if prepared.cached_asset is not None:
                print(f"  ⏭️  已缓存: {title}")
                hit += 1
                continue
            # 2) 真正生成入库
            t0 = time.perf_counter()
            resp = gen.generate_or_match(args.user, GenerationRequest(request_text=req_text, force_generate=True, directive=directive))
            dt = time.perf_counter() - t0
            mark = "（智能 directive）" if directive else "（模板兜底）"
            if resp.status == "succeeded" and resp.asset:
                print(f"  ✅ {title} {mark} {dt:.1f}s -> {resp.asset.object_key}")
                done += 1
            else:
                print(f"  ❌ {title}: status={resp.status}")
                failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {title}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n完成: 生成 {done}, 已缓存跳过 {hit}, 失败 {failed}")
    return 1 if failed else 0


def _profile_context(repository: Repository, gen: GenerationService, user_id: str):
    from floppy_backend.models import GenerationBudget, ProfileContext
    profile = repository.get_profile(user_id)
    used_chars, used_count = repository.generation_usage_since(user_id)
    budget = GenerationBudget(
        daily_remaining_chars=max(0, gen._settings.daily_char_budget - used_chars),
        daily_generate_count_remaining=max(0, gen._settings.daily_generate_count - used_count),
    )
    return ProfileContext(**profile.model_dump(), generation_budget=budget)


if __name__ == "__main__":
    raise SystemExit(main())
