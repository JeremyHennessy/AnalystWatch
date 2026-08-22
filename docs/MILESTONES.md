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

Reworked the existing user-visible shell without changing monitoring behavior: workspace reliability overview, health KPIs, needs-attention triage, clearer sources, incident-first detail, visual history, progressive disclosure and responsive/static Pages parity. The UI change was limited to templates, shared CSS and UI regression coverage. Hosted monitoring state advanced after merge.

## Product v0.17 — Microsoft 365 Excel connector — complete

Added table-first SharePoint / OneDrive Excel ingestion through delegated Microsoft Graph access, DriveItem modified-time/ETag evidence, paginated table rows, normal preflight/onboarding reuse and public identifier redaction. Clean gate: **172 tests**, Ruff/compile and PostgreSQL 16 CI green, live-source smoke green. No real Microsoft tenant credential or application-permission workbook access was claimed.

## Product v0.18 — Row-level / key-level change analysis — complete

Added bounded configured-key row snapshots, previous-successful and active-baseline comparisons, Added/Removed/Changed/Unchanged counts, per-column change counts, bounded examples, privacy-aware retention and public aggregate-only rendering. Clean gate: **183 tests**, Ruff/compile and PostgreSQL 16 CI green; live-source smoke green.

Raw row snapshots and key/value samples remain bounded and are not published in static Pages/state output.

## Product v0.19 — Power BI Guard — complete

Implemented workspace-scoped Power BI Guard definitions, environment-backed bearer-token references, semantic-model/refresh evidence, best-effort report/workspace/datasource evidence, existing-source Health correlation, deterministic false-confidence handling, analyst-facing Guard pages, SQLite/PostgreSQL persistence and Viewer/Operator/Admin route boundaries.

Frozen checkpoint: **196 tests**, Ruff/compile green, PostgreSQL 16 CI green.

No Power BI refresh triggering, full Fabric lineage catalogue, source Health redefinition or live Microsoft-tenant claim was introduced.

## Product v0.20 — Microsoft Teams + dependency graph / blast radius — complete

Implemented:

- Microsoft Teams Workflows / Power Automate Adaptive Card delivery;
- environment-backed Teams webhook/public base URL configuration;
- reuse of existing eligible-candidate, atomic claim, idempotency, retry and reconciliation semantics;
- Source / Workbook / Semantic Model / Report / Custom dependency assets;
- explicit/discovered workspace-scoped dependency edges;
- SQLite/PostgreSQL dependency persistence;
- deterministic cycle-safe blast radius;
- Power BI source → semantic model → report discovery;
- additive source-detail downstream-impact context.

Verified checkpoint: **212 tests**, Ruff/compile green, PostgreSQL 16 CI green. Merged to `main` at `5ec4744826dafa737931bde89733ee277bbf08ef`.

No retired Office 365 Connector implementation, enterprise SQL-column lineage, separate Teams state machine, source Health changes or unverified Microsoft side-effect claims were introduced.

## Product v0.21 — reconciliation monitor / ambiguous delivery operations — complete

Implemented:

- read-only reconciliation queue derived from existing `Prepared` delivery attempts;
- default 30-minute stale threshold;
- oldest unresolved attempts first;
- bounded 5,000-attempt scan and separate 100-item display/output limit;
- explicit scan/output limit evidence;
- queue privacy boundary excluding idempotency keys, claim owners, provider raw evidence and reconciliation notes;
- `/reconciliation` Delivery Ops view and bounded read API;
- evidence-note reconciliation to existing Succeeded/Failed states;
- authenticated `reconciled_by` attribution for UI and API paths;
- Viewer read / Operator reconcile boundaries;
- dynamic-only Delivery Ops navigation, omitted from static Pages.

Final exact-head CI passed **226 tests, 1 warning** with Ruff/compile/PostgreSQL 16. Merged to `main` at `244757286ad8cb3a7302fc2e0e9f51cfb847f4c5`.

No automatic ambiguity inference, automatic retry, provider-specific reconciliation polling, detector/Health change, UI redesign or new delivery-state schema was introduced.

## Product v0.22 — Google Sheets connector — current release candidate

Implemented from exact v0.21 merge baseline `244757286ad8cb3a7302fc2e0e9f51cfb847f4c5`:

- new `google_sheets` source type;
- `gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]` source location contract;
- Google Sheets API v4 `spreadsheets.values.get` read path;
- row-major retrieval with `UNFORMATTED_VALUE` numeric rendering and formatted date/time evidence;
- environment-backed Authorization header reference through the existing `request_header_env` contract;
- bearer-token value is never persisted in the source definition;
- deterministic configured header-row parsing relative to the returned range;
- short rows padded to the header width and fully blank rows ignored;
- duplicate/empty headers and rows wider than the header fail closed;
- existing numeric-field, unique-key, latest-date and freshness preflight contracts reused unchanged;
- no fabricated Google Sheets modification timestamp;
- expected refresh requires content-date evidence or preflight reports `freshness_unverifiable`;
- static Pages redact spreadsheet ID, internal `gsheets://` location and token environment-variable name;
- public location is bounded to `Google Sheets · <A1 range>`;
- existing Add Source UI now exposes Spreadsheet ID, A1 range, header row and token environment reference;
- no new UI/CSS architecture, detector thresholds, source Health semantics or persistence schema.

Functional checkpoint on `9cb60774817a2a637a1714a5c15ccd643faa4324`:

- **236 passed, 1 warning**;
- Ruff green;
- compile/import green;
- PostgreSQL 16 CI green;
- live-source smoke #80 green.

Explicit non-goals / unverified boundaries:

- no Google SDK dependency;
- no OAuth refresh-token management;
- no service-account key exchange;
- no Google Sheets write access;
- no parallel onboarding/monitoring state machine;
- no claim of live Google Workspace access because no real Google credential was supplied in this repository session.

## Product roadmap after v0.22

Proceed sequentially unless evidence changes a dependency:

- Product v0.23 — business rules / Data Rules
- Product v0.24 — reliability scorecards + trust badge
- Product v0.25 — preconfigured source packs

AI investigation remains downstream of deterministic findings and must not redefine Health classification.
