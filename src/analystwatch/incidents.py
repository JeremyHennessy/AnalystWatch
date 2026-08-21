from __future__ import annotations

from .models import (
    HealthStatus,
    IncidentSnapshot,
    IncidentStatus,
    IncidentTransition,
    NotificationCandidate,
    Observation,
)

_SEVERITY = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.WARNING: 1,
    HealthStatus.CRITICAL: 2,
}


def _is_unhealthy(observation: Observation) -> bool:
    return observation.health != HealthStatus.HEALTHY


def incident_transition(
    previous: Observation | None,
    current: Observation,
) -> IncidentTransition | None:
    if current.health == HealthStatus.HEALTHY:
        if previous and previous.health != HealthStatus.HEALTHY:
            return IncidentTransition.RECOVERED
        return None

    if previous is None or previous.health == HealthStatus.HEALTHY:
        return IncidentTransition.OPENED
    if previous.health == HealthStatus.WARNING and current.health == HealthStatus.CRITICAL:
        return IncidentTransition.ESCALATED
    return None


def notification_candidate(
    previous: Observation | None,
    current: Observation,
) -> NotificationCandidate | None:
    transition = incident_transition(previous, current)
    if transition is None:
        return None

    if transition == IncidentTransition.OPENED:
        reason = f"Source entered {current.health.value} health from a non-incident state."
    elif transition == IncidentTransition.ESCALATED:
        reason = "Open incident escalated from Warning to Critical."
    else:
        reason = "Open incident recovered to Healthy."

    return NotificationCandidate(
        id=f"{current.id}:{transition.value.lower()}",
        source_id=current.source_id,
        observation_id=current.id,
        transition=transition,
        previous_health=previous.health if previous else None,
        current_health=current.health,
        created_at=current.observed_at,
        reason=reason,
    )


def latest_incident(observations: list[Observation]) -> IncidentSnapshot | None:
    if not observations:
        return None

    first_unhealthy_index = next(
        (index for index, item in enumerate(observations) if _is_unhealthy(item)),
        None,
    )
    if first_unhealthy_index is None:
        return None

    start = first_unhealthy_index
    end = start
    while end < len(observations) and _is_unhealthy(observations[end]):
        end += 1

    unhealthy_block = observations[start:end]
    opened = unhealthy_block[-1]
    latest_unhealthy = unhealthy_block[0]
    peak = max((item.health for item in unhealthy_block), key=_SEVERITY.__getitem__)

    if start == 0:
        return IncidentSnapshot(
            source_id=opened.source_id,
            status=IncidentStatus.OPEN,
            opened_observation_id=opened.id,
            opened_at=opened.observed_at,
            latest_incident_observation_id=latest_unhealthy.id,
            updated_at=latest_unhealthy.observed_at,
            current_health=latest_unhealthy.health,
            peak_health=peak,
            observation_count=len(unhealthy_block),
        )

    recovered = observations[start - 1]
    return IncidentSnapshot(
        source_id=opened.source_id,
        status=IncidentStatus.RECOVERED,
        opened_observation_id=opened.id,
        opened_at=opened.observed_at,
        latest_incident_observation_id=latest_unhealthy.id,
        updated_at=recovered.observed_at,
        current_health=HealthStatus.HEALTHY,
        peak_health=peak,
        observation_count=len(unhealthy_block),
        recovered_observation_id=recovered.id,
        recovered_at=recovered.observed_at,
    )
