from pathlib import Path

from fastapi.testclient import TestClient

from analystwatch.web import create_app


def test_onboarding_exposes_microsoft_excel_connection_fields(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "onboard.db"))
    response = client.get("/sources/new")
    assert response.status_code == 200
    assert "Microsoft 365 Excel" in response.text
    assert "Drive ID" in response.text
    assert "Workbook item ID" in response.text
    assert "Excel table" in response.text
    assert "Microsoft token environment variable" in response.text
    assert "does not store the bearer token" in response.text
    assert "microsoft_excel" in response.text
