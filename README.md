# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs that analysts depend on: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.6 status

Core v0.6 is a test-ready Python modular monolith with scheduled monitoring, GitHub Pages test hosting, real-source validation, source-contract preflight, operational review, deterministic incident transitions, and a delivery-policy sandbox.

It supports:

- CSV, XLSX, JSON and HTTP GET JSON sources
- deterministic availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness checks
- explicit `numeric_fields` for APIs that publish numbers as strings
- explicit baseline plus recent Healthy-history comparison context
- independent monitoring cadence and upstream freshness expectations
- preflight-protected interactive/API source creation and editing
- environment-backed API headers without persisting secret values
- Acknowledged / Reviewed analyst state for unhealthy observations
- guarded Healthy-only baseline promotion
- derived incident lifecycle: Opened, Escalated, Recovered
- persisted transition notification candidates with duplicate-noise suppression
- opt-in per-source `notification_transitions` policy
- auditable candidate states: Pending, Eligible, Suppressed
- local FastAPI dashboard/API and read-only GitHub Pages views
- scheduled GitHub Actions monitoring and live-source smoke validation

**Core v0.6 still does not send notifications.** There is no email, Slack, Teams, webhook, SMS, provider adapter, destination configuration, or retry worker.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

## Hosted test sources

`config/sources.json` is the code-reviewed source list used by GitHub Actions. It currently includes:

- `demo-market`
- `bank-of-canada-usd-cad`
- `us-treasury-debt`

Keep this file free of secret values and secret query parameters. The live-source smoke gate repeatedly validates the public API integrations from GitHub Actions.

## Source preflight and editing

Run the local app:

```bash
analystwatch serve --host 127.0.0.1 --port 8000
```

The **Add source** flow performs non-persistent preflight before acceptance. Preflight can validate availability, non-empty data, numeric fields, unique keys and freshness evidence. Accepted sources do not get a baseline until their first real monitoring check.

Existing interactive/API source edits use the same server-side preflight. A failed edit leaves the prior definition, observations and baseline unchanged. `sync-sources` remains the explicit repository-reviewed path for hosted source configuration.

## Environment-backed API headers

Secret values are resolved from environment variables at request time and are never stored in `SourceDefinition`, SQLite source JSON, Git history, or Pages output.

```json
{
  "request_header_env": {
    "Authorization": "ANALYSTWATCH_API_TOKEN"
  }
}
```

Missing required environment variables become explicit source-availability evidence rather than crashes. The repository and `monitor-state` branch are currently public, so secret **values must never be committed or persisted there**.

## Incident lifecycle

Incident state is derived from immutable observation history.

- **Opened** — Healthy/no prior observation → Warning or Critical
- **Escalated** — Warning → Critical in an open incident
- **Recovered** — Warning/Critical → Healthy

Repeated Warning or repeated Critical observations at unchanged severity do not create another transition candidate.

```bash
analystwatch incident market_data
analystwatch notification-candidates --source-id market_data
```

Observation review state is independent: Acknowledged / Reviewed records analyst attention only and never changes Health or resolves an incident.

## Delivery policy sandbox

Each meaningful transition still creates an auditable notification candidate, but v0.6 evaluates whether that candidate would be eligible for a future delivery system.

A source opts in by listing transitions:

```json
{
  "notification_transitions": ["Opened", "Escalated", "Recovered"]
}
```

The safe default is an empty list. With no enabled transitions, new candidates are **Suppressed**.

Candidate states:

- **Eligible** — transition matched the source policy
- **Suppressed** — transition did not match the policy or no transitions were enabled
- **Pending** — legacy v0.5 candidate not yet explicitly policy-evaluated

Each evaluated candidate snapshots the enabled-transition policy, evaluation time and decision reason. Later source-policy edits do **not** rewrite historical decisions. Legacy Pending candidates can be evaluated once:

```bash
analystwatch evaluate-notification-candidates market_data
```

Repeat evaluation is idempotent because already evaluated candidates are skipped.

**Eligible does not mean delivered.** Core v0.6 has no send path.

## Baseline review

Baseline promotion remains a guarded operation:

```bash
analystwatch baseline-review market_data
analystwatch promote-baseline market_data \
  --observation-id <healthy-observation-id> \
  --expected-baseline-id <current-baseline-id>
```

Only a Healthy available candidate with a profile can be promoted, and the expected baseline guard prevents stale review from overwriting a newer baseline.

## GitHub Pages test deployment

Pages is read-only. GitHub Actions runs monitoring, persists the small test database on `monitor-state`, renders `site/`, and deploys the generated static artifact.

Pages can expose source contracts, review state, incident summaries, notification policy and Eligible/Suppressed/Pending counts. It exposes no delivery controls, strips API query strings from displayed locations, and does not render request-header environment-variable names.

## Verification

Repository gate:

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.6 functional head passed Ruff, compile, **58 tests**, and live-source smoke. During verification CI also caught and forced restoration of the approved **“Notification candidates”** UI label before the milestone closeout.

## Current limitations

- no outbound notification delivery
- no production delivery retry/idempotency lifecycle yet
- GitHub Pages is read-only and intended for testing
- `monitor-state` branch persistence is not a production database design
- authentication/workspace ownership is not implemented
- environment-backed headers are not a multi-user secret-management service
- GitHub cron execution can be delayed
- schema rename inference is not implemented
- historical detector context remains deterministic rolling Healthy medians, not forecasting/ML
- more real-source transition history is required before enabling a real delivery adapter

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
