# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.14 status

Core v0.14 adds a deployment-grade **PostgreSQL persistence implementation** behind the same `MonitoringStore` contract already proven by SQLite and `MemoryStore`.

PostgreSQL is an explicit third runtime backend:

- `legacy` — SQLite schema-v1; still the safe default and still used by the hosted `monitor-state` deployment;
- `namespaced` — workspace-aware SQLite schema-v2;
- `postgres` — workspace-aware PostgreSQL persistence, selected only when explicitly configured with a DSN.

**Core v0.14 does not switch the hosted deployment to PostgreSQL.** No production DSN is committed to the repository and an unset backend still resolves to `legacy`.

**Core v0.14 still has no real outbound notification provider.** Delivery remains deterministic local `dry-run` only.

## PostgreSQL persistence

`PostgresStorage` implements the existing service persistence contract with workspace-aware keys equivalent to the schema-v2 proof:

- `(workspace_id, source_id)`
- `(workspace_id, observation_id)`
- `(workspace_id, candidate_id)`
- `(workspace_id, attempt_id)`
- `(workspace_id, idempotency_key)`

The implementation uses the PostgreSQL schema `analystwatch` and keeps its own backend-specific schema metadata. Different workspaces can reuse domain IDs and idempotency keys without collision.

Delivery-attempt concurrency uses PostgreSQL row locking instead of SQLite's database-level claim transaction. Candidate claims and Prepared reconciliation use `SELECT ... FOR UPDATE`, while uniqueness constraints remain workspace-scoped.

## Runtime selection

The default remains unchanged:

```bash
analystwatch --storage-backend legacy --workspace-id local list
```

Namespaced SQLite remains available:

```bash
analystwatch --storage-backend namespaced --db state-v2.db --workspace-id team-a list
```

PostgreSQL requires explicit selection **and** a DSN:

```bash
analystwatch \
  --storage-backend postgres \
  --postgres-dsn "$ANALYSTWATCH_POSTGRES_DSN" \
  --workspace-id team-a \
  list
```

Environment variables:

```text
ANALYSTWATCH_STORAGE_BACKEND=postgres
ANALYSTWATCH_POSTGRES_DSN=postgresql://...
```

Selecting `postgres` without a DSN is rejected. No PostgreSQL DSN is inferred from `--db`.

FastAPI supports the same explicit boundary:

```python
from analystwatch.web import create_app

app = create_app(
    workspace_id="team-a",
    storage_backend="postgres",
    postgres_dsn="postgresql://...",
)
```

`app.state.storage_backend` records the resolved backend.

## PostgreSQL migration rehearsal

Core v0.14 adds an explicit schema-v2 → PostgreSQL workspace import. The destination workspace must be empty.

CLI rehearsal:

```bash
analystwatch \
  --db migrations/team-a-v2.db \
  --workspace-id team-a \
  --storage-backend postgres \
  --postgres-dsn "$ANALYSTWATCH_POSTGRES_DSN" \
  import-postgres-state
```

The import operates through the `MonitoringStore` contract and preserves:

- source definitions;
- observation history;
- baseline selection;
- observation review state;
- notification candidates;
- delivery-attempt history and idempotency keys.

The regression suite then starts FastAPI on the imported PostgreSQL workspace and verifies source/history/candidate/attempt continuity through API reads.

## PostgreSQL verification and CI

Backend-aware verification is available when PostgreSQL is explicitly selected:

```bash
analystwatch \
  --storage-backend postgres \
  --postgres-dsn "$ANALYSTWATCH_POSTGRES_DSN" \
  verify-state
```

GitHub CI now starts a real PostgreSQL 16 service for the test job. The existing store-conformance suite runs against **SQLite, MemoryStore and PostgreSQL**, including baseline/history, incidents/candidates, idempotent attempts, retry timing, Prepared reconciliation, review/baseline promotion and Pages rendering.

Additional PostgreSQL regressions cover:

- explicit DSN enforcement;
- cross-workspace duplicate identities and idempotency values;
- concurrent delivery claims serialized with `FOR UPDATE`;
- schema-v2 → PostgreSQL operational-state import;
- FastAPI startup/readback on PostgreSQL;
- CLI cutover rehearsal.

The verified v0.14 functional checkpoint passed Ruff, compile and **143 tests** against PostgreSQL 16.

## Safety and operational boundaries

v0.14 proves the application persistence contract on PostgreSQL, but it is **not** a managed production deployment.

Still intentionally deferred:

- provisioning a managed PostgreSQL service and production secrets;
- production migration/version tooling beyond the current schema initialization contract;
- managed backups, point-in-time recovery and retention policy;
- authenticated user/session identity and workspace membership authorization;
- real outbound notification delivery.

The hosted GitHub workflow remains on legacy branch-backed SQLite test persistence until a separately controlled deployment cutover is approved and verified.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
