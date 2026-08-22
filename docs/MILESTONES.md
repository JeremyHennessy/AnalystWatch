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

## Core v0.16 — Managed runtime + first live email delivery — complete

Added environment-backed managed-runtime validation, PostgreSQL startup/membership bootstrap, dedicated managed PostgreSQL recovery validation and a Resend live-email adapter behind the existing delivery-attempt state machine. Clean gate: 164 tests plus live-source smoke; hosted legacy/local compatibility verified after merge.

Still not implied by v0.16: production app cutover to managed PostgreSQL or a verified real Resend side effect.

## Product v0.16.1 — UI & Product Foundation — complete

Reworked the existing user-visible shell without changing monitoring behavior:

- workspace reliability overview and health KPIs
- needs-attention triage queue
- clearer monitored-source list
- incident-first source detail hierarchy
- visual health history
- compact profile/review/baseline actions
- monitoring contract under progressive disclosure
- responsive/mobile improvements
- static Pages parity
- preservation of established public-output safety/status guarantees

The UI change was limited to templates, shared CSS and UI regression coverage. Hosted monitoring state advanced after merge.

## Product v0.17 — Microsoft 365 Excel connector — current release candidate

Implemented and verified on the functional checkpoint:

- `microsoft_excel` source type
- internal `m365://<drive>/<item>?table=<name>` descriptor
- optional worksheet and page-size selectors
- delegated Microsoft Graph Authorization via existing environment-backed header references
- DriveItem modified-time and ETag evidence
- Excel Table column/header discovery
- paged Excel Table row ingestion
- normalization into the existing DataFrame/profile/detector pipeline
- preflight and normal source onboarding reuse
- Microsoft 365 fields in the analyst-facing onboarding page
- no token value persisted in the source definition
- public Pages/state redaction of drive ID, workbook item ID and token environment-variable name
- deterministic Graph pagination/error/auth/preflight tests
- clean functional checkpoint: **172 tests**, Ruff/compile green, PostgreSQL 16 CI green
- live-source smoke green on the unchanged public-source set

Explicitly not claimed by v0.17:

- no real Microsoft tenant credential was used in this repository session;
- no live SharePoint/OneDrive tenant check was performed;
- no application-permission support is claimed for the Excel workbook/table Graph APIs used here;
- the full `Connect Microsoft 365 → browse site/drive/workbook/table` OAuth selection flow is not yet implemented;
- no detector, storage, incident or notification semantics changed.

## Product roadmap after v0.17

Proceed sequentially unless evidence changes a dependency:

- Product v0.18 — row-level / key-level change analysis
- Product v0.19 — Power BI Guard
- Product v0.20 — Microsoft Teams + lightweight dependency graph / blast radius
- Product v0.21 — reconciliation monitors
- Product v0.22 — Google Sheets connector
- Product v0.23 — business rules / Data Rules
- Product v0.24 — reliability scorecards + trust badge
- Product v0.25 — preconfigured source packs

AI investigation remains downstream of deterministic findings and must not redefine Health classification.
