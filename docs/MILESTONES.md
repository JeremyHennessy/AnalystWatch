# Milestones

## Core v0.1 — complete

Deterministic monitoring foundation: ingestion, profiling, Health classification, baseline retention, CLI/API/dashboard, broken fixtures and CI.

## Core v0.2 — Scheduling & Signal Quality — complete

Added independent monitoring cadence, due-source scheduling, repository source sync, Healthy-history references, freshness evidence, Pages export and scheduled GitHub Actions monitoring.

## Core v0.2.1 — Initial real-source validation — complete

Validated Bank of Canada USD/CAD and U.S. Treasury Debt to the Penny from GitHub Actions and added explicit numeric-string contracts. No detector thresholds changed.

## Core v0.3 — Source onboarding & contract preflight — complete

Added non-persistent source preflight, contract validation, safe local onboarding/API creation and duplicate-ID protection. Clean gate: 32 tests.

## Core v0.4 — Operational review & secure source configuration — complete

Added environment-backed request headers, preflight-protected edits, Acknowledged/Reviewed state, guarded Healthy baseline promotion and public-output redaction. Clean gate: 41 tests.

## Core v0.5 — Incident transitions & notification readiness — complete

Added derived Opened/Escalated/Recovered incident lifecycle, duplicate-noise suppression, and transition candidates persisted atomically with observations. Clean gate: 50 tests; live-source smoke green. No outbound delivery.

## Core v0.6 — Delivery policy sandbox — complete

Added per-source opt-in transition policy, safe-default suppression, Eligible/Suppressed evaluation with immutable policy snapshots, and explicit idempotent evaluation of legacy Pending candidates. Clean gate: 58 tests; live-source smoke green. No outbound delivery.

## Core v0.7 — Dry-run delivery attempts — current

Goal: prove execution, idempotency and retry persistence semantics without connecting a real provider.

Implemented and verified on the functional checkpoint:

- separate `DeliveryAttempt` model; candidate policy state remains unchanged
- states: `Prepared`, `Succeeded`, `Failed`
- `dry-run` is the only delivery mode/adapter
- adapter performs no network or external I/O
- attempts are explicit only; monitoring never creates them automatically
- only Eligible notification candidates can be attempted
- caller-supplied idempotency key
- same key replays the stored attempt without rerunning the adapter
- idempotency-key reuse across a different candidate/adapter is rejected
- successful attempt blocks another attempt for the same candidate/adapter
- failed attempt may be retried with a new key and incremented attempt number
- persisted Prepared attempt blocks blind retry
- SQLite uniqueness on idempotency key and candidate/adapter/attempt number
- CLI/API can inspect attempts and execute only the explicitly named dry-run path
- Pages exposes aggregate attempt counts/state counts only and does not expose idempotency keys
- approved `Notification candidates` label and v0.6 no-delivery copy preserved
- clean functional checkpoint reached **66 passing tests**
- live-source smoke remained green

No detector, scheduler, hosted source configuration, notification-policy semantics, secret handling, review semantics, baseline semantics, Pages workflow or shared CSS changed.

## Candidate v0.8 — attempt reconciliation & persistence hardening

Before any real provider integration:

- define explicit reconciliation for abandoned `Prepared` attempts
- define claim/lease/concurrency semantics for multiple workers
- define retry timing/backoff separately from monitoring cadence
- make idempotency behavior robust under concurrent requests, not only sequential service calls
- replace branch-backed SQLite test persistence with deployment-appropriate storage
- define authentication/workspace ownership before remote delivery actions
- accumulate real transition/candidate history and inspect policy noise

## Later

- first opt-in provider integration behind the proven attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
