from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from analystwatch.models import (
    HealthStatus,
    IncidentStatus,
    IncidentTransition,
    MonitoringConfig,
    ObservationReviewState,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app


def _source(path: Path, source_id: str = "market") -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        name="Market",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(unique_keys=["id"]),
    )


def _write_rows(path: Path, count: int) -> pd.DataFrame:
    frame = pd.DataFrame({"id": range(count), "value": [100] * count})
    frame.to_csv(path, index=False)
    return frame


def test_open_incident_creates_one_candidate_and_ongoing_failure_does_not_duplicate(
    service,
    tmp_path: Path,
):
    path = tmp_path / "market.csv"
    _write_rows(path, 100)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()

    first_failure = service.check_source("market")
    second_failure = service.check_source("market")

    assert first_failure.health == HealthStatus.CRITICAL
    assert second_failure.health == HealthStatus.CRITICAL
    incident = service.incident("market")
    assert incident is not None
    assert incident.status == IncidentStatus.OPEN
    assert incident.current_health == HealthStatus.CRITICAL
    assert incident.peak_health == HealthStatus.CRITICAL
    assert incident.observation_count == 2
    candidates = service.notification_candidates("market")
    assert [item.transition for item in candidates] == [IncidentTransition.OPENED]
    assert candidates[0].observation_id == first_failure.id


def test_warning_to_critical_creates_escalation_candidate(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _write_rows(path, 100)
    service.add_source(_source(path))
    service.check_source("market")

    _write_rows(path, 70)
    warning = service.check_source("market")
    _write_rows(path, 20)
    critical = service.check_source("market")

    assert warning.health == HealthStatus.WARNING
    assert critical.health == HealthStatus.CRITICAL
    candidates = service.notification_candidates("market")
    assert [item.transition for item in candidates] == [
        IncidentTransition.ESCALATED,
        IncidentTransition.OPENED,
    ]
    incident = service.incident("market")
    assert incident is not None
    assert incident.status == IncidentStatus.OPEN
    assert incident.peak_health == HealthStatus.CRITICAL
    assert incident.observation_count == 2


def test_recovery_closes_derived_incident_and_creates_recovery_candidate(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    baseline_frame = _write_rows(path, 100)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()
    service.check_source("market")
    baseline_frame.to_csv(path, index=False)

    recovery = service.check_source("market")

    assert recovery.health == HealthStatus.HEALTHY
    incident = service.incident("market")
    assert incident is not None
    assert incident.status == IncidentStatus.RECOVERED
    assert incident.current_health == HealthStatus.HEALTHY
    assert incident.recovered_observation_id == recovery.id
    candidates = service.notification_candidates("market")
    assert [item.transition for item in candidates] == [
        IncidentTransition.RECOVERED,
        IncidentTransition.OPENED,
    ]


def test_recovered_incident_remains_derivable_after_later_healthy_checks(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    baseline_frame = _write_rows(path, 100)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()
    service.check_source("market")
    baseline_frame.to_csv(path, index=False)
    recovery = service.check_source("market")
    service.check_source("market")

    incident = service.incident("market")
    assert incident is not None
    assert incident.status == IncidentStatus.RECOVERED
    assert incident.recovered_observation_id == recovery.id


def test_all_healthy_history_has_no_incident_or_notification_candidate(service, tmp_path: Path):
    path = tmp_path / "healthy.csv"
    _write_rows(path, 50)
    service.add_source(_source(path, source_id="healthy"))
    service.check_source("healthy")
    service.check_source("healthy")

    assert service.incident("healthy") is None
    assert service.notification_candidates("healthy") == []


def test_review_state_does_not_resolve_open_incident(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _write_rows(path, 20)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()
    failure = service.check_source("market")

    service.review_observation(
        "market",
        failure.id,
        ObservationReviewState.REVIEWED,
    )

    incident = service.incident("market")
    assert incident is not None
    assert incident.status == IncidentStatus.OPEN
    assert incident.current_health == HealthStatus.CRITICAL


def test_candidate_is_persisted_with_transition_observation(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _write_rows(path, 20)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()
    failure = service.check_source("market")

    candidate = service.notification_candidates("market")[0]
    stored_observation = service.storage.get_observation(candidate.observation_id)

    assert candidate.observation_id == failure.id
    assert stored_observation is not None
    assert stored_observation.id == failure.id


def test_pages_exposes_incident_summary_but_no_delivery_controls(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _write_rows(path, 20)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()
    service.check_source("market")

    output = build_pages_site(service.storage, tmp_path / "site")
    detail = (output / "sources" / "market" / "index.html").read_text(encoding="utf-8")
    state = json.loads((output / "state.json").read_text(encoding="utf-8"))

    assert "Incident lifecycle" in detail
    assert "Notification candidates" in detail
    assert "does not send email, Slack, webhooks" in detail
    assert "Send notification" not in detail
    source_state = next(item for item in state["sources"] if item["id"] == "market")
    assert source_state["incident"]["status"] == "Open"
    assert source_state["notification_candidate_count"] == 1


def test_incident_and_notification_candidate_api_are_read_only(tmp_path: Path):
    path = tmp_path / "market.csv"
    _write_rows(path, 20)
    app = create_app(tmp_path / "web.db")
    app.state.service.add_source(_source(path))
    app.state.service.check_source("market")
    path.unlink()
    app.state.service.check_source("market")
    client = TestClient(app)

    incident = client.get("/api/sources/market/incident")
    candidates = client.get("/api/notification-candidates?source_id=market")

    assert incident.status_code == 200
    assert incident.json()["status"] == "Open"
    assert candidates.status_code == 200
    assert candidates.json()[0]["transition"] == "Opened"
