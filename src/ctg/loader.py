"""Upsert helpers for series/observations/runs."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from psycopg2.extras import execute_values

from ctg.config import connect


def upsert_series(meta: dict) -> None:
    sql = """
        insert into series (id, source, native_code, title, units, frequency, last_updated)
        values (%(id)s, %(source)s, %(native_code)s, %(title)s, %(units)s, %(frequency)s, now())
        on conflict (id) do update set
            title = excluded.title,
            units = excluded.units,
            frequency = excluded.frequency,
            last_updated = now();
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, meta)


def upsert_observations(series_id: str, rows: Iterable[tuple]) -> int:
    """rows is an iterable of (date, value) tuples. Returns count upserted."""
    payload = [(series_id, ts, val) for ts, val in rows]
    if not payload:
        return 0
    sql = """
        insert into observations (series_id, ts, value)
        values %s
        on conflict (series_id, ts) do update set value = excluded.value;
    """
    with connect() as conn, conn.cursor() as cur:
        execute_values(cur, sql, payload, page_size=1000)
    return len(payload)


def start_run(source: str) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into runs (source, started_at, status) values (%s, now(), 'running') returning id;",
            (source,),
        )
        return cur.fetchone()[0]


def finish_run(run_id: int, rows: int, status: str = "ok", error: str | None = None) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update runs
               set finished_at = now(),
                   rows_upserted = %s,
                   status = %s,
                   error_message = %s
             where id = %s;
            """,
            (rows, status, error, run_id),
        )


def max_observation_date(series_id: str):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select max(ts) from observations where series_id = %s;", (series_id,))
        return cur.fetchone()[0]
