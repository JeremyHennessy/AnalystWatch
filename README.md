# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.26 status

Product v0.26 adds **self-service Microsoft 365 and Google Sheets discovery to the existing Add Source workflow**.

The goal is not to create a second connector system or pretend OAuth is complete. The release reduces manual provider-ID lookup while preserving the connector contracts already proven in v0.17 and v0.22:

- Microsoft 365 Excel still resolves to an ordinary `m365://<drive>/<item>?table=<table>` location;
- Google Sheets still resolves to an ordinary `gsheets://<spreadsheet>?range=<A1-range>&header_row=<n>` location;
- the resulting source still passes through normal preflight and guarded onboarding;
- credentials remain environment-backed and bearer-token values are never persisted in a source definition.

## Microsoft connection browser

When **Microsoft 365 Excel** is selected on Add Source, AnalystWatch can now:

1. test the standard server-side Microsoft credential;
2. browse the current user's available drives;
3. search a selected drive for `.xlsx` workbooks;
4. choose a workbook;
5. load its Excel tables;
6. populate the existing Drive ID, workbook item ID, and table fields.

The ordinary manual connector fields remain available and editable. Browse/select is an optional setup aid, not a replacement source model.

## Google connection browser

When **Google Sheets** is selected, AnalystWatch can now:

1. test the standard server-side Google credential;
2. browse available Google spreadsheets through Drive API metadata;
3. choose a spreadsheet;
4. load its GRID sheets/tabs through Sheets API metadata;
5. populate the existing Spreadsheet ID field;
6. suggest an explicit A1 range when the returned grid dimensions are safely bounded.

Automatic range suggestion is intentionally conservative. AnalystWatch fills the grid only when dimensions are known and no larger than **5,000 rows × 100 columns**. Larger or unknown grids require the analyst to enter an explicit A1 range before preflight, preventing a convenient browser helper from silently truncating the monitored dataset.

## Credential and security boundary

Provider discovery is deliberately non-persistent.

The dynamic app uses fixed server credential references only:

- `ANALYSTWATCH_MICROSOFT_AUTHORIZATION`;
- `ANALYSTWATCH_GOOGLE_AUTHORIZATION`.

Callers cannot submit arbitrary environment-variable names to discovery endpoints. Public connection-check responses do not expose those names, bearer-token values, or provider response bodies.

Connection discovery POST routes require **Operator** access under signed-bearer authorization.

Microsoft pagination follows only validated `https://graph.microsoft.com/v1.0/...` next links and both Microsoft/Google discovery paths have bounded pagination safety limits.

A local readiness model can distinguish invalid connector locations, missing credential references, missing runtime credential values, and locally `ready_to_test` configuration. `ready_to_test` means only that AnalystWatch has enough local configuration to attempt a provider request; it does not claim that the credential is valid or that a real tenant/resource can be reached.

An early provisional readiness API that accepted arbitrary source payloads was removed before release because it could have exposed environment-variable existence as a side channel. External browse/test APIs are fixed-reference only.

## Existing onboarding contract remains authoritative

Product v0.26 does not bypass Product v0.25 Source Packs or source preflight.

The Add Source page still supports:

- six role-mapped workflow Source Packs;
- explicit generated-contract preview and apply;
- editable cadence, freshness, numeric, key and row-comparison fields;
- deterministic Data Rules;
- stale-preflight invalidation after any configuration change;
- manual connector entry;
- `Run preflight` before `Add monitored source`.

Provider-browser selections dispatch the same form change events as manual edits, so previously successful preflight evidence is invalidated when the selected workbook, table, spreadsheet, sheet, or range changes.

## Source Packs retained

The v0.25 catalog remains unchanged:

- FP&A Forecast;
- Sales Pipeline;
- Claims Register;
- Operations Orders;
- Finance Close;
- Customer Export.

Packs still materialize the existing `MonitoringConfig` only. There is no pack-specific persistence model and no schema guessing or AI role mapping.

## Reliability and Health retained

Product v0.26 does **not** change source ingestion semantics, detector thresholds, Data Rule evaluation, or Healthy / Warning / Critical classification.

Current Health remains authoritative. Product v0.24 trust badges and explainable 7-day / 30-day scorecards remain downstream of the existing observation evidence; connection discovery cannot upgrade or downgrade Health.

## Dynamic app vs GitHub Pages

Connection browsing is available only in the authenticated/local **dynamic FastAPI app**, where provider requests can be made securely.

GitHub Pages remains a **read-only monitoring snapshot**. Product v0.26 does not place credentials, provider discovery, or dynamic connection controls into public/static Pages output.

## Monitoring data status

Product v0.25 merged to `main` at `fdab78d706b6db75e88cba3d142a15372ca5908d`. The hosted `monitor-state` branch advanced after that merge to `db00ee1ea914c8bca5071f0af4fd656792182844`, confirming post-merge monitoring-state persistence.

Product v0.26 does not change monitoring source data or ingestion behavior, so no monitoring-database rewrite is required for this release.

## Verification

Verified Product v0.26 checkpoints:

- discovery foundation `79722100a930f1928a77f20cb709d9095a6be04b`: **316 passed, 1 warning**;
- consolidated readiness/discovery API `4d0b369ffa14976e3d4cdcfbb21229a179ca4895`: **327 passed, 1 warning**;
- Add Source browser + security-corrected UI `6f18044d33f25be59b04d27408066daffe35c8d4`: **330 passed, 1 warning**.

Each checkpoint passed Ruff, compile/import checks, and the PostgreSQL 16-backed suite on its exact head.

No real Microsoft or Google tenant credential was supplied for this repository work, so live tenant discovery is **not claimed**. The live-source smoke workflow is also not claimed unless it actually runs on the final release head.

Release-only version/documentation changes are gated again on their exact head before merge.

## What comes next

After v0.26, the next priority is to replace the current operator-provisioned environment-token assumption with a real credential lifecycle and hosted pilot:

1. OAuth authorization-code connect/reconnect/revoke flow with secure token storage;
2. authenticated managed-PostgreSQL pilot deployment;
3. real Microsoft and Google tenant validation;
4. real Power BI + email/Teams failure drills end to end;
5. five-minute first-value onboarding and safe test/simulation controls;
6. customer/pilot validation before broad connector accumulation.

AI investigation remains an explanation layer over deterministic evidence and must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
