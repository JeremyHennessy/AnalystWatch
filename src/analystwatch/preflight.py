from __future__ import annotations

from datetime import datetime
from typing import Literal

import httpx
import pandas as pd
from pydantic import BaseModel, Field

from .data_rules import evaluate_data_rules
from .detectors import detect_freshness
from .ingest import ingest_source
from .models import DatasetProfile, HealthStatus, SourceDefinition
from .profile import profile_dataframe


class ContractIssue(BaseModel):
    level: Literal["error", "warning", "info"]
    code: str
    message: str
    field: str | None = None


class SourcePreflight(BaseModel):
    source: SourceDefinition
    ready: bool
    accepted: bool = False
    available: bool
    profile: DatasetProfile | None = None
    http_status: int | None = None
    response_ms: float | None = None
    source_modified_at: datetime | None = None
    issues: list[ContractIssue] = Field(default_factory=list)


def _issue(
    level: Literal["error", "warning", "info"],
    code: str,
    message: str,
    field: str | None = None,
) -> ContractIssue:
    return ContractIssue(level=level, code=code, message=message, field=field)


def preflight_source(
    source: SourceDefinition,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> SourcePreflight:
    """Inspect one source without persisting it or creating a baseline."""
    result = ingest_source(source, client=client)
    if not result.available or result.dataframe is None:
        return SourcePreflight(
            source=source,
            ready=False,
            available=False,
            http_status=result.http_status,
            response_ms=result.response_ms,
            source_modified_at=result.source_modified_at,
            issues=[
                _issue(
                    "error",
                    "availability",
                    result.error or "The source returned no usable dataset.",
                )
            ],
        )

    frame = result.dataframe
    profile = profile_dataframe(
        frame,
        source.config.latest_date_field,
        infer_latest_date_field=source.config.infer_latest_date_field,
        numeric_fields=source.config.numeric_fields,
    )
    issues: list[ContractIssue] = []

    if profile.row_count == 0:
        issues.append(_issue("error", "empty_dataset", "The source returned zero records."))

    for field in source.config.numeric_fields:
        if field not in frame.columns:
            issues.append(
                _issue(
                    "error",
                    "numeric_field_missing",
                    f"Configured numeric field '{field}' is not present.",
                    field,
                )
            )
            continue
        raw = frame[field]
        raw_non_null = int(raw.notna().sum())
        if raw_non_null == 0:
            issues.append(
                _issue(
                    "error",
                    "numeric_field_empty",
                    f"Configured numeric field '{field}' has no non-null values to validate.",
                    field,
                )
            )
            continue
        parsed = pd.to_numeric(raw, errors="coerce")
        parsed_non_null = int(parsed.notna().sum())
        parse_rate = parsed_non_null / raw_non_null
        if parse_rate < 0.95:
            issues.append(
                _issue(
                    "error",
                    "numeric_parse_rate",
                    (
                        f"Only {parse_rate:.1%} of non-null values in '{field}' parse as numeric; "
                        "at least 95% is required for this contract."
                    ),
                    field,
                )
            )
        elif parse_rate < 1.0:
            issues.append(
                _issue(
                    "warning",
                    "numeric_parse_partial",
                    f"{parse_rate:.1%} of non-null values in '{field}' parse as numeric.",
                    field,
                )
            )

    for field in source.config.unique_keys:
        if field not in frame.columns:
            issues.append(
                _issue(
                    "error",
                    "unique_key_missing",
                    f"Configured unique key '{field}' is not present.",
                    field,
                )
            )
            continue
        series = frame[field]
        null_count = int(series.isna().sum())
        if null_count:
            issues.append(
                _issue(
                    "error",
                    "unique_key_nulls",
                    f"Configured unique key '{field}' contains {null_count} null value(s).",
                    field,
                )
            )
        duplicate_rows = int(series.dropna().duplicated(keep=False).sum())
        if duplicate_rows:
            issues.append(
                _issue(
                    "error",
                    "unique_key_duplicates",
                    (
                        f"Configured unique key '{field}' is not unique; "
                        f"{duplicate_rows} row(s) participate in duplicates."
                    ),
                    field,
                )
            )

    for rule in source.config.data_rules:
        rule_findings = evaluate_data_rules(frame, [rule])
        for finding in rule_findings:
            issues.append(
                _issue(
                    "error",
                    "data_rule_failed",
                    f"{finding.description} {finding.why_flagged}",
                    rule.field,
                )
            )

    freshness_evidence = profile.latest_date or result.source_modified_at
    if source.config.latest_date_field:
        if source.config.latest_date_field not in frame.columns:
            issues.append(
                _issue(
                    "error",
                    "freshness_field_missing",
                    (
                        f"Configured freshness field '{source.config.latest_date_field}' "
                        "is not present."
                    ),
                    source.config.latest_date_field,
                )
            )
        elif profile.latest_date is None:
            issues.append(
                _issue(
                    "error",
                    "freshness_field_unparseable",
                    (
                        f"Configured freshness field '{source.config.latest_date_field}' "
                        "contains no parseable dates."
                    ),
                    source.config.latest_date_field,
                )
            )

    if source.config.expected_refresh_minutes is not None and freshness_evidence is None:
        issues.append(
            _issue(
                "error",
                "freshness_unverifiable",
                (
                    "A refresh expectation is configured, but the source exposes no usable "
                    "content date or modification timestamp."
                ),
            )
        )
    elif source.config.expected_refresh_minutes is not None:
        observed_at = now or datetime.now().astimezone()
        freshness_findings = detect_freshness(
            config=source.config,
            profile=profile,
            source_modified_at=result.source_modified_at,
            observed_at=observed_at,
        )
        for finding in freshness_findings:
            level: Literal["error", "warning", "info"] = (
                "warning"
                if finding.severity in {HealthStatus.WARNING, HealthStatus.CRITICAL}
                else "info"
            )
            issues.append(
                _issue(
                    level,
                    "freshness_signal",
                    f"Current data freshness: {finding.description} {finding.why_flagged}",
                    profile.latest_date_field,
                )
            )

    ready = not any(issue.level == "error" for issue in issues)
    return SourcePreflight(
        source=source,
        ready=ready,
        available=True,
        profile=profile,
        http_status=result.http_status,
        response_ms=result.response_ms,
        source_modified_at=result.source_modified_at,
        issues=issues,
    )
