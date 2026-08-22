from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .incidents import incident_transition
from .models import HealthStatus, IncidentTransition, Observation


class TrustBadge(str, Enum):
    NOT_MONITORED = "Not monitored"
    TRUSTED = "Trusted"
    ATTENTION = "Attention"
    CRITICAL = "Critical"


class ReliabilityWindow(BaseModel):
    days: int = Field(gt=0)
    check_count: int = Field(ge=0)
    successful_check_count: int = Field(ge=0)
    successful_check_pct: float | None = Field(default=None, ge=0, le=1)
    healthy_count: int = Field(ge=0)
    healthy_check_pct: float | None = Field(default=None, ge=0, le=1)
    warning_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    incident_count: int = Field(ge=0)
    recovered_incident_count: int = Field(ge=0)
    stale_occurrence_count: int = Field(ge=0)
    data_rule_failure_occurrence_count: int = Field(ge=0)
    mttr_minutes: float | None = Field(default=None, ge=0)


class ReliabilityScorecard(BaseModel):
    source_id: str
    as_of: datetime
    current_health: HealthStatus | None = None
    badge: TrustBadge
    latest_observation_at: datetime | None = None
    history_complete: bool = True
    window_7d: ReliabilityWindow
    window_30d: ReliabilityWindow


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Scorecard timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _badge_for_health(health: HealthStatus | None) -> TrustBadge:
    if health is None:
        return TrustBadge.NOT_MONITORED
    if health == HealthStatus.HEALTHY:
        return TrustBadge.TRUSTED
    if health == HealthStatus.WARNING:
        return TrustBadge.ATTENTION
    return TrustBadge.CRITICAL


def _is_successful(observation: Observation) -> bool:
    return observation.available and observation.profile is not None


def _is_stale_occurrence(observation: Observation) -> bool:
    return any(finding.detector == "freshness" for finding in observation.findings)


def _is_data_rule_occurrence(observation: Observation) -> bool:
    return any(
        finding.detector == "data_rule" or finding.detector.startswith("data_rule:")
        for finding in observation.findings
    )


def _incident_events(
    observations: list[tuple[datetime, Observation]],
    *,
    history_complete: bool,
) -> list[tuple[datetime, IncidentTransition, float | None]]:
    events: list[tuple[datetime, IncidentTransition, float | None]] = []
    previous: Observation | None = None
    opened_at: datetime | None = None

    for index, (observed_at, observation) in enumerate(observations):
        transition = incident_transition(previous, observation)
        if index == 0 and not history_complete and observation.health != HealthStatus.HEALTHY:
            transition = None
        if transition == IncidentTransition.OPENED:
            opened_at = observed_at
            events.append((observed_at, transition, None))
        elif transition == IncidentTransition.ESCALATED:
            events.append((observed_at, transition, None))
        elif transition == IncidentTransition.RECOVERED:
            recovery_minutes = None
            if opened_at is not None:
                recovery_minutes = (observed_at - opened_at).total_seconds() / 60
            events.append((observed_at, transition, recovery_minutes))
            opened_at = None
        previous = observation

    return events


def _window(
    observations: list[tuple[datetime, Observation]],
    events: list[tuple[datetime, IncidentTransition, float | None]],
    *,
    as_of: datetime,
    days: int,
) -> ReliabilityWindow:
    start = as_of - timedelta(days=days)
    current = [item for observed_at, item in observations if start <= observed_at <= as_of]
    check_count = len(current)
    successful_count = sum(_is_successful(item) for item in current)
    healthy_count = sum(item.health == HealthStatus.HEALTHY for item in current)
    warning_count = sum(item.health == HealthStatus.WARNING for item in current)
    critical_count = sum(item.health == HealthStatus.CRITICAL for item in current)
    stale_count = sum(_is_stale_occurrence(item) for item in current)
    data_rule_count = sum(_is_data_rule_occurrence(item) for item in current)

    window_events = [event for event in events if start <= event[0] <= as_of]
    incident_count = sum(event[1] == IncidentTransition.OPENED for event in window_events)
    recovered_events = [
        event for event in window_events if event[1] == IncidentTransition.RECOVERED
    ]
    recovery_minutes = [event[2] for event in recovered_events if event[2] is not None]

    return ReliabilityWindow(
        days=days,
        check_count=check_count,
        successful_check_count=successful_count,
        successful_check_pct=(round(successful_count / check_count, 4) if check_count else None),
        healthy_count=healthy_count,
        healthy_check_pct=(round(healthy_count / check_count, 4) if check_count else None),
        warning_count=warning_count,
        critical_count=critical_count,
        incident_count=incident_count,
        recovered_incident_count=len(recovered_events),
        stale_occurrence_count=stale_count,
        data_rule_failure_occurrence_count=data_rule_count,
        mttr_minutes=(
            round(sum(recovery_minutes) / len(recovery_minutes), 1)
            if recovery_minutes
            else None
        ),
    )


def build_reliability_scorecard(
    source_id: str,
    observations: list[Observation],
    *,
    as_of: datetime,
    history_complete: bool = True,
) -> ReliabilityScorecard:
    """Derive an explainable reliability scorecard from existing observation evidence.

    The trust badge maps only the latest current Health state. Historical metrics explain recent
    reliability but never override Health or act as a second classifier.
    """

    as_of_utc = _utc(as_of)
    normalized: list[tuple[datetime, Observation]] = []
    for observation in observations:
        if observation.source_id != source_id:
            raise ValueError("Scorecard observations must all match source_id")
        observed_at = _utc(observation.observed_at)
        if observed_at <= as_of_utc:
            normalized.append((observed_at, observation))

    normalized.sort(key=lambda item: (item[0], item[1].id))
    latest = normalized[-1] if normalized else None
    events = _incident_events(normalized, history_complete=history_complete)

    return ReliabilityScorecard(
        source_id=source_id,
        as_of=as_of_utc,
        current_health=latest[1].health if latest else None,
        badge=_badge_for_health(latest[1].health if latest else None),
        latest_observation_at=latest[0] if latest else None,
        history_complete=history_complete,
        window_7d=_window(normalized, events, as_of=as_of_utc, days=7),
        window_30d=_window(normalized, events, as_of=as_of_utc, days=30),
    )
