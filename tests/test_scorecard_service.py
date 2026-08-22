from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analystwatch.models import (
    DatasetProfile,
    HealthStatus,
    MonitoringConfig,
    Observation,
    SourceDefinition,
    SourceType,
)
from analystwatch.scorecard_service import ReliabilityScorecardService

AS_OF = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)
PROFILE = DatasetProfile(row_count=1, column_count=0, columns={})


class FakeStore:
    def __init__(
        self,
        source: SourceDefinition | None,
        observations: list[Observation] | None = None,
    ) -> None:
        self.source = source
        self.observations = observations or []
        self.limits: list[int] = []

    def get_source(self, source_id: str) -> SourceDefinition | None:
        if self.source is not None and self.source.id == source_id:
            return self.source
        return None

    def list_observations(self, source_id: str, limit: int = 20) -> list[Observation]:
        self.limits.append(limit)
        return self.observations[:limit]


def _source(*, interval: int = 60) -> SourceDefinition:
    return SourceDefinition(
        id="source-a",
        name="Source A",
        source_type=SourceType.CSV,
        location="source.csv",
        config=MonitoringConfig(monitor_interval_minutes=interval),
    )


def _observation(
    observation_id: str,
    age: timedelta,
    health: HealthStatus,
) -> Observation:
    return Observation(
        id=observation_id,
        source_id="source-a",
        observed_at=AS_OF - age,
        available=True,
        health=health,
        profile=PROFILE,
    )


def test_service_expands_history_until_pre_window_health_context_is_available() -> None:
    store = FakeStore(
        _source(interval=100_000),
        [
            _observation("current", timedelta(days=1), HealthStatus.HEALTHY),
            _observation("incident-later", timedelta(days=10), HealthStatus.WARNING),
            _observation("incident-open", timedelta(days=20), HealthStatus.WARNING),
            _observation("pre-window", timedelta(days=40), HealthStatus.HEALTHY),
        ],
    )
    service = ReliabilityScorecardService(
        store,
        minimum_history_observations=2,
        max_history_observations=8,
    )

    scorecard = service.scorecard("source-a", as_of=AS_OF)

    assert store.limits == [3, 6]
    assert scorecard.history_complete is True
    assert scorecard.window_30d.check_count == 3
    assert scorecard.window_30d.incident_count == 1
    assert scorecard.window_30d.recovered_incident_count == 1
    assert scorecard.window_30d.mttr_minutes == 27360.0


def test_service_marks_capped_history_incomplete_and_does_not_invent_mttr() -> None:
    store = FakeStore(
        _source(),
        [
            _observation("recovered", timedelta(days=1), HealthStatus.HEALTHY),
            _observation("visible-incident", timedelta(days=2), HealthStatus.WARNING),
            _observation("hidden-incident", timedelta(days=40), HealthStatus.WARNING),
            _observation("hidden-healthy", timedelta(days=41), HealthStatus.HEALTHY),
        ],
    )
    service = ReliabilityScorecardService(
        store,
        minimum_history_observations=2,
        max_history_observations=2,
    )

    scorecard = service.scorecard("source-a", as_of=AS_OF)

    assert store.limits == [2]
    assert scorecard.history_complete is False
    assert scorecard.window_30d.incident_count == 0
    assert scorecard.window_30d.recovered_incident_count == 1
    assert scorecard.window_30d.mttr_minutes is None


def test_service_uses_monitoring_cadence_to_bound_high_frequency_history() -> None:
    store = FakeStore(_source(interval=1))
    service = ReliabilityScorecardService(store)

    scorecard = service.scorecard("source-a", as_of=AS_OF)

    assert store.limits == [44642]
    assert scorecard.history_complete is True


def test_service_rejects_unknown_source() -> None:
    service = ReliabilityScorecardService(FakeStore(None))

    with pytest.raises(KeyError, match="Unknown source"):
        service.scorecard("missing", as_of=AS_OF)


def test_service_validates_history_bounds() -> None:
    store = FakeStore(_source())

    with pytest.raises(ValueError, match="must be positive"):
        ReliabilityScorecardService(store, minimum_history_observations=0)
    with pytest.raises(ValueError, match="at least minimum"):
        ReliabilityScorecardService(
            store,
            minimum_history_observations=10,
            max_history_observations=5,
        )
