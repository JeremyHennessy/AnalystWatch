# AnalystWatch Product v0.26 Architecture

## Decision

Product v0.26 adds a **non-persistent provider-discovery layer around the existing Microsoft 365 Excel and Google Sheets connectors**.

The architectural rule is: **connection UX may make an existing connector easier to configure, but it cannot create a second source model, hide the resulting connector location, persist bearer tokens, bypass preflight, or influence source Health.**

```text
server-managed provider credential reference
        ↓
connection check / resource discovery
        ↓
analyst selects provider resource
        ↓
existing m365:// or gsheets:// location fields
        ↓
ordinary SourceDefinition + MonitoringConfig
        ↓
existing /api/preflight
        ↓
existing guarded onboarding
        ↓
existing ingestion / findings / Health / incidents
```

## Provider model

`ConnectionProvider` is shared by discovery and local readiness logic:

- `microsoft`;
- `google`.

There is one provider model rather than separate readiness/discovery enums.

`ConnectionReadiness` is local configuration evidence only. It may report:

- `invalid_location`;
- `needs_credential_reference`;
- `needs_credential_value`;
- `ready_to_test`.

`ready_to_test` is intentionally narrow: AnalystWatch has enough local configuration to attempt a provider request. It does not prove token validity, tenant membership, resource access, or future provider availability.

Readiness serializes neither bearer-token values nor the referenced environment-variable name.

## Credential boundary

Existing connector sources continue to use environment-backed Authorization references in `MonitoringConfig.request_header_env`.

Product v0.26 adds no token persistence table, encrypted secret store, refresh-token flow, OAuth callback, or provider session state.

Dynamic discovery endpoints use fixed runtime references only:

```text
Microsoft → ANALYSTWATCH_MICROSOFT_AUTHORIZATION
Google    → ANALYSTWATCH_GOOGLE_AUTHORIZATION
```

The caller cannot choose an arbitrary environment-variable name.

Public connection-check responses expose only bounded status:

- provider;
- configured boolean;
- reachable boolean;
- HTTP status when available;
- bounded error text.

They do not expose the credential environment-variable name, token value, or raw provider error body.

An early provisional endpoint that accepted an arbitrary `SourceDefinition` for readiness calculation was removed before release because it could have been used as an environment-variable-existence oracle. Readiness remains an internal/local model while external discovery is fixed-reference only.

## Microsoft discovery

Microsoft discovery uses Microsoft Graph v1.0 and the existing delegated-access connector model.

The dynamic setup flow can:

1. test the standard server Microsoft credential;
2. enumerate current-user drives;
3. search a selected drive for matching files;
4. retain only real `.xlsx` file items;
5. enumerate workbook tables;
6. copy the selected drive/item/table identifiers into the existing Microsoft connector controls.

No selected resource is persisted by discovery itself.

### Microsoft pagination safety

Graph collection helpers have a bounded page limit.

Any `@odata.nextLink` must:

- use HTTPS;
- have host `graph.microsoft.com`;
- remain under `/v1.0/`.

Unexpected hosts/paths fail closed and are never followed.

Provider response bodies are not copied into public errors.

## Google discovery

Google discovery uses:

- Drive API v3 for spreadsheet file discovery;
- Sheets API v4 metadata for sheet/tab discovery.

The dynamic setup flow can:

1. test the standard server Google credential;
2. list non-trashed Google spreadsheet files;
3. include shared-drive-visible items through the existing metadata query parameters;
4. load sheet properties for a selected spreadsheet;
5. retain selectable `GRID` sheets only;
6. copy the selected spreadsheet ID into the existing Google connector control.

No spreadsheet or sheet selection is persisted until ordinary source onboarding succeeds.

### Google range safety

A Google Sheet tab is not itself a complete monitoring contract. The existing connector still requires an explicit A1 range.

The Add Source browser may suggest an A1 range only when returned grid dimensions are known and bounded at no more than:

- 5,000 rows;
- 100 columns.

For larger or unknown grids, the helper intentionally does not manufacture a truncated range. The analyst must enter an explicit A1 range before preflight.

This preserves the existing deterministic ingestion boundary and avoids silently excluding provider data for UI convenience.

## API boundary

Product v0.26 adds Operator-only POST endpoints:

```text
/api/connections/microsoft/check
/api/connections/microsoft/drives
/api/connections/microsoft/workbooks
/api/connections/microsoft/tables
/api/connections/google/check
/api/connections/google/spreadsheets
/api/connections/google/sheets
```

These endpoints are discovery/calculation surfaces only.

They do not:

- create/update a source;
- establish a baseline;
- run source monitoring;
- persist a provider resource selection;
- persist a token;
- write observation history;
- change source Health.

Signed-bearer authorization classifies the connection POST prefix as `Operator` rather than the default Admin-only mutation bucket. Viewer access is insufficient for external provider discovery.

## Add Source UI boundary

The approved v0.25 onboarding form remains authoritative.

Product v0.26 adds `static/connection_onboard.js` as an optional enhancement loaded by the existing Add Source template. It injects browse/test controls inside the existing Microsoft and Google sections.

The existing manual fields remain visible and editable:

Microsoft:

- Drive ID;
- workbook item ID;
- Excel table;
- optional worksheet;
- environment-backed Authorization reference.

Google:

- spreadsheet ID;
- A1 range;
- header row;
- environment-backed Authorization reference.

Source Packs, Data Rules, row-comparison fields, run policy, preflight evidence, and guarded onboarding are not replaced.

Browser selections populate those ordinary controls and dispatch normal form-input events. Therefore the v0.25 stale-preflight rule remains authoritative: if the selected provider resource changes after a successful preflight, Add Source is disabled until preflight runs again.

The browser JavaScript contains no fixed credential environment-variable names or bearer-token examples.

## Existing connector boundary

Product v0.26 does not modify `ingest_source(...)`, Microsoft Excel ingestion, or Google Sheets values ingestion.

The final source still uses existing connector locations:

```text
m365://<drive-id>/<item-id>?table=<table-name>[&worksheet=<sheet>]

gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]
```

Those locations continue through the existing parsers, ingestion functions, profiling, preflight, runtime monitoring, and Pages privacy rules.

## Source Pack coexistence

Source Packs and connection discovery solve different parts of onboarding:

- connection discovery answers **where is the provider data?**;
- Source Packs answer **which business fields must remain trustworthy?**

They converge only in the existing Add Source form and then become an ordinary `SourceDefinition` plus `MonitoringConfig`.

There is no combined pack/connection persistence model.

## Health and monitoring boundary

Connection discovery is not a Health detector.

It cannot produce Healthy / Warning / Critical and cannot change scorecards, incidents, baselines, notifications, dependencies, delivery attempts, or reviews.

After onboarding, the existing source ingestion and deterministic finding pipeline remain the only source-monitoring path.

Product v0.26 therefore requires no monitoring-database migration and no rewrite of existing hosted source data.

## Dynamic app vs static Pages

Provider discovery is intentionally dynamic-app-only.

The FastAPI app may contact Microsoft/Google using configured server credentials for an authorized Operator.

Static GitHub Pages remains a read-only monitoring artifact and receives no provider-discovery controls or credential state. Existing Pages redaction/privacy boundaries remain unchanged.

## Hosted data custody

Product v0.25 merged at `fdab78d706b6db75e88cba3d142a15372ca5908d`.

Post-merge `monitor-state` advanced to `db00ee1ea914c8bca5071f0af4fd656792182844`, confirming hosted monitoring-state persistence after the v0.25 release.

Because v0.26 changes setup UX rather than monitoring data or ingestion semantics, no hosted database mutation is required as part of this release.

## Verification

Exact green checkpoints:

- discovery foundation `79722100a930f1928a77f20cb709d9095a6be04b`: **316 passed, 1 warning**;
- consolidated readiness/discovery API `4d0b369ffa14976e3d4cdcfbb21229a179ca4895`: **327 passed, 1 warning**;
- Add Source provider browser + security-corrected UI `6f18044d33f25be59b04d27408066daffe35c8d4`: **330 passed, 1 warning**.

Each checkpoint passed Ruff, compile/import checks, and the PostgreSQL 16-backed suite.

The UI regression boundary verifies that manual Microsoft/Google fields, Source Packs, preflight, and Add monitored source remain present while the separate connection browser is loaded.

No real Microsoft or Google tenant credential was supplied for repository validation, so real tenant discovery is not claimed.

Release-only metadata/documentation changes are re-gated on their exact head before merge.

## Next architecture step

The next connection milestone should add a real OAuth credential lifecycle rather than more discovery endpoints:

- authorization-code initiation/callback;
- securely persisted tokens/refresh metadata;
- reconnect/revoke;
- credential health without secret disclosure;
- explicit tenant/account identity evidence;
- migration away from operator-provisioned environment bearer tokens where appropriate.

Only after that should AnalystWatch run a real hosted Microsoft/Google/Power BI/notification pilot and full end-to-end failure drills.

AI investigation remains downstream of deterministic evidence and must not redefine Health.
