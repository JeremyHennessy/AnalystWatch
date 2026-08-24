from __future__ import annotations

from fastapi.testclient import TestClient

import analystwatch.connection_web as connection_web
from analystwatch.auth import WorkspaceRole
from analystwatch.connection_discovery import (
    ConnectionCheck,
    ConnectionDiscoveryError,
    ConnectionProvider,
    MicrosoftDriveOption,
)
from analystwatch.web import create_app
from analystwatch.web_auth import required_role


def test_connection_check_redacts_fixed_server_environment_name(tmp_path, monkeypatch) -> None:
    def fake_check(provider, environment_variable):
        assert provider == ConnectionProvider.MICROSOFT
        assert environment_variable == connection_web.MICROSOFT_AUTH_ENV
        return ConnectionCheck(
            provider=provider,
            environment_variable=environment_variable,
            configured=False,
            reachable=False,
            error=f"Missing {environment_variable}",
        )

    monkeypatch.setattr(connection_web, "check_connection", fake_check)
    response = TestClient(create_app(tmp_path / "check.db")).post(
        "/api/connections/microsoft/check"
    )

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["error"] == "Server credential is not configured."
    assert connection_web.MICROSOFT_AUTH_ENV not in response.text


def test_discovery_api_uses_fixed_server_reference_without_persisting(
    tmp_path, monkeypatch
) -> None:
    seen: list[str] = []

    def fake_drives(environment_variable):
        seen.append(environment_variable)
        return [MicrosoftDriveOption(id="drive-1", name="Finance")]

    monkeypatch.setattr(connection_web, "list_microsoft_drives", fake_drives)
    app = create_app(tmp_path / "drives.db")
    response = TestClient(app).post("/api/connections/microsoft/drives")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "drive-1", "name": "Finance", "drive_type": None, "web_url": None}
    ]
    assert seen == [connection_web.MICROSOFT_AUTH_ENV]
    assert app.state.workspace_storage.list_sources() == []


def test_provider_discovery_error_is_bounded_and_status_mapped(tmp_path, monkeypatch) -> None:
    def fake_spreadsheets(environment_variable):
        assert environment_variable == connection_web.GOOGLE_AUTH_ENV
        raise ConnectionDiscoveryError(
            ConnectionProvider.GOOGLE,
            "provider_rejected",
            "Google Workspace returned HTTP 403.",
            http_status=403,
        )

    monkeypatch.setattr(connection_web, "list_google_spreadsheets", fake_spreadsheets)
    response = TestClient(create_app(tmp_path / "provider-error.db")).post(
        "/api/connections/google/spreadsheets"
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "provider_rejected",
        "message": "Google Workspace returned HTTP 403.",
    }
    assert "token" not in response.text.lower()


def test_connection_discovery_mutations_require_operator_role() -> None:
    paths = [
        "/api/connections/microsoft/check",
        "/api/connections/microsoft/drives",
        "/api/connections/microsoft/workbooks",
        "/api/connections/microsoft/tables",
        "/api/connections/google/check",
        "/api/connections/google/spreadsheets",
        "/api/connections/google/sheets",
    ]

    for path in paths:
        assert required_role("POST", path) == WorkspaceRole.OPERATOR
