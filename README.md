# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs that analysts depend on: stale data, schema changes, unexpected row loss, null explosions, numerical scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.2.1 status

Core v0.2.1 is a test-ready Python modular monolith with scheduled monitoring, a GitHub Pages test surface, and initial validation against real public APIs. It supports:

- CSV, XLSX, JSON and unauthenticated HTTP GET JSON sources
- source profiles for schema, row count, nulls, cardinality, numeric distributions and material categories
- explicit `numeric_fields` contracts for APIs that publish numeric values as strings
- deterministic availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness checks
- explicit baseline plus recent Healthy-history comparison context
- independent check cadence and source-freshness expectations
- retained observations and baseline promotion
- Healthy / Warning / Critical state with evidence-backed findings
- CLI, JSON API and local FastAPI dashboard
- generated read-only GitHub Pages dashboard
- scheduled GitHub Actions monitoring for testing
- a live-source smoke gate for repository-configured sources

It does **not** include authentication, billing, notification delivery, authenticated API secrets, enterprise warehouses, BI integrations, or LLM-dependent detection.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

## Repository-configured sources

`config/sources.json` is the source list used by the GitHub Actions test monitor. Keep this file free of credentials or secret query parameters.

```bash
analystwatch sync-sources config/sources.json
analystwatch schedule
analystwatch check-due
```

The hosted test configuration currently includes:

- `demo-market` — checked-in deterministic CSV fixture
- `bank-of-canada-usd-cad` — Bank of Canada USD/CAD daily observations
- `us-treasury-debt` — U.S. Treasury Debt to the Penny

The Treasury API publishes numeric amounts as JSON strings. Those amount fields are explicitly listed in `numeric_fields`, so AnalystWatch profiles them numerically and can detect scaling/distribution changes without automatically treating numeric-looking IDs or codes as numbers.

The first live-source smoke run on August 21, 2026 verified both public APIs from GitHub Actions: each returned 30 usable rows, both configured freshness fields parsed successfully, and all configured numeric fields were profiled numerically. That is an initial integration verification, not yet evidence of long-term false-positive performance.

## Add a source manually

```bash
analystwatch add-source \
  --id market_data \
  --name "Market Data" \
  --type csv \
  --location ./market_data.csv \
  --monitor-interval-minutes 60 \
  --unique-key id

analystwatch check market_data
analystwatch list
```

Monitoring cadence and freshness are separate. This checks every hour but expects the source itself to refresh daily:

```bash
analystwatch add-source \
  --id economic_api \
  --name "Economic API" \
  --type api \
  --location https://example.test/data \
  --monitor-interval-minutes 60 \
  --expected-refresh-minutes 1440 \
  --latest-date-field as_of
```

Date inference is deliberately opt-in:

```bash
analystwatch add-source \
  --id inferred_api \
  --name "Inferred Date API" \
  --type api \
  --location https://example.test/data \
  --expected-refresh-minutes 1440 \
  --infer-latest-date-field
```

For source-specific parsing contracts such as `numeric_fields`, use `config/sources.json`; this keeps hosted test configuration explicit and reviewable.

## Baselines and signal quality

The first successful observation becomes the baseline. To explicitly accept a later observation:

```bash
analystwatch promote-baseline market_data
```

After enough recent Healthy observations exist, AnalystWatch uses their median as an operational reference for row count, null rate, numeric median and key-duplication checks. Findings still expose the explicit baseline so gradual healthy growth does not erase the approved reference point.

## Local dashboard

```bash
analystwatch serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## GitHub Pages test deployment

GitHub Pages is static hosting, so FastAPI does not run there. `.github/workflows/pages.yml` runs AnalystWatch in GitHub Actions, stores the small test SQLite database on the dedicated `monitor-state` branch, renders `site/`, and deploys that read-only snapshot to Pages.

The repository is currently public. Therefore `monitor-state` is also public and **must contain only non-secret test state**. Do not store credentials, authenticated API headers, secret query parameters, or sensitive datasets in that branch/database. This branch-based persistence is temporary test infrastructure, not the production storage design.

The workflow runs:

- after pushes to `main` — all enabled sources
- manually — all enabled sources
- hourly at minute 17 — only sources currently due

GitHub Pages must be configured to use **GitHub Actions** as its publishing source. The workflow then uses GitHub's official Pages artifact/deployment actions.

For local static export testing:

```bash
analystwatch build-pages --output site
python -m http.server 8080 --directory site
```

## Live-source validation

Pull requests that change live-source configuration or the relevant ingestion/profile/service code run `.github/workflows/live-source-smoke.yml`.

The smoke gate checks each enabled configured source and fails when:

- the source is unavailable or produces no profile
- the source resolves to Critical on its first observation
- a configured numeric field is missing or is not profiled numerically
- a configured freshness field has no parseable date

This complements deterministic mocked tests; it does not replace them.

## Demonstrate the core signal

```bash
python scripts/run_demo.py
```

The demo establishes a healthy CSV baseline, divides `amount` values by 100 without changing schema or volume, then detects Critical numeric drift with a **possible scaling/unit change** explanation rather than asserting an unsupported root cause.

## Test / repository gate

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

CI runs the same gate on pushes and pull requests.

## Architecture

```text
source config -> schedule -> ingestion -> profile -> deterministic detectors
                                      |                 |
                                      |                 v
                                      |       baseline + healthy history
                                      v                 |
                                  SQLite <--------------+
                                      |
                      +---------------+----------------+
                      |                                |
                 FastAPI local                  static Pages export
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).

## Current limitations

- GitHub Pages is read-only and intended for testing.
- Test-state persistence on `monitor-state` is not the production storage design.
- The current public repository means all branch-persisted test state is public.
- GitHub cron execution can be delayed.
- API authentication/secret storage is not implemented.
- Date-field inference is opt-in and intentionally conservative.
- Rename-looking schema changes are not inferred yet.
- Historical context is a deterministic rolling Healthy median, not forecasting/ML.
- Real-source validation has begun but has not yet accumulated enough history to quantify long-run false-positive/false-negative rates.
- Notifications are intentionally deferred until real-world signal quality is validated further.
