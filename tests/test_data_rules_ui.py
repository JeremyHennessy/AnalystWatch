from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from analystwatch.models import DataRule, MonitoringConfig, SourceDefinition, SourceType
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app

NOW = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)


def _rule_source(path: Path) -> SourceDefinition:
    return SourceDefinition(
        id="private-rule-feed",
        name="Private Rule Feed",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            data_rules=[
                DataRule(
                    id="confidential-status-rule",
                    name="Confidential workflow state",
                    kind="allowed_values",
                    field="internal_status",
                    allowed_values=["PRIVATE_ALLOWED"],
                    severity="Critical",
                    likely_impact="Secret impact phrase for internal operations.",
                    suggested_investigation="Secret investigation phrase for operators.",
                )
            ]
        ),
    )


def _seed_rule_failure(app, path: Path) -> None:
    source = _rule_source(path)
    pd.DataFrame({"internal_status": ["PRIVATE_ALLOWED"] * 100}).to_csv(path, index=False)
    onboard = app.state.service.onboard_source(source, now=NOW)
    assert onboard.ready is True
    assert onboard.accepted is True
    baseline = app.state.service.check_source(source.id, now=NOW)
    assert baseline.health.value == "Healthy"

    values = ["PRIVATE_ALLOWED"] * 99 + ["PRIVATE_FORBIDDEN"]
    pd.DataFrame({"internal_status": values}).to_csv(path, index=False)
    current = app.state.service.check_source(source.id, now=NOW + timedelta(hours=1))
    assert current.health.value == "Critical"


def test_onboarding_exposes_typed_data_rule_builder(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "onboard.db"))
    response = client.get("/sources/new")

    assert response.status_code == 200
    assert "Data Rules" in response.text
    assert "+ Add Data Rule" in response.text
    assert "Rule ID" in response.text
    assert "Failure severity" in response.text
    assert "Allowed values" in response.text
    assert "Numeric range" in response.text
    assert "Row count range" in response.text
    assert "Why it matters" in response.text
    assert "What to check" in response.text
    assert "data_rules: dataRules()" in response.text
    assert "Every configured rule must pass preflight" in response.text


def test_dynamic_source_detail_keeps_private_data_rule_evidence(tmp_path: Path) -> None:
    app = create_app(tmp_path / "state.db")
    path = tmp_path / "private.csv"
    _seed_rule_failure(app, path)
    client = TestClient(app)

    response = client.get("/sources/private-rule-feed")

    assert response.status_code == 200
    assert "Confidential workflow state" in response.text
    assert "confidential-status-rule" in response.text
    assert "internal_status" in response.text
    assert "PRIVATE_ALLOWED" in response.text
    assert "Secret impact phrase for internal operations." in response.text
    assert "Secret investigation phrase for operators." in response.text
    assert "PRIVATE_FORBIDDEN" not in response.text


def test_static_pages_redact_private_data_rule_contract(tmp_path: Path) -> None:
    app = create_app(tmp_path / "state.db")
    path = tmp_path / "private.csv"
    _seed_rule_failure(app, path)

    output = build_pages_site(
        app.state.storage,
        tmp_path / "site",
        generated_at=NOW + timedelta(hours=1),
    )
    detail = (output / "sources" / "private-rule-feed" / "index.html").read_text(
        encoding="utf-8"
    )
    raw_state = (output / "state.json").read_text(encoding="utf-8")

    for rendered in (detail, raw_state):
        assert "confidential-status-rule" not in rendered
        assert "Confidential workflow state" not in rendered
        assert "internal_status" not in rendered
        assert "PRIVATE_ALLOWED" not in rendered
        assert "PRIVATE_FORBIDDEN" not in rendered
        assert "Secret impact phrase for internal operations." not in rendered
        assert "Secret investigation phrase for operators." not in rendered
        assert "A configured Data Rule failed." in rendered
        assert "Private configured Data Rule" in rendered

    assert '"violations": 1' in raw_state
    assert '"rows": 100' in raw_state
    assert '"violation_pct": 0.01' in raw_state
