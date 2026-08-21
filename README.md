# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.11 status

Core v0.11 keeps the verified deterministic monitoring, review, incident, delivery-attempt and SQLite integrity behavior from earlier milestones and proves the runtime/storage boundary introduced in v0.10.

New in v0.11:

- independent process-local `MemoryStore` implementing the `MonitoringStore` contract without inheriting or wrapping SQLite
- shared service-level conformance coverage across SQLite `Storage` and `MemoryStore`
- CLI monitoring commands bound to a selected workspace via `--workspace-id`
- FastAPI bound to one workspace, defaulting to `local`
- cross-workspace FastAPI source writes rejected before preflight/persistence
- Pages rendered through the workspace-bound monitoring store
- SQLite verify/backup/restore kept as raw implementation-specific maintenance operations
- scheduler typed against the structural `MonitoringStore` protocol

**Core v0.11 still has no real outbound notification provider.** The only delivery adapter remains deterministic local `dry-run` and performs no external I/O.

## Runtime workspace binding

The default workspace remains `local`, so existing source definitions and hosted jobs continue to operate without configuration changes.

```bash
analystwatch --workspace-id local list
analystwatch --workspace-id team-a check market-data
analystwatch --workspace-id team-a build-pages --output site
```

FastAPI uses `ANALYSTWATCH_WORKSPACE_ID` or `local` when unset. `create_app(..., workspace_id="team-a")` can also bind explicitly for tests/embedding.

`app.state.storage` remains the historical raw SQLite maintenance/test handle for compatibility. HTTP behavior and service operations use `app.state.workspace_storage`, which enforces the workspace boundary.

## Store conformance

`MonitoringStore` is now exercised through two unrelated implementations:

- `Storage` — durable SQLite implementation used by the current hosted runtime
- `MemoryStore` — independent process-local implementation used to prove service semantics are not SQLite-specific

The same service-level scenarios run against both stores: baseline/history, incident/candidate creation, idempotent attempts, retry timing, Prepared reconciliation, review state, baseline promotion and Pages output.

This is a contract proof, not a production-database migration. `MemoryStore` is intentionally non-durable.

## Persistence and workspace limits

The current SQLite schema still uses globally unique `source_id` values. `WorkspaceStore` prevents cross-workspace access but two workspaces cannot yet use the same source ID in one SQLite database. Composite `(workspace_id, source_id)` persistence remains a separate migration.

SQLite maintenance remains local and explicit:

```bash
analystwatch --db instance/analystwatch.db verify-state
analystwatch --db instance/analystwatch.db backup-state backups/analystwatch.db
analystwatch restore-state backups/analystwatch.db restored/analystwatch.db
```

## Verification

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.11 functional checkpoint passed Ruff, compile and **113 tests**. The live-source PR workflow did not run because its explicit path filter is limited to ingestion/model/profile/service changes; v0.11 changes runtime/store files instead. Hosted compatibility is therefore verified after merge by the normal `monitor-state` pipeline.

## Current limitations

- SQLite source IDs remain globally unique across workspaces
- there is no authenticated remote user/session authorization layer
- `MemoryStore` is test/runtime-only and not durable
- `monitor-state` branch persistence remains test-only, not production storage
- snapshots are local SQLite files, not managed backups
- no real notification provider exists

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
