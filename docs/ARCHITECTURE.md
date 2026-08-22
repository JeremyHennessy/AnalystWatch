# AnalystWatch Product v0.22 Architecture

## Decision

Product v0.22 adds Google Sheets as another `SourceType` while preserving the existing AnalystWatch ingestion, preflight, monitoring, persistence and UI architecture.

The architectural rule is: **Google Sheets is a connector into the existing source pipeline, not a parallel monitoring product.**

```text
SourceDefinition(type=google_sheets)
        ↓
environment-backed Authorization header resolution
        ↓
Google Sheets API v4 spreadsheets.values.get
        ↓
deterministic row-major values normalization
        ↓
pandas DataFrame
        ↓
existing preflight / profiling / detectors
        ↓
existing observations / baselines / row diff / incidents
```

No Google-specific observation, baseline, incident, detector or persistence model is introduced.

## Source contract

`SourceType.GOOGLE_SHEETS` uses the location format:

```text
gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]
```

`GoogleSheetsLocation` contains:

- `spreadsheet_id`;
- explicit A1 `range_name`;
- `header_row`, one-based and relative to the values returned for that range.

The parser requires a spreadsheet ID and range. Header row defaults to 1 and is bounded to 1..1000.

The source still uses the ordinary `MonitoringConfig` for monitor cadence, freshness expectations, numeric fields, unique keys, row-diff settings and request-header environment references.

## Provider/API boundary

`google_sheets.py` calls the Google Sheets API v4 values endpoint:

```text
GET /v4/spreadsheets/{spreadsheetId}/values/{range}
```

Request parameters are deliberately deterministic:

- `majorDimension=ROWS`;
- `valueRenderOption=UNFORMATTED_VALUE`;
- `dateTimeRenderOption=FORMATTED_STRING`.

The connector uses `httpx`, matching the existing provider/client approach. Product v0.22 does not introduce the Google SDK.

Provider non-2xx responses are converted to normal ingestion availability evidence with the HTTP status. If Google supplies an ETag it is retained as `response_etag`.

## Authorization boundary

Authorization reuses the existing environment-backed request-header contract.

A typical source definition stores only:

```text
request_header_env = {
  "Authorization": "ANALYSTWATCH_GOOGLE_AUTHORIZATION"
}
```

At runtime `_request_headers(...)` resolves the environment variable and passes the resulting header to the connector.

The credential value is not written into the source definition, public Pages output or Google-specific storage because no Google-specific storage exists.

Product v0.22 intentionally does not implement:

- OAuth refresh-token persistence/rotation;
- service-account private-key exchange;
- Google SDK credential objects;
- write scopes or Sheets mutations.

Those capabilities would require a separate credential-lifecycle design and are outside this connector milestone.

## Values → DataFrame normalization

Google's values API can return ragged rows. The connector therefore applies explicit table-shape rules before the existing monitor sees the data.

1. The response `values` member must be an array.
2. The configured header row must exist.
3. The header must contain at least one column.
4. Header names must be non-empty.
5. Header names must be unique.
6. Data rows may be shorter than the header and are padded with `None`.
7. Fully empty data rows are ignored.
8. A data row wider than the header fails closed.

These rules prevent a provider-shape quirk from silently changing the DataFrame schema or shifting values into inferred columns.

Once normalized, the result is a normal pandas DataFrame and all existing profiling/detector logic applies unchanged.

## Preflight reuse

Google Sheets does not get provider-specific detector logic.

`preflight_source(...)` continues to validate the same contracts after ingestion:

- availability;
- row/column profile;
- configured numeric fields;
- configured unique keys;
- latest-date field or conservative inference;
- expected refresh evidence.

This preserves one onboarding acceptance boundary across file, API, Microsoft Excel and Google Sheets sources.

## Freshness evidence boundary

The values read used in Product v0.22 does not expose a trustworthy sheet modification timestamp that AnalystWatch can directly map to `source_modified_at`.

The connector therefore leaves `source_modified_at=None` rather than inventing a modification date.

If `expected_refresh_minutes` is configured, the normal preflight rule must obtain freshness from content, for example:

- a configured `latest_date_field`; or
- the existing conservative date-field inference.

Without content-date evidence, preflight reports `freshness_unverifiable` and refuses to claim the refresh expectation can be checked.

A future metadata enhancement may add independently verified Google modification evidence, but it must not retroactively reinterpret current values-read evidence.

## Static/public privacy boundary

Private/runtime Google source locations contain the spreadsheet ID and can contain an authorization environment-variable reference in configuration.

`pages.py` special-cases Google Sheets public locations through `public_google_sheets_location(...)` and renders only:

```text
Google Sheets · <A1 range>
```

The static index, source detail and `state.json` are regression-tested to exclude:

- spreadsheet ID;
- internal `gsheets://` location;
- authorization environment-variable name.

The A1 range remains visible because it describes the monitored data slice without exposing the private spreadsheet identifier.

## Onboarding boundary

The existing Add Source page is extended using the existing connector-specific form pattern.

For `google_sheets` it collects:

- Spreadsheet ID;
- A1 range;
- header row;
- Google Authorization environment-variable reference.

Client-side code constructs the canonical `gsheets://` location and normal `request_header_env` mapping, then submits the same `/api/preflight` and `/api/onboard` requests used by every other source type.

No separate Google onboarding endpoint or persistence flow is introduced.

The UI also states the freshness limitation: a range read does not itself provide a sheet modification timestamp, so an expected-refresh contract should include trustworthy content-date evidence.

## Preserved Product v0.21 architecture

Product v0.21 Delivery Ops remains unchanged:

- reconciliation queue is derived from existing `Prepared` delivery attempts;
- Prepared remains neither success nor failure;
- retry remains blocked until explicit evidence-backed reconciliation;
- no automatic retry is created by reconciliation;
- signed-bearer reconciliation records the authenticated reviewer;
- bounded queue output avoids exposing idempotency keys, claim owners, provider raw evidence or reconciliation notes.

Product v0.21 was merged to `main` at `244757286ad8cb3a7302fc2e0e9f51cfb847f4c5` after final exact-head CI passed 226 tests, 1 warning.

## Preserved Teams / dependency / Power BI architecture

Product v0.22 does not change:

- Teams Workflows delivery or its existing candidate/attempt/idempotency/reconciliation model;
- dependency graph asset/edge storage or cycle-safe blast radius;
- Power BI Guard trust correlation;
- Power BI discovered-edge namespaces;
- source-detail downstream-impact rendering;
- Viewer / Operator / Admin authorization model.

A Google Sheets source can participate in the existing SourceGuard and dependency model exactly like another source ID; no Google-specific graph semantics are required.

## Persistence

No Google-specific database schema is introduced.

`SourceDefinition` already persists the source type, location and `MonitoringConfig`. Existing legacy/namespaced/PostgreSQL storage therefore carries Google Sheets configuration through the same source-definition contract.

Only the authorization environment-variable name is persisted, not the credential value.

## Public/static application boundary

The public GitHub Pages build remains a read-only source-monitoring snapshot.

It may show a redacted Google Sheets source and its published monitoring result, but it does not expose private spreadsheet identifiers or credentials and still does not fabricate:

- Teams delivery configuration/outcomes;
- Power BI tenant evidence;
- dynamic dependency graph state;
- reconciliation queue state.

## Preserved behavior

Product v0.22 does not change:

- existing CSV/XLSX/JSON/API/Microsoft Excel ingestion semantics;
- source detector thresholds;
- Healthy / Warning / Critical classification;
- baseline promotion/review;
- row-level comparison semantics/retention;
- incident lifecycle;
- notification candidate policy;
- Prepared/Succeeded/Failed delivery semantics;
- retry/reconciliation safety;
- dependency traversal/storage;
- Power BI trust logic;
- source scheduler;
- approved UI layout/CSS architecture.

## Verification

The verified Product v0.22 functional checkpoint is `9cb60774817a2a637a1714a5c15ccd643faa4324`.

CI #495 passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed suite;
- **236 passed, 1 warning**.

Live-source smoke #80 also passed.

Coverage includes:

- canonical location parsing and public location;
- Google Authorization environment-reference enforcement;
- API path/options and ETag evidence;
- header-row handling;
- ragged-row normalization;
- duplicate/empty-header and over-wide-row failures;
- provider HTTP rejection evidence;
- existing numeric/key/date preflight reuse;
- freshness-unverifiable behavior without content-date evidence;
- static Pages privacy redaction;
- connector-specific onboarding fields;
- all existing Product v0.21 regressions.

No real Google Workspace credential was supplied in this repository session, so live Google Sheets access is not claimed.

## Next architecture step

Product v0.23 should add deterministic business/Data Rules through the existing source evidence pipeline. Rules should be explicit, auditable assertions over ingested/profiled data and must not create an opaque AI-driven Health classification path.
