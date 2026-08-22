from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from analystwatch.email_delivery import (
    EmailDestination,
    ResendEmailAdapter,
    deliver_email_candidate,
)
from analystwatch.models import (
    DeliveryAttemptState,
    DeliveryMode,
    Finding,
    HealthStatus,
    IncidentTransition,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    SourceDefinition,
    SourceType,
)
from analystwatch.storage import Storage

NOW = datetime(2026, 8, 22, 1, 45, tzinfo=timezone.utc)


def _seed(storage: Storage) -> NotificationCandidate:
    storage.initialize()
    source = SourceDefinition(
        id="finance",
        workspace_id="team-a",
        name="Finance Extract",
        source_type=SourceType.CSV,
        location="finance.csv",
    )
    observation = Observation(
        id="obs-1",
        source_id=source.id,
        observed_at=NOW,
        available=True,
        health=HealthStatus.CRITICAL,
        findings=[
            Finding(
                severity=HealthStatus.CRITICAL,
                detector="row_count",
                description="Row count fell by 42%.",
                current_value=580,
                baseline_value=1000,
                why_flagged="Exceeded critical row-count threshold.",
                likely_impact="Reporting totals may be incomplete.",
                suggested_investigation="Inspect the upstream extract filters.",
            )
        ],
    )
    candidate = NotificationCandidate(
        id="candidate-1",
        source_id=source.id,
        observation_id=observation.id,
        transition=IncidentTransition.OPENED,
        previous_health=HealthStatus.HEALTHY,
        current_health=HealthStatus.CRITICAL,
        created_at=NOW,
        reason="Finance Extract moved from Healthy to Critical.",
        state=NotificationCandidateState.ELIGIBLE,
        evaluated_at=NOW,
        policy_enabled_transitions=[IncidentTransition.OPENED],
        policy_reason="Opened notifications enabled.",
    )
    storage.upsert_source(source)
    storage.save_observation(observation, notification_candidate=candidate)
    return candidate


def _destination() -> EmailDestination:
    return EmailDestination(
        from_address="AnalystWatch <alerts@example.com>",
        to_addresses=("analyst@example.com",),
        base_url="https://analystwatch.example",
    )


def test_resend_live_delivery_preserves_attempt_contract_and_content(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "email-123"})

    adapter = ResendEmailAdapter(
        "re_test_secret",
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    attempt = deliver_email_candidate(
        storage,
        "candidate-1",
        "candidate-1/email/1",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert attempt.state == DeliveryAttemptState.SUCCEEDED
    assert attempt.mode == DeliveryMode.LIVE
    assert attempt.adapter == "resend-email"
    assert attempt.result_summary == "Resend accepted email email-123."
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["idempotency-key"] == "candidate-1/email/1"
    assert request.headers["authorization"] == "Bearer re_test_secret"
    body = request.content.decode()
    assert "Finance Extract" in body
    assert "team-a" in body
    assert "Row count fell by 42%." in body
    assert "Reporting totals may be incomplete." in body
    assert "Inspect the upstream extract filters." in body
    assert "https://analystwatch.example/sources/finance" in body
    assert "re_test_secret" not in body


def test_same_idempotency_key_replays_without_second_external_send(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": "email-123"})

    adapter = ResendEmailAdapter(
        "re_test_secret",
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = deliver_email_candidate(
        storage,
        "candidate-1",
        "stable-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )
    replay = deliver_email_candidate(
        storage,
        "candidate-1",
        "stable-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert first.id == replay.id
    assert replay.state == DeliveryAttemptState.SUCCEEDED
    assert calls == 1


def test_transport_uncertainty_keeps_attempt_prepared_for_reconciliation(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider response timed out", request=request)

    adapter = ResendEmailAdapter(
        "re_test_secret",
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    attempt = deliver_email_candidate(
        storage,
        "candidate-1",
        "uncertain-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert attempt.state == DeliveryAttemptState.PREPARED
    assert attempt.mode == DeliveryMode.LIVE
    persisted = storage.get_delivery_attempt(attempt.id)
    assert persisted is not None
    assert persisted.state == DeliveryAttemptState.PREPARED
    assert persisted.mode == DeliveryMode.LIVE


def test_definitive_provider_rejection_records_failed_attempt(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "bad"})

    adapter = ResendEmailAdapter(
        "re_test_secret",
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(reject)),
    )
    attempt = deliver_email_candidate(
        storage,
        "candidate-1",
        "rejected-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert attempt.state == DeliveryAttemptState.FAILED
    assert attempt.mode == DeliveryMode.LIVE
    assert attempt.error == "Resend rejected email with HTTP 422"
    assert "re_test_secret" not in attempt.error
