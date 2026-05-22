"""FRED (St. Louis Fed) source."""
from __future__ import annotations

from datetime import date
from typing import Iterator

import requests

from ctg.config import env

BASE = "https://api.stlouisfed.org/fred"


def _get(path: str, **params) -> dict:
    params["api_key"] = env("FRED_API_KEY")
    params["file_type"] = "json"
    r = requests.get(f"{BASE}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_metadata(native_code: str) -> dict:
    data = _get("series", series_id=native_code)
    s = data["seriess"][0]
    return {
        "id": f"FRED:{native_code}",
        "source": "FRED",
        "native_code": native_code,
        "title": s.get("title"),
        "units": s.get("units"),
        "frequency": s.get("frequency_short"),
    }


def fetch_observations(
    native_code: str, start: date | None = None
) -> Iterator[tuple[date, float | None]]:
    params = {"series_id": native_code}
    if start is not None:
        params["observation_start"] = start.isoformat()
    data = _get("series/observations", **params)
    for obs in data["observations"]:
        ts = date.fromisoformat(obs["date"])
        raw = obs["value"]
        val = None if raw in (".", "", None) else float(raw)
        yield ts, val
