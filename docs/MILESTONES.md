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

## Core v0.9 — Persistence integrity & execution ownership — complete

Added stable storage identity/schema metadata, read-only integrity verification, verified SQLite snapshots, create-only restore, delivery claimant attribution and reconciliation reviewer attribution. Clean gate: 84 tests.

## Core v0.10 — Storage protocol & workspace guardrails — current

Goal: define and prove an ownership boundary without changing the hosted runtime or pretending the current SQLite schema is multi-tenant.

Implemented and verified on the functional checkpoint:

- structural `MonitoringStore` persistence protocol
- backward-compatible `SourceDefinition.workspace_id` with default `local`
- strict workspace identifier validation
- `WorkspaceStore` bound to one workspace
- workspace-filtered source listing and lookup
- foreign-workspace source writes blocked before SQLite
- observations/baselines/reviews hidden across workspace boundaries
- notification candidates and delivery attempts hidden across workspace boundaries
- foreign candidate claims/attempt updates/reconciliation blocked
- baseline promotion constrained to the bound workspace
- `create_workspace_service(...)` composes existing `MonitorService` with the workspace store
- existing v0.9 SQLite schema remains unchanged
- existing persisted source JSON remains valid and resolves to workspace `local`
- global source-ID collision is explicit: another workspace cannot reuse an existing ID yet
- eight new regressions, including a real incident → Eligible candidate → dry-run attempt isolation path
- clean functional checkpoint reached **92 passing tests**
- live-source smoke remained green

No detector, scheduler, hosted source configuration, notification-policy, retry/reconciliation state-machine, Pages/UI, secret, review, baseline, workflow or shared-CSS semantics changed.

## Candidate v0.11 — runtime workspace binding & storage conformance

Before selecting a production database or adding authentication:

- run CLI/FastAPI/Pages through explicit workspace-bound construction
- add a second independent `MonitoringStore` implementation or conformance harness
- prove the full operational contract across both implementations
- define composite workspace/source identity requirements for future persistent storage
- keep legacy hosted SQLite as the default until migration behavior is independently verified

## Later

- deployment-appropriate persistent database adapter
- authenticated workspace/user authorization
- migration/import from verified SQLite snapshots
- retention/audit policy for observations, candidates and attempts
- first opt-in provider integration behind the proven attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- billing and integrations
