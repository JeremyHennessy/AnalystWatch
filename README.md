# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs that analysts depend on: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.7 status

Core v0.7 is a test-ready Python modular monolith with scheduled monitoring, source-contract preflight, real-source validation, operational review, incident transitions, notification-policy evaluation, and an explicit dry-run delivery-attempt lifecycle.

It supports:

- CSV, XLSX, JSON and HTTP GET JSON sources
- deterministic availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness checks
- explicit baselines plus recent Healthy-history comparison context
- preflight-protected interactive/API source creation and editing
- environment-backed API headers without persisting secret values
- Acknowledged / Reviewed analyst state separate from technical Health
- guarded Healthy-only baseline promotion
- derived incident lifecycle: Opened, Escalated, Recovered
- auditable notification candidates: Pending, Eligible, Suppressed
- per-source opt-in `notification_transitions` policy
- explicit dry-run delivery attempts: Prepared, Succeeded, Failed
- idempotent attempt replay and controlled retry after failure
- local CLI/API inspection and read-only GitHub Pages summaries
- scheduled GitHub Actions monitoring and live-source smoke validation

**Core v0.7 still has no real notification delivery.** There is no email, Slack, Teams, webhook, SMS, provider SDK, destination configuration, background delivery worker, or generic send control. The only attempt adapter is `dry-run`, and it performs no external I/O or network request.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

## Hosted test sources

`config/sources.json` is the code-reviewed source list used by GitHub Actions. It currently includes `demo-market`, Bank of Canada USD/CAD, and U.S. Treasury Debt to the Penny. Keep repository configuration free of secret values and secret query parameters.

The hosted sources currently opt into no notification transitions, so candidates remain suppressed by default and no dry-run attempt is created automatically.

## Source preflight, editing and credentials

Run the local app:

```bash
analystwatch serve --host 127.0.0.1 --port 8000
```

Interactive/API creation and edits perform fresh server-side preflight before persistence. A failed edit leaves the prior definition, observations and baseline unchanged. Accepted new sources establish their baseline only on the first real monitoring check.

API header values are resolved from environment variables at request time. `request_header_env` stores only header-to-environment-variable references; secret values are not written into source definitions, SQLite source JSON, Git history, or Pages output.

## Incidents and notification policy

Incident state is derived from immutable observation history:

- **Opened** — Healthy/no prior observation → Warning or Critical
- **Escalated** — Warning → Critical in an open incident
- **Recovered** — Warning/Critical → Healthy

Repeated same-severity incident observations do not create duplicate transition candidates.

A source can opt specific transitions into notification eligibility:

```json
{
  "notification_transitions": ["Opened", "Escalated", "Recovered"]
}
```

The safe default is an empty list. Candidate states are:

- **Eligible** — transition matched the source policy
- **Suppressed** — transition did not match, or no transitions were enabled
- **Pending** — legacy candidate not yet explicitly policy-evaluated

Policy evaluation snapshots the enabled transitions, evaluation time and reason; later source edits do not rewrite historical decisions.

```bash
analystwatch incident market_data
analystwatch notification-candidates --source-id market_data
analystwatch evaluate-notification-candidates market_data
```

## Dry-run delivery attempts

An **Eligible** candidate can be explicitly exercised through the local dry-run adapter:

```bash
analystwatch dry-run-delivery <candidate-id> \
  --idempotency-key <caller-stable-key>

analystwatch delivery-attempts --candidate-id <candidate-id>
```

Attempt states are:

- **Prepared** — attempt persisted before adapter execution
- **Succeeded** — dry-run adapter completed successfully
- **Failed** — dry-run adapter reported or raised a failure

Semantics:

- attempts are never created automatically by monitoring;
- only Eligible candidates can be attempted;
- the same idempotency key returns the same persisted attempt without rerunning the adapter;
- a successful dry-run blocks another attempt for the same candidate/adapter;
- a failed attempt can be retried with a new idempotency key and incremented attempt number;
- a persisted Prepared attempt blocks a blind retry because the system refuses to guess whether a side effect occurred;
- notification-candidate policy state is not rewritten by attempt outcomes.

The `dry-run` adapter performs **no network or external I/O**. API equivalents are `GET /api/delivery-attempts` and `POST /api/delivery-attempts/dry-run`. There is no generic `/send` endpoint.

## Baseline and review semantics

Acknowledged/Reviewed records analyst attention only; it never changes Health or resolves an incident. Baseline promotion remains Healthy-only and requires the expected current baseline ID so stale review cannot overwrite a newer approved baseline.

## GitHub Pages test deployment

Pages remains read-only. It can display monitoring contracts, review state, incident summaries, notification policy/candidate counts, and dry-run attempt counts by state. It does not expose idempotency keys, attempt payloads, request-header environment-variable names, or delivery controls.

The temporary `monitor-state` branch remains test-only persistence and must contain only non-secret state.

## Verification

Repository gate:

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.7 functional checkpoint passed Ruff, compile, **66 tests**, and live-source smoke. During development CI also caught preservation of the approved no-delivery UI copy; the prior text was restored and the v0.7 dry-run clarification was added separately.

## Current limitations

- dry-run only; no outbound provider exists
- a crash can leave a Prepared attempt that requires future explicit reconciliation rather than automatic retry
- SQLite idempotency constraints are present, but concurrent production-grade claim/lease semantics are not yet implemented
- GitHub Pages is read-only and intended for testing
- `monitor-state` branch persistence is not a production database design
- authentication/workspace ownership is not implemented
- environment-backed headers are not a multi-user secret-management service
- GitHub cron execution can be delayed
- schema rename inference is not implemented
- historical detector context remains deterministic rolling Healthy medians, not forecasting/ML
- more real transition history is required before any real provider integration

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
