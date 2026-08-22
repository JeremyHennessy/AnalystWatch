# AnalystWatch

**Reliability monitoring for analyst-owned data and reporting workflows.**

AnalystWatch monitors CSV, Excel, JSON, REST API and Microsoft 365 Excel inputs for silent reliability failures, then carries that trust signal into downstream reporting workflows.

The product question remains simple: **can I trust the data feeding this analysis or report today?**

## Product v0.19 status

Product v0.19 adds **Power BI Guard** as the first DashboardGuard capability.

Power BI Guard correlates Power BI semantic-model refresh evidence with current AnalystWatch upstream source health. A technically successful Power BI refresh is therefore not treated as proof that the dashboard contains trustworthy data.

The deterministic correlation distinguishes cases such as:

- source Healthy + refresh Completed → Guard can be Healthy;
- source Critical + refresh Completed → Guard is Critical because the model may have refreshed successfully from untrustworthy data;
- refresh Failed / Cancelled / Disabled → Guard is Critical;
- refresh still in progress or evidence unavailable → trust remains unconfirmed rather than being silently assumed Healthy;
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

The first implementation collects, where permitted:

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

## DashboardGuard UI

The authenticated/local FastAPI application now exposes:

- `/power-bi` — Power BI Guard overview;
- `/power-bi/{guard_id}` — analyst-facing Guard detail;
- Guard read/config/check API routes.

The detail page answers:

1. Can this dashboard be trusted?
2. What did the latest Power BI refresh report?
3. Which AnalystWatch sources feed it and what is their current health?
4. Which reports use the semantic model?
5. What datasource types and refresh history were observed?
6. What supporting metadata could not be read?

Viewer can read Guard state, Operator can run a Guard check, and Admin is required to create/update Guard configuration.

The existing public GitHub Pages deployment does **not** fabricate Power BI status or expose a broken DashboardGuard link when no real hosted Guard state exists.

## Persistence

Power BI Guard definitions and snapshots are stored separately from source-monitoring observations:

- local/legacy/namespaced application modes use a workspace-scoped companion SQLite Guard database;
- PostgreSQL mode stores workspace-scoped Guard definitions and snapshots in the AnalystWatch PostgreSQL schema.

The Guard store never persists the bearer-token value.

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
- diverse hosted demo sources across CSV, JSON, XLSX and public APIs.

## Verification

The frozen Product v0.19 functional checkpoint passed:

- Ruff;
- compile/import checks;
- **196 deterministic tests** against PostgreSQL 16 CI;
- Power BI trust-correlation cases;
- secret-safe required/optional REST evidence behavior;
- workspace-scoped SQLite/PostgreSQL Guard persistence;
- orchestration from current AnalystWatch source health;
- Viewer / Operator / Admin route-boundary tests;
- analyst-facing Guard overview/detail rendering.

A real Microsoft tenant credential has **not** been supplied or verified in this repository session, so live Power BI tenant access is not claimed.

## Next milestone

Product v0.20 is **Microsoft Teams + lightweight dependency graph / blast radius**. It should reuse the established delivery architecture for Teams and model analyst-facing dependencies such as source → workbook → semantic model → report without attempting enterprise SQL-column lineage.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
