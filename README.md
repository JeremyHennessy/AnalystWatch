# AnalystWatch

**Reliability monitoring for analyst-owned data and reporting workflows.**

AnalystWatch monitors CSV, Excel, JSON, REST API, Microsoft 365 Excel and Google Sheets inputs for silent reliability failures, carries that trust signal into downstream reporting workflows, helps analysts understand downstream impact, and keeps ambiguous outbound-delivery outcomes visible until an operator can resolve them from evidence.

The product question is: **can I trust the data feeding this analysis or report today, what is affected if I cannot, and are any delivery outcomes still operationally unresolved?**

## Product v0.23 status

Product v0.23 adds **deterministic analyst-defined Data Rules** to the existing source evidence pipeline.

The release does not create a second Health system. Rules are evaluated against the ingested DataFrame, produce ordinary AnalystWatch `Finding` evidence, and then enter the existing single `health_from_findings(...)` classification boundary together with schema, freshness, null, numeric, category, uniqueness and row-count findings.

Supported rule kinds are:

- `not_null` — a declared field must contain no null values;
- `allowed_values` — values must remain inside an explicit allowed set;
- `numeric_range` — numeric values must remain within a configured minimum and/or maximum;
- `row_count_range` — source row count must remain within configured integer bounds.

Every rule has an explicit ID, analyst-facing name and Warning/Critical failure severity. Field-based rules can also carry analyst-defined business impact and investigation guidance.

## Data Rule contract and safety

`MonitoringConfig.data_rules` is typed and fail-closed.

Invalid combinations are rejected before monitoring, including missing required fields, empty allowed sets, incompatible parameters, invalid numeric/range bounds and duplicate rule IDs.

The first release deliberately does **not** include:

- SQL or arbitrary expression execution;
- AI-defined rules;
- AI-driven Health classification;
- detector-threshold rewrites;
- a separate rule incident/state machine;
- a Data Rule persistence schema.

Rules remain explicit, deterministic and auditable.

## Preflight and onboarding

Configured Data Rules are evaluated during normal source preflight.

A source that already violates its declared rule contract is not accepted as ready for onboarding. This acceptance boundary is intentionally stricter than runtime severity: even a rule configured as Warning must pass preflight before a new or edited source is accepted.

The existing Add Source page now includes a typed Data Rule builder for rule ID, name, kind, failure severity, field/allowed-values/range parameters and optional business-impact/investigation guidance. It submits through the same `/api/preflight` and `/api/onboard` paths as the rest of the source contract; there is no parallel onboarding flow.

## Runtime Health integration

During `check_source(...)`, Data Rule findings are appended to the same finding collection used by the existing detectors before Health is derived.

Consequences therefore reuse existing product behavior:

- Warning rules can move a source to Warning when no more-severe finding exists;
- Critical rules can move a source to Critical;
- existing incident transitions, notification-candidate policy, delivery attempts, reviews and baseline controls continue to operate from the resulting Health state;
- Data Rules cannot independently overwrite or bypass the existing Health derivation.

## Evidence and privacy boundary

Rule evaluation does not copy failing row values into findings. Field-based failures expose bounded aggregate evidence such as violation count, row count and violation percentage, plus the declared private rule contract inside the authenticated/local application.

Public GitHub Pages are intentionally more restrictive. For configured Data Rules, static output hides:

- rule IDs and rule names;
- referenced field names;
- allowed-value sets and numeric bounds;
- custom business-impact and investigation text;
- profile, freshness-contract and row-diff metadata for fields referenced by Data Rules;
- ordinary detector evidence that would otherwise reveal a private Data Rule field.

Public output retains generic rule-failure wording and bounded aggregate failure counts. Unrelated public profile evidence is preserved, so the privacy policy is selective rather than a global removal of profile data.

The authenticated/local source detail remains full-fidelity for the declared rule contract, while failing row values remain absent.

## Source connectors

Existing source connectors remain unchanged by Product v0.23:

- CSV;
- XLSX;
- JSON;
- REST API;
- Microsoft 365 SharePoint / OneDrive Excel tables through Microsoft Graph delegated access;
- Google Sheets ranges through the Google Sheets API v4 values endpoint.

Google Sheets continues to use:

`gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]`

Authorization remains environment-backed through `request_header_env`; bearer-token values are not persisted. Static Pages publish only `Google Sheets · <A1 range>` and do not publish the spreadsheet ID, internal `gsheets://` location or authorization environment-variable name.

A real Google Workspace credential was not supplied or invoked in this repository work, so live Google Sheets tenant access is **not claimed**. Likewise, previously implemented Microsoft/Teams/Power BI provider paths must not be interpreted as verified real-tenant side effects unless corresponding credentials and external outcomes were actually exercised.

## Existing product foundation

Product v0.23 preserves the previously verified architecture, including:

- deterministic ingestion, profiling and source detectors;
- mandatory source preflight and guarded onboarding;
- healthy-history references, freshness evidence and baseline promotion/review;
- incident lifecycle and notification policy;
- dry-run/live delivery attempt state, idempotency, retry and explicit reconciliation;
- workspace-aware SQLite/namespaced/PostgreSQL persistence;
- Viewer / Operator / Admin authorization;
- bounded key-level row change analysis;
- Power BI Guard trust correlation;
- dependency mapping and deterministic blast radius;
- Microsoft Teams Workflows delivery architecture;
- Delivery Ops reconciliation monitoring;
- Google Sheets and Microsoft 365 Excel connector boundaries;
- read-only GitHub Pages monitoring snapshots.

## Verification

The Product v0.23 functional/UI/privacy checkpoint `ba779642aeaa971ceda38fa1799ea4f2387904a2` passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed test suite;
- **253 passed, 1 warning**;
- live-source smoke #100.

Coverage includes typed rule validation, deterministic evaluation, preflight rejection, runtime Warning/Critical integration, incident/notification reuse, bounded rule evidence, typed onboarding UI, authenticated/private rule evidence, selective static-profile redaction, and preservation of unrelated public profile evidence.

Release-only metadata and documentation changes are gated again on their exact head before merge.

## Next milestone

Product v0.24 is **reliability scorecards + trust badge**: summarize deterministic recent reliability in an executive-facing form without introducing an opaque Health classifier.

Product v0.25 remains **preconfigured source packs** so common analyst workflows can start with useful keys, freshness contracts and Data Rules instead of low-level configuration from scratch.

AI investigation remains downstream of deterministic findings and must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
