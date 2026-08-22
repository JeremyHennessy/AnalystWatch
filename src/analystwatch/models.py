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
    MICROSOFT_EXCEL = "microsoft_excel"


class HealthStatus(str, Enum):
    HEALTHY = "Healthy"
    WARNING = "Warning"
    CRITICAL = "Critical"


class ObservationReviewState(str, Enum):
    ACKNOWLEDGED = "Acknowledged"
    REVIEWED = "Reviewed"


class IncidentStatus(str, Enum):
    OPEN = "Open"
    RECOVERED = "Recovered"


class IncidentTransition(str, Enum):
    OPENED = "Opened"
    ESCALATED = "Escalated"
    RECOVERED = "Recovered"


class NotificationCandidateState(str, Enum):
    PENDING = "Pending"
    ELIGIBLE = "Eligible"
    SUPPRESSED = "Suppressed"


class DeliveryAttemptState(str, Enum):
    PREPARED = "Prepared"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"


class DeliveryReconciliationOutcome(str, Enum):
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"


class DeliveryMode(str, Enum):
    DRY_RUN = "dry-run"
    LIVE = "live"


class MonitoringConfig(BaseModel):
    expected_refresh_minutes: int | None = Field(default=None, gt=0)
    monitor_interval_minutes: int = Field(default=60, gt=0)
    latest_date_field: str | None = None
    infer_latest_date_field: bool = False
    sheet_name: str | int | None = None
    json_record_path: str | None = None
    unique_keys: list[str] = Field(default_factory=list)
    numeric_fields: list[str] = Field(default_factory=list)
    request_header_env: dict[str, str] = Field(default_factory=dict)
    notification_transitions: list[IncidentTransition] = Field(default_factory=list)
    delivery_retry_minutes: int = Field(default=0, ge=0)
    request_timeout_seconds: float = Field(default=10.0, gt=0)

    history_window_size: int = Field(default=5, ge=3, le=50)
    min_history_observations: int = Field(default=3, ge=2, le=50)

    row_diff_fields: list[str] = Field(default_factory=list)
    row_diff_max_rows: int = Field(default=5000, ge=1, le=50000)
    row_diff_max_columns: int = Field(default=50, ge=1, le=200)
    row_diff_max_snapshot_bytes: int = Field(default=1_000_000, ge=1024, le=25_000_000)
    row_diff_sample_limit: int = Field(default=20, ge=0, le=100)
    row_diff_snapshot_retention: int = Field(default=2, ge=1, le=10)

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
        if self.min_history_observations > self.history_window_size:
            raise ValueError("min_history_observations must not exceed history_window_size")
        for field_name, values in (
            ("unique_keys", self.unique_keys),
            ("numeric_fields", self.numeric_fields),
            ("row_diff_fields", self.row_diff_fields),
        ):
            if any(not value or value != value.strip() for value in values):
                raise ValueError(f"{field_name} values must be non-empty and trimmed")
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
        for header, env_name in self.request_header_env.items():
            if not header or header != header.strip():
                raise ValueError("request_header_env header names must be non-empty and trimmed")
            if not env_name or env_name != env_name.strip():
                raise ValueError(
                    "request_header_env environment variable names must be non-empty and trimmed"
                )
        if len(set(self.notification_transitions)) != len(self.notification_transitions):
            raise ValueError("notification_transitions must not contain duplicates")
        return self


class SourceDefinition(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    workspace_id: str = Field(default="local", min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
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
    latest_date_field: str | None = None


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


class RowSnapshotRow(BaseModel):
    key: dict[str, Any]
    values: dict[str, Any]


class RowSnapshot(BaseModel):
    key_fields: list[str]
    value_fields: list[str]
    row_count: int
    serialized_bytes: int
    rows: list[RowSnapshotRow] = Field(default_factory=list)


class RowSample(BaseModel):
    key: dict[str, Any]
    values: dict[str, Any] = Field(default_factory=dict)


class RowValueChange(BaseModel):
    previous: Any = None
    current: Any = None


class RowChangedSample(BaseModel):
    key: dict[str, Any]
    changes: dict[str, RowValueChange] = Field(default_factory=dict)


class RowDiffComparison(BaseModel):
    reference_observation_id: str
    reference_label: str
    added_count: int = 0
    removed_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    changed_columns: dict[str, int] = Field(default_factory=dict)
    added_samples: list[RowSample] = Field(default_factory=list)
    removed_samples: list[RowSample] = Field(default_factory=list)
    changed_samples: list[RowChangedSample] = Field(default_factory=list)


class RowDiffEvidence(BaseModel):
    key_fields: list[str]
    snapshot_available: bool
    snapshot_reason: str | None = None
    previous: RowDiffComparison | None = None
    baseline: RowDiffComparison | None = None


class Observation(BaseModel):
    id: str
    source_id: str
    observed_at: datetime
    available: bool
    health: HealthStatus
    findings: list[Finding] = Field(default_factory=list)
    profile: DatasetProfile | None = None
    row_snapshot: RowSnapshot | None = None
    row_diff: RowDiffEvidence | None = None
    http_status: int | None = None
    response_ms: float | None = None
    source_modified_at: datetime | None = None
    response_etag: str | None = None
    error: str | None = None
    is_baseline: bool = False


class RunDecision(BaseModel):
    source_id: str
    due: bool
    reason: str
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None


class ObservationReview(BaseModel):
    observation_id: str
    source_id: str
    state: ObservationReviewState
    updated_at: datetime


class BaselineReview(BaseModel):
    source_id: str
    current_baseline: Observation | None = None
    candidate: Observation | None = None
    ready: bool
    blockers: list[str] = Field(default_factory=list)


class IncidentSnapshot(BaseModel):
    source_id: str
    status: IncidentStatus
    opened_observation_id: str
    opened_at: datetime
    latest_incident_observation_id: str
    updated_at: datetime
    current_health: HealthStatus
    peak_health: HealthStatus
    observation_count: int
    recovered_observation_id: str | None = None
    recovered_at: datetime | None = None


class NotificationCandidate(BaseModel):
    id: str
    source_id: str
    observation_id: str
    transition: IncidentTransition
    previous_health: HealthStatus | None = None
    current_health: HealthStatus
    created_at: datetime
    reason: str
    state: NotificationCandidateState = NotificationCandidateState.PENDING
    evaluated_at: datetime | None = None
    policy_enabled_transitions: list[IncidentTransition] = Field(default_factory=list)
    policy_reason: str | None = None


class DeliveryAttempt(BaseModel):
    id: str
    candidate_id: str
    source_id: str
    adapter: str = Field(min_length=1)
    mode: DeliveryMode = DeliveryMode.DRY_RUN
    idempotency_key: str = Field(min_length=1)
    attempt_number: int = Field(ge=1)
    state: DeliveryAttemptState
    created_at: datetime
    claim_owner: str | None = None
    completed_at: datetime | None = None
    result_summary: str | None = None
    error: str | None = None
    reconciled_at: datetime | None = None
    reconciled_by: str | None = None
    reconciliation_note: str | None = None


class DeliveryRetryDecision(BaseModel):
    candidate_id: str
    due: bool
    reason: str
    last_attempt_id: str | None = None
    last_state: DeliveryAttemptState | None = None
    next_retry_at: datetime | None = None


class StorageVerification(BaseModel):
    storage_id: str | None = None
    schema_version: int | None = None
    integrity_ok: bool
    integrity_message: str
    source_count: int = 0
    observation_count: int = 0
    review_count: int = 0
    notification_candidate_count: int = 0
    delivery_attempt_count: int = 0


class StorageSnapshotResult(BaseModel):
    snapshot_path: str
    verification: StorageVerification
