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

Implemented and verified on the frozen functional checkpoint:

- workspace-scoped Power BI Guard definitions
- environment-variable reference for the delegated bearer token; token value is never persisted
- semantic-model metadata and refreshability evidence
- refresh history, status, start/end times and duration
- best-effort workspace/report/datasource metadata
- report-to-semantic-model relationships
- current AnalystWatch upstream source-health correlation
- deterministic false-confidence case: refresh Completed + upstream Critical => Guard Critical
- Warning for completed refresh with Warning or unobserved upstream sources
- Critical for Failed/Cancelled/Disabled refresh
- explicit unconfirmed trust for incomplete/unknown/missing refresh evidence
- secret-safe provider error handling
- SQLite and PostgreSQL Guard definition/snapshot persistence
- Power BI Guard orchestration service using current AnalystWatch source observations
- analyst-facing DashboardGuard overview and detail pages
- upstream source status, downstream reports, refresh history and datasource-type evidence in the Guard UI
- Viewer read / Operator check / Admin configuration route boundaries
- cross-workspace Guard configuration rejection
- dynamic SourceGuard → DashboardGuard navigation
- static GitHub Pages intentionally do not fabricate Power BI state when no hosted Guard/credential exists
- frozen functional checkpoint: **196 tests**, Ruff/compile green, PostgreSQL 16 CI green

Explicit non-goals preserved:

- no Power BI refresh triggering;
- no full Fabric/warehouse lineage catalogue;
- no source detector threshold changes;
- no redefinition of upstream source Health;
- no separate notification state machine;
- no claim of live Microsoft tenant access without a real credential.

## Product v0.20 — Microsoft Teams + dependency graph / blast radius — complete

Implemented on top of the verified v0.19 baseline:

- Microsoft Teams Workflows / Power Automate webhook adapter using Adaptive Cards
- environment-backed Teams webhook and public base URL configuration
- reuse of the existing eligible-candidate and delivery-attempt state machine
- atomic claim, caller idempotency, retry and reconciliation semantics preserved for Teams
- same-key replay protection against duplicate external POSTs
- explicit provider rejection → Failed; ambiguous transport failure → Prepared for reconciliation
- Teams status route exposes only configured/unconfigured state and never the webhook URL
- Teams delivery action is Operator-level; configuration/mutation boundaries remain fail closed
- Source / Workbook / Semantic Model / Report / Custom dependency asset types
- explicit and discovered dependency edges
- workspace-scoped SQLite and PostgreSQL dependency persistence
- deterministic cycle-safe blast-radius traversal without duplicate descendant counts
- analyst-facing `/dependencies` Dependency Map plus dependency read/mutation/blast-radius API routes
- Power BI evidence discovery for configured source → semantic model and semantic model → report relationships
- per-Guard discovered-edge namespaces so refreshes replace only their own stale discovered relationships
- unavailable Power BI evidence does not erase the last known dependency graph
- additive source-detail Downstream impact panel using the recorded dependency graph
- dynamic SourceGuard / Power BI Guard navigation to the Dependency Map
- no detector, source Health, baseline, incident or existing delivery-state semantics changed
- verified checkpoint: **212 tests**, Ruff/compile green, PostgreSQL 16 CI green
- merged to `main` at `5ec4744826dafa737931bde89733ee277bbf08ef`

Explicit non-goals / unverified boundaries preserved:

- no retired Office 365 Connector implementation;
- no enterprise SQL-column/Fabric lineage catalogue;
- no separate Teams notification state machine;
- no source detector threshold changes or Health redefinition;
- no claim of a real Teams side effect because no real Teams Workflows webhook was supplied in this repository session;
- no claim of live Microsoft Power BI tenant access because no real tenant credential was supplied;
- static GitHub Pages do not fabricate dynamic Teams, Power BI or dependency state.

## Product v0.21 — reconciliation monitor / ambiguous delivery operations — current release

Implemented from the exact verified v0.20 merge baseline:

- read-only reconciliation queue derived from existing delivery-attempt state
- only unresolved `Prepared` attempts enter the queue
- default stale threshold of 30 minutes
- oldest unresolved attempts first
- bounded 5,000-attempt storage scan and separate 100-item output/display limit
- explicit `scan_limit_reached` and `item_limit_reached` evidence instead of claiming exhaustive history
- bounded queue fields exclude idempotency keys, claim owners, provider raw results/errors and reconciliation notes
- analyst-facing `/reconciliation` Delivery Ops view
- `GET /api/delivery-reconciliation` bounded read API
- evidence-note reconciliation form for explicit Succeeded / Failed outcomes
- existing reconciliation state transition remains authoritative; no new notification/delivery state machine
- no automatic retry when an operator reconciles an attempt to Failed
- existing retry policy continues to decide whether/when a later attempt can be claimed
- signed-bearer UI and API reconciliation persist the authenticated operator as `reconciled_by`
- Viewer read / Operator reconciliation boundaries; other mutations remain fail closed
- dynamic application navigation exposes Delivery Ops without adding it to the static Pages overview
- functional checkpoint: **225 tests**, Ruff/compile green, PostgreSQL 16 CI green

Explicit non-goals preserved:

- no automatic guessing of an ambiguous provider outcome;
- no automatic retry of Prepared attempts;
- no provider-specific reconciliation polling in this milestone;
- no detector threshold or source Health changes;
- no unrelated UI redesign;
- no new delivery-attempt persistence schema;
- static GitHub Pages do not fabricate reconciliation state.

## Product roadmap after v0.21

Proceed sequentially unless evidence changes a dependency:

- Product v0.22 — Google Sheets connector
- Product v0.23 — business rules / Data Rules
- Product v0.24 — reliability scorecards + trust badge
- Product v0.25 — preconfigured source packs

AI investigation remains downstream of deterministic findings and must not redefine Health classification.
