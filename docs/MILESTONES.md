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

## Core v0.15 — Authenticated workspace authorization — complete

Added provider-neutral authenticated principals, signed-bearer mode, persistent SQLite/PostgreSQL workspace memberships, Viewer/Operator/Admin authorization, fail-closed FastAPI enforcement and cross-workspace/security-negative tests. Clean gate: 156 tests; hosted local-auth compatibility verified after merge.

## Core v0.16 — Managed runtime + first live email delivery — current candidate

Implemented and verified on the functional checkpoint:

- `DeliveryMode.LIVE` without changing the existing dry-run path
- Resend email adapter behind the existing Eligible-candidate delivery-attempt contract
- provider idempotency header using the AnalystWatch idempotency key
- live attempt state persisted before external I/O
- provider acceptance → Succeeded
- definitive provider rejection → Failed
- transport uncertainty remains Prepared for explicit reconciliation
- same-key replay does not execute a second provider request
- analyst-oriented email content with source/workspace/transition/severity/findings/impact/investigation/link
- secret/DSN/idempotency-key redaction from email and stored result/error surfaces
- environment-backed managed-runtime configuration
- PostgreSQL schema/startup verification
- PostgreSQL workspace-membership initialization
- trusted first-Admin bootstrap with non-Admin conflict refusal
- dedicated external managed PostgreSQL validation project
- isolated managed-database recovery rehearsal with state removal and reset-from-parent recovery
- temporary recovery branches cleaned up after verification
- clean functional checkpoint: **164 tests**, Ruff/compile green, PostgreSQL 16 CI green
- live-source smoke green

Still intentionally not claimed by the candidate:

- the existing GitHub-hosted app has not been cut over from legacy SQLite/local auth;
- no production application deployment target is configured;
- no real Resend credential/sender has been configured through this repository session;
- therefore a successful real external email side effect is not yet claimed.

The managed PostgreSQL validation environment proves infrastructure/storage recovery mechanics, not production application deployment.

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
