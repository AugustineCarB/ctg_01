# CTG — Cross-the-Globe Market Data Warehouse

This repo's purpose: **pull market/economic data from many sources on a daily cadence into a Supabase Postgres database, so any Claude Code session can chart "X vs Y over time" by querying the warehouse.**

The downstream UX target is sentences like:
> "Grab the 10-year and 2-year yields and plot the 2s10s curve since 2000."

A future agent should be able to answer that with `ctg.query.get([...])` → DataFrame → matplotlib, with no fetching code required.

---

## Architecture at a glance

```
data sources (FRED, Yahoo, Treasury, ...)
        │
        ▼  src/ctg/sources/<source>.py      (one module per provider)
        │     ↳ fetch_metadata(code) -> dict
        │     ↳ fetch_observations(code, start) -> Iterator[(date, value)]
        ▼
   src/ctg/runner.py        ── orchestrates one (source, code) at a time
        │
        ▼  src/ctg/loader.py
        │     ↳ upsert_series / upsert_observations / start_run / finish_run
        ▼
   Supabase Postgres        (tables: series, observations, runs)
        │
        ▼  src/ctg/query.py
        │     ↳ get([series_ids], start=...) -> wide pandas DataFrame
        ▼
   downstream Claude Code session → charts
```

## Database schema (canonical)

Defined in `supabase/migrations/0001_init.sql`. Three tables:

- **`series`** — catalog. One row per series we track. PK `id` = `"<SOURCE>:<native_code>"` (e.g. `FRED:DGS10`).
- **`observations`** — the data. PK `(series_id, ts)`. Wide-format queries are built by pivoting on `series_id`.
- **`runs`** — ETL audit log. One row per `runner.run_one(...)` invocation.

All writes use `on conflict do update`, so re-running a backfill is idempotent.

## What's built so far

- Repo scaffold (`src/ctg`, `supabase/migrations`, `scripts`)
- Migration `0001_init.sql` (series, observations, runs)
- FRED source (`src/ctg/sources/fred.py`)
- Generic runner + loader
- Query helper for downstream sessions
- Series loaded from FRED (both backfilled from 2000-01-01):
  - `FRED:DGS10` — 10Y Treasury yield, 6,884 rows
  - `FRED:DGS2` — 2Y Treasury yield, 6,884 rows
- Demo notebook: [notebooks/01_2s10s_demo.ipynb](notebooks/01_2s10s_demo.ipynb) — plots 10Y, 2Y, and the 2s10s spread; shades inverted periods

## What's NOT built yet

- Additional sources: Yahoo, US Treasury, CoinGecko, BLS, ECB, etc.
- Series registry (declarative YAML listing every series we track)
- Daily cron (GitHub Actions workflow)
- Tests

## Conventions

- **Series IDs** are always `"<SOURCE>:<native_code>"` in UPPERCASE for the source, native casing for the code (FRED uses upper, Yahoo can be mixed). Example: `FRED:DGS10`, `YAHOO:^GSPC`.
- **Idempotency is non-negotiable.** Every loader path must be safe to re-run on the same day.
- **Incremental by default.** If `--since` is omitted, the runner picks up from `max(ts) + 1 day` per series.
- **Rates**: FRED allows ~120 req/min, no auth issues at our volume. Yahoo is unofficial — batch where possible.
- **Secrets**: only in `.env` (gitignored). `supabase_info.md` is also gitignored — delete it after copying values.

## Running things

```bash
# one-time: install deps (psycopg2-binary, requests, pandas, python-dotenv already on anaconda Python)
/opt/anaconda3/bin/pip install psycopg2-binary python-dotenv

# apply migrations
PYTHONPATH=src /opt/anaconda3/bin/python scripts/apply_migrations.py

# backfill a series
PYTHONPATH=src /opt/anaconda3/bin/python -m ctg.runner --source FRED --code DGS10 --since 2000-01-01

# incremental update (default if --since omitted)
PYTHONPATH=src /opt/anaconda3/bin/python -m ctg.runner --source FRED --code DGS10
```

## How to query (downstream agent playbook)

```python
import sys; sys.path.insert(0, "src")
from ctg.query import get, list_series
import matplotlib.pyplot as plt

# discover what's available
list_series()

# pull what you need into a wide DataFrame
df = get(["FRED:DGS10", "FRED:DGS2"], start="2000-01-01")
df["2s10s"] = df["FRED:DGS10"] - df["FRED:DGS2"]
df["2s10s"].plot(title="2s10s spread"); plt.show()
```

## How to add a new source

1. Create `src/ctg/sources/<name>.py` exposing:
   - `fetch_metadata(native_code: str) -> dict` returning `{id, source, native_code, title, units, frequency}`.
   - `fetch_observations(native_code: str, start: date | None) -> Iterator[(date, float|None)]`.
2. Register it in `SOURCES` in `src/ctg/runner.py`.
3. Run `python -m ctg.runner --source <NAME> --code <CODE> --since 2000-01-01` for a backfill.

## How to add a new series (existing source)

For now: just invoke the runner with the new code. Once the declarative registry exists, it'll be a single YAML entry.

## Connection notes

Supabase free tier no longer exposes the direct `db.<ref>.supabase.co` host. We connect via the **session pooler**:

```
host:     aws-1-us-east-1.pooler.supabase.com
port:     5432  (session mode; 6543 is transaction mode)
user:     postgres.<project_ref>
database: postgres
sslmode:  require
```

If you spin up a new project, re-discover the region with `scripts/find_pooler_region.py`.

## Open design questions to revisit

- **Wide vs long table for observations**: currently long (one row per `(series, date)`). Cheap, flexible, but joins for multi-series charts cost a pivot. Consider materialized views once we have ~100 series.
- **Intraday data**: schema is daily-only (`ts` is `date`). When we want minute/hourly bars (e.g. crypto), add a separate `observations_intraday(series_id, ts timestamptz, value)` table.
- **Metadata creep**: keep `series` lean for now; if we start needing lots of provider-specific fields, add a `metadata jsonb` column.
- **Currency / FX normalization**: out of scope until we hit a use case.
