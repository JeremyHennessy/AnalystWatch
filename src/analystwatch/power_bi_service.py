from __future__ import annotations

import os
from datetime import datetime

from .power_bi import PowerBIGuardDefinition, PowerBIGuardSnapshot, read_power_bi_guard
from .power_bi_storage import PowerBIGuardStore
from .store import MonitoringStore


class PowerBIGuardService:
    """Orchestrate Power BI evidence with current AnalystWatch source health."""

    def __init__(self, store: PowerBIGuardStore, monitoring_store: MonitoringStore):
        self.store = store
        self.monitoring_store = monitoring_store

    def list_guards(self) -> list[PowerBIGuardDefinition]:
        return self.store.list_guards()

    def get_guard(self, guard_id: str) -> PowerBIGuardDefinition | None:
        return self.store.get_guard(guard_id)

    def upsert_guard(self, definition: PowerBIGuardDefinition) -> PowerBIGuardDefinition:
        return self.store.upsert_guard(definition)

    def latest_snapshot(self, guard_id: str) -> PowerBIGuardSnapshot | None:
        return self.store.latest_snapshot(guard_id)

    def snapshots(self, guard_id: str, limit: int = 30) -> list[PowerBIGuardSnapshot]:
        return self.store.list_snapshots(guard_id, limit=limit)

    def check_guard(
        self,
        guard_id: str,
        *,
        now: datetime | None = None,
    ) -> PowerBIGuardSnapshot:
        definition = self.store.get_guard(guard_id)
        if definition is None:
            raise KeyError(f"Unknown Power BI Guard: {guard_id}")

        token = os.environ.get(definition.auth_token_env)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        upstream_health = {}
        for source_id in definition.upstream_source_ids:
            latest = self.monitoring_store.get_latest(source_id)
            upstream_health[source_id] = latest.health if latest is not None else None

        snapshot = read_power_bi_guard(
            definition,
            headers=headers,
            upstream_health=upstream_health,
            now=now,
        )
        return self.store.save_snapshot(snapshot)
