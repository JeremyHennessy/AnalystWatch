from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analystwatch.models import (
    DeliveryAttemptState,
    DeliveryReconciliationOutcome,
    HealthStatus,
    IncidentTransition,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    SourceDefinition,
    SourceType,
)
from analystwatch.reconciliation import build_delivery_reconciliation_queue

NOW = datetime(2026, 8, 22, 15, 30, tzinfo=timezone.utc)


def _prepared(service, source_id: str, created_at: datetime, *, adapter: str = "teams-workflow"):
    source = SourceDefinition(
        id=source_id,
        name=f"{source_id.title()} Feed",
        source_type=SourceType.JSON,
        location=f"{source_id}.json",
    )
    observation = Observation(
        id=f"obs-{source_id}",
        source_id=source_id,
        observed_at=created_at - timedelta(minutes=1),
        available=True,
        health=HealthStatus.CRITICAL,
    )
    candidate = NotificationCandidate(
        id=f"candidate-{source_id}",
        source_id=source_id,
        observation_id=observation.id,
        transition=IncidentTransition.OPENED,
        previous_health=HealthStatus.HEALTHY,
        current_health=HealthStatus.CRITICAL,
        created_at=created_at - timedelta(minutes=1),
        reason=f"{source.name} moved from Healthy to Critical.",
        state=NotificationCandidateState.ELIGIBLE,
        evaluated_at=created_at - timedelta(minutes=1),
        policy_enabled_transitions=[IncidentTransition.OPENED],
        policy_reason="Opened notifications enabled.",
    )
    service.storage.upsert_source(source)
    service.storage.save_observation(observation, notification_candidate=candidate)
    attempt, replayed = service.storage.claim_delivery_attempt(
        candidate.id,
        f"private-{source_id}-key",
        adapter,
        created_at=created_at,
        retry_minutes=0,
        claim_owner="test-worker",
    )
    assert replayed is False
    return attempt


def test_reconciliation_queue_surfaces_only_prepared_and_marks_stale(service) -> None:
    old = _prepared(service, "orders", NOW - timedelta(minutes=45))
    fresh = _prepared(service, "forecast", NOW - timedelta(minutes=5))
    completed = _prepared(service, "treasury", NOW - timedelta(minutes=60), adapter="resend")
    service.reconcile_delivery_attempt(
        completed.id,
        DeliveryReconciliationOutcome.SUCCEEDED,
        "Provider audit log confirms the message was accepted.",
        now=NOW - timedelta(minutes=55),
    )

    queue = build_delivery_reconciliation_queue(
        service.storage,
        now=NOW,
        stale_after_minutes=30,
    )

    assert queue.prepared_count == 2
    assert queue.stale_count == 1
    assert [item.attempt_id for item in queue.items] == [old.id, fresh.id]
    assert queue.items[0].age_minutes == 45
    assert queue.items[0].stale is True
    assert queue.items[0].source_name == "Orders Feed"
    assert queue.items[0].transition == IncidentTransition.OPENED
    assert queue.items[0].current_health == HealthStatus.CRITICAL
    assert queue.items[1].age_minutes == 5
    assert queue.items[1].stale is False


def test_reconciliation_queue_is_safe_and_does_not_expose_claim_secrets(service) -> None:
    _prepared(service, "orders", NOW - timedelta(minutes=30))

    queue = build_delivery_reconciliation_queue(service.storage, now=NOW)
    serialized = queue.model_dump_json()

    assert queue.items[0].stale is True
    assert "private-orders-key" not in serialized
    assert "idempotency_key" not in serialized
    assert "test-worker" not in serialized
    assert "claim_owner" not in serialized
    assert "result_summary" not in serialized
    assert "error" not in serialized


def test_reconciled_attempt_leaves_queue_without_creating_retry(service) -> None:
    prepared = _prepared(service, "orders", NOW - timedelta(minutes=40))
    before = build_delivery_reconciliation_queue(service.storage, now=NOW)

    reconciled = service.reconcile_delivery_attempt(
        prepared.id,
        DeliveryReconciliationOutcome.FAILED,
        "Provider logs confirm no Teams delivery was accepted.",
        now=NOW,
    )
    after = build_delivery_reconciliation_queue(service.storage, now=NOW)

    assert before.prepared_count == 1
    assert reconciled.state == DeliveryAttemptState.FAILED
    assert after.prepared_count == 0
    assert after.items == []
    assert len(service.delivery_attempts(candidate_id=prepared.candidate_id)) == 1


def test_reconciliation_queue_reports_output_limit_and_scan_cap_separately(service) -> None:
    _prepared(service, "orders", NOW - timedelta(minutes=50))
    _prepared(service, "forecast", NOW - timedelta(minutes=40))

    limited = build_delivery_reconciliation_queue(service.storage, now=NOW, limit=1)
    capped = build_delivery_reconciliation_queue(service.storage, now=NOW, scan_limit=1)

    assert limited.prepared_count == 2
    assert len(limited.items) == 1
    assert limited.scan_limit_reached is False
    assert capped.scan_limit_reached is True


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("stale_after_minutes", 0, "stale_after_minutes"),
        ("limit", 0, "limit"),
        ("scan_limit", 0, "scan_limit"),
    ],
)
def test_reconciliation_queue_rejects_invalid_limits(service, argument, value, message) -> None:
    kwargs = {argument: value}
    with pytest.raises(ValueError, match=message):
        build_delivery_reconciliation_queue(service.storage, now=NOW, **kwargs)
