# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, unexpected row loss, null explosions, numerical scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.8 status

Core v0.8 is a test-ready Python modular monolith with scheduled monitoring, source-contract preflight, real-source validation, operational review, incident transitions, notification policy, and a hardened dry-run delivery-attempt lifecycle.

It supports:

- CSV, XLSX, JSON and HTTP GET JSON sources
- deterministic reliability detectors with explicit baseline + Healthy-history context
- preflight-protected source creation/editing
- environment-backed API headers without persisting secret values
- Acknowledged / Reviewed analyst state separate from technical Health
- guarded Healthy-only baseline promotion
- derived Opened / Escalated / Recovered incident lifecycle
- Pending / Eligible / Suppressed notification candidates
- per-source opt-in `notification_transitions`
- explicit dry-run delivery attempts: Prepared / Succeeded / Failed
- atomic SQLite attempt claiming under `BEGIN IMMEDIATE`
- caller idempotency and concurrent claim protection
- explicit reconciliation of abandoned Prepared attempts
- optional delivery retry delay independent from monitoring cadence
- CLI/API inspection and read-only GitHub Pages summaries

**Core v0.8 still has no real notification delivery.** There is no email, Slack, Teams, webhook, SMS, provider SDK, background delivery worker, automatic retry worker, automatic Prepared timeout, or generic send control. The only adapter is local `dry-run`, with no network or external I/O.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

## Monitoring and source contracts

The hosted test configuration remains `config/sources.json` with `demo-market`, Bank of Canada USD/CAD, and U.S. Treasury Debt to the Penny. Hosted sources still enable no notification transitions, so no delivery attempt is created automatically.

Interactive/API source creation and edits perform fresh preflight before persistence. Failed edits preserve the previous definition, observations, and baseline. API secret values are resolved from environment variables at request time and are not written into source definitions, SQLite source JSON, Git history, or Pages output.

## Incidents and notification policy

Incident transitions remain deterministic:

- **Opened** — Healthy/no prior observation → Warning or Critical
- **Escalated** — Warning → Critical
- **Recovered** — Warning/Critical → Healthy

Repeated same-severity unhealthy observations do not create duplicate transition candidates. Source policy can opt transitions into eligibility with `notification_transitions`; the default is empty, so candidates are suppressed.

## Dry-run attempts

Only an **Eligible** candidate can be explicitly dry-run attempted:

```bash
analystwatch dry-run-delivery <candidate-id> --idempotency-key <stable-key>
analystwatch delivery-attempts --candidate-id <candidate-id>
```

Attempt states:

- **Prepared** — persisted before adapter execution
- **Succeeded** — dry-run completed
- **Failed** — dry-run reported/raised failure

Claiming is now atomic. Candidate eligibility, idempotency replay, latest state, retry timing, attempt-number allocation, and Prepared insertion happen in one SQLite `BEGIN IMMEDIATE` transaction. Concurrent callers using the same key resolve to one claim plus replay; different keys cannot both claim the same candidate while a Prepared attempt exists.

## Retry timing

`delivery_retry_minutes` is independent from `monitor_interval_minutes`. Its default is **0 minutes** to preserve v0.7 immediate retry behavior. A source may opt into a delay:

```json
{
  "delivery_retry_minutes": 30
}
```

Inspect readiness without executing anything:

```bash
analystwatch delivery-retry-status <candidate-id>
```

A failed attempt is retryable only at/after `completed_at + delivery_retry_minutes`.

## Prepared reconciliation

A crash can leave a Prepared attempt. v0.8 still refuses a blind retry. Instead, an operator must explicitly reconcile it after reviewing evidence:

```bash
analystwatch reconcile-delivery-attempt <attempt-id> \
  --outcome Failed \
  --note "Reviewed evidence and confirmed the dry run did not complete."
```

Outcome must be `Succeeded` or `Failed`; the note is required. Reconciliation records timestamp + note. Failed reconciliation enters the configured retry-delay rules. Succeeded reconciliation blocks future attempts for that candidate/adapter.

API equivalents:

- `GET /api/delivery-attempts/retry-status`
- `POST /api/delivery-attempts/{attempt_id}/reconcile`
- existing `GET /api/delivery-attempts`
- existing `POST /api/delivery-attempts/dry-run`

There is no generic send route.

## Pages / public-output boundary

GitHub Pages remains read-only. It exposes the retry-delay configuration and aggregate candidate/attempt state counts, but not idempotency keys, reconciliation notes, attempt payloads, request-header environment-variable names, or reconciliation controls. Previously approved `Notification candidates` and no-delivery copy remain preserved.

## Verification

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.8 functional checkpoint passed Ruff, compile, **75 tests**, and live-source smoke. The test suite includes real concurrent SQLite claim tests for same-key replay and different-key exclusion.

## Current limitations

- dry-run only; no outbound provider exists
- reconciliation is manual; there is no automatic Prepared timeout
- SQLite `BEGIN IMMEDIATE` provides current single-database claim safety, not distributed multi-node leasing
- retry timing is modeled but there is no automatic retry worker
- GitHub Pages is read-only/testing only
- `monitor-state` branch persistence is not production storage
- authentication/workspace ownership is not implemented
- environment-backed headers are not a multi-user secret-management service
- more real incident/candidate history is required before any provider integration

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
