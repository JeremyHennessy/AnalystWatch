# AnalystWatch Core v0.12 Architecture

## Decision

Core v0.12 proves a persistent workspace-aware identity model without changing the verified hosted runtime. The existing legacy SQLite `Storage + WorkspaceStore` path remains the default for CLI, FastAPI, Pages and `monitor-state`.

A separate `NamespacedStorage` adapter introduces schema version 2 and satisfies the existing `MonitoringStore` contract. This keeps migration risk isolated from detector, incident, notification-policy and delivery-attempt semantics.

## Schema-v2 identity model

Every operational table is physically namespaced by workspace.

### Sources

Primary key: `(workspace_id, id)`.

### Observations

Primary key: `(workspace_id, id)` with composite foreign key to `(workspace_id, source_id)`.

### Observation reviews

Primary key: `(workspace_id, observation_id)` with workspace-scoped foreign keys to observation and source.

### Notification candidates

Primary key: `(workspace_id, id)` and unique `(workspace_id, observation_id)`.

### Delivery attempts

Primary key: `(workspace_id, id)` with:

- unique `(workspace_id, idempotency_key)`
- unique `(workspace_id, candidate_id, adapter, attempt_number)`
- workspace-scoped foreign keys to candidate and source

Consequently two workspaces can reuse the same source, observation, candidate and attempt IDs and the same idempotency key in one database without collision.

## Bound-store behavior

`NamespacedStorage(path, workspace_id)` is bound to exactly one validated workspace. All domain queries include that workspace key and source writes must match the bound workspace.

Multiple instances can share one SQLite file while remaining isolated:

```python
team_a = NamespacedStorage("state.db", "team-a")
team_b = NamespacedStorage("state.db", "team-b")
```

The adapter implements the same `MonitoringStore` surface used by `MonitorService` and the previously proven `Storage` / `MemoryStore` implementations.

## Legacy import boundary

`NamespacedStorage.import_legacy_snapshot(...)` is a create-only migration primitive.

Import sequence:

1. require source and destination to differ;
2. reject an existing destination;
3. verify the source read-only with the legacy schema-v1 verifier;
4. require schema version 1;
5. select only source definitions whose `workspace_id` matches the requested workspace;
6. create a new schema-v2 destination with a new `storage_id`;
7. copy selected source rows and their observations, reviews, candidates and attempts;
8. preserve baseline observation references;
9. verify the destination after import;
10. remove only the newly-created destination on failure.

The imported database deliberately receives a new logical storage identity. Migration is not a clone/restore operation and does not impersonate the legacy database.

## Runtime boundary

Core v0.12 does **not** add runtime backend selection. The current application continues to construct legacy `Storage` and wrap it in `WorkspaceStore`.

This means schema-v2 code can be independently tested without changing the deployment state or requiring a live migration.

## Compatibility

No changes are made to:

- legacy `Storage` schema or persistence semantics
- detector logic or thresholds
- incident derivation
- notification policy
- delivery retry/reconciliation state machine
- CLI/FastAPI runtime backend selection
- hosted source configuration
- Pages templates/CSS
- GitHub Actions workflows

## Verification

The verified v0.12 functional checkpoint passed Ruff, compile and **121 deterministic tests**.

The new regressions prove:

- `NamespacedStorage` satisfies `MonitoringStore`;
- duplicate IDs and idempotency values coexist across workspaces;
- foreign workspace rows are not exposed;
- foreign source writes are blocked;
- selected-workspace legacy import preserves baseline/review/candidate/attempt state;
- import never overwrites an existing target;
- schema-v2 input is rejected as a legacy source;
- corrupt sources fail before a destination is created.

## Limitations

- schema-v2 is not yet selectable by the application runtime
- there is no authenticated user/session authorization
- import has no CLI wrapper yet
- current hosted state remains legacy branch-backed SQLite test persistence
- no real outbound notification provider exists
