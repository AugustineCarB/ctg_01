"""ECB Data Portal — euro-area rates, FX, yield curves. No auth.

Native code format: ``<flowRef>.<key>`` where flowRef is the dataset (EXR, YC,
FM, ...) and key is the period/dimension string. We split on the first dot.

Examples:
    EXR.D.USD.EUR.SP00.A         — USD/EUR daily reference rate
    FM.D.U2.EUR.4F.KR.DFR.LEV    — ECB deposit facility rate
    YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y  — euro yield curve 10Y AAA spot
"""
from __future__ import annotations

import csv
from datetime import date
from io import StringIO
from typing import Iterator

import requests

BASE = "https://data-api.ecb.europa.eu/service/data"


def _split(native_code: str) -> tuple[str, str]:
    if "." not in native_code:
        raise ValueError(f"ECB code must be flowRef.key, got {native_code!r}")
    flow, _, key = native_code.partition(".")
    return flow, key


def _csv(native_code: str, start: date | None = None) -> list[dict]:
    flow, key = _split(native_code)
    params = {"format": "csvdata"}
    if start is not None:
        params["startPeriod"] = start.isoformat()
    r = requests.get(f"{BASE}/{flow}/{key}", params=params, timeout=60)
    r.raise_for_status()
    text = r.text
    if not text.strip():
        return []
    return list(csv.DictReader(StringIO(text)))


def fetch_metadata(native_code: str) -> dict:
    flow, key = _split(native_code)
    r = requests.get(
        f"{BASE}/{flow}/{key}",
        params={"format": "csvdata", "lastNObservations": 1},
        timeout=30,
    )
    r.raise_for_status()
    rows = list(csv.DictReader(StringIO(r.text)))
    row = rows[0] if rows else {}
    title = row.get("TITLE_COMPL") or row.get("TITLE") or native_code
    units = row.get("UNIT") or row.get("UNIT_MEASURE")
    freq_raw = (row.get("FREQ") or "").upper()
    freq = {"D": "D", "W": "W", "M": "M", "Q": "Q", "A": "A", "B": "D"}.get(freq_raw)
    return {
        "id": f"ECB:{native_code}",
        "source": "ECB",
        "native_code": native_code,
        "title": title,
        "units": units,
        "frequency": freq,
    }


def _parse_period(period: str) -> date:
    p = period.strip()
    parts = p.split("-")
    if len(parts) == 3:
        return date.fromisoformat(p)
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), 1)
    return date(int(parts[0]), 12, 31)


def fetch_observations(
    native_code: str, start: date | None = None
) -> Iterator[tuple[date, float | None]]:
    for row in _csv(native_code, start=start):
        period = row.get("TIME_PERIOD")
        raw = row.get("OBS_VALUE")
        if not period:
            continue
        ts = _parse_period(period)
        val = None if raw in (None, "", "NaN", ".") else float(raw)
        yield ts, val
