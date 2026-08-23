# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.25 status

Product v0.25 adds **role-mapped Source Packs** that reduce onboarding configuration work without introducing a second source model or hiding business assumptions.

The first pack catalog contains:

- **FP&A Forecast**;
- **Sales Pipeline**;
- **Claims Register**;
- **Operations Orders**;
- **Finance Close**;
- **Customer Export**.

A pack describes semantic roles such as `Opportunity ID`, `Last updated date`, `Pipeline stage`, or `Amount`. The analyst maps those roles to the actual column names in the source. AnalystWatch then materializes the mapping into the existing typed `MonitoringConfig`.

There are no canned customer field names and no automatic schema guessing in the pack contract.

## Transparent pack materialization

A Source Pack can populate existing monitoring primitives only:

- monitoring cadence;
- expected refresh cadence;
- freshness date field;
- unique keys;
- numeric fields;
- bounded row-comparison fields;
- deterministic Data Rules.

The initial release deliberately generates only conservative rule types:

- `not_null` for explicitly mapped required business fields;
- `row_count_range` with a minimum of one row for workflows that should not silently become empty.

Packs do **not** invent allowed-value enumerations, numeric bounds, detector thresholds, SQL expressions, or AI-generated rules.

Optional roles remain optional. If an optional row-comparison role is omitted, the pack does not silently fall back to comparing every source column; row comparison remains bounded to mapped identity/context fields.

## Catalog and preview API

Two non-persistent endpoints support the onboarding experience:

- `GET /api/source-packs` — returns the typed pack catalog;
- `POST /api/source-packs/materialize` — validates role mappings and returns the generated `MonitoringConfig` preview.

Materialization does not create a source, establish a baseline, run monitoring, or persist a pack selection.

The generated source definition must still pass the existing `POST /api/preflight` acceptance boundary and is only persisted through the existing guarded onboarding path.

## Onboarding flow

The existing Add Source page now supports an optional Source Pack flow:

1. choose a workflow preset;
2. map the pack's semantic roles to real source columns;
3. **Preview generated contract**;
4. review cadence, freshness, keys, numeric fields, row-comparison fields and generated rules;
5. **Apply pack contract**;
6. optionally edit the generated cadence, fields, row-comparison fields and Data Rules;
7. run the normal source preflight;
8. add the monitored source only after preflight passes.

Selecting a pack is never sufficient by itself. The UI requires explicit preview and apply before preflight, and applying a pack does not save or onboard the source.

The pack ID and role mapping are not stored as a parallel persistence model. Only the resulting ordinary source configuration is persisted when onboarding succeeds.

Any configuration edit after a successful preflight invalidates that stale preflight evidence and requires preflight to run again before onboarding can be accepted.

## Reliability scorecards retained

Product v0.25 preserves Product v0.24 reliability scorecards and trust badges.

Current Health remains authoritative:

- no eligible observation → `Not monitored`;
- `Healthy` → `Trusted`;
- `Warning` → `Attention`;
- `Critical` → `Critical`.

Seven-day and 30-day scorecards continue to expose explainable check/success/Health ratios, incident openings and recoveries, stale occurrences, Data Rule failure occurrences, and MTTR when the true incident start is known. There is no opaque composite reliability score.

## Deterministic Data Rules retained

The four existing Data Rule kinds remain unchanged:

- `not_null`;
- `allowed_values`;
- `numeric_range`;
- `row_count_range`.

Data Rules still enter the ordinary `Finding` pipeline before the single existing `health_from_findings(...)` boundary. Source Packs merely generate some of those existing typed rules; they do not have their own Health or incident state machine.

## Source connectors

Existing connectors remain unchanged by Product v0.25:

- CSV;
- XLSX;
- JSON;
- REST API;
- Microsoft 365 SharePoint / OneDrive Excel tables through Microsoft Graph delegated access;
- Google Sheets ranges through Google Sheets API v4.

Credentials remain environment-backed where configured. No new live-tenant or provider-side-effect claim is implied by Source Packs.

## Existing product foundation

Product v0.25 preserves the previously verified architecture, including deterministic ingestion/profiling/detectors, mandatory preflight, Healthy-history references, guarded baselines, incident lifecycle, notification policy, delivery attempt safety/reconciliation, workspace-aware persistence, Viewer/Operator/Admin authorization, bounded key-level row changes, Power BI Guard, dependency/blast-radius analysis, Teams Workflows delivery, Delivery Ops, reliability scorecards, and read-only GitHub Pages snapshots.

## Verification

The Product v0.25 functional/API/UI checkpoint `a3f3703f6bdd29191329e497fef60234474888c0` passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed test suite;
- **303 passed, 1 warning**.

Earlier isolated checkpoints passed **294 tests** for the pure pack materializer, **299 tests** after catalog/materialization API + normal-preflight integration, and **302 tests** before the final editable row-comparison / stale-preflight safety refinement.

Coverage includes pack-model validation, six-pack catalog behavior, role mapping, optional-role handling, duplicate/invalid mapping rejection, schedule overrides, generated key/freshness/numeric/row-diff/rule contracts, bounded row-diff fallback, non-persistent APIs, successful and failing normal preflight paths, explicit onboarding preview/apply behavior, editable row-comparison fields, and stale-preflight invalidation after configuration changes.

Release head `f3df908b3fae452d7bd4355d325bd5a82c2e2def` then passed the final release gate with **303 passed, 1 warning**, Ruff/compile/PostgreSQL 16 green, and package/FastAPI/module versions aligned at `0.25.0`.

Live-source smoke was not triggered for Product v0.25 and is not claimed; the release does not change source-ingestion workflow paths.

## What comes next

Product v0.25 completes the immediate feature-focused sequence. The next priority is **self-service connection and real pilot validation**, not connector accumulation:

1. Microsoft connection UX: connect account → choose workbook/table → credential health/reconnect/revoke;
2. Google connection UX: connect account → choose spreadsheet/sheet/range → credential health/reconnect/revoke;
3. authenticated hosted pilot on managed PostgreSQL with real Microsoft, Google, Power BI and notification destinations;
4. end-to-end failure drills from source → finding/rule → Health → incident → blast radius → notification → reconciliation;
5. a five-minute first-value onboarding path with test/simulation tools.

AI investigation can follow as an explanation layer over deterministic evidence, but it must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
