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
- **Sources** (7):
  - `fred.py` — FRED REST API
  - `yahoo.py` — Yahoo Finance via `yfinance`
  - `eia.py` — EIA v2 (energy spot prices, public domain)
  - `tiingo.py` — clean-license US equities/ETFs, total-return adjClose
  - `ecb.py` — ECB Data Portal SDMX-CSV (euro rates, FX, yield curve)
  - `dbnomics.py` — umbrella adapter for 93 macro providers (Eurostat, IMF, BIS, OECD, ...)
  - `frankfurter.py` — free FX rates (ECB reference rates) for EM pairs
- **Declarative series registry** at [registry.yaml](registry.yaml) — single source of truth. Currently 47 series.
- `runner.py --all` reads `registry.yaml` and updates every series (idempotent)
- Demo notebook: [notebooks/01_2s10s_demo.ipynb](notebooks/01_2s10s_demo.ipynb) — plots 10Y, 2Y, and the 2s10s spread; shades inverted periods

Warehouse currently holds **~270k observations** across 47 series: US Treasury curve, short rates, US macro (CPI, unemployment), equity indices, US ETFs (SPY/QQQ/IWM/DIA/TLT/IEF/HYG/LQD/EEM/EFA), FX/commodities, energy spot prices (WTI/Brent/Henry Hub/refined products), **euro-area rates/FX/yield curve (ECB)**, **euro-area macro (HICP, unemployment, GDP via DBnomics)**, and **EM FX pairs (BRL/MXN/ZAR/CNY/INR/TRY via Frankfurter)** — all backfilled to 2000-01-01 (or earliest available).

## What's NOT built yet

- **AAII / NAAIM sentiment** — deferred. AAII's public XLS now returns HTTP 403 (Imperva bot block) and NAAIM's current XLSX URL returns 404. Both require either fragile page scraping or a paid feed; coming back to these only if there's a strong macro signal we miss elsewhere.
- US Treasury direct (defensive cross-check vs FRED)
- Tests

## GitHub repository

- **Repo**: https://github.com/AugustineCarB/ctg_01 (**public**)
- **Default branch**: `main`
- **gh CLI** is authenticated locally as `AugustineCarB` via keyring (HTTPS, scopes: gist, read:org, repo). All git/gh commands work without prompting.

### Push hygiene

The repo is public, so before every commit Claude must:
1. Stage files **explicitly** — never `git add -A` or `git add .`. Sensitive files (`.env`, `supabase_info.md`) are gitignored but a stray `add -A` could still pull in something like a notebook checkpoint with embedded data.
2. Run the secret-check pattern before committing:
   ```bash
   git diff --cached | grep -iE "(eyJ|<known-secret-prefixes>)" || echo clean
   ```
3. Use the heredoc-via-file pattern for multi-line commit messages with special characters: write the message to `/tmp/ctg_commit_msg.txt`, then `git commit -F /tmp/ctg_commit_msg.txt`. (Inline heredoc with backticks in the message can crash bash quoting.)

### Commit message conventions

- One-line title (≤72 chars), imperative mood ("Add EIA source", not "Added").
- Wrapped body explaining **why** the change is shaped the way it is (especially workarounds — see the EIA pagination commit).
- Trailer: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- No `Generated with Claude Code` footer (kept terse).

### Working with the workflow

```bash
# manually trigger the daily cron
gh workflow run "Daily warehouse update" --repo AugustineCarB/ctg_01

# list recent runs
gh run list --workflow=daily.yml --repo AugustineCarB/ctg_01 --limit 5

# tail a specific run
gh run watch <RUN_ID> --repo AugustineCarB/ctg_01

# read full log of a finished run
gh run view <RUN_ID> --repo AugustineCarB/ctg_01 --log | less

# inspect which series errored in the last run (uses the runs table)
PYTHONPATH=src /opt/anaconda3/envs/ctg/bin/python -c "
from ctg.config import connect
with connect() as c, c.cursor() as cur:
    cur.execute(\"select source, error_message from runs where started_at > now() - interval '2 hours' and status='error';\")
    for row in cur.fetchall(): print(row)
"
```

### Local-dev vs CI environment

- **Local**: anaconda env `ctg` at `/opt/anaconda3/envs/ctg/bin/python` (Python 3.12).
- **CI** (`.github/workflows/daily.yml`): fresh `actions/setup-python@v5` with Python 3.12, then `pip install -r requirements.txt`.
- Anything new the code imports **must** be added to [requirements.txt](requirements.txt) or the cron breaks. The anaconda env is a superset; CI is the source of truth for "minimal deps to run."

### Common cron failures and what to check

| Symptom | Likely cause |
|---|---|
| `start > end` 4xx (Frankfurter, others) | Local backfill already loaded today's data; CI's `max(ts)+1` is now in the future. Source should guard with `if start > end: return`. |
| Yahoo `possibly delisted; no price data found` for crypto on weekends/holidays | Benign — `yfinance` warning on empty-range fetch, the `0 rows upserted` is fine. |
| `Tenant or user not found` (Postgres) | Pooler region changed or credentials rotated. Re-run `scripts/find_pooler_region.py`. |
| `404 NOT FOUND` from DBnomics | Series ID changed upstream. Use `https://api.db.nomics.world/v22/series/<provider>/<dataset>?q=<keyword>&limit=8` to find the new code. |
| EIA returns rows from the wrong date | EIA's `start` param is silently ignored at large `length`. Source already filters client-side; if you regress this, the symptom is "incremental run loads thousands of historical rows." |

## Daily cron (GitHub Actions)

[.github/workflows/daily.yml](.github/workflows/daily.yml) runs `python -m ctg.runner --all` every day at **23:00 UTC** (7pm ET / 4pm PT). One workflow refreshes every series in `registry.yaml`; monthly/quarterly series cost ~200 ms each because the runner is incremental and idempotent — no point splitting by frequency.

The workflow ends with a summary step that prints `series by source`, total observation count, and a per-source success/error breakdown for the run.

Trigger manually with `gh workflow run "Daily warehouse update"` or via the Actions tab.

### Required GitHub secrets

Mirror everything in `.env`:

| Secret | Source |
|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_HOST`, `SUPABASE_DB_PORT`, `SUPABASE_DB_NAME`, `SUPABASE_DB_USER`, `SUPABASE_DB_PASSWORD` | Supabase project settings |
| `FRED_API_KEY` | fred.stlouisfed.org |
| `EIA_API_KEY` | eia.gov/opendata/register.php |
| `TIINGO_API_KEY` | tiingo.com account → API token |

Set them all at once from local `.env`:

```bash
source .env
for k in SUPABASE_URL SUPABASE_SERVICE_KEY SUPABASE_DB_HOST SUPABASE_DB_PORT \
        SUPABASE_DB_NAME SUPABASE_DB_USER SUPABASE_DB_PASSWORD \
        FRED_API_KEY EIA_API_KEY TIINGO_API_KEY; do
  gh secret set "$k" --body "${!k}" --repo AugustineCarB/ctg_01
done
```

## Conventions

- **Series IDs** are always `"<SOURCE>:<native_code>"` in UPPERCASE for the source, native casing for the code (FRED uses upper, Yahoo can be mixed). Example: `FRED:DGS10`, `YAHOO:^GSPC`.
- **Idempotency is non-negotiable.** Every loader path must be safe to re-run on the same day.
- **Incremental by default.** If `--since` is omitted, the runner picks up from `max(ts) + 1 day` per series.
- **Rates**: FRED allows ~120 req/min, no auth issues at our volume. Yahoo is unofficial — batch where possible.
- **Secrets**: only in `.env` (gitignored). `supabase_info.md` is also gitignored — delete it after copying values.
- **EIA quirk**: the v2 ``start`` query parameter is silently ignored when ``length>10``-ish. The source filters client-side instead — EIA returns rows newest→oldest, we stop paging once we cross ``start``.

## Running things

This project runs in a dedicated conda env `ctg` (Python 3.12), isolated from other envs on the machine. The Jupyter kernel `CTG (Python 3.12)` points at the same interpreter, so notebooks and CLI runs share one environment.

```bash
# one-time: create the env + register the Jupyter kernel
/opt/anaconda3/bin/conda create -n ctg python=3.12 -y
/opt/anaconda3/envs/ctg/bin/pip install psycopg2-binary python-dotenv pandas requests pyyaml yfinance matplotlib ipykernel
/opt/anaconda3/envs/ctg/bin/python -m ipykernel install --user --name ctg --display-name "CTG (Python 3.12)"

# apply migrations
PYTHONPATH=src /opt/anaconda3/envs/ctg/bin/python scripts/apply_migrations.py

# update every series in registry.yaml (incremental — picks up from max(ts)+1 per series)
PYTHONPATH=src /opt/anaconda3/envs/ctg/bin/python -m ctg.runner --all

# backfill every series from a specific date
PYTHONPATH=src /opt/anaconda3/envs/ctg/bin/python -m ctg.runner --all --since 2000-01-01

# update a single series (ad hoc)
PYTHONPATH=src /opt/anaconda3/envs/ctg/bin/python -m ctg.runner --source FRED --code DGS10
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
- **[.claude/skills/brand_chart/SKILL.md](.claude/skills/brand_chart/SKILL.md)** — `/brand-chart [target]`. Stamps the Clocktower logo (`creative_assets/ctg_logo.png`) as a bottom-right watermark on matplotlib charts. Use when writing a new chart or retrofitting existing notebooks/scripts so every chart in the project carries consistent branding. Pass a file path, `"all"`, or leave blank when branding a chart you're about to write inline.

Skills are invoked as slash commands (e.g. `/better-prompts`, `/fan-out-fan-in`, `/brand-chart`). Add new ones under `.claude/skills/<kebab-name>/SKILL.md` following the README conventions.

## Open design questions to revisit

- **Wide vs long table for observations**: currently long (one row per `(series, date)`). Cheap, flexible, but joins for multi-series charts cost a pivot. Consider materialized views once we have ~100 series.
- **Intraday data**: schema is daily-only (`ts` is `date`). When we want minute/hourly bars (e.g. crypto), add a separate `observations_intraday(series_id, ts timestamptz, value)` table.
- **Metadata creep**: keep `series` lean for now; if we start needing lots of provider-specific fields, add a `metadata jsonb` column.
- **Currency / FX normalization**: out of scope until we hit a use case.
