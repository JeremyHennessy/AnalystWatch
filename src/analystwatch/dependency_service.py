from __future__ import annotations

from .dependencies import AssetKind, AssetRef, BlastRadius, DependencyEdge, calculate_blast_radius
from .dependency_storage import DependencyStore


class DependencyService:
    def __init__(self, store: DependencyStore):
        self.store = store

    def edges(self) -> list[DependencyEdge]:
        return self.store.list_edges()

    def upsert_edge(self, edge: DependencyEdge) -> DependencyEdge:
        return self.store.upsert_edge(edge)

    def delete_edge(self, edge_id: str) -> bool:
        return self.store.delete_edge(edge_id)

    def assets(self) -> list[AssetRef]:
        by_key: dict[str, AssetRef] = {}
        for edge in self.store.list_edges():
            by_key[edge.upstream.key] = edge.upstream
            by_key[edge.downstream.key] = edge.downstream
        return sorted(by_key.values(), key=lambda item: (item.kind.value, item.name.lower()))

    def roots(self) -> list[AssetRef]:
        edges = self.store.list_edges()
        upstream: dict[str, AssetRef] = {}
        downstream_keys: set[str] = set()
        for edge in edges:
            upstream[edge.upstream.key] = edge.upstream
            downstream_keys.add(edge.downstream.key)
        roots = [asset for key, asset in upstream.items() if key not in downstream_keys]
        return sorted(roots, key=lambda item: (item.kind.value, item.name.lower()))

    def blast_radius(self, kind: AssetKind, asset_id: str) -> BlastRadius:
        asset = next(
            (
                item
                for item in self.assets()
                if item.kind == kind and item.id == asset_id
            ),
            None,
        )
        if asset is None:
            raise KeyError(f"Unknown dependency asset: {kind.value}:{asset_id}")
        return calculate_blast_radius(asset, self.store.list_edges())
