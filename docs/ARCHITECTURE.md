# AnalystWatch Core v0.14 Architecture

## Decision

Core v0.14 proves PostgreSQL as a deployment-grade persistence implementation behind the established `MonitoringStore` contract. It deliberately does **not** combine production persistence with remote authentication or switch the hosted runtime away from legacy SQLite.

The deterministic monitoring engine, detector logic, incident derivation, notification policy and delivery-attempt state machine remain unchanged.

## Persistence implementations

The service contract is now exercised through three independent implementations:

- `Storage` / `WorkspaceStore` — legacy SQLite runtime;
- `NamespacedStorage` — workspace-aware SQLite schema-v2 proof;
- `PostgresStorage` — workspace-aware PostgreSQL implementation.

PostgreSQL lives in the database schema `analystwatch` and carries its own backend-specific schema metadata. PostgreSQL schema version numbers are not treated as interchangeable with the SQLite file schema versions.

## PostgreSQL identity model

The PostgreSQL tables preserve the workspace-aware identity semantics proven in v0.12.

### Sources

Primary key: `(workspace_id, id)`.

### Observations

Primary key: `(workspace_id, id)` with workspace-scoped source foreign key. A `BIGSERIAL` sequence supplies deterministic insertion ordering for timestamp ties.

### Observation reviews

Primary key: `(workspace_id, observation_id)` with workspace-scoped observation/source references.

### Notification candidates

Primary key: `(workspace_id, id)` with unique `(workspace_id, observation_id)` and a sequence for deterministic ordering.

### Delivery attempts

Primary key: `(workspace_id, id)` with:

- unique `(workspace_id, idempotency_key)`;
- unique `(workspace_id, candidate_id, adapter, attempt_number)`;
- workspace-scoped candidate/source foreign keys;
- insertion sequence for stable ordering.

This permits different workspaces to reuse source, observation, candidate, attempt and idempotency identifiers safely in one PostgreSQL database.

## Transaction and claim safety

SQLite's verified claim path uses `BEGIN IMMEDIATE`. PostgreSQL uses row-level locking instead.

For a delivery claim, `PostgresStorage`:

1. selects the workspace candidate with `FOR UPDATE`;
2. validates Eligible state;
3. resolves idempotent replay within the workspace;
4. checks the latest attempt and retry rules;
5. inserts the new Prepared attempt under workspace-scoped uniqueness constraints;
6. commits as one transaction.

Concurrent different-key claims for the same candidate therefore serialize on the candidate row. The regression suite proves that one caller obtains the Prepared attempt while the other observes the resulting Prepared state rather than creating duplicate work.

Prepared reconciliation likewise locks the attempt row with `FOR UPDATE` before applying Succeeded/Failed reconciliation evidence.

## Runtime storage selection

`runtime_storage.py` now supports:

```text
legacy | namespaced | postgres
```

`legacy` remains the default.

PostgreSQL selection is explicit and requires a separate DSN. `--db` continues to represent SQLite file state and is not overloaded as a PostgreSQL connection string.

CLI:

```text
--storage-backend postgres
--postgres-dsn <dsn>
```

Environment:

```text
ANALYSTWATCH_STORAGE_BACKEND=postgres
ANALYSTWATCH_POSTGRES_DSN=<dsn>
```

FastAPI accepts the same backend and DSN explicitly or through environment configuration.

Selecting PostgreSQL without a DSN is rejected before storage construction. With no backend setting, the hosted process still selects `legacy`.

## PostgreSQL verification

`PostgresStorage.verify_dsn(...)` verifies:

- database connectivity;
- presence of AnalystWatch PostgreSQL metadata;
- expected PostgreSQL schema version;
- persisted storage identity;
- source/observation/review/candidate/attempt counts.

This is a backend verification contract, not a substitute for managed-database health monitoring or backup verification.

## Workspace migration into PostgreSQL

`PostgresStorage.import_workspace(source_store)` copies one already-bound `MonitoringStore` into an empty PostgreSQL workspace.

Current cutover rehearsal uses `NamespacedStorage` as the source after the separately proven legacy → namespaced migration step.

The import preserves:

- sources;
- observations;
- current baseline pointers;
- observation reviews;
- notification candidates;
- delivery attempts, attempt numbers, states, ownership and idempotency keys.

The destination workspace must be empty, preventing an import from silently merging or overwriting existing production state.

The CLI command `import-postgres-state` makes this migration explicit. It requires `--storage-backend postgres`, a PostgreSQL DSN, a selected workspace and a schema-v2 source supplied through `--db`.

## FastAPI and Pages proof

The migration regression imports operational schema-v2 state into PostgreSQL and then starts FastAPI explicitly with the PostgreSQL backend.

The test verifies source history, candidate count and delivery-attempt count through normal API reads. The shared conformance suite also renders Pages from PostgreSQL, proving read surfaces do not depend on SQLite-specific behavior.

## CI boundary

The CI job now starts an actual PostgreSQL 16 service container. PostgreSQL is not mocked.

The existing cross-store conformance scenarios run against SQLite, `MemoryStore` and PostgreSQL. PostgreSQL-specific regressions add:

- DSN enforcement;
- workspace-scoped duplicate IDs/idempotency;
- concurrent candidate-claim serialization;
- namespaced → PostgreSQL import continuity;
- CLI import rehearsal;
- FastAPI PostgreSQL startup/readback.

The verified v0.14 functional checkpoint passed Ruff, compile and **143 deterministic tests** against PostgreSQL 16.

## Hosted deployment boundary

No production PostgreSQL DSN is committed or configured by v0.14. The hosted `monitor-state` workflow remains on the unset/default `legacy` path.

Post-merge `monitor-state` advancement remains the compatibility gate for the existing hosted runtime. It does **not** constitute a PostgreSQL production deployment.

## Remaining production requirements

PostgreSQL contract proof is only one layer of production readiness. Still separate:

- managed PostgreSQL provisioning and secret injection;
- formal migration/version rollout tooling;
- managed backups, point-in-time recovery, retention and restore drills;
- connection-pool/runtime sizing and observability;
- authenticated principals/sessions;
- workspace membership and remote authorization rules;
- first external notification provider.

The next milestone isolates authenticated workspace authorization so persistence and identity policy are not changed in the same release.
