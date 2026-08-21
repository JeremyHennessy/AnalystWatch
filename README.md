# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in the CSV, Excel, JSON and REST API inputs that analysts depend on: stale data, schema changes, unexpected row loss, null explosions, numerical scaling shifts, category changes and key duplication. The top-level question is simple: **can I trust the data feeding my analysis today?**

## Core v0.1 status

Core v0.1 is a local proof-of-concept modular monolith. It supports:

- CSV, XLSX, JSON and unauthenticated HTTP GET JSON sources
- source profiles for schema, row count, nulls, cardinality, numeric distributions and material categories
- deterministic availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness checks
- retained observations and an explicit baseline
- Healthy / Warning / Critical source state with evidence-backed findings
- a CLI, JSON API and intentionally simple web dashboard

It does **not** include authentication, billing, notifications, enterprise warehouses, BI integrations, LLM-dependent detection, or embedded scheduling.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

## Add and check a source

```bash
analystwatch add-source \\
  --id market_data \\
  --name "Market Data" \\
  --type csv \\
  --location ./market_data.csv \\
  --unique-key id

analystwatch check market_data
analystwatch list
```

The first successful observation becomes the baseline. To explicitly accept a later observation as the new baseline:

```bash
analystwatch promote-baseline market_data
```

For freshness, configure either file age or a date field:

```bash
analystwatch add-source \\
  --id economic_api \\
  --name "Economic API" \\
  --type api \\
  --location https://example.test/data \\
  --expected-refresh-minutes 1440 \\
  --latest-date-field as_of
```

## Dashboard

```bash
analystwatch serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The dashboard shows current health; each source page shows findings, baseline/current evidence and recent history. Sources can also be created with `POST /api/sources` and checked with `POST /api/sources/{id}/check`.

## Demonstrate the core signal

```bash
python scripts/run_demo.py
```

The demo establishes a healthy CSV baseline, divides the `amount` values by 100 without changing schema or volume, then runs AnalystWatch again. The expected result is Critical numeric drift with a **possible scaling/unit change** explanation—not an unsupported claim about root cause.

## Test / repository gate

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

CI runs the same gate on pushes and pull requests.

## Architecture

```text
source -> ingestion -> profile -> deterministic detectors -> health/findings
                                                |
                                                v
                                    SQLite observation history
                                                |
                                                v
                                      CLI / FastAPI dashboard
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the decision and tradeoffs and [`docs/MILESTONES.md`](docs/MILESTONES.md) for scope.

## Current limitations

- API authentication/secret storage is not implemented.
- API content freshness requires a configured `latest_date_field`; HTTP 200 alone is not freshness evidence.
- JSON is limited to analyst-friendly record structures documented in the architecture file.
- Rename-looking schema changes are not inferred yet; added/removed columns are reported without claiming a rename.
- SQLite and the local dashboard are proof-of-concept infrastructure, not a multi-tenant SaaS architecture.
- Detection is intentionally deterministic and threshold-based; historical multi-window anomaly models are later work.
