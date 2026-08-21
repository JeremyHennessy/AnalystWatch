# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs that analysts depend on: stale data, schema changes, unexpected row loss, null explosions, numerical scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.5 status

Core v0.5 is a test-ready Python modular monolith with scheduled monitoring, GitHub Pages test hosting, real-source validation, source-contract preflight, operational review controls, and deterministic incident transitions. It supports:

- CSV, XLSX, JSON and HTTP GET JSON sources
- deterministic availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness checks
- explicit `numeric_fields` for APIs that publish numeric values as strings
- explicit baseline plus recent Healthy-history comparison context
- independent monitoring cadence and upstream freshness expectations
- source preflight before interactive/API creation or editing
- environment-backed API request headers without persisting secret values
- Acknowledged / Reviewed analyst review state for unhealthy observations
- guarded Healthy-only baseline promotion
- deterministic incident lifecycle: Opened, Escalated, Recovered
- persisted Pending notification **candidates** for meaningful incident transitions
- suppression of repeated notification candidates while an incident remains at the same severity
- local FastAPI dashboard/API and read-only GitHub Pages views
- scheduled GitHub Actions monitoring and live-source smoke validation

Core v0.5 does **not** send notifications. There is no email, Slack, webhook, SMS, retry worker, or external delivery adapter in this milestone.

It also does not yet include user authentication, billing, enterprise warehouses, BI integrations, or LLM-dependent detection.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

## Repository-configured sources

`config/sources.json` is the source list used by the GitHub Actions test monitor. Keep this file free of credentials and secret query parameters.

```bash
analystwatch sync-sources config/sources.json
analystwatch schedule
analystwatch check-due
```

The hosted test configuration currently includes:

- `demo-market` — checked-in deterministic CSV fixture
- `bank-of-canada-usd-cad` — Bank of Canada USD/CAD daily observations
- `us-treasury-debt` — U.S. Treasury Debt to the Penny

The Treasury API publishes numeric amounts as JSON strings. Those amount fields are explicitly listed in `numeric_fields`, so AnalystWatch profiles them numerically without broadly coercing numeric-looking identifiers.

The live-source smoke gate has repeatedly verified the Bank of Canada and U.S. Treasury sources from GitHub Actions. That establishes integration behavior at those checkpoints, not long-run false-positive/false-negative performance.

## Add, validate and edit a source locally

Run the local dashboard:

```bash
analystwatch serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, then choose **Add source**. The onboarding flow separates validation from persistence:

1. define the source and contracts AnalystWatch should enforce;
2. run **Preflight**;
3. AnalystWatch ingests and profiles the candidate without saving it;
4. resolve blocking contract errors;
5. add the source only when preflight reports **Ready**.

Preflight validates source availability/non-empty data and, where configured, numeric fields, unique keys, and freshness evidence. A stale-but-structurally-valid source may produce a freshness warning without becoming an invalid source contract.

Existing source definitions can be replaced through `PUT /api/sources/{source_id}` or the CLI only after the replacement definition passes the same preflight. A failed edit leaves the previous definition, observations and baseline unchanged. Source IDs cannot change during an edit.

A newly accepted source is stored without creating an observation or baseline. Its first normal monitoring check establishes the baseline.

## Environment-backed API headers

Secret values are not stored in `SourceDefinition`, SQLite source JSON, Git branches, or Pages output. A source maps a header to an environment-variable name:

```json
{
  "request_header_env": {
    "Authorization": "ANALYSTWATCH_API_TOKEN",
    "X-Api-Key": "VENDOR_API_KEY"
  }
}
```

At request time AnalystWatch reads those environment variables and sends their values as HTTP headers. If a configured environment variable is missing, the source becomes unavailable with explicit evidence rather than crashing the monitor.

```bash
analystwatch add-source \
  --id secured_api \
  --name "Secured API" \
  --type api \
  --location https://example.test/data \
  --request-header-env Authorization=ANALYSTWATCH_API_TOKEN
```

The repository and `monitor-state` branch are currently public. Secret **values must never be committed or written to `monitor-state`**. Hosted authenticated sources should use intentionally configured GitHub Actions secrets/environment variables.

## Operational review

A Warning/Critical observation may be marked **Acknowledged** or **Reviewed**. This records analyst attention only. It does not alter the observation's Health, findings, incident state, or claim that the source problem is resolved.

## Incident transitions

Core v0.5 derives the latest incident from immutable observation history rather than maintaining a separately mutable incident record.

Meaningful transitions are:

- **Opened** — Healthy/no prior observation → Warning or Critical
- **Escalated** — Warning → Critical within an open incident
- **Recovered** — Warning/Critical → Healthy

Repeated Warning or repeated Critical observations inside the same ongoing incident do not create another transition candidate. A recovered incident remains reconstructable even after later Healthy checks.

Inspect the derived incident:

```bash
analystwatch incident market_data
```

## Notification candidates — no delivery

Each Opened, Escalated, or Recovered transition can create one `Pending` notification candidate. The candidate and the transition observation are persisted in the **same SQLite transaction** so one cannot be committed without the other.

Inspect candidates:

```bash
analystwatch notification-candidates
analystwatch notification-candidates --source-id market_data
```

Candidates are evidence that a future delivery policy *could* act. Core v0.5 does not deliver them anywhere. The API endpoints are read-only:

- `GET /api/sources/{source_id}/incident`
- `GET /api/notification-candidates`

The source detail page and static Pages view show incident lifecycle and candidate counts but provide no send controls.

## Baseline review

The first successful monitoring observation becomes the baseline. A later baseline change is guarded:

```bash
analystwatch baseline-review market_data
analystwatch promote-baseline market_data \
  --observation-id <healthy-observation-id> \
  --expected-baseline-id <current-baseline-id>
```

Only a Healthy, available observation with a profile can be promoted. Promotion verifies the current baseline is still the baseline that was reviewed; a changed baseline requires a fresh review.

After enough recent Healthy observations exist, AnalystWatch can use their median as the operational reference for row count, null rate, numeric median and key duplication while still retaining/exposing the explicit approved baseline.

## GitHub Pages test deployment

GitHub Pages is static hosting, so FastAPI and write operations do not run there. `.github/workflows/pages.yml` runs AnalystWatch in GitHub Actions, stores the small test SQLite database on the dedicated `monitor-state` branch, renders `site/`, and deploys that read-only snapshot.

The repository is currently public. Therefore `monitor-state` is public and **must contain only non-secret test state**. Branch-backed persistence is temporary test infrastructure, not a production database design.

Pages exposes monitoring contracts, review state, derived incident summaries, and candidate counts. API query strings are stripped from displayed API locations, request-header environment-variable names are not exposed in static Pages output, and no delivery action is available.

The workflow runs:

- after pushes to `main` — all enabled sources
- manually — all enabled sources
- hourly at minute 17 — only sources currently due

For local static export testing:

```bash
analystwatch build-pages --output site
python -m http.server 8080 --directory site
```

## Live-source validation

Pull requests that change live-source configuration or relevant ingestion/profile/service code run `.github/workflows/live-source-smoke.yml`.

The smoke gate verifies that enabled configured sources remain available, profile successfully, do not become Critical on their initial smoke observation, preserve configured numeric contracts, and expose parseable configured freshness dates.

This complements deterministic tests; it does not replace them.

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

The v0.5 functional candidate passed Ruff, compile, **50 tests**, and the live-source smoke gate. CI runs the same repository gate on pushes and pull requests.

## Architecture

```text
candidate/edit -> preflight -> accept definition
                               |
                               v
source config -> schedule -> ingestion -> profile -> deterministic detectors
                                      |                 |
                                      |                 v
                                      |       baseline + healthy history
                                      v                 |
                                  SQLite <--------------+
                                      |
                  immutable observation history
                     |            |             |
                  review       incident      guarded
                   state       derivation     baseline
                                  |
                       transition candidate
                    (atomic with observation)
                                  |
                        NO DELIVERY IN v0.5
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).

## Current limitations

- GitHub Pages is read-only and intended for testing.
- `monitor-state` branch persistence is not a production database design.
- The current public repository means all branch-persisted test state is public.
- GitHub cron execution can be delayed.
- Environment-backed API headers are implemented, but there is no multi-user secret-management service or credentials UI.
- Notification candidates are persisted but **not delivered**.
- Authentication/workspace ownership is not implemented.
- Date-field inference is opt-in and intentionally conservative.
- Schema rename inference is not implemented.
- Historical context is a deterministic rolling Healthy median, not forecasting/ML.
- Real-source history is still insufficient to quantify long-run false-positive/false-negative rates.
