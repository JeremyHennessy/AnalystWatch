# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, unexpected row loss, null explosions, numerical scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.10 status

Core v0.10 remains a Python modular monolith. It keeps all verified v0.9 monitoring, review, incident, delivery-attempt and persistence-integrity behavior, and adds the first explicit storage/workspace boundary without changing the hosted SQLite schema.

It supports:

- deterministic reliability monitoring across CSV/XLSX/JSON/HTTP JSON sources
- explicit baseline + recent Healthy-history context
- safe source onboarding/editing and environment-backed API headers
- Acknowledged / Reviewed workflow state separate from technical Health
- derived Opened / Escalated / Recovered incidents
- opt-in notification-transition policy
- atomic SQLite dry-run attempt claims with idempotency/retry/reconciliation semantics
- stable SQLite storage identity and verified snapshot/restore tooling
- persisted delivery claim owner and reconciliation reviewer identity
- structural `MonitoringStore` persistence protocol
- backward-compatible source ownership via `workspace_id`, defaulting to `local`
- `WorkspaceStore`, which hides foreign-workspace operational records and blocks foreign writes
- `create_workspace_service(...)` for explicitly workspace-bound `MonitorService` instances

**Core v0.10 still has no real outbound notification provider.** The only delivery adapter remains local `dry-run`, with no external I/O or network request.

## Workspace guardrail

Every `SourceDefinition` now has a workspace owner:

```json
{
  "id": "market-data",
  "workspace_id": "local"
}
```

The field defaults to `local`, so existing persisted source JSON from prior releases remains valid without rewriting stored records.

A workspace-bound service can be created explicitly:

```python
from analystwatch.storage import Storage
from analystwatch.workspace import create_workspace_service

service = create_workspace_service(
    Storage("instance/analystwatch.db"),
    workspace_id="team-a",
)
```

The bound store:

- lists/returns only sources owned by the bound workspace;
- blocks source writes for a different workspace;
- hides foreign observations, baselines, reviews and incident inputs;
- hides foreign notification candidates and delivery attempts;
- blocks foreign candidate claims, attempt updates/reconciliation and baseline promotion.

This is an **ownership guardrail**, not multi-tenant persistence. The current SQLite schema still uses globally unique source IDs, so two workspaces cannot yet store the same source ID in one database.

## Storage protocol

`MonitoringStore` defines the persistence surface required by monitoring/service/read operations. The current SQLite `Storage` implementation and `WorkspaceStore` both satisfy that structural protocol.

Core service logic is unchanged in v0.10; the workspace boundary is opt-in through `WorkspaceStore` / `create_workspace_service(...)`. CLI/FastAPI runtime selection, authentication and composite workspace/source keys are intentionally deferred until the guard layer is proven.

## Persistence integrity

All v0.9 persistence protections remain:

```bash
analystwatch --db instance/analystwatch.db verify-state
analystwatch --db instance/analystwatch.db backup-state backups/analystwatch.db
analystwatch restore-state backups/analystwatch.db restored/analystwatch.db
```

Verification is read-only, snapshots use SQLite's backup API, and restore remains create-only into a new destination. Existing targets are never overwritten.

## Delivery safety

Existing rules remain unchanged:

- monitoring never creates delivery attempts automatically;
- only Eligible candidates can be attempted;
- claim decisions use SQLite `BEGIN IMMEDIATE`;
- same-key replay is idempotent;
- different keys cannot both claim Prepared work;
- optional retry delay is independent from monitoring cadence;
- Prepared attempts require explicit reconciliation;
- no generic send route or real provider exists.

## Verification

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.10 functional checkpoint passed Ruff, compile, **92 tests**, and live-source smoke. Eight new regressions cover default-local compatibility, protocol conformance, workspace validation, source isolation, observation/baseline isolation, global source-ID collision behavior, and incident/candidate/dry-run attempt isolation.

## Current limitations

- workspace binding is opt-in and is not yet wired into the existing CLI/FastAPI runtime
- current SQLite source IDs remain globally unique across workspaces
- there is no authentication or remote authorization layer yet
- `monitor-state` branch persistence is still test-only, not production storage
- snapshots are local SQLite files, not managed backups
- no real notification provider exists
- more real incident/candidate history is required before introducing external side effects

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
