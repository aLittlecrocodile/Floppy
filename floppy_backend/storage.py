from __future__ import annotations

from pathlib import Path, PurePosixPath


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
        return f"{self.public_base_url}/audio/{object_key.lstrip('/')}"

    def _safe_path(self, object_key: str) -> Path:
        clean = PurePosixPath(object_key.lstrip("/"))
        if clean.is_absolute() or ".." in clean.parts:
            raise ValueError("invalid object key")
        path = (self.storage_dir / Path(*clean.parts)).resolve()
        if not path.is_relative_to(self.storage_dir):
            raise ValueError("invalid object key")
        return path
