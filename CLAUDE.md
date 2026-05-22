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
- FRED source (`src/ctg/sources/fred.py`) — REST API
- Yahoo Finance source (`src/ctg/sources/yahoo.py`) — via `yfinance`
- EIA v2 source (`src/ctg/sources/eia.py`) — energy spot prices, public-domain license
- **Declarative series registry** at [registry.yaml](registry.yaml) — single source of truth for what we track. Currently 22 series across FRED + Yahoo + EIA.
- `runner.py --all` reads `registry.yaml` and updates every series (idempotent)
- Demo notebook: [notebooks/01_2s10s_demo.ipynb](notebooks/01_2s10s_demo.ipynb) — plots 10Y, 2Y, and the 2s10s spread; shades inverted periods

Warehouse currently holds **~127k observations**: full US Treasury curve (DGS2/5/10/30 + T10Y2Y), short rates (DFF, SOFR), monthly macro (CPIAUCSL, UNRATE), equity indices (^GSPC, ^NDX, ^VIX), FX/commodities (DXY, gold), crypto (BTC, ETH), and **energy** (WTI, Brent, Henry Hub gas, NY gasoline, heating oil, Gulf Coast jet) — all backfilled to 2000-01-01.

## What's NOT built yet

Macro-focused next sources (see [agent_research.md](agent_research.md), re-ranked for macro lens):
- Tiingo — clean-license US equities/ETFs (replaces yfinance for SPY/QQQ/IWM)
- ECB Data Portal — euro area yield curve, EUR rates, FX
- DBnomics — umbrella adapter for 93 non-US macro providers
- AAII / NAAIM — equity sentiment (Bull/Bear spread)
- Frankfurter — EM FX pairs

Plus:
- Daily cron (GitHub Actions workflow)
- Tests

## Conventions

- **Series IDs** are always `"<SOURCE>:<native_code>"` in UPPERCASE for the source, native casing for the code (FRED uses upper, Yahoo can be mixed). Example: `FRED:DGS10`, `YAHOO:^GSPC`.
- **Idempotency is non-negotiable.** Every loader path must be safe to re-run on the same day.
- **Incremental by default.** If `--since` is omitted, the runner picks up from `max(ts) + 1 day` per series.
- **Rates**: FRED allows ~120 req/min, no auth issues at our volume. Yahoo is unofficial — batch where possible.
- **Secrets**: only in `.env` (gitignored). `supabase_info.md` is also gitignored — delete it after copying values.
- **EIA quirk**: the v2 ``start`` query parameter is silently ignored when ``length>10``-ish. The source filters client-side instead — EIA returns rows newest→oldest, we stop paging once we cross ``start``.

## Running things

```bash
# one-time: install deps (psycopg2-binary, requests, pandas, python-dotenv already on anaconda Python)
/opt/anaconda3/bin/pip install psycopg2-binary python-dotenv

# apply migrations
PYTHONPATH=src /opt/anaconda3/bin/python scripts/apply_migrations.py

# update every series in registry.yaml (incremental — picks up from max(ts)+1 per series)
PYTHONPATH=src /opt/anaconda3/bin/python -m ctg.runner --all

# backfill every series from a specific date
PYTHONPATH=src /opt/anaconda3/bin/python -m ctg.runner --all --since 2000-01-01

# update a single series (ad hoc)
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

1. Add an entry to [registry.yaml](registry.yaml):
   ```yaml
   - id: FRED:NEWCODE
     source: fred
     code: NEWCODE
     notes: short description
   ```
2. Run `python -m ctg.runner --all --since 2000-01-01` to backfill (existing series get incremental updates, the new one gets the full history).
3. Commit and push — the daily cron (once built) will keep it fresh.

The `id` must equal `<SOURCE-UPPERCASE>:<code>` exactly — the registry loader enforces this.

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

## Workspace tooling (`.claude/`)

This workspace ships with custom Claude Code configuration under `.claude/`:

- **[.claude/settings.json](.claude/settings.json)** — workspace permissions allowlist (Bash, Edit/Write/Read, Agent, WebFetch/Search, Google Drive MCP). Keeps routine tool calls from prompting for approval.
- **[.claude/skills/README.md](.claude/skills/README.md)** — formatting conventions every `SKILL.md` in this workspace must follow (frontmatter shape, `$ARGUMENTS` usage, skill-vs-CLAUDE.md split).
- **[.claude/skills/better_prompts/SKILL.md](.claude/skills/better_prompts/SKILL.md)** — `/better-prompts <raw idea>`. Refines a vague idea into a structured prompt (role/goal/context/instructions/constraints/output_format XML blocks) via a short clarifying-question loop. Use when sketching a new prompt you'll reuse — e.g. a prompt that asks a downstream agent to "chart X vs Y from the warehouse."
- **[.claude/skills/fan_out_fan_in/SKILL.md](.claude/skills/fan_out_fan_in/SKILL.md)** — `/fan-out-fan-in <question>`. Dispatches 3–7 parallel sonnet research agents on distinct angles, then synthesizes their reports with one opus agent into a decision-ready brief. Good fit here for multi-angle CTG decisions like *"which source should we add next?"*, *"long vs wide table for intraday?"*, or *"how should we run the daily cron — GitHub Actions, Supabase cron, or a small VM?"* — questions where you want a recommendation, not five separate reports.

Skills are invoked as slash commands (e.g. `/better-prompts`, `/fan-out-fan-in`). Add new ones under `.claude/skills/<kebab-name>/SKILL.md` following the README conventions.

## Open design questions to revisit

- **Wide vs long table for observations**: currently long (one row per `(series, date)`). Cheap, flexible, but joins for multi-series charts cost a pivot. Consider materialized views once we have ~100 series.
- **Intraday data**: schema is daily-only (`ts` is `date`). When we want minute/hourly bars (e.g. crypto), add a separate `observations_intraday(series_id, ts timestamptz, value)` table.
- **Metadata creep**: keep `series` lean for now; if we start needing lots of provider-specific fields, add a `metadata jsonb` column.
- **Currency / FX normalization**: out of scope until we hit a use case.
