from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from .delivery import DryRunDeliveryAdapter
from .detectors import detect_freshness, detect_profile_changes, health_from_findings
from .incidents import (
    evaluate_notification_candidate,
    latest_incident,
    notification_candidate,
)
from .ingest import ingest_source
from .models import (
    BaselineReview,
    DeliveryAttempt,
    DeliveryAttemptState,
    DeliveryReconciliationOutcome,
    DeliveryRetryDecision,
    Finding,
    HealthStatus,
    IncidentSnapshot,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    ObservationReview,
    ObservationReviewState,
    RunDecision,
    SourceDefinition,
)
from .preflight import SourcePreflight, preflight_source
from .profile import profile_dataframe
from .scheduler import run_decision
from .storage import Storage


class MonitorService:
    def __init__(self, storage: Storage, execution_owner: str | None = None):
        self.storage = storage
        self.storage.initialize()
        default_owner = os.environ.get("ANALYSTWATCH_EXECUTION_OWNER")
        if default_owner is None:
            default_owner = f"{socket.gethostname()}:{os.getpid()}"
        self.execution_owner = self._validate_execution_owner(
            execution_owner if execution_owner is not None else default_owner
        )

    @staticmethod
    def _validate_execution_owner(owner: str) -> str:
        if not owner or owner != owner.strip():
            raise ValueError("execution owner must be non-empty and trimmed")
        return owner

    def add_source(self, source: SourceDefinition) -> SourceDefinition:
        self.storage.upsert_source(source)
        return source

    def add_sources(self, sources: list[SourceDefinition]) -> list[SourceDefinition]:
        for source in sources:
            self.add_source(source)
        return sources

    def preflight_source(
        self,
        source: SourceDefinition,
        *,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ) -> SourcePreflight:
        return preflight_source(source, client=client, now=now)

    def onboard_source(
        self,
        source: SourceDefinition,
        *,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ) -> SourcePreflight:
        if self.storage.get_source(source.id) is not None:
            raise ValueError(
                f"Source ID already exists: {source.id}. "
                "Editing existing sources is a separate workflow."
            )
        preflight = self.preflight_source(source, client=client, now=now)
        if not preflight.ready:
            return preflight
        self.add_source(source)
        return preflight.model_copy(update={"accepted": True})

    def update_source(
        self,
        source_id: str,
        replacement: SourceDefinition,
        *,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ) -> SourcePreflight:
        existing = self.storage.get_source(source_id)
        if existing is None:
            raise KeyError(f"Unknown source: {source_id}")
        if replacement.id != source_id:
            raise ValueError("Source ID cannot change during an update")
        preflight = self.preflight_source(replacement, client=client, now=now)
        if not preflight.ready:
            return preflight
        self.add_source(replacement)
        return preflight.model_copy(update={"accepted": True})

    def review_observation(
        self,
        source_id: str,
        observation_id: str,
        state: ObservationReviewState,
        *,
        now: datetime | None = None,
    ) -> ObservationReview:
        observation = self.storage.get_observation(observation_id)
        if observation is None or observation.source_id != source_id:
            raise ValueError("Observation does not belong to this source")
        if observation.health == HealthStatus.HEALTHY:
            raise ValueError("Healthy observations do not require an alert review state")
        reviewed_at = now or datetime.now(timezone.utc)
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
        return self.storage.save_review(
            ObservationReview(
                observation_id=observation.id,
                source_id=source_id,
                state=state,
                updated_at=reviewed_at,
            )
        )

    def incident(self, source_id: str) -> IncidentSnapshot | None:
        if self.storage.get_source(source_id) is None:
            raise KeyError(f"Unknown source: {source_id}")
        return latest_incident(self.storage.list_observations(source_id, limit=200))

    def notification_candidates(
        self,
        source_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[NotificationCandidate]:
        if source_id is not None and self.storage.get_source(source_id) is None:
            raise KeyError(f"Unknown source: {source_id}")
        return self.storage.list_notification_candidates(source_id, limit=limit)

    def evaluate_pending_notification_candidates(
        self,
        source_id: str,
        *,
        now: datetime | None = None,
    ) -> list[NotificationCandidate]:
        source = self.storage.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        evaluated_at = now or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
        updated: list[NotificationCandidate] = []
        for candidate in self.storage.list_notification_candidates(source_id, limit=1000):
            if candidate.state != NotificationCandidateState.PENDING:
                continue
            evaluated = evaluate_notification_candidate(
                candidate,
                source.config.notification_transitions,
                evaluated_at=evaluated_at,
            )
            updated.append(self.storage.update_notification_candidate(evaluated))
        return updated

    def delivery_attempts(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryAttempt]:
        if candidate_id is not None:
            candidate = self.storage.get_notification_candidate(candidate_id)
            if candidate is None:
                raise KeyError(f"Unknown notification candidate: {candidate_id}")
        if source_id is not None and self.storage.get_source(source_id) is None:
            raise KeyError(f"Unknown source: {source_id}")
        return self.storage.list_delivery_attempts(
            candidate_id=candidate_id,
            source_id=source_id,
            limit=limit,
        )

    def delivery_retry_decision(
        self,
        candidate_id: str,
        *,
        now: datetime | None = None,
        adapter_name: str = "dry-run",
    ) -> DeliveryRetryDecision:
        candidate = self.storage.get_notification_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown notification candidate: {candidate_id}")
        source = self.storage.get_source(candidate.source_id)
        if source is None:
            raise KeyError(f"Unknown source: {candidate.source_id}")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if candidate.state != NotificationCandidateState.ELIGIBLE:
            return DeliveryRetryDecision(
                candidate_id=candidate.id,
                due=False,
                reason="Only Eligible notification candidates can be attempted.",
            )

        attempts = [
            item
            for item in self.storage.list_delivery_attempts(candidate_id=candidate.id, limit=1000)
            if item.adapter == adapter_name
        ]
        latest = max(attempts, key=lambda item: item.attempt_number, default=None)
        if latest is None:
            return DeliveryRetryDecision(
                candidate_id=candidate.id,
                due=True,
                reason="No delivery attempt has been claimed for this candidate.",
            )
        if latest.state == DeliveryAttemptState.SUCCEEDED:
            return DeliveryRetryDecision(
                candidate_id=candidate.id,
                due=False,
                reason="A successful delivery attempt already exists.",
                last_attempt_id=latest.id,
                last_state=latest.state,
            )
        if latest.state == DeliveryAttemptState.PREPARED:
            return DeliveryRetryDecision(
                candidate_id=candidate.id,
                due=False,
                reason="Prepared attempt requires explicit reconciliation before retry.",
                last_attempt_id=latest.id,
                last_state=latest.state,
            )
        if latest.completed_at is None:
            return DeliveryRetryDecision(
                candidate_id=candidate.id,
                due=False,
                reason="Failed attempt is missing its completion timestamp.",
                last_attempt_id=latest.id,
                last_state=latest.state,
            )

        next_retry_at = latest.completed_at + timedelta(
            minutes=source.config.delivery_retry_minutes
        )
        due = current >= next_retry_at
        return DeliveryRetryDecision(
            candidate_id=candidate.id,
            due=due,
            reason=(
                "Failed attempt is eligible for retry."
                if due
                else "Failed attempt is inside the configured retry delay."
            ),
            last_attempt_id=latest.id,
            last_state=latest.state,
            next_retry_at=next_retry_at,
        )

    def reconcile_delivery_attempt(
        self,
        attempt_id: str,
        outcome: DeliveryReconciliationOutcome,
        note: str,
        *,
        now: datetime | None = None,
        reviewer: str | None = None,
    ) -> DeliveryAttempt:
        if not note or note != note.strip():
            raise ValueError("Reconciliation note must be non-empty and trimmed")
        reconciled_at = now or datetime.now(timezone.utc)
        if reconciled_at.tzinfo is None:
            reconciled_at = reconciled_at.replace(tzinfo=timezone.utc)
        reconciled_by = self._validate_execution_owner(
            reviewer if reviewer is not None else self.execution_owner
        )
        state = (
            DeliveryAttemptState.SUCCEEDED
            if outcome == DeliveryReconciliationOutcome.SUCCEEDED
            else DeliveryAttemptState.FAILED
        )
        return self.storage.reconcile_prepared_delivery_attempt(
            attempt_id,
            state,
            reconciled_at=reconciled_at,
            note=note,
            reconciled_by=reconciled_by,
        )

    def dry_run_delivery(
        self,
        candidate_id: str,
        idempotency_key: str,
        *,
        now: datetime | None = None,
        adapter: DryRunDeliveryAdapter | None = None,
        execution_owner: str | None = None,
    ) -> DeliveryAttempt:
        if not idempotency_key or idempotency_key != idempotency_key.strip():
            raise ValueError("idempotency_key must be non-empty and trimmed")
        candidate = self.storage.get_notification_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown notification candidate: {candidate_id}")
        source = self.storage.get_source(candidate.source_id)
        if source is None:
            raise KeyError(f"Unknown source: {candidate.source_id}")

        created_at = now or datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        delivery_adapter = adapter or DryRunDeliveryAdapter()
        claim_owner = self._validate_execution_owner(
            execution_owner if execution_owner is not None else self.execution_owner
        )
        prepared, replayed = self.storage.claim_delivery_attempt(
            candidate_id,
            idempotency_key,
            delivery_adapter.name,
            created_at=created_at,
            retry_minutes=source.config.delivery_retry_minutes,
            claim_owner=claim_owner,
        )
        if replayed:
            return prepared

        try:
            result = delivery_adapter.deliver(candidate)
        except Exception as exc:
            completed = prepared.model_copy(
                update={
                    "state": DeliveryAttemptState.FAILED,
                    "completed_at": created_at,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            if result.success:
                completed = prepared.model_copy(
                    update={
                        "state": DeliveryAttemptState.SUCCEEDED,
                        "completed_at": created_at,
                        "result_summary": result.summary,
                    }
                )
            else:
                completed = prepared.model_copy(
                    update={
                        "state": DeliveryAttemptState.FAILED,
                        "completed_at": created_at,
                        "error": result.error or "Dry-run adapter reported failure.",
                    }
                )
        return self.storage.update_delivery_attempt(completed)

    def baseline_review(
        self,
        source_id: str,
        observation_id: str | None = None,
    ) -> BaselineReview:
        source = self.storage.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        current = self.storage.get_baseline(source_id)
        candidate = (
            self.storage.get_observation(observation_id)
            if observation_id
            else self.storage.get_latest(source_id)
        )
        blockers: list[str] = []
        if current is None:
            blockers.append("No current baseline is established.")
        if candidate is None or candidate.source_id != source_id:
            blockers.append("No candidate observation is available for this source.")
        elif not candidate.available or candidate.profile is None:
            blockers.append("The candidate observation is unavailable or has no profile.")
        elif candidate.health != HealthStatus.HEALTHY:
            blockers.append("Only a Healthy observation can be promoted after baseline review.")
        elif current and candidate.id == current.id:
            blockers.append("The candidate is already the current baseline.")
        return BaselineReview(
            source_id=source_id,
            current_baseline=current,
            candidate=candidate,
            ready=not blockers,
            blockers=blockers,
        )

    def promote_baseline_after_review(
        self,
        source_id: str,
        observation_id: str,
        expected_current_baseline_id: str,
    ) -> Observation:
        current = self.storage.get_baseline(source_id)
        if current is None or current.id != expected_current_baseline_id:
            raise ValueError(
                "Baseline changed since review; refresh the candidate before promoting."
            )
        review = self.baseline_review(source_id, observation_id)
        if not review.ready:
            raise ValueError("; ".join(review.blockers))
        return self.storage.promote_baseline(source_id, observation_id)

    def get_run_decision(
        self,
        source_id: str,
        *,
        now: datetime | None = None,
    ) -> RunDecision:
        source = self.storage.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        return run_decision(self.storage, source, now=now)

    def check_due_sources(self, *, now: datetime | None = None) -> list[Observation]:
        observations: list[Observation] = []
        for source in self.storage.list_sources():
            decision = run_decision(self.storage, source, now=now)
            if decision.due:
                observations.append(self.check_source(source.id, now=now))
        return observations

    def check_all_sources(self, *, now: datetime | None = None) -> list[Observation]:
        return [
            self.check_source(source.id, now=now)
            for source in self.storage.list_sources()
            if source.enabled
        ]

    def check_source(
        self,
        source_id: str,
        *,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ) -> Observation:
        source = self.storage.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        if not source.enabled:
            raise ValueError(f"Source is disabled: {source_id}")

        observed_at = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        previous = self.storage.get_latest(source_id)
        baseline = self.storage.get_baseline(source_id)
        reference_observations = self.storage.list_reference_observations(
            source_id, limit=source.config.history_window_size
        )
        history_profiles = [
            item.profile for item in reference_observations if item.profile is not None
        ]

        result = ingest_source(source, client=client)
        findings: list[Finding] = []
        profile = None

        if not result.available or result.dataframe is None:
            findings.append(
                Finding(
                    severity=HealthStatus.CRITICAL,
                    detector="availability",
                    description="Source could not be read successfully.",
                    current_value=result.error,
                    baseline_value="available" if baseline else None,
                    why_flagged=result.error or "The source returned no usable dataset.",
                    confidence="high",
                    likely_impact="Dependent analysis cannot be refreshed reliably.",
                    suggested_investigation="Check the source path/URL and upstream availability.",
                )
            )
        else:
            profile = profile_dataframe(
                result.dataframe,
                source.config.latest_date_field,
                infer_latest_date_field=source.config.infer_latest_date_field,
                numeric_fields=source.config.numeric_fields,
            )
            findings.extend(
                detect_freshness(
                    config=source.config,
                    profile=profile,
                    source_modified_at=result.source_modified_at,
                    observed_at=observed_at,
                )
            )
            if baseline and baseline.profile:
                findings.extend(
                    detect_profile_changes(
                        baseline.profile,
                        profile,
                        source.config,
                        history=history_profiles,
                    )
                )

        health = health_from_findings(findings)
        observation = Observation(
            id=str(uuid4()),
            source_id=source_id,
            observed_at=observed_at,
            available=result.available,
            health=health,
            findings=findings,
            profile=profile,
            http_status=result.http_status,
            response_ms=result.response_ms,
            source_modified_at=result.source_modified_at,
            response_etag=result.response_etag,
            error=result.error,
            is_baseline=baseline is None and result.available and profile is not None,
        )
        candidate = notification_candidate(previous, observation)
        if candidate is not None:
            candidate = evaluate_notification_candidate(
                candidate,
                source.config.notification_transitions,
                evaluated_at=observed_at,
            )
        self.storage.save_observation(
            observation,
            set_baseline=observation.is_baseline,
            notification_candidate=candidate,
        )
        return observation
