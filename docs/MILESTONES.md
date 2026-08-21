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

## Core v0.11 — Runtime workspace binding & store conformance — current

Implemented and verified on the functional checkpoint:

- independent `MemoryStore` implementation that does not inherit/wrap SQLite
- shared persistence conformance scenarios across SQLite and MemoryStore
- CLI global `--workspace-id`, default `local`
- CLI monitoring/list/check/Pages paths use workspace-bound storage
- SQLite verify/backup/restore remain raw maintenance paths
- FastAPI bound to one workspace, default `local`
- cross-workspace source writes blocked before preflight/persistence
- raw `app.state.storage` compatibility handle retained while HTTP/service paths use `workspace_storage`
- scheduler typed against `MonitoringStore`
- 16 parametrized cross-store conformance cases
- 5 workspace-runtime regression cases
- clean functional checkpoint reached **113 passing tests**

The live-source PR workflow is intentionally path-filtered to ingestion/model/profile/service changes, so it does not run for this runtime/store-only milestone. Hosted `monitor-state` advancement after merge is the deployment compatibility gate.

## Candidate v0.12 — workspace-aware persistent identity proof

Before selecting a production database:

- implement a separate persistent store schema keyed by workspace + source identity
- prove two workspaces can use the same source ID without collisions
- carry workspace identity through observations, reviews, candidates and attempts
- add verified import from a legacy SQLite snapshot into one selected workspace
- keep current hosted SQLite runtime unchanged until the new schema is independently proven

## Later

- controlled runtime backend selection and migration rehearsal
- deployment-appropriate production database adapter
- authenticated workspace/user authorization
- retention/audit policy for observations, candidates and attempts
- first opt-in provider integration behind the proven attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- billing and integrations
