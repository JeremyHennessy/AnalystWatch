from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analystwatch.cli import main as cli_main
from analystwatch.models import (
    DatasetProfile,
    DeliveryAttemptState,
    HealthStatus,
    IncidentTransition,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    ObservationReview,
    ObservationReviewState,
    SourceDefinition,
    SourceType,
)
from analystwatch.namespaced_storage import (
    NAMESPACED_STORAGE_SCHEMA_VERSION,
    NamespacedStorage,
)
from analystwatch.pages import build_pages_site
from analystwatch.runtime_storage import create_runtime_storage, verify_runtime_database
from analystwatch.service import MonitorService
from analystwatch.storage import STORAGE_SCHEMA_VERSION, Storage
from analystwatch.web import create_app

NOW = datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc)


def _source(workspace_id: str = "local") -> SourceDefinition:
    return SourceDefinition(
        id="market",
        workspace_id=workspace_id,
        name="Market Data",
        source_type=SourceType.CSV,
        location="market.csv",
    )


def _observation(
    observation_id: str,
    health: HealthStatus,
    observed_at: datetime,
) -> Observation:
    return Observation(
        id=observation_id,
        source_id="market",
        observed_at=observed_at,
        available=True,
        health=health,
        profile=DatasetProfile(row_count=10, column_count=1, columns={}),
    )


def _build_legacy_operational_state(path: Path) -> Storage:
    store = Storage(path)
    store.initialize()
    store.upsert_source(_source())

    baseline = _observation("obs-healthy", HealthStatus.HEALTHY, NOW)
    store.save_observation(baseline, set_baseline=True)

    critical = _observation(
        "obs-critical",
        HealthStatus.CRITICAL,
        NOW + timedelta(minutes=5),
    )
    candidate = NotificationCandidate(
        id="candidate-opened",
        source_id="market",
        observation_id=critical.id,
        transition=IncidentTransition.OPENED,
        current_health=HealthStatus.CRITICAL,
        created_at=critical.observed_at,
        reason="Migration rehearsal",
        state=NotificationCandidateState.ELIGIBLE,
        evaluated_at=critical.observed_at,
        policy_enabled_transitions=[IncidentTransition.OPENED],
        policy_reason="Enabled for migration rehearsal",
    )
    store.save_observation(critical, notification_candidate=candidate)
    store.save_review(
        ObservationReview(
            observation_id=critical.id,
            source_id="market",
            state=ObservationReviewState.REVIEWED,
            updated_at=critical.observed_at,
        )
    )
    prepared, replayed = store.claim_delivery_attempt(
        candidate.id,
        "migration-key",
        "dry-run",
        created_at=critical.observed_at,
        retry_minutes=0,
        claim_owner="migration-worker",
    )
    assert replayed is False
    store.update_delivery_attempt(
        prepared.model_copy(
            update={
                "state": DeliveryAttemptState.SUCCEEDED,
                "completed_at": critical.observed_at,
                "result_summary": "Dry-run success",
            }
        )
    )
    return store


def test_runtime_factory_defaults_to_legacy_for_new_database(tmp_path: Path):
    path = tmp_path / "legacy.db"
    runtime = create_runtime_storage(path, "local")
    assert runtime.backend == "legacy"

    MonitorService(runtime.monitoring_store)
    verification = verify_runtime_database(path, "legacy")
    assert verification.schema_version == STORAGE_SCHEMA_VERSION


def test_runtime_factory_initializes_explicit_namespaced_database(tmp_path: Path):
    path = tmp_path / "namespaced.db"
    runtime = create_runtime_storage(path, "team-a", "namespaced")
    assert runtime.backend == "namespaced"

    service = MonitorService(runtime.monitoring_store)
    service.add_source(_source("team-a"))
    verification = verify_runtime_database(path, "namespaced")
    assert verification.schema_version == NAMESPACED_STORAGE_SCHEMA_VERSION
    assert verification.source_count == 1


def test_runtime_factory_rejects_schema_backend_mismatch_before_initialization(tmp_path: Path):
    legacy_path = tmp_path / "legacy.db"
    legacy = Storage(legacy_path)
    legacy.initialize()
    legacy_id = legacy.verify().storage_id

    with pytest.raises(ValueError, match="requires schema version 2"):
        create_runtime_storage(legacy_path, "local", "namespaced")
    assert Storage.verify_database(legacy_path).storage_id == legacy_id

    namespaced_path = tmp_path / "namespaced.db"
    namespaced = NamespacedStorage(namespaced_path, "local")
    namespaced.initialize()
    namespaced_id = namespaced.verify().storage_id

    with pytest.raises(ValueError, match="requires schema version 1"):
        create_runtime_storage(namespaced_path, "local", "legacy")
    assert NamespacedStorage.verify_database(namespaced_path).storage_id == namespaced_id


def test_runtime_factory_rejects_corrupt_and_unknown_existing_state_without_mutation(
    tmp_path: Path,
):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not sqlite")
    original = corrupt.read_bytes()
    with pytest.raises(ValueError, match="integrity verification"):
        create_runtime_storage(corrupt, "local", "legacy")
    assert corrupt.read_bytes() == original

    unknown = tmp_path / "unknown.db"
    sqlite3.connect(unknown).close()
    with pytest.raises(ValueError, match="no AnalystWatch schema metadata"):
        create_runtime_storage(unknown, "local", "legacy")
    with sqlite3.connect(unknown) as db:
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall() == []


def test_fastapi_refuses_wrong_backend_before_startup(tmp_path: Path):
    legacy = Storage(tmp_path / "legacy.db")
    legacy.initialize()

    with pytest.raises(ValueError, match="requires schema version 2"):
        create_app(tmp_path / "legacy.db", workspace_id="local", storage_backend="namespaced")


def test_cli_import_and_backend_aware_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    legacy = Storage(tmp_path / "legacy.db")
    legacy.initialize()
    snapshot = tmp_path / "snapshot.db"
    legacy.backup_to(snapshot)
    destination = tmp_path / "namespaced.db"

    assert (
        cli_main(
            [
                "--workspace-id",
                "local",
                "import-namespaced-state",
                str(snapshot),
                str(destination),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        cli_main(
            [
                "--db",
                str(destination),
                "--storage-backend",
                "namespaced",
                "verify-state",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == NAMESPACED_STORAGE_SCHEMA_VERSION


def test_namespaced_mode_does_not_claim_legacy_backup_restore_support(tmp_path: Path):
    path = tmp_path / "namespaced.db"
    NamespacedStorage(path, "local").initialize()

    with pytest.raises(SystemExit, match="available only"):
        cli_main(
            [
                "--db",
                str(path),
                "--storage-backend",
                "namespaced",
                "backup-state",
                str(tmp_path / "backup.db"),
            ]
        )


def test_full_legacy_to_namespaced_fastapi_and_pages_rehearsal(tmp_path: Path):
    legacy = _build_legacy_operational_state(tmp_path / "legacy.db")
    snapshot = tmp_path / "snapshot.db"
    snapshot_result = legacy.backup_to(snapshot)
    assert snapshot_result.verification.schema_version == STORAGE_SCHEMA_VERSION

    destination = tmp_path / "namespaced.db"
    NamespacedStorage.import_legacy_snapshot(
        snapshot,
        destination,
        workspace_id="local",
    )

    app = create_app(destination, workspace_id="local", storage_backend="namespaced")
    assert app.state.storage_backend == "namespaced"
    client = TestClient(app)

    source_response = client.get("/api/sources/market")
    assert source_response.status_code == 200
    source_payload = source_response.json()
    assert source_payload["source"]["workspace_id"] == "local"
    assert len(source_payload["history"]) == 2
    assert source_payload["notification_candidate_count"] == 1
    assert source_payload["delivery_attempt_count"] == 1

    candidates = client.get("/api/notification-candidates", params={"source_id": "market"})
    assert candidates.status_code == 200
    assert candidates.json()[0]["id"] == "candidate-opened"

    attempts = client.get("/api/delivery-attempts", params={"source_id": "market"})
    assert attempts.status_code == 200
    assert attempts.json()[0]["idempotency_key"] == "migration-key"

    pages = build_pages_site(app.state.workspace_storage, tmp_path / "site")
    state = json.loads((pages / "state.json").read_text(encoding="utf-8"))
    assert len(state["sources"]) == 1
    assert state["sources"][0]["notification_candidate_count"] == 1
    assert state["sources"][0]["delivery_attempt_count"] == 1
    assert "Market Data" in (pages / "index.html").read_text(encoding="utf-8")
