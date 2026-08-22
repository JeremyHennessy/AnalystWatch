# AnalystWatch

**Reliability monitoring for analyst-owned data and reporting workflows.**

AnalystWatch monitors CSV, Excel, JSON, REST API and Microsoft 365 Excel inputs for silent reliability failures, carries that trust signal into downstream reporting workflows, helps analysts understand downstream impact, and keeps ambiguous outbound-delivery outcomes visible until an operator can resolve them from evidence.

The product question is: **can I trust the data feeding this analysis or report today, what is affected if I cannot, and are any delivery outcomes still operationally unresolved?**

## Product v0.21 status

Product v0.21 adds **operational reconciliation monitoring** on top of the verified Product v0.20 Teams and dependency-graph baseline.

It does not introduce a new notification state machine. It makes the existing safety model operationally visible:

- `Prepared` remains neither success nor failure;
- retry remains blocked while the outcome is ambiguous;
- an operator must use durable external evidence to reconcile the attempt to `Succeeded` or `Failed`;
- reconciliation does not automatically create a retry;
- the authenticated operator identity is persisted as the reconciliation reviewer when signed-bearer authentication is enabled.

The verified v0.21 functional checkpoint passed **225 tests** with Ruff, compile/import checks and PostgreSQL 16 CI green.

## Reconciliation Monitor

The authenticated/local application exposes a dedicated Delivery Ops surface:

- `GET /reconciliation` — analyst/operator reconciliation monitor;
- `GET /api/delivery-reconciliation` — bounded reconciliation queue API;
- `POST /reconciliation/{attempt_id}/resolve` — evidence-backed UI reconciliation action;
- the existing `POST /api/delivery-attempts/{attempt_id}/reconcile` API remains supported and now records the authenticated reviewer when available.

Read access is Viewer-level. Reconciliation actions are Operator-level. Unclassified mutations continue to fail closed under the existing Admin boundary.

### Queue semantics

The reconciliation queue is derived from existing delivery attempts rather than persisted as a second operational state store.

Defaults:

- stale threshold: **30 minutes**;
- bounded delivery-history scan: **5,000 attempts**;
- returned/displayed queue items: **100 attempts**;
- ordering: oldest unresolved `Prepared` attempts first.

Each queue item contains bounded operational context only:

- attempt ID;
- candidate ID;
- source ID and source name;
- delivery adapter and mode;
- creation time and unresolved age;
- stale/not-stale state;
- candidate transition and current Health when available.

The queue does **not** expose:

- idempotency keys;
- delivery claim owner;
- raw provider result/error evidence;
- reconciliation notes;
- provider secrets.

`scan_limit_reached` and `item_limit_reached` are reported separately. If the scan cap is reached, AnalystWatch explicitly does not claim the queue is exhaustive. If the output limit is reached, the UI states how many of the scanned Prepared attempts are being shown.

### Evidence-backed resolution

The reconciliation UI requires an evidence note and one explicit outcome:

- **Confirm succeeded** — only when external evidence shows the provider accepted/completed the delivery;
- **Confirm failed** — only when external evidence shows the delivery did not complete.

The form accepts bounded URL-encoded input only and rejects missing/ambiguous fields. The existing `MonitorService.reconcile_delivery_attempt(...)` remains the authority for the state transition.

Reconciliation to `Failed` does not itself retry. Existing retry policy determines when a later delivery attempt may be claimed.

## Product v0.20 foundation

Product v0.20 added two connected capabilities on top of the verified Product v0.19 Power BI Guard baseline:

1. **Microsoft Teams Workflows delivery** using the existing notification-candidate and delivery-attempt state machine.
2. **Lightweight dependency mapping and blast radius** across Source, Workbook, Semantic Model, Report and Custom assets.

The release deliberately did not attempt enterprise SQL-column lineage, replace existing source Health logic, or introduce a second notification state machine.

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

Product v0.20 introduced workspace-scoped dependency relationships between:

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

When a monitored source has recorded downstream relationships, its existing source detail page shows an additive **Downstream impact** panel with the current blast-radius count and asset-kind breakdown. Existing detector output, incident state, source Health and approved source-detail structure remain unchanged.

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

The authenticated/local FastAPI application exposes four connected analyst surfaces:

- SourceGuard — monitored source health, incidents, history and downstream impact;
- Power BI Guard — semantic-model trust and Power BI evidence;
- Dependency Map — recorded relationships and blast radius;
- Delivery Ops / Reconciliation Monitor — unresolved Prepared attempts and evidence-backed reconciliation.

Dynamic application navigation connects these surfaces using the existing UI structure. The public GitHub Pages deployment retains its static boundary and does not fabricate dynamic Teams, Power BI, dependency or reconciliation state.

## Persistence

Product v0.21 adds no reconciliation-queue schema. The queue is derived from existing workspace-scoped delivery-attempt records through `MonitoringStore`.

Power BI Guard and dependency state remain stored separately from source-monitoring observations:

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
- dry-run, live-email and Teams delivery architecture;
- authenticated workspace authorization;
- SQLite, namespaced SQLite and PostgreSQL persistence;
- row-level / key-level change analysis with bounded retention;
- analyst-facing SourceGuard UI;
- Power BI Guard trust correlation and evidence collection;
- dependency mapping and blast radius;
- diverse hosted demo sources across CSV, JSON, XLSX and public APIs.

## Verification

The Product v0.21 functional checkpoint passed on GitHub Actions with PostgreSQL 16:

- Ruff;
- compile/import checks;
- **225 deterministic tests**;
- Prepared-only reconciliation queue derivation and stale-age classification;
- oldest-first ordering;
- bounded scan and separate output-limit evidence;
- secret/claim/result redaction from queue output;
- reconciliation removal from the unresolved queue without automatic retry creation;
- reconciliation page/API rendering;
- required evidence-note and content-type validation;
- Viewer read / Operator reconciliation route boundaries;
- authenticated reviewer attribution for both UI and existing API reconciliation paths;
- all existing Teams, dependency, Power BI and source-monitoring regression coverage.

Product v0.20's verified checkpoint was **212 tests**.

A real Microsoft Teams Workflows webhook has **not** been supplied or invoked in this repository session, so live Teams side-effect delivery is not claimed.

A real Microsoft Power BI tenant credential has also **not** been supplied or verified in this repository session, so live Power BI tenant access is not claimed.

## Next milestone

Product v0.22 is planned as a **Google Sheets connector**, reusing the existing source preflight/onboarding and monitoring contracts rather than creating a parallel ingestion system.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
