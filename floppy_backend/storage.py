from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path, PurePosixPath

# Base URL of the *current* HTTP request (set by middleware in main.py).
# Minting playback URLs from the host the client actually used means a phone
# reaching the backend on any LAN IP gets stream URLs it can play back —
# the configured FLOPPY_PUBLIC_BASE_URL is only the fallback (background
# jobs, websockets, scripts).
_request_base_url: ContextVar[str | None] = ContextVar("floppy_request_base_url", default=None)


def set_request_base_url(base_url: str | None) -> None:
    _request_base_url.set(base_url.rstrip("/") if base_url else None)


class LocalFileStorage:
    def __init__(self, storage_dir: Path, public_base_url: str):
        self.storage_dir = storage_dir.resolve()
        self.public_base_url = public_base_url.rstrip("/")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, object_key: str) -> Path:
        path = self._safe_path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def existing_path_for(self, object_key: str) -> Path:
        return self._safe_path(object_key)

    def public_url(self, object_key: str) -> str:
        base = _request_base_url.get() or self.public_base_url
        return f"{base}/audio/{object_key.lstrip('/')}"

    def _safe_path(self, object_key: str) -> Path:
        clean = PurePosixPath(object_key.lstrip("/"))
        if clean.is_absolute() or ".." in clean.parts:
            raise ValueError("invalid object key")
        path = (self.storage_dir / Path(*clean.parts)).resolve()
        if not path.is_relative_to(self.storage_dir):
            raise ValueError("invalid object key")
        return path
