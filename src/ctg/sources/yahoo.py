"""Yahoo Finance source via yfinance."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

import yfinance as yf


def fetch_metadata(native_code: str) -> dict:
    t = yf.Ticker(native_code)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass
    title = info.get("longName") or info.get("shortName") or native_code
    currency = info.get("currency")
    return {
        "id": f"YAHOO:{native_code}",
        "source": "YAHOO",
        "native_code": native_code,
        "title": title,
        "units": currency,
        "frequency": "D",
    }


def fetch_observations(
    native_code: str, start: date | None = None
) -> Iterator[tuple[date, float | None]]:
    start_str = (start or date(2000, 1, 1)).isoformat()
    end_str = (date.today() + timedelta(days=1)).isoformat()
    df = yf.download(
        native_code,
        start=start_str,
        end=end_str,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df.empty:
        return
    if "Close" in df.columns:
        close = df["Close"]
    else:
        close = df.iloc[:, 0]
    if hasattr(close, "iloc") and close.ndim > 1:
        close = close.iloc[:, 0]
    for ts, val in close.dropna().items():
        d = ts.date() if hasattr(ts, "date") else ts
        yield d, float(val)
