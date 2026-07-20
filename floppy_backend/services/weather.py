"""Real weather context via Open-Meteo (no API key required).

Feeds a compact ``weather`` dict into the Hermes decision context so the
agent can answer "明天要不要带伞" and bridge real rain outside to rain
audio. Best-effort with a TTL cache: a network failure or timeout returns
None and the decision proceeds without weather — never blocks a chat turn.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_WEATHER_CODES = {
    0: "晴", 1: "大部晴朗", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹",
}


class WeatherService:
    """City-keyed weather snapshots with a 30-minute TTL cache."""

    def __init__(self, *, ttl_sec: float = 1800.0, timeout_sec: float = 2.5):
        self._ttl = ttl_sec
        self._timeout = timeout_sec
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._geo_cache: dict[str, tuple[float, float] | None] = {}

    def snapshot(self, city: str) -> dict[str, Any] | None:
        city = (city or "").strip()
        if not city:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(city)
            if hit and now - hit[0] < self._ttl:
                return hit[1]
        snap = self._fetch(city)
        with self._lock:
            self._cache[city] = (now, snap)
        return snap

    def _fetch(self, city: str) -> dict[str, Any] | None:
        try:
            coords = self._geocode(city)
            if coords is None:
                return None
            lat, lon = coords
            resp = httpx.get(
                _FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                    "forecast_days": 2,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current") or {}
            daily = data.get("daily") or {}
            code_now = int(current.get("weather_code", 0))

            def day(idx: int) -> dict[str, Any]:
                def pick(key, default=None):
                    values = daily.get(key) or []
                    return values[idx] if idx < len(values) else default
                return {
                    "desc": _WEATHER_CODES.get(int(pick("weather_code", 0) or 0), "未知"),
                    "temp_max": pick("temperature_2m_max"),
                    "temp_min": pick("temperature_2m_min"),
                    "rain_prob_max": pick("precipitation_probability_max"),
                }

            return {
                "city": city,
                "now": {
                    "desc": _WEATHER_CODES.get(code_now, "未知"),
                    "temp": current.get("temperature_2m"),
                    "raining": code_now in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99},
                },
                "today": day(0),
                "tomorrow": day(1),
            }
        except Exception:  # noqa: BLE001 — weather is garnish, never a blocker
            return None

    def _geocode(self, city: str) -> tuple[float, float] | None:
        if city in self._geo_cache:
            return self._geo_cache[city]
        try:
            resp = httpx.get(
                _GEOCODE_URL,
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
            coords = (results[0]["latitude"], results[0]["longitude"]) if results else None
        except Exception:  # noqa: BLE001
            coords = None
        self._geo_cache[city] = coords
        return coords
