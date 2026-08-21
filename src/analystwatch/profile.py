from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from .models import ColumnProfile, DatasetProfile, NumericStats

_DATE_FIELD_PRIORITY = (
    "last_updated",
    "last_modified",
    "updated_at",
    "modified_at",
    "as_of",
    "snapshot_date",
    "report_date",
    "effective_date",
    "timestamp",
    "datetime",
    "date",
)


def _finite(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _dtype_kind(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "text"


def _numeric_stats(series: pd.Series) -> NumericStats:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return NumericStats()
    quantiles = numeric.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return NumericStats(
        minimum=_finite(numeric.min()),
        maximum=_finite(numeric.max()),
        mean=_finite(numeric.mean()),
        median=_finite(quantiles.loc[0.5]),
        stddev=_finite(numeric.std(ddof=1)) if len(numeric) > 1 else 0.0,
        p05=_finite(quantiles.loc[0.05]),
        p25=_finite(quantiles.loc[0.25]),
        p75=_finite(quantiles.loc[0.75]),
        p95=_finite(quantiles.loc[0.95]),
    )


def _category_frequencies(series: pd.Series, row_count: int) -> dict[str, float] | None:
    non_null = series.dropna()
    if non_null.empty:
        return {}
    unique_count = int(non_null.nunique(dropna=True))
    if unique_count > min(50, max(20, row_count // 2)):
        return None
    frequencies = non_null.astype(str).value_counts(normalize=True).head(20)
    return {str(key): float(value) for key, value in frequencies.items()}


def _normalized_field_name(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _candidate_date_field(frame: pd.DataFrame) -> str | None:
    normalized = {_normalized_field_name(name): str(name) for name in frame.columns}
    for candidate in _DATE_FIELD_PRIORITY:
        if candidate not in normalized:
            continue
        field = normalized[candidate]
        series = frame[field]
        non_null = series.dropna()
        if non_null.empty:
            continue
        parsed = pd.to_datetime(non_null, errors="coerce", utc=True)
        if float(parsed.notna().mean()) >= 0.80:
            return field
    return None


def profile_dataframe(
    frame: pd.DataFrame,
    latest_date_field: str | None = None,
    *,
    infer_latest_date_field: bool = False,
    numeric_fields: list[str] | None = None,
) -> DatasetProfile:
    row_count = len(frame)
    columns: dict[str, ColumnProfile] = {}
    forced_numeric = set(numeric_fields or [])

    for name in frame.columns:
        raw_series = frame[name]
        field_name = str(name)
        if field_name in forced_numeric:
            series = pd.to_numeric(raw_series, errors="coerce")
            dtype = "numeric"
        else:
            series = raw_series
            dtype = _dtype_kind(series)
        null_count = int(series.isna().sum())
        non_null_count = max(row_count - null_count, 0)
        unique_count = int(series.nunique(dropna=True))
        duplicate_count = max(non_null_count - unique_count, 0)
        duplicate_pct = duplicate_count / non_null_count if non_null_count else 0.0

        columns[field_name] = ColumnProfile(
            dtype=dtype,
            null_count=null_count,
            null_pct=(null_count / row_count) if row_count else 0.0,
            unique_count=unique_count,
            duplicate_pct=duplicate_pct,
            numeric=_numeric_stats(series) if dtype == "numeric" else None,
            category_frequencies=(
                _category_frequencies(series, row_count) if dtype in {"text", "boolean"} else None
            ),
        )

    resolved_date_field = latest_date_field
    if resolved_date_field is None and infer_latest_date_field:
        resolved_date_field = _candidate_date_field(frame)

    latest_date = None
    if resolved_date_field and resolved_date_field in frame.columns:
        parsed = pd.to_datetime(frame[resolved_date_field], errors="coerce", utc=True).dropna()
        if not parsed.empty:
            latest_date = parsed.max().to_pydatetime()

    return DatasetProfile(
        row_count=row_count,
        column_count=len(frame.columns),
        columns=columns,
        latest_date=latest_date,
        latest_date_field=resolved_date_field if latest_date is not None else None,
    )
