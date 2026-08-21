from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from analystwatch.models import (
    HealthStatus,
    IncidentTransition,
    MonitoringConfig,
    NotificationCandidate,
    NotificationCandidateState,
    SourceDefinition,
    SourceType,
)
from analystwatch.pages import build_pages_site
from analystwatch.web import create_app


def _source(
    path: Path,
    *,
    transitions: list[IncidentTransition] | None = None,
) -> SourceDefinition:
    return SourceDefinition(
        id="market",
        name="Market",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            unique_keys=["id"],
            notification_transitions=transitions or [],
        ),
    )


def _healthy(path: Path, count: int = 20) -> None:
    pd.DataFrame({"id": range(count), "value": [100] * count}).to_csv(path, index=False)


def test_default_notification_policy_suppresses_transition_candidate(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    service.add_source(_source(path))
    service.check_source("market")
    path.unlink()

    service.check_source("market")

    candidate = service.notification_candidates("market")[0]
    assert candidate.transition == IncidentTransition.OPENED
    assert candidate.state == NotificationCandidateState.SUPPRESSED
    assert candidate.policy_enabled_transitions == []
    assert "No notification transitions" in (candidate.policy_reason or "")


def test_enabled_transition_becomes_eligible_but_is_not_delivered(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    service.add_source(_source(path, transitions=[IncidentTransition.OPENED]))
    service.check_source("market")
    path.unlink()

    failure = service.check_source("market")

    candidate = service.notification_candidates("market")[0]
    assert candidate.observation_id == failure.id
    assert candidate.state == NotificationCandidateState.ELIGIBLE
    assert candidate.policy_enabled_transitions == [IncidentTransition.OPENED]
    assert candidate.evaluated_at == failure.observed_at


def test_policy_snapshot_is_not_rewritten_after_source_policy_edit(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    original = _source(path, transitions=[IncidentTransition.OPENED])
    service.add_source(original)
    service.check_source("market")
    path.unlink()
    service.check_source("market")
    original_candidate = service.notification_candidates("market")[0]

    _healthy(path)
    replacement = original.model_copy(
        update={
            "config": original.config.model_copy(
                update={"notification_transitions": [IncidentTransition.RECOVERED]}
            )
        }
    )
    result = service.update_source("market", replacement)

    assert result.ready is True
    stored = service.notification_candidates("market")[0]
    assert stored.id == original_candidate.id
    assert stored.state == NotificationCandidateState.ELIGIBLE
    assert stored.policy_enabled_transitions == [IncidentTransition.OPENED]


def test_recovery_uses_policy_active_when_recovery_occurs(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    original = _source(path, transitions=[IncidentTransition.OPENED])
    service.add_source(original)
    baseline_frame = pd.read_csv(path)
    service.check_source("market")
    path.unlink()
    service.check_source("market")

    replacement = original.model_copy(
        update={
            "config": original.config.model_copy(
                update={"notification_transitions": [IncidentTransition.RECOVERED]}
            )
        }
    )
    baseline_frame.to_csv(path, index=False)
    assert service.update_source("market", replacement).ready is True
    service.check_source("market")

    candidates = service.notification_candidates("market")
    recovery = next(item for item in candidates if item.transition == IncidentTransition.RECOVERED)
    opened = next(item for item in candidates if item.transition == IncidentTransition.OPENED)
    assert recovery.state == NotificationCandidateState.ELIGIBLE
    assert recovery.policy_enabled_transitions == [IncidentTransition.RECOVERED]
    assert opened.policy_enabled_transitions == [IncidentTransition.OPENED]


def test_legacy_pending_candidate_evaluation_is_explicit_and_idempotent(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    source = _source(path, transitions=[IncidentTransition.OPENED])
    service.add_source(source)
    observation = service.check_source("market")
    legacy = NotificationCandidate(
        id="legacy:opened",
        source_id="market",
        observation_id=observation.id,
        transition=IncidentTransition.OPENED,
        previous_health=HealthStatus.HEALTHY,
        current_health=HealthStatus.CRITICAL,
        created_at=observation.observed_at,
        reason="Legacy v0.5 candidate",
    )
    with service.storage.connect() as db:
        db.execute(
            """
            INSERT INTO notification_candidates(
                id, source_id, observation_id, created_at, candidate_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                legacy.id,
                legacy.source_id,
                legacy.observation_id,
                legacy.created_at.isoformat(),
                legacy.model_dump_json(),
            ),
        )

    first = service.evaluate_pending_notification_candidates("market")
    second = service.evaluate_pending_notification_candidates("market")

    assert len(first) == 1
    assert first[0].state == NotificationCandidateState.ELIGIBLE
    assert first[0].policy_enabled_transitions == [IncidentTransition.OPENED]
    assert second == []


def test_duplicate_notification_transitions_are_rejected():
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        MonitoringConfig(
            notification_transitions=[IncidentTransition.OPENED, IncidentTransition.OPENED]
        )


def test_pages_exposes_policy_counts_without_delivery_controls(service, tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    service.add_source(_source(path, transitions=[IncidentTransition.OPENED]))
    service.check_source("market")
    path.unlink()
    service.check_source("market")

    output = build_pages_site(service.storage, tmp_path / "site")
    detail = (output / "sources" / "market" / "index.html").read_text(encoding="utf-8")

    assert "Eligible transitions: Opened" in detail
    assert "1 Eligible" in detail
    assert "still does not send email, Slack, webhooks" in detail
    assert "Send notification" not in detail


def test_policy_evaluation_api_only_evaluates_pending_candidates(tmp_path: Path):
    path = tmp_path / "market.csv"
    _healthy(path)
    app = create_app(tmp_path / "web.db")
    source = _source(path, transitions=[IncidentTransition.OPENED])
    app.state.service.add_source(source)
    observation = app.state.service.check_source("market")
    legacy = NotificationCandidate(
        id="legacy:opened",
        source_id="market",
        observation_id=observation.id,
        transition=IncidentTransition.OPENED,
        current_health=HealthStatus.CRITICAL,
        created_at=observation.observed_at,
        reason="Legacy candidate",
    )
    with app.state.storage.connect() as db:
        db.execute(
            """
            INSERT INTO notification_candidates(
                id, source_id, observation_id, created_at, candidate_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                legacy.id,
                legacy.source_id,
                legacy.observation_id,
                legacy.created_at.isoformat(),
                legacy.model_dump_json(),
            ),
        )
    client = TestClient(app)

    first = client.post("/api/notification-candidates/evaluate", params={"source_id": "market"})
    second = client.post("/api/notification-candidates/evaluate", params={"source_id": "market"})

    assert first.status_code == 200
    assert first.json()[0]["state"] == "Eligible"
    assert second.status_code == 200
    assert second.json() == []
