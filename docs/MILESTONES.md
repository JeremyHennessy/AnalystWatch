# Milestones

## Core v0.1 — complete

Deterministic monitoring foundation: ingestion, profiling, Health classification, baseline retention, CLI/API/dashboard, broken fixtures and CI.

## Core v0.2 — Scheduling & Signal Quality — complete

Added monitoring cadence, due-source scheduling, repository source sync, Healthy-history references, freshness evidence, Pages export and scheduled GitHub Actions monitoring.

## Core v0.2.1 — Initial real-source validation — complete

Validated Bank of Canada USD/CAD and U.S. Treasury Debt to the Penny through GitHub Actions and added explicit numeric-string contracts. No detector thresholds changed.

## Core v0.3 — Source onboarding & contract preflight — complete

Added non-persistent preflight, contract validation, safe onboarding/API creation and duplicate-ID protection. Clean gate: 32 tests.

## Core v0.4 — Operational review & secure source configuration — complete

Added environment-backed request headers, safe source edits, Acknowledged/Reviewed state, guarded Healthy baseline promotion and public-output redaction. Clean gate: 41 tests.

## Core v0.5 — Incident transitions & notification readiness — complete

Added derived Opened/Escalated/Recovered incident lifecycle and transition candidates with duplicate-noise suppression. Clean gate: 50 tests. No outbound delivery.

## Core v0.6 — Delivery policy sandbox — complete

Added opt-in notification-transition policy, safe-default suppression and immutable policy decisions. Clean gate: 58 tests. No outbound delivery.

## Core v0.7 — Dry-run delivery attempts — complete

Added explicit Prepared/Succeeded/Failed dry-run attempts, caller idempotency, retry-after-failure semantics and aggregate read surfaces. Clean gate: 66 tests.

## Core v0.8 — Attempt reconciliation & claim safety — complete

Added atomic SQLite attempt claims, concurrent claim protection, independent retry delay and explicit Prepared reconciliation. Clean gate: 75 tests.

## Core v0.9 — Persistence integrity & execution ownership — current

Goal: make current state portable/verifiable and add execution attribution without pretending test SQLite is production storage.

Implemented and verified on the functional checkpoint:

- additive persistent storage metadata with stable `storage_id` and schema version
- read-only SQLite integrity verification without initialization/mutation
- source/observation/review/candidate/attempt count verification
- SQLite backup-API snapshots with pre/post integrity verification
- snapshot identity/schema/counts must match active DB
- create-only restore into a new destination database
- existing backup/restore targets are never overwritten
- corrupt snapshot verification fails without mutating the source file
- incomplete newly-created backup/restore destinations are removed on failure
- `claim_owner` persisted on delivery attempts
- `reconciled_by` persisted separately on Prepared reconciliation
- same-key replay preserves the original claimant across service processes
- local service owner resolves from explicit value, environment, or hostname:pid
- local CLI adds `verify-state`, `backup-state`, `restore-state`
- owner/reviewer overrides remain local CLI operations; no remote spoofing parameters added
- Pages remains unchanged and redacts storage/owner/reviewer/internal persistence details
- clean functional checkpoint reached **84 passing tests**
- live-source smoke remained green

No detector, scheduler, hosted source configuration, notification-policy, retry/reconciliation state-machine, Pages/UI, secret, review, baseline, workflow or shared-CSS semantics changed.

## Candidate v0.10 — production persistence boundary & workspace ownership

Before any real provider integration:

- define storage repository/protocol boundary independent from SQLite implementation
- select/develop deployment-appropriate persistent storage
- define workspace/user ownership and authorization for remote write operations
- define migration/import path from verified SQLite snapshots
- define retention/audit policy for observations, candidates and attempts
- preserve deterministic monitoring and delivery state-machine semantics across the storage boundary

## Later

- first opt-in provider integration behind the proven attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
