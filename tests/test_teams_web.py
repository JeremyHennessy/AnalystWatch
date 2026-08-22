from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

from analystwatch.auth import WorkspaceRole
from analystwatch.models import (
    Finding,
    HealthStatus,
    IncidentTransition,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    SourceDefinition,
    SourceType,
)
from analystwatch.teams_delivery import TeamsWorkflowAdapter, TeamsWorkflowDestination
from analystwatch.web import create_app
from analystwatch.web_auth import required_role

NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)


def _seed(app) -> None:
    storage = app.state.workspace_storage
    source = SourceDefinition(
        id="operations",
        workspace_id="team-a",
        name="Operations Feed",
        source_type=SourceType.JSON,
        location="operations.json",
    )
    observation = Observation(
        id="obs-teams-web",
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
        id="candidate-teams-web",
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


def test_teams_web_route_delivers_with_injected_secret_backed_adapter(tmp_path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    adapter = TeamsWorkflowAdapter(
        TeamsWorkflowDestination(
            webhook_url="https://example.logic.azure.com/workflows/private-token",
            base_url="https://analystwatch.example",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    app = create_app(
        tmp_path / "state.db",
        workspace_id="team-a",
        teams_adapter=adapter,
    )
    _seed(app)
    client = TestClient(app)

    status = client.get("/api/delivery/teams/status")
    response = client.post(
        "/api/delivery-attempts/teams",
        params={
            "candidate_id": "candidate-teams-web",
            "idempotency_key": "candidate-teams-web/teams/1",
        },
    )

    assert status.status_code == 200
    assert status.json() == {"configured": True}
    assert response.status_code == 200
    assert response.json()["state"] == "Succeeded"
    assert response.json()["adapter"] == "teams-workflow"
    assert len(requests) == 1
    assert "private-token" not in response.text


def test_teams_web_route_is_fail_closed_when_not_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANALYSTWATCH_TEAMS_WORKFLOW_WEBHOOK_URL", raising=False)
    app = create_app(tmp_path / "state.db", workspace_id="team-a")
    client = TestClient(app)

    assert client.get("/api/delivery/teams/status").json() == {"configured": False}
    response = client.post(
        "/api/delivery-attempts/teams",
        params={"candidate_id": "unknown", "idempotency_key": "key"},
    )
    assert response.status_code == 409
    assert "not configured" in response.json()["detail"]


def test_teams_and_dependency_role_boundaries() -> None:
    assert required_role("GET", "/api/delivery/teams/status") == WorkspaceRole.VIEWER
    assert required_role("POST", "/api/delivery-attempts/teams") == WorkspaceRole.OPERATOR
    assert required_role("GET", "/dependencies") == WorkspaceRole.VIEWER
    assert required_role("PUT", "/api/dependencies/edges/manual") == WorkspaceRole.ADMIN
