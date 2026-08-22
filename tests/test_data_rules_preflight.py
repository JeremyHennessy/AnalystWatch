from __future__ import annotations

from pathlib import Path

import pandas as pd

from analystwatch.models import DataRule, MonitoringConfig, SourceDefinition, SourceType
from analystwatch.preflight import preflight_source
from analystwatch.service import MonitorService
from analystwatch.storage import Storage


def _source(path: Path, rule: DataRule) -> SourceDefinition:
    return SourceDefinition(
        id="business-feed",
        name="Business Feed",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(data_rules=[rule]),
    )


def test_preflight_accepts_source_when_configured_data_rule_passes(tmp_path: Path) -> None:
    path = tmp_path / "business.csv"
    pd.DataFrame({"status": ["Approved", "Pending"]}).to_csv(path, index=False)
    source = _source(
        path,
        DataRule(
            id="status-contract",
            name="Status contract",
            kind="allowed_values",
            field="status",
            allowed_values=["Approved", "Pending"],
            severity="Warning",
        ),
    )

    result = preflight_source(source)

    assert result.ready is True
    assert not any(issue.code == "data_rule_failed" for issue in result.issues)


def test_preflight_blocks_initial_data_rule_failure_even_for_warning_rule(tmp_path: Path) -> None:
    path = tmp_path / "business.csv"
    pd.DataFrame({"status": ["Approved", "Unexpected"]}).to_csv(path, index=False)
    source = _source(
        path,
        DataRule(
            id="status-contract",
            name="Status contract",
            kind="allowed_values",
            field="status",
            allowed_values=["Approved", "Pending"],
            severity="Warning",
        ),
    )

    result = preflight_source(source)

    assert result.ready is False
    issue = next(item for item in result.issues if item.code == "data_rule_failed")
    assert issue.level == "error"
    assert issue.field == "status"
    assert "Status contract" in issue.message
    assert "outside the configured allowed set" in issue.message
    assert "Unexpected" not in issue.model_dump_json()


def test_preflight_blocks_missing_data_rule_field(tmp_path: Path) -> None:
    path = tmp_path / "business.csv"
    pd.DataFrame({"private_value": ["customer-secret"]}).to_csv(path, index=False)
    source = _source(
        path,
        DataRule(
            id="required-status",
            name="Required status",
            kind="not_null",
            field="status",
        ),
    )

    result = preflight_source(source)

    assert result.ready is False
    issue = next(item for item in result.issues if item.code == "data_rule_failed")
    assert issue.field == "status"
    assert "not present" in issue.message
    assert "customer-secret" not in issue.model_dump_json()


def test_onboarding_does_not_persist_source_that_fails_data_rule_preflight(tmp_path: Path) -> None:
    path = tmp_path / "business.csv"
    pd.DataFrame({"amount": [10, 999]}).to_csv(path, index=False)
    source = _source(
        path,
        DataRule(
            id="amount-contract",
            name="Amount contract",
            kind="numeric_range",
            field="amount",
            maximum=100,
        ),
    )
    service = MonitorService(Storage(tmp_path / "state.db"))

    result = service.onboard_source(source)

    assert result.ready is False
    assert result.accepted is False
    assert service.storage.get_source(source.id) is None
    assert any(issue.code == "data_rule_failed" for issue in result.issues)
