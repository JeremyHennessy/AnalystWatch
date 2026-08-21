from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock

from .models import (
    DeliveryAttempt,
    DeliveryAttemptState,
    DeliveryMode,
    HealthStatus,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    ObservationReview,
    SourceDefinition,
)


class MemoryStore:
    """Independent in-memory implementation of the MonitoringStore contract.

    This adapter exists to prove service semantics are not coupled to SQLite.
    It is process-local test/runtime state, not durable persistence.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._sources: dict[str, SourceDefinition] = {}
        self._observations: dict[str, Observation] = {}
        self._observation_ids: dict[str, list[str]] = {}
        self._baseline_ids: dict[str, str] = {}
        self._reviews: dict[str, ObservationReview] = {}
        self._candidates: dict[str, NotificationCandidate] = {}
        self._candidate_ids: list[str] = []
        self._attempts: dict[str, DeliveryAttempt] = {}
        self._attempt_ids: list[str] = []
        self._idempotency: dict[str, str] = {}

    def initialize(self) -> None:
        return None

    def upsert_source(self, source: SourceDefinition) -> None:
        with self._lock:
            self._sources[source.id] = source

    def get_source(self, source_id: str) -> SourceDefinition | None:
        with self._lock:
            return self._sources.get(source_id)

    def list_sources(self) -> list[SourceDefinition]:
        with self._lock:
            return [self._sources[key] for key in sorted(self._sources)]

    def save_observation(
        self,
        observation: Observation,
        *,
        set_baseline: bool = False,
        notification_candidate: NotificationCandidate | None = None,
    ) -> None:
        with self._lock:
            if observation.source_id not in self._sources:
                raise ValueError(f"Unknown source: {observation.source_id}")
            if observation.id in self._observations:
                raise ValueError(f"Observation already exists: {observation.id}")
            self._observations[observation.id] = observation
            self._observation_ids.setdefault(observation.source_id, []).append(observation.id)
            if notification_candidate is not None:
                if notification_candidate.observation_id != observation.id:
                    raise ValueError("Notification candidate must belong to the saved observation")
                if notification_candidate.id in self._candidates:
                    raise ValueError(
                        f"Notification candidate already exists: {notification_candidate.id}"
                    )
                if any(
                    item.observation_id == notification_candidate.observation_id
                    for item in self._candidates.values()
                ):
                    raise ValueError("Observation already has a notification candidate")
                self._candidates[notification_candidate.id] = notification_candidate
                self._candidate_ids.append(notification_candidate.id)
            if set_baseline:
                self._baseline_ids[observation.source_id] = observation.id

    def get_observation(self, observation_id: str) -> Observation | None:
        with self._lock:
            return self._observations.get(observation_id)

    def _with_baseline_marker(self, observation: Observation | None) -> Observation | None:
        if observation is None:
            return None
        is_baseline = self._baseline_ids.get(observation.source_id) == observation.id
        if observation.is_baseline == is_baseline:
            return observation
        return observation.model_copy(update={"is_baseline": is_baseline})

    def get_baseline(self, source_id: str) -> Observation | None:
        with self._lock:
            observation_id = self._baseline_ids.get(source_id)
            return self._with_baseline_marker(
                self._observations.get(observation_id) if observation_id else None
            )

    def get_latest(self, source_id: str) -> Observation | None:
        with self._lock:
            ids = self._observation_ids.get(source_id, [])
            if not ids:
                return None
            latest = max(
                (self._observations[item] for item in ids),
                key=lambda item: (item.observed_at, ids.index(item.id)),
            )
            return self._with_baseline_marker(latest)

    def get_last_successful(self, source_id: str) -> Observation | None:
        for observation in self.list_observations(source_id, limit=100):
            if observation.available and observation.profile is not None:
                return observation
        return None

    def list_reference_observations(self, source_id: str, limit: int = 5) -> list[Observation]:
        references: list[Observation] = []
        for observation in self.list_observations(source_id, limit=max(limit * 4, 20)):
            if (
                observation.available
                and observation.profile is not None
                and observation.health == HealthStatus.HEALTHY
            ):
                references.append(observation)
            if len(references) >= limit:
                break
        return references

    def list_observations(self, source_id: str, limit: int = 20) -> list[Observation]:
        with self._lock:
            ids = list(self._observation_ids.get(source_id, []))
            indexed = [(index, self._observations[item]) for index, item in enumerate(ids)]
            indexed.sort(key=lambda pair: (pair[1].observed_at, pair[0]), reverse=True)
            return [self._with_baseline_marker(item) for _, item in indexed[:limit]]  # type: ignore[list-item]

    def save_review(self, review: ObservationReview) -> ObservationReview:
        with self._lock:
            observation = self._observations.get(review.observation_id)
            if observation is None or observation.source_id != review.source_id:
                raise ValueError("Observation does not belong to this source")
            self._reviews[review.observation_id] = review
            return review

    def get_review(self, observation_id: str) -> ObservationReview | None:
        with self._lock:
            return self._reviews.get(observation_id)

    def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None:
        with self._lock:
            return self._candidates.get(candidate_id)

    def list_notification_candidates(
        self,
        source_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[NotificationCandidate]:
        with self._lock:
            indexed = [
                (index, self._candidates[candidate_id])
                for index, candidate_id in enumerate(self._candidate_ids)
                if source_id is None or self._candidates[candidate_id].source_id == source_id
            ]
            indexed.sort(key=lambda pair: (pair[1].created_at, pair[0]), reverse=True)
            return [item for _, item in indexed[:limit]]

    def update_notification_candidate(
        self,
        candidate: NotificationCandidate,
    ) -> NotificationCandidate:
        with self._lock:
            if candidate.id not in self._candidates:
                raise ValueError(f"Unknown notification candidate: {candidate.id}")
            self._candidates[candidate.id] = candidate
            return candidate

    def claim_delivery_attempt(
        self,
        candidate_id: str,
        idempotency_key: str,
        adapter: str,
        *,
        created_at: datetime,
        retry_minutes: int,
        claim_owner: str | None = None,
    ) -> tuple[DeliveryAttempt, bool]:
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise KeyError(f"Unknown notification candidate: {candidate_id}")
            if candidate.state != NotificationCandidateState.ELIGIBLE:
                raise ValueError("Only Eligible notification candidates can be attempted")

            existing_id = self._idempotency.get(idempotency_key)
            if existing_id is not None:
                existing = self._attempts[existing_id]
                if existing.candidate_id != candidate_id or existing.adapter != adapter:
                    raise ValueError("Idempotency key belongs to a different delivery attempt")
                return existing, True

            attempts = [
                item
                for item in self._attempts.values()
                if item.candidate_id == candidate_id and item.adapter == adapter
            ]
            latest = max(attempts, key=lambda item: item.attempt_number, default=None)
            if latest is not None and latest.state == DeliveryAttemptState.SUCCEEDED:
                raise ValueError("Candidate already has a successful dry-run delivery attempt")
            if latest is not None and latest.state == DeliveryAttemptState.PREPARED:
                raise ValueError("Candidate already has a Prepared dry-run delivery attempt")

            attempt_number = 1
            if latest is not None:
                if latest.state != DeliveryAttemptState.FAILED:
                    raise ValueError(
                        "A new delivery attempt requires the previous attempt to have Failed"
                    )
                if latest.completed_at is None:
                    raise ValueError("Failed delivery attempt is missing its completion timestamp")
                next_retry_at = latest.completed_at + timedelta(minutes=retry_minutes)
                if created_at < next_retry_at:
                    raise ValueError(f"Delivery retry is not due until {next_retry_at.isoformat()}")
                attempt_number = latest.attempt_number + 1

            prepared = DeliveryAttempt(
                id=f"{candidate.id}:{adapter}:{attempt_number}",
                candidate_id=candidate.id,
                source_id=candidate.source_id,
                adapter=adapter,
                mode=DeliveryMode.DRY_RUN,
                idempotency_key=idempotency_key,
                attempt_number=attempt_number,
                state=DeliveryAttemptState.PREPARED,
                created_at=created_at,
                claim_owner=claim_owner,
            )
            self._attempts[prepared.id] = prepared
            self._attempt_ids.append(prepared.id)
            self._idempotency[idempotency_key] = prepared.id
            return prepared, False

    def update_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        with self._lock:
            if attempt.id not in self._attempts:
                raise ValueError(f"Unknown delivery attempt: {attempt.id}")
            self._attempts[attempt.id] = attempt
            return attempt

    def get_delivery_attempt(self, attempt_id: str) -> DeliveryAttempt | None:
        with self._lock:
            return self._attempts.get(attempt_id)

    def list_delivery_attempts(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryAttempt]:
        with self._lock:
            indexed = [
                (index, self._attempts[attempt_id])
                for index, attempt_id in enumerate(self._attempt_ids)
                if (candidate_id is None or self._attempts[attempt_id].candidate_id == candidate_id)
                and (source_id is None or self._attempts[attempt_id].source_id == source_id)
            ]
            indexed.sort(
                key=lambda pair: (pair[1].created_at, pair[1].attempt_number, pair[0]),
                reverse=True,
            )
            return [item for _, item in indexed[:limit]]

    def reconcile_prepared_delivery_attempt(
        self,
        attempt_id: str,
        outcome: DeliveryAttemptState,
        *,
        reconciled_at: datetime,
        note: str,
        reconciled_by: str | None = None,
    ) -> DeliveryAttempt:
        if outcome not in {DeliveryAttemptState.SUCCEEDED, DeliveryAttemptState.FAILED}:
            raise ValueError("Prepared attempts can reconcile only to Succeeded or Failed")
        with self._lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise KeyError(f"Unknown delivery attempt: {attempt_id}")
            if attempt.state != DeliveryAttemptState.PREPARED:
                raise ValueError("Only Prepared delivery attempts can be reconciled")
            reconciled = attempt.model_copy(
                update={
                    "state": outcome,
                    "completed_at": reconciled_at,
                    "reconciled_at": reconciled_at,
                    "reconciled_by": reconciled_by,
                    "reconciliation_note": note,
                    "result_summary": (
                        "Prepared attempt reconciled as successful after explicit review."
                        if outcome == DeliveryAttemptState.SUCCEEDED
                        else None
                    ),
                    "error": (
                        "Prepared attempt reconciled as failed after explicit review."
                        if outcome == DeliveryAttemptState.FAILED
                        else None
                    ),
                }
            )
            self._attempts[attempt_id] = reconciled
            return reconciled

    def promote_baseline(self, source_id: str, observation_id: str) -> Observation:
        with self._lock:
            observation = self._observations.get(observation_id)
            if observation is None or observation.source_id != source_id:
                raise ValueError("Observation does not belong to this source")
            if not observation.available or observation.profile is None:
                raise ValueError("Unavailable observations cannot become a baseline")
            self._baseline_ids[source_id] = observation_id
            marked = self._with_baseline_marker(observation)
            if marked is None:
                raise ValueError("Unable to promote baseline")
            return marked
