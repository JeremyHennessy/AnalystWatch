from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .models import DatasetProfile, Finding, HealthStatus, MonitoringConfig


def _finding(
    severity: HealthStatus,
    detector: str,
    description: str,
    current_value: object,
    baseline_value: object,
    why: str,
    *,
    confidence: str = "high",
    impact: str | None = None,
    investigation: str | None = None,
) -> Finding:
    return Finding(
        severity=severity,
        detector=detector,
        description=description,
        current_value=current_value,
        baseline_value=baseline_value,
        why_flagged=why,
        confidence=confidence,
        likely_impact=impact,
        suggested_investigation=investigation,
    )


def detect_profile_changes(
    baseline: DatasetProfile,
    current: DatasetProfile,
    config: MonitoringConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_detect_schema(baseline, current))
    findings.extend(_detect_row_count(baseline, current, config))
    findings.extend(_detect_nulls(baseline, current, config))
    findings.extend(_detect_numeric(baseline, current, config))
    findings.extend(_detect_categories(baseline, current, config))
    findings.extend(_detect_uniqueness(baseline, current, config))
    return findings


def detect_freshness(
    *,
    config: MonitoringConfig,
    profile: DatasetProfile,
    source_modified_at: datetime | None,
    observed_at: datetime,
) -> list[Finding]:
    if config.expected_refresh_minutes is None:
        return []

    evidence_time = profile.latest_date if config.latest_date_field else source_modified_at
    evidence_label = config.latest_date_field or "source modification time"
    if evidence_time is None:
        return [
            _finding(
                HealthStatus.WARNING,
                "freshness",
                "Freshness could not be established from the configured source evidence.",
                None,
                f"expected refresh every {config.expected_refresh_minutes} minutes",
                f"No usable {evidence_label} was available.",
                confidence="high",
                investigation="Configure a latest_date_field for APIs or verify source timestamps.",
            )
        ]

    now = observed_at.astimezone(timezone.utc)
    evidence_time = evidence_time.astimezone(timezone.utc)
    age_minutes = max((now - evidence_time).total_seconds() / 60, 0.0)
    threshold = float(config.expected_refresh_minutes)
    if age_minutes <= threshold:
        return []
    severity = HealthStatus.CRITICAL if age_minutes >= threshold * 2 else HealthStatus.WARNING
    return [
        _finding(
            severity,
            "freshness",
            f"Source appears stale based on {evidence_label}.",
            round(age_minutes, 1),
            threshold,
            (
                f"Age is {age_minutes:.1f} minutes; expected refresh interval is "
                f"{threshold:.1f} minutes."
            ),
            impact="Dependent analysis may be using outdated data.",
            investigation=(
                "Confirm the upstream refresh completed and that the freshness field is correct."
            ),
        )
    ]


def health_from_findings(findings: Iterable[Finding]) -> HealthStatus:
    severities = {finding.severity for finding in findings}
    if HealthStatus.CRITICAL in severities:
        return HealthStatus.CRITICAL
    if HealthStatus.WARNING in severities:
        return HealthStatus.WARNING
    return HealthStatus.HEALTHY


def _detect_schema(baseline: DatasetProfile, current: DatasetProfile) -> list[Finding]:
    findings: list[Finding] = []
    baseline_names = set(baseline.columns)
    current_names = set(current.columns)
    removed = sorted(baseline_names - current_names)
    added = sorted(current_names - baseline_names)
    if removed:
        findings.append(
            _finding(
                HealthStatus.CRITICAL,
                "schema",
                f"Removed columns: {', '.join(removed)}",
                sorted(current_names),
                sorted(baseline_names),
                "One or more baseline columns are missing from the current source.",
                impact="Downstream calculations may fail or silently omit required fields.",
                investigation="Confirm whether the upstream schema changed intentionally.",
            )
        )
    if added:
        findings.append(
            _finding(
                HealthStatus.WARNING,
                "schema",
                f"Added columns: {', '.join(added)}",
                sorted(current_names),
                sorted(baseline_names),
                "The current source contains columns that were not present in the baseline.",
                investigation="Review whether downstream mappings should include the new fields.",
            )
        )
    for name in sorted(baseline_names & current_names):
        before = baseline.columns[name].dtype
        after = current.columns[name].dtype
        if before != after:
            findings.append(
                _finding(
                    HealthStatus.WARNING,
                    "schema",
                    f"Type changed for '{name}': {before} → {after}",
                    after,
                    before,
                    "The inferred data type differs from the baseline.",
                    investigation="Inspect raw values and confirm the change is intentional.",
                )
            )
    return findings


def _detect_row_count(
    baseline: DatasetProfile,
    current: DatasetProfile,
    config: MonitoringConfig,
) -> list[Finding]:
    if baseline.row_count == 0:
        if current.row_count == 0:
            return []
        return [
            _finding(
                HealthStatus.WARNING,
                "row_count",
                "Row count changed from an empty baseline.",
                current.row_count,
                baseline.row_count,
                "The baseline had zero rows, so percentage drift is undefined.",
            )
        ]
    change = abs(current.row_count - baseline.row_count) / baseline.row_count
    if change < config.warning_row_change_pct:
        return []
    severity = (
        HealthStatus.CRITICAL
        if change >= config.critical_row_change_pct
        else HealthStatus.WARNING
    )
    return [
        _finding(
            severity,
            "row_count",
            f"Row count changed by {change:.1%}.",
            current.row_count,
            baseline.row_count,
            (
                f"Absolute row-count change {change:.1%} exceeds the "
                f"{config.warning_row_change_pct:.1%} warning threshold."
            ),
            impact="The source may be incomplete, truncated, or unexpectedly expanded.",
            investigation="Compare upstream extraction scope and date coverage.",
        )
    ]


def _detect_nulls(
    baseline: DatasetProfile,
    current: DatasetProfile,
    config: MonitoringConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    for name in sorted(set(baseline.columns) & set(current.columns)):
        before = baseline.columns[name].null_pct
        after = current.columns[name].null_pct
        increase = after - before
        if increase < config.warning_null_increase_pct:
            continue
        severity = (
            HealthStatus.CRITICAL
            if increase >= config.critical_null_increase_pct
            else HealthStatus.WARNING
        )
        findings.append(
            _finding(
                severity,
                "null_rate",
                f"Null rate increased materially for '{name}'.",
                round(after, 4),
                round(before, 4),
                (
                    f"Null rate increased by {increase:.1%}, above the "
                    f"{config.warning_null_increase_pct:.1%} warning threshold."
                ),
                impact="Missing values may bias or break dependent analysis.",
                investigation="Inspect upstream population logic for this field.",
            )
        )
    return findings


def _detect_numeric(
    baseline: DatasetProfile,
    current: DatasetProfile,
    config: MonitoringConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    for name in sorted(set(baseline.columns) & set(current.columns)):
        before_stats = baseline.columns[name].numeric
        after_stats = current.columns[name].numeric
        if not before_stats or not after_stats:
            continue
        before = before_stats.median
        after = after_stats.median
        if before is None or after is None:
            continue

        factor: float | None = None
        if abs(before) > 1e-12 and abs(after) > 1e-12 and before * after > 0:
            factor = max(abs(after / before), abs(before / after))
        if factor is not None and factor >= config.warning_numeric_factor:
            severity = (
                HealthStatus.CRITICAL
                if factor >= config.critical_numeric_factor
                else HealthStatus.WARNING
            )
            findings.append(
                _finding(
                    severity,
                    "numeric_drift",
                    f"Significant numeric distribution change detected in '{name}'.",
                    round(after, 6),
                    round(before, 6),
                    f"Median magnitude changed by a factor of {factor:.2f}.",
                    confidence="high" if factor >= config.critical_numeric_factor else "medium",
                    impact="Possible scaling/unit change, partial data, or data corruption.",
                    investigation=(
                        "Review source units and upstream transformations before trusting "
                        "dependent outputs."
                    ),
                )
            )
            continue

        stddev = before_stats.stddev or 0.0
        relative_shift = (abs(after - before) / abs(before)) if abs(before) > 1e-12 else None
        z_shift_is_material = relative_shift is None or relative_shift >= 0.20
        if stddev > 0 and z_shift_is_material:
            z_shift = abs(after - before) / stddev
            if z_shift >= 3.0:
                severity = HealthStatus.CRITICAL if z_shift >= 5.0 else HealthStatus.WARNING
                findings.append(
                    _finding(
                        severity,
                        "numeric_drift",
                        f"Median shifted materially for '{name}'.",
                        round(after, 6),
                        round(before, 6),
                        f"Median shift is {z_shift:.2f} baseline standard deviations.",
                        confidence="medium",
                        impact="Numeric behaviour differs substantially from the baseline.",
                        investigation="Inspect the distribution and upstream transformation logic.",
                    )
                )
    return findings


def _detect_categories(
    baseline: DatasetProfile,
    current: DatasetProfile,
    config: MonitoringConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    for name in sorted(set(baseline.columns) & set(current.columns)):
        before = baseline.columns[name].category_frequencies
        after = current.columns[name].category_frequencies
        if before is None or after is None:
            continue
        keys = set(before) | set(after)
        if not keys:
            continue
        tvd = 0.5 * sum(abs(before.get(key, 0.0) - after.get(key, 0.0)) for key in keys)
        disappeared = sorted(
            key
            for key, freq in before.items()
            if freq >= config.material_category_frequency and after.get(key, 0.0) == 0
        )
        appeared = sorted(
            key
            for key, freq in after.items()
            if freq >= config.material_category_frequency and before.get(key, 0.0) == 0
        )
        if not disappeared and not appeared and tvd < config.warning_category_tvd:
            continue
        severity = (
            HealthStatus.CRITICAL
            if tvd >= config.critical_category_tvd
            else HealthStatus.WARNING
        )
        details: list[str] = []
        if disappeared:
            details.append(f"disappeared: {', '.join(disappeared)}")
        if appeared:
            details.append(f"new: {', '.join(appeared)}")
        if not details:
            details.append(f"distribution distance: {tvd:.2f}")
        findings.append(
            _finding(
                severity,
                "categorical_drift",
                f"Categorical behaviour changed for '{name}' ({'; '.join(details)}).",
                {"distribution": after, "tvd": round(tvd, 4)},
                {"distribution": before, "tvd": 0.0},
                (
                    f"Total variation distance is {tvd:.2f} and/or a material category "
                    "changed presence."
                ),
                confidence="medium",
                impact="Filters, segment totals, or business logic may behave differently.",
                investigation="Confirm category changes with the upstream source owner.",
            )
        )
    return findings


def _detect_uniqueness(
    baseline: DatasetProfile,
    current: DatasetProfile,
    config: MonitoringConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    for name in config.unique_keys:
        if name not in baseline.columns or name not in current.columns:
            continue
        before = baseline.columns[name].duplicate_pct
        after = current.columns[name].duplicate_pct
        increase = after - before
        if after < 0.02 or increase < 0.02:
            continue
        severity = HealthStatus.CRITICAL if after >= 0.10 else HealthStatus.WARNING
        findings.append(
            _finding(
                severity,
                "uniqueness",
                f"Configured key '{name}' is no longer reliably unique.",
                round(after, 4),
                round(before, 4),
                f"Duplicate rate increased by {increase:.1%} to {after:.1%}.",
                impact="Joins or record-level assumptions may duplicate or overwrite data.",
                investigation="Inspect duplicate key values and upstream record generation.",
            )
        )
    return findings
