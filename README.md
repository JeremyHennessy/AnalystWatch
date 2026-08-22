# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.13 status

Core v0.13 keeps the verified monitoring, review, incident, notification-policy and delivery-attempt behavior from earlier milestones and adds **controlled runtime persistence selection**.

Two SQLite persistence modes now exist:

- `legacy` — schema version 1, still the safe default and still used by the hosted `monitor-state` deployment;
- `namespaced` — schema version 2, workspace-aware persistent identity introduced and proven in v0.12.

No backend is selected implicitly from file shape. Existing databases are inspected read-only first and the requested backend must match their stored schema version before initialization is allowed.

**Core v0.13 still has no real outbound notification provider.** The only delivery adapter remains deterministic local `dry-run` and performs no external I/O.

## Controlled backend selection

CLI selection:

```bash
analystwatch --storage-backend legacy --workspace-id local list
analystwatch --storage-backend namespaced --workspace-id team-a list
```

The equivalent environment variable is:

```bash
ANALYSTWATCH_STORAGE_BACKEND=namespaced
```

If unset, the backend is `legacy`.

FastAPI supports the same boundary:

```python
from analystwatch.web import create_app

app = create_app(
    "state.db",
    workspace_id="team-a",
    storage_backend="namespaced",
)
```

`app.state.storage_backend` records the selected backend.

## Startup safety

For an existing database, AnalystWatch performs read-only integrity/schema inspection before constructing the selected runtime store.

- `legacy` requires schema version 1;
- `namespaced` requires schema version 2;
- corrupt databases are rejected;
- SQLite files without AnalystWatch schema metadata are rejected;
- a schema/backend mismatch is rejected before either store can initialize or mutate the file.

A non-existent database may be initialized under the explicitly selected backend.

Backend-aware verification:

```bash
analystwatch --db state.db --storage-backend legacy verify-state
analystwatch --db state-v2.db --storage-backend namespaced verify-state
```

## Local legacy → namespaced import

The v0.12 create-only import primitive now has a local CLI wrapper:

```bash
analystwatch \
  --workspace-id team-a \
  import-namespaced-state \
  backups/legacy.db \
  migrations/team-a-v2.db
```

The command verifies the legacy schema-v1 snapshot read-only, imports only the selected workspace into a new schema-v2 database, preserves its source/history/baseline/review/candidate/attempt state, assigns a new storage identity and never overwrites an existing destination.

Import does **not** automatically switch the application or hosted deployment to the new file.

## Migration rehearsal

Core v0.13 includes an end-to-end regression rehearsal using real persisted operational state:

1. create legacy schema-v1 state with a Healthy baseline;
2. persist a later Critical observation;
3. persist an Eligible Opened candidate and Reviewed state;
4. persist a successful dry-run delivery attempt;
5. create a verified legacy snapshot;
6. import the selected workspace into schema-v2;
7. start FastAPI explicitly in `namespaced` mode;
8. verify source history, candidate and attempt continuity through API reads;
9. render the static Pages site from the migrated namespaced store.

That rehearsal passes without changing the hosted default.

## Maintenance boundary

Legacy snapshot tooling remains intentionally explicit:

```bash
analystwatch --storage-backend legacy backup-state backups/state.db
analystwatch --storage-backend legacy restore-state backups/state.db restored/state.db
```

Core v0.13 does not claim equivalent backup/restore tooling for schema-v2. Namespaced mode supports verified runtime inspection and the create-only legacy import path; broader persistence operations remain a later milestone.

## Verification

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.13 functional checkpoint passed Ruff, compile and **129 tests**. Eight new regressions cover default/explicit backend initialization, both schema-mismatch directions, corrupt/unknown-state rejection without mutation, FastAPI startup refusal, CLI import/verification, maintenance-boundary enforcement and the full migrated FastAPI/Pages rehearsal.

The live-source PR workflow is path-filtered to ingestion/model/profile/service changes and does not run for this runtime-only milestone. Hosted compatibility is verified after merge by the normal `monitor-state` pipeline, which remains on the default `legacy` backend.

## Current limitations

- hosted `monitor-state` remains legacy branch-backed SQLite test persistence;
- there is no automatic hosted backend migration or cutover;
- namespaced backup/restore parity is not implemented;
- there is no authenticated user/session authorization layer;
- no deployment-grade production database adapter has been selected;
- snapshots remain local SQLite files rather than managed backups;
- no real notification provider exists.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
