from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from analystwatch.models import SourceDefinition, SourceType
from analystwatch.web import create_app


def test_dashboard_renders_source_health_and_evidence(tmp_path: Path):
    csv_path = tmp_path / "market.csv"
    pd.DataFrame({"id": [1, 2, 3], "amount": [100, 110, 120]}).to_csv(csv_path, index=False)
    app = create_app(tmp_path / "web.db")
    client = TestClient(app)

    create = client.post(
        "/api/sources",
        json={
            "id": "market",
            "name": "Market Data",
            "source_type": "csv",
            "location": str(csv_path),
            "enabled": True,
            "config": {},
        },
    )
    assert create.status_code == 200
    check = client.post("/api/sources/market/check")
    assert check.status_code == 200
    assert check.json()["health"] == "Healthy"

    home = client.get("/")
    assert home.status_code == 200
    assert "Market Data" in home.text
    assert "Healthy" in home.text
    assert "WORKSPACE OVERVIEW" in home.text
    assert "Sources healthy" in home.text
    assert "Needs attention" in home.text
    assert "Monitored sources" in home.text

    detail = client.get("/sources/market")
    assert detail.status_code == 200
    assert "Data verified" in detail.text
    assert "Baseline" in detail.text
    assert "Last successful update" in detail.text
    assert "Current profile" in detail.text
    assert "No material reliability findings" in detail.text
    assert "WHAT CHANGED?" in detail.text
    assert "Recent health history" in detail.text
    assert "Monitoring contract" in detail.text


def test_source_api_returns_history(tmp_path: Path):
    csv_path = tmp_path / "market.csv"
    pd.DataFrame({"id": [1], "value": [1]}).to_csv(csv_path, index=False)
    app = create_app(tmp_path / "api.db")
    app.state.service.add_source(
        SourceDefinition(
            id="market", name="Market", source_type=SourceType.CSV, location=str(csv_path)
        )
    )
    app.state.service.check_source("market")
    client = TestClient(app)
    response = client.get("/api/sources/market")
    assert response.status_code == 200
    payload = response.json()
    assert payload["health"] == "Healthy"
    assert len(payload["history"]) == 1


def test_detail_renders_after_first_check_is_unavailable(tmp_path: Path):
    missing_path = tmp_path / "missing.csv"
    app = create_app(tmp_path / "failed.db")
    app.state.service.add_source(
        SourceDefinition(
            id="missing",
            name="Missing Source",
            source_type=SourceType.CSV,
            location=str(missing_path),
        )
    )
    observation = app.state.service.check_source("missing")
    assert observation.health.value == "Critical"
    assert app.state.storage.get_baseline("missing") is None

    client = TestClient(app)
    detail = client.get("/sources/missing")
    assert detail.status_code == 200
    assert "Critical" in detail.text
    assert "No successful observation" in detail.text
    assert "Not established" in detail.text
    assert "WHAT HAPPENED?" in detail.text
    assert "Suggested next check" in detail.text
