# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON, REST API and Microsoft 365 Excel inputs: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Product v0.17 status

Product v0.17 adds the first Microsoft 365 Excel connector for SharePoint and OneDrive workbooks while preserving the existing deterministic profiling, detector, incident and notification architecture.

The connector is deliberately table-first. AnalystWatch reads an Excel Table through Microsoft Graph, converts it to the same pandas/DataFrame representation used by existing sources, and then runs the normal preflight/profile/detector pipeline. There is no Microsoft-specific health classifier.

### Microsoft 365 Excel source

A Microsoft source uses the internal location contract:

```text
m365://<drive-id>/<item-id>?table=<table-name>[&worksheet=<sheet>][&page_size=500]
```

The onboarding UI exposes this as separate fields for:

- SharePoint / OneDrive drive ID;
- workbook item ID;
- Excel table name;
- optional worksheet;
- delegated Microsoft Graph authorization environment variable.

The bearer token itself is never stored in the source definition. The source contains only the name of the environment variable that supplies the `Authorization` header at runtime.

### Connector evidence

The Graph adapter reads:

- DriveItem metadata including `lastModifiedDateTime` and ETag when available;
- Excel Table columns;
- Excel Table rows;
- Microsoft Graph pagination links.

Rows are normalized into the existing tabular monitoring representation, so configured keys, numeric fields, freshness checks, schema drift, row-count drift, null-rate drift and the rest of the existing detector pipeline work without duplication.

### Public-output protection

Generated Pages and `state.json` do not publish Microsoft drive IDs, workbook item IDs or token environment-variable names. A Microsoft source is rendered publicly as a human label such as:

```text
Microsoft 365 Excel · FinanceTable
```

### Authentication boundary

The Excel workbook APIs used by this connector require delegated Microsoft Graph access. Product v0.17 therefore does **not** claim application-only Microsoft Graph access for these workbook/table operations.

The repository does not contain a real Microsoft tenant credential, and this milestone does not claim a live tenant connection. The connector and onboarding path are verified deterministically using mocked Graph responses.

A future account-connection improvement should add the full user flow:

```text
Connect Microsoft 365
→ choose SharePoint site / OneDrive
→ choose workbook
→ choose Excel table
→ preflight
→ monitor
```

without changing the monitoring engine.

## Existing SaaS foundation

Core v0.16 remains intact underneath v0.17:

- authenticated workspace authorization from v0.15;
- SQLite, namespaced SQLite and PostgreSQL persistence;
- managed-runtime readiness and PostgreSQL recovery validation;
- first live-email adapter behind the existing delivery-attempt state machine;
- hosted GitHub Pages monitor still using legacy SQLite/local auth unless explicitly cut over.

No production PostgreSQL cutover or successful real Resend delivery is implied by v0.17.

## Verification

The v0.17 functional checkpoint passed:

- Ruff;
- compile/import gate;
- **172 deterministic tests** against PostgreSQL 16 CI;
- Microsoft Graph ingestion, pagination, failure and preflight regressions;
- Microsoft onboarding regression coverage;
- public Pages redaction tests for Microsoft identifiers;
- live-source smoke against the existing public Bank of Canada / U.S. Treasury source set.

No detector thresholds, persistence semantics, incident semantics or notification state-machine behavior changed in this milestone.

## Next milestone

Product v0.18 is **row-level / key-level change analysis**. For sources with configured keys, AnalystWatch should move from “something changed” to bounded, privacy-aware evidence showing which rows and columns were added, removed or changed relative to the previous successful observation and active baseline.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
