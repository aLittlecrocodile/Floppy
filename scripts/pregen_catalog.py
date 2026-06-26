#!/usr/bin/env python3
"""Batch pre-generate audio from catalog.

- minimax strategy: calls MiniMax TTS (requires FLOPPY_MINIMAX_API_KEY)
- local strategy: generates local tone placeholder
- skip strategy: metadata only

Usage:
  .venv/bin/python scripts/pregen_catalog.py [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from floppy_backend.catalog import AUDIO_CATALOG
from floppy_backend.config import get_settings
from floppy_backend.db import connect, initialize
from floppy_backend.models import AudioAssetIn, AudioType, GenerationRequest
from floppy_backend.providers.audio import LocalToneAudioProvider, build_audio_provider
from floppy_backend.repositories import Repository
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.script_expander import expand_script
from floppy_backend.storage import LocalFileStorage
from floppy_backend.utils import sha256_json, text_embedding


def main():
    dry_run = "--dry-run" in sys.argv
    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)
    repository = Repository(conn)
    storage = LocalFileStorage(settings.storage_dir, settings.public_base_url)
    normalizer = RequestNormalizer()
    local_provider = LocalToneAudioProvider()

    minimax_provider = None
    if settings.audio_provider == "minimax" or settings.minimax_api_key:
        try:
            minimax_provider = build_audio_provider(settings.__class__(audio_provider="minimax", minimax_api_key=settings.minimax_api_key, minimax_base_url=settings.minimax_base_url))
        except Exception as e:
            print(f"⚠ MiniMax provider unavailable: {e}")

    results = []
    for item in AUDIO_CATALOG:
        normalized = normalizer.normalize(GenerationRequest(request_text=item["request_text"]), profile=None)
        cache_key = sha256_json({
            "normalized": normalized.model_dump(mode="json"),
            "title": item["title"],
            "script_text": item.get("script_text"),
        })
        strategy = item["provider_strategy"]

        if strategy == "skip":
            results.append({"title": item["title"], "status": "skipped"})
            continue

        use_minimax = strategy == "minimax" and minimax_provider and not item["is_placeholder"]
        provider = minimax_provider if use_minimax else local_provider
        ext = "mp3" if use_minimax else "wav"
        object_key = f"pregen/{item['audio_type']}/{cache_key[:16]}.{ext}"

        if dry_run:
            results.append({"title": item["title"], "status": f"dry-run ({strategy})", "object_key": object_key})
            continue

        try:
            script_text = item.get("script_text")
            if use_minimax and script_text:
                script_text = expand_script(script_text, item["duration_sec"])
            generated = provider.generate(normalized, storage.path_for(object_key), object_key, script_text=script_text, title=item["title"])
            repository.upsert_asset(AudioAssetIn(
                type=AudioType(item["audio_type"]),
                title=item["title"],
                object_key=object_key,
                duration_sec=item["duration_sec"],
                language="zh-CN",
                voice_id=item.get("voice_style") or normalized.voice_style,
                prompt_hash=cache_key,
                content_hash=generated.content_hash,
                mood_tags=item["mood_tags"],
                tags=item["tags"],
                user_segment_tags=item["user_segment_tags"],
                safety_status="approved",
                quality_score=item["quality_score"],
                embedding=text_embedding(" ".join([item["request_text"], item["audio_type"], *item["tags"], *item["mood_tags"]])),
                created_by="pregen_minimax" if use_minimax else "pregen_local",
            ))
            status = "minimax" if use_minimax else "local_placeholder"
            results.append({"title": item["title"], "status": status, "cost": getattr(generated, "estimated_cost_usd", None)})
        except Exception as e:
            results.append({"title": item["title"], "status": f"FAILED: {e}"})

    print(f"\n{'Title':<30} {'Status':<25} {'Cost'}")
    print("-" * 70)
    for r in results:
        cost = f"${r.get('cost', 0) or 0:.4f}" if r.get("cost") else "-"
        print(f"{r['title']:<30} {r['status']:<25} {cost}")
    print(f"\nTotal: {len(results)} items")
    conn.close()


if __name__ == "__main__":
    main()
