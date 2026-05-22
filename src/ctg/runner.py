"""Generic runner: pull one series end-to-end, or all from the registry."""
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
from ctg.registry import SeriesEntry, load as load_registry
from ctg.sources import eia, fred, tiingo, yahoo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ctg")

SOURCES = {"FRED": fred, "YAHOO": yahoo, "EIA": eia, "TIINGO": tiingo}


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
        log.exception("run failed for %s", series_id)
        finish_run(run_id, 0, "error", str(e))
        raise


def run_all(since: date | None = None) -> dict[str, int | str]:
    results: dict[str, int | str] = {}
    for entry in load_registry():
        try:
            n = run_one(entry.source.upper(), entry.code, since=since)
            results[entry.id] = n
        except Exception as e:
            results[entry.id] = f"error: {e}"
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", help="e.g. FRED (ignored if --all)")
    p.add_argument("--code", help="e.g. DGS10 (ignored if --all)")
    p.add_argument("--since", help="YYYY-MM-DD; default = incremental from last loaded")
    p.add_argument("--all", action="store_true", help="run every series in registry.yaml")
    args = p.parse_args()

    since = date.fromisoformat(args.since) if args.since else None

    if args.all:
        results = run_all(since=since)
        log.info("=" * 60)
        log.info("registry run summary:")
        for sid, n in results.items():
            log.info("  %s: %s", sid, n)
        return

    if not args.source or not args.code:
        p.error("--source and --code are required unless --all is set")
    run_one(args.source.upper(), args.code, since)


if __name__ == "__main__":
    main()
