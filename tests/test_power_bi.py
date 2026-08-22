from __future__ import annotations

from datetime import datetime, timezone

import httpx

from analystwatch.models import HealthStatus
from analystwatch.power_bi import (
    PowerBIGuardDefinition,
    PowerBIRefreshEvidence,
    correlate_power_bi_trust,
    read_power_bi_guard,
)


def _definition() -> PowerBIGuardDefinition:
    return PowerBIGuardDefinition(
        id="treasury-dashboard",
        name="Treasury semantic model",
        power_bi_workspace_id="workspace-123",
        dataset_id="dataset-456",
        auth_token_env="POWER_BI_TOKEN",
        upstream_source_ids=["fx", "treasury"],
        refresh_history_limit=20,
    )


def _refresh(status: str = "Completed") -> PowerBIRefreshEvidence:
    return PowerBIRefreshEvidence(
        request_id="refresh-1",
        refresh_type="Scheduled",
        status=status,
        start_time=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 22, 10, 2, tzinfo=timezone.utc),
        duration_seconds=120,
    )


def test_completed_refresh_with_healthy_upstream_is_healthy() -> None:
    health, trust_case, summary = correlate_power_bi_trust(
        _refresh(),
        {"fx": HealthStatus.HEALTHY, "treasury": HealthStatus.HEALTHY},
    )

    assert health == HealthStatus.HEALTHY
    assert trust_case == "refresh_completed_upstream_healthy"
    assert "all configured upstream" in summary


def test_completed_refresh_with_critical_upstream_is_critical() -> None:
    health, trust_case, summary = correlate_power_bi_trust(
        _refresh(),
        {"fx": HealthStatus.HEALTHY, "treasury": HealthStatus.CRITICAL},
    )

    assert health == HealthStatus.CRITICAL
    assert trust_case == "upstream_critical_refresh_completed"
    assert "refreshed successfully from untrustworthy data" in summary


def test_failed_refresh_is_critical_even_when_upstream_is_healthy() -> None:
    health, trust_case, summary = correlate_power_bi_trust(
        _refresh("Failed"),
        {"fx": HealthStatus.HEALTHY},
    )

    assert health == HealthStatus.CRITICAL
    assert trust_case == "refresh_failed"
    assert "Failed" in summary


def test_missing_upstream_observation_is_warning_after_completed_refresh() -> None:
    health, trust_case, summary = correlate_power_bi_trust(
        _refresh(),
        {"fx": HealthStatus.HEALTHY, "treasury": None},
    )

    assert health == HealthStatus.WARNING
    assert trust_case == "upstream_unknown_refresh_completed"
    assert "no current observation" in summary


def test_power_bi_guard_reads_refresh_reports_workspace_and_datasource_types() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer test-token"
        path = request.url.path
        if path.endswith("/datasets/dataset-456"):
            return httpx.Response(
                200,
                json={
                    "id": "dataset-456",
                    "name": "Treasury Model",
                    "isRefreshable": True,
                },
            )
        if path.endswith("/datasets/dataset-456/refreshes"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "requestId": "refresh-1",
                            "refreshType": "Scheduled",
                            "status": "Completed",
                            "startTime": "2026-08-22T10:00:00Z",
                            "endTime": "2026-08-22T10:02:30Z",
                        },
                        {
                            "requestId": "refresh-0",
                            "refreshType": "Scheduled",
                            "status": "Completed",
                            "startTime": "2026-08-21T10:00:00Z",
                            "endTime": "2026-08-21T10:03:00Z",
                        },
                    ]
                },
            )
        if path.endswith("/groups/workspace-123"):
            return httpx.Response(200, json={"id": "workspace-123", "name": "Finance BI"})
        if path.endswith("/groups/workspace-123/reports"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "report-1",
                            "name": "Executive Treasury",
                            "datasetId": "dataset-456",
                            "webUrl": "https://app.powerbi.com/report-1",
                        },
                        {
                            "id": "report-other",
                            "name": "Other",
                            "datasetId": "other-dataset",
                        },
                    ]
                },
            )
        if path.endswith("/datasets/dataset-456/datasources"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"datasourceType": "Web"},
                        {"datasourceType": "Sql"},
                        {"datasourceType": "Web"},
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = read_power_bi_guard(
            _definition(),
            headers={"Authorization": "Bearer test-token"},
            upstream_health={"fx": HealthStatus.HEALTHY, "treasury": HealthStatus.HEALTHY},
            client=client,
            now=datetime(2026, 8, 22, 11, 0, tzinfo=timezone.utc),
        )

    assert snapshot.available is True
    assert snapshot.health == HealthStatus.HEALTHY
    assert snapshot.semantic_model_name == "Treasury Model"
    assert snapshot.power_bi_workspace_name == "Finance BI"
    assert snapshot.latest_refresh is not None
    assert snapshot.latest_refresh.status == "Completed"
    assert snapshot.latest_refresh.duration_seconds == 150
    assert len(snapshot.refresh_history) == 2
    assert [report.name for report in snapshot.reports] == ["Executive Treasury"]
    assert snapshot.datasource_types == {"Sql": 1, "Web": 2}
    assert snapshot.evidence_warnings == []
    assert any("$top=20" in url for url in requested)


def test_optional_power_bi_metadata_permission_failure_does_not_break_refresh_guard() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/datasets/dataset-456"):
            return httpx.Response(200, json={"id": "dataset-456", "name": "Model"})
        if path.endswith("/datasets/dataset-456/refreshes"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "status": "Completed",
                            "startTime": "2026-08-22T10:00:00Z",
                            "endTime": "2026-08-22T10:01:00Z",
                        }
                    ]
                },
            )
        return httpx.Response(403, json={"error": {"message": "forbidden"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = read_power_bi_guard(
            _definition(),
            headers={"Authorization": "Bearer test-token"},
            upstream_health={"fx": HealthStatus.HEALTHY, "treasury": HealthStatus.HEALTHY},
            client=client,
        )

    assert snapshot.available is True
    assert snapshot.health == HealthStatus.HEALTHY
    assert snapshot.reports == []
    assert snapshot.datasource_types == {}
    assert len(snapshot.evidence_warnings) == 3
    assert "workspace metadata unavailable (HTTP 403)." in snapshot.evidence_warnings
    assert "report relationships unavailable (HTTP 403)." in snapshot.evidence_warnings
    assert "data source metadata unavailable (HTTP 403)." in snapshot.evidence_warnings


def test_required_refresh_history_failure_is_unavailable_without_leaking_token() -> None:
    secret = "super-secret-power-bi-token"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/datasets/dataset-456"):
            return httpx.Response(200, json={"id": "dataset-456", "name": "Model"})
        return httpx.Response(401, json={"error": {"message": secret}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot = read_power_bi_guard(
            _definition(),
            headers={"Authorization": f"Bearer {secret}"},
            upstream_health={"fx": HealthStatus.HEALTHY, "treasury": HealthStatus.HEALTHY},
            client=client,
        )

    assert snapshot.available is False
    assert snapshot.health == HealthStatus.WARNING
    assert snapshot.http_status == 401
    assert snapshot.error == "Power BI refresh history returned HTTP 401"
    assert secret not in snapshot.model_dump_json()


def test_missing_authorization_is_explicit_and_definition_stores_only_env_name() -> None:
    definition = _definition()
    snapshot = read_power_bi_guard(
        definition,
        headers={},
        upstream_health={"fx": HealthStatus.HEALTHY, "treasury": HealthStatus.HEALTHY},
    )

    assert snapshot.available is False
    assert snapshot.trust_case == "authorization_missing"
    assert definition.auth_token_env == "POWER_BI_TOKEN"
    assert "Bearer" not in definition.model_dump_json()
