from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Any, Iterable


def utcnow() -> datetime:
    return datetime.now(UTC)


def stable_id(prefix: str, payload: Any) -> str:
    digest = sha256_json(payload)[:20]
    return f"{prefix}_{digest}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str) -> Any:
    return json.loads(value)


def tokenize(text: str) -> list[str]:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", text.lower())
    tokens = [part for part in normalized.split() if part]
    chinese_chars = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
    return tokens + chinese_chars


def text_embedding(text: str, dimensions: int = 32) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        sign = 1 if digest[2] % 2 == 0 else -1
        vector[index] += sign * (1.0 + len(token) / 10.0)
    return normalize(vector)


def normalize(vector: Iterable[float]) -> list[float]:
    values = list(vector)
    norm = math.sqrt(sum(item * item for item in values))
    if norm == 0:
        return values
    return [item / norm for item in values]

