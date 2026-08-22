from pathlib import Path

from fastapi.testclient import TestClient

from analystwatch.web import create_app


def test_onboarding_exposes_google_sheets_connection_fields(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "onboard.db"))
    response = client.get("/sources/new")

    assert response.status_code == 200
    assert "Google Sheets" in response.text
    assert "Spreadsheet ID" in response.text
    assert "A1 range" in response.text
    assert "Header row" in response.text
    assert "Google token environment variable" in response.text
    assert "Google Sheets range reads do not provide a sheet modification timestamp" in response.text
    assert "The secret value is never saved by AnalystWatch" in response.text
    assert "google_sheets" in response.text
    assert "ANALYSTWATCH_GOOGLE_AUTHORIZATION" in response.text
