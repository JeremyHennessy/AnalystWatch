from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import analystwatch.connection_web as connection_web
from analystwatch.connection_discovery import (
    ConnectionCheck,
    ConnectionProvider,
    GoogleSpreadsheetOption,
    MicrosoftDriveOption,
)
from analystwatch.connection_identity import ConnectionAccountIdentity
from analystwatch.connection_lifecycle import (
    CredentialLifecycle,
    CredentialLifecycleState,
    CredentialNextAction,
)
from analystwatch.credential_runtime import load_credential_keyring
from analystwatch.credential_store import seal_provider_credential
from analystwatch.web import create_app


def _key() -> str:
    return base64.urlsafe_b64encode(bytes([31]) * 32).decode("ascii").rstrip("=")


def _configure_keyring(monkeypatch) -> None:
    monkeypatch.setenv("ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID", "active")
    monkeypatch.setenv(
        "ANALYSTWATCH_CREDENTIAL_KEYS_JSON",
        json.dumps({"active": _key()}),
    )


def _install_credential(
    app,
    monkeypatch,
    provider: ConnectionProvider,
    *,
    expires_at: datetime | None = None,
) -> str:
    _configure_keyring(monkeypatch)
    now = datetime.now(timezone.utc)
    credential_id = connection_web.DEFAULT_OAUTH_CREDENTIAL_IDS[provider]
    token = f"{provider.value}-stored-access-token"
    record = seal_provider_credential(
        load_credential_keyring(),
        credential_id=credential_id,
        workspace_id=app.state.workspace_id,
        provider=provider,
        subject_id=f"{provider.value}-subject",
        access_token=token,
        refresh_token=f"{provider.value}-refresh-token",
        scopes=["scope-a"],
        access_token_expires_at=expires_at or now + timedelta(hours=1),
        now=now,
    )
    app.state.oauth_credential_store.upsert(record)
    return token


def test_microsoft_check_prefers_encrypted_oauth_credential_over_environment(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(tmp_path / "microsoft-oauth.db")
    expected_token = _install_credential(app, monkeypatch, ConnectionProvider.MICROSOFT)
    seen: list[str] = []

    def fake_oauth_check(provider, access_token):
        assert provider == ConnectionProvider.MICROSOFT
        seen.append(access_token)
        return ConnectionCheck(
            provider=provider,
            environment_variable="stored_oauth",
            configured=True,
            reachable=True,
            http_status=200,
        )

    def forbidden_environment_check(*_args):
        raise AssertionError("Environment credential fallback must not run")

    monkeypatch.setattr(connection_web, "check_connection_with_access_token", fake_oauth_check)
    monkeypatch.setattr(connection_web, "check_connection", forbidden_environment_check)

    response = TestClient(app).post("/api/connections/microsoft/check")

    assert response.status_code == 200
    assert response.json()["reachable"] is True
    assert seen == [expected_token]
    assert expected_token not in response.text


def test_existing_browse_endpoint_uses_stored_oauth_token_without_ui_changes(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(tmp_path / "browse-oauth.db")
    expected_token = _install_credential(app, monkeypatch, ConnectionProvider.MICROSOFT)
    seen: list[str] = []

    def fake_oauth_drives(access_token):
        seen.append(access_token)
        return [MicrosoftDriveOption(id="drive-1", name="Finance")]

    monkeypatch.setattr(
        connection_web,
        "list_microsoft_drives_with_access_token",
        fake_oauth_drives,
    )
    monkeypatch.setattr(
        connection_web,
        "list_microsoft_drives",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected env fallback")),
    )

    response = TestClient(app).post("/api/connections/microsoft/drives")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "drive-1"
    assert seen == [expected_token]


def test_google_identity_and_lifecycle_use_the_same_stored_oauth_credential(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(tmp_path / "google-oauth.db")
    expected_token = _install_credential(app, monkeypatch, ConnectionProvider.GOOGLE)
    seen: list[tuple[str, str]] = []

    def fake_identity(provider, access_token):
        assert provider == ConnectionProvider.GOOGLE
        seen.append(("identity", access_token))
        return ConnectionAccountIdentity(
            provider=provider,
            subject_id="google-subject",
            display_name="Analyst",
        )

    def fake_lifecycle(provider, access_token):
        assert provider == ConnectionProvider.GOOGLE
        seen.append(("lifecycle", access_token))
        return CredentialLifecycle(
            provider=provider,
            state=CredentialLifecycleState.VERIFIED,
            next_action=CredentialNextAction.NONE,
            configured=True,
            reachable=True,
            identity_verified=True,
            http_status=200,
            identity=ConnectionAccountIdentity(
                provider=provider,
                subject_id="google-subject",
            ),
            guidance="Verified.",
        )

    monkeypatch.setattr(
        connection_web,
        "inspect_connection_identity_with_access_token",
        fake_identity,
    )
    monkeypatch.setattr(
        connection_web,
        "credential_lifecycle_with_access_token",
        fake_lifecycle,
    )

    client = TestClient(app)
    identity = client.post("/api/connections/google/identity")
    lifecycle = client.post("/api/connections/google/lifecycle")

    assert identity.status_code == 200
    assert lifecycle.status_code == 200
    assert seen == [
        ("identity", expected_token),
        ("lifecycle", expected_token),
    ]


def test_google_browse_prefers_stored_oauth_credential(tmp_path, monkeypatch) -> None:
    app = create_app(tmp_path / "google-browse.db")
    expected_token = _install_credential(app, monkeypatch, ConnectionProvider.GOOGLE)
    seen: list[str] = []

    def fake_spreadsheets(access_token):
        seen.append(access_token)
        return [GoogleSpreadsheetOption(id="sheet-1", name="Forecast")]

    monkeypatch.setattr(
        connection_web,
        "list_google_spreadsheets_with_access_token",
        fake_spreadsheets,
    )
    monkeypatch.setattr(
        connection_web,
        "list_google_spreadsheets",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected env fallback")),
    )

    response = TestClient(app).post("/api/connections/google/spreadsheets")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Forecast"
    assert seen == [expected_token]


def test_expired_stored_oauth_credential_fails_closed_without_environment_fallback(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(tmp_path / "expired.db")
    _install_credential(
        app,
        monkeypatch,
        ConnectionProvider.MICROSOFT,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    monkeypatch.setattr(
        connection_web,
        "check_connection",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected env fallback")),
    )

    response = TestClient(app).post("/api/connections/microsoft/check")

    assert response.status_code == 409
    assert "expired" in response.text.lower()


def test_missing_keyring_for_existing_oauth_credential_does_not_fall_back_to_env(
    tmp_path,
    monkeypatch,
) -> None:
    app = create_app(tmp_path / "missing-key.db")
    _install_credential(app, monkeypatch, ConnectionProvider.GOOGLE)
    monkeypatch.delenv("ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID")
    monkeypatch.delenv("ANALYSTWATCH_CREDENTIAL_KEYS_JSON")
    monkeypatch.setattr(
        connection_web,
        "check_connection",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected env fallback")),
    )

    response = TestClient(app).post("/api/connections/google/check")

    assert response.status_code == 503
    assert "key" in response.text.lower()
    assert "stored-access-token" not in response.text
