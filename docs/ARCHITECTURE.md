# AnalystWatch Core v0.10 Architecture

## Decision

Core v0.10 keeps the Python modular-monolith runtime and the existing SQLite schema, but adds the first explicit storage/workspace boundary. The objective is to separate ownership semantics from detector/service logic before selecting a production database or adding remote authentication.

The deterministic monitoring engine remains authoritative. Review state, incident state, notification policy, delivery attempts, execution ownership and reconciliation attribution remain operational records and do not rewrite detector findings or Health.

## MonitoringStore protocol

`src/analystwatch/store.py` defines the structural persistence contract required by monitoring/service/read surfaces. The protocol covers:

- source persistence and lookup;
- observations, baselines and reference history;
- observation review state;
- notification candidate state;
- delivery attempt claim/update/list/reconciliation;
- guarded baseline promotion.

The existing SQLite `Storage` class satisfies this protocol without schema changes.

The protocol intentionally excludes local SQLite maintenance operations such as verify/backup/restore because those are implementation-specific persistence tooling rather than the monitoring domain contract.

## Source workspace ownership

`SourceDefinition.workspace_id` is introduced with a safe default of `local` and the same conservative identifier alphabet used for source IDs.

Persisted source JSON written before v0.10 omits the field. Pydantic therefore loads those definitions as `workspace_id="local"`; v0.10 does not need a destructive migration or rewrite.

## WorkspaceStore

`WorkspaceStore` is a workspace-bound view over a `MonitoringStore`.

For reads it returns only records whose source belongs to the bound workspace. For writes it validates workspace ownership before delegating to the underlying store.

The boundary covers:

- sources;
- observations and baselines;
- reviews;
- notification candidates;
- delivery attempts and claims;
- Prepared reconciliation;
- baseline promotion.

Foreign records are treated as unavailable to the bound service rather than exposing their existence.

## Service binding

`create_workspace_service(storage, workspace_id, execution_owner=None)` creates an existing `MonitorService` over `WorkspaceStore`. Core monitoring and delivery state-machine code is therefore unchanged; ownership is enforced by the persistence boundary supplied to it.

This is deliberately opt-in in v0.10. Existing CLI/FastAPI construction continues to use the unbound SQLite store so the hosted/test runtime does not change in the same milestone that introduces the guard abstraction.

## Important persistence limitation

The current SQLite schema still has `sources.id` as a global primary key and downstream records still refer to `source_id` alone. Consequently:

- two workspaces cannot store the same source ID in one database;
- `WorkspaceStore` blocks a foreign workspace from reusing an existing source ID;
- v0.10 is an ownership guardrail, not full multi-tenant persistence.

Composite workspace/source keys or a deployment database must be introduced in a later, separately verified migration.

## Existing v0.9 persistence safety

All v0.9 behavior remains unchanged:

- additive stable `storage_id` and schema metadata;
- read-only SQLite integrity verification;
- verified SQLite backup API snapshots;
- create-only verified restore;
- execution claim/reviewer attribution;
- atomic delivery claim and explicit reconciliation semantics.

## Public/runtime boundary

Core v0.10 does not change GitHub Pages, the hosted source configuration, FastAPI routing, CLI behavior or notification delivery. This avoids silently changing the production/test entrypoint before the workspace guard itself has passed the full regression and live-source gates.

## Verification boundary

The verified v0.10 functional checkpoint passed Ruff, compile, **92 deterministic tests**, and live-source smoke against the existing configured sources.

## Limitations

- workspace binding is opt-in rather than the default runtime path
- no remote user/session authentication exists
- no authorization policy beyond explicit workspace ownership is implemented
- SQLite source IDs are still globally unique
- branch-backed SQLite remains test persistence, not a production database
- no real notification provider exists
