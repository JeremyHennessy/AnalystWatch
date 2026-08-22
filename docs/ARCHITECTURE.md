# AnalystWatch Product v0.19 Architecture

## Decision

Product v0.19 introduces **Power BI Guard** as a separate DashboardGuard evidence boundary that correlates Power BI refresh state with existing AnalystWatch source health.

It does not redefine source Health, detector thresholds, incident semantics or notification-state behavior.

```text
AnalystWatch source observations
        +
Power BI semantic-model refresh evidence
        ↓
deterministic trust correlation
        ↓
Power BI Guard snapshot
        ↓
DashboardGuard overview/detail
```

The primary product risk addressed is false confidence: a Power BI refresh can complete successfully even when its upstream data is stale, incomplete or otherwise Critical.

## Guard definition

`PowerBIGuardDefinition` contains only identifiers and a secret reference:

- AnalystWatch workspace ID;
- Guard ID/name;
- Power BI workspace/group ID;
- semantic-model/dataset ID;
- environment-variable name for the bearer token;
- upstream AnalystWatch source IDs;
- refresh-history limit.

The bearer-token value is resolved at check time and is never written to the Guard definition or snapshot.

## Evidence collection

`read_power_bi_guard(...)` uses the Power BI REST API under `https://api.powerbi.com/v1.0/myorg`.

Required evidence:

- semantic-model metadata;
- refresh history.

Best-effort evidence:

- workspace metadata;
- report relationships;
- datasource metadata.

Required evidence failure returns an explicit unavailable/Warning Guard snapshot. Best-effort permission failures append evidence warnings but do not masquerade as a source-data failure.

Provider error bodies and bearer values are not copied into persisted error evidence.

## Deterministic trust correlation

`correlate_power_bi_trust(...)` is deterministic and auditable.

Important cases:

```text
refresh Completed + upstream all Healthy
→ Healthy

refresh Completed + any upstream Critical
→ Critical
→ explicit false-confidence warning

refresh Completed + any upstream Warning
→ Warning

refresh Completed + upstream not observed
→ Warning

refresh Failed / Cancelled / Disabled
→ Critical

refresh InProgress / NotStarted / unknown
→ Warning

no refresh history
→ Warning
```

The Guard result never mutates the upstream source observation.

## Orchestration

`PowerBIGuardService` owns the integration seam:

1. load the stored Guard definition;
2. resolve the bearer token from its configured environment-variable name;
3. load the latest AnalystWatch observation for each configured upstream source;
4. pass those source Health values to the deterministic Power BI reader/correlator;
5. persist the returned Guard snapshot.

A missing upstream source observation becomes `None` and is handled explicitly by the trust correlation.

## Persistence

`PowerBIGuardStore` is separate from `MonitoringStore`.

Local/SQLite runtime:

- companion `*.powerbi.db` file;
- `(workspace_id, guard_id)` identity;
- immutable time-keyed snapshot history.

PostgreSQL runtime:

- Guard definitions and snapshots live in the existing AnalystWatch PostgreSQL schema;
- workspace-scoped composite identity;
- no token value persisted.

This separation avoids changing verified source-observation schemas merely to add downstream dashboard evidence.

## Web/API boundary

`power_bi_web.py` registers DashboardGuard routes without folding Power BI logic into the existing source controller.

Read surfaces:

- `GET /power-bi`;
- `GET /power-bi/{guard_id}`;
- Guard list/detail APIs.

Mutation surfaces:

- Guard configuration upsert;
- explicit Guard check.

Authorization remains centralized in the existing web authorization layer:

- Viewer → read;
- Operator → check;
- Admin → Guard configuration mutation.

Cross-workspace Guard definitions are rejected before persistence.

## Analyst-facing UI

The dynamic application exposes DashboardGuard from the existing product navigation.

The overview explains why a successful refresh can still be unsafe. The detail page prioritizes:

1. trust result;
2. latest refresh state and duration;
3. upstream AnalystWatch source health;
4. reports potentially affected;
5. recent refresh history;
6. datasource/workspace evidence and permission limitations.

The static GitHub Pages build does not show the dynamic DashboardGuard navigation when no hosted Guard state/tenant credential exists. AnalystWatch does not fabricate Power BI health for the public demo.

## Preserved behavior

Product v0.19 does not change:

- CSV/XLSX/JSON/API/Microsoft Excel ingestion;
- source detector thresholds;
- source Healthy / Warning / Critical classification;
- source baseline promotion or review;
- row-level comparison semantics/retention;
- source incident lifecycle;
- notification candidate policy;
- email/dry-run delivery state machine;
- source scheduler;
- existing public Pages source-state policy.

## Verification

The frozen v0.19 functional checkpoint passed **196 tests**, Ruff and compile checks against PostgreSQL 16 CI.

Coverage includes deterministic Power BI trust cases, REST evidence handling, secret redaction, SQLite/PostgreSQL Guard persistence, orchestration with current AnalystWatch source health, web rendering, workspace rejection and Viewer/Operator/Admin route classification.

No real Microsoft tenant credential was available in this repository session. Therefore the implementation/API contract is verified, but live tenant access is not claimed.

## Next architecture step

Product v0.20 should add Microsoft Teams through the existing delivery-attempt architecture and introduce lightweight dependency edges/blast-radius calculation across analyst-facing assets. It should not attempt enterprise SQL-column lineage.
