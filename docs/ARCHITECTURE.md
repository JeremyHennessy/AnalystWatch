# AnalystWatch Core v0.11 Architecture

## Decision

Core v0.11 proves that the workspace/storage boundary introduced in v0.10 is usable by the real runtime and is not coupled to SQLite.

The deterministic monitoring engine remains unchanged. Detector Health, review state, incident transitions, notification policy and delivery-attempt semantics are not rewritten by this milestone.

## Runtime workspace boundary

CLI monitoring commands and FastAPI are now constructed through `WorkspaceStore` with a safe default workspace of `local`.

- CLI: global `--workspace-id` (or `ANALYSTWATCH_WORKSPACE_ID`)
- FastAPI: `create_app(..., workspace_id=...)` or `ANALYSTWATCH_WORKSPACE_ID`
- Pages: rendered from the already workspace-bound store supplied by CLI/service code

Cross-workspace FastAPI source writes are rejected before preflight and persistence. Read surfaces expose only sources/operational records visible to the bound workspace.

SQLite maintenance commands (`verify-state`, `backup-state`, `restore-state`) remain intentionally raw implementation-specific operations rather than workspace-scoped monitoring operations.

For backward compatibility, `app.state.storage` remains the raw SQLite handle used by existing maintenance/test seams. `app.state.workspace_storage` and `app.state.service` are the guarded runtime path.

## MonitoringStore conformance

`MonitoringStore` is now exercised through two independent implementations:

### SQLite Storage

The existing durable local/test implementation with atomic attempt claiming, integrity metadata and snapshot/restore tooling.

### MemoryStore

A separate process-local implementation built with in-memory dictionaries and an `RLock`. It does not inherit from or wrap SQLite.

The shared conformance suite covers:

- source persistence and lookup
- baseline establishment and observation history
- incident derivation and notification-candidate persistence
- idempotent delivery attempt replay
- failed-attempt retry timing
- Prepared attempt reconciliation and reviewer attribution
- operational review state
- guarded baseline promotion
- Pages rendering

Passing the same service behaviors through two unrelated adapters is the evidence that the store abstraction is functional rather than a type-only façade.

## Scheduler boundary

The scheduler consumes the `MonitoringStore` protocol rather than the concrete SQLite class. Runtime behavior is unchanged.

## Important persistence limitation

Workspace isolation is still implemented as a guard around the current schema. SQLite continues to key sources globally by `source_id`; therefore two workspaces cannot store the same source ID in one database.

A future persistent adapter must use composite workspace-aware identity (for example `(workspace_id, source_id)`) across sources and downstream operational records. That migration is intentionally separate from v0.11.

## Verification

The verified v0.11 functional checkpoint passed Ruff, compile and **113 deterministic tests**. The PR live-source workflow is path-filtered to ingestion/model/profile/service changes and therefore does not run for this runtime/store-only diff. Post-merge hosted `monitor-state` persistence is the deployment compatibility gate.

## Limitations

- no authenticated user/session authorization
- no composite workspace/source persistence yet
- `MemoryStore` is non-durable and test/runtime-only
- current SQLite/branch-backed state remains a test deployment design
- no real outbound notification provider exists
