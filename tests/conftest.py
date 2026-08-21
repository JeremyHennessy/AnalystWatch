from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.service import MonitorService
from analystwatch.storage import Storage


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def base_frame() -> pd.DataFrame:
    rows = 1000
    return pd.DataFrame(
        {
            "id": list(range(1, rows + 1)),
            "amount": [8000 + (index % 101) for index in range(rows)],
            "jurisdiction": [
                None if index < 20 else "CA" if index % 2 else "NY" for index in range(rows)
            ],
            "segment": [
                "A" if index % 5 < 2 else "B" if index % 5 < 4 else "C"
                for index in range(rows)
            ],
            "as_of": ["2026-08-21"] * rows,
        }
    )


@pytest.fixture
def service(tmp_path: Path) -> MonitorService:
    return MonitorService(Storage(tmp_path / "analystwatch.db"))


def write_csv_source(
    service: MonitorService,
    path: Path,
    frame: pd.DataFrame,
    *,
    source_id: str = "market",
    config: MonitoringConfig | None = None,
) -> SourceDefinition:
    frame.to_csv(path, index=False)
    source = SourceDefinition(
        id=source_id,
        name="Market Data",
        source_type=SourceType.CSV,
        location=str(path),
        config=config or MonitoringConfig(unique_keys=["id"]),
    )
    service.add_source(source)
    return source
