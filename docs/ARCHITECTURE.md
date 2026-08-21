# AnalystWatch Core v0.8 Architecture

## Decision

Core v0.8 remains a Python modular monolith. FastAPI is the local/API control surface; GitHub Pages is generated read-only test output. The monitoring engine remains authoritative. Review state, incident state, notification-policy decisions, and delivery attempts are downstream operational records and never rewrite detector findings or Health.

SQLite persists source definitions, observations, review state, notification candidates, delivery attempts, profiles, and baseline selection. `monitor-state` remains temporary public test persistence and must contain only non-secret state.

## Data flow

```text
source -> preflight/config -> schedule -> ingest -> profile -> detectors
                                                |
                                                v
                                      immutable Observation
                                          |      |      |
                                       review incident baseline
                                                |
                                      transition candidate
                                                |
                                      notification policy
                                  Pending / Eligible / Suppressed
                                                |
                                  explicit dry-run execution only
                                                |
                                 atomic SQLite attempt claim
                                                |
                                             Prepared
                                                |
                                      local dry-run adapter
                                         /             \
                                  Succeeded           Failed
                                      |                 |
                                      |           optional retry delay
                                      |                 |
                                      +------ explicit retry --------+

abandoned Prepared -> explicit reconciliation review -> Succeeded / Failed
```

No monitoring transaction automatically executes a delivery attempt.

## Atomic claim safety

v0.7 enforced idempotency sequentially in the service. v0.8 moves the concurrency-critical decision into `Storage.claim_delivery_attempt` under one SQLite `BEGIN IMMEDIATE` transaction.

The transaction covers:

1. candidate existence and Eligible state;
2. caller idempotency-key lookup;
3. latest candidate/adapter attempt state;
4. configured retry timing;
5. attempt-number allocation;
6. Prepared insert.

Same-key concurrent callers converge on the same persisted attempt. Different keys cannot create two Prepared attempts for the same candidate/adapter. SQLite also retains unique constraints on the idempotency key and `(candidate_id, adapter, attempt_number)`.

This is adequate for the current single SQLite database. It is not a distributed lease/claim system for multiple database nodes.

## Retry timing

`MonitoringConfig.delivery_retry_minutes` is independent from monitoring cadence. The default is `0`, preserving v0.7 immediate retry after a Failed attempt. Nonzero delay is opt-in.

`DeliveryRetryDecision` reports whether a candidate is currently retryable and the next retry timestamp when applicable.

Rules:

- no attempt yet -> due;
- Succeeded -> not due;
- Prepared -> not due; explicit reconciliation required;
- Failed with completion timestamp -> due at `completed_at + delivery_retry_minutes`;
- non-Eligible candidate -> not due.

The claim transaction enforces the same timing rule; retry-status is not merely advisory.

## Prepared reconciliation

A process crash between Prepared persistence and completion can leave an ambiguous Prepared attempt. v0.8 does not infer an outcome or automatically retry it.

`reconcile_prepared_delivery_attempt` requires:

- an existing Prepared attempt;
- explicit outcome `Succeeded` or `Failed`;
- explicit review note;
- reconciliation timestamp.

The resulting attempt stores `reconciled_at` and `reconciliation_note`. A Failed reconciliation becomes eligible for retry according to the configured retry delay. A Succeeded reconciliation blocks later attempts.

Reconciliation runs under `BEGIN IMMEDIATE` so two reviewers cannot independently reconcile the same Prepared state.

## Dry-run boundary

The only adapter remains `DryRunDeliveryAdapter`; it contains no network/client/provider dependency. Real delivery remains out of scope.

## CLI and API

New local operations:

- `delivery-retry-status <candidate-id>`
- `reconcile-delivery-attempt <attempt-id> --outcome ... --note ...`
- `GET /api/delivery-attempts/retry-status`
- `POST /api/delivery-attempts/{attempt_id}/reconcile`

Existing explicit dry-run operations remain. There is no generic send route, automatic retry loop, or automatic reconciliation loop.

## Pages/public boundary

Pages remains read-only. Public state may include `delivery_retry_minutes` and aggregate attempt-state counts. It does not contain idempotency keys, reconciliation notes, attempt JSON, or reconciliation controls.

Approved v0.6/v0.7 copy and the `Notification candidates` label remain preserved, with v0.8 wording added separately.

## Verification boundary

The verified v0.8 functional checkpoint passed Ruff, compile, **75 deterministic tests**, and live-source smoke against the existing configured sources. The new suite includes concurrent same-key and different-key SQLite claim tests.

## Limitations

- single SQLite database claim safety, not distributed leasing
- manual Prepared reconciliation only
- no automatic retry worker
- no real provider integration
- branch-backed hosted state remains test-only
- no authentication/workspace ownership
- more real incident/candidate history is required before introducing side effects
