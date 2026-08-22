# AnalystWatch Product v0.17 Architecture

## Decision

Product v0.17 adds Microsoft 365 Excel as a connector to the existing AnalystWatch ingestion boundary. It does **not** introduce a second profiling, detector, incident or notification architecture.

The connector normalizes a SharePoint / OneDrive Excel Table into the same pandas DataFrame used by CSV, local XLSX, JSON and API sources. Everything after ingestion remains deterministic and unchanged.

## Source contract

`SourceType.MICROSOFT_EXCEL` uses an internal location descriptor:

```text
m365://<drive-id>/<item-id>?table=<table-name>[&worksheet=<sheet>][&page_size=500]
```

The descriptor identifies the workbook and Excel Table but contains no bearer token.

Delegated Microsoft Graph authorization is supplied through the existing `request_header_env` mechanism:

```text
Authorization → <environment variable name>
```

Only the environment-variable name is persisted. The credential value remains external runtime configuration.

## Microsoft Graph adapter

`microsoft_excel.py` owns connector-specific Graph behavior:

1. validate the `m365://` descriptor;
2. require an injected `Authorization` header;
3. read DriveItem metadata for modified-time / ETag evidence;
4. read Excel Table columns;
5. read Excel Table rows;
6. follow Graph pagination safely;
7. normalize row width to the declared columns;
8. return a DataFrame plus standard ingestion metadata.

The adapter accepts only pagination URLs under `https://graph.microsoft.com/v1.0/` before following them.

Non-2xx Graph responses become normal ingestion availability evidence rather than uncaught monitor failures.

## Delegated-access boundary

The Excel workbook/table Graph operations used by v0.17 require delegated user access. This milestone does not claim application-permission support for those workbook APIs.

There is no OAuth account browser in v0.17. A production SaaS onboarding flow should later obtain the delegated token and discover tenant/site/drive/workbook/table identifiers for the user instead of asking them to supply identifiers manually.

That future UX can change the selection experience without changing this ingestion or detector boundary.

## Existing pipeline reuse

After connector ingestion, Microsoft Excel data flows through the same sequence as other tabular sources:

```text
Microsoft Graph Excel Table
→ DataFrame
→ preflight
→ profile
→ configured contracts
→ deterministic detectors
→ Health
→ observation/history
→ incident
→ notification candidate
```

This preserves detector comparability across source types and avoids Microsoft-specific reliability semantics.

## Metadata evidence

Where Graph supplies it, the connector records:

- DriveItem `lastModifiedDateTime` as `source_modified_at`;
- DriveItem ETag as `response_etag`;
- Graph HTTP status and request duration.

These values are source evidence; they do not independently redefine Health.

## Public-output boundary

Internal Microsoft identifiers are not useful on a public/static status page. `pages.py` therefore redacts the raw `m365://` descriptor and publishes only a label such as:

```text
Microsoft 365 Excel · FinanceTable
```

Regression coverage proves that generated Pages and `state.json` do not contain the drive ID, workbook item ID or authorization environment-variable name.

This redaction does not alter the persisted source definition used by the authenticated/local application runtime.

## Onboarding

The existing source-onboarding page now includes Microsoft 365 Excel. It collects:

- drive ID;
- workbook item ID;
- Excel Table;
- optional worksheet;
- delegated-token environment-variable name;
- normal cadence, freshness, numeric and key contracts.

The form synthesizes the internal source descriptor and then calls the same `/api/preflight` and `/api/onboard` paths used by existing sources.

The established rule remains: **Validate before monitoring.**

## Verification boundary

Product v0.17 is verified through deterministic mocked-Graph tests, PostgreSQL-backed full CI and the existing live public-source smoke gate.

The functional checkpoint passed **172 tests** plus Ruff and compile checks. Coverage includes parsing, row normalization, Graph pagination, metadata, authorization absence, Graph rejection, preflight reuse, onboarding UI and public-output redaction.

No live Microsoft tenant credential was used in this repository session, so a real SharePoint/OneDrive tenant connection is not claimed.

## Preserved Core v0.16 behavior

v0.17 does not change:

- detector thresholds;
- monitoring schedule semantics;
- storage schemas;
- workspace authorization;
- incident derivation;
- notification-candidate policy;
- delivery idempotency/reconciliation;
- hosted legacy SQLite/local-auth defaults.

## Next architecture step

Product v0.18 should add bounded row/key change evidence. The key architectural requirement is to persist only the minimum comparison material necessary for configured-key diffs, with explicit retention and sample limits, rather than turning AnalystWatch into an unlimited raw-data archive.
