# AnalystWatch Core v0.7 Architecture

## Decision

Core v0.7 remains a Python modular monolith. FastAPI is the interactive local/API surface; GitHub Pages is generated read-only test output. The deterministic monitoring engine remains authoritative. Review state, incident state, notification-policy decisions, and delivery attempts are downstream operational records and do not rewrite detector Health/findings.

SQLite persists source definitions, observations, review state, notification candidates, dry-run delivery attempts, profiles, and the selected baseline. The temporary GitHub-hosted environment retains this database on the public `monitor-state` branch, which must contain only non-secret test state.

## Data flow

```text
SourceDefinition
  -> preflight for interactive create/edit
  -> schedule -> ingest -> profile -> deterministic detectors
  -> immutable Observation: Healthy / Warning / Critical
       |
       +-> review state: Acknowledged / Reviewed
       +-> derive Incident: Opened / Escalated / Recovered
              |
              +-> NotificationCandidate
                    |
                    +-> source notification_transitions policy
                         -> Eligible / Suppressed
                         -> immutable policy snapshot
                              |
                              +-> EXPLICIT dry-run only
                                   -> Prepared DeliveryAttempt
                                   -> local DryRunDeliveryAdapter
                                   -> Succeeded / Failed
       +-> guarded baseline review/promotion
  -> FastAPI/API inspection
  -> read-only Pages summary
```

No monitoring check automatically creates a DeliveryAttempt. There is no outbound provider integration in v0.7.

## Delivery-attempt model

`DeliveryAttempt` is separate from `NotificationCandidate`. A candidate says whether an incident transition matched policy; an attempt records an explicit execution against an adapter.

Fields include:

- candidate/source identifiers
- adapter and mode
- caller idempotency key
- monotonic attempt number per candidate/adapter
- state: `Prepared`, `Succeeded`, `Failed`
- created/completed timestamps
- result summary or error evidence

The candidate remains `Eligible` after a successful or failed dry run. Delivery history must not rewrite the historical policy decision.

## Dry-run adapter boundary

`DryRunDeliveryAdapter` is deterministic and contains no network client or provider SDK. It returns a local result only. Tests can inject a deterministic failure without external I/O.

This adapter proves execution semantics independently from a real transport.

## Idempotency and retry semantics

The caller supplies a stable idempotency key.

- if the key already exists for the same candidate/adapter, the stored attempt is returned without rerunning the adapter;
- if that key belongs to another candidate/adapter, the operation is rejected;
- after `Succeeded`, another key is rejected for the same candidate/adapter;
- after `Failed`, a new key may create the next attempt number;
- after `Prepared`, another key is blocked.

SQLite enforces:

- unique idempotency key;
- unique `(candidate_id, adapter, attempt_number)`.

The service also enforces the state-machine rules before insert.

## Prepared-before-execution persistence

The system persists `Prepared` before adapter invocation, then records `Succeeded` or `Failed` afterward. These are intentionally separate transactions.

If the process dies between them, the database retains a `Prepared` attempt. v0.7 refuses a blind retry because a future real provider might have received a side effect even when local completion was not recorded. Reconciliation/lease/timeout semantics are therefore a future milestone rather than being guessed in v0.7.

## Candidate eligibility boundary

Only `Eligible` notification candidates may be attempted. `Suppressed` and legacy `Pending` candidates are rejected. Candidate policy evaluation remains the v0.6 behavior and is not modified by attempt outcomes.

## Storage

`delivery_attempts` references both `notification_candidates` and `sources` with foreign keys and uses cascade deletion for test-state cleanup. Attempts are append-oriented audit records; only the JSON payload of an existing attempt is updated when its Prepared state completes.

## CLI/API surfaces

Local CLI:

- `delivery-attempts` — inspection
- `dry-run-delivery` — explicit dry-run execution requiring an idempotency key

Local API:

- `GET /api/delivery-attempts`
- `POST /api/delivery-attempts/dry-run`

There is no generic send route, automatic worker, destination configuration, or real adapter.

## Pages/public output

Pages remains read-only. It exposes only aggregate delivery-attempt counts and state counts. It does not export:

- idempotency keys;
- full delivery-attempt payloads;
- any execution control;
- request-header environment-variable names.

The approved `Notification candidates` label and prior no-delivery wording are preserved.

## Existing operational semantics

Source preflight/editing, environment-backed headers, Acknowledged/Reviewed state, guarded Healthy-only baseline promotion, incident derivation, notification-transition policy, scheduling, and detector thresholds are unchanged in v0.7.

## Verification boundary

The verified v0.7 functional checkpoint passed Ruff, compile, **66 deterministic tests**, and live-source smoke against the demo, Bank of Canada and U.S. Treasury sources.

CI caught a UI-copy preservation regression during development. The prior v0.6 no-delivery sentence was restored exactly and v0.7 dry-run wording was added separately. No service/storage semantics were changed by that correction.

## Tradeoffs / current limitations

- dry-run adapter only; no real provider exists
- Prepared attempts require future explicit reconciliation semantics
- production-grade concurrency claims/leases are not implemented
- `monitor-state` is test-only branch-backed persistence
- authentication/workspace ownership is not implemented
- environment-backed headers are not a multi-user secret vault
- GitHub scheduling is not real-time
- Pages is read-only
- incident derivation reads recent history into memory
- more real transition history is required before provider integration
