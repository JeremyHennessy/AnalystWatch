from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analystwatch.delivery import DryRunDeliveryAdapter
from analystwatch.models import (
    DeliveryAttempt,
    DeliveryAttemptState,
    DeliveryMode,
    IncidentTransition,
    MonitoringConfig,
    NotificationCandidateState,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app


def _source(
    path: Path,
    *,
    source_id: str = "market",
    transitions: list[IncidentTransition] | None = None,
) -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        name=source_id.title(),
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            unique_keys=["id"],
            notification_transitions=(
                [IncidentTransition.OPENED] if transitions is None else transitions
            ),
        ),
    )


def _healthy(path: Path, count: int = 20) -> None:
    pd.DataFrame({"id": range(count), "value": [100] * count}).to_csv(path, index=False)


def _eligible_candidate(service, path: Path):
    _healthy(path)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()
    service.check_source("market")
    candidate = service.notification_candidates("market")[0]
    assert candidate.state == NotificationCandidateState.ELIGIBLE
    return candidate


def test_eligible_candidate_dry_run_succeeds_without_changing_candidate(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    now = datetime(2026, 8, 21, 19, 20, tzinfo=timezone.utc)

    attempt = service.dry_run_delivery(candidate.id, "market-opened-1", now=now)

    assert attempt.state == DeliveryAttemptState.SUCCEEDED
    assert attempt.mode == DeliveryMode.DRY_RUN
    assert attempt.adapter == "dry-run"
    assert attempt.attempt_number == 1
    assert attempt.created_at == now
    assert attempt.completed_at == now
    assert "no external delivery was attempted" in (attempt.result_summary or "")
    assert service.notification_candidates("market")[0].state == NotificationCandidateState.ELIGIBLE
    assert service.delivery_attempts(candidate_id=candidate.id) == [attempt]


def test_suppressed_candidate_cannot_be_dry_run_attempted(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    service.add_source(_source(path, transitions=[]))
    service.check_source("market")
    path.unlink()
    service.check_source("market")
    candidate = service.notification_candidates("market")[0]

    assert candidate.state == NotificationCandidateState.SUPPRESSED
    with pytest.raises(ValueError, match="Only Eligible"):
        service.dry_run_delivery(candidate.id, "suppressed-1")
    assert service.delivery_attempts(candidate_id=candidate.id) == []


class CountingDryRunAdapter(DryRunDeliveryAdapter):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def deliver(self, candidate):
        self.calls += 1
        return super().deliver(candidate)


def test_same_idempotency_key_replays_without_rerunning_adapter(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    adapter = CountingDryRunAdapter()

    first = service.dry_run_delivery(candidate.id, "stable-key", adapter=adapter)
    second = service.dry_run_delivery(candidate.id, "stable-key", adapter=adapter)

    assert first == second
    assert adapter.calls == 1
    assert len(service.delivery_attempts(candidate_id=candidate.id)) == 1


def test_success_blocks_new_idempotency_key_for_same_candidate(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    service.dry_run_delivery(candidate.id, "first-key")

    with pytest.raises(ValueError, match="already has a successful"):
        service.dry_run_delivery(candidate.id, "second-key")
    assert len(service.delivery_attempts(candidate_id=candidate.id)) == 1


def test_failed_attempt_replays_same_key_and_new_key_retries(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    failed = service.dry_run_delivery(
        candidate.id,
        "attempt-1",
        adapter=DryRunDeliveryAdapter(fail_with="simulated dry-run failure"),
    )

    replay = service.dry_run_delivery(candidate.id, "attempt-1")
    retry = service.dry_run_delivery(candidate.id, "attempt-2")

    assert failed.state == DeliveryAttemptState.FAILED
    assert failed.error == "simulated dry-run failure"
    assert replay == failed
    assert retry.state == DeliveryAttemptState.SUCCEEDED
    assert retry.attempt_number == 2
    attempts = service.delivery_attempts(candidate_id=candidate.id)
    assert {item.attempt_number for item in attempts} == {1, 2}


def test_prepared_attempt_blocks_new_retry_until_resolved(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    prepared = DeliveryAttempt(
        id=f"{candidate.id}:dry-run:1",
        candidate_id=candidate.id,
        source_id=candidate.source_id,
        adapter="dry-run",
        mode=DeliveryMode.DRY_RUN,
        idempotency_key="prepared-key",
        attempt_number=1,
        state=DeliveryAttemptState.PREPARED,
        created_at=datetime.now(timezone.utc),
    )
    service.storage.create_delivery_attempt(prepared)

    replay = service.dry_run_delivery(candidate.id, "prepared-key")
    assert replay == prepared
    with pytest.raises(ValueError, match="Prepared dry-run"):
        service.dry_run_delivery(candidate.id, "new-key")


def test_dry_run_api_is_idempotent_and_has_no_generic_send_route(tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    app = create_app(tmp_path / "web.db")
    app.state.service.add_source(_source(path))
    app.state.service.check_source("market")
    path.unlink()
    app.state.service.check_source("market")
    candidate = app.state.service.notification_candidates("market")[0]
    client = TestClient(app)

    first = client.post(
        "/api/delivery-attempts/dry-run",
        params={"candidate_id": candidate.id, "idempotency_key": "api-key"},
    )
    second = client.post(
        "/api/delivery-attempts/dry-run",
        params={"candidate_id": candidate.id, "idempotency_key": "api-key"},
    )
    listing = client.get("/api/delivery-attempts", params={"candidate_id": candidate.id})
    routes = {route.path for route in app.routes}

    assert first.status_code == 200
    assert first.json()["state"] == "Succeeded"
    assert second.json()["id"] == first.json()["id"]
    assert len(listing.json()) == 1
    assert "/api/delivery-attempts/dry-run" in routes
    assert all("/send" not in route for route in routes)


def test_pages_exposes_only_dry_run_attempt_summary(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    candidate = _eligible_candidate(service, path)
    service.dry_run_delivery(candidate.id, "private-idempotency-key")

    output = build_pages_site(service.storage, tmp_path / "site")
    detail = (output / "sources" / "market" / "index.html").read_text(encoding="utf-8")
    raw_state = (output / "state.json").read_text(encoding="utf-8")
    state = json.loads(raw_state)["sources"][0]

    assert "Notification candidates" in detail
    assert "Dry-run attempts: 1 total" in detail
    assert "1 Succeeded" in detail
    assert "no external delivery or network request" in detail
    assert "private-idempotency-key" not in detail
    assert "private-idempotency-key" not in raw_state
    assert state["delivery_attempt_count"] == 1
    assert state["delivery_attempt_states"]["Succeeded"] == 1
    assert "Send notification" not in detail
