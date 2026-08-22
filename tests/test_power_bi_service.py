from __future__ import annotations

from datetime import datetime, timezone

from analystwatch.models import HealthStatus, MonitoringConfig, SourceDefinition, SourceType
from analystwatch.power_bi import PowerBIGuardDefinition, PowerBIGuardSnapshot
from analystwatch.power_bi_service import PowerBIGuardService
from analystwatch.power_bi_storage import SQLitePowerBIGuardStore
from analystwatch.service import MonitorService
from analystwatch.storage import Storage
from analystwatch.workspace import WorkspaceStore


def _source(path, source_id: str) -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        name=source_id,
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(),
    )


def test_power_bi_service_uses_current_upstream_health_and_env_token(
    tmp_path,
    monkeypatch,
) -> None:
    source_path = tmp_path / "upstream.csv"
    source_path.write_text("id,value\n1,10\n", encoding="utf-8")
    monitoring = WorkspaceStore(Storage(tmp_path / "state.db"), "local")
    monitor_service = MonitorService(monitoring)
    monitor_service.add_source(_source(source_path, "upstream"))
    observation = monitor_service.check_source("upstream")
    assert observation.health == HealthStatus.HEALTHY

    guard_store = SQLitePowerBIGuardStore(tmp_path / "power-bi.db", "local")
    guard_store.initialize()
    guard_store.upsert_guard(
        PowerBIGuardDefinition(
            id="guard",
            name="Executive Model",
            power_bi_workspace_id="group",
            dataset_id="dataset",
            auth_token_env="POWER_BI_TEST_TOKEN",
            upstream_source_ids=["upstream", "missing-source"],
        )
    )
    service = PowerBIGuardService(guard_store, monitoring)
    monkeypatch.setenv("POWER_BI_TEST_TOKEN", "secret-token")
    captured = {}

    def fake_read(definition, *, headers, upstream_health, now=None):
        captured["headers"] = headers
        captured["upstream_health"] = upstream_health
        return PowerBIGuardSnapshot(
            guard_id=definition.id,
            checked_at=now or datetime.now(timezone.utc),
            available=True,
            health=HealthStatus.WARNING,
            trust_case="test",
            summary="test",
        )

    monkeypatch.setattr("analystwatch.power_bi_service.read_power_bi_guard", fake_read)
    checked_at = datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc)
    snapshot = service.check_guard("guard", now=checked_at)

    assert captured["headers"] == {"Authorization": "Bearer secret-token"}
    assert captured["upstream_health"] == {
        "upstream": HealthStatus.HEALTHY,
        "missing-source": None,
    }
    assert snapshot.checked_at == checked_at
    assert guard_store.latest_snapshot("guard") == snapshot
    assert "secret-token" not in snapshot.model_dump_json()


def test_power_bi_service_missing_env_is_explicit_without_secret_material(
    tmp_path,
    monkeypatch,
) -> None:
    monitoring = WorkspaceStore(Storage(tmp_path / "state.db"), "local")
    guard_store = SQLitePowerBIGuardStore(tmp_path / "power-bi.db", "local")
    guard_store.initialize()
    guard_store.upsert_guard(
        PowerBIGuardDefinition(
            id="guard",
            name="Executive Model",
            power_bi_workspace_id="group",
            dataset_id="dataset",
            auth_token_env="POWER_BI_MISSING_TOKEN",
        )
    )
    monkeypatch.delenv("POWER_BI_MISSING_TOKEN", raising=False)
    service = PowerBIGuardService(guard_store, monitoring)

    snapshot = service.check_guard("guard")

    assert snapshot.available is False
    assert snapshot.trust_case == "authorization_missing"
    assert snapshot.error == "Power BI Authorization header is not configured."
