from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from analystwatch.dependencies import (
    AssetKind,
    AssetRef,
    DependencyEdge,
    calculate_blast_radius,
    power_bi_dependency_edges,
)
from analystwatch.dependency_storage import PostgresDependencyStore, SQLiteDependencyStore
from analystwatch.models import HealthStatus
from analystwatch.power_bi import (
    PowerBIGuardDefinition,
    PowerBIGuardSnapshot,
    PowerBIReportEvidence,
)


def _asset(kind: AssetKind, asset_id: str, name: str) -> AssetRef:
    return AssetRef(kind=kind, id=asset_id, name=name)


def _edges(workspace: str = "team-a") -> list[DependencyEdge]:
    source = _asset(AssetKind.SOURCE, "orders", "Orders API")
    workbook = _asset(AssetKind.WORKBOOK, "forecast", "Forecast workbook")
    model = _asset(AssetKind.SEMANTIC_MODEL, "model", "Executive Model")
    report_a = _asset(AssetKind.REPORT, "report-a", "Executive Dashboard")
    report_b = _asset(AssetKind.REPORT, "report-b", "Operations Dashboard")
    return [
        DependencyEdge(
            id="source-workbook",
            workspace_id=workspace,
            upstream=source,
            downstream=workbook,
        ),
        DependencyEdge(
            id="workbook-model",
            workspace_id=workspace,
            upstream=workbook,
            downstream=model,
        ),
        DependencyEdge(
            id="model-report-a",
            workspace_id=workspace,
            upstream=model,
            downstream=report_a,
        ),
        DependencyEdge(
            id="model-report-b",
            workspace_id=workspace,
            upstream=model,
            downstream=report_b,
        ),
    ]


def test_blast_radius_counts_all_downstream_assets_without_duplicates() -> None:
    edges = _edges()
    root = edges[0].upstream
    radius = calculate_blast_radius(root, edges)

    assert [item.name for item in radius.direct] == ["Forecast workbook"]
    assert radius.total == 4
    assert radius.counts == {"workbook": 1, "semantic_model": 1, "report": 2}
    assert {item.name for item in radius.downstream} == {
        "Forecast workbook",
        "Executive Model",
        "Executive Dashboard",
        "Operations Dashboard",
    }


def test_blast_radius_is_cycle_safe() -> None:
    a = _asset(AssetKind.SOURCE, "a", "A")
    b = _asset(AssetKind.CUSTOM, "b", "B")
    edges = [
        DependencyEdge(id="a-b", upstream=a, downstream=b),
        DependencyEdge(id="b-a", upstream=b, downstream=a),
    ]

    radius = calculate_blast_radius(a, edges)

    assert [item.key for item in radius.downstream] == [b.key]


def test_power_bi_snapshot_discovers_source_model_and_report_edges() -> None:
    definition = PowerBIGuardDefinition(
        id="guard",
        name="Executive Model",
        power_bi_workspace_id="group",
        dataset_id="dataset",
        auth_token_env="POWER_BI_TOKEN",
        upstream_source_ids=["treasury", "fx"],
    )
    snapshot = PowerBIGuardSnapshot(
        guard_id="guard",
        checked_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        available=True,
        health=HealthStatus.HEALTHY,
        trust_case="healthy",
        summary="Healthy",
        semantic_model_name="Treasury Model",
        reports=[
            PowerBIReportEvidence(id="report", name="Treasury Dashboard", web_url="https://pbi/report")
        ],
    )

    edges = power_bi_dependency_edges(definition, snapshot)

    assert len(edges) == 3
    assert sum(edge.upstream.kind == AssetKind.SOURCE for edge in edges) == 2
    assert any(
        edge.upstream.kind == AssetKind.SEMANTIC_MODEL
        and edge.downstream.kind == AssetKind.REPORT
        and edge.discovered
        for edge in edges
    )


def test_sqlite_dependency_store_is_workspace_scoped(tmp_path) -> None:
    path = tmp_path / "dependencies.db"
    team_a = SQLiteDependencyStore(path, "team-a")
    team_b = SQLiteDependencyStore(path, "team-b")
    team_a.initialize()
    team_b.initialize()

    edge_a = _edges("team-a")[0]
    edge_b = _edges("team-b")[0].model_copy(update={"relationship": "client feed"})
    team_a.upsert_edge(edge_a)
    team_b.upsert_edge(edge_b)

    assert team_a.get_edge(edge_a.id) == edge_a
    assert team_b.get_edge(edge_b.id) == edge_b
    assert team_a.list_edges() == [edge_a]
    with pytest.raises(ValueError, match="another workspace"):
        team_a.upsert_edge(edge_b)


@pytest.mark.skipif(
    not os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN"),
    reason="PostgreSQL test DSN not configured",
)
def test_postgres_dependency_store_allows_same_edge_id_across_workspaces() -> None:
    dsn = os.environ["ANALYSTWATCH_TEST_POSTGRES_DSN"]
    team_a = PostgresDependencyStore(dsn, "dependency-a")
    team_b = PostgresDependencyStore(dsn, "dependency-b")
    team_a.initialize()
    team_b.initialize()
    edge_a = _edges("dependency-a")[0]
    edge_b = _edges("dependency-b")[0].model_copy(update={"relationship": "client feed"})

    team_a.upsert_edge(edge_a)
    team_b.upsert_edge(edge_b)
    try:
        assert team_a.get_edge(edge_a.id) == edge_a
        assert team_b.get_edge(edge_b.id) == edge_b
    finally:
        team_a.delete_edge(edge_a.id)
        team_b.delete_edge(edge_b.id)
