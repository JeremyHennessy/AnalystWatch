from __future__ import annotations

from fastapi.testclient import TestClient

from analystwatch.web import create_app


def test_add_source_loads_connection_browser_without_removing_manual_fields(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "connection-ui.db"))

    response = client.get("/sources/new")

    assert response.status_code == 200
    assert "/static/connection_onboard.js" in response.text
    for field_id in [
        "microsoft-drive-id",
        "microsoft-item-id",
        "microsoft-table",
        "microsoft-worksheet",
        "google-spreadsheet-id",
        "google-range",
        "google-header-row",
    ]:
        assert f'id="{field_id}"' in response.text
    assert "Start with a source pack" in response.text
    assert "Run preflight" in response.text
    assert "Add monitored source" in response.text


def test_connection_browser_exposes_provider_browse_flow_and_bounded_google_range(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "connection-js.db"))

    response = client.get("/static/connection_onboard.js")

    assert response.status_code == 200
    script = response.text
    for endpoint in [
        "/api/connections/microsoft/check",
        "/api/connections/microsoft/drives",
        "/api/connections/microsoft/workbooks",
        "/api/connections/microsoft/tables",
        "/api/connections/google/check",
        "/api/connections/google/spreadsheets",
        "/api/connections/google/sheets",
    ]:
        assert endpoint in script
    assert "Test Microsoft connection" in script
    assert "Browse drives" in script
    assert "Search workbooks" in script
    assert "Load workbook tables" in script
    assert "Test Google connection" in script
    assert "Browse spreadsheets" in script
    assert "Load sheets" in script
    assert "5000" in script
    assert "100" in script
    assert "Enter an explicit A1 range before preflight" in script


def test_connection_browser_never_embeds_server_credential_names_or_token_examples(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path / "connection-private-ui.db"))

    script = client.get("/static/connection_onboard.js").text

    assert "ANALYSTWATCH_MICROSOFT_AUTHORIZATION" not in script
    assert "ANALYSTWATCH_GOOGLE_AUTHORIZATION" not in script
    assert "Bearer " not in script
