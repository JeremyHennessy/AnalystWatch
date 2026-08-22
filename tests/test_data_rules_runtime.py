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
        id="amount-feed",
        name="Amount Feed",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            data_rules=[
                DataRule(
                    id="amount-contract",
                    name="Amount must remain bounded",
                    kind="numeric_range",
                    field="amount",
                    minimum=0,
                    maximum=100,
                    severity=severity,
                    likely_impact="Out-of-range amounts can distort financial totals.",
                    suggested_investigation="Inspect the upstream amount calculation.",
                )
            ],
            notification_transitions=[IncidentTransition.OPENED] if notify else [],
            warning_numeric_factor=1000,
            critical_numeric_factor=10000,
        ),
    )


def _healthy_baseline(service: MonitorService, source: SourceDefinition, path: Path) -> None:
    pd.DataFrame({"amount": [10.0, 20.0]}).to_csv(path, index=False)
    onboard = service.onboard_source(source, now=NOW)
    assert onboard.ready is True
    assert onboard.accepted is True
    first = service.check_source(source.id, now=NOW)
    assert first.health == HealthStatus.HEALTHY
    assert first.findings == []


def test_runtime_warning_rule_flows_through_existing_health_derivation(tmp_path: Path) -> None:
    path = tmp_path / "amounts.csv"
    service = MonitorService(Storage(tmp_path / "state.db"))
    source = _source(path, severity=HealthStatus.WARNING)
    _healthy_baseline(service, source, path)

    pd.DataFrame({"amount": [10.0, 150.0]}).to_csv(path, index=False)
    observation = service.check_source(source.id, now=NOW + timedelta(hours=1))

    rule_findings = [
        finding
        for finding in observation.findings
        if finding.detector == "data_rule:amount-contract"
    ]
    assert observation.health == HealthStatus.WARNING
    assert len(rule_findings) == 1
    assert rule_findings[0].severity == HealthStatus.WARNING
    assert rule_findings[0].current_value == {
        "violations": 1,
        "rows": 2,
        "violation_pct": 0.5,
    }
    assert "150" not in rule_findings[0].model_dump_json()


def test_critical_rule_uses_existing_incident_and_notification_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "amounts.csv"
    service = MonitorService(Storage(tmp_path / "state.db"))
    source = _source(path, severity=HealthStatus.CRITICAL, notify=True)
    _healthy_baseline(service, source, path)

    pd.DataFrame({"amount": [10.0, 999.0]}).to_csv(path, index=False)
    observation = service.check_source(source.id, now=NOW + timedelta(hours=1))

    assert observation.health == HealthStatus.CRITICAL
    rule_findings = [
        finding
        for finding in observation.findings
        if finding.detector == "data_rule:amount-contract"
    ]
    assert len(rule_findings) == 1
    assert rule_findings[0].severity == HealthStatus.CRITICAL
    assert "999" not in rule_findings[0].model_dump_json()

    incident = service.incident(source.id)
    assert incident is not None
    assert incident.current_health == HealthStatus.CRITICAL
    candidates = service.notification_candidates(source.id)
    assert len(candidates) == 1
    assert candidates[0].transition == IncidentTransition.OPENED
    assert candidates[0].state == NotificationCandidateState.ELIGIBLE
    assert candidates[0].observation_id == observation.id
