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

Added derived incident lifecycle and atomic transition candidates:

- Opened
- Escalated
- Recovered
- repeated same-severity incident checks suppressed as duplicate noise
- candidate persisted atomically with transition observation
- no outbound delivery

Clean gate: 50 tests; live-source smoke green.

## Core v0.6 — Delivery policy sandbox — current

Goal: determine whether a transition *would* be deliverable, without connecting any provider.

Implemented and verified on the functional candidate:

- per-source `notification_transitions` policy
- safe default is no enabled transitions
- new candidates immediately evaluate to `Eligible` or `Suppressed`
- candidate snapshots enabled transitions, evaluation time and decision reason
- later policy edits do not rewrite historical candidate decisions
- legacy v0.5 `Pending` candidates are explicitly evaluated, not silently migrated
- repeat legacy evaluation is idempotent
- CLI/API expose policy evaluation and candidate state only
- Pages exposes policy and Pending / Eligible / Suppressed counts
- still no email, Slack, Teams, webhook, SMS, destination, retry worker or send control
- approved **“Notification candidates”** UI label restored after CI caught a regression
- clean functional gate reached **58 passing tests**
- live-source smoke remained green

No detector, scheduler, hosted source configuration, secret handling, review semantics, baseline semantics, Pages workflow or shared CSS changed.

## Candidate v0.7 — delivery-attempt model & persistence readiness

Before real provider integration:

- add explicit delivery-attempt lifecycle independent from monitoring transactions
- define idempotency key and retry/backoff semantics
- add dry-run/sandbox destination abstraction with no external network side effect by default
- preserve immutable candidate policy decisions
- replace branch-backed SQLite test persistence with deployment-appropriate storage
- define authentication/workspace ownership before remote delivery actions
- accumulate real transition/candidate history to evaluate policy noise

## Later

- first opt-in provider integration
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
