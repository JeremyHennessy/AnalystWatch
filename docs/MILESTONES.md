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

Added workspace-aware PostgreSQL persistence behind `MonitoringStore`, PostgreSQL row-lock claim/reconciliation safety, runtime DSN selection, namespaced → PostgreSQL import, PostgreSQL verification and real PostgreSQL 16 CI conformance. Clean gate: 143 tests. This was a persistence contract proof, not a managed PostgreSQL production cutover.

## Core v0.15 — Authenticated workspace authorization — complete

Added provider-neutral authenticated principals, signed-bearer mode, persistent SQLite/PostgreSQL workspace memberships, Viewer/Operator/Admin authorization, fail-closed FastAPI enforcement and cross-workspace/security-negative tests. Clean gate: 156 tests.

## Core v0.16 — Managed runtime + first live email delivery architecture — complete

Added environment-backed managed-runtime validation, PostgreSQL startup/membership bootstrap, dedicated managed PostgreSQL recovery validation and a Resend live-email adapter behind the existing delivery-attempt state machine. Clean gate: 164 tests plus live-source smoke.

Still not implied by v0.16: production app cutover to managed PostgreSQL or a verified real Resend side effect.

## Product v0.16.1 — UI & Product Foundation — complete

Reworked the user-visible shell without changing monitoring behavior: workspace reliability overview, health KPIs, needs-attention triage, clearer sources, incident-first detail, visual history, progressive disclosure and responsive/static Pages parity.

## Product v0.16.2 — realistic demo portfolio — complete

Expanded the demo from a narrow technical proof into a realistic analyst-facing portfolio without changing deterministic monitoring semantics.

## Product v0.16.3 — real XLSX claims demo — complete

Added a realistic XLSX claims workflow demo and strengthened the product narrative around analyst-owned operational/reporting sources.

## Product v0.17 — Microsoft 365 Excel connector — complete

Added table-first SharePoint / OneDrive Excel ingestion through delegated Microsoft Graph access, DriveItem modified-time/ETag evidence, paginated table rows, normal preflight/onboarding reuse and public identifier redaction. Verified at 172 tests with Ruff/compile/PostgreSQL 16 green and live-source smoke green. No real Microsoft tenant credential was claimed.

## Product v0.18 — Row-level / key-level change analysis — complete

Added bounded configured-key row snapshots, previous-successful and active-baseline comparisons, Added/Removed/Changed/Unchanged counts, per-column change counts, bounded examples, privacy-aware retention and public aggregate-only rendering. Verified at 183 tests with Ruff/compile/PostgreSQL 16 green and live-source smoke green.

## Product v0.19 — Power BI Guard — complete

Implemented workspace-scoped Power BI Guard definitions, environment-backed bearer-token references, semantic-model/refresh evidence, best-effort report/workspace/datasource evidence, existing-source Health correlation, deterministic false-confidence handling, analyst-facing Guard pages, SQLite/PostgreSQL persistence and Viewer/Operator/Admin route boundaries. Frozen checkpoint: 196 tests. No real tenant claim.

## Product v0.20 — Microsoft Teams + dependency graph / blast radius — complete

Implemented Microsoft Teams Workflows delivery behind existing delivery safety, workspace-scoped dependency assets/edges, deterministic cycle-safe blast radius and Power BI source → semantic-model → report discovery. Verified at 212 tests. Merged to `main` at `5ec4744826dafa737931bde89733ee277bbf08ef`.

## Product v0.21 — reconciliation monitor / ambiguous delivery operations — complete

Added Delivery Ops over existing `Prepared` delivery attempts, bounded/privacy-safe output, explicit evidence-note reconciliation and authenticated reviewer attribution. Final exact-head CI passed 226 tests / 1 warning. Merged at `244757286ad8cb3a7302fc2e0e9f51cfb847f4c5`.

## Product v0.22 — Google Sheets connector — complete

Added `google_sheets`, `gsheets://...` locations, Google Sheets API v4 values ingestion, environment-backed Authorization references, deterministic header/ragged-row handling, existing preflight contracts and static Pages redaction. Final feature head passed 236 tests / 1 warning with live-source smoke green. Merged at `21c45c56f6f84328a88644b9df8e1c9ef474c383`. No real Google Workspace credential was supplied.

## Product v0.23 — deterministic Data Rules — complete

Added typed `not_null`, `allowed_values`, `numeric_range`, and `row_count_range` rules; fail-closed validation; privacy-bounded findings; preflight enforcement; normal Finding → Health integration; Data Rule UI; and public Pages privacy protection. Functional/privacy checkpoint passed 253 tests / 1 warning and live-source smoke; release merged at `e95b2d44fccbf23a2e694dab00299e54c08e2ba2`.

## Product v0.24 — reliability scorecards + trust badge — complete

Added deterministic `Not monitored` / `Trusted` / `Attention` / `Critical` badges mirroring current Health, explainable 7-day/30-day windows, incident/recovery/MTTR evidence, stale/rule occurrence counts, adaptive bounded history and count-only downstream context. Feature checkpoint passed 275 tests / 1 warning. Merged at `ac542a73db8657c455b5ea990ce5e1df3f93b1fb`.

## Product v0.25 — role-mapped Source Packs — complete

Implemented from exact v0.24 merge baseline `ac542a73db8657c455b5ea990ce5e1df3f93b1fb`:

- six workflow packs: FP&A Forecast, Sales Pipeline, Claims Register, Operations Orders, Finance Close and Customer Export;
- semantic roles rather than canned customer field names;
- fail-closed required/unknown/blank/duplicate role mapping validation;
- existing `MonitoringConfig` materialization only;
- conservative generated `not_null` and non-empty `row_count_range` rules;
- bounded row-diff fallback;
- non-persistent catalog/materialization APIs;
- normal preflight remains authoritative;
- explicit choose → role map → preview → apply → preflight onboarding UX;
- visible/editable row-comparison fields;
- stale-preflight invalidation after any contract edit;
- package/FastAPI/module versions aligned at `0.25.0`.

Final exact merge candidate `9d8f75fe7a6bf89acd07e2cf40459a4b7a127d2e` passed CI #595 with Ruff/compile/PostgreSQL 16 green and **303 passed / 1 warning**. Product v0.25 merged to `main` at `fdab78d706b6db75e88cba3d142a15372ca5908d`.

Live-source smoke was not triggered and is not claimed. Post-merge hosted `monitor-state` advanced to `db00ee1ea914c8bca5071f0af4fd656792182844`, verifying monitoring-state persistence after the release.

## Product v0.26 — self-service Microsoft/Google connection UX — current release candidate

Implemented from exact v0.25 merge baseline `fdab78d706b6db75e88cba3d142a15372ca5908d`:

- one shared Microsoft/Google provider model;
- local connector-readiness states without secret/environment-name serialization;
- fixed server credential references for external discovery;
- Microsoft credential check, drive discovery, `.xlsx` search and workbook-table discovery;
- Google credential check, spreadsheet discovery and GRID sheet/tab metadata discovery;
- bounded pagination and strict Microsoft Graph next-link validation;
- provider response bodies not copied into public errors;
- Operator-only connection discovery POST routes;
- no public arbitrary-environment readiness probe;
- packaged Add Source connection browser loaded as an optional enhancement;
- existing manual Microsoft/Google fields preserved;
- existing Source Packs, Data Rules, row-diff fields, preflight and guarded onboarding preserved;
- browser selections populate existing connector fields rather than a second persistence model;
- Google A1 range suggestion only for known grids <= 5,000 rows × 100 columns; larger/unknown grids require explicit analyst range selection;
- browser JavaScript contains no server credential names or bearer-token examples;
- provider discovery remains dynamic-app-only; static Pages remains read-only monitoring output;
- no ingestion, detector, source Health, persistence schema or monitoring-data changes.

Verified checkpoints:

- discovery foundation `79722100a930f1928a77f20cb709d9095a6be04b`: CI #604, **316 passed / 1 warning**;
- consolidated readiness/discovery API `4d0b369ffa14976e3d4cdcfbb21229a179ca4895`: CI #618, **327 passed / 1 warning**;
- Add Source connection browser + security-corrected UI `6f18044d33f25be59b04d27408066daffe35c8d4`: CI #634, **330 passed / 1 warning**.

All three exact checkpoints passed Ruff, compile/import checks and the PostgreSQL 16-backed suite.

Real Microsoft/Google tenant discovery is not claimed because no real provider credential was supplied for repository validation.

Release-only version/documentation changes are re-gated on their exact head before merge.

## Roadmap after v0.26

Prioritize real credential lifecycle and pilot validation rather than connector accumulation:

1. OAuth authorization-code connect/callback flow;
2. secure token/refresh-token storage and tenant/account identity evidence;
3. credential health, reconnect and revoke;
4. authenticated hosted managed-PostgreSQL pilot;
5. real Microsoft/Google/Power BI/email/Teams failure drills;
6. five-minute first-value onboarding with safe test/simulation controls;
7. customer/pilot validation before broad connector accumulation or billing complexity.

AI investigation remains downstream of deterministic evidence and must not redefine Health classification.
