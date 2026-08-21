from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

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
from analystwatch.storage import STORAGE_SCHEMA_VERSION, Storage
from analystwatch.store import MonitoringStore

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)


def _source(workspace_id: str, source_id: str = "shared") -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        workspace_id=workspace_id,
        name=f"Source {workspace_id}",
        source_type=SourceType.CSV,
        location=f"{workspace_id}.csv",
    )


def _observation(source_id: str, observation_id: str = "obs") -> Observation:
    return Observation(
        id=observation_id,
        source_id=source_id,
        observed_at=NOW,
        available=True,
        health=HealthStatus.HEALTHY,
        profile=DatasetProfile(row_count=1, column_count=0, columns={}),
    )


def _candidate(
    source_id: str,
    observation_id: str = "obs",
    candidate_id: str = "candidate",
) -> NotificationCandidate:
    return NotificationCandidate(
        id=candidate_id,
        source_id=source_id,
        observation_id=observation_id,
        transition=IncidentTransition.OPENED,
        current_health=HealthStatus.CRITICAL,
        created_at=NOW,
        reason="Namespaced persistence test",
        state=NotificationCandidateState.ELIGIBLE,
        evaluated_at=NOW,
        policy_enabled_transitions=[IncidentTransition.OPENED],
        policy_reason="Enabled for test",
    )


def _populate_workspace(
    store: NamespacedStorage | Storage,
    source: SourceDefinition,
    *,
    observation_id: str = "obs",
    candidate_id: str = "candidate",
    idempotency_key: str = "same-key",
) -> None:
    store.upsert_source(source)
    observation = _observation(source.id, observation_id)
    candidate = _candidate(source.id, observation_id, candidate_id)
    store.save_observation(
        observation,
        set_baseline=True,
        notification_candidate=candidate,
    )
    store.save_review(
        ObservationReview(
            observation_id=observation.id,
            source_id=source.id,
            state=ObservationReviewState.REVIEWED,
            updated_at=NOW,
        )
    )
    prepared, replayed = store.claim_delivery_attempt(
        candidate.id,
        idempotency_key,
        "dry-run",
        created_at=NOW,
        retry_minutes=0,
        claim_owner="worker-a",
    )
    assert replayed is False
    store.update_delivery_attempt(
        prepared.model_copy(
            update={
                "state": DeliveryAttemptState.SUCCEEDED,
                "completed_at": NOW,
                "result_summary": "Dry-run success",
            }
        )
    )


def test_namespaced_storage_satisfies_monitoring_store_protocol(tmp_path: Path):
    store = NamespacedStorage(tmp_path / "namespaced.db", "team-a")
    store.initialize()

    assert isinstance(store, MonitoringStore)
    verification = store.verify()
    assert verification.integrity_ok is True
    assert verification.schema_version == NAMESPACED_STORAGE_SCHEMA_VERSION


def test_same_domain_ids_can_coexist_across_workspaces(tmp_path: Path):
    path = tmp_path / "namespaced.db"
    team_a = NamespacedStorage(path, "team-a")
    team_b = NamespacedStorage(path, "team-b")
    team_a.initialize()
    team_b.initialize()

    _populate_workspace(team_a, _source("team-a"))
    _populate_workspace(team_b, _source("team-b"))

    assert team_a.get_source("shared").workspace_id == "team-a"
    assert team_b.get_source("shared").workspace_id == "team-b"
    assert team_a.get_observation("obs") is not None
    assert team_b.get_observation("obs") is not None
    assert team_a.get_notification_candidate("candidate") is not None
    assert team_b.get_notification_candidate("candidate") is not None

    attempt_a = team_a.list_delivery_attempts(candidate_id="candidate")[0]
    attempt_b = team_b.list_delivery_attempts(candidate_id="candidate")[0]
    assert attempt_a.id == attempt_b.id == "candidate:dry-run:1"
    assert attempt_a.idempotency_key == attempt_b.idempotency_key == "same-key"

    verification = team_a.verify()
    assert verification.source_count == 2
    assert verification.observation_count == 2
    assert verification.review_count == 2
    assert verification.notification_candidate_count == 2
    assert verification.delivery_attempt_count == 2


def test_namespaced_store_does_not_expose_foreign_workspace_rows(tmp_path: Path):
    path = tmp_path / "namespaced.db"
    team_a = NamespacedStorage(path, "team-a")
    team_b = NamespacedStorage(path, "team-b")
    team_a.initialize()
    team_b.initialize()
    _populate_workspace(team_a, _source("team-a"))

    assert team_b.get_source("shared") is None
    assert team_b.list_sources() == []
    assert team_b.get_observation("obs") is None
    assert team_b.list_observations("shared") == []
    assert team_b.get_baseline("shared") is None
    assert team_b.get_review("obs") is None
    assert team_b.get_notification_candidate("candidate") is None
    assert team_b.list_notification_candidates() == []
    assert team_b.get_delivery_attempt("candidate:dry-run:1") is None
    assert team_b.list_delivery_attempts() == []


def test_namespaced_store_rejects_foreign_source_write(tmp_path: Path):
    store = NamespacedStorage(tmp_path / "namespaced.db", "team-a")
    store.initialize()

    with pytest.raises(ValueError, match="does not match bound workspace"):
        store.upsert_source(_source("team-b"))


def test_legacy_import_copies_only_selected_workspace_with_operational_state(
    tmp_path: Path,
):
    legacy_path = tmp_path / "legacy.db"
    legacy = Storage(legacy_path)
    legacy.initialize()
    _populate_workspace(
        legacy,
        _source("team-a", "a-source"),
        observation_id="a-obs",
        candidate_id="a-candidate",
        idempotency_key="a-key",
    )
    _populate_workspace(
        legacy,
        _source("team-b", "b-source"),
        observation_id="b-obs",
        candidate_id="b-candidate",
        idempotency_key="b-key",
    )

    snapshot = tmp_path / "legacy-snapshot.db"
    legacy_result = legacy.backup_to(snapshot)
    assert legacy_result.verification.schema_version == STORAGE_SCHEMA_VERSION

    destination = tmp_path / "namespaced.db"
    imported = NamespacedStorage.import_legacy_snapshot(
        snapshot,
        destination,
        workspace_id="team-a",
    )

    assert imported.verification.integrity_ok is True
    assert imported.verification.schema_version == NAMESPACED_STORAGE_SCHEMA_VERSION
    assert imported.verification.storage_id != legacy_result.verification.storage_id
    assert imported.verification.source_count == 1
    assert imported.verification.observation_count == 1
    assert imported.verification.review_count == 1
    assert imported.verification.notification_candidate_count == 1
    assert imported.verification.delivery_attempt_count == 1

    team_a = NamespacedStorage(destination, "team-a")
    team_b = NamespacedStorage(destination, "team-b")
    team_a.initialize()
    team_b.initialize()

    assert team_a.get_source("a-source") is not None
    assert team_a.get_source("b-source") is None
    assert team_a.get_baseline("a-source").id == "a-obs"
    assert team_a.get_review("a-obs").state == ObservationReviewState.REVIEWED
    assert team_a.get_notification_candidate("a-candidate") is not None
    attempt = team_a.list_delivery_attempts(candidate_id="a-candidate")[0]
    assert attempt.state == DeliveryAttemptState.SUCCEEDED
    assert attempt.idempotency_key == "a-key"
    assert team_b.list_sources() == []


def test_legacy_import_never_overwrites_destination(tmp_path: Path):
    legacy = Storage(tmp_path / "legacy.db")
    legacy.initialize()
    snapshot = tmp_path / "snapshot.db"
    legacy.backup_to(snapshot)

    destination = tmp_path / "existing.db"
    destination.write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(FileExistsError):
        NamespacedStorage.import_legacy_snapshot(
            snapshot,
            destination,
            workspace_id="local",
        )
    assert destination.read_text(encoding="utf-8") == "do not overwrite"


def test_legacy_import_rejects_schema_v2_as_source(tmp_path: Path):
    namespaced_path = tmp_path / "already-v2.db"
    NamespacedStorage(namespaced_path, "local").initialize()

    with pytest.raises(ValueError, match="legacy schema-v1"):
        NamespacedStorage.import_legacy_snapshot(
            namespaced_path,
            tmp_path / "target.db",
            workspace_id="local",
        )


def test_legacy_import_rejects_corrupt_source_without_creating_target(tmp_path: Path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not a sqlite database")
    target = tmp_path / "target.db"

    with pytest.raises(ValueError, match="failed integrity verification"):
        NamespacedStorage.import_legacy_snapshot(
            corrupt,
            target,
            workspace_id="local",
        )
    assert not target.exists()
