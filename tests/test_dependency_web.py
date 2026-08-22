from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from analystwatch.dependencies import AssetKind, AssetRef, DependencyEdge
from analystwatch.models import HealthStatus, Observation, SourceDefinition, SourceType
from analystwatch.web import create_app


def _edge(workspace_id: str = "team-a") -> DependencyEdge:
    return DependencyEdge(
        id="orders-to-model",
        workspace_id=workspace_id,
        upstream=AssetRef(
            kind=AssetKind.SOURCE,
            id="orders",
            name="Orders API",
            href="/sources/orders",
        ),
        downstream=AssetRef(
            kind=AssetKind.SEMANTIC_MODEL,
            id="sales-model",
            name="Sales Model",
        ),
        relationship="feeds semantic model",
    )


def _seed_source(app) -> None:
    storage = app.state.workspace_storage
    source = SourceDefinition(
        id="orders",
        workspace_id="team-a",
        name="Orders API",
        source_type=SourceType.JSON,
        location="orders.json",
    )
    observation = Observation(
        id="orders-healthy",
        source_id=source.id,
        observed_at=datetime(2026, 8, 22, 15, 30, tzinfo=timezone.utc),
        available=True,
        health=HealthStatus.HEALTHY,
    )
    storage.upsert_source(source)
    storage.save_observation(observation)


def test_dependency_api_persists_edges_and_exposes_blast_radius(tmp_path) -> None:
    app = create_app(tmp_path / "state.db", workspace_id="team-a")
    _seed_source(app)
    client = TestClient(app)

    create = client.put(
        "/api/dependencies/edges/orders-to-model",
        json=_edge().model_dump(mode="json"),
    )
    radius = client.get(
        "/api/dependencies/blast-radius",
        params={"kind": "source", "asset_id": "orders"},
    )
    page = client.get("/dependencies")
    source_page = client.get("/sources/orders")
    source_api = client.get("/api/sources/orders")

    assert create.status_code == 200
    assert radius.status_code == 200
    assert radius.json()["root"]["name"] == "Orders API"
    assert radius.json()["downstream"][0]["name"] == "Sales Model"
    assert page.status_code == 200
    assert "What breaks downstream if this changes?" in page.text
    assert "Orders API" in page.text
    assert "Sales Model" in page.text
    assert source_page.status_code == 200
    assert "DOWNSTREAM IMPACT" in source_page.text
    assert "1 downstream asset" in source_page.text
    assert "Semantic Model" in source_page.text
    assert source_api.status_code == 200
    assert source_api.json()["downstream_impact"]["downstream"][0]["name"] == "Sales Model"


def test_dependency_api_rejects_cross_workspace_edge(tmp_path) -> None:
    app = create_app(tmp_path / "state.db", workspace_id="team-a")
    client = TestClient(app)

    response = client.put(
        "/api/dependencies/edges/orders-to-model",
        json=_edge(workspace_id="team-b").model_dump(mode="json"),
    )

    assert response.status_code == 409
    assert "another workspace" in response.json()["detail"]
    assert app.state.dependency_service.edges() == []


def test_discovered_replacement_removes_stale_edges_without_touching_explicit_edges(
    tmp_path,
) -> None:
    app = create_app(tmp_path / "state.db", workspace_id="team-a")
    service = app.state.dependency_service
    explicit = _edge()
    old_report = DependencyEdge(
        id="pbi:guard:report:old",
        workspace_id="team-a",
        upstream=AssetRef(kind=AssetKind.SEMANTIC_MODEL, id="model", name="Model"),
        downstream=AssetRef(kind=AssetKind.REPORT, id="old", name="Old Report"),
        discovered=True,
    )
    current_report = DependencyEdge(
        id="pbi:guard:report:new",
        workspace_id="team-a",
        upstream=AssetRef(kind=AssetKind.SEMANTIC_MODEL, id="model", name="Model"),
        downstream=AssetRef(kind=AssetKind.REPORT, id="new", name="New Report"),
        discovered=True,
    )
    service.upsert_edge(explicit)
    service.upsert_edge(old_report)

    service.replace_discovered_edges("pbi:guard:", [current_report])

    edge_ids = {edge.id for edge in service.edges()}
    assert edge_ids == {"orders-to-model", "pbi:guard:report:new"}
