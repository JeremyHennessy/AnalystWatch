from __future__ import annotations

from collections import deque
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .power_bi import PowerBIGuardDefinition, PowerBIGuardSnapshot
from .workspace import DEFAULT_WORKSPACE_ID, validate_workspace_id


class AssetKind(StrEnum):
    SOURCE = "source"
    WORKBOOK = "workbook"
    SEMANTIC_MODEL = "semantic_model"
    REPORT = "report"
    CUSTOM = "custom"


class AssetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AssetKind
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    href: str | None = None

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.id}"


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=256)
    workspace_id: str = DEFAULT_WORKSPACE_ID
    upstream: AssetRef
    downstream: AssetRef
    relationship: str = Field(default="feeds", min_length=1, max_length=80)
    discovered: bool = False

    @model_validator(mode="after")
    def validate_edge(self) -> DependencyEdge:
        self.workspace_id = validate_workspace_id(self.workspace_id)
        if self.upstream.key == self.downstream.key:
            raise ValueError("dependency edge cannot point an asset to itself")
        return self


class BlastRadius(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: AssetRef
    direct: list[AssetRef]
    downstream: list[AssetRef]
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return len(self.downstream)


def calculate_blast_radius(root: AssetRef, edges: list[DependencyEdge]) -> BlastRadius:
    adjacency: dict[str, list[AssetRef]] = {}
    for edge in edges:
        adjacency.setdefault(edge.upstream.key, []).append(edge.downstream)

    direct = _unique_assets(adjacency.get(root.key, []))
    visited = {root.key}
    discovered: list[AssetRef] = []
    queue = deque(direct)
    while queue:
        asset = queue.popleft()
        if asset.key in visited:
            continue
        visited.add(asset.key)
        discovered.append(asset)
        for downstream in adjacency.get(asset.key, []):
            if downstream.key not in visited:
                queue.append(downstream)

    counts: dict[str, int] = {}
    for asset in discovered:
        counts[asset.kind.value] = counts.get(asset.kind.value, 0) + 1
    return BlastRadius(root=root, direct=direct, downstream=discovered, counts=counts)


def power_bi_dependency_edges(
    definition: PowerBIGuardDefinition,
    snapshot: PowerBIGuardSnapshot,
) -> list[DependencyEdge]:
    model_name = snapshot.semantic_model_name or definition.name
    semantic_model = AssetRef(
        kind=AssetKind.SEMANTIC_MODEL,
        id=definition.dataset_id,
        name=model_name,
        href=f"/power-bi/{definition.id}",
    )
    edges: list[DependencyEdge] = []
    for source_id in definition.upstream_source_ids:
        source = AssetRef(
            kind=AssetKind.SOURCE,
            id=source_id,
            name=source_id,
            href=f"/sources/{source_id}",
        )
        edges.append(
            DependencyEdge(
                id=f"pbi:{definition.id}:source:{source_id}",
                workspace_id=definition.workspace_id,
                upstream=source,
                downstream=semantic_model,
                relationship="feeds semantic model",
                discovered=True,
            )
        )
    for report in snapshot.reports:
        report_asset = AssetRef(
            kind=AssetKind.REPORT,
            id=report.id,
            name=report.name,
            href=report.web_url,
        )
        edges.append(
            DependencyEdge(
                id=f"pbi:{definition.id}:report:{report.id}",
                workspace_id=definition.workspace_id,
                upstream=semantic_model,
                downstream=report_asset,
                relationship="feeds report",
                discovered=True,
            )
        )
    return edges


def _unique_assets(assets: list[AssetRef]) -> list[AssetRef]:
    seen: set[str] = set()
    result: list[AssetRef] = []
    for asset in assets:
        if asset.key in seen:
            continue
        seen.add(asset.key)
        result.append(asset)
    return result
