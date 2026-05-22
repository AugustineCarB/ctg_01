"""EIA (Energy Information Administration) v2 source.

Uses the v2 ``seriesid`` compatibility endpoint so we can keep the familiar
v1-style series codes (e.g. ``PET.RWTC.D``). Paginates via ``offset``/``length``
because some series (WTI back to 1986) exceed the 5000-row default page.
"""
from __future__ import annotations

from datetime import date
from typing import Iterator

import requests

from ctg.config import env

BASE = "https://api.eia.gov/v2"
PAGE_SIZE = 5000


def _get(path: str, **params) -> dict:
    params["api_key"] = env("EIA_API_KEY")
    r = requests.get(f"{BASE}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_metadata(native_code: str) -> dict:
    data = _get(f"seriesid/{native_code}", length=1)["response"]
    rows = data.get("data", [])
    first = rows[0] if rows else {}
    title = first.get("series-description") or first.get("series-name") or native_code
    units = first.get("units")
    freq_raw = first.get("frequency") or ""
    freq = {"daily": "D", "weekly": "W", "monthly": "M", "quarterly": "Q", "annual": "A"}.get(
        freq_raw.lower(), freq_raw[:1].upper() if freq_raw else None
    )
    return {
        "id": f"EIA:{native_code}",
        "source": "EIA",
        "native_code": native_code,
        "title": title,
        "units": units,
        "frequency": freq,
    }


def _parse_period(period: str) -> date:
    """Parse EIA period strings: 'YYYY-MM-DD', 'YYYY-MM', or 'YYYY'."""
    parts = period.split("-")
    if len(parts) == 3:
        return date.fromisoformat(period)
    if len(parts) == 2:
        # month -> use end of month? simplest: use day 1 (period-start) for now.
        # Monthly EIA series get stamped on the first of the month.
        return date(int(parts[0]), int(parts[1]), 1)
    return date(int(parts[0]), 12, 31)


def fetch_observations(
    native_code: str, start: date | None = None
) -> Iterator[tuple[date, float | None]]:
    """Paginate through the series newest→oldest, stop once we cross ``start``.

    EIA v2's ``start`` query parameter is silently ignored for large pages,
    so we filter on the client. Rows arrive in descending period order.
    """
    offset = 0
    while True:
        resp = _get(f"seriesid/{native_code}", offset=offset, length=PAGE_SIZE)["response"]
        rows = resp.get("data", [])
        if not rows:
            break

        stop = False
        for row in rows:
            period = row.get("period")
            if period is None:
                continue
            ts = _parse_period(period)
            if start is not None and ts < start:
                stop = True
                break
            raw = row.get("value")
            val = None if raw in (None, "", ".") else float(raw)
            yield ts, val

        if stop or len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
