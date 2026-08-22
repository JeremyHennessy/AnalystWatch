from __future__ import annotations

import pandas as pd

from .models import DataRule, DataRuleKind, Finding


def _rule_condition(rule: DataRule) -> dict[str, object]:
    condition: dict[str, object] = {"kind": rule.kind.value}
    if rule.field is not None:
        condition["field"] = rule.field
    if rule.allowed_values:
        condition["allowed_values"] = list(rule.allowed_values)
    if rule.minimum is not None:
        condition["minimum"] = rule.minimum
    if rule.maximum is not None:
        condition["maximum"] = rule.maximum
    return condition


def _failure(
    rule: DataRule,
    *,
    violation_count: int,
    row_count: int,
    why: str,
) -> Finding:
    violation_pct = violation_count / row_count if row_count else 0.0
    return Finding(
        severity=rule.severity,
        detector=f"data_rule:{rule.id}",
        description=f"Data rule '{rule.name}' failed.",
        current_value={
            "violations": violation_count,
            "rows": row_count,
            "violation_pct": round(violation_pct, 6),
        },
        baseline_value=_rule_condition(rule),
        why_flagged=why,
        confidence="high",
        likely_impact=rule.likely_impact or "A declared business-data invariant is not satisfied.",
        suggested_investigation=(
            rule.suggested_investigation
            or "Inspect the upstream records and confirm whether the rule or source data changed."
        ),
    )


def _row_count_failure(rule: DataRule, row_count: int, why: str) -> Finding:
    return Finding(
        severity=rule.severity,
        detector=f"data_rule:{rule.id}",
        description=f"Data rule '{rule.name}' failed.",
        current_value={"row_count": row_count},
        baseline_value=_rule_condition(rule),
        why_flagged=why,
        confidence="high",
        likely_impact=rule.likely_impact or "A declared business-data invariant is not satisfied.",
        suggested_investigation=(
            rule.suggested_investigation
            or "Inspect the upstream records and confirm whether the rule or source data changed."
        ),
    )


def _missing_field(rule: DataRule, row_count: int) -> Finding:
    return _failure(
        rule,
        violation_count=row_count,
        row_count=row_count,
        why=f"Configured rule field '{rule.field}' is not present in the current dataset.",
    )


def evaluate_data_rules(frame: pd.DataFrame, rules: list[DataRule]) -> list[Finding]:
    """Evaluate explicit deterministic data rules without exposing failing row values."""
    findings: list[Finding] = []
    row_count = len(frame)

    for rule in rules:
        if rule.kind == DataRuleKind.ROW_COUNT_RANGE:
            below = rule.minimum is not None and row_count < rule.minimum
            above = rule.maximum is not None and row_count > rule.maximum
            if below or above:
                if below:
                    why = (
                        f"Row count {row_count} is below the configured minimum "
                        f"{int(rule.minimum)}."
                    )
                else:
                    why = (
                        f"Row count {row_count} exceeds the configured maximum "
                        f"{int(rule.maximum)}."
                    )
                findings.append(_row_count_failure(rule, row_count, why))
            continue

        field = rule.field
        if field is None:  # validated by DataRule; defensive for deserialized legacy input
            continue
        if field not in frame.columns:
            findings.append(_missing_field(rule, row_count))
            continue

        series = frame[field]
        if rule.kind == DataRuleKind.NOT_NULL:
            violations = int(series.isna().sum())
            if violations:
                findings.append(
                    _failure(
                        rule,
                        violation_count=violations,
                        row_count=row_count,
                        why=f"Field '{field}' contains {violations} null value(s).",
                    )
                )
            continue

        if rule.kind == DataRuleKind.ALLOWED_VALUES:
            normalized = series.astype("string")
            valid = normalized.isin(rule.allowed_values) & normalized.notna()
            violations = int((~valid).sum())
            if violations:
                findings.append(
                    _failure(
                        rule,
                        violation_count=violations,
                        row_count=row_count,
                        why=(
                            f"Field '{field}' contains {violations} value(s) outside the "
                            "configured allowed set."
                        ),
                    )
                )
            continue

        if rule.kind == DataRuleKind.NUMERIC_RANGE:
            numeric = pd.to_numeric(series, errors="coerce")
            valid = numeric.notna()
            if rule.minimum is not None:
                valid &= numeric >= rule.minimum
            if rule.maximum is not None:
                valid &= numeric <= rule.maximum
            violations = int((~valid).sum())
            if violations:
                bounds: list[str] = []
                if rule.minimum is not None:
                    bounds.append(f">= {rule.minimum:g}")
                if rule.maximum is not None:
                    bounds.append(f"<= {rule.maximum:g}")
                findings.append(
                    _failure(
                        rule,
                        violation_count=violations,
                        row_count=row_count,
                        why=(
                            f"Field '{field}' contains {violations} null, non-numeric, or "
                            f"out-of-range value(s); expected {' and '.join(bounds)}."
                        ),
                    )
                )
            continue

    return findings
