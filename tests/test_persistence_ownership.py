from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from analystwatch.models import (
    DeliveryAttemptState,
    DeliveryReconciliationOutcome,
    IncidentTransition,
    MonitoringConfig,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.service import MonitorService
from analystwatch.storage import STORAGE_SCHEMA_VERSION, Storage


def _source(path: Path) -> SourceDefinition:
    return SourceDefinition(
        id="market",
        name="Market",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            unique_keys=["id"],
            notification_transitions=[IncidentTransition.OPENED],
        ),
    )


def _healthy(path: Path) -> None:
    pd.DataFrame({"id": range(20), "value": [100] * 20}).to_csv(path, index=False)


def _service_with_attempt(
    db_path: Path,
    source_path: Path,
    *,
    owner: str = "worker-a",
) -> tuple[MonitorService, str]:
    service = MonitorService(Storage(db_path), execution_owner=owner)
    _healthy(source_path)
    service.add_source(_source(source_path))
    service.check_source("market")
    source_path.unlink()
    service.check_source("market")
    candidate = service.notification_candidates("market")[0]
    attempt = service.dry_run_delivery(
        candidate.id,
        "stable-attempt-key",
        execution_owner=owner,
    )
    assert attempt.state == DeliveryAttemptState.SUCCEEDED
    return service, candidate.id


def test_initialize_assigns_stable_storage_identity_and_schema_version(tmp_path: Path):
    db_path = tmp_path / "state.db"
    storage = Storage(db_path)
    storage.initialize()
    first = storage.verify()

    storage.initialize()
    second = storage.verify()

    assert first.integrity_ok is True
    assert first.storage_id
    assert first.schema_version == STORAGE_SCHEMA_VERSION
    assert second.storage_id == first.storage_id
    assert second.schema_version == first.schema_version


def test_backup_round_trip_preserves_verified_identity_and_counts(tmp_path: Path):
    db_path = tmp_path / "state.db"
    service, _ = _service_with_attempt(db_path, tmp_path / "market.csv")
    active = service.storage.verify()

    result = service.storage.backup_to(tmp_path / "snapshot.db")

    assert result.verification == active
    assert result.verification.integrity_ok is True
    assert result.verification.storage_id == active.storage_id
    assert result.verification.source_count == 1
    assert result.verification.observation_count == 2
    assert result.verification.notification_candidate_count == 1
    assert result.verification.delivery_attempt_count == 1


def test_restore_snapshot_creates_new_verified_database_with_same_state(tmp_path: Path):
    db_path = tmp_path / "state.db"
    service, candidate_id = _service_with_attempt(db_path, tmp_path / "market.csv")
    snapshot = tmp_path / "snapshot.db"
    service.storage.backup_to(snapshot)

    restored_path = tmp_path / "restored.db"
    restored = Storage.restore_snapshot(snapshot, restored_path)
    restored_storage = Storage(restored_path)

    assert restored.verification == service.storage.verify()
    assert restored_storage.get_source("market") is not None
    assert len(restored_storage.list_observations("market")) == 2
    assert len(restored_storage.list_notification_candidates("market")) == 1
    assert len(restored_storage.list_delivery_attempts(candidate_id=candidate_id)) == 1


def test_backup_and_restore_refuse_unsafe_destinations(tmp_path: Path):
    db_path = tmp_path / "state.db"
    storage = Storage(db_path)
    storage.initialize()

    with pytest.raises(ValueError, match="must differ"):
        storage.backup_to(db_path)

    existing_backup = tmp_path / "existing.db"
    existing_backup.write_bytes(b"do-not-overwrite")
    with pytest.raises(FileExistsError):
        storage.backup_to(existing_backup)
    assert existing_backup.read_bytes() == b"do-not-overwrite"

    snapshot = tmp_path / "snapshot.db"
    storage.backup_to(snapshot)
    with pytest.raises(ValueError, match="must differ"):
        Storage.restore_snapshot(snapshot, snapshot)
    restore_target = tmp_path / "restore-existing.db"
    restore_target.write_bytes(b"keep-me")
    with pytest.raises(FileExistsError):
        Storage.restore_snapshot(snapshot, restore_target)
    assert restore_target.read_bytes() == b"keep-me"


def test_corrupt_database_verification_fails_without_mutating_file(tmp_path: Path):
    corrupt = tmp_path / "corrupt.db"
    original = b"this is not sqlite data"
    corrupt.write_bytes(original)

    verification = Storage.verify_database(corrupt)

    assert verification.integrity_ok is False
    assert "SQLite verification failed" in verification.integrity_message
    assert corrupt.read_bytes() == original
    restore_target = tmp_path / "restore.db"
    with pytest.raises(ValueError, match="Snapshot failed integrity verification"):
        Storage.restore_snapshot(corrupt, restore_target)
    assert not restore_target.exists()


def test_delivery_claim_records_service_execution_owner(tmp_path: Path):
    service, candidate_id = _service_with_attempt(
        tmp_path / "state.db",
        tmp_path / "market.csv",
        owner="worker-a",
    )

    attempt = service.delivery_attempts(candidate_id=candidate_id)[0]

    assert attempt.claim_owner == "worker-a"


def test_same_key_replay_preserves_original_owner_across_services(tmp_path: Path):
    db_path = tmp_path / "state.db"
    source_path = tmp_path / "market.csv"
    first_service = MonitorService(Storage(db_path), execution_owner="worker-a")
    _healthy(source_path)
    first_service.add_source(_source(source_path))
    first_service.check_source("market")
    source_path.unlink()
    first_service.check_source("market")
    candidate = first_service.notification_candidates("market")[0]

    first = first_service.dry_run_delivery(candidate.id, "shared-key")
    second_service = MonitorService(Storage(db_path), execution_owner="worker-b")
    replay = second_service.dry_run_delivery(candidate.id, "shared-key")

    assert replay == first
    assert replay.claim_owner == "worker-a"


def test_reconciliation_records_explicit_reviewer_owner(tmp_path: Path):
    db_path = tmp_path / "state.db"
    source_path = tmp_path / "market.csv"
    service = MonitorService(Storage(db_path), execution_owner="worker-a")
    _healthy(source_path)
    service.add_source(_source(source_path))
    service.check_source("market")
    source_path.unlink()
    service.check_source("market")
    candidate = service.notification_candidates("market")[0]
    now = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    prepared, replayed = service.storage.claim_delivery_attempt(
        candidate.id,
        "prepared-key",
        "dry-run",
        created_at=now,
        retry_minutes=0,
        claim_owner="worker-a",
    )
    assert replayed is False

    reconciled = service.reconcile_delivery_attempt(
        prepared.id,
        DeliveryReconciliationOutcome.FAILED,
        "Reviewed the abandoned attempt and confirmed it did not complete.",
        now=now,
        reviewer="reviewer-b",
    )

    assert reconciled.claim_owner == "worker-a"
    assert reconciled.reconciled_by == "reviewer-b"
    assert reconciled.reconciliation_note.startswith("Reviewed the abandoned")


def test_pages_redacts_storage_identity_execution_owner_and_reviewer(tmp_path: Path):
    db_path = tmp_path / "state.db"
    source_path = tmp_path / "market.csv"
    service = MonitorService(Storage(db_path), execution_owner="secret-worker-owner")
    _healthy(source_path)
    service.add_source(_source(source_path))
    service.check_source("market")
    source_path.unlink()
    service.check_source("market")
    candidate = service.notification_candidates("market")[0]
    now = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    prepared, _ = service.storage.claim_delivery_attempt(
        candidate.id,
        "private-idempotency-key",
        "dry-run",
        created_at=now,
        retry_minutes=0,
        claim_owner="secret-worker-owner",
    )
    private_note = "private reconciliation note"
    service.reconcile_delivery_attempt(
        prepared.id,
        DeliveryReconciliationOutcome.FAILED,
        private_note,
        now=now,
        reviewer="secret-reviewer-owner",
    )
    storage_id = service.storage.verify().storage_id
    assert storage_id

    output = build_pages_site(service.storage, tmp_path / "site")
    detail = (output / "sources" / "market" / "index.html").read_text(encoding="utf-8")
    raw_state = (output / "state.json").read_text(encoding="utf-8")

    for private_value in [
        storage_id,
        "secret-worker-owner",
        "secret-reviewer-owner",
        "private-idempotency-key",
        private_note,
    ]:
        assert private_value not in detail
        assert private_value not in raw_state
    assert "Notification candidates" in detail
    assert "Core v0.7 dry-run attempts perform no external delivery" in detail
