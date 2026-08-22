from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from analystwatch.cli import main as cli_main
from analystwatch.models import (
    DatasetProfile,
    DeliveryAttempt,
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
from analystwatch.namespaced_storage import NamespacedStorage
from analystwatch.postgres_storage import PostgresStorage
from analystwatch.runtime_storage import create_runtime_storage, verify_runtime_database
from analystwatch.web import create_app

NOW = datetime(2026, 8, 22, 0, 30, tzinfo=timezone.utc)


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    return dsn


def _workspace(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _source(workspace_id: str, source_id: str = "shared") -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        workspace_id=workspace_id,
        name=f"Source {workspace_id}",
        source_type=SourceType.CSV,
        location=f"{workspace_id}.csv",
    )


def _observation(
    source_id: str,
    observation_id: str,
    health: HealthStatus = HealthStatus.HEALTHY,
) -> Observation:
    return Observation(
        id=observation_id,
        source_id=source_id,
        observed_at=NOW,
        available=True,
        health=health,
        profile=DatasetProfile(row_count=10, column_count=1, columns={}),
    )


def _candidate(
    source_id: str,
    observation_id: str,
    candidate_id: str = "candidate",
) -> NotificationCandidate:
    return NotificationCandidate(
        id=candidate_id,
        source_id=source_id,
        observation_id=observation_id,
        transition=IncidentTransition.OPENED,
        current_health=HealthStatus.CRITICAL,
        created_at=NOW,
        reason="PostgreSQL persistence test",
        state=NotificationCandidateState.ELIGIBLE,
        evaluated_at=NOW,
        policy_enabled_transitions=[IncidentTransition.OPENED],
        policy_reason="Enabled for PostgreSQL test",
    )


def _populate_candidate(store: PostgresStorage, source_id: str = "shared") -> None:
    store.initialize()
    store.upsert_source(_source(store.workspace_id, source_id))
    observation = _observation(source_id, "obs", HealthStatus.CRITICAL)
    store.save_observation(
        observation,
        notification_candidate=_candidate(source_id, observation.id),
    )


def _populate_namespaced_operational_state(path: Path, workspace_id: str) -> NamespacedStorage:
    store = NamespacedStorage(path, workspace_id)
    store.initialize()
    source = _source(workspace_id, "market")
    store.upsert_source(source)

    baseline = _observation("market", "baseline", HealthStatus.HEALTHY)
    store.save_observation(baseline, set_baseline=True)

    critical = _observation("market", "critical", HealthStatus.CRITICAL)
    candidate = _candidate("market", critical.id, "opened")
    store.save_observation(critical, notification_candidate=candidate)
    store.save_review(
        ObservationReview(
            observation_id=critical.id,
            source_id="market",
            state=ObservationReviewState.REVIEWED,
            updated_at=NOW,
        )
    )
    prepared, replayed = store.claim_delivery_attempt(
        candidate.id,
        "migration-key",
        "dry-run",
        created_at=NOW,
        retry_minutes=0,
        claim_owner="migration-worker",
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
    return store


def test_postgres_runtime_requires_explicit_dsn(tmp_path: Path):
    with pytest.raises(ValueError, match="requires ANALYSTWATCH_POSTGRES_DSN"):
        create_runtime_storage(tmp_path / "unused.db", "local", "postgres")


def test_postgres_runtime_initializes_and_verifies(postgres_dsn: str, tmp_path: Path):
    workspace = _workspace("runtime")
    runtime = create_runtime_storage(
        tmp_path / "unused.db",
        workspace,
        "postgres",
        postgres_dsn=postgres_dsn,
    )
    assert runtime.backend == "postgres"
    store = runtime.raw_storage
    assert isinstance(store, PostgresStorage)
    store.initialize()
    store.clear_workspace()
    try:
        store.upsert_source(_source(workspace, "runtime-source"))
        verification = verify_runtime_database(
            tmp_path / "unused.db",
            "postgres",
            postgres_dsn=postgres_dsn,
        )
        assert verification.integrity_ok is True
        assert verification.storage_id is not None
    finally:
        store.clear_workspace()


def test_postgres_same_ids_and_idempotency_are_workspace_scoped(postgres_dsn: str):
    workspace_a = _workspace("a")
    workspace_b = _workspace("b")
    team_a = PostgresStorage(postgres_dsn, workspace_a)
    team_b = PostgresStorage(postgres_dsn, workspace_b)
    team_a.initialize()
    team_b.initialize()
    team_a.clear_workspace()
    team_b.clear_workspace()
    try:
        _populate_candidate(team_a)
        _populate_candidate(team_b)
        attempt_a, replay_a = team_a.claim_delivery_attempt(
            "candidate",
            "same-key",
            "dry-run",
            created_at=NOW,
            retry_minutes=0,
        )
        attempt_b, replay_b = team_b.claim_delivery_attempt(
            "candidate",
            "same-key",
            "dry-run",
            created_at=NOW,
            retry_minutes=0,
        )
        assert replay_a is replay_b is False
        assert attempt_a.id == attempt_b.id == "candidate:dry-run:1"
        assert team_a.get_source("shared").workspace_id == workspace_a  # type: ignore[union-attr]
        assert team_b.get_source("shared").workspace_id == workspace_b  # type: ignore[union-attr]
    finally:
        team_a.clear_workspace()
        team_b.clear_workspace()


def test_postgres_candidate_lock_serializes_concurrent_claims(postgres_dsn: str):
    workspace = _workspace("claim")
    seed = PostgresStorage(postgres_dsn, workspace)
    seed.initialize()
    seed.clear_workspace()
    _populate_candidate(seed)
    barrier = Barrier(2)

    def claim(key: str) -> DeliveryAttempt:
        store = PostgresStorage(postgres_dsn, workspace)
        barrier.wait()
        attempt, replayed = store.claim_delivery_attempt(
            "candidate",
            key,
            "dry-run",
            created_at=NOW,
            retry_minutes=0,
        )
        assert replayed is False
        return attempt

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(claim, "key-a"), executor.submit(claim, "key-b")]
            successes: list[DeliveryAttempt] = []
            failures: list[Exception] = []
            for future in futures:
                try:
                    successes.append(future.result())
                except Exception as exc:  # noqa: BLE001 - assert concurrency outcome
                    failures.append(exc)
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], ValueError)
        assert "Prepared" in str(failures[0])
        assert len(seed.list_delivery_attempts(candidate_id="candidate")) == 1
    finally:
        seed.clear_workspace()


def test_namespaced_to_postgres_import_preserves_operational_state(
    postgres_dsn: str,
    tmp_path: Path,
):
    workspace = _workspace("migrate")
    source = _populate_namespaced_operational_state(tmp_path / "source.db", workspace)
    destination = PostgresStorage(postgres_dsn, workspace)
    destination.initialize()
    destination.clear_workspace()
    try:
        destination.import_workspace(source)
        assert destination.get_source("market") is not None
        assert destination.get_baseline("market").id == "baseline"  # type: ignore[union-attr]
        assert destination.get_review("critical").state == ObservationReviewState.REVIEWED  # type: ignore[union-attr]
        assert destination.get_notification_candidate("opened") is not None
        attempts = destination.list_delivery_attempts(candidate_id="opened")
        assert len(attempts) == 1
        assert attempts[0].state == DeliveryAttemptState.SUCCEEDED
        assert attempts[0].idempotency_key == "migration-key"

        with pytest.raises(ValueError, match="must be empty"):
            destination.import_workspace(source)
    finally:
        destination.clear_workspace()


def test_postgres_fastapi_and_cli_cutover_rehearsal(
    postgres_dsn: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    workspace = _workspace("app")
    source_path = tmp_path / "namespaced.db"
    _populate_namespaced_operational_state(source_path, workspace)
    destination = PostgresStorage(postgres_dsn, workspace)
    destination.initialize()
    destination.clear_workspace()
    try:
        assert (
            cli_main(
                [
                    "--db",
                    str(source_path),
                    "--workspace-id",
                    workspace,
                    "--storage-backend",
                    "postgres",
                    "--postgres-dsn",
                    postgres_dsn,
                    "import-postgres-state",
                ]
            )
            == 0
        )
        output = json.loads(capsys.readouterr().out)
        assert output["integrity_ok"] is True

        app = create_app(
            tmp_path / "unused.db",
            workspace_id=workspace,
            storage_backend="postgres",
            postgres_dsn=postgres_dsn,
        )
        assert app.state.storage_backend == "postgres"
        client = TestClient(app)
        response = client.get("/api/sources/market")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["history"]) == 2
        assert payload["notification_candidate_count"] == 1
        assert payload["delivery_attempt_count"] == 1
    finally:
        destination.clear_workspace()
