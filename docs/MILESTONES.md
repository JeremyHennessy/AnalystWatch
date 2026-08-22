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

## Core v0.13 — Controlled backend selection & migration rehearsal — complete

Added safe `legacy` / `namespaced` runtime selection, pre-initialization schema checks, backend-aware verification, local legacy → namespaced import and full migrated FastAPI/Pages rehearsal. Clean gate: 129 tests; hosted default-legacy state verified after merge.

## Core v0.14 — PostgreSQL production persistence proof — current

Implemented and verified on the functional checkpoint:

- deployment-grade `PostgresStorage` implementation of `MonitoringStore`
- PostgreSQL schema namespace `analystwatch`
- backend-specific PostgreSQL schema/storage identity metadata
- composite workspace identity for sources, observations, reviews, candidates and attempts
- workspace-local idempotency-key uniqueness
- workspace-local candidate/adapter attempt numbering
- deterministic insertion ordering for timestamp ties
- PostgreSQL `FOR UPDATE` row locking for delivery claim and Prepared reconciliation safety
- shared conformance suite now runs across SQLite, `MemoryStore` and PostgreSQL
- real PostgreSQL 16 service added to GitHub CI; PostgreSQL is not mocked
- `psycopg` production driver dependency
- explicit runtime backend `postgres`; safe default remains `legacy`
- PostgreSQL requires an explicit DSN via CLI/environment/FastAPI
- backend-aware PostgreSQL verification
- explicit namespaced schema-v2 → empty PostgreSQL workspace import
- imported source/history/baseline/review/candidate/attempt state preserved
- concurrent same-candidate claim regression proves row-lock serialization
- cross-workspace duplicate domain IDs and idempotency values proven safe in PostgreSQL
- CLI `import-postgres-state` cutover rehearsal
- FastAPI successfully starts and reads imported PostgreSQL operational state
- hosted workflow remains on legacy SQLite; no production DSN is committed
- clean functional checkpoint reached **143 passing tests** against PostgreSQL 16

v0.14 is a production-persistence **contract proof**, not a managed PostgreSQL deployment. Managed provisioning, backups/PITR, retention, operational observability and an actual hosted cutover remain separate deployment work.

## Candidate v0.15 — authenticated workspace authorization

Before enabling real external delivery:

- define a provider-neutral authenticated principal/session model
- define persisted workspace membership and role semantics
- distinguish read-only, operational-write and administrative capabilities
- enforce workspace membership on remote FastAPI reads and writes
- never trust a user-supplied workspace identifier without authenticated membership
- preserve explicit local/CLI operation without silently pretending it is remote authentication
- add negative tests for cross-workspace reads, writes, candidate operations and baseline/review operations
- keep notification delivery disabled until the authorization boundary is independently green

## Later

- managed PostgreSQL deployment/cutover, backups/PITR and retention policy
- first opt-in provider integration behind the proven attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- billing and integrations
