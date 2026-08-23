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

Implemented Microsoft Teams Workflows / Power Automate delivery behind existing delivery safety, workspace-scoped dependency assets/edges, deterministic cycle-safe blast radius and Power BI source → semantic-model → report discovery. Verified checkpoint: **212 tests**, Ruff/compile/PostgreSQL 16 green. Merged to `main` at `5ec4744826dafa737931bde89733ee277bbf08ef`.

No retired Office 365 Connector implementation, enterprise SQL-column lineage, separate Teams state machine, source Health changes or unverified Microsoft side-effect claims were introduced.

## Product v0.21 — reconciliation monitor / ambiguous delivery operations — complete

Added the read-only Delivery Ops reconciliation queue over existing `Prepared` delivery attempts, bounded/privacy-safe output, explicit evidence-note reconciliation and authenticated reviewer attribution. Final exact-head CI passed **226 tests, 1 warning**. Merged to `main` at `244757286ad8cb3a7302fc2e0e9f51cfb847f4c5`.

No automatic ambiguity inference, automatic retry, provider-specific reconciliation polling, detector/Health change, UI redesign or new delivery-state schema was introduced.

## Product v0.22 — Google Sheets connector — complete

Implemented from exact v0.21 merge baseline `244757286ad8cb3a7302fc2e0e9f51cfb847f4c5`:

- new `google_sheets` source type;
- `gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]` source location contract;
- Google Sheets API v4 `spreadsheets.values.get` read path;
- row-major retrieval with deterministic numeric/date rendering;
- environment-backed Authorization header reference through the existing `request_header_env` contract;
- deterministic configured header-row parsing and conservative ragged-row normalization;
- existing numeric-field, unique-key, latest-date and freshness preflight contracts reused unchanged;
- no fabricated Google Sheets modification timestamp;
- expected refresh requires content-date evidence or preflight reports `freshness_unverifiable`;
- static Pages redact spreadsheet ID, internal `gsheets://` location and token environment-variable name;
- existing Add Source UI exposes Spreadsheet ID, A1 range, header row and token environment reference;
- no new detector thresholds, source Health semantics or persistence schema.

Final verified feature head passed **236 tests, 1 warning** with Ruff/compile/PostgreSQL 16 green and live-source smoke green. Product v0.22 merged to `main` at `21c45c56f6f84328a88644b9df8e1c9ef474c383`.

No real Google Workspace credential was supplied, so live Google Sheets tenant access was not claimed.

## Product v0.23 — deterministic Data Rules — complete

Implemented from exact v0.22 merge baseline `21c45c56f6f84328a88644b9df8e1c9ef474c383`:

- typed deterministic rule kinds: `not_null`, `allowed_values`, `numeric_range`, `row_count_range`;
- explicit rule ID, analyst-facing name, Warning/Critical failure severity and optional business guidance;
- fail-closed rule-model validation and duplicate-rule-ID rejection;
- deterministic DataFrame evaluator that returns ordinary `Finding` evidence;
- no failing row values copied into Data Rule findings;
- bounded aggregate violation counts/percentages for field-based failures;
- preflight evaluates configured rules and refuses to accept a source already violating its declared contract;
- runtime `check_source(...)` appends Data Rule findings before the existing single `health_from_findings(...)` derivation;
- existing incident, notification, delivery, review and baseline behavior remains downstream of ordinary Health rather than a parallel rule state machine;
- typed Data Rule builder added to the existing Add Source UI;
- authenticated/local source detail retains the private declared rule contract while failing row values remain absent;
- public Pages genericize Data Rule findings and remove public profile/config/row-diff evidence for fields referenced by Data Rules;
- ordinary detector findings that would reveal a private Data Rule field are genericized in public output;
- unrelated public profile evidence remains visible;
- package/FastAPI/module version metadata aligned at `0.23.0`.

Functional/UI/privacy checkpoint `ba779642aeaa971ceda38fa1799ea4f2387904a2` passed **253 tests, 1 warning** with Ruff/compile/PostgreSQL 16 and live-source smoke #100 green. Release head `12573b6f83984e1ada0f0ee878d69b294c7b6ebc` passed the final gate and live-source smoke #101. Product v0.23 merged to `main` at `e95b2d44fccbf23a2e694dab00299e54c08e2ba2`.

Explicit non-goals remained: no SQL/arbitrary expression language, no AI-defined rules/Health, no detector-threshold rewrite, no new observation/incident/persistence state machine, and no unrelated UI redesign.

## Product v0.24 — reliability scorecards + trust badge — complete

Implemented from exact v0.23 merge baseline `e95b2d44fccbf23a2e694dab00299e54c08e2ba2`:

- deterministic `TrustBadge`: `Not monitored`, `Trusted`, `Attention`, `Critical`;
- badge maps only the latest current Health and never becomes a second classifier;
- explainable 7-day and 30-day reliability windows;
- check count, successful-check ratio, Healthy-check ratio, Warning/Critical counts;
- incident opening/recovery counts derived from the existing transition function;
- stale and Data Rule failure occurrences counted once per observation;
- MTTR only when a real incident opening timestamp is known;
- timezone-aware inclusive windows and future-observation exclusion;
- adaptive history loading based on configured monitoring cadence;
- history expansion until pre-window Healthy context is available or a 50,000-observation safety cap is reached;
- explicit `history_complete` claim-safety state;
- no fabricated incident opening or MTTR when history is truncated;
- dedicated scorecard API with count-only downstream-impact context;
- downstream asset names/IDs/URLs excluded from the scorecard endpoint;
- downstream impact cannot change Health or the trust badge;
- compact scorecard panel added to the existing source detail without redesigning the established detail layout;
- same deterministic aggregate scorecard rendered in static Pages and serialized in public `state.json`;
- v0.23 private Data Rule contracts remain redacted while aggregate rule-failure occurrence counts remain available;
- no database migration, new connector, detector-threshold change or numeric black-box score.

Feature/UI/static checkpoint `4fc6e6126391da630a635b2ea9c04cfc7890d6fe` passed **275 tests, 1 warning** with Ruff/compile/PostgreSQL 16 green. Release head `381137d1a3d337585fbe749bbdca04f2820fa267` passed the final CI gate and Product v0.24 merged to `main` at `ac542a73db8657c455b5ea990ce5e1df3f93b1fb`.

Live-source smoke was not triggered by the v0.24 change set and was not claimed. Post-merge `monitor-state` persistence advanced on the v0.24 release.

## Product v0.25 — role-mapped Source Packs — current release

Implemented from exact v0.24 merge baseline `ac542a73db8657c455b5ea990ce5e1df3f93b1fb`:

- six typed workflow packs: FP&A Forecast, Sales Pipeline, Claims Register, Operations Orders, Finance Close and Customer Export;
- semantic roles instead of canned customer-specific field names;
- explicit analyst mapping from roles to real source columns;
- fail-closed required-role, unknown-role, blank/untrimmed and duplicate-field validation;
- optional roles omitted rather than guessed;
- pack schedule defaults with explicit positive-value overrides;
- materialization into the existing `MonitoringConfig` only;
- generated existing freshness field, unique-key, numeric-field and bounded row-diff settings;
- conservative generated `not_null` and non-empty `row_count_range` Data Rules only;
- no hidden allowed-value sets, numeric bounds, detector thresholds, SQL or AI rules;
- bounded row-diff fallback prevents omitted optional pack roles from silently expanding comparison to every source column;
- non-persistent `GET /api/source-packs` catalog;
- non-persistent `POST /api/source-packs/materialize` contract preview;
- materialization does not create, persist, baseline or monitor a source;
- materialized configs still pass through the existing authoritative `/api/preflight` boundary;
- generated Data Rule failures reject preflight exactly like manually configured rules;
- existing Add Source page now supports choose → role map → preview → explicit apply → normal preflight;
- selecting a pack without applying it cannot silently alter a source;
- applying a pack copies ordinary config into existing onboarding controls and does not persist pack metadata;
- no persistence migration or second source/config state model;
- package/FastAPI/module version metadata aligned at `0.25.0` during release closeout.

Isolated checkpoints:

- pure pack materializer: **294 passed, 1 warning**;
- catalog/materialization API + normal-preflight integration: **299 passed, 1 warning**;
- functional/API/UI checkpoint `ca91d63e4c857a4faa154c17e29c36aafd78653d`: **302 passed, 1 warning**, Ruff/compile/PostgreSQL 16 green.

Release-only metadata/docs are re-gated on their exact head before merge.

Explicit non-goals:

- no connector expansion;
- no schema guessing or AI role mapping;
- no hidden business-state enum assumptions;
- no numeric business-limit assumptions;
- no detector-threshold changes;
- no pack-specific persistence model;
- no preflight bypass;
- no new Health or incident state machine.

## Roadmap after v0.25

The immediate feature-focused sequence ends with Product v0.25. Prioritize product usability and real-world validation next:

1. self-service Microsoft connection UX for account authorization and workbook/table selection;
2. self-service Google connection UX for account authorization and spreadsheet/sheet/range selection;
3. credential lifecycle: health, reconnect and revoke;
4. authenticated hosted pilot on managed PostgreSQL;
5. real Microsoft/Google/Power BI/email/Teams end-to-end failure drills;
6. five-minute first-value onboarding with test alerts and safe failure simulation;
7. customer/pilot validation before broad connector accumulation or billing complexity.

AI investigation remains downstream of deterministic evidence and must not redefine Health classification.
