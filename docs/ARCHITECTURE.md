# AnalystWatch Core v0.13 Architecture

## Decision

Core v0.13 introduces controlled runtime persistence selection while keeping the verified hosted deployment on the legacy schema-v1 SQLite path by default.

The milestone does not change detector behavior, incident derivation, notification policy, delivery-attempt semantics, legacy schema-v1 storage or namespaced schema-v2 storage. Instead it adds one shared construction boundary that decides which already-proven store may start.

## Runtime storage factory

`src/analystwatch/runtime_storage.py` is the authoritative runtime selection seam.

Supported backends:

- `legacy` — schema version 1;
- `namespaced` — schema version 2.

`legacy` is the default.

The factory returns:

- the selected raw persistence implementation;
- the `MonitoringStore` used by `MonitorService`;
- the normalized backend name.

For legacy mode the domain store is `WorkspaceStore(Storage(...), workspace_id)`. For namespaced mode the already workspace-bound `NamespacedStorage` is used directly.

## Read-only pre-initialization verification

Existing database files are inspected before store construction/initialization.

The sequence is:

1. if the path does not exist, allow the explicitly selected backend to create it later;
2. if the path exists, use the existing read-only SQLite verifier;
3. reject failed integrity checks;
4. require AnalystWatch schema metadata;
5. require schema version 1 for `legacy` or schema version 2 for `namespaced`;
6. only after the check succeeds construct the selected persistence implementation.

This prevents a schema-v1 process from attempting to initialize schema-v2 state, and vice versa. It also prevents an unknown or corrupt existing SQLite file from being opportunistically converted into AnalystWatch state.

## CLI boundary

Global selection:

```text
--storage-backend legacy|namespaced
```

Environment equivalent:

```text
ANALYSTWATCH_STORAGE_BACKEND
```

The normal monitoring/list/check/Pages paths all construct `MonitorService` through the shared runtime factory.

`verify-state` is backend-aware and rejects a mismatched schema.

`backup-state` and `restore-state` remain explicitly legacy-only. v0.13 does not imply namespaced snapshot parity that has not been implemented.

## Migration command

`import-namespaced-state` wraps the v0.12 create-only migration primitive:

- source must be a verified legacy schema-v1 snapshot;
- one selected workspace is imported;
- destination must not exist;
- destination is schema-v2 with a new storage identity;
- source/history/baseline/review/candidate/attempt state is retained for that workspace;
- no runtime or hosted cutover occurs automatically.

The migration command is deliberately separate from runtime selection so importing data and choosing to run against it are two explicit actions.

## FastAPI boundary

`create_app(...)` accepts `storage_backend=` and otherwise reads `ANALYSTWATCH_STORAGE_BACKEND`, defaulting to `legacy`.

FastAPI uses the same runtime factory as CLI. `app.state.storage_backend` records the resolved backend, `app.state.storage` is the selected raw implementation, and `app.state.workspace_storage` is the domain `MonitoringStore` used by the service/read paths.

All previously verified workspace guards remain in place.

## End-to-end migration rehearsal

The v0.13 acceptance suite creates legacy operational state containing:

- a Healthy baseline observation;
- a later Critical observation;
- a Reviewed observation state;
- an Eligible Opened notification candidate;
- a successful dry-run delivery attempt.

The suite then:

1. snapshots the legacy database with the verified schema-v1 backup path;
2. imports workspace `local` into a new schema-v2 database;
3. starts FastAPI with `storage_backend="namespaced"`;
4. reads source/history/candidate/attempt continuity through API endpoints;
5. renders static Pages from the migrated namespaced store and verifies aggregate candidate/attempt state.

This proves that a migrated schema-v2 database is runnable by the application, not merely structurally valid.

## Hosted deployment boundary

No workflow or hosted configuration selects the namespaced backend in v0.13. With `ANALYSTWATCH_STORAGE_BACKEND` unset, the hosted pipeline continues on `legacy`.

Post-merge `monitor-state` advancement is therefore the deployment compatibility gate: it proves the new runtime factory did not break the existing hosted legacy path.

## Verification

The verified v0.13 functional checkpoint passed Ruff, compile and **129 deterministic tests**.

New regressions prove:

- default legacy initialization;
- explicit namespaced initialization;
- mismatch rejection in both schema directions;
- corrupt/unknown existing state rejection without mutation;
- FastAPI startup refusal on mismatch;
- CLI import and backend-aware verification;
- legacy-only backup/restore boundary;
- complete legacy snapshot → schema-v2 → FastAPI → Pages rehearsal.

## Limitations

- hosted state still uses branch-backed legacy SQLite test persistence;
- there is no automatic migration/cutover coordinator;
- namespaced backup/restore parity is not implemented;
- there is no authenticated workspace/user authorization layer;
- no deployment-grade production database adapter exists yet;
- no real outbound notification provider exists.
