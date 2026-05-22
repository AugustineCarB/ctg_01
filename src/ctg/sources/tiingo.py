"""Tiingo source — clean-license daily EOD prices for US equities & ETFs."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

import requests

from ctg.config import env

BASE = "https://api.tiingo.com/tiingo/daily"


def _headers() -> dict:
    return {
        "Authorization": f"Token {env('TIINGO_API_KEY')}",
        "Content-Type": "application/json",
    }


def fetch_metadata(native_code: str) -> dict:
    r = requests.get(f"{BASE}/{native_code}", headers=_headers(), timeout=30)
    r.raise_for_status()
    d = r.json()
    return {
        "id": f"TIINGO:{native_code}",
        "source": "TIINGO",
        "native_code": native_code,
        "title": d.get("name") or native_code,
        "units": "USD",
        "frequency": "D",
    }


def fetch_observations(
    native_code: str, start: date | None = None
) -> Iterator[tuple[date, float | None]]:
    """Yield (date, adjClose) — split-and-dividend-adjusted total-return close."""
    params = {
        "startDate": (start or date(2000, 1, 1)).isoformat(),
        "endDate": (date.today() + timedelta(days=1)).isoformat(),
        "format": "json",
        "resampleFreq": "daily",
    }
    r = requests.get(
        f"{BASE}/{native_code}/prices",
        headers=_headers(),
        params=params,
        timeout=60,
    )
    r.raise_for_status()
    for row in r.json():
        ts_str = row.get("date", "")[:10]
        if not ts_str:
            continue
        ts = date.fromisoformat(ts_str)
        val = row.get("adjClose")
        yield ts, (None if val is None else float(val))
