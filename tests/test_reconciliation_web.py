from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from analystwatch.auth import SignedSessionAuthenticator, WorkspaceMembership, WorkspaceRole
from analystwatch.auth_storage import SQLiteMembershipStore
from analystwatch.models import (
    HealthStatus,
    IncidentTransition,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app
from analystwatch.web_auth import required_role

NOW = datetime(2026, 8, 22, 15, 30, tzinfo=timezone.utc)
SECRET = "analystwatch-reconciliation-secret-32-bytes"


def _seed_prepared(app, *, workspace_id: str = "local"):
    storage = app.state.workspace_storage
    source = SourceDefinition(
        id="orders",
        workspace_id=workspace_id,
        name="Orders Feed",
        source_type=SourceType.JSON,
        location="orders.json",
    )
    observation = Observation(
        id="obs-orders",
        source_id=source.id,
        observed_at=NOW - timedelta(minutes=61),
        available=True,
        health=HealthStatus.CRITICAL,
    )
    candidate = NotificationCandidate(
        id="candidate-orders",
        source_id=source.id,
        observation_id=observation.id,
        transition=IncidentTransition.OPENED,
        previous_health=HealthStatus.HEALTHY,
        current_health=HealthStatus.CRITICAL,
        created_at=NOW - timedelta(minutes=61),
        reason="Orders Feed moved from Healthy to Critical.",
        state=NotificationCandidateState.ELIGIBLE,
        evaluated_at=NOW - timedelta(minutes=61),
        policy_enabled_transitions=[IncidentTransition.OPENED],
        policy_reason="Opened notifications enabled.",
    )
    storage.upsert_source(source)
    storage.save_observation(observation, notification_candidate=candidate)
    attempt, replayed = storage.claim_delivery_attempt(
        candidate.id,
        "private-orders-key",
        "teams-workflow",
        created_at=NOW - timedelta(minutes=60),
        retry_minutes=0,
        claim_owner="delivery-worker",
    )
    assert replayed is False
    return attempt


def _authorization(user_id: str) -> dict[str, str]:
    token = SignedSessionAuthenticator(SECRET).issue_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _secured_operator_app(tmp_path: Path):
    memberships = SQLiteMembershipStore(tmp_path / "memberships.db")
    memberships.initialize()
    memberships.upsert_membership(
        WorkspaceMembership(
            workspace_id="team-a",
            user_id="operator",
            role=WorkspaceRole.OPERATOR,
        )
    )
    return create_app(
        tmp_path / "state.db",
        workspace_id="team-a",
        auth_mode="signed-bearer",
        auth_secret=SECRET,
        membership_store=memberships,
    )


def test_reconciliation_api_and_page_expose_bounded_prepared_context(tmp_path: Path) -> None:
    app = create_app(tmp_path / "state.db")
    attempt = _seed_prepared(app)
    client = TestClient(app)

    api = client.get(
        "/api/delivery-reconciliation",
        params={"stale_after_minutes": 30},
    )
    page = client.get("/reconciliation", params={"stale_after_minutes": 30})

    assert api.status_code == 200
    payload = api.json()
    assert payload["prepared_count"] == 1
    assert payload["stale_count"] == 1
    assert payload["items"][0]["attempt_id"] == attempt.id
    assert payload["items"][0]["source_name"] == "Orders Feed"
    assert "idempotency_key" not in api.text
    assert "private-orders-key" not in api.text
    assert "delivery-worker" not in api.text

    assert page.status_code == 200
    assert "Which delivery outcomes are still unresolved?" in page.text
    assert "Orders Feed" in page.text
    assert "Evidence note" in page.text
    assert "private-orders-key" not in page.text
    assert "delivery-worker" not in page.text


def test_reconciliation_ui_resolves_existing_attempt_without_auto_retry(tmp_path: Path) -> None:
    app = create_app(tmp_path / "state.db")
    attempt = _seed_prepared(app)
    client = TestClient(app)

    response = client.post(
        f"/reconciliation/{attempt.id}/resolve",
        data={
            "outcome": "Failed",
            "note": "Teams workflow history confirms the card was not accepted.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/reconciliation"
    reconciled = app.state.workspace_storage.get_delivery_attempt(attempt.id)
    assert reconciled is not None
    assert reconciled.state.value == "Failed"
    assert reconciled.reconciliation_note.startswith("Teams workflow history")
    assert len(app.state.service.delivery_attempts(candidate_id=attempt.candidate_id)) == 1
    assert client.get("/api/delivery-reconciliation").json()["prepared_count"] == 0


def test_reconciliation_ui_rejects_missing_evidence_and_wrong_content_type(tmp_path: Path) -> None:
    app = create_app(tmp_path / "state.db")
    attempt = _seed_prepared(app)
    client = TestClient(app)

    missing_note = client.post(
        f"/reconciliation/{attempt.id}/resolve",
        data={"outcome": "Failed"},
    )
    wrong_type = client.post(
        f"/reconciliation/{attempt.id}/resolve",
        json={"outcome": "Failed", "note": "Not accepted as a form."},
    )

    assert missing_note.status_code == 400
    assert wrong_type.status_code == 415
    assert app.state.workspace_storage.get_delivery_attempt(attempt.id).state.value == "Prepared"


def test_authenticated_reconciliation_ui_records_operator_identity(tmp_path: Path) -> None:
    app = _secured_operator_app(tmp_path)
    attempt = _seed_prepared(app, workspace_id="team-a")
    client = TestClient(app)

    response = client.post(
        f"/reconciliation/{attempt.id}/resolve",
        data={
            "outcome": "Succeeded",
            "note": "Provider audit event confirms the delivery completed.",
        },
        headers=_authorization("operator"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    reconciled = app.state.workspace_storage.get_delivery_attempt(attempt.id)
    assert reconciled is not None
    assert reconciled.state.value == "Succeeded"
    assert reconciled.reconciled_by == "operator"


def test_authenticated_reconciliation_api_records_operator_identity(tmp_path: Path) -> None:
    app = _secured_operator_app(tmp_path)
    attempt = _seed_prepared(app, workspace_id="team-a")
    client = TestClient(app)

    response = client.post(
        f"/api/delivery-attempts/{attempt.id}/reconcile",
        params={
            "outcome": "Failed",
            "note": "Provider audit event confirms the delivery did not complete.",
        },
        headers=_authorization("operator"),
    )

    assert response.status_code == 200
    reconciled = app.state.workspace_storage.get_delivery_attempt(attempt.id)
    assert reconciled is not None
    assert reconciled.state.value == "Failed"
    assert reconciled.reconciled_by == "operator"


def test_delivery_ops_navigation_is_dynamic_only(tmp_path: Path) -> None:
    app = create_app(tmp_path / "state.db")
    client = TestClient(app)

    dynamic = client.get("/")
    output = build_pages_site(app.state.storage, tmp_path / "site", generated_at=NOW)
    static_html = (output / "index.html").read_text(encoding="utf-8")

    assert dynamic.status_code == 200
    assert 'href="/reconciliation"' in dynamic.text
    assert "Delivery Ops" in dynamic.text
    assert 'href="/reconciliation"' not in static_html
    assert "Delivery Ops" not in static_html


def test_reconciliation_role_boundaries() -> None:
    assert required_role("GET", "/reconciliation") == WorkspaceRole.VIEWER
    assert required_role("GET", "/api/delivery-reconciliation") == WorkspaceRole.VIEWER
    assert (
        required_role("POST", "/reconciliation/attempt-1/resolve")
        == WorkspaceRole.OPERATOR
    )
