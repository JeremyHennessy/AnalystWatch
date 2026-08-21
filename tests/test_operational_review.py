from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analystwatch.ingest import ingest_source
from analystwatch.models import (
    MonitoringConfig,
    ObservationReviewState,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app


def test_api_headers_are_resolved_from_environment_without_persisting_secret(monkeypatch):
    monkeypatch.setenv("ANALYSTWATCH_TOKEN", "super-secret-value")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json=[{"id": 1, "amount": 10}])

    source = SourceDefinition(
        id="secured",
        name="Secured API",
        source_type=SourceType.API,
        location="https://example.test/data",
        config=MonitoringConfig(
            request_header_env={"Authorization": "ANALYSTWATCH_TOKEN"},
            numeric_fields=["amount"],
        ),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ingest_source(source, client=client)

    assert result.available is True
    assert seen["authorization"] == "super-secret-value"
    assert "super-secret-value" not in source.model_dump_json()
    assert "ANALYSTWATCH_TOKEN" in source.model_dump_json()


def test_missing_header_environment_variable_is_evidence_not_a_crash(monkeypatch):
    monkeypatch.delenv("ANALYSTWATCH_MISSING", raising=False)
    source = SourceDefinition(
        id="secured",
        name="Secured API",
        source_type=SourceType.API,
        location="https://example.test/data",
        config=MonitoringConfig(
            request_header_env={"X-Api-Key": "ANALYSTWATCH_MISSING"},
        ),
    )

    result = ingest_source(source)

    assert result.available is False
    assert "ANALYSTWATCH_MISSING" in (result.error or "")
    assert "X-Api-Key" in (result.error or "")


def test_safe_source_update_preflights_and_preserves_baseline(service, tmp_path: Path):
    path = tmp_path / "source.csv"
    pd.DataFrame({"id": [1, 2, 3], "amount": [10, 11, 12]}).to_csv(path, index=False)
    original = SourceDefinition(
        id="market",
        name="Market",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(unique_keys=["id"]),
    )
    service.add_source(original)
    baseline = service.check_source("market")
    replacement = original.model_copy(
        update={
            "name": "Market Updated",
            "config": original.config.model_copy(update={"monitor_interval_minutes": 120}),
        }
    )

    result = service.update_source("market", replacement)

    assert result.ready is True
    assert result.accepted is True
    assert service.storage.get_source("market") == replacement
    assert service.storage.get_baseline("market").id == baseline.id


def test_failed_source_update_does_not_replace_working_definition(service, tmp_path: Path):
    path = tmp_path / "source.csv"
    pd.DataFrame({"id": [1, 2], "amount": [10, 11]}).to_csv(path, index=False)
    original = SourceDefinition(
        id="market",
        name="Market",
        source_type=SourceType.CSV,
        location=str(path),
    )
    service.add_source(original)
    replacement = original.model_copy(
        update={"config": MonitoringConfig(unique_keys=["missing_key"])}
    )

    result = service.update_source("market", replacement)

    assert result.ready is False
    assert result.accepted is False
    assert service.storage.get_source("market") == original


def test_unhealthy_observation_can_be_acknowledged_then_reviewed(service, tmp_path: Path):
    source = SourceDefinition(
        id="missing",
        name="Missing",
        source_type=SourceType.CSV,
        location=str(tmp_path / "missing.csv"),
    )
    service.add_source(source)
    observation = service.check_source("missing")

    acknowledged = service.review_observation(
        "missing",
        observation.id,
        ObservationReviewState.ACKNOWLEDGED,
    )
    reviewed = service.review_observation(
        "missing",
        observation.id,
        ObservationReviewState.REVIEWED,
    )

    assert acknowledged.state == ObservationReviewState.ACKNOWLEDGED
    assert reviewed.state == ObservationReviewState.REVIEWED
    assert service.storage.get_review(observation.id).state == ObservationReviewState.REVIEWED


def test_healthy_observation_cannot_be_given_alert_review_state(service, tmp_path: Path):
    path = tmp_path / "healthy.csv"
    pd.DataFrame({"id": [1, 2]}).to_csv(path, index=False)
    source = SourceDefinition(
        id="healthy",
        name="Healthy",
        source_type=SourceType.CSV,
        location=str(path),
    )
    service.add_source(source)
    observation = service.check_source("healthy")

    with pytest.raises(ValueError, match="Healthy observations"):
        service.review_observation(
            "healthy",
            observation.id,
            ObservationReviewState.ACKNOWLEDGED,
        )


def test_baseline_promotion_requires_reviewed_candidate_and_current_baseline_guard(
    service,
    tmp_path: Path,
):
    path = tmp_path / "baseline.csv"
    pd.DataFrame({"id": [1, 2, 3], "amount": [10, 11, 12]}).to_csv(path, index=False)
    source = SourceDefinition(
        id="market",
        name="Market",
        source_type=SourceType.CSV,
        location=str(path),
    )
    service.add_source(source)
    baseline = service.check_source("market")
    candidate = service.check_source("market")
    review = service.baseline_review("market", candidate.id)

    assert review.ready is True
    assert review.current_baseline.id == baseline.id
    assert review.candidate.id == candidate.id

    with pytest.raises(ValueError, match="Baseline changed since review"):
        service.promote_baseline_after_review("market", candidate.id, "stale-baseline")

    promoted = service.promote_baseline_after_review("market", candidate.id, baseline.id)
    assert promoted.id == candidate.id
    assert service.storage.get_baseline("market").id == candidate.id


def test_static_pages_never_expose_header_environment_variable_names(service, tmp_path: Path):
    source = SourceDefinition(
        id="secured",
        name="Secured",
        source_type=SourceType.API,
        location="https://example.test/data?token=do-not-render",
        config=MonitoringConfig(
            request_header_env={"Authorization": "ANALYSTWATCH_TOKEN"},
        ),
    )
    service.add_source(source)

    output = build_pages_site(service.storage, tmp_path / "site")
    detail = (output / "sources" / "secured" / "index.html").read_text(encoding="utf-8")

    assert "1 environment-backed header configured" in detail
    assert "ANALYSTWATCH_TOKEN" not in detail
    assert "do-not-render" not in detail


def test_web_review_and_guarded_baseline_endpoints(tmp_path: Path):
    path = tmp_path / "web.csv"
    pd.DataFrame({"id": [1, 2], "amount": [10, 11]}).to_csv(path, index=False)
    app = create_app(tmp_path / "web.db")
    source = SourceDefinition(
        id="market",
        name="Market",
        source_type=SourceType.CSV,
        location=str(path),
    )
    app.state.service.add_source(source)
    baseline = app.state.service.check_source("market")
    candidate = app.state.service.check_source("market")
    client = TestClient(app)

    review = client.get(f"/api/sources/market/baseline-review?observation_id={candidate.id}")
    assert review.status_code == 200
    assert review.json()["ready"] is True

    promote = client.post(
        "/api/sources/market/baseline",
        params={
            "observation_id": candidate.id,
            "expected_current_baseline_id": baseline.id,
        },
    )
    assert promote.status_code == 200
    assert promote.json()["id"] == candidate.id
