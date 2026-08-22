from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from analystwatch.delivery import DryRunDeliveryAdapter
from analystwatch.memory_store import MemoryStore
from analystwatch.models import (
    DeliveryAttemptState,
    DeliveryReconciliationOutcome,
    IncidentTransition,
    MonitoringConfig,
    ObservationReviewState,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.postgres_storage import PostgresStorage
from analystwatch.storage import Storage
from analystwatch.store import MonitoringStore
from analystwatch.workspace import create_workspace_service


@pytest.fixture(params=["sqlite", "memory", "postgres"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[MonitoringStore]:
    if request.param == "sqlite":
        yield Storage(tmp_path / "state.db")
        return
    if request.param == "memory":
        yield MemoryStore()
        return

    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    postgres = PostgresStorage(dsn, "local")
    postgres.initialize()
    postgres.clear_workspace()
    try:
        yield postgres
    finally:
        postgres.clear_workspace()


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": list(range(1, 101)),
            "amount": [8000 + (index % 17) for index in range(100)],
            "segment": ["A" if index % 2 else "B" for index in range(100)],
        }
    )


def _service(
    store: MonitoringStore,
    tmp_path: Path,
    *,
    retry_minutes: int = 0,
):
    path = tmp_path / "market.csv"
    _frame().to_csv(path, index=False)
    service = create_workspace_service(store, "local", execution_owner="worker-a")
    service.add_source(
        SourceDefinition(
            id="market",
            name="Market",
            source_type=SourceType.CSV,
            location=str(path),
            config=MonitoringConfig(
                unique_keys=["id"],
                notification_transitions=[IncidentTransition.OPENED],
                delivery_retry_minutes=retry_minutes,
            ),
        )
    )
    return service, path


def _eligible_candidate(
    store: MonitoringStore,
    tmp_path: Path,
    *,
    retry_minutes: int = 0,
):
    service, path = _service(store, tmp_path, retry_minutes=retry_minutes)
    started = datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)
    service.check_source("market", now=started)
    changed = _frame()
    changed["amount"] = changed["amount"] / 100
    changed.to_csv(path, index=False)
    observation = service.check_source("market", now=started + timedelta(minutes=1))
    candidates = service.notification_candidates("market")
    assert observation.health.value == "Critical"
    assert len(candidates) == 1
    assert candidates[0].state.value == "Eligible"
    return service, path, candidates[0], started


def test_store_implements_monitoring_protocol(store: MonitoringStore) -> None:
    assert isinstance(store, MonitoringStore)


def test_baseline_and_history_contract(store: MonitoringStore, tmp_path: Path) -> None:
    service, _ = _service(store, tmp_path)
    observed_at = datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)

    observation = service.check_source("market", now=observed_at)
    baseline = service.storage.get_baseline("market")
    history = service.storage.list_observations("market")

    assert observation.health.value == "Healthy"
    assert baseline is not None
    assert baseline.id == observation.id
    assert baseline.is_baseline is True
    assert [item.id for item in history] == [observation.id]


def test_incident_candidate_contract(store: MonitoringStore, tmp_path: Path) -> None:
    service, _, candidate, _ = _eligible_candidate(store, tmp_path)
    incident = service.incident("market")

    assert incident is not None
    assert incident.status.value == "Open"
    assert incident.current_health.value == "Critical"
    assert candidate.transition.value == "Opened"
    assert candidate.state.value == "Eligible"


def test_idempotent_attempt_contract(store: MonitoringStore, tmp_path: Path) -> None:
    service, _, candidate, started = _eligible_candidate(store, tmp_path)
    attempted_at = started + timedelta(minutes=2)

    first = service.dry_run_delivery(candidate.id, "stable-key", now=attempted_at)
    replay = service.dry_run_delivery(candidate.id, "stable-key", now=attempted_at)

    assert first.state == DeliveryAttemptState.SUCCEEDED
    assert replay.id == first.id
    assert replay.idempotency_key == "stable-key"
    assert replay.claim_owner == "worker-a"
    assert len(service.delivery_attempts(candidate_id=candidate.id)) == 1


def test_retry_timing_contract(store: MonitoringStore, tmp_path: Path) -> None:
    service, _, candidate, started = _eligible_candidate(store, tmp_path, retry_minutes=30)
    attempted_at = started + timedelta(minutes=2)

    failed = service.dry_run_delivery(
        candidate.id,
        "failed-key",
        now=attempted_at,
        adapter=DryRunDeliveryAdapter(fail_with="synthetic failure"),
    )
    assert failed.state == DeliveryAttemptState.FAILED

    with pytest.raises(ValueError, match="not due"):
        service.dry_run_delivery(
            candidate.id,
            "early-key",
            now=attempted_at + timedelta(minutes=29),
        )

    retried = service.dry_run_delivery(
        candidate.id,
        "retry-key",
        now=attempted_at + timedelta(minutes=30),
    )
    assert retried.state == DeliveryAttemptState.SUCCEEDED
    assert retried.attempt_number == 2


def test_prepared_reconciliation_contract(store: MonitoringStore, tmp_path: Path) -> None:
    service, _, candidate, started = _eligible_candidate(store, tmp_path)
    prepared_at = started + timedelta(minutes=2)
    prepared, replayed = service.storage.claim_delivery_attempt(
        candidate.id,
        "prepared-key",
        "dry-run",
        created_at=prepared_at,
        retry_minutes=0,
        claim_owner="worker-a",
    )

    assert replayed is False
    assert prepared.state == DeliveryAttemptState.PREPARED

    reconciled = service.reconcile_delivery_attempt(
        prepared.id,
        DeliveryReconciliationOutcome.FAILED,
        "Reviewed local dry-run evidence.",
        now=prepared_at + timedelta(minutes=5),
        reviewer="reviewer-b",
    )
    assert reconciled.state == DeliveryAttemptState.FAILED
    assert reconciled.reconciled_by == "reviewer-b"
    assert reconciled.reconciliation_note == "Reviewed local dry-run evidence."


def test_review_and_baseline_promotion_contract(store: MonitoringStore, tmp_path: Path) -> None:
    service, path, _, started = _eligible_candidate(store, tmp_path)
    critical = service.storage.get_latest("market")
    assert critical is not None

    review = service.review_observation(
        "market",
        critical.id,
        ObservationReviewState.REVIEWED,
        now=started + timedelta(minutes=2),
    )
    assert service.storage.get_review(critical.id) == review

    _frame().to_csv(path, index=False)
    recovered = service.check_source("market", now=started + timedelta(minutes=3))
    current_baseline = service.storage.get_baseline("market")
    assert recovered.health.value == "Healthy"
    assert current_baseline is not None

    baseline_review = service.baseline_review("market", recovered.id)
    assert baseline_review.ready is True
    promoted = service.promote_baseline_after_review(
        "market",
        recovered.id,
        current_baseline.id,
    )
    assert promoted.id == recovered.id
    assert service.storage.get_baseline("market").id == recovered.id  # type: ignore[union-attr]


def test_pages_contract(store: MonitoringStore, tmp_path: Path) -> None:
    service, _ = _service(store, tmp_path)
    service.check_source(
        "market",
        now=datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc),
    )

    output = build_pages_site(service.storage, tmp_path / "site")
    public_state = json.loads((output / "state.json").read_text(encoding="utf-8"))

    assert (output / "index.html").exists()
    assert (output / "sources" / "market" / "index.html").exists()
    assert [item["id"] for item in public_state["sources"]] == ["market"]
