# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs that analysts depend on: stale data, schema changes, unexpected row loss, null explosions, numerical scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.4 status

Core v0.4 is a test-ready Python modular monolith with scheduled monitoring, a GitHub Pages test surface, real-source validation, contract preflight, and an operational review layer. It supports:

- CSV, XLSX, JSON and HTTP GET JSON sources
- source profiles for schema, row count, nulls, cardinality, numeric distributions and material categories
- explicit `numeric_fields` contracts for APIs that publish numeric values as strings
- deterministic availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness checks
- explicit baseline plus recent Healthy-history comparison context
- independent check cadence and source-freshness expectations
- retained observations and guarded baseline promotion
- Healthy / Warning / Critical state with evidence-backed findings
- source preflight that validates a candidate without saving it or creating a baseline
- preflight-protected creation and editing of source definitions
- environment-backed API request headers without storing secret values in source definitions
- Acknowledged / Reviewed operational state for unhealthy observations
- local onboarding UI, JSON API and FastAPI dashboard
- generated read-only GitHub Pages dashboard
- scheduled GitHub Actions monitoring for testing
- a live-source smoke gate for repository-configured sources

It does **not** include user authentication, billing, notification delivery, enterprise warehouses, BI integrations, or LLM-dependent detection.

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

The Treasury API publishes numeric amounts as JSON strings. Those amount fields are explicitly listed in `numeric_fields`, so AnalystWatch profiles them numerically and can detect scaling/distribution changes without automatically treating numeric-looking IDs or codes as numbers.

The live-source smoke gate has repeatedly verified the Bank of Canada and U.S. Treasury sources from GitHub Actions. That establishes integration behavior at those checkpoints, not long-term false-positive or false-negative performance.

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
5. add the monitored source only when preflight reports **Ready**.

Preflight validates, where configured:

- source availability and non-empty data
- numeric fields and their parseability
- unique-key presence, nulls and duplicates
- freshness-field presence and date parseability
- whether a configured refresh expectation has usable freshness evidence

A stale-but-structurally-valid source can surface a freshness warning without making the contract invalid. Blocking errors prevent onboarding.

Existing source definitions can be replaced through `PUT /api/sources/{source_id}` or the CLI only after the replacement definition passes the same preflight checks. A failed edit leaves the existing definition, observations and baseline unchanged. Source IDs cannot change during an edit.

A newly accepted source is saved without creating an observation or baseline; its first explicit/scheduled monitoring check establishes the baseline.

## Environment-backed API headers

Secret values are not stored in `SourceDefinition`, SQLite source JSON, Git branches, or Pages output. A source can instead map an HTTP header to an environment variable name:

```json
{
  "request_header_env": {
    "Authorization": "ANALYSTWATCH_API_TOKEN",
    "X-Api-Key": "VENDOR_API_KEY"
  }
}
```

At request time AnalystWatch reads those environment variables and sends their values as headers. If a required environment variable is missing, the source becomes unavailable with explicit evidence rather than crashing the monitor.

For CLI configuration:

```bash
analystwatch add-source \
  --id secured_api \
  --name "Secured API" \
  --type api \
  --location https://example.test/data \
  --request-header-env Authorization=ANALYSTWATCH_API_TOKEN
```

The current repository and `monitor-state` branch are public. Environment-variable **names** may appear in local source configuration, but secret **values must never be committed or written to `monitor-state`**. Hosted authenticated sources should use GitHub Actions secrets/environment variables when that workflow is intentionally configured for them.

## Operational review

An unhealthy observation may be marked **Acknowledged** or **Reviewed**. This records analyst attention only; it does **not** change the observation health or claim that the upstream problem is resolved.

The local source-detail page exposes this workflow for Warning/Critical observations. Pages remains read-only and may display the review state.

## Baseline review

The first successful monitoring observation becomes the baseline. A later baseline change is now a guarded review operation:

```bash
analystwatch baseline-review market_data
analystwatch promote-baseline market_data \
  --observation-id <healthy-observation-id> \
  --expected-baseline-id <current-baseline-id>
```

Only a Healthy, available observation with a profile can be promoted. Promotion also verifies that the current baseline is still the baseline that was reviewed; if it changed in the meantime, the operation stops and requires a fresh review.

After enough recent Healthy observations exist, AnalystWatch uses their median as an operational reference for row count, null rate, numeric median and key-duplication checks. Findings still expose the explicit baseline so gradual healthy growth does not erase the approved reference point.

## GitHub Pages test deployment

GitHub Pages is static hosting, so FastAPI and write operations do not run there. `.github/workflows/pages.yml` runs AnalystWatch in GitHub Actions, stores the small test SQLite database on the dedicated `monitor-state` branch, renders `site/`, and deploys that read-only snapshot to Pages.

The repository is currently public. Therefore `monitor-state` is also public and **must contain only non-secret test state**. This branch-backed persistence is temporary test infrastructure, not the production storage design.

The Pages source detail exposes the monitoring contract and operational review state. API query strings are stripped from displayed API locations, and environment-variable names for configured request headers are not exposed in static Pages output.

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
                         review state + baseline guard
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
- Environment-backed API headers are implemented, but there is not yet a multi-user secret-management service or credentials UI.
- Date-field inference is opt-in and intentionally conservative.
- Rename-looking schema changes are not inferred yet.
- Historical context is a deterministic rolling Healthy median, not forecasting/ML.
- Real-source history is still insufficient to quantify long-run false-positive/false-negative rates.
- Notifications remain deferred until signal quality is validated further.
