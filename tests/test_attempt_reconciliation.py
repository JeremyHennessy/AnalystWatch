from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analystwatch.delivery import DryRunDeliveryAdapter
from analystwatch.models import (
    DeliveryAttemptState,
    DeliveryReconciliationOutcome,
    IncidentTransition,
    MonitoringConfig,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app


def _source(path: Path, *, retry_minutes: int = 0) -> SourceDefinition:
    return SourceDefinition(
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


def _healthy(path: Path) -> None:
    pd.DataFrame({"id": range(20), "value": [100] * 20}).to_csv(path, index=False)


def _eligible_candidate(service, path: Path, *, retry_minutes: int = 0):
    _healthy(path)
    service.add_source(_source(path, retry_minutes=retry_minutes))
    service.check_source("market")
    path.unlink()
    service.check_source("market")
    return service.notification_candidates("market")[0]


def test_default_zero_retry_delay_preserves_immediate_v07_retry(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    now = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    failed = service.dry_run_delivery(
        candidate.id,
        "attempt-1",
        now=now,
        adapter=DryRunDeliveryAdapter(fail_with="simulated failure"),
    )

    decision = service.delivery_retry_decision(candidate.id, now=now)
    retry = service.dry_run_delivery(candidate.id, "attempt-2", now=now)

    assert failed.state == DeliveryAttemptState.FAILED
    assert decision.due is True
    assert decision.next_retry_at == now
    assert retry.state == DeliveryAttemptState.SUCCEEDED
    assert retry.attempt_number == 2


def test_configured_retry_delay_blocks_until_independent_due_time(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path, retry_minutes=30)
    failed_at = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    service.dry_run_delivery(
        candidate.id,
        "attempt-1",
        now=failed_at,
        adapter=DryRunDeliveryAdapter(fail_with="simulated failure"),
    )

    before = service.delivery_retry_decision(candidate.id, now=failed_at + timedelta(minutes=29))
    due = service.delivery_retry_decision(candidate.id, now=failed_at + timedelta(minutes=30))

    assert before.due is False
    assert before.next_retry_at == failed_at + timedelta(minutes=30)
    assert due.due is True
    with pytest.raises(ValueError, match="not due until"):
        service.dry_run_delivery(
            candidate.id,
            "too-early",
            now=failed_at + timedelta(minutes=29),
        )
    retry = service.dry_run_delivery(
        candidate.id,
        "on-time",
        now=failed_at + timedelta(minutes=30),
    )
    assert retry.attempt_number == 2
    assert retry.state == DeliveryAttemptState.SUCCEEDED


def test_prepared_attempt_can_reconcile_failed_then_retry_after_delay(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path, retry_minutes=15)
    prepared_at = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    prepared, replayed = service.storage.claim_delivery_attempt(
        candidate.id,
        "prepared-key",
        "dry-run",
        created_at=prepared_at,
        retry_minutes=15,
    )
    assert replayed is False

    reconciled_at = prepared_at + timedelta(minutes=5)
    reconciled = service.reconcile_delivery_attempt(
        prepared.id,
        DeliveryReconciliationOutcome.FAILED,
        "Reviewed the abandoned dry-run and confirmed it did not complete.",
        now=reconciled_at,
    )

    assert reconciled.state == DeliveryAttemptState.FAILED
    assert reconciled.reconciled_at == reconciled_at
    assert reconciled.reconciliation_note.startswith("Reviewed the abandoned")
    decision = service.delivery_retry_decision(
        candidate.id,
        now=reconciled_at + timedelta(minutes=14),
    )
    assert decision.due is False
    assert decision.next_retry_at == reconciled_at + timedelta(minutes=15)
    retry = service.dry_run_delivery(
        candidate.id,
        "retry-after-review",
        now=reconciled_at + timedelta(minutes=15),
    )
    assert retry.attempt_number == 2
    assert retry.state == DeliveryAttemptState.SUCCEEDED


def test_reconcile_prepared_success_blocks_future_attempt(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    now = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    prepared, _ = service.storage.claim_delivery_attempt(
        candidate.id,
        "prepared-key",
        "dry-run",
        created_at=now,
        retry_minutes=0,
    )

    reconciled = service.reconcile_delivery_attempt(
        prepared.id,
        DeliveryReconciliationOutcome.SUCCEEDED,
        "Reviewed durable evidence and confirmed successful completion.",
        now=now + timedelta(minutes=1),
    )

    assert reconciled.state == DeliveryAttemptState.SUCCEEDED
    assert service.delivery_retry_decision(candidate.id, now=now + timedelta(hours=1)).due is False
    with pytest.raises(ValueError, match="already has a successful"):
        service.dry_run_delivery(candidate.id, "new-key", now=now + timedelta(hours=1))


def test_reconciliation_requires_prepared_state_and_review_note(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    succeeded = service.dry_run_delivery(candidate.id, "success-key")

    with pytest.raises(ValueError, match="non-empty and trimmed"):
        service.reconcile_delivery_attempt(
            succeeded.id,
            DeliveryReconciliationOutcome.FAILED,
            "",
        )
    with pytest.raises(ValueError, match="Only Prepared"):
        service.reconcile_delivery_attempt(
            succeeded.id,
            DeliveryReconciliationOutcome.FAILED,
            "Reviewed completed attempt; reconciliation must be rejected.",
        )


def test_atomic_claim_same_key_returns_one_claim_and_one_replay(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    now = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)

    def claim():
        return service.storage.claim_delivery_attempt(
            candidate.id,
            "same-key",
            "dry-run",
            created_at=now,
            retry_minutes=0,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))

    attempts = [item for item, _ in results]
    replay_flags = [replayed for _, replayed in results]
    assert attempts[0].id == attempts[1].id
    assert sorted(replay_flags) == [False, True]
    assert len(service.delivery_attempts(candidate_id=candidate.id)) == 1


def test_atomic_claim_different_keys_allows_only_one_prepared(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    now = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)

    def claim(key: str):
        try:
            attempt, replayed = service.storage.claim_delivery_attempt(
                candidate.id,
                key,
                "dry-run",
                created_at=now,
                retry_minutes=0,
            )
            return ("claimed", attempt.id, replayed)
        except ValueError as exc:
            return ("blocked", str(exc), False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["key-a", "key-b"]))

    assert sorted(item[0] for item in results) == ["blocked", "claimed"]
    assert any("Prepared dry-run" in item[1] for item in results if item[0] == "blocked")
    assert len(service.delivery_attempts(candidate_id=candidate.id)) == 1


def test_api_exposes_retry_status_and_explicit_reconciliation(tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    app = create_app(tmp_path / "web.db")
    source = _source(path, retry_minutes=10)
    app.state.service.add_source(source)
    app.state.service.check_source("market")
    path.unlink()
    app.state.service.check_source("market")
    candidate = app.state.service.notification_candidates("market")[0]
    now = datetime.now(timezone.utc)
    prepared, _ = app.state.storage.claim_delivery_attempt(
        candidate.id,
        "api-prepared",
        "dry-run",
        created_at=now,
        retry_minutes=10,
    )
    client = TestClient(app)

    status = client.get(
        "/api/delivery-attempts/retry-status",
        params={"candidate_id": candidate.id},
    )
    reconciled = client.post(
        f"/api/delivery-attempts/{prepared.id}/reconcile",
        params={
            "outcome": "Failed",
            "note": "Reviewed through the local API and confirmed incomplete.",
        },
    )

    assert status.status_code == 200
    assert status.json()["due"] is False
    assert status.json()["last_state"] == "Prepared"
    assert reconciled.status_code == 200
    assert reconciled.json()["state"] == "Failed"
    assert reconciled.json()["reconciliation_note"].startswith("Reviewed through")


def test_pages_shows_retry_policy_but_redacts_reconciliation_note(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path, retry_minutes=25)
    now = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    prepared, _ = service.storage.claim_delivery_attempt(
        candidate.id,
        "private-idempotency-key",
        "dry-run",
        created_at=now,
        retry_minutes=25,
    )
    private_note = "private reconciliation review note"
    service.reconcile_delivery_attempt(
        prepared.id,
        DeliveryReconciliationOutcome.FAILED,
        private_note,
        now=now + timedelta(minutes=1),
    )

    output = build_pages_site(service.storage, tmp_path / "site")
    detail = (output / "sources" / "market" / "index.html").read_text(encoding="utf-8")
    raw_state = (output / "state.json").read_text(encoding="utf-8")
    state = json.loads(raw_state)["sources"][0]

    assert "Notification candidates" in detail
    assert "Delivery retry delay" in detail
    assert "25 min after Failed" in detail
    assert "Core v0.6 still does not send email, Slack, webhooks" in detail
    assert "Core v0.7 dry-run attempts perform no external delivery" in detail
    assert "private-idempotency-key" not in detail
    assert "private-idempotency-key" not in raw_state
    assert private_note not in detail
    assert private_note not in raw_state
    assert state["delivery_retry_minutes"] == 25
    assert "reconcile-delivery-attempt" not in detail
