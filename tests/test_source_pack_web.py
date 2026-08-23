from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from analystwatch.web import create_app


def _sales_pipeline_request() -> dict[str, object]:
    return {
        "pack_id": "sales_pipeline",
        "role_mapping": {
            "opportunity_id": "OpportunityKey",
            "updated_at": "LastModifiedUtc",
            "stage": "PipelineStage",
            "amount": "ExpectedRevenue",
        },
    }


def test_source_pack_catalog_is_available_without_persistence(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "catalog.db")
    client = TestClient(app)

    response = client.get("/api/source-packs")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [
        "fp_and_a_forecast",
        "sales_pipeline",
        "claims_register",
        "operations_orders",
        "finance_close",
        "customer_export",
    ]
    assert app.state.workspace_storage.list_sources() == []


def test_materialize_endpoint_returns_existing_monitoring_config_only(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "materialize.db")
    client = TestClient(app)

    response = client.post("/api/source-packs/materialize", json=_sales_pipeline_request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["pack_id"] == "sales_pipeline"
    assert payload["config"]["unique_keys"] == ["OpportunityKey"]
    assert payload["config"]["latest_date_field"] == "LastModifiedUtc"
    assert payload["config"]["numeric_fields"] == ["ExpectedRevenue"]
    assert payload["config"]["row_diff_fields"] == ["PipelineStage", "ExpectedRevenue"]
    assert app.state.workspace_storage.list_sources() == []


def test_materialized_pack_still_uses_normal_preflight_acceptance_boundary(tmp_path) -> None:
    source_path = tmp_path / "pipeline.csv"
    source_path.write_text(
        "OpportunityKey,LastModifiedUtc,PipelineStage,ExpectedRevenue\n"
        f"opp-1,{datetime.now(timezone.utc).isoformat()},Qualified,125000\n",
        encoding="utf-8",
    )
    app = create_app(db_path=tmp_path / "preflight.db")
    client = TestClient(app)

    materialized = client.post(
        "/api/source-packs/materialize",
        json=_sales_pipeline_request(),
    )
    assert materialized.status_code == 200

    source = {
        "id": "pipeline-pack-test",
        "name": "Pipeline pack test",
        "source_type": "csv",
        "location": str(source_path),
        "config": materialized.json()["config"],
    }
    preflight = client.post("/api/preflight", json=source)

    assert preflight.status_code == 200
    assert preflight.json()["ready"] is True
    assert app.state.workspace_storage.list_sources() == []


def test_materialized_pack_rule_failure_is_rejected_by_normal_preflight(tmp_path) -> None:
    source_path = tmp_path / "broken-pipeline.csv"
    source_path.write_text(
        "OpportunityKey,LastModifiedUtc,PipelineStage,ExpectedRevenue\n"
        f"opp-1,{datetime.now(timezone.utc).isoformat()},,125000\n",
        encoding="utf-8",
    )
    app = create_app(db_path=tmp_path / "broken-preflight.db")
    client = TestClient(app)

    materialized = client.post(
        "/api/source-packs/materialize",
        json=_sales_pipeline_request(),
    )
    source = {
        "id": "broken-pipeline-pack-test",
        "name": "Broken pipeline pack test",
        "source_type": "csv",
        "location": str(source_path),
        "config": materialized.json()["config"],
    }
    preflight = client.post("/api/preflight", json=source)

    assert preflight.status_code == 200
    assert preflight.json()["ready"] is False
    assert any(
        issue["code"] == "data_rule_failed"
        for issue in preflight.json()["issues"]
    )
    assert app.state.workspace_storage.list_sources() == []


def test_materialize_endpoint_fails_closed_for_incomplete_mapping(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "invalid-materialize.db")
    client = TestClient(app)

    response = client.post(
        "/api/source-packs/materialize",
        json={
            "pack_id": "sales_pipeline",
            "role_mapping": {"opportunity_id": "OpportunityKey"},
        },
    )

    assert response.status_code == 422
    assert "Missing required role mappings" in response.json()["detail"]
    assert app.state.workspace_storage.list_sources() == []
