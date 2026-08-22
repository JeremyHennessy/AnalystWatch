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

Added Prepared/Succeeded/Failed dry-run attempts, caller idempotency, retry-after-failure semantics and aggregate read surfaces. Clean gate: 66 tests.

## Core v0.8 — Attempt reconciliation & claim safety — complete

Added atomic SQLite attempt claims, concurrent claim protection, independent retry delay and explicit Prepared reconciliation. Clean gate: 75 tests.

## Core v0.9 — Persistence integrity & execution ownership — complete

Added stable storage identity/schema metadata, read-only integrity verification, verified SQLite snapshots, create-only restore, delivery claimant attribution and reconciliation reviewer attribution. Clean gate: 84 tests.

## Core v0.10 — Storage protocol & workspace guardrails — complete

Added structural `MonitoringStore`, backward-compatible default-local source ownership and `WorkspaceStore` isolation without changing the SQLite schema. Clean gate: 92 tests; hosted state verified after merge.

## Core v0.11 — Runtime workspace binding & store conformance — complete

Added independent `MemoryStore`, shared conformance coverage, default-local CLI/FastAPI workspace binding and runtime isolation. Clean gate: 113 tests; hosted state verified after merge.

## Core v0.12 — Workspace-aware persistent identity proof — complete

Added separate schema-v2 `NamespacedStorage`, composite workspace/domain keys, workspace-local idempotency and verified selected-workspace import from legacy snapshots. Clean gate: 121 tests; hosted legacy state verified after merge.

## Core v0.13 — Controlled backend selection & migration rehearsal — current

Implemented and verified on the functional checkpoint:

- shared runtime storage factory for `legacy` and `namespaced` modes
- safe default remains `legacy`
- existing databases inspected read-only before runtime initialization
- schema version 1 accepted only by `legacy`
- schema version 2 accepted only by `namespaced`
- corrupt or AnalystWatch-unknown existing state rejected without mutation
- global CLI `--storage-backend` and `ANALYSTWATCH_STORAGE_BACKEND`
- backend-aware `verify-state`
- legacy backup/restore explicitly remain legacy-only
- local `import-namespaced-state` command wraps the create-only v1 → v2 import
- FastAPI accepts explicit/environment backend selection
- FastAPI records selected backend in app state
- end-to-end migration rehearsal starts from operational legacy state
- rehearsal verifies Healthy baseline, later Critical history, Reviewed state, Eligible candidate and completed dry-run attempt
- verified legacy snapshot imported into schema-v2
- migrated state successfully opened through namespaced FastAPI
- source/history/candidate/attempt continuity verified through API reads
- migrated state successfully rendered through static Pages
- eight new backend/migration regressions
- clean functional checkpoint reached **129 passing tests**

The live-source PR workflow is path-filtered to ingestion/model/profile/service changes and does not run for this runtime-only milestone. Post-merge `monitor-state` advancement remains the deployment compatibility gate proving the hosted default-legacy path still operates normally.

## Candidate v0.14 — production persistence & authenticated workspace boundary

Before enabling real external delivery:

- select a deployment-grade persistent database behind the proven `MonitoringStore` contract
- implement workspace-aware identity equivalent to the schema-v2 proof
- define authenticated user/session identity
- define workspace membership and authorization rules for remote reads/writes
- define production migration/cutover from verified local snapshots
- define managed backup/retention/audit policy
- keep real notification delivery disabled until persistence/auth boundaries are proven

## Later

- first opt-in provider integration behind the proven attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- billing and integrations
