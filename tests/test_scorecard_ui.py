from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from analystwatch.models import (
    DataRule,
    DatasetProfile,
    Finding,
    HealthStatus,
    MonitoringConfig,
    Observation,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app

PROFILE = DatasetProfile(row_count=10, column_count=0, columns={})


def _source(*, data_rules: list[DataRule] | None = None) -> SourceDefinition:
    return SourceDefinition(
        id="orders",
        name="Orders",
        source_type=SourceType.CSV,
        location="orders.csv",
        config=MonitoringConfig(data_rules=data_rules or []),
    )


def _observation(
    observed_at: datetime,
    *,
    health: HealthStatus = HealthStatus.HEALTHY,
    findings: list[Finding] | None = None,
) -> Observation:
    return Observation(
        id=f"orders-{int(observed_at.timestamp())}",
        source_id="orders",
        observed_at=observed_at,
        available=True,
        health=health,
        profile=PROFILE,
        findings=findings or [],
    )


def test_dynamic_source_detail_renders_explainable_scorecard(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    app = create_app(tmp_path / "state.db")
    storage = app.state.workspace_storage
    storage.upsert_source(_source())
    storage.save_observation(_observation(now - timedelta(hours=1)))

    response = TestClient(app).get("/sources/orders")

    assert response.status_code == 200
    assert "RELIABILITY SCORECARD" in response.text
    assert "Recent reliability" in response.text
    assert "Trusted" in response.text
    assert "7 days" in response.text
    assert "30 days" in response.text
    assert "Healthy checks" in response.text
    assert "Successful checks" in response.text
    assert "Incidents opened" in response.text
    assert "Stale occurrences" in response.text
    assert "Rule-failure occurrences" in response.text
    assert "MTTR" in response.text
    assert "100.0%" in response.text
    assert "94/100" not in response.text


def test_static_pages_render_and_serialize_same_aggregate_scorecard(tmp_path: Path) -> None:
    observed_at = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)
    generated_at = observed_at + timedelta(hours=1)
    app = create_app(tmp_path / "state.db")
    storage = app.state.workspace_storage
    storage.upsert_source(_source())
    storage.save_observation(_observation(observed_at))

    output = build_pages_site(
        app.state.storage,
        tmp_path / "site",
        generated_at=generated_at,
    )
    detail = (output / "sources" / "orders" / "index.html").read_text(encoding="utf-8")
    state = json.loads((output / "state.json").read_text(encoding="utf-8"))
    scorecard = state["sources"][0]["scorecard"]

    assert "RELIABILITY SCORECARD" in detail
    assert "Trusted" in detail
    assert "100.0%" in detail
    assert scorecard["badge"] == "Trusted"
    assert scorecard["current_health"] == "Healthy"
    assert scorecard["history_complete"] is True
    assert scorecard["window_7d"]["check_count"] == 1
    assert scorecard["window_7d"]["healthy_check_pct"] == 1.0
    assert scorecard["window_30d"]["successful_check_pct"] == 1.0


def test_public_scorecard_counts_private_rule_failure_without_leaking_contract(
    tmp_path: Path,
) -> None:
    observed_at = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)
    private_rule = DataRule(
        id="secret-rule",
        name="Secret workflow state",
        kind="allowed_values",
        severity="Warning",
        field="internal_status",
        allowed_values=["PRIVATE_ALLOWED"],
        likely_impact="SECRET IMPACT",
        suggested_investigation="SECRET INVESTIGATION",
    )
    finding = Finding(
        severity=HealthStatus.WARNING,
        detector="data_rule:secret-rule",
        description="Secret workflow state failed for internal_status",
        current_value={"violations": 1, "rows": 10, "violation_pct": 0.1},
        baseline_value={"field": "internal_status", "allowed_values": ["PRIVATE_ALLOWED"]},
        why_flagged="PRIVATE_ALLOWED contract failed",
        likely_impact="SECRET IMPACT",
        suggested_investigation="SECRET INVESTIGATION",
    )
    app = create_app(tmp_path / "state.db")
    storage = app.state.workspace_storage
    storage.upsert_source(_source(data_rules=[private_rule]))
    storage.save_observation(
        _observation(
            observed_at,
            health=HealthStatus.WARNING,
            findings=[finding],
        )
    )

    output = build_pages_site(
        app.state.storage,
        tmp_path / "site",
        generated_at=observed_at + timedelta(hours=1),
    )
    raw_state = (output / "state.json").read_text(encoding="utf-8")
    state = json.loads(raw_state)
    scorecard = state["sources"][0]["scorecard"]

    assert scorecard["badge"] == "Attention"
    assert scorecard["window_7d"]["data_rule_failure_occurrence_count"] == 1
    assert "secret-rule" not in raw_state
    assert "Secret workflow state" not in raw_state
    assert "internal_status" not in raw_state
    assert "PRIVATE_ALLOWED" not in raw_state
    assert "SECRET IMPACT" not in raw_state
    assert "SECRET INVESTIGATION" not in raw_state
