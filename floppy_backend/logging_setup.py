"""Centralised logging config for the Floppy backend.

Wires the ``floppy`` logger (and the root logger) to both stdout and a
rotating file so request/connection history survives after the launching
terminal is gone. The access-log middleware below records every HTTP hit
with its **client IP** — the fastest way to tell "did that device even
reach us?" apart from "the app returned an error".
"""
from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    *,
    level: str = "INFO",
    log_dir: str | Path = "logs",
    log_file: str = "floppy.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    """Configure console + rotating-file logging. Idempotent.

    Returns the resolved log-file path so callers can print it at startup.
    """
    global _CONFIGURED

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_path = log_path / log_file

    if _CONFIGURED:
        return file_path

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    # Avoid piling duplicate handlers on reload.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Make uvicorn's own access/error logs flow through the same handlers/file.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    logging.getLogger("floppy").setLevel(numeric_level)

    _CONFIGURED = True
    return file_path


def _client_ip(scope) -> str:  # noqa: ANN001 — ASGI scope
    """Best-effort real client IP.

    Honours X-Forwarded-For / X-Real-IP (first hop) when present so a
    reverse-proxied deployment still logs the true source, otherwise falls
    back to the raw TCP peer from the ASGI ``client`` tuple.
    """
    headers = {k: v for k, v in scope.get("headers") or []}
    fwd = headers.get(b"x-forwarded-for")
    if fwd:
        return fwd.decode("latin-1").split(",")[0].strip()
    real = headers.get(b"x-real-ip")
    if real:
        return real.decode("latin-1").strip()
    client = scope.get("client")
    if client:
        return f"{client[0]}:{client[1]}"
    return "unknown"


class AccessLogMiddleware:
    """Pure-ASGI middleware: log every HTTP request with client IP,
    method, path, status code and latency. WebSocket upgrades are logged
    at connect time too (they never get an HTTP status)."""

    def __init__(self, app):  # noqa: ANN001 — ASGI app
        self.app = app
        self.logger = logging.getLogger("floppy.access")

    async def __call__(self, scope, receive, send):  # noqa: ANN001 — ASGI signature
        if scope["type"] == "websocket":
            ip = _client_ip(scope)
            path = scope.get("path", "")
            self.logger.info("WS    %s %s (connect)", ip, path)
            await self.app(scope, receive, send)
            return

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        ip = _client_ip(scope)
        method = scope.get("method", "?")
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode("latin-1")
        target = f"{path}?{query}" if query else path
        start = time.perf_counter()
        status_holder = {"code": 0}

        async def send_wrapper(message):  # noqa: ANN001 — ASGI message
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            self.logger.exception(
                "%-6s %s %s -> 500 EXC (%.1fms)", method, ip, target, elapsed
            )
            raise
        else:
            elapsed = (time.perf_counter() - start) * 1000
            self.logger.info(
                "%-6s %s %s -> %d (%.1fms)",
                method,
                ip,
                target,
                status_holder["code"],
                elapsed,
            )
