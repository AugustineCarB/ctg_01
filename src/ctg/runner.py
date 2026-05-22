"""Generic runner: pull one series end-to-end."""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from ctg.loader import (
    finish_run,
    max_observation_date,
    start_run,
    upsert_observations,
    upsert_series,
)
from ctg.sources import fred

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ctg")

SOURCES = {"FRED": fred}


def run_one(source: str, native_code: str, since: date | None = None) -> int:
    src = SOURCES[source]
    series_id = f"{source}:{native_code}"
    run_id = start_run(source.lower())
    try:
        meta = src.fetch_metadata(native_code)
        upsert_series(meta)

        if since is None:
            last = max_observation_date(series_id)
            since = (last + timedelta(days=1)) if last else date(2000, 1, 1)

        log.info("fetching %s from %s", series_id, since)
        rows = list(src.fetch_observations(native_code, start=since))
        n = upsert_observations(series_id, rows)
        log.info("upserted %d rows into %s", n, series_id)
        finish_run(run_id, n, "ok")
        return n
    except Exception as e:
        log.exception("run failed")
        finish_run(run_id, 0, "error", str(e))
        raise


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, help="e.g. FRED")
    p.add_argument("--code", required=True, help="e.g. DGS10")
    p.add_argument("--since", help="YYYY-MM-DD; default = incremental from last loaded")
    args = p.parse_args()
    since = date.fromisoformat(args.since) if args.since else None
    run_one(args.source.upper(), args.code, since)


if __name__ == "__main__":
    main()
