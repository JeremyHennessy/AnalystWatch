# AnalystWatch Product v0.20 Architecture

## Decision

Product v0.20 extends the verified Product v0.19 architecture in two bounded directions:

1. **Microsoft Teams Workflows delivery** reuses the existing notification-candidate and delivery-attempt state machine.
2. **Lightweight dependency mapping** adds a separate workspace-scoped graph for analyst-facing assets and deterministic blast-radius calculation.

Neither capability redefines source Health, detector thresholds, baseline/review behavior, incident semantics or the established delivery-attempt state machine.

```text
Source observation / incident
        ↓
eligible notification candidate
        ↓
existing atomic delivery claim + idempotency
        ↓
TeamsWorkflowAdapter
        ↓
Microsoft Teams Workflow / Power Automate webhook
```

```text
Source / Workbook / Semantic Model / Report / Custom assets
        ↓
explicit or discovered dependency edges
        ↓
cycle-safe downstream traversal
        ↓
blast radius
        ↓
Dependency Map + source downstream-impact context
```

Power BI Guard remains a separate DashboardGuard evidence boundary from v0.19:

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
        +
successful evidence → discovered dependency edges
```

## Microsoft Teams delivery boundary

`teams_delivery.py` contains the provider adapter and Adaptive Card construction. It does not own notification eligibility, delivery idempotency, retry timing or reconciliation state.

`deliver_teams_candidate(...)` delegates those responsibilities to the existing monitoring storage contract:

1. load/validate the eligible notification candidate;
2. atomically claim the delivery attempt using the caller idempotency key;
3. if the claim is a same-key replay of an existing successful/prepared attempt, do not issue another provider POST;
4. post the Adaptive Card through `TeamsWorkflowAdapter` only for a newly claimed attempt;
5. explicit provider rejection → Failed;
6. successful provider acceptance → Succeeded;
7. ambiguous transport exception → leave the attempt Prepared for explicit reconciliation.

This preserves the safety property established before v0.20: AnalystWatch does not infer the outcome of an ambiguous external side effect.

The adapter persists only bounded provider evidence. It does not persist the Teams webhook URL or raw provider response body.

## Teams runtime and web boundary

`teams_web.py` resolves optional runtime configuration:

- `ANALYSTWATCH_TEAMS_WORKFLOW_WEBHOOK_URL`;
- `ANALYSTWATCH_PUBLIC_BASE_URL`.

If no webhook is configured, the application remains usable and the delivery action fails closed with a configuration error. If a webhook is configured, the public base URL is required.

Routes:

- `GET /api/delivery/teams/status` → configuration boolean only;
- `POST /api/delivery-attempts/teams` → existing eligible-candidate delivery flow.

Authorization remains centralized in `web_auth.py`:

- Viewer → Teams status read;
- Operator → Teams delivery action;
- Admin remains required for unclassified configuration mutations.

The implementation targets Microsoft **Teams Workflows / Power Automate** rather than the retired Office 365 Connector model.

## Dependency graph model

`dependencies.py` defines deliberately lightweight analyst-facing graph primitives:

- `AssetKind.SOURCE`;
- `AssetKind.WORKBOOK`;
- `AssetKind.SEMANTIC_MODEL`;
- `AssetKind.REPORT`;
- `AssetKind.CUSTOM`;
- `AssetRef`;
- `DependencyEdge`;
- `BlastRadius`.

A dependency edge records upstream → downstream direction, workspace ownership, relationship text and whether the relationship was explicitly supplied or discovered.

`calculate_blast_radius(...)` performs deterministic cycle-safe downstream traversal. Descendants are deduplicated by asset key, so converging paths do not inflate the impacted-asset count.

This is intentionally not SQL-column lineage or a Fabric/warehouse metadata catalogue.

## Dependency persistence

Dependency persistence is separate from `MonitoringStore` and `PowerBIGuardStore`.

Local/SQLite runtime:

- companion `*.dependencies.db` file;
- workspace-scoped edge identity.

PostgreSQL runtime:

- dependency edges stored in AnalystWatch PostgreSQL;
- workspace-scoped composite identity;
- the same logical edge ID can exist independently in different workspaces.

Keeping the graph separate avoids changing the already-verified source-observation schema.

## Dependency service and discovery replacement

`DependencyService` owns graph reads/writes and blast-radius calculation.

Explicit edges are ordinary persisted relationships.

Discovered edges can be replaced through a namespace-scoped operation. Replacement rules are deliberately conservative:

- replacement edges must be marked discovered;
- every replacement edge must match the requested namespace;
- stale discovered edges are removed only inside that namespace;
- explicit edges are never removed by discovery refresh;
- discovered edges owned by another namespace are not touched.

This gives provider discovery a bounded reconciliation mechanism instead of treating the graph as an unqualified overwrite.

## Power BI → dependency integration

Product v0.19 `PowerBIGuardDefinition`, evidence collection and deterministic trust correlation remain intact.

After a successful available Power BI Guard check, `power_bi_web.py` converts evidence into discovered edges:

- configured AnalystWatch source → semantic model;
- semantic model → returned Power BI report.

Edges are namespaced as `pbi:<guard_id>:`. A later successful check can remove stale relationships within that Guard's namespace.

If the Power BI snapshot is unavailable, the dependency graph is not replaced. This prevents a temporary provider outage or permission problem from erasing the last known relationship evidence.

## Dependency web/API boundary

`dependency_web.py` registers a separate dependency surface:

Read surfaces:

- `GET /dependencies`;
- `GET /api/dependencies/edges`;
- `GET /api/dependencies/assets`;
- `GET /api/dependencies/blast-radius`.

Mutation surfaces:

- `PUT /api/dependencies/edges/{edge_id}`;
- `DELETE /api/dependencies/edges/{edge_id}`.

Cross-workspace edges are rejected before persistence.

Authorization uses the existing fail-closed rules:

- Viewer → reads;
- dependency mutations are Admin-level unless explicitly reclassified later.

## Analyst-facing impact context

The dynamic Dependency Map answers: **what may be affected downstream if this asset changes?**

For each graph root, it shows the total downstream blast radius and recorded relationships. Explicit and discovered evidence remain distinguishable.

The existing source detail page receives an additive `downstream_impact` value from the dependency service. When a monitored source has recorded descendants, the existing sidebar shows:

- total downstream assets;
- asset-kind counts;
- link to the Dependency Map.

No dependency relationship means no impact panel. The graph does not manufacture an impact claim when evidence is absent.

The workspace overview and Power BI Guard dynamic pages link to the Dependency Map using existing navigation styling. No existing layout/CSS architecture was rewritten.

## Preserved Power BI architecture

Power BI Guard still correlates refresh evidence with existing source Health. Important deterministic cases remain:

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

`PowerBIGuardDefinition` continues to store identifiers and an environment-variable name for the bearer token, never the token value itself. Required semantic-model/refresh evidence and best-effort workspace/report/datasource evidence retain the v0.19 error/redaction behavior.

## Public/static boundary

The public GitHub Pages build remains a read-only source-monitoring snapshot.

It does not fabricate:

- Teams delivery configuration or outcomes;
- Power BI tenant evidence;
- dynamic dependency graph state.

Dynamic DashboardGuard/Dependency Map navigation is therefore not injected into the static overview.

## Preserved behavior

Product v0.20 does not change:

- CSV/XLSX/JSON/API/Microsoft Excel ingestion;
- source detector thresholds;
- source Healthy / Warning / Critical classification;
- source baseline promotion or review;
- row-level comparison semantics/retention;
- source incident lifecycle;
- notification candidate policy;
- delivery attempt Prepared/Succeeded/Failed semantics;
- delivery retry/reconciliation safety;
- live-email adapter behavior;
- source scheduler;
- existing public Pages source-state policy.

## Verification

The verified v0.20 functional checkpoint passed **212 tests**, Ruff and compile/import checks against PostgreSQL 16 CI.

Coverage includes:

- Teams Adaptive Card request behavior;
- same-key replay/idempotency;
- explicit rejection and ambiguous transport handling;
- secret-safe web configuration/status;
- Viewer/Operator/Admin route classification;
- SQLite/PostgreSQL dependency workspace isolation;
- cycle-safe blast radius;
- dependency API/UI rendering;
- source-detail downstream-impact propagation;
- Power BI discovery-edge synchronization and stale-edge replacement;
- the existing Power BI trust/persistence/security suite.

No real Teams Workflows webhook was supplied in this repository session. Therefore adapter/API/state-machine behavior is verified, but a real Teams side effect is not claimed.

No real Power BI tenant credential was supplied either, so live Microsoft tenant access remains unverified.

## Next architecture step

Product v0.21 should make ambiguous delivery outcomes operationally visible: surface stale Prepared attempts, provide bounded reconciliation-monitoring views and tighten operator workflows without weakening the existing idempotency/reconciliation model.
