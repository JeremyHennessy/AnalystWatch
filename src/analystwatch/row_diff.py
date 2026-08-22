from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

import pandas as pd

from .models import (
    MonitoringConfig,
    Observation,
    RowChangedSample,
    RowDiffComparison,
    RowDiffEvidence,
    RowSample,
    RowSnapshot,
    RowSnapshotRow,
    RowValueChange,
)


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    return str(value)


def _key_token(key: dict[str, Any]) -> str:
    return json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_row_snapshot(
    dataframe: pd.DataFrame,
    config: MonitoringConfig,
) -> tuple[RowSnapshot | None, str | None]:
    key_fields = list(config.unique_keys)
    if not key_fields:
        return None, "Configure unique keys to enable row-level comparison."

    missing_keys = [field for field in key_fields if field not in dataframe.columns]
    if missing_keys:
        return None, f"Configured key fields are missing: {', '.join(missing_keys)}."
    if dataframe[key_fields].isna().any(axis=None):
        return None, "Row-level comparison requires non-null configured key values."
    if dataframe.duplicated(subset=key_fields, keep=False).any():
        return None, "Row-level comparison requires unique configured key values."
    if len(dataframe) > config.row_diff_max_rows:
        return (
            None,
            f"Dataset has {len(dataframe)} rows; row-level comparison limit is "
            f"{config.row_diff_max_rows}.",
        )

    requested_fields = (
        list(config.row_diff_fields) if config.row_diff_fields else list(dataframe.columns)
    )
    missing_fields = [field for field in requested_fields if field not in dataframe.columns]
    if missing_fields:
        return None, f"Configured row-diff fields are missing: {', '.join(missing_fields)}."

    value_fields: list[str] = []
    for field in [*key_fields, *requested_fields]:
        if field not in value_fields:
            value_fields.append(field)
    if len(value_fields) > config.row_diff_max_columns:
        return (
            None,
            f"Comparison would retain {len(value_fields)} columns; row-level comparison limit is "
            f"{config.row_diff_max_columns}.",
        )

    rows: list[RowSnapshotRow] = []
    for record in dataframe[value_fields].to_dict(orient="records"):
        normalized = {field: _normalize_value(record.get(field)) for field in value_fields}
        key = {field: normalized[field] for field in key_fields}
        values = {field: normalized[field] for field in value_fields if field not in key_fields}
        rows.append(RowSnapshotRow(key=key, values=values))

    payload = {
        "key_fields": key_fields,
        "value_fields": value_fields,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    serialized_bytes = len(serialized)
    if serialized_bytes > config.row_diff_max_snapshot_bytes:
        return (
            None,
            f"Comparison snapshot would use {serialized_bytes} bytes; limit is "
            f"{config.row_diff_max_snapshot_bytes} bytes.",
        )

    return (
        RowSnapshot(
            key_fields=key_fields,
            value_fields=value_fields,
            row_count=len(rows),
            serialized_bytes=serialized_bytes,
            rows=rows,
        ),
        None,
    )


def compare_row_snapshots(
    current: RowSnapshot,
    reference: RowSnapshot,
    *,
    reference_observation_id: str,
    reference_label: str,
    sample_limit: int,
) -> RowDiffComparison:
    if current.key_fields != reference.key_fields:
        raise ValueError("Row snapshots use different key fields")

    current_rows = {_key_token(row.key): row for row in current.rows}
    reference_rows = {_key_token(row.key): row for row in reference.rows}
    current_tokens = set(current_rows)
    reference_tokens = set(reference_rows)
    added_tokens = sorted(current_tokens - reference_tokens)
    removed_tokens = sorted(reference_tokens - current_tokens)
    common_tokens = sorted(current_tokens & reference_tokens)

    changed_columns: dict[str, int] = {}
    changed_samples: list[RowChangedSample] = []
    changed_count = 0
    unchanged_count = 0
    for token in common_tokens:
        current_row = current_rows[token]
        reference_row = reference_rows[token]
        changes: dict[str, RowValueChange] = {}
        for field in sorted(set(current_row.values) | set(reference_row.values)):
            previous_value = reference_row.values.get(field)
            current_value = current_row.values.get(field)
            if previous_value != current_value:
                changed_columns[field] = changed_columns.get(field, 0) + 1
                changes[field] = RowValueChange(
                    previous=previous_value,
                    current=current_value,
                )
        if changes:
            changed_count += 1
            if len(changed_samples) < sample_limit:
                changed_samples.append(RowChangedSample(key=current_row.key, changes=changes))
        else:
            unchanged_count += 1

    added_samples = [
        RowSample(key=current_rows[token].key, values=current_rows[token].values)
        for token in added_tokens[:sample_limit]
    ]
    removed_samples = [
        RowSample(key=reference_rows[token].key, values=reference_rows[token].values)
        for token in removed_tokens[:sample_limit]
    ]

    return RowDiffComparison(
        reference_observation_id=reference_observation_id,
        reference_label=reference_label,
        added_count=len(added_tokens),
        removed_count=len(removed_tokens),
        changed_count=changed_count,
        unchanged_count=unchanged_count,
        changed_columns=dict(
            sorted(changed_columns.items(), key=lambda item: (-item[1], item[0]))
        ),
        added_samples=added_samples,
        removed_samples=removed_samples,
        changed_samples=changed_samples,
    )


def build_row_diff_evidence(
    current_snapshot: RowSnapshot | None,
    snapshot_reason: str | None,
    *,
    key_fields: list[str],
    previous_successful: Observation | None,
    baseline: Observation | None,
    sample_limit: int,
) -> RowDiffEvidence:
    evidence = RowDiffEvidence(
        key_fields=key_fields,
        snapshot_available=current_snapshot is not None,
        snapshot_reason=snapshot_reason,
    )
    if current_snapshot is None:
        return evidence

    if previous_successful and previous_successful.row_snapshot is not None:
        try:
            evidence.previous = compare_row_snapshots(
                current_snapshot,
                previous_successful.row_snapshot,
                reference_observation_id=previous_successful.id,
                reference_label="previous successful",
                sample_limit=sample_limit,
            )
        except ValueError:
            pass
    if baseline and baseline.row_snapshot is not None:
        try:
            evidence.baseline = compare_row_snapshots(
                current_snapshot,
                baseline.row_snapshot,
                reference_observation_id=baseline.id,
                reference_label="active baseline",
                sample_limit=sample_limit,
            )
        except ValueError:
            pass
    return evidence


def strip_row_diff_raw_payloads(observation: Observation) -> Observation:
    row_diff = observation.row_diff
    if row_diff is not None:
        updates: dict[str, RowDiffComparison | None] = {}
        for field in ("previous", "baseline"):
            comparison = getattr(row_diff, field)
            if comparison is not None:
                updates[field] = comparison.model_copy(
                    update={
                        "added_samples": [],
                        "removed_samples": [],
                        "changed_samples": [],
                    }
                )
        row_diff = row_diff.model_copy(update=updates)
    return observation.model_copy(update={"row_snapshot": None, "row_diff": row_diff})
