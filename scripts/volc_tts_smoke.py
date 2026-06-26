#!/usr/bin/env python3
"""火山引擎单向流式 TTS (tts/unidirectional) 冒烟测试脚本.

独立验证用，不依赖 floppy_backend。验证:
  1) 凭证 / 鉴权是否正确
  2) 普通旁白 TTS 是否能出音频
  3) 拟声 / 氛围文本能否凑出"简短环境音"

接口: HTTP Chunked 流式, 每个 chunk 是一个 JSON, data 字段为 base64 音频分片。
文档: https://www.volcengine.com/docs/6561/1756902

用法:
  export VOLC_TTS_API_KEY=...        # 控制台 > API Key 管理
  python3 scripts/volc_tts_smoke.py --speaker zh_female_xxx
或:
  python3 scripts/volc_tts_smoke.py --api-key XXX --speaker zh_female_xxx
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from pathlib import Path

import requests

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_RESOURCE_ID = "seed-tts-2.0"

# 测试用例: (文件名后缀, 描述, text, 额外 req_params)
CASES = [
    (
        "narration",
        "普通旁白 (验证基础 TTS)",
        "今晚，给自己一点安静的时间。慢慢地，把呼吸放轻，让思绪沉下来。",
        {},
    ),
    (
        "ambient_whisper",
        "耳语/拟声氛围 (验证简短环境音能力)",
        "沙……沙……雨，轻轻地落在窗台上。滴答，滴答，滴答……",
        {"silence_duration": 1500},
    ),
]


def synth(api_key: str, resource_id: str, speaker: str, text: str,
          fmt: str, sample_rate: int, extra: dict) -> tuple[bytes, dict]:
    """发一次合成请求, 流式收完所有 chunk, 返回 (音频字节, 最后一个 meta)."""
    req_params = {
        "text": text,
        "speaker": speaker,
        "audio_params": {"format": fmt, "sample_rate": sample_rate},
    }
    # extra 里的 audio_params 子键合并进去, 其余直接放 req_params
    for key, value in extra.items():
        if key == "audio_params":
            req_params["audio_params"].update(value)
        else:
            req_params[key] = value

    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Control-Require-Usage-Tokens-Return": "*",
        "Content-Type": "application/json",
    }
    body = {"req_params": req_params}

    audio = bytearray()
    last_meta: dict = {}
    with requests.post(ENDPOINT, headers=headers, json=body, stream=True, timeout=120) as resp:
        logid = resp.headers.get("X-Tt-Logid", "")
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} (logid={logid}): {resp.text[:500]}")
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                # 偶有非 JSON 行 (空 chunk / 心跳), 跳过
                continue
            code = chunk.get("code")
            if code not in (0, None, 20000000):
                raise RuntimeError(f"合成失败 code={code} msg={chunk.get('message')} (logid={logid})")
            data_b64 = chunk.get("data")
            if data_b64:
                audio.extend(base64.b64decode(data_b64))
            # 保留带 usage / sentence 的 meta
            if chunk.get("usage") or chunk.get("sentence") or chunk.get("message"):
                last_meta = {k: v for k, v in chunk.items() if k != "data"}
        last_meta["_logid"] = logid
    return bytes(audio), last_meta


def main() -> int:
    parser = argparse.ArgumentParser(description="火山单向流式 TTS 冒烟测试")
    parser.add_argument("--api-key", default=os.getenv("VOLC_TTS_API_KEY"),
                        help="X-Api-Key, 默认读环境变量 VOLC_TTS_API_KEY")
    parser.add_argument("--resource-id", default=DEFAULT_RESOURCE_ID,
                        help=f"X-Api-Resource-Id, 默认 {DEFAULT_RESOURCE_ID}")
    parser.add_argument("--speaker", required=True,
                        help="音色 ID (从控制台音色库获取), 必填")
    parser.add_argument("--format", default="mp3", choices=["mp3", "pcm", "ogg_opus", "wav"])
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--text", default=None,
                        help="只合成这一段自定义文本, 不跑内置用例")
    parser.add_argument("--out-dir", default="storage/volc_smoke", type=Path)
    args = parser.parse_args()

    if not args.api_key:
        print("缺少 API Key: 设 VOLC_TTS_API_KEY 或传 --api-key", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ext = "mp3" if args.format == "mp3" else ("wav" if args.format == "wav" else "raw")

    if args.text:
        cases = [("custom", "自定义文本", args.text, {})]
    else:
        cases = CASES

    failures = 0
    for name, desc, text, extra in cases:
        print(f"\n=== [{name}] {desc} ===")
        print(f"    text: {text}")
        try:
            audio, meta = synth(args.api_key, args.resource_id, args.speaker,
                                text, args.format, args.sample_rate, extra)
        except Exception as exc:  # noqa: BLE001 — 冒烟脚本, 直接打印
            print(f"    ❌ 失败: {exc}")
            failures += 1
            continue
        if not audio:
            print("    ⚠️  请求成功但没拿到音频数据")
            failures += 1
            continue
        out_path = args.out_dir / f"{name}.{ext}"
        out_path.write_bytes(audio)
        usage = meta.get("usage") or {}
        print(f"    ✅ {len(audio)} bytes -> {out_path}")
        if usage:
            print(f"    计费字数: {usage.get('text_words')}")
        print(f"    logid: {meta.get('_logid')}")

    print(f"\n完成: {len(cases) - failures}/{len(cases)} 成功, 输出在 {args.out_dir}/")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
