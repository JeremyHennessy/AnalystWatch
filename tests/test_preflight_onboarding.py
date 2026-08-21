from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.web import create_app


def _csv_source(path: Path, *, source_id: str = "candidate", **config) -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        name="Candidate source",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(**config),
    )


def test_preflight_is_read_only_and_ready_for_valid_source(service, tmp_path: Path):
    path = tmp_path / "valid.csv"
    pd.DataFrame(
        {"id": [1, 2, 3], "amount": ["10.5", "11.0", "12.25"], "as_of": ["2026-08-21"] * 3}
    ).to_csv(path, index=False)
    source = _csv_source(
        path,
        unique_keys=["id"],
        numeric_fields=["amount"],
        latest_date_field="as_of",
    )

    result = service.preflight_source(source)

    assert result.ready is True
    assert result.accepted is False
    assert result.available is True
    assert result.profile is not None
    assert result.profile.columns["amount"].dtype == "numeric"
    assert result.issues == []
    assert service.storage.get_source(source.id) is None


def test_onboard_persists_only_after_successful_preflight(service, tmp_path: Path):
    path = tmp_path / "valid.csv"
    pd.DataFrame({"id": [1, 2], "value": [4, 5]}).to_csv(path, index=False)
    source = _csv_source(path, unique_keys=["id"])

    result = service.onboard_source(source)

    assert result.ready is True
    assert result.accepted is True
    assert service.storage.get_source(source.id) == source
    assert service.storage.get_latest(source.id) is None


def test_duplicate_declared_unique_key_blocks_onboarding(service, tmp_path: Path):
    path = tmp_path / "duplicates.csv"
    pd.DataFrame({"id": [1, 1, 2], "value": [4, 5, 6]}).to_csv(path, index=False)
    source = _csv_source(path, unique_keys=["id"])

    result = service.onboard_source(source)

    assert result.ready is False
    assert result.accepted is False
    assert any(issue.code == "unique_key_duplicates" for issue in result.issues)
    assert service.storage.get_source(source.id) is None


def test_bad_numeric_parse_rate_blocks_onboarding(service, tmp_path: Path):
    path = tmp_path / "bad-numeric.csv"
    pd.DataFrame(
        {"id": list(range(10)), "amount": ["1", "2", "3", "4", "5", "6", "7", "8", "bad", "also-bad"]}
    ).to_csv(path, index=False)
    source = _csv_source(path, numeric_fields=["amount"])

    result = service.preflight_source(source)

    issue = next(issue for issue in result.issues if issue.code == "numeric_parse_rate")
    assert result.ready is False
    assert "80.0%" in issue.message


def test_missing_declared_freshness_field_blocks_onboarding(service, tmp_path: Path):
    path = tmp_path / "no-date.csv"
    pd.DataFrame({"id": [1, 2], "amount": [10, 11]}).to_csv(path, index=False)
    source = _csv_source(
        path,
        expected_refresh_minutes=1440,
        latest_date_field="record_date",
    )

    result = service.preflight_source(source)

    assert result.ready is False
    assert any(issue.code == "freshness_field_missing" for issue in result.issues)


def test_local_onboarding_ui_preflights_then_accepts_source(tmp_path: Path):
    source_path = tmp_path / "web.csv"
    pd.DataFrame({"id": [1, 2, 3], "amount": [10, 11, 12]}).to_csv(source_path, index=False)
    app = create_app(tmp_path / "web.db")
    client = TestClient(app)
    payload = {
        "id": "web-source",
        "name": "Web source",
        "source_type": "csv",
        "location": str(source_path),
        "enabled": True,
        "config": {
            "monitor_interval_minutes": 60,
            "numeric_fields": ["amount"],
            "unique_keys": ["id"],
        },
    }

    page = client.get("/sources/new")
    assert page.status_code == 200
    assert "Validate before monitoring" in page.text

    preflight = client.post("/api/preflight", json=payload)
    assert preflight.status_code == 200
    assert preflight.json()["ready"] is True
    assert client.get("/api/sources").json() == []

    onboard = client.post("/api/onboard", json=payload)
    assert onboard.status_code == 200
    assert onboard.json()["accepted"] is True

    detail = client.get("/sources/web-source")
    assert detail.status_code == 200
    assert "Monitoring contract" in detail.text
    assert "amount" in detail.text
    assert "id" in detail.text


def test_onboarding_refuses_to_overwrite_existing_source(service, tmp_path: Path):
    path = tmp_path / "existing.csv"
    pd.DataFrame({"id": [1, 2]}).to_csv(path, index=False)
    existing = _csv_source(path, source_id="existing", unique_keys=["id"])
    service.add_source(existing)
    replacement = existing.model_copy(update={"name": "Replacement"})

    try:
        service.onboard_source(replacement)
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Existing source ID was overwritten")

    assert service.storage.get_source("existing").name == "Candidate source"
