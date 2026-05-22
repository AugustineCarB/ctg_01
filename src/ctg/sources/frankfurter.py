"""Frankfurter — free FX rates sourced from the ECB reference rates.

Native code format: 6-letter ISO concat, e.g. ``USDBRL`` (base=USD, quote=BRL).
History starts 1999-01-04 (the ECB's first reference rate publication).
"""
from __future__ import annotations

from datetime import date
from typing import Iterator

import requests

BASE = "https://api.frankfurter.dev/v1"
MIN_DATE = date(1999, 1, 4)


def _split(native_code: str) -> tuple[str, str]:
    if len(native_code) != 6:
        raise ValueError(f"frankfurter code must be 6 letters (BASEQUOTE), got {native_code!r}")
    return native_code[:3].upper(), native_code[3:].upper()


def fetch_metadata(native_code: str) -> dict:
    b, q = _split(native_code)
    return {
        "id": f"FRANKFURTER:{native_code}",
        "source": "FRANKFURTER",
        "native_code": native_code,
        "title": f"{b}/{q} reference rate (ECB via Frankfurter)",
        "units": q,
        "frequency": "D",
    }


def fetch_observations(
    native_code: str, start: date | None = None
) -> Iterator[tuple[date, float | None]]:
    base, quote = _split(native_code)
    start = max(start or MIN_DATE, MIN_DATE)
    end = date.today()
    url = f"{BASE}/{start.isoformat()}..{end.isoformat()}"
    r = requests.get(url, params={"base": base, "symbols": quote}, timeout=30)
    r.raise_for_status()
    rates = r.json().get("rates", {})
    for day, mapping in sorted(rates.items()):
        val = mapping.get(quote)
        if val is None:
            continue
        yield date.fromisoformat(day), float(val)
