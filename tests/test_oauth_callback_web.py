from __future__ import annotations

import base64
import json
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from analystwatch.auth import SignedSessionAuthenticator, WorkspaceMembership, WorkspaceRole
from analystwatch.auth_storage import SQLiteMembershipStore
from analystwatch.connection_discovery import ConnectionProvider
from analystwatch.credential_persistence import SQLiteCredentialStore
from analystwatch.credential_runtime import load_credential_keyring
from analystwatch.credential_store import seal_provider_credential, unseal_access_token
from analystwatch.oauth_authorization import OAuthAuthorizationError
from analystwatch.oauth_authorization_store import SQLiteOAuthAuthorizationStore
from analystwatch.web import create_app

SECRET = "analystwatch-test-auth-secret-32-bytes-minimum"


def _key() -> str:
    return base64.urlsafe_b64encode(bytes([29]) * 32).decode("ascii").rstrip("=")


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


def _start_state(
    client: TestClient,
    provider: str,
    credential_id: str,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    response = client.post(
        f"/api/oauth/{provider}/start",
        params={"credential_id": credential_id},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def _fake_complete(
    authorization_store,
    credential_store,
    keyring,
    config,
    *,
    provider,
    workspace_id,
    state,
    code,
    now,
    client=None,
):
    del config, code, client
    provider = ConnectionProvider(provider)
    consumed = authorization_store.consume(
        state,
        keyring,
        now=now,
        expected_workspace_id=workspace_id,
        expected_provider=provider,
    )
    record = seal_provider_credential(
        keyring,
        credential_id=consumed.transaction.credential_id,
        workspace_id=workspace_id,
        provider=provider,
        subject_id=f"{provider.value}-subject",
        access_token="oauth-web-access-token",
        refresh_token="oauth-web-refresh-token",
        scopes=["scope-a"],
        access_token_expires_at=now + timedelta(hours=1),
        now=now,
    )
    return credential_store.upsert(record)


def test_callback_success_uses_encrypted_credential_store_and_never_echoes_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_oauth(monkeypatch)
    monkeypatch.setattr("analystwatch.oauth_web.complete_oauth_authorization", _fake_complete)
    app = create_app(tmp_path / "callback.db")
    client = TestClient(app)
    state = _start_state(client, "microsoft", "microsoft-primary")
    code = "authorization-code-must-not-be-rendered"

    response = client.get(
        "/api/oauth/microsoft/callback",
        params={"state": state, "code": code},
    )

    assert response.status_code == 200
    assert "Connection complete" in response.text
    assert code not in response.text
    assert state not in response.text

    store = app.state.oauth_credential_store
    assert isinstance(store, SQLiteCredentialStore)
    record = store.get("local", "microsoft-primary")
    assert record is not None
    assert unseal_access_token(record, load_credential_keyring()) == "oauth-web-access-token"
    with store.connect() as db:
        raw = db.execute(
            "SELECT record_json FROM provider_credentials WHERE credential_id = ?",
            ("microsoft-primary",),
        ).fetchone()["record_json"]
    assert "oauth-web-access-token" not in raw
    assert "oauth-web-refresh-token" not in raw


def test_provider_denial_consumes_state_without_echoing_provider_description(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_oauth(monkeypatch)
    app = create_app(tmp_path / "denial.db")
    client = TestClient(app)
    state = _start_state(client, "google", "google-primary")

    response = client.get(
        "/api/oauth/google/callback",
        params={
            "state": state,
            "error": "access_denied",
            "error_description": "provider-private-description",
        },
    )

    assert response.status_code == 400
    assert "provider-private-description" not in response.text
    store = app.state.oauth_authorization_store
    assert isinstance(store, SQLiteOAuthAuthorizationStore)
    transaction_id = _transaction_ids(store)[0]
    transaction = store.get(transaction_id)
    assert transaction is not None
    with pytest.raises(OAuthAuthorizationError, match="already consumed"):
        store.consume(
            state,
            load_credential_keyring(),
            now=transaction.created_at + timedelta(minutes=1),
        )


def _transaction_ids(store: SQLiteOAuthAuthorizationStore) -> list[str]:
    with store.connect() as db:
        rows = db.execute(
            "SELECT transaction_id FROM oauth_authorization_transactions ORDER BY transaction_id"
        ).fetchall()
    return [row["transaction_id"] for row in rows]


def test_signed_bearer_callback_does_not_require_browser_authorization_header(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_oauth(monkeypatch)
    memberships = SQLiteMembershipStore(tmp_path / "memberships.db")
    memberships.initialize()
    memberships.upsert_membership(
        WorkspaceMembership(
            workspace_id="team-a",
            user_id="operator",
            role=WorkspaceRole.OPERATOR,
        )
    )
    app = create_app(
        tmp_path / "team-a.db",
        workspace_id="team-a",
        auth_mode="signed-bearer",
        auth_secret=SECRET,
        membership_store=memberships,
    )
    client = TestClient(app)
    state = _start_state(
        client,
        "microsoft",
        "microsoft-primary",
        headers=_authorization("operator"),
    )

    callback = client.get(
        "/api/oauth/microsoft/callback",
        params={"state": state, "error": "access_denied"},
    )

    assert callback.status_code == 400
    assert callback.status_code != 401
    assert "WWW-Authenticate" not in callback.headers


def test_callback_provider_mismatch_does_not_consume_the_correct_route_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_oauth(monkeypatch)
    app = create_app(tmp_path / "provider-binding.db")
    client = TestClient(app)
    state = _start_state(client, "microsoft", "microsoft-primary")

    wrong_route = client.get(
        "/api/oauth/google/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert wrong_route.status_code == 400

    correct_route = client.get(
        "/api/oauth/microsoft/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert correct_route.status_code == 400
    assert "did not complete" in correct_route.text


def test_existing_connected_credential_id_blocks_a_second_authorization_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_oauth(monkeypatch)
    monkeypatch.setattr("analystwatch.oauth_web.complete_oauth_authorization", _fake_complete)
    app = create_app(tmp_path / "duplicate.db")
    client = TestClient(app)
    state = _start_state(client, "google", "google-primary")
    completed = client.get(
        "/api/oauth/google/callback",
        params={"state": state, "code": "valid-test-code"},
    )
    assert completed.status_code == 200

    second = client.post(
        "/api/oauth/google/start",
        params={"credential_id": "google-primary"},
        follow_redirects=False,
    )
    assert second.status_code == 409
    assert "location" not in second.headers


def test_callback_rejects_missing_state_and_ambiguous_result(tmp_path: Path, monkeypatch) -> None:
    _configure_oauth(monkeypatch)
    app = create_app(tmp_path / "malformed.db")
    client = TestClient(app)

    missing_state = client.get(
        "/api/oauth/microsoft/callback",
        params={"code": "code"},
    )
    assert missing_state.status_code == 400

    state = _start_state(client, "microsoft", "microsoft-primary")
    ambiguous = client.get(
        "/api/oauth/microsoft/callback",
        params={"state": state, "code": "code", "error": "access_denied"},
    )
    assert ambiguous.status_code == 400
