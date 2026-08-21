from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SourceType(str, Enum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"
    API = "api"


class HealthStatus(str, Enum):
    HEALTHY = "Healthy"
    WARNING = "Warning"
    CRITICAL = "Critical"


class MonitoringConfig(BaseModel):
    expected_refresh_minutes: int | None = Field(default=None, gt=0)
    latest_date_field: str | None = None
    sheet_name: str | int | None = None
    json_record_path: str | None = None
    unique_keys: list[str] = Field(default_factory=list)
    request_timeout_seconds: float = Field(default=10.0, gt=0)

    warning_row_change_pct: float = Field(default=0.25, ge=0)
    critical_row_change_pct: float = Field(default=0.50, ge=0)
    warning_null_increase_pct: float = Field(default=0.10, ge=0)
    critical_null_increase_pct: float = Field(default=0.25, ge=0)
    warning_numeric_factor: float = Field(default=2.0, gt=1)
    critical_numeric_factor: float = Field(default=10.0, gt=1)
    warning_category_tvd: float = Field(default=0.20, ge=0, le=1)
    critical_category_tvd: float = Field(default=0.60, ge=0, le=1)
    material_category_frequency: float = Field(default=0.10, ge=0, le=1)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "MonitoringConfig":
        if self.warning_row_change_pct > self.critical_row_change_pct:
            raise ValueError("warning_row_change_pct must not exceed critical_row_change_pct")
        if self.warning_null_increase_pct > self.critical_null_increase_pct:
            raise ValueError("warning_null_increase_pct must not exceed critical_null_increase_pct")
        if self.warning_numeric_factor > self.critical_numeric_factor:
            raise ValueError("warning_numeric_factor must not exceed critical_numeric_factor")
        if self.warning_category_tvd > self.critical_category_tvd:
            raise ValueError("warning_category_tvd must not exceed critical_category_tvd")
        return self


class SourceDefinition(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1)
    source_type: SourceType
    location: str = Field(min_length=1)
    enabled: bool = True
    config: MonitoringConfig = Field(default_factory=MonitoringConfig)


class NumericStats(BaseModel):
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    p05: float | None = None
    p25: float | None = None
    p75: float | None = None
    p95: float | None = None


class ColumnProfile(BaseModel):
    dtype: str
    null_count: int
    null_pct: float
    unique_count: int
    duplicate_pct: float
    numeric: NumericStats | None = None
    category_frequencies: dict[str, float] | None = None


class DatasetProfile(BaseModel):
    row_count: int
    column_count: int
    columns: dict[str, ColumnProfile]
    latest_date: datetime | None = None


class Finding(BaseModel):
    severity: HealthStatus
    detector: str
    description: str
    current_value: Any = None
    baseline_value: Any = None
    why_flagged: str
    confidence: str | None = None
    likely_impact: str | None = None
    suggested_investigation: str | None = None


class Observation(BaseModel):
    id: str
    source_id: str
    observed_at: datetime
    available: bool
    health: HealthStatus
    findings: list[Finding] = Field(default_factory=list)
    profile: DatasetProfile | None = None
    http_status: int | None = None
    response_ms: float | None = None
    source_modified_at: datetime | None = None
    error: str | None = None
    is_baseline: bool = False
