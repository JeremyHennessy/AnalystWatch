from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from analystwatch.auth import SignedSessionAuthenticator, WorkspaceMembership, WorkspaceRole
from analystwatch.auth_storage import SQLiteMembershipStore
from analystwatch.models import SourceDefinition, SourceType
from analystwatch.web import create_app

SECRET = "analystwatch-test-auth-secret-32-bytes-minimum"


def _authorization(user_id: str) -> dict[str, str]:
    token = SignedSessionAuthenticator(SECRET).issue_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _secured_app(tmp_path: Path, workspace_id: str = "team-a"):
    memberships = SQLiteMembershipStore(tmp_path / "memberships.db")
    memberships.initialize()
    memberships.upsert_membership(
        WorkspaceMembership(workspace_id=workspace_id, user_id="viewer", role=WorkspaceRole.VIEWER)
    )
    memberships.upsert_membership(
        WorkspaceMembership(
            workspace_id=workspace_id, user_id="operator", role=WorkspaceRole.OPERATOR
        )
    )
    memberships.upsert_membership(
        WorkspaceMembership(workspace_id=workspace_id, user_id="admin", role=WorkspaceRole.ADMIN)
    )
    app = create_app(
        tmp_path / f"{workspace_id}.db",
        workspace_id=workspace_id,
        auth_mode="signed-bearer",
        auth_secret=SECRET,
        membership_store=memberships,
    )
    return app, memberships


def _seed_source(app, tmp_path: Path, workspace_id: str = "team-a") -> None:
    csv_path = tmp_path / f"{workspace_id}-market.csv"
    pd.DataFrame({"id": [1, 2], "value": [10, 20]}).to_csv(csv_path, index=False)
    app.state.service.add_source(
        SourceDefinition(
            id="market",
            workspace_id=workspace_id,
            name="Market",
            source_type=SourceType.CSV,
            location=str(csv_path),
        )
    )
    app.state.service.check_source("market")


def test_remote_mode_requires_valid_authentication_and_membership(tmp_path: Path) -> None:
    app, _ = _secured_app(tmp_path)
    _seed_source(app, tmp_path)
    client = TestClient(app)

    missing = client.get("/api/sources")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    outsider = client.get("/api/sources", headers=_authorization("outsider"))
    assert outsider.status_code == 403

    viewer = client.get("/api/sources", headers=_authorization("viewer"))
    assert viewer.status_code == 200
    assert viewer.json()[0]["source"]["workspace_id"] == "team-a"


def test_viewer_cannot_mutate_workspace_state(tmp_path: Path) -> None:
    app, _ = _secured_app(tmp_path)
    _seed_source(app, tmp_path)
    client = TestClient(app)
    headers = _authorization("viewer")

    assert client.post("/api/sources/market/check", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/sources/market/observations/unknown/review",
            params={"state": "Reviewed"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/notification-candidates/evaluate",
            params={"source_id": "market"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/sources",
            json={
                "id": "new-source",
                "workspace_id": "team-a",
                "name": "New",
                "source_type": "csv",
                "location": "missing.csv",
                "config": {},
            },
            headers=headers,
        ).status_code
        == 403
    )


def test_operator_can_operate_but_cannot_administer(tmp_path: Path) -> None:
    app, _ = _secured_app(tmp_path)
    _seed_source(app, tmp_path)
    client = TestClient(app)
    headers = _authorization("operator")

    assert client.post("/api/sources/market/check", headers=headers).status_code == 200
    latest = app.state.workspace_storage.get_latest("market")
    assert latest is not None
    # Authorization permits the Operator through; the existing domain rule then
    # rejects reviewing this already-baselined Healthy observation with 409.
    assert (
        client.post(
            f"/api/sources/market/observations/{latest.id}/review",
            params={"state": "Reviewed"},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/workspace/memberships/new-user",
            params={"role": "Viewer"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/sources/market/baseline",
            params={
                "observation_id": latest.id,
                "expected_current_baseline_id": latest.id,
            },
            headers=headers,
        ).status_code
        == 403
    )


def test_admin_can_manage_membership_and_source_configuration(tmp_path: Path) -> None:
    app, memberships = _secured_app(tmp_path)
    client = TestClient(app)
    headers = _authorization("admin")

    membership_response = client.put(
        "/api/workspace/memberships/new-user",
        params={"role": "Viewer"},
        headers=headers,
    )
    assert membership_response.status_code == 200
    assert memberships.get_membership("team-a", "new-user").role == WorkspaceRole.VIEWER  # type: ignore[union-attr]

    csv_path = tmp_path / "admin-source.csv"
    pd.DataFrame({"id": [1], "value": [5]}).to_csv(csv_path, index=False)
    create = client.post(
        "/api/sources",
        json={
            "id": "admin-source",
            "workspace_id": "team-a",
            "name": "Admin Source",
            "source_type": "csv",
            "location": str(csv_path),
            "config": {},
        },
        headers=headers,
    )
    assert create.status_code == 200


def test_cross_workspace_access_is_denied_before_resource_lookup(tmp_path: Path) -> None:
    shared_memberships = SQLiteMembershipStore(tmp_path / "shared-auth.db")
    shared_memberships.initialize()
    shared_memberships.upsert_membership(
        WorkspaceMembership(workspace_id="team-a", user_id="user-a", role=WorkspaceRole.ADMIN)
    )
    app_b = create_app(
        tmp_path / "team-b.db",
        workspace_id="team-b",
        auth_mode="signed-bearer",
        auth_secret=SECRET,
        membership_store=shared_memberships,
    )
    client_b = TestClient(app_b)
    headers = _authorization("user-a")

    assert client_b.get("/api/sources", headers=headers).status_code == 403
    assert client_b.get("/api/sources/market", headers=headers).status_code == 403
    assert client_b.post("/api/sources/market/check", headers=headers).status_code == 403
    assert (
        client_b.post(
            "/api/notification-candidates/evaluate",
            params={"source_id": "market"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client_b.post(
            "/api/delivery-attempts/dry-run",
            params={"candidate_id": "candidate", "idempotency_key": "key"},
            headers=headers,
        ).status_code
        == 403
    )


def test_payload_workspace_id_cannot_override_authenticated_workspace(tmp_path: Path) -> None:
    app, _ = _secured_app(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/sources",
        json={
            "id": "wrong-workspace",
            "workspace_id": "team-b",
            "name": "Wrong Workspace",
            "source_type": "csv",
            "location": "missing.csv",
            "config": {},
        },
        headers=_authorization("admin"),
    )

    assert response.status_code == 409
    assert app.state.workspace_storage.get_source("wrong-workspace") is None


def test_local_mode_preserves_existing_unauthenticated_workflow(tmp_path: Path) -> None:
    app = create_app(tmp_path / "local.db")
    client = TestClient(app)

    assert app.state.auth_mode == "local"
    assert client.get("/").status_code == 200
    assert client.get("/api/sources").status_code == 200
