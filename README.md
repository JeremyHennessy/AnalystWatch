# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.12 status

Core v0.12 keeps the verified monitoring, review, incident, delivery-attempt, workspace-runtime and legacy SQLite behavior from v0.11, while adding a separately proven workspace-aware persistent schema.

New in v0.12:

- `NamespacedStorage`, a separate persistent SQLite adapter using schema version 2
- composite workspace identity across sources, observations, reviews, candidates and attempts
- workspace-local idempotency-key uniqueness
- workspace-local candidate/adapter attempt numbering
- safe reuse of the same source/candidate/attempt IDs in different workspaces in one database
- read-only verified import from a legacy schema-v1 snapshot
- selected-workspace import only, preserving baseline/review/candidate/attempt state
- create-only import destinations with a new storage identity

**Core v0.12 does not switch the hosted runtime to the new schema.** CLI, FastAPI, Pages and `monitor-state` continue to use the verified legacy `Storage + WorkspaceStore` path by default.

**Core v0.12 still has no real outbound notification provider.** The only delivery adapter remains deterministic local `dry-run` and performs no external I/O.

## Namespaced persistent identity

`NamespacedStorage(path, workspace_id)` is bound to one workspace, but multiple bound instances can share the same SQLite file.

Schema-v2 tables use workspace-aware keys such as:

- `(workspace_id, source_id)`
- `(workspace_id, observation_id)`
- `(workspace_id, candidate_id)`
- `(workspace_id, attempt_id)`
- `(workspace_id, idempotency_key)`

This allows `team-a` and `team-b` to both own a source called `market-data` and to reuse the same delivery idempotency value without collision.

The existing `MonitoringStore` contract is unchanged and `NamespacedStorage` satisfies it.

## Verified legacy import

A verified legacy schema-v1 snapshot can be imported into a **new** schema-v2 database for one selected workspace:

```python
from analystwatch.namespaced_storage import NamespacedStorage

result = NamespacedStorage.import_legacy_snapshot(
    "backups/legacy.db",
    "migrations/team-a.db",
    workspace_id="team-a",
)
```

Import behavior is intentionally conservative:

- the source database is opened/verified read-only through the existing legacy verifier;
- only sources whose `workspace_id` matches the selected workspace are copied;
- observations, baselines, reviews, notification candidates and delivery attempts for those sources are preserved;
- the destination must not already exist;
- the destination is verified as schema-v2 after import;
- the new database receives a new `storage_id` rather than impersonating the legacy snapshot.

There is no automatic runtime switch after import.

## Current runtime

The verified runtime remains unchanged from v0.11:

```bash
analystwatch --workspace-id local list
analystwatch --workspace-id team-a check market-data
analystwatch --workspace-id team-a build-pages --output site
```

FastAPI remains workspace-bound through `WorkspaceStore`. Raw SQLite verify/backup/restore remain implementation-specific maintenance operations.

## Verification

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.12 functional checkpoint passed Ruff, compile and **121 tests**. Eight new regressions cover schema-v2 protocol conformance, duplicate IDs/idempotency across workspaces, isolation, foreign-write blocking, full selected-workspace legacy import, overwrite protection, schema-version rejection and corrupt-source rejection.

The live-source PR workflow is path-filtered to ingestion/model/profile/service changes and does not run for this new-adapter-only diff. Hosted compatibility is verified after merge by the normal `monitor-state` pipeline, which remains on the legacy runtime.

## Current limitations

- schema-v2 is not yet selectable by CLI/FastAPI runtime configuration
- the hosted `monitor-state` deployment remains legacy SQLite test persistence
- there is no authenticated user/session authorization layer
- legacy import is currently a Python API, not a CLI migration command
- snapshots remain local SQLite files, not managed backups
- no real notification provider exists

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
