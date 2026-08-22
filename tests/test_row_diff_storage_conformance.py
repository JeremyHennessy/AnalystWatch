from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from analystwatch.memory_store import MemoryStore
from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.namespaced_storage import NamespacedStorage
from analystwatch.postgres_storage import PostgresStorage
from analystwatch.storage import Storage
from analystwatch.store import MonitoringStore
from analystwatch.workspace import create_workspace_service


@pytest.fixture(params=["sqlite", "namespaced", "memory", "postgres"])
def row_diff_store(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[MonitoringStore]:
    if request.param == "sqlite":
        yield Storage(tmp_path / "legacy.db")
        return
    if request.param == "namespaced":
        yield NamespacedStorage(tmp_path / "namespaced.db", "local")
        return
    if request.param == "memory":
        yield MemoryStore()
        return

    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    store = PostgresStorage(dsn, "local")
    store.initialize()
    store.clear_workspace()
    try:
        yield store
    finally:
        store.clear_workspace()


def _write(path: Path, amount: int) -> None:
    pd.DataFrame(
        {
            "id": [1, 2, 3],
            "amount": [amount, 200, 300],
            "status": ["Active", "Active", "Closed"],
        }
    ).to_csv(path, index=False)


def test_row_snapshot_retention_contract(
    row_diff_store: MonitoringStore,
    tmp_path: Path,
) -> None:
    path = tmp_path / "customers.csv"
    _write(path, 100)
    service = create_workspace_service(row_diff_store, "local")
    service.add_source(
        SourceDefinition(
            id="customers",
            name="Customers",
            source_type=SourceType.CSV,
            location=str(path),
            config=MonitoringConfig(
                unique_keys=["id"],
                row_diff_snapshot_retention=1,
                row_diff_sample_limit=5,
            ),
        )
    )
    started = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)

    baseline = service.check_source("customers", now=started)
    _write(path, 110)
    middle = service.check_source("customers", now=started + timedelta(minutes=1))
    _write(path, 120)
    latest = service.check_source("customers", now=started + timedelta(minutes=2))

    persisted_baseline = service.storage.get_observation(baseline.id)
    persisted_middle = service.storage.get_observation(middle.id)
    persisted_latest = service.storage.get_observation(latest.id)

    assert persisted_baseline is not None and persisted_baseline.row_snapshot is not None
    assert persisted_latest is not None and persisted_latest.row_snapshot is not None
    assert persisted_middle is not None and persisted_middle.row_snapshot is None
    assert persisted_middle.row_diff is not None
    assert persisted_middle.row_diff.previous is not None
    assert persisted_middle.row_diff.previous.changed_count == 1
    assert persisted_middle.row_diff.previous.changed_samples == []
