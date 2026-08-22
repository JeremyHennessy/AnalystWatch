# AnalystWatch

**Reliability monitoring for analyst-owned data and reporting workflows.**

AnalystWatch monitors CSV, Excel, JSON, REST API, Microsoft 365 Excel and Google Sheets inputs for silent reliability failures, carries that trust signal into downstream reporting workflows, helps analysts understand downstream impact, and keeps ambiguous outbound-delivery outcomes visible until an operator can resolve them from evidence.

The product question is: **can I trust the data feeding this analysis or report today, what is affected if I cannot, and are any delivery outcomes still operationally unresolved?**

## Product v0.22 status

Product v0.22 adds a **Google Sheets connector** through the same ingestion, preflight, onboarding and monitoring contracts already used by the existing source types.

The connector deliberately does not create a parallel Google-specific monitoring system. A Google Sheets range becomes an ordinary AnalystWatch `SourceDefinition`, is converted into a deterministic DataFrame, then passes through the existing profiler, preflight rules, detectors, baseline/history, row-diff and incident logic.

The verified v0.22 functional checkpoint passed **236 tests, 1 warning** with Ruff, compile/import checks and PostgreSQL 16 CI green. Live-source smoke #80 also passed against the existing hosted source set.

## Google Sheets connector

Google Sheets sources use source type `google_sheets` and the location contract:

`gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]`

`header_row` is one-based and relative to the returned A1 range. The default is `1`.

The connector calls Google Sheets API v4 `spreadsheets.values.get` with:

- `majorDimension=ROWS`;
- `valueRenderOption=UNFORMATTED_VALUE` so numeric values remain suitable for existing numeric profiling;
- `dateTimeRenderOption=FORMATTED_STRING` so date/time cells have deterministic text evidence for existing freshness/date parsing.

The returned values are normalized conservatively:

- the configured header row must exist and contain non-empty unique column names;
- data rows shorter than the header are padded with `None`;
- fully blank data rows are ignored;
- rows wider than the header fail closed rather than silently changing table shape.

Provider non-2xx responses remain availability failures with the HTTP status recorded. Response ETag is retained when Google supplies it.

## Google authorization boundary

Google authorization reuses `MonitoringConfig.request_header_env` rather than storing credentials in a Google-specific model.

The onboarding UI defaults the Authorization environment-variable reference to:

`ANALYSTWATCH_GOOGLE_AUTHORIZATION`

That environment variable should contain an authorization value such as `Bearer ...` at runtime. The bearer token value is not persisted in the source definition.

Product v0.22 intentionally does **not** add:

- a Google SDK dependency;
- OAuth refresh-token management;
- service-account key exchange;
- Google Sheets write access.

A real Google Workspace credential was not supplied or invoked in this repository session, so live Google Sheets tenant access is **not claimed**.

## Freshness evidence for Google Sheets

The `spreadsheets.values.get` range read does not provide a sheet modification timestamp that AnalystWatch can safely treat as refresh evidence.

Therefore Product v0.22 does not fabricate `source_modified_at` for Google Sheets. If a source config declares `expected_refresh_minutes`, preflight must also be able to establish freshness from the data itself, for example through a configured `latest_date_field` or the existing conservative date-field inference. Without that evidence, preflight reports `freshness_unverifiable` rather than assuming the sheet is current.

## Google Sheets onboarding

The existing Add Source page now includes Google Sheets as a source type with connector-specific fields:

- Spreadsheet ID;
- explicit A1 range;
- header row within the returned range;
- Google token environment-variable reference.

The same page continues to configure the existing monitoring cadence and data contracts such as freshness field, numeric fields and unique keys. Preflight remains mandatory before a source can be accepted through the normal onboarding flow.

## Static Pages privacy

The public GitHub Pages export does not publish Google spreadsheet identifiers or authorization references.

A Google Sheets source renders publicly as:

`Google Sheets · <A1 range>`

The static index, source detail and `state.json` are regression-tested to exclude:

- the spreadsheet ID;
- the internal `gsheets://` location;
- the authorization environment-variable name.

This preserves the existing distinction between the private/runtime source definition and the bounded public monitoring snapshot.

## Product v0.21 foundation — Delivery Ops

Product v0.21 added operational reconciliation monitoring over the existing delivery-attempt state machine.

- `Prepared` remains neither success nor failure;
- retry remains blocked while the outcome is ambiguous;
- an operator must use durable external evidence to reconcile the attempt to `Succeeded` or `Failed`;
- reconciliation does not automatically create a retry;
- signed-bearer reconciliation records the authenticated operator as reviewer;
- `/reconciliation` and `GET /api/delivery-reconciliation` expose a bounded Prepared-attempt queue without idempotency keys, claim owners, provider raw evidence, reconciliation notes or secrets.

Product v0.21 was merged to `main` at `244757286ad8cb3a7302fc2e0e9f51cfb847f4c5` after its final exact-head CI passed **226 tests, 1 warning**.

## Product v0.20 foundation — Teams and impact intelligence

Product v0.20 added:

- Microsoft Teams Workflows / Power Automate delivery behind the existing eligible-candidate and delivery-attempt safety model;
- explicit provider rejection → `Failed`;
- ambiguous transport outcome → `Prepared` for reconciliation;
- same-key idempotency protection against duplicate external POSTs;
- Source / Workbook / Semantic Model / Report / Custom dependency assets;
- explicit and discovered dependency edges;
- deterministic cycle-safe blast radius;
- Power BI source → semantic model → report discovery;
- additive source-detail downstream-impact context.

A real Teams Workflows webhook has not been supplied in this repository session, so a real Teams side effect remains unverified. A real Power BI tenant credential also has not been supplied, so live Power BI tenant access remains unverified.

## Product surfaces

The authenticated/local FastAPI application exposes four connected analyst surfaces:

- SourceGuard — monitored source health, incidents, history and downstream impact;
- Power BI Guard — semantic-model trust and Power BI evidence;
- Dependency Map — recorded relationships and blast radius;
- Delivery Ops / Reconciliation Monitor — unresolved Prepared attempts and evidence-backed reconciliation.

Google Sheets participates in SourceGuard through the existing source model; it does not require a fifth product surface.

The public GitHub Pages deployment remains a read-only monitoring snapshot and does not fabricate dynamic Teams, Power BI, dependency or reconciliation state.

## Persistence

Product v0.22 adds no Google-specific persistence schema. Google Sheets source configuration is stored through the existing source-definition storage contract, with only the environment-variable reference persisted for authorization.

Existing workspace-aware SQLite/namespaced/PostgreSQL source state, Power BI Guard storage, dependency storage and delivery-attempt persistence remain unchanged.

## Existing product foundation

Previously verified capabilities remain intact, including:

- deterministic source ingestion/profiling/detectors;
- CSV / XLSX / JSON / REST API monitoring;
- Microsoft 365 SharePoint / OneDrive Excel-table ingestion;
- source preflight and onboarding;
- historical baselines and reviews;
- incident lifecycle and notification policy;
- dry-run, live-email and Teams delivery architecture;
- reconciliation monitoring;
- authenticated workspace authorization;
- SQLite, namespaced SQLite and PostgreSQL persistence;
- row-level / key-level change analysis with bounded retention;
- Power BI Guard trust correlation and evidence collection;
- dependency mapping and blast radius;
- diverse hosted demo sources across CSV, JSON, XLSX and public APIs.

## Verification

The Product v0.22 functional checkpoint on `9cb60774817a2a637a1714a5c15ccd643faa4324` passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed test suite;
- **236 passed, 1 warning**;
- live-source smoke #80.

Coverage includes:

- Google Sheets location parsing and public-location rendering;
- Authorization environment-reference enforcement;
- Sheets API request path and stable value-rendering options;
- row normalization, padding and empty-row handling;
- fail-closed duplicate/empty headers and over-wide rows;
- provider HTTP error evidence;
- reuse of numeric/key/latest-date preflight contracts;
- `freshness_unverifiable` when expected refresh lacks trustworthy date evidence;
- static Pages spreadsheet/token-reference redaction;
- connector-specific onboarding fields;
- all existing Product v0.21 regressions.

No live Google credential was supplied, so live Google Workspace access remains unverified.

## Next milestone

Product v0.23 is **business rules / Data Rules**: add deterministic analyst-defined assertions downstream of ingestion/profile evidence, without weakening the existing source Health and audit boundaries.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
