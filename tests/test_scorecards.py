from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analystwatch.models import DatasetProfile, Finding, HealthStatus, Observation
from analystwatch.scorecards import TrustBadge, build_reliability_scorecard

AS_OF = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)
PROFILE = DatasetProfile(row_count=1, column_count=0, columns={})


def _finding(detector: str, *, severity: HealthStatus = HealthStatus.WARNING) -> Finding:
    return Finding(
        severity=severity,
        detector=detector,
        description=f"{detector} finding",
        why_flagged="deterministic test evidence",
    )


def _observation(
    observation_id: str,
    observed_at: datetime,
    health: HealthStatus,
    *,
    source_id: str = "source-a",
    successful: bool = True,
    findings: list[Finding] | None = None,
) -> Observation:
    return Observation(
        id=observation_id,
        source_id=source_id,
        observed_at=observed_at,
        available=successful,
        health=health,
        findings=findings or [],
        profile=PROFILE if successful else None,
    )


def test_scorecard_without_history_is_explicitly_not_monitored() -> None:
    scorecard = build_reliability_scorecard("source-a", [], as_of=AS_OF)

    assert scorecard.badge == TrustBadge.NOT_MONITORED
    assert scorecard.current_health is None
    assert scorecard.latest_observation_at is None
    for window in (scorecard.window_7d, scorecard.window_30d):
        assert window.check_count == 0
        assert window.successful_check_pct is None
        assert window.healthy_check_pct is None
        assert window.incident_count == 0
        assert window.mttr_minutes is None


@pytest.mark.parametrize(
    ("health", "badge"),
    [
        (HealthStatus.HEALTHY, TrustBadge.TRUSTED),
        (HealthStatus.WARNING, TrustBadge.ATTENTION),
        (HealthStatus.CRITICAL, TrustBadge.CRITICAL),
    ],
)
def test_badge_maps_only_current_health(health: HealthStatus, badge: TrustBadge) -> None:
    observations = [
        _observation("old-critical", AS_OF - timedelta(days=2), HealthStatus.CRITICAL),
        _observation("current", AS_OF - timedelta(hours=1), health),
    ]

    scorecard = build_reliability_scorecard("source-a", observations, as_of=AS_OF)

    assert scorecard.current_health == health
    assert scorecard.badge == badge


def test_windows_expose_transparent_reliability_incident_and_finding_metrics() -> None:
    observations = [
        _observation("older", AS_OF - timedelta(days=8), HealthStatus.HEALTHY),
        _observation(
            "fresh",
            AS_OF - timedelta(days=6),
            HealthStatus.HEALTHY,
            findings=[_finding("freshness"), _finding("freshness")],
        ),
        _observation(
            "opened",
            AS_OF - timedelta(days=5),
            HealthStatus.WARNING,
            findings=[_finding("data_rule:first"), _finding("data_rule:second")],
        ),
        _observation(
            "escalated",
            AS_OF - timedelta(days=4),
            HealthStatus.CRITICAL,
            successful=False,
        ),
        _observation("recovered", AS_OF - timedelta(days=3), HealthStatus.HEALTHY),
    ]

    scorecard = build_reliability_scorecard("source-a", observations, as_of=AS_OF)
    seven = scorecard.window_7d
    thirty = scorecard.window_30d

    assert seven.check_count == 4
    assert seven.successful_check_count == 3
    assert seven.successful_check_pct == 0.75
    assert seven.healthy_count == 2
    assert seven.healthy_check_pct == 0.5
    assert seven.warning_count == 1
    assert seven.critical_count == 1
    assert seven.incident_count == 1
    assert seven.recovered_incident_count == 1
    assert seven.mttr_minutes == 2880.0
    assert seven.stale_occurrence_count == 1
    assert seven.data_rule_failure_occurrence_count == 1

    assert thirty.check_count == 5
    assert thirty.successful_check_count == 4
    assert thirty.successful_check_pct == 0.8
    assert thirty.healthy_count == 3
    assert thirty.healthy_check_pct == 0.6
    assert thirty.incident_count == 1
    assert thirty.recovered_incident_count == 1


def test_recovery_inside_window_keeps_mttr_without_fabricating_new_incident() -> None:
    observations = [
        _observation("opened", AS_OF - timedelta(days=8), HealthStatus.WARNING),
        _observation("recovered", AS_OF - timedelta(days=6), HealthStatus.HEALTHY),
    ]

    scorecard = build_reliability_scorecard("source-a", observations, as_of=AS_OF)

    assert scorecard.window_7d.incident_count == 0
    assert scorecard.window_7d.recovered_incident_count == 1
    assert scorecard.window_7d.mttr_minutes == 2880.0
    assert scorecard.window_30d.incident_count == 1


def test_window_boundaries_are_inclusive_and_older_checks_are_excluded() -> None:
    observations = [
        _observation("seven", AS_OF - timedelta(days=7), HealthStatus.HEALTHY),
        _observation("thirty", AS_OF - timedelta(days=30), HealthStatus.HEALTHY),
        _observation(
            "too-old",
            AS_OF - timedelta(days=30, seconds=1),
            HealthStatus.HEALTHY,
        ),
    ]

    scorecard = build_reliability_scorecard("source-a", observations, as_of=AS_OF)

    assert scorecard.window_7d.check_count == 1
    assert scorecard.window_30d.check_count == 2


def test_future_observations_are_excluded_and_unsorted_input_is_deterministic() -> None:
    past_warning = _observation(
        "past-warning",
        AS_OF - timedelta(days=2),
        HealthStatus.WARNING,
    )
    current_healthy = _observation(
        "current-healthy",
        AS_OF - timedelta(hours=1),
        HealthStatus.HEALTHY,
    )
    future_critical = _observation(
        "future-critical",
        AS_OF + timedelta(hours=1),
        HealthStatus.CRITICAL,
    )

    scorecard = build_reliability_scorecard(
        "source-a",
        [future_critical, current_healthy, past_warning],
        as_of=AS_OF,
    )

    assert scorecard.current_health == HealthStatus.HEALTHY
    assert scorecard.badge == TrustBadge.TRUSTED
    assert scorecard.latest_observation_at == AS_OF - timedelta(hours=1)
    assert scorecard.window_7d.check_count == 2
    assert scorecard.window_7d.incident_count == 1
    assert scorecard.window_7d.recovered_incident_count == 1


def test_scorecard_rejects_mixed_sources() -> None:
    observations = [
        _observation(
            "wrong-source",
            AS_OF - timedelta(hours=1),
            HealthStatus.HEALTHY,
            source_id="source-b",
        )
    ]

    with pytest.raises(ValueError, match="must all match source_id"):
        build_reliability_scorecard("source-a", observations, as_of=AS_OF)


def test_scorecard_rejects_naive_timestamps() -> None:
    naive = AS_OF.replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        build_reliability_scorecard("source-a", [], as_of=naive)
