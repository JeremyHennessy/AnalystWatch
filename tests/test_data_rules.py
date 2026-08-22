from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from analystwatch.data_rules import evaluate_data_rules
from analystwatch.models import DataRule, DataRuleKind, HealthStatus, MonitoringConfig


def _rule(**updates) -> DataRule:
    payload = {
        "id": "status-valid",
        "name": "Status must be approved",
        "kind": DataRuleKind.ALLOWED_VALUES,
        "severity": HealthStatus.CRITICAL,
        "field": "status",
        "allowed_values": ["Approved", "Pending"],
    }
    payload.update(updates)
    return DataRule(**payload)


def test_data_rule_contract_is_typed_and_rejects_ambiguous_configurations() -> None:
    with pytest.raises(ValidationError, match="severity"):
        _rule(severity=HealthStatus.HEALTHY)
    with pytest.raises(ValidationError, match="require field"):
        DataRule(id="missing-field", name="Missing", kind=DataRuleKind.NOT_NULL)
    with pytest.raises(ValidationError, match="at least one allowed value"):
        DataRule(
            id="allowed-empty",
            name="Allowed",
            kind=DataRuleKind.ALLOWED_VALUES,
            field="status",
        )
    with pytest.raises(ValidationError, match="minimum and/or maximum"):
        DataRule(
            id="range-empty",
            name="Range",
            kind=DataRuleKind.NUMERIC_RANGE,
            field="amount",
        )
    with pytest.raises(ValidationError, match="non-negative integer"):
        DataRule(
            id="row-count",
            name="Rows",
            kind=DataRuleKind.ROW_COUNT_RANGE,
            minimum=1.5,
        )


def test_monitoring_config_rejects_duplicate_data_rule_ids() -> None:
    rule = _rule()
    with pytest.raises(ValidationError, match="duplicate IDs"):
        MonitoringConfig(data_rules=[rule, rule.model_copy(update={"name": "Second"})])


def test_passing_rules_produce_no_findings() -> None:
    frame = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "status": ["Approved", "Pending", "Approved"],
            "amount": [10.0, 20.0, 30.0],
        }
    )
    rules = [
        DataRule(id="id-present", name="ID required", kind="not_null", field="id"),
        _rule(),
        DataRule(
            id="amount-range",
            name="Amount range",
            kind="numeric_range",
            field="amount",
            minimum=0,
            maximum=100,
        ),
        DataRule(
            id="row-volume",
            name="Expected row volume",
            kind="row_count_range",
            minimum=2,
            maximum=5,
        ),
    ]

    assert evaluate_data_rules(frame, rules) == []


def test_not_null_rule_reports_counts_without_row_values() -> None:
    frame = pd.DataFrame({"account": ["secret-a", None, "secret-b", None]})
    rule = DataRule(
        id="account-required",
        name="Account required",
        kind="not_null",
        field="account",
        severity="Warning",
    )

    findings = evaluate_data_rules(frame, [rule])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == HealthStatus.WARNING
    assert finding.detector == "data_rule:account-required"
    assert finding.current_value == {"violations": 2, "rows": 4, "violation_pct": 0.5}
    assert "secret-a" not in finding.model_dump_json()
    assert "secret-b" not in finding.model_dump_json()


def test_allowed_values_rule_treats_nulls_and_unknown_values_as_violations() -> None:
    frame = pd.DataFrame({"status": ["Approved", "Rejected", None, "Pending"]})

    finding = evaluate_data_rules(frame, [_rule()])[0]

    assert finding.current_value == {"violations": 2, "rows": 4, "violation_pct": 0.5}
    assert finding.baseline_value == {
        "kind": "allowed_values",
        "field": "status",
        "allowed_values": ["Approved", "Pending"],
    }
    assert "Rejected" not in finding.model_dump_json()


def test_numeric_range_rule_counts_null_non_numeric_and_out_of_range_values() -> None:
    frame = pd.DataFrame({"amount": [10, "20", None, "bad", -1, 101]})
    rule = DataRule(
        id="amount-range",
        name="Amount must be bounded",
        kind="numeric_range",
        field="amount",
        minimum=0,
        maximum=100,
        likely_impact="Bad amounts can distort totals.",
        suggested_investigation="Inspect the source amount field.",
    )

    finding = evaluate_data_rules(frame, [rule])[0]

    assert finding.current_value == {
        "violations": 4,
        "rows": 6,
        "violation_pct": 0.666667,
    }
    assert finding.baseline_value == {
        "kind": "numeric_range",
        "field": "amount",
        "minimum": 0.0,
        "maximum": 100.0,
    }
    assert finding.likely_impact == "Bad amounts can distort totals."
    assert finding.suggested_investigation == "Inspect the source amount field."
    assert "bad" not in finding.model_dump_json()


def test_row_count_range_reports_dataset_count_not_fake_row_violations() -> None:
    frame = pd.DataFrame({"id": [1, 2]})
    rule = DataRule(
        id="minimum-volume",
        name="Minimum row volume",
        kind="row_count_range",
        minimum=3,
    )

    finding = evaluate_data_rules(frame, [rule])[0]

    assert finding.current_value == {"row_count": 2}
    assert finding.baseline_value == {"kind": "row_count_range", "minimum": 3.0}
    assert "below the configured minimum 3" in finding.why_flagged


def test_missing_rule_field_fails_closed_without_exposing_data() -> None:
    frame = pd.DataFrame({"private": ["customer-secret"]})
    rule = DataRule(
        id="required-business-field",
        name="Required business field",
        kind="not_null",
        field="business_status",
    )

    finding = evaluate_data_rules(frame, [rule])[0]

    assert finding.detector == "data_rule:required-business-field"
    assert "business_status" in finding.why_flagged
    assert "customer-secret" not in finding.model_dump_json()
