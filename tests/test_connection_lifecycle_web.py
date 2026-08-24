from __future__ import annotations

from fastapi.testclient import TestClient

import analystwatch.connection_web as connection_web
from analystwatch.auth import WorkspaceRole
from analystwatch.connection_discovery import ConnectionProvider
from analystwatch.connection_lifecycle import (
    CredentialLifecycle,
    CredentialLifecycleState,
    CredentialNextAction,
)
from analystwatch.web import create_app
from analystwatch.web_auth import required_role


def test_microsoft_lifecycle_api_uses_fixed_server_reference(tmp_path, monkeypatch) -> None:
    seen: list[tuple[ConnectionProvider, str]] = []

    def fake_lifecycle(provider, environment_variable):
        seen.append((provider, environment_variable))
        return CredentialLifecycle(
            provider=provider,
            state=CredentialLifecycleState.REJECTED,
            next_action=CredentialNextAction.RECONNECT,
            configured=True,
            reachable=False,
            identity_verified=False,
            http_status=401,
            guidance="Reconnect with a valid provider credential.",
        )

    monkeypatch.setattr(connection_web, "credential_lifecycle", fake_lifecycle)
    response = TestClient(create_app(tmp_path / "lifecycle.db")).post(
        "/api/connections/microsoft/lifecycle"
    )

    assert response.status_code == 200
    assert response.json()["state"] == "rejected"
    assert response.json()["next_action"] == "reconnect"
    assert seen == [
        (ConnectionProvider.MICROSOFT, connection_web.MICROSOFT_AUTH_ENV)
    ]
    assert connection_web.MICROSOFT_AUTH_ENV not in response.text


def test_google_lifecycle_api_can_return_verified_identity(tmp_path, monkeypatch) -> None:
    def fake_lifecycle(provider, environment_variable):
        assert provider == ConnectionProvider.GOOGLE
        assert environment_variable == connection_web.GOOGLE_AUTH_ENV
        return CredentialLifecycle(
            provider=provider,
            state=CredentialLifecycleState.VERIFIED,
            next_action=CredentialNextAction.NONE,
            configured=True,
            reachable=True,
            identity_verified=True,
            http_status=200,
            identity={
                "provider": "google",
                "subject_id": "permission-1",
                "display_name": "Finance Analyst",
                "email": "finance@example.com",
            },
            guidance="The provider credential is reachable and its account identity is verified.",
        )

    monkeypatch.setattr(connection_web, "credential_lifecycle", fake_lifecycle)
    response = TestClient(create_app(tmp_path / "verified-lifecycle.db")).post(
        "/api/connections/google/lifecycle"
    )

    assert response.status_code == 200
    assert response.json()["state"] == "verified"
    assert response.json()["identity"]["email"] == "finance@example.com"
    assert connection_web.GOOGLE_AUTH_ENV not in response.text


def test_lifecycle_endpoints_require_operator_role() -> None:
    for path in [
        "/api/connections/microsoft/lifecycle",
        "/api/connections/google/lifecycle",
    ]:
        assert required_role("POST", path) == WorkspaceRole.OPERATOR
