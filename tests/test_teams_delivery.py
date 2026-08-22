from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

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
from analystwatch.teams_delivery import (
    TeamsWorkflowAdapter,
    TeamsWorkflowDestination,
    deliver_teams_candidate,
)

NOW = datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)


def _seed(storage: Storage) -> None:
    storage.initialize()
    source = SourceDefinition(
        id="operations",
        workspace_id="team-a",
        name="Operations Feed",
        source_type=SourceType.JSON,
        location="operations.json",
    )
    observation = Observation(
        id="obs-teams",
        source_id=source.id,
        observed_at=NOW,
        available=True,
        health=HealthStatus.CRITICAL,
        findings=[
            Finding(
                severity=HealthStatus.CRITICAL,
                detector="unique_keys",
                description="Duplicate order IDs were detected.",
                current_value=4,
                baseline_value=0,
                why_flagged="Configured order_id key is no longer unique.",
                likely_impact="Orders may be double counted.",
                suggested_investigation="Inspect the export join and duplicate rows.",
            )
        ],
    )
    candidate = NotificationCandidate(
        id="candidate-teams",
        source_id=source.id,
        observation_id=observation.id,
        transition=IncidentTransition.OPENED,
        previous_health=HealthStatus.HEALTHY,
        current_health=HealthStatus.CRITICAL,
        created_at=NOW,
        reason="Operations Feed moved from Healthy to Critical.",
        state=NotificationCandidateState.ELIGIBLE,
        evaluated_at=NOW,
        policy_enabled_transitions=[IncidentTransition.OPENED],
        policy_reason="Opened notifications enabled.",
    )
    storage.upsert_source(source)
    storage.save_observation(observation, notification_candidate=candidate)


def _destination() -> TeamsWorkflowDestination:
    return TeamsWorkflowDestination(
        webhook_url="https://example.logic.azure.com/workflows/private-token",
        base_url="https://analystwatch.example",
    )


def test_teams_workflow_delivery_uses_adaptive_card_and_existing_attempt_contract(
    tmp_path: Path,
) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    adapter = TeamsWorkflowAdapter(
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    attempt = deliver_teams_candidate(
        storage,
        "candidate-teams",
        "candidate-teams/teams/1",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert attempt.state == DeliveryAttemptState.SUCCEEDED
    assert attempt.mode == DeliveryMode.LIVE
    assert attempt.adapter == "teams-workflow"
    assert attempt.result_summary == "Microsoft Teams Workflows accepted the alert."
    assert len(requests) == 1
    body = requests[0].content.decode()
    assert '"type":"message"' in body
    assert "application/vnd.microsoft.card.adaptive" in body
    assert "Operations Feed" in body
    assert "Duplicate order IDs were detected." in body
    assert "https://analystwatch.example/sources/operations" in body
    assert "private-token" not in body


def test_teams_same_idempotency_key_replays_without_second_post(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(202)

    adapter = TeamsWorkflowAdapter(
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = deliver_teams_candidate(
        storage,
        "candidate-teams",
        "stable-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )
    replay = deliver_teams_candidate(
        storage,
        "candidate-teams",
        "stable-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert replay.id == first.id
    assert replay.state == DeliveryAttemptState.SUCCEEDED
    assert calls == 1


def test_teams_transport_uncertainty_stays_prepared(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("workflow response timed out", request=request)

    adapter = TeamsWorkflowAdapter(
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    attempt = deliver_teams_candidate(
        storage,
        "candidate-teams",
        "uncertain-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert attempt.state == DeliveryAttemptState.PREPARED
    assert attempt.mode == DeliveryMode.LIVE
    assert attempt.error is None


def test_teams_definitive_rejection_is_failed_and_redacts_webhook(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    _seed(storage)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="private provider body")

    adapter = TeamsWorkflowAdapter(
        _destination(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    attempt = deliver_teams_candidate(
        storage,
        "candidate-teams",
        "rejected-key",
        adapter,
        created_at=NOW,
        claim_owner="test-runner",
    )

    assert attempt.state == DeliveryAttemptState.FAILED
    assert attempt.error == "Teams Workflows webhook rejected message with HTTP 400"
    assert "private-token" not in attempt.error
    assert "private provider body" not in attempt.error
