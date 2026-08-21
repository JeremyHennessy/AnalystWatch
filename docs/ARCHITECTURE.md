# AnalystWatch Core v0.9 Architecture

## Decision

Core v0.9 remains a Python modular monolith. SQLite is still the current local/test persistence mechanism; v0.9 makes that state identifiable, verifiable and portable without claiming it is production storage. FastAPI remains the local/API control plane and GitHub Pages remains read-only generated output.

The deterministic monitoring engine is still authoritative. Review state, incident state, notification policy, delivery attempts, claim ownership and reconciliation attribution are operational records and never rewrite detector findings or Health.

## Storage identity

`Storage.initialize()` additively creates `storage_metadata` and writes, once:

- `schema_version`
- `storage_id`

Existing databases receive these rows when first opened under v0.9. `INSERT OR IGNORE` keeps the storage ID stable across later initialization.

## Read-only verification

`Storage.verify_database(path)`:

1. requires the file to already exist;
2. opens SQLite using `mode=ro`;
3. runs `PRAGMA integrity_check`;
4. reads metadata when available;
5. reports table counts for sources, observations, reviews, notification candidates and delivery attempts;
6. closes without initializing or modifying the database.

A corrupt SQLite file returns an unsuccessful `StorageVerification`; verification does not repair or rewrite it.

## Snapshot creation

`Storage.backup_to(destination)` is create-only:

- destination cannot equal active DB;
- existing destination is rejected;
- active DB must verify first;
- copy uses SQLite's backup API;
- snapshot is verified afterward;
- verified storage identity/schema/table counts must match the active DB;
- incomplete new snapshot is deleted on failure.

## Snapshot restore

`Storage.restore_snapshot(snapshot, destination)` is also create-only:

- source snapshot must exist and verify;
- destination must not already exist;
- source snapshot is opened read-only;
- SQLite backup API copies it into a new DB;
- restored DB must verify identically;
- incomplete new destination is deleted on failure.

There is intentionally no in-place restore/overwrite operation in v0.9.

## Execution ownership

`DeliveryAttempt` adds optional audit fields:

- `claim_owner`
- `reconciled_by`

Operational `MonitorService` paths always provide a validated owner. Low-level storage helpers keep ownership optional for backward-compatible tests/manual fixtures.

Service owner resolution order:

1. explicit constructor/operation override;
2. `ANALYSTWATCH_EXECUTION_OWNER`;
3. `hostname:pid`.

Same-key idempotency replay returns the existing persisted attempt, so a later process cannot overwrite the original claimant.

Prepared reconciliation records a separate reviewer identity while preserving the original claimant.

## Remote/API boundary

Storage verification/backup/restore are **local CLI only**. They are not FastAPI endpoints. FastAPI dry-run/reconciliation uses the process execution owner and does not accept remote owner-spoofing parameters.

## Public Pages boundary

Pages code is unchanged in v0.9. It consumes aggregate attempt/candidate data only, so storage IDs, execution owners, reviewer identities, reconciliation notes and idempotency keys remain absent from generated output.

## Existing safety semantics

v0.8 behavior remains unchanged:

- atomic SQLite claim under `BEGIN IMMEDIATE`;
- idempotency replay;
- concurrent different-key exclusion;
- independent retry timing;
- explicit Prepared reconciliation;
- dry-run adapter only;
- no automatic delivery/provider.

## Verification boundary

The verified v0.9 functional checkpoint passed Ruff, compile, **84 deterministic tests**, and live-source smoke against the existing configured sources.

## Limitations

- branch-backed SQLite is still test persistence, not a production database
- snapshot files are local artifacts, not managed/remote backups
- no automatic backup schedule or retention policy
- no distributed execution lease across independent databases
- no authentication/workspace boundary
- no real notification provider
