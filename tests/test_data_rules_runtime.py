from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from analystwatch.models import (
    DataRule,
    HealthStatus,
    IncidentTransition,
    MonitoringConfig,
    NotificationCandidateState,
    SourceDefinition,
    SourceType,
)
from analystwatch.service import MonitorService
from analystwatch.storage import Storage

NOW = datetime(2026, 8, 22, 19, 40, tzinfo=timezone.utc)


def _source(path: Path, *, severity: HealthStatus, notify: bool = False) -> SourceDefinition:
    return SourceDefinition(
        id="status-feed",
        name="Status Feed",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            data_rules=[
                DataRule(
                    id="status-contract",
                    name="Status must remain approved",
                    kind="allowed_values",
                    field="status",
                    allowed_values=["Approved"],
                    severity=severity,
                    likely_impact="Unapproved status values can alter business workflows.",
                    suggested_investigation="Inspect the upstream status mapping.",
                )
            ],
            notification_transitions=[IncidentTransition.OPENED] if notify else [],
        ),
    )


def _healthy_baseline(service: MonitorService, source: SourceDefinition, path: Path) -> None:
    pd.DataFrame({"status": ["Approved"] * 100}).to_csv(path, index=False)
    onboard = service.onboard_source(source, now=NOW)
    assert onboard.ready is True
    assert onboard.accepted is True
    first = service.check_source(source.id, now=NOW)
    assert first.health == HealthStatus.HEALTHY
    assert first.findings == []


def _one_unexpected_status(path: Path) -> None:
    values = ["Approved"] * 99 + ["Unexpected"]
    pd.DataFrame({"status": values}).to_csv(path, index=False)


def test_runtime_warning_rule_flows_through_existing_health_derivation(tmp_path: Path) -> None:
    path = tmp_path / "statuses.csv"
    service = MonitorService(Storage(tmp_path / "state.db"))
    source = _source(path, severity=HealthStatus.WARNING)
    _healthy_baseline(service, source, path)

    _one_unexpected_status(path)
    observation = service.check_source(source.id, now=NOW + timedelta(hours=1))

    rule_findings = [
        finding
        for finding in observation.findings
        if finding.detector == "data_rule:status-contract"
    ]
    assert observation.health == HealthStatus.WARNING
    assert observation.findings == rule_findings
    assert len(rule_findings) == 1
    assert rule_findings[0].severity == HealthStatus.WARNING
    assert rule_findings[0].current_value == {
        "violations": 1,
        "rows": 100,
        "violation_pct": 0.01,
    }
    assert "Unexpected" not in rule_findings[0].model_dump_json()


def test_critical_rule_uses_existing_incident_and_notification_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "statuses.csv"
    service = MonitorService(Storage(tmp_path / "state.db"))
    source = _source(path, severity=HealthStatus.CRITICAL, notify=True)
    _healthy_baseline(service, source, path)

    _one_unexpected_status(path)
    observation = service.check_source(source.id, now=NOW + timedelta(hours=1))

    rule_findings = [
        finding
        for finding in observation.findings
        if finding.detector == "data_rule:status-contract"
    ]
    assert observation.health == HealthStatus.CRITICAL
    assert observation.findings == rule_findings
    assert len(rule_findings) == 1
    assert rule_findings[0].severity == HealthStatus.CRITICAL
    assert "Unexpected" not in rule_findings[0].model_dump_json()

    incident = service.incident(source.id)
    assert incident is not None
    assert incident.current_health == HealthStatus.CRITICAL
    candidates = service.notification_candidates(source.id)
    assert len(candidates) == 1
    assert candidates[0].transition == IncidentTransition.OPENED
    assert candidates[0].state == NotificationCandidateState.ELIGIBLE
    assert candidates[0].observation_id == observation.id
