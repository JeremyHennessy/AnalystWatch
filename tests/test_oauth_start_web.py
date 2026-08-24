from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from analystwatch.auth import SignedSessionAuthenticator, WorkspaceMembership, WorkspaceRole
from analystwatch.auth_storage import SQLiteMembershipStore
from analystwatch.oauth_authorization import (
    OAuthAuthorizationTransaction,
    authorization_state_digest,
)
from analystwatch.oauth_authorization_store import SQLiteOAuthAuthorizationStore
from analystwatch.web import create_app

SECRET = "analystwatch-test-auth-secret-32-bytes-minimum"


def _key() -> str:
    return base64.urlsafe_b64encode(bytes([23]) * 32).decode("ascii").rstrip("=")


def _configure_oauth(monkeypatch) -> None:
    values = {
        "ANALYSTWATCH_PUBLIC_BASE_URL": "https://analystwatch.example",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID": "microsoft-client",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET": "microsoft-secret",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
        "ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID": "active",
        "ANALYSTWATCH_CREDENTIAL_KEYS_JSON": json.dumps({"active": _key()}),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _authorization(user_id: str) -> dict[str, str]:
    token = SignedSessionAuthenticator(SECRET).issue_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _oauth_store(app) -> SQLiteOAuthAuthorizationStore:
    store = app.state.oauth_authorization_store
    assert isinstance(store, SQLiteOAuthAuthorizationStore)
    return store


def _rows(app) -> list[OAuthAuthorizationTransaction]:
    store = _oauth_store(app)
    with store.connect() as db:
        rows = db.execute(
            """
            SELECT record_json
            FROM oauth_authorization_transactions
            ORDER BY transaction_id
            """
        ).fetchall()
    return [OAuthAuthorizationTransaction.model_validate_json(row["record_json"]) for row in rows]


def test_local_start_redirect_persists_before_redirect_and_binds_local_user(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_oauth(monkeypatch)
    app = create_app(tmp_path / "local.db")
    client = TestClient(app)

    response = client.post(
        "/api/oauth/microsoft/start",
        params={"credential_id": "microsoft-primary"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    parts = urlsplit(location)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
    )
    assert query["client_id"] == ["microsoft-client"]
    assert query["response_type"] == ["code"]
    assert query["response_mode"] == ["query"]
    assert query["code_challenge_method"] == ["S256"]
    assert "microsoft-secret" not in location

    records = _rows(app)
    assert len(records) == 1
    record = records[0]
    assert record.workspace_id == "default-local"
    assert record.user_id == "local-operator"
    assert record.provider.value == "microsoft"
    assert record.credential_id == "microsoft-primary"
    assert record.state_sha256_b64 == authorization_state_digest(query["state"][0])

    store = _oauth_store(app)
    with store.connect() as db:
        raw = db.execute(
            "SELECT record_json FROM oauth_authorization_transactions"
        ).fetchone()["record_json"]
    assert query["state"][0] not in raw
    assert query["code_challenge"][0] not in raw


def test_google_start_redirect_has_offline_parameters(tmp_path: Path, monkeypatch) -> None:
    _configure_oauth(monkeypatch)
    app = create_app(tmp_path / "google.db")
    client = TestClient(app)

    response = client.post(
        "/api/oauth/google/start",
        params={"credential_id": "google-primary"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert "prompt" not in query
    assert _rows(app)[0].provider.value == "google"


def test_oauth_runtime_configuration_is_lazy_and_failure_does_not_persist_or_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name in [
        "ANALYSTWATCH_PUBLIC_BASE_URL",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET",
        "ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID",
        "ANALYSTWATCH_CREDENTIAL_KEYS_JSON",
    ]:
        monkeypatch.delenv(name, raising=False)

    app = create_app(tmp_path / "missing-config.db")
    client = TestClient(app)
    response = client.post(
        "/api/oauth/microsoft/start",
        params={"credential_id": "microsoft-primary"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert "location" not in response.headers
    assert _rows(app) == []

    monkeypatch.setenv("ANALYSTWATCH_PUBLIC_BASE_URL", "https://analystwatch.example")
    monkeypatch.setenv("ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID", "microsoft-client")
    monkeypatch.setenv("ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET", "microsoft-secret")
    response = client.post(
        "/api/oauth/microsoft/start",
        params={"credential_id": "microsoft-primary"},
        follow_redirects=False,
    )
    assert response.status_code == 503
    assert "location" not in response.headers
    assert _rows(app) == []


def test_invalid_credential_id_fails_without_redirect_or_transaction(tmp_path: Path, monkeypatch) -> None:
    _configure_oauth(monkeypatch)
    app = create_app(tmp_path / "invalid-id.db")
    client = TestClient(app)

    response = client.post(
        "/api/oauth/google/start",
        params={"credential_id": " bad-id "},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "location" not in response.headers
    assert _rows(app) == []


def test_signed_bearer_start_is_operator_level_and_binds_authenticated_user(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_oauth(monkeypatch)
    memberships = SQLiteMembershipStore(tmp_path / "memberships.db")
    memberships.initialize()
    for user_id, role in [
        ("viewer", WorkspaceRole.VIEWER),
        ("operator", WorkspaceRole.OPERATOR),
        ("admin", WorkspaceRole.ADMIN),
    ]:
        memberships.upsert_membership(
            WorkspaceMembership(workspace_id="team-a", user_id=user_id, role=role)
        )
    app = create_app(
        tmp_path / "team-a.db",
        workspace_id="team-a",
        auth_mode="signed-bearer",
        auth_secret=SECRET,
        membership_store=memberships,
    )
    client = TestClient(app)

    viewer = client.post(
        "/api/oauth/microsoft/start",
        params={"credential_id": "viewer-denied"},
        headers=_authorization("viewer"),
        follow_redirects=False,
    )
    assert viewer.status_code == 403
    assert _rows(app) == []

    operator = client.post(
        "/api/oauth/microsoft/start",
        params={"credential_id": "operator-connect"},
        headers=_authorization("operator"),
        follow_redirects=False,
    )
    admin = client.post(
        "/api/oauth/google/start",
        params={"credential_id": "admin-connect"},
        headers=_authorization("admin"),
        follow_redirects=False,
    )
    assert operator.status_code == 303
    assert admin.status_code == 303

    records = _rows(app)
    assert {(record.user_id, record.credential_id) for record in records} == {
        ("operator", "operator-connect"),
        ("admin", "admin-connect"),
    }
    assert all(record.workspace_id == "team-a" for record in records)


def test_provider_callbacks_are_not_exposed_yet(tmp_path: Path, monkeypatch) -> None:
    _configure_oauth(monkeypatch)
    app = create_app(tmp_path / "no-callback.db")
    client = TestClient(app)

    for provider in ["microsoft", "google"]:
        response = client.get(
            f"/api/oauth/{provider}/callback",
            params={"code": "not-used", "state": "A" * 43},
        )
        assert response.status_code == 404
