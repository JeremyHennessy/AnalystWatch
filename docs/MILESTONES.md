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

## Core v0.12 — Workspace-aware persistent identity proof — current

Implemented and verified on the functional checkpoint:

- separate `NamespacedStorage` persistent adapter using schema version 2
- composite workspace identity across sources, observations, reviews, candidates and attempts
- workspace-local idempotency-key uniqueness
- workspace-local candidate/adapter attempt numbering
- same source/candidate/attempt IDs can coexist in different workspaces in one database
- same idempotency value can coexist in different workspaces
- adapter remains bound to one validated workspace per instance
- adapter satisfies the existing `MonitoringStore` contract
- read-only verified import from legacy schema-v1 snapshots
- selected-workspace import only
- imported baseline, review, candidate and delivery-attempt state preserved
- import destination is create-only and never overwritten
- imported schema-v2 database receives a new storage identity
- corrupt or non-v1 sources are rejected before a target is retained
- current hosted legacy runtime remains unchanged
- eight new regressions
- clean functional checkpoint reached **121 passing tests**

The live-source PR workflow is path-filtered to ingestion/model/profile/service changes and therefore does not run for this new-adapter-only milestone. Post-merge `monitor-state` advancement is the deployment compatibility gate for the unchanged legacy runtime.

## Candidate v0.13 — controlled backend selection & migration rehearsal

Before any production database selection:

- add explicit runtime backend selection with safe legacy default
- reject schema/backend mismatches before initialization
- add a local CLI wrapper for verified legacy-to-namespaced import
- rehearse legacy snapshot → schema-v2 import → FastAPI startup → Pages rendering
- prove source/history/candidate/attempt continuity after import
- keep hosted deployment on legacy until the rehearsal is independently green

## Later

- deployment-appropriate production database adapter
- authenticated workspace/user authorization
- retention/audit policy for observations, candidates and attempts
- first opt-in provider integration behind the proven attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- billing and integrations
