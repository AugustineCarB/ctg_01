"""Helper for downstream Claude Code sessions to read series as a DataFrame."""
from __future__ import annotations

from datetime import date

import pandas as pd

from ctg.config import connect


def get(series_ids: list[str], start: date | str | None = None) -> pd.DataFrame:
    """Return a wide DataFrame indexed by date, one column per series_id."""
    if isinstance(start, str):
        start = date.fromisoformat(start)

    sql = "select series_id, ts, value from observations where series_id = any(%s)"
    params: list = [series_ids]
    if start is not None:
        sql += " and ts >= %s"
        params.append(start)
    sql += " order by ts;"

    with connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    return df.pivot(index="ts", columns="series_id", values="value").sort_index()


def list_series() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql("select * from series order by id;", conn)
