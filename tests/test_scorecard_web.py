from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from analystwatch.dependencies import AssetKind, AssetRef, DependencyEdge
from analystwatch.models import DatasetProfile, HealthStatus, Observation, SourceDefinition, SourceType
from analystwatch.web import create_app

NOW = datetime.now(timezone.utc)
PROFILE = DatasetProfile(row_count=10, column_count=0, columns={})


def _seed_source(app, *, health: HealthStatus = HealthStatus.HEALTHY) -> None:
    storage = app.state.workspace_storage
    source = SourceDefinition(
        id="orders",
        name="Orders",
        source_type=SourceType.CSV,
        location="orders.csv",
    )
    storage.upsert_source(source)
    storage.save_observation(
        Observation(
            id="orders-current",
            source_id=source.id,
            observed_at=NOW - timedelta(hours=1),
            available=True,
            health=health,
            profile=PROFILE,
        )
    )


def test_scorecard_api_exposes_current_badge_and_empty_bounded_impact(tmp_path) -> None:
    app = create_app(tmp_path / "state.db")
    _seed_source(app)
    client = TestClient(app)

    response = client.get("/api/sources/orders/scorecard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scorecard"]["current_health"] == "Healthy"
    assert payload["scorecard"]["badge"] == "Trusted"
    assert payload["scorecard"]["window_7d"]["check_count"] == 1
    assert payload["scorecard"]["window_30d"]["successful_check_pct"] == 1.0
    assert payload["downstream_impact"] == {"total": 0, "counts": {}}


def test_scorecard_api_exposes_only_downstream_counts_not_asset_identity(tmp_path) -> None:
    app = create_app(tmp_path / "state.db")
    _seed_source(app)
    dependency_service = app.state.dependency_service
    dependency_service.upsert_edge(
        DependencyEdge(
            id="orders-to-secret-model",
            upstream=AssetRef(kind=AssetKind.SOURCE, id="orders", name="Orders"),
            downstream=AssetRef(
                kind=AssetKind.SEMANTIC_MODEL,
                id="private-model",
                name="Secret FP&A Model",
                href="https://private.example/model",
            ),
        )
    )
    dependency_service.upsert_edge(
        DependencyEdge(
            id="secret-model-to-secret-report",
            upstream=AssetRef(
                kind=AssetKind.SEMANTIC_MODEL,
                id="private-model",
                name="Secret FP&A Model",
            ),
            downstream=AssetRef(
                kind=AssetKind.REPORT,
                id="private-report",
                name="Board Forecast — Confidential",
                href="https://private.example/report",
            ),
        )
    )
    client = TestClient(app)

    response = client.get("/api/sources/orders/scorecard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["downstream_impact"] == {
        "total": 2,
        "counts": {"report": 1, "semantic_model": 1},
    }
    rendered = response.text
    assert "Secret FP&A Model" not in rendered
    assert "Board Forecast" not in rendered
    assert "private.example" not in rendered


def test_downstream_impact_does_not_change_trust_badge(tmp_path) -> None:
    app = create_app(tmp_path / "state.db")
    _seed_source(app, health=HealthStatus.WARNING)
    app.state.dependency_service.upsert_edge(
        DependencyEdge(
            id="orders-to-report",
            upstream=AssetRef(kind=AssetKind.SOURCE, id="orders", name="Orders"),
            downstream=AssetRef(kind=AssetKind.REPORT, id="report", name="Executive Report"),
        )
    )
    client = TestClient(app)

    payload = client.get("/api/sources/orders/scorecard").json()

    assert payload["scorecard"]["current_health"] == "Warning"
    assert payload["scorecard"]["badge"] == "Attention"
    assert payload["downstream_impact"]["total"] == 1


def test_scorecard_api_returns_404_for_unknown_source(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "state.db"))

    response = client.get("/api/sources/missing/scorecard")

    assert response.status_code == 404
    assert "Unknown source" in response.json()["detail"]
