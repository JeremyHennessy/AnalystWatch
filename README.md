# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, unexpected row loss, null explosions, numerical scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.9 status

Core v0.9 is a test-ready Python modular monolith with scheduled monitoring, source-contract preflight, real-source validation, operational review, incident transitions, notification policy, hardened dry-run delivery attempts, and verified local persistence tooling.

It supports:

- deterministic reliability monitoring across CSV/XLSX/JSON/HTTP JSON sources
- explicit baseline + recent Healthy-history context
- safe source onboarding/editing and environment-backed API headers
- Acknowledged / Reviewed workflow state separate from technical Health
- derived Opened / Escalated / Recovered incidents
- opt-in notification-transition policy
- atomic SQLite dry-run attempt claims with idempotency/retry/reconciliation semantics
- stable SQLite storage identity and schema metadata
- read-only storage integrity verification
- verified SQLite snapshot creation
- create-only verified snapshot restore into a new destination
- persisted delivery claim owner and reconciliation reviewer identity
- local CLI persistence operations with no remote backup/restore API
- read-only GitHub Pages summaries with storage/owner/reviewer details redacted

**Core v0.9 still has no real outbound notification provider.** The only adapter remains local `dry-run`, with no external I/O or network request.

## Persistence integrity

Every initialized v0.9 database receives additive metadata:

- `storage_id` — stable UUID for that logical database
- `schema_version` — current storage metadata version

Verify an existing database without initializing or mutating it:

```bash
analystwatch --db instance/analystwatch.db verify-state
```

Verification opens SQLite read-only, runs `PRAGMA integrity_check`, and reports counts for sources, observations, reviews, notification candidates and delivery attempts.

## Verified backup and restore

Create a new verified snapshot:

```bash
analystwatch --db instance/analystwatch.db backup-state backups/analystwatch.db
```

Backup uses SQLite's backup API. The active database is verified first, then the snapshot is verified and must match the active storage identity/schema/counts. Existing snapshot destinations are never overwritten.

Restore is deliberately create-only:

```bash
analystwatch restore-state backups/analystwatch.db restored/analystwatch.db
```

The snapshot is opened/verified read-only, restored into a **new** destination, and the result must verify identically. Existing restore targets are rejected rather than overwritten. A failed backup/restore removes only the incomplete newly-created destination.

This is portability/test-hardening, **not** a production database migration or managed backup service.

## Execution ownership

Dry-run attempts now persist `claim_owner`. A service owner is resolved from:

1. an explicit owner supplied locally;
2. `ANALYSTWATCH_EXECUTION_OWNER`; or
3. local `hostname:pid`.

CLI override:

```bash
analystwatch dry-run-delivery <candidate-id> \
  --idempotency-key <stable-key> \
  --execution-owner worker-a
```

Same-key replay preserves the original stored claimant even when another service process replays it later.

Prepared reconciliation stores a separate reviewer identity:

```bash
analystwatch reconcile-delivery-attempt <attempt-id> \
  --outcome Failed \
  --note "Reviewed evidence and confirmed it did not complete." \
  --reviewer reviewer-b
```

The local FastAPI API continues to use the service process identity; owner overrides are intentionally not exposed as remote request parameters.

## Existing delivery safety

All prior v0.8 rules remain:

- monitoring never creates delivery attempts automatically;
- only Eligible candidates can be attempted;
- claim decisions use SQLite `BEGIN IMMEDIATE`;
- same-key replay is idempotent;
- different keys cannot both claim Prepared work;
- optional retry delay is independent from monitoring cadence;
- Prepared attempts require explicit reconciliation;
- no generic send route or real provider exists.

## Public-output boundary

Pages remains read-only. It does **not** expose:

- storage ID or schema metadata;
- claim owner;
- reconciliation reviewer or note;
- idempotency keys;
- backup/restore controls;
- request-header environment-variable names.

Existing approved incident/notification/dry-run copy remains unchanged.

## Verification

```bash
ruff check .
python -m compileall -q src tests scripts
pytest -q
```

The verified v0.9 functional checkpoint passed Ruff, compile, **84 tests**, and live-source smoke. New tests cover full-state snapshot/restore, corrupt-file non-mutation, unsafe destination rejection, stable storage identity, cross-service claimant preservation, reviewer attribution, and Pages redaction.

## Current limitations

- `monitor-state` branch persistence is still test-only, not production storage
- snapshots are local SQLite files; there is no managed backup scheduler/object storage integration
- restore is create-only; there is intentionally no in-place replacement operation
- execution ownership is attribution, not distributed leasing across independent databases
- no authentication/workspace ownership boundary exists yet
- no real notification provider exists
- more real incident/candidate history is required before introducing external side effects

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
