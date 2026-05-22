"""DBnomics — umbrella adapter for 93 macro data providers. No auth.

Native code format: ``<provider>/<dataset>/<series>`` (slash-separated).
Examples:
    Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA20    — Euro area HICP (YoY %)
    IMF/WEO:2024-10/EA.NGDP_RPCH                 — IMF WEO Euro area real GDP growth
"""
from __future__ import annotations

from datetime import date
from typing import Iterator

import requests

BASE = "https://api.db.nomics.world/v22/series"


def _get(native_code: str, observations: int = 1) -> dict:
    r = requests.get(f"{BASE}/{native_code}", params={"observations": observations}, timeout=60)
    r.raise_for_status()
    return r.json()


def _first_doc(payload: dict) -> dict:
    docs = (payload.get("series") or {}).get("docs") or []
    if not docs:
        raise ValueError("DBnomics returned no series docs")
    return docs[0]


def fetch_metadata(native_code: str) -> dict:
    doc = _first_doc(_get(native_code, observations=1))
    freq_raw = (doc.get("@frequency") or "").lower()
    freq = {"daily": "D", "weekly": "W", "monthly": "M", "quarterly": "Q", "annual": "A"}.get(
        freq_raw
    )
    return {
        "id": f"DBNOMICS:{native_code}",
        "source": "DBNOMICS",
        "native_code": native_code,
        "title": doc.get("series_name") or native_code,
        "units": doc.get("unit") or doc.get("UNIT"),
        "frequency": freq,
    }


def _parse_period(period: str) -> date:
    p = period.strip()
    parts = p.split("-")
    if len(parts) == 3:
        return date.fromisoformat(p)
    if len(parts) == 2:
        if "Q" in p:  # e.g. 2024-Q3
            y, q = p.split("-Q")
            month = int(q) * 3
            return date(int(y), month, 1)
        return date(int(parts[0]), int(parts[1]), 1)
    return date(int(parts[0]), 12, 31)


def fetch_observations(
    native_code: str, start: date | None = None
) -> Iterator[tuple[date, float | None]]:
    doc = _first_doc(_get(native_code, observations=1))
    periods = doc.get("period") or []
    values = doc.get("value") or []
    for period, raw in zip(periods, values):
        ts = _parse_period(str(period))
        if start is not None and ts < start:
            continue
        if raw in (None, "NA"):
            val = None
        else:
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
        yield ts, val
