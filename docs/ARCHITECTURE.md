# AnalystWatch Product v0.25 Architecture

## Decision

Product v0.25 adds Source Packs as **thin, typed configuration generators over the existing `MonitoringConfig`**.

The architectural rule is: **a pack reduces setup effort; it does not create a second source model, persistence model, Health classifier, or onboarding boundary.**

```text
SourcePack catalog
        ↓
semantic role mapping supplied by analyst
        ↓
materialize_source_pack(...)
        ↓
ordinary MonitoringConfig
        ↓
ordinary SourceDefinition
        ↓
existing preflight
        ↓
existing guarded onboarding
        ↓
existing monitoring / Health / incidents / delivery
```

## Pack model

A `SourcePack` contains:

- stable pack ID and analyst-facing name/description;
- typed semantic roles;
- required/optional role status;
- default monitoring/refresh cadence;
- role references for freshness, keys, numeric fields and row comparison;
- conservative typed Data Rule templates.

The initial catalog is:

- FP&A Forecast;
- Sales Pipeline;
- Claims Register;
- Operations Orders;
- Finance Close;
- Customer Export.

Roles are business concepts, not customer-specific field names. For example, the Sales Pipeline pack asks the analyst to map `Opportunity ID`, `Last updated date`, `Pipeline stage`, and optional `Opportunity amount` to their actual source columns.

## Mapping validation

`materialize_source_pack(...)` fails closed when:

- a required role is missing;
- an unknown role is supplied;
- a mapped field is blank or untrimmed;
- multiple semantic roles are mapped to the same source field;
- an unsupported pack ID is requested;
- a schedule override violates the existing positive cadence constraints.

Optional roles are omitted rather than inferred.

No schema inspection or AI inference is used to guess role mappings.

## Materialization boundary

Pack materialization returns `SourcePackMaterialization`, containing the pack identity, normalized role mapping, and the generated ordinary `MonitoringConfig`.

The generated config uses only existing fields:

- `monitor_interval_minutes`;
- `expected_refresh_minutes`;
- `latest_date_field`;
- `unique_keys`;
- `numeric_fields`;
- `row_diff_fields`;
- `data_rules`.

Existing detector thresholds, request credentials, notification policy, retry behavior, history configuration and other unrelated settings remain the normal `MonitoringConfig` defaults.

## Data Rule boundary

The first Source Pack release generates only conservative rule templates:

- `not_null` for explicit mapped fields that the workflow requires;
- `row_count_range` with minimum one for non-empty workflow extracts.

Source Packs do not generate:

- `allowed_values` enumerations based on guessed business states;
- numeric minimum/maximum thresholds;
- SQL or arbitrary expressions;
- AI-authored rules;
- direct Health decisions.

Generated rules are ordinary Product v0.23 `DataRule` objects and therefore enter the same deterministic finding pipeline and single `health_from_findings(...)` boundary.

## Row-comparison safety

Existing row-diff semantics interpret an empty `row_diff_fields` list as “all columns within safety limits.” That behavior is useful for manual configuration but is too broad as an accidental pack fallback.

Product v0.25 therefore ensures that when a pack's optional comparison-value roles are all omitted, the materialized pack uses mapped unique-key fields as the bounded comparison field list rather than silently expanding to every source column.

When optional comparison roles are mapped, only those explicit mapped fields are added.

This keeps pack-generated snapshots transparent and bounded.

## Non-persistent API boundary

Two dedicated endpoints support catalog discovery and preview:

```text
GET  /api/source-packs
POST /api/source-packs/materialize
```

`GET /api/source-packs` returns the typed pack catalog.

`POST /api/source-packs/materialize` validates a pack ID, role mapping, and optional schedule overrides, then returns the generated `SourcePackMaterialization`.

Neither endpoint creates a source, writes monitoring state, establishes a baseline, or starts monitoring. The materialization POST is a calculation/preview surface only.

The routes use direct `app.add_api_route(...)` registration to preserve the repository's established FastAPI route-regression contract.

## Preflight and onboarding boundary

Source Packs do not add a pack-specific preflight or onboarding endpoint.

After materialization, the caller builds the normal `SourceDefinition` and submits it to the existing `/api/preflight` path. That preflight remains authoritative for:

- connector availability;
- declared fields/keys;
- freshness evidence;
- generated Data Rules;
- all other existing source acceptance checks.

A generated pack rule that fails causes ordinary preflight rejection exactly like a manually configured rule.

Only the existing guarded onboarding path persists an accepted source.

## Analyst-facing onboarding flow

The existing Add Source page contains an optional Source Pack section.

The flow is intentionally explicit:

1. choose a pack;
2. map each semantic role to a real source column;
3. request a non-persistent generated-contract preview;
4. review the generated cadence/freshness/key/numeric/row-diff/Data Rule contract;
5. explicitly apply the pack;
6. optionally edit the resulting visible monitoring controls and Data Rules;
7. run normal preflight;
8. onboard only if preflight passes.

Selecting a pack alone is insufficient. If a pack is selected but not previewed/applied, the browser refuses to run preflight with that pack selection.

Applying a pack only copies the generated ordinary configuration into the current onboarding form. It does not persist anything.

## Persistence

Product v0.25 requires **no database migration**.

Pack definitions are code-level product presets. A pack ID or role mapping is not persisted as a parallel source record.

After successful onboarding, storage contains the normal `SourceDefinition` with its materialized `MonitoringConfig`, exactly as if the analyst had configured those fields manually.

SQLite, namespaced storage and PostgreSQL therefore require no pack-specific tables or migration logic.

## Authorization

Source Packs do not change the existing authorization policy. Catalog discovery is a normal read surface. Materialization and source creation remain subject to the existing web authorization rules, and actual persistence still requires the existing source onboarding mutation boundary.

No pack can bypass workspace isolation or source-creation authorization.

## Preserved v0.24 reliability architecture

Source Packs do not modify reliability scorecards or trust badges.

Current source Health remains authoritative; seven-day and 30-day scorecards remain explanatory derived evidence. Pack-generated rules may affect Health only through the same normal rule → Finding → `health_from_findings(...)` path used by manually authored rules.

## Preserved product architecture

Product v0.25 does not change:

- connector ingestion semantics;
- detector thresholds;
- Healthy / Warning / Critical classification;
- Data Rule evaluator semantics;
- baseline promotion/review;
- Healthy-history reference behavior;
- incident lifecycle;
- notification policy;
- delivery attempt state/idempotency/retry/reconciliation;
- workspace persistence boundaries;
- Viewer / Operator / Admin role model;
- Power BI Guard trust logic;
- dependency graph and blast radius;
- Teams delivery state handling;
- Delivery Ops reconciliation;
- scorecard derivation;
- static Pages privacy boundaries.

## Verification

The functional/API/UI checkpoint `ca91d63e4c857a4faa154c17e29c36aafd78653d` passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed suite;
- **302 passed, 1 warning**.

Earlier isolated checkpoints passed 294 tests for the pure materializer and 299 tests after the catalog/materialization API + normal-preflight integration.

Coverage proves:

- all six packs are present and typed;
- required/optional role behavior;
- fail-closed unknown/blank/duplicate mappings;
- schedule overrides;
- generated freshness/key/numeric/row-diff fields;
- conservative generated Data Rules;
- bounded row-diff fallback when optional roles are omitted;
- catalog/materialization APIs do not persist sources;
- materialized configs still pass through normal successful/failing preflight behavior;
- onboarding exposes role mapping, preview and explicit apply;
- applying a pack reuses the existing contract controls rather than a parallel config model.

Release-only version/documentation changes are gated again on their exact head before merge.

## Next architecture step

Product v0.25 closes the immediate feature-focused sequence.

The next architecture priority is **connection lifecycle + hosted pilot validation**:

1. real Microsoft OAuth/connection selection for workbook/table discovery;
2. real Google connection selection for spreadsheet/sheet/range discovery;
3. reconnect, revoke and credential-health states;
4. managed PostgreSQL authenticated hosted pilot;
5. real provider-side end-to-end failure drills through monitoring, incident, blast radius, notification and reconciliation.

AI investigation can later summarize and prioritize deterministic evidence, but it remains downstream and must never redefine Health.
