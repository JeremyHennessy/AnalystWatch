# AnalystWatch

**Reliability monitoring for analyst-owned data and reporting workflows.**

AnalystWatch monitors CSV, Excel, JSON, REST API and Microsoft 365 Excel inputs for silent reliability failures, carries that trust signal into downstream reporting workflows, and helps analysts understand what may be affected when an upstream source changes.

The product question is: **can I trust the data feeding this analysis or report today, and what is the downstream impact if I cannot?**

## Product v0.20 status

Product v0.20 adds two connected capabilities on top of the verified Product v0.19 Power BI Guard baseline:

1. **Microsoft Teams Workflows delivery** using the existing notification-candidate and delivery-attempt state machine.
2. **Lightweight dependency mapping and blast radius** across Source, Workbook, Semantic Model, Report and Custom assets.

The release deliberately does not attempt enterprise SQL-column lineage, replace existing source Health logic, or introduce a second notification state machine.

## Microsoft Teams Workflows delivery

AnalystWatch can deliver an already-eligible notification candidate to a Microsoft Teams Workflows / Power Automate webhook as an Adaptive Card.

The integration reuses the existing delivery safety model:

- the candidate must already be eligible under the source notification policy;
- an atomic claim protects a delivery attempt before the external request;
- idempotency keys prevent a same-key replay from issuing a duplicate POST;
- an explicit provider rejection records a Failed attempt;
- an ambiguous transport failure leaves the attempt Prepared for reconciliation rather than assuming success or failure;
- retry and reconciliation behavior continues to use the existing delivery-attempt state machine.

Runtime configuration is environment-backed:

- `ANALYSTWATCH_TEAMS_WORKFLOW_WEBHOOK_URL` — secret Teams Workflows webhook URL;
- `ANALYSTWATCH_PUBLIC_BASE_URL` — public AnalystWatch base URL used in the Adaptive Card.

The application exposes:

- `GET /api/delivery/teams/status` — reports only whether Teams delivery is configured;
- `POST /api/delivery-attempts/teams` — Operator-level delivery action for an eligible candidate and idempotency key.

The webhook URL and raw provider response body are not persisted in the delivery attempt. The status route does not return the webhook URL.

The implementation targets **Teams Workflows / Power Automate**, not the retired Office 365 Connector model.

## Dependency map and blast radius

Product v0.20 introduces workspace-scoped dependency relationships between:

- Source;
- Workbook;
- Semantic Model;
- Report;
- Custom asset.

Relationships can be explicit or discovered. The graph provides deterministic, cycle-safe downstream traversal and counts the assets that may be affected by an upstream change without double-counting shared descendants.

The authenticated/local application exposes:

- `/dependencies` — analyst-facing Dependency Map;
- `GET /api/dependencies/edges`;
- `PUT /api/dependencies/edges/{edge_id}`;
- `DELETE /api/dependencies/edges/{edge_id}`;
- `GET /api/dependencies/assets`;
- `GET /api/dependencies/blast-radius?kind=...&asset_id=...`.

Viewer can read dependency state. Dependency mutations remain Admin-level operations under the fail-closed authorization rules.

When a monitored source has recorded downstream relationships, its existing source detail page now shows an additive **Downstream impact** panel with the current blast-radius count and asset-kind breakdown. Existing detector output, incident state, source Health and approved source-detail structure are otherwise unchanged.

## Power BI dependency discovery

Power BI Guard remains the first DashboardGuard capability from Product v0.19. It correlates Power BI semantic-model refresh evidence with current AnalystWatch upstream source health so that a technically successful refresh is not treated as proof that the dashboard contains trustworthy data.

Product v0.20 additionally uses successful Power BI evidence to discover lightweight dependency relationships:

- configured AnalystWatch source → semantic model;
- semantic model → returned Power BI report.

Discovered Power BI edges are namespaced per Guard. A successful evidence read replaces stale discovered edges only within that Guard's namespace and does not modify explicit relationships. If Power BI evidence is unavailable, AnalystWatch does not erase the last known dependency graph.

Power BI Guard continues to distinguish cases such as:

- source Healthy + refresh Completed → Guard can be Healthy;
- source Critical + refresh Completed → Guard is Critical because the model may have refreshed successfully from untrustworthy data;
- refresh Failed / Cancelled / Disabled → Guard is Critical;
- refresh still in progress or evidence unavailable → trust remains unconfirmed rather than silently assumed Healthy;
- completed refresh with Warning or unobserved upstream sources → Guard is Warning.

Power BI Guard does **not** redefine the Health of the monitored upstream source. It creates a separate deterministic dashboard-trust result from Power BI evidence plus existing AnalystWatch source observations.

## Power BI evidence

A Guard definition identifies:

- the AnalystWatch workspace;
- Power BI workspace ID;
- semantic-model / dataset ID;
- an environment variable containing the delegated bearer token;
- upstream AnalystWatch source IDs;
- refresh-history depth.

The credential itself is not stored in the Guard definition.

The implementation collects, where permitted:

- semantic-model name and refreshability;
- refresh history;
- refresh status;
- refresh start/end time and duration;
- reports linked to the semantic model;
- report web URLs;
- datasource-type counts;
- Power BI workspace name;
- current health of configured AnalystWatch upstream sources.

Semantic-model and refresh-history evidence are required. Workspace/report/datasource metadata are best effort: permission failures become explicit evidence warnings without falsely converting a valid refresh result into a source-data failure.

## Product UI

The authenticated/local FastAPI application exposes three connected analyst surfaces:

- SourceGuard — monitored source health, incidents, history and downstream impact;
- Power BI Guard — semantic-model trust and Power BI evidence;
- Dependency Map — recorded relationships and blast radius.

The dynamic workspace overview and Power BI Guard pages link to the Dependency Map. The public GitHub Pages deployment retains its static boundary and does not fabricate dynamic Teams, Power BI or dependency state.

## Persistence

Power BI Guard and dependency state are stored separately from source-monitoring observations:

- local/legacy/namespaced application modes use workspace-scoped companion SQLite databases;
- PostgreSQL mode stores workspace-scoped Guard and dependency records in the AnalystWatch PostgreSQL schema.

The Teams webhook secret is environment-backed rather than stored as product data. The Power BI Guard store never persists the bearer-token value.

## Existing product foundation

All previously verified capabilities remain intact, including:

- deterministic source ingestion/profiling/detectors;
- CSV / XLSX / JSON / REST API monitoring;
- Microsoft 365 SharePoint / OneDrive Excel-table ingestion;
- source preflight and onboarding;
- historical baselines and reviews;
- incident lifecycle and notification policy;
- dry-run and live-email delivery architecture;
- authenticated workspace authorization;
- SQLite, namespaced SQLite and PostgreSQL persistence;
- row-level / key-level change analysis with bounded retention;
- analyst-facing SourceGuard UI;
- Power BI Guard trust correlation and evidence collection;
- diverse hosted demo sources across CSV, JSON, XLSX and public APIs.

## Verification

The Product v0.20 functional checkpoint passed on GitHub Actions with PostgreSQL 16:

- Ruff;
- compile/import checks;
- **212 deterministic tests**;
- Teams Adaptive Card construction and request behavior;
- Teams same-key idempotency, explicit-rejection and ambiguous-transport behavior;
- secret-safe Teams status/delivery routes and Viewer / Operator / Admin boundaries;
- workspace-scoped SQLite/PostgreSQL dependency persistence;
- deterministic cycle-safe blast radius;
- dependency API and analyst-facing Dependency Map rendering;
- source-detail downstream-impact propagation;
- Power BI → dependency discovery and stale discovered-edge replacement;
- existing Power BI trust-correlation, persistence and authorization coverage.

A real Microsoft Teams Workflows webhook has **not** been supplied or invoked in this repository session, so live Teams side-effect delivery is not claimed.

A real Microsoft Power BI tenant credential has also **not** been supplied or verified in this repository session, so live Power BI tenant access is not claimed.

## Next milestone

Product v0.21 is **operational reconciliation monitoring**: surface stale Prepared delivery attempts, make ambiguous-outcome queues visible to operators, and tighten delivery operations without weakening the existing idempotency/reconciliation safety model.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
