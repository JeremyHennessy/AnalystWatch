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

## Core v0.14 — PostgreSQL production persistence proof — complete

Added workspace-aware PostgreSQL persistence behind `MonitoringStore`, PostgreSQL row-lock claim/reconciliation safety, runtime DSN selection, namespaced → PostgreSQL import, PostgreSQL verification and real PostgreSQL 16 CI conformance. Clean gate: 143 tests; hosted default-legacy state verified after merge. This was a persistence contract proof, not a managed PostgreSQL deployment.

## Core v0.15 — Authenticated workspace authorization — current

Implemented and verified on the functional checkpoint:

- separate provider-neutral authenticated-principal model
- opt-in `signed-bearer` web auth mode; safe default remains `local`
- HMAC-SHA256 signed bearer verification with principal subject and optional expiry
- bearer tokens do not carry trusted workspace authority
- separate `MembershipStore` contract so RBAC does not modify `MonitoringStore`
- SQLite sidecar membership persistence for local/test use
- PostgreSQL workspace membership persistence in `analystwatch.workspace_memberships`
- initial roles: Viewer, Operator and Admin
- explicit role ordering and capability enforcement
- centralized FastAPI authorization middleware
- authority chain enforced as principal → bound-workspace membership → role → capability → operation
- missing authentication returns 401 in signed mode
- authenticated non-members return 403
- Viewer mutations denied
- Operator administrative mutations denied
- Admin membership and source-configuration operations permitted
- workspace-A users denied reads and operations against workspace B
- arbitrary payload `workspace_id` cannot override the bound workspace
- unclassified remote mutations fail closed as Admin-only
- `/healthz` and static assets remain intentionally outside the authenticated application boundary
- local mode preserves existing unauthenticated local/hosted workflow behavior
- no unauthenticated first-Admin bootstrap endpoint; initial Admin seeding is a trusted deployment responsibility
- PostgreSQL membership persistence exercised against the real PostgreSQL 16 CI service
- clean functional checkpoint reached **156 passing tests**

Core v0.15 proves the application authorization boundary. It does **not** add OAuth/OIDC, SSO, user-account lifecycle, managed deployment, billing or real notification delivery.

## Candidate Core v0.16 — managed deployment + first real email delivery

Proceed only after v0.15 merge/hosted compatibility verification.

Managed runtime work:

- provision/configure managed PostgreSQL without committing credentials
- secret injection and rotation boundary
- explicit schema migration/version/startup checks
- trusted initial Admin provisioning
- backup/retention policy
- point-in-time recovery where supported
- restore rehearsal
- connection-pool/runtime sizing
- health checks and observability
- controlled hosted cutover with rollback evidence

First real external delivery:

- implement email behind the existing delivery abstraction
- preserve Eligible-candidate requirement
- preserve idempotency, claim ownership and Prepared state
- record success/failure deterministically
- preserve retry timing and reconciliation semantics
- verify actual external side effects without exposing secrets, DSNs, authorization headers or idempotency keys

## Product roadmap after Core v0.16

Proceed sequentially unless evidence changes a dependency:

- Product v0.17 — SharePoint / OneDrive Excel connector
- Product v0.18 — row-level / key-level change analysis
- Product v0.19 — Power BI Guard
- Product v0.20 — Microsoft Teams + lightweight dependency graph / blast radius
- Product v0.21 — reconciliation monitors
- Product v0.22 — Google Sheets connector
- Product v0.23 — business rules / Data Rules
- Product v0.24 — reliability scorecards + trust badge
- Product v0.25 — preconfigured source packs

AI investigation remains downstream of deterministic findings and must not redefine Health classification.
