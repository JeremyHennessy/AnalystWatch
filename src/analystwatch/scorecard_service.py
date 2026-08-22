from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Protocol

from .models import HealthStatus, Observation, SourceDefinition
from .scorecards import ReliabilityScorecard, build_reliability_scorecard


class ScorecardStore(Protocol):
    def get_source(self, source_id: str) -> SourceDefinition | None: ...

    def list_observations(self, source_id: str, limit: int = 20) -> list[Observation]: ...


class ReliabilityScorecardService:
    """Build bounded scorecards without adding a persistence schema."""

    def __init__(
        self,
        storage: ScorecardStore,
        *,
        minimum_history_observations: int = 1000,
        max_history_observations: int = 50_000,
    ) -> None:
        if minimum_history_observations < 1:
            raise ValueError("minimum_history_observations must be positive")
        if max_history_observations < minimum_history_observations:
            raise ValueError(
                "max_history_observations must be at least minimum_history_observations"
            )
        self.storage = storage
        self.minimum_history_observations = minimum_history_observations
        self.max_history_observations = max_history_observations

    def scorecard(
        self,
        source_id: str,
        *,
        as_of: datetime | None = None,
    ) -> ReliabilityScorecard:
        source = self.storage.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        current = as_of or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)

        observations, history_complete = self._history(source, as_of=current)
        return build_reliability_scorecard(
            source.id,
            observations,
            as_of=current,
            history_complete=history_complete,
        )

    def _history(
        self,
        source: SourceDefinition,
        *,
        as_of: datetime,
    ) -> tuple[list[Observation], bool]:
        cutoff = as_of - timedelta(days=30)
        expected_31d_checks = ceil(
            (31 * 24 * 60) / source.config.monitor_interval_minutes
        )
        limit = min(
            max(expected_31d_checks + 2, self.minimum_history_observations),
            self.max_history_observations,
        )

        while True:
            observations = self.storage.list_observations(source.id, limit=limit)
            if len(observations) < limit:
                return observations, True

            eligible = [
                observation
                for observation in observations
                if self._utc(observation.observed_at) <= as_of
            ]
            if eligible:
                oldest = eligible[-1]
                if (
                    self._utc(oldest.observed_at) < cutoff
                    and oldest.health == HealthStatus.HEALTHY
                ):
                    return observations, True

            if limit >= self.max_history_observations:
                return observations, False
            limit = min(limit * 2, self.max_history_observations)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Stored observation timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)
