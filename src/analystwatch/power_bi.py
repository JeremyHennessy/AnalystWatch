from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, field_validator

from .models import HealthStatus
from .workspace import DEFAULT_WORKSPACE_ID, validate_workspace_id

POWER_BI_ROOT = "https://api.powerbi.com/v1.0/myorg"


class PowerBIGuardDefinition(BaseModel):
    id: str
    workspace_id: str = DEFAULT_WORKSPACE_ID
    name: str
    power_bi_workspace_id: str
    dataset_id: str
    auth_token_env: str
    upstream_source_ids: list[str] = Field(default_factory=list)
    refresh_history_limit: int = Field(default=20, ge=1, le=60)
    enabled: bool = True

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        return validate_workspace_id(value)

    @field_validator(
        "id",
        "name",
        "power_bi_workspace_id",
        "dataset_id",
        "auth_token_env",
    )
    @classmethod
    def require_trimmed_value(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("upstream_source_ids")
    @classmethod
    def normalize_upstream_sources(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("upstream source IDs must not be empty")
            if cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class PowerBIRefreshEvidence(BaseModel):
    request_id: str | None = None
    refresh_type: str | None = None
    status: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: float | None = None


class PowerBIReportEvidence(BaseModel):
    id: str
    name: str
    web_url: str | None = None


class PowerBIDatasourceEvidence(BaseModel):
    datasource_type: str


class PowerBIUpstreamEvidence(BaseModel):
    source_id: str
    health: HealthStatus | None = None


class PowerBIGuardSnapshot(BaseModel):
    guard_id: str
    checked_at: datetime
    available: bool
    health: HealthStatus
    trust_case: str
    summary: str
    power_bi_workspace_name: str | None = None
    semantic_model_name: str | None = None
    is_refreshable: bool | None = None
    latest_refresh: PowerBIRefreshEvidence | None = None
    refresh_history: list[PowerBIRefreshEvidence] = Field(default_factory=list)
    reports: list[PowerBIReportEvidence] = Field(default_factory=list)
    datasource_types: dict[str, int] = Field(default_factory=dict)
    upstream: list[PowerBIUpstreamEvidence] = Field(default_factory=list)
    evidence_warnings: list[str] = Field(default_factory=list)
    http_status: int | None = None
    response_ms: float | None = None
    error: str | None = None


class PowerBIResponseError(RuntimeError):
    def __init__(self, status_code: int, evidence_name: str):
        super().__init__(f"Power BI {evidence_name} returned HTTP {status_code}")
        self.status_code = status_code
        self.evidence_name = evidence_name


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _refresh_evidence(item: dict[str, Any]) -> PowerBIRefreshEvidence:
    start_time = _parse_datetime(item.get("startTime"))
    end_time = _parse_datetime(item.get("endTime"))
    duration = None
    if start_time is not None and end_time is not None:
        duration = max(0.0, (end_time - start_time).total_seconds())
    request_id = item.get("requestId")
    refresh_type = item.get("refreshType")
    return PowerBIRefreshEvidence(
        request_id=request_id if isinstance(request_id, str) else None,
        refresh_type=refresh_type if isinstance(refresh_type, str) else None,
        status=str(item.get("status") or "Unknown"),
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration,
    )


def correlate_power_bi_trust(
    latest_refresh: PowerBIRefreshEvidence | None,
    upstream_health: dict[str, HealthStatus | None],
) -> tuple[HealthStatus, str, str]:
    missing = [source_id for source_id, health in upstream_health.items() if health is None]
    critical = [
        source_id
        for source_id, health in upstream_health.items()
        if health == HealthStatus.CRITICAL
    ]
    warning = [
        source_id
        for source_id, health in upstream_health.items()
        if health == HealthStatus.WARNING
    ]

    if latest_refresh is None:
        return (
            HealthStatus.WARNING,
            "no_refresh_history",
            "Power BI returned no refresh history, so dashboard freshness cannot be confirmed.",
        )

    status = latest_refresh.status.casefold()
    if status in {"failed", "cancelled", "disabled"}:
        suffix = ""
        if critical or warning:
            suffix = " Upstream AnalystWatch sources also need attention."
        return (
            HealthStatus.CRITICAL,
            "refresh_failed",
            f"The latest Power BI refresh is {latest_refresh.status}.{suffix}",
        )

    if status in {"unknown", "inprogress", "in progress", "notstarted", "not started"}:
        return (
            HealthStatus.WARNING,
            "refresh_not_complete",
            f"The latest Power BI refresh is {latest_refresh.status}; trust is not confirmed yet.",
        )

    if status == "completed":
        if critical:
            return (
                HealthStatus.CRITICAL,
                "upstream_critical_refresh_completed",
                (
                    "Power BI reports a completed refresh, but "
                    f"{len(critical)} upstream AnalystWatch source(s) are Critical. "
                    "The dashboard may have refreshed successfully from untrustworthy data."
                ),
            )
        if warning:
            return (
                HealthStatus.WARNING,
                "upstream_warning_refresh_completed",
                (
                    "Power BI reports a completed refresh, but "
                    f"{len(warning)} upstream AnalystWatch source(s) are Warning."
                ),
            )
        if missing:
            return (
                HealthStatus.WARNING,
                "upstream_unknown_refresh_completed",
                (
                    "Power BI reports a completed refresh, but "
                    f"{len(missing)} configured upstream source(s) have no current observation."
                ),
            )
        return (
            HealthStatus.HEALTHY,
            "refresh_completed_upstream_healthy",
            (
                "Power BI refresh completed and all configured upstream "
                "AnalystWatch sources are Healthy."
            ),
        )

    return (
        HealthStatus.WARNING,
        "refresh_status_unknown",
        f"Power BI returned unrecognized refresh status {latest_refresh.status!r}.",
    )


def _required_get(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    evidence_name: str,
) -> httpx.Response:
    response = client.get(url, headers=headers)
    if response.status_code < 200 or response.status_code >= 300:
        raise PowerBIResponseError(response.status_code, evidence_name)
    return response


def _best_effort_get(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    evidence_name: str,
    warnings: list[str],
) -> httpx.Response | None:
    response = client.get(url, headers=headers)
    if response.status_code < 200 or response.status_code >= 300:
        warnings.append(f"{evidence_name} unavailable (HTTP {response.status_code}).")
        return None
    return response


def read_power_bi_guard(
    definition: PowerBIGuardDefinition,
    *,
    headers: dict[str, str],
    upstream_health: dict[str, HealthStatus | None],
    timeout_seconds: float = 15.0,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> PowerBIGuardSnapshot:
    checked_at = now or datetime.now(timezone.utc)
    if "Authorization" not in headers:
        return PowerBIGuardSnapshot(
            guard_id=definition.id,
            checked_at=checked_at,
            available=False,
            health=HealthStatus.WARNING,
            trust_case="authorization_missing",
            summary="Power BI Guard requires an environment-backed Authorization bearer token.",
            upstream=[
                PowerBIUpstreamEvidence(source_id=source_id, health=upstream_health.get(source_id))
                for source_id in definition.upstream_source_ids
            ],
            error="Power BI Authorization header is not configured.",
        )

    owns_client = client is None
    active_client = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    last_status: int | None = None
    warnings: list[str] = []
    group_id = quote(definition.power_bi_workspace_id, safe="")
    dataset_id = quote(definition.dataset_id, safe="")
    try:
        dataset_response = _required_get(
            active_client,
            f"{POWER_BI_ROOT}/groups/{group_id}/datasets/{dataset_id}",
            headers,
            "semantic model",
        )
        last_status = dataset_response.status_code
        dataset = dataset_response.json()

        refresh_response = _required_get(
            active_client,
            (
                f"{POWER_BI_ROOT}/groups/{group_id}/datasets/{dataset_id}/refreshes"
                f"?$top={definition.refresh_history_limit}"
            ),
            headers,
            "refresh history",
        )
        last_status = refresh_response.status_code
        refresh_items = refresh_response.json().get("value", [])
        if not isinstance(refresh_items, list):
            raise ValueError("Power BI refresh history did not contain a value array")
        refreshes = [_refresh_evidence(item) for item in refresh_items if isinstance(item, dict)]

        group_response = _best_effort_get(
            active_client,
            f"{POWER_BI_ROOT}/groups/{group_id}",
            headers,
            "workspace metadata",
            warnings,
        )
        if group_response is not None:
            last_status = group_response.status_code
        group = group_response.json() if group_response is not None else {}

        reports_response = _best_effort_get(
            active_client,
            f"{POWER_BI_ROOT}/groups/{group_id}/reports",
            headers,
            "report relationships",
            warnings,
        )
        if reports_response is not None:
            last_status = reports_response.status_code
        report_items = (
            reports_response.json().get("value", []) if reports_response is not None else []
        )
        reports = []
        if isinstance(report_items, list):
            for item in report_items:
                if not isinstance(item, dict) or item.get("datasetId") != definition.dataset_id:
                    continue
                report_id = item.get("id")
                name = item.get("name")
                if isinstance(report_id, str) and isinstance(name, str):
                    web_url = item.get("webUrl")
                    reports.append(
                        PowerBIReportEvidence(
                            id=report_id,
                            name=name,
                            web_url=web_url if isinstance(web_url, str) else None,
                        )
                    )

        datasources_response = _best_effort_get(
            active_client,
            f"{POWER_BI_ROOT}/groups/{group_id}/datasets/{dataset_id}/datasources",
            headers,
            "data source metadata",
            warnings,
        )
        if datasources_response is not None:
            last_status = datasources_response.status_code
        datasource_items = (
            datasources_response.json().get("value", []) if datasources_response is not None else []
        )
        datasource_counter: Counter[str] = Counter()
        if isinstance(datasource_items, list):
            for item in datasource_items:
                if not isinstance(item, dict):
                    continue
                datasource_type = item.get("datasourceType")
                if isinstance(datasource_type, str) and datasource_type:
                    datasource_counter[datasource_type] += 1

        latest_refresh = refreshes[0] if refreshes else None
        health, trust_case, summary = correlate_power_bi_trust(latest_refresh, upstream_health)
        return PowerBIGuardSnapshot(
            guard_id=definition.id,
            checked_at=checked_at,
            available=True,
            health=health,
            trust_case=trust_case,
            summary=summary,
            power_bi_workspace_name=(
                group.get("name") if isinstance(group.get("name"), str) else None
            ),
            semantic_model_name=(
                dataset.get("name") if isinstance(dataset.get("name"), str) else definition.name
            ),
            is_refreshable=(
                dataset.get("isRefreshable")
                if isinstance(dataset.get("isRefreshable"), bool)
                else None
            ),
            latest_refresh=latest_refresh,
            refresh_history=refreshes,
            reports=reports,
            datasource_types=dict(sorted(datasource_counter.items())),
            upstream=[
                PowerBIUpstreamEvidence(source_id=source_id, health=upstream_health.get(source_id))
                for source_id in definition.upstream_source_ids
            ],
            evidence_warnings=warnings,
            http_status=last_status,
            response_ms=(time.perf_counter() - started) * 1000,
        )
    except (PowerBIResponseError, ValueError, httpx.HTTPError) as exc:
        status_code = exc.status_code if isinstance(exc, PowerBIResponseError) else last_status
        return PowerBIGuardSnapshot(
            guard_id=definition.id,
            checked_at=checked_at,
            available=False,
            health=HealthStatus.WARNING,
            trust_case="power_bi_unavailable",
            summary="Power BI Guard could not obtain required semantic-model refresh evidence.",
            upstream=[
                PowerBIUpstreamEvidence(source_id=source_id, health=upstream_health.get(source_id))
                for source_id in definition.upstream_source_ids
            ],
            evidence_warnings=warnings,
            http_status=status_code,
            response_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    finally:
        if owns_client:
            active_client.close()
