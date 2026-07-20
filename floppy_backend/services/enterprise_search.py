"""Real Baidu internal search (内搜) for the Unwind agent.

Talks to the same API the local enterprise-search OneTool skill uses
(apigo.baidu-int.com), authenticating with the cached ugate token from
``~/.config/uuap/.eac_ugate_token_<username>`` — run the get-ugate-token
skill once to create it. Without a token the service reports
unavailable and callers degrade gracefully.

Notes from the OneTool skill docs honored here:
- corporate proxies truncate apigo requests → ``trust_env=False`` (direct);
- username comes from SANDBOX_USERNAME / BAIDU_CC_USERNAME, else it is
  auto-detected from the token cache filename.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

NEISOU_SEARCH_URL = "https://apigo.baidu-int.com/search-open/openapi/search-auth/openapi/search/neisou"


def _token_cache_dir() -> Path:
    return Path.home() / ".config" / "uuap"


class EnterpriseSearchService:
    """ugate-authenticated internal search with graceful degradation."""

    def __init__(self, *, timeout_sec: float = 6.0):
        self._timeout = timeout_sec

    # -- identity ----------------------------------------------------------

    def _identity(self) -> tuple[str, str] | None:
        """(username, token) from env + token cache; None when unauthorized."""
        cache_dir = _token_cache_dir()
        username = os.environ.get("SANDBOX_USERNAME") or os.environ.get("BAIDU_CC_USERNAME")
        candidates: list[str] = []
        if username:
            candidates.append(username)
        else:
            try:
                # newest token file first — a freshly pasted token must win
                # over stale caches for other usernames
                files = sorted(
                    cache_dir.glob(".eac_ugate_token_*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                candidates = [p.name.removeprefix(".eac_ugate_token_") for p in files]
            except OSError:
                candidates = []
        for name in candidates:
            token = self._read_token(cache_dir / f".eac_ugate_token_{name}")
            if token:
                return name, token
        return None

    @staticmethod
    def _read_token(path: Path) -> str | None:
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(data, dict):
            token = data.get("token")
            return str(token) if token else None
        return None

    @property
    def available(self) -> bool:
        return self._identity() is not None

    # -- search ------------------------------------------------------------

    def neisou(self, query: str, *, limit: int = 3) -> dict[str, Any]:
        """Search 内搜. Returns {"status": ..., "results": [...]}.

        status: "ok" | "unauthorized" | "error" | "empty".
        Each result: {"title", "url", "snippet"} (fields best-effort).
        """
        query = (query or "").strip()
        if not query:
            return {"status": "empty", "results": []}
        identity = self._identity()
        if identity is None:
            return {"status": "unauthorized", "results": []}
        username, token = identity
        try:
            resp = httpx.post(
                NEISOU_SEARCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "ugate-token": token,
                    "uuap": username,
                },
                json={"word": query, "pageNo": 1, "auth": False},
                timeout=self._timeout,
                trust_env=False,  # corp proxy truncates apigo requests
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 — degrade, never crash a turn
            return {"status": "error", "results": [], "error": str(exc)[:160]}
        results = _extract_results(payload, limit=limit)
        return {"status": "ok" if results else "empty", "results": results}


def _extract_results(payload: Any, *, limit: int) -> list[dict[str, str]]:
    """Defensive extraction — the API envelope varies by resource type."""
    items: list[Any] = []

    def _collect(node: Any, depth: int = 0) -> None:
        if depth > 4 or len(items) >= limit * 4:
            return
        if isinstance(node, list):
            for child in node:
                _collect(child, depth + 1)
        elif isinstance(node, dict):
            title = node.get("title") or node.get("docTitle") or node.get("name")
            if isinstance(title, str) and title.strip():
                items.append(node)
                return
            for value in node.values():
                _collect(value, depth + 1)

    _collect(payload)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in items:
        title = _strip_marks(str(node.get("title") or node.get("docTitle") or node.get("name") or ""))
        if not title or title in seen:
            continue
        seen.add(title)
        url = str(node.get("url") or node.get("docUrl") or node.get("link") or node.get("resourceUrl") or "")
        snippet = _clean_snippet(_strip_marks(str(
            node.get("summary") or node.get("abstract") or node.get("content")
            or node.get("desc") or node.get("snippet") or ""
        )))[:140]
        results.append({"title": title[:80], "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _clean_snippet(text: str) -> str:
    """FAQ-database hits embed record structure（知识分类/标准问题/相似问题/答案）
    before the actual answer — keep only the answer body, drop boilerplate
    greetings, so replies speak the answer itself."""
    for marker in ("答案：", "答案:"):
        if marker in text:
            text = text.split(marker, 1)[1]
            break
    for greeting in ("同学你好，", "同学您好，", "您好，", "你好，"):
        if text.startswith(greeting):
            text = text[len(greeting):]
            break
    return text.strip()


def _strip_marks(text: str) -> str:
    """Search APIs return <em data-highlight>-style fragments; strip all tags."""
    text = re.sub(r"<[^>]{0,60}>", "", text)
    return text.replace("\n", "").replace("\r", "").strip()
