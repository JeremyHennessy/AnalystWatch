from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from analystwatch.models import (
    IncidentTransition,
    MonitoringConfig,
    SourceDefinition,
    SourceType,
)
from analystwatch.service import MonitorService
from analystwatch.storage import Storage
from analystwatch.store import MonitoringStore
from analystwatch.workspace import WorkspaceStore, create_workspace_service, validate_workspace_id


def _source(
    path: Path,
    *,
    source_id: str,
    workspace_id: str = "local",
    transitions: list[IncidentTransition] | None = None,
) -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        workspace_id=workspace_id,
        name=f"{workspace_id} source",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            unique_keys=["id"],
            notification_transitions=transitions or [],
        ),
    )


def _healthy_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": list(range(1, 101)),
            "amount": [8000 + (index % 11) for index in range(100)],
            "segment": ["A" if index % 2 else "B" for index in range(100)],
        }
    )


def test_source_definition_defaults_to_local_workspace(tmp_path: Path) -> None:
    source = SourceDefinition(
        id="market",
        name="Market",
        source_type=SourceType.CSV,
        location=str(tmp_path / "market.csv"),
    )

    assert source.workspace_id == "local"


def test_storage_and_workspace_store_satisfy_monitoring_protocol(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    bound = WorkspaceStore(storage, "local")

    assert isinstance(storage, MonitoringStore)
    assert isinstance(bound, MonitoringStore)


def test_workspace_validation_is_strict() -> None:
    assert validate_workspace_id("team-a") == "team-a"
    with pytest.raises(ValueError):
        validate_workspace_id(" team-a")
    with pytest.raises(ValueError):
        validate_workspace_id("team/a")


def test_workspace_store_filters_sources_and_blocks_foreign_writes(tmp_path: Path) -> None:
    db = Storage(tmp_path / "state.db")
    db.initialize()
    alpha = WorkspaceStore(db, "alpha")
    beta = WorkspaceStore(db, "beta")

    alpha_source = _source(tmp_path / "alpha.csv", source_id="alpha-source", workspace_id="alpha")
    alpha.upsert_source(alpha_source)

    assert [item.id for item in alpha.list_sources()] == ["alpha-source"]
    assert beta.list_sources() == []
    assert beta.get_source("alpha-source") is None

    with pytest.raises(ValueError, match="does not match bound workspace"):
        beta.upsert_source(alpha_source)


def test_workspace_store_preserves_default_local_sources(tmp_path: Path) -> None:
    path = tmp_path / "market.csv"
    _healthy_frame().to_csv(path, index=False)
    raw_service = MonitorService(Storage(tmp_path / "state.db"))
    raw_service.add_source(_source(path, source_id="market"))

    local_service = create_workspace_service(Storage(tmp_path / "state.db"), "local")

    assert local_service.storage.get_source("market") is not None
    assert [item.id for item in local_service.storage.list_sources()] == ["market"]


def test_workspace_services_isolate_observations_and_baselines(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    alpha_path = tmp_path / "alpha.csv"
    beta_path = tmp_path / "beta.csv"
    _healthy_frame().to_csv(alpha_path, index=False)
    _healthy_frame().to_csv(beta_path, index=False)

    alpha = create_workspace_service(Storage(db_path), "alpha")
    beta = create_workspace_service(Storage(db_path), "beta")
    alpha.add_source(_source(alpha_path, source_id="alpha-source", workspace_id="alpha"))
    beta.add_source(_source(beta_path, source_id="beta-source", workspace_id="beta"))

    alpha_observation = alpha.check_source("alpha-source")
    beta_observation = beta.check_source("beta-source")

    assert alpha.storage.get_observation(alpha_observation.id) is not None
    assert alpha.storage.get_observation(beta_observation.id) is None
    assert beta.storage.get_observation(alpha_observation.id) is None
    assert alpha.storage.get_baseline("beta-source") is None
    assert beta.storage.get_baseline("alpha-source") is None

    with pytest.raises(KeyError):
        alpha.check_source("beta-source")
    with pytest.raises(KeyError):
        beta.check_source("alpha-source")


def test_foreign_workspace_cannot_reuse_an_existing_global_source_id(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    alpha = create_workspace_service(Storage(db_path), "alpha")
    beta = create_workspace_service(Storage(db_path), "beta")
    alpha_source = _source(tmp_path / "alpha.csv", source_id="shared", workspace_id="alpha")
    beta_source = _source(tmp_path / "beta.csv", source_id="shared", workspace_id="beta")

    alpha.add_source(alpha_source)
    with pytest.raises(ValueError, match="already owned by another workspace"):
        beta.add_source(beta_source)


def test_candidates_and_attempts_do_not_cross_workspace_boundary(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    alpha_path = tmp_path / "alpha.csv"
    beta_path = tmp_path / "beta.csv"
    healthy = _healthy_frame()
    healthy.to_csv(alpha_path, index=False)
    healthy.to_csv(beta_path, index=False)

    alpha = create_workspace_service(Storage(db_path), "alpha", execution_owner="alpha-worker")
    beta = create_workspace_service(Storage(db_path), "beta", execution_owner="beta-worker")
    alpha.add_source(
        _source(
            alpha_path,
            source_id="alpha-source",
            workspace_id="alpha",
            transitions=[IncidentTransition.OPENED],
        )
    )
    beta.add_source(_source(beta_path, source_id="beta-source", workspace_id="beta"))

    alpha.check_source("alpha-source")
    changed = healthy.copy()
    changed["amount"] = changed["amount"] / 100
    changed.to_csv(alpha_path, index=False)
    alpha.check_source("alpha-source")

    candidates = alpha.notification_candidates("alpha-source")
    assert len(candidates) == 1
    assert candidates[0].state.value == "Eligible"
    attempt = alpha.dry_run_delivery(candidates[0].id, "alpha-key")
    assert attempt.state.value == "Succeeded"

    assert beta.storage.get_notification_candidate(candidates[0].id) is None
    assert beta.storage.get_delivery_attempt(attempt.id) is None
    assert beta.storage.list_notification_candidates() == []
    assert beta.storage.list_delivery_attempts() == []

    with pytest.raises(KeyError):
        beta.notification_candidates("alpha-source")
    with pytest.raises(KeyError):
        beta.delivery_attempts(source_id="alpha-source")
