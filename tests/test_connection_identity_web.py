from __future__ import annotations

from fastapi.testclient import TestClient

import analystwatch.connection_web as connection_web
from analystwatch.auth import WorkspaceRole
from analystwatch.connection_discovery import ConnectionDiscoveryError, ConnectionProvider
from analystwatch.connection_identity import ConnectionAccountIdentity
from analystwatch.web import create_app
from analystwatch.web_auth import required_role


def test_microsoft_identity_api_uses_fixed_server_reference(tmp_path, monkeypatch) -> None:
    seen: list[tuple[ConnectionProvider, str]] = []

    def fake_identity(provider, environment_variable):
        seen.append((provider, environment_variable))
        return ConnectionAccountIdentity(
            provider=provider,
            subject_id="user-123",
            display_name="Analyst User",
            email="analyst@example.com",
        )

    monkeypatch.setattr(connection_web, "inspect_connection_identity", fake_identity)
    response = TestClient(create_app(tmp_path / "identity.db")).post(
        "/api/connections/microsoft/identity"
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "microsoft",
        "subject_id": "user-123",
        "display_name": "Analyst User",
        "email": "analyst@example.com",
    }
    assert seen == [
        (ConnectionProvider.MICROSOFT, connection_web.MICROSOFT_AUTH_ENV)
    ]
    assert connection_web.MICROSOFT_AUTH_ENV not in response.text


def test_google_identity_error_is_bounded(tmp_path, monkeypatch) -> None:
    def fake_identity(provider, environment_variable):
        assert provider == ConnectionProvider.GOOGLE
        assert environment_variable == connection_web.GOOGLE_AUTH_ENV
        raise ConnectionDiscoveryError(
            provider,
            "provider_rejected",
            "Google Workspace returned HTTP 401.",
            http_status=401,
        )

    monkeypatch.setattr(connection_web, "inspect_connection_identity", fake_identity)
    response = TestClient(create_app(tmp_path / "identity-error.db")).post(
        "/api/connections/google/identity"
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "provider_rejected",
        "message": "Google Workspace returned HTTP 401.",
    }
    assert connection_web.GOOGLE_AUTH_ENV not in response.text


def test_identity_endpoints_require_operator_role() -> None:
    for path in [
        "/api/connections/microsoft/identity",
        "/api/connections/google/identity",
    ]:
        assert required_role("POST", path) == WorkspaceRole.OPERATOR
