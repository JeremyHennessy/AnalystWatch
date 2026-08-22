from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from analystwatch.auth import WorkspaceRole
from analystwatch.models import HealthStatus
from analystwatch.power_bi import (
    PowerBIGuardDefinition,
    PowerBIGuardSnapshot,
    PowerBIRefreshEvidence,
    PowerBIReportEvidence,
    PowerBIUpstreamEvidence,
)
from analystwatch.web import create_app
from analystwatch.web_auth import required_role


def _definition(workspace_id: str = "local") -> PowerBIGuardDefinition:
    return PowerBIGuardDefinition(
        id="executive-bi",
        workspace_id=workspace_id,
        name="Executive Treasury Model",
        power_bi_workspace_id="workspace-1",
        dataset_id="dataset-1",
        auth_token_env="POWER_BI_TOKEN",
        upstream_source_ids=["treasury", "fx"],
    )


def _snapshot() -> PowerBIGuardSnapshot:
    return PowerBIGuardSnapshot(
        guard_id="executive-bi",
        checked_at=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
        available=True,
        health=HealthStatus.CRITICAL,
        trust_case="upstream_critical_refresh_completed",
        summary=(
            "Power BI reports a completed refresh, but 1 upstream AnalystWatch source is Critical."
        ),
        power_bi_workspace_name="Finance BI",
        semantic_model_name="Executive Treasury Model",
        is_refreshable=True,
        latest_refresh=PowerBIRefreshEvidence(
            status="Completed",
            refresh_type="Scheduled",
            start_time=datetime(2026, 8, 22, 12, 55, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            duration_seconds=300,
        ),
        refresh_history=[
            PowerBIRefreshEvidence(
                status="Completed",
                refresh_type="Scheduled",
                duration_seconds=300,
            )
        ],
        reports=[
            PowerBIReportEvidence(
                id="report-1",
                name="Executive Treasury Dashboard",
                web_url="https://app.powerbi.com/report-1",
            )
        ],
        datasource_types={"Web": 2, "Sql": 1},
        upstream=[
            PowerBIUpstreamEvidence(source_id="treasury", health=HealthStatus.CRITICAL),
            PowerBIUpstreamEvidence(source_id="fx", health=HealthStatus.HEALTHY),
        ],
    )


def test_power_bi_guard_pages_show_false_confidence_and_downstream_context(tmp_path) -> None:
    app = create_app(tmp_path / "state.db")
    app.state.power_bi_store.upsert_guard(_definition())
    app.state.power_bi_store.save_snapshot(_snapshot())
    client = TestClient(app)

    overview = client.get("/power-bi")
    detail = client.get("/power-bi/executive-bi")

    assert overview.status_code == 200
    assert "Can users trust this dashboard right now?" in overview.text
    assert "Executive Treasury Model" in overview.text
    assert "Critical" in overview.text
    assert "A successful refresh can still be unsafe" in overview.text

    assert detail.status_code == 200
    assert "Completed" in detail.text
    assert "Executive Treasury Dashboard" in detail.text
    assert "treasury" in detail.text
    assert "Critical" in detail.text
    assert "Reports using this model" in detail.text
    assert "Datasource types" in detail.text


def test_power_bi_guard_api_rejects_cross_workspace_definition(tmp_path) -> None:
    app = create_app(tmp_path / "state.db", workspace_id="workspace-a")
    client = TestClient(app)

    response = client.put(
        "/api/power-bi/guards/executive-bi",
        json=_definition(workspace_id="workspace-b").model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert "another workspace" in response.json()["detail"]


def test_power_bi_guard_role_boundary_is_viewer_read_operator_check_admin_config() -> None:
    assert required_role("GET", "/power-bi") == WorkspaceRole.VIEWER
    assert required_role("GET", "/api/power-bi/guards/executive-bi") == WorkspaceRole.VIEWER
    assert (
        required_role("POST", "/api/power-bi/guards/executive-bi/check")
        == WorkspaceRole.OPERATOR
    )
    assert (
        required_role("PUT", "/api/power-bi/guards/executive-bi")
        == WorkspaceRole.ADMIN
    )
