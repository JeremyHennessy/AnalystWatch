from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .models import (
    DeliveryAttempt,
    DeliveryAttemptState,
    NotificationCandidate,
    Observation,
    ObservationReview,
    SourceDefinition,
)


@runtime_checkable
class MonitoringStore(Protocol):
    """Persistence contract used by monitoring/service/read surfaces."""

    def initialize(self) -> None: ...

    def upsert_source(self, source: SourceDefinition) -> None: ...

    def get_source(self, source_id: str) -> SourceDefinition | None: ...

    def list_sources(self) -> list[SourceDefinition]: ...

    def save_observation(
        self,
        observation: Observation,
        *,
        set_baseline: bool = False,
        notification_candidate: NotificationCandidate | None = None,
    ) -> None: ...

    def get_observation(self, observation_id: str) -> Observation | None: ...

    def get_baseline(self, source_id: str) -> Observation | None: ...

    def get_latest(self, source_id: str) -> Observation | None: ...

    def get_last_successful(self, source_id: str) -> Observation | None: ...

    def list_reference_observations(
        self,
        source_id: str,
        limit: int = 5,
    ) -> list[Observation]: ...

    def list_observations(self, source_id: str, limit: int = 20) -> list[Observation]: ...

    def save_review(self, review: ObservationReview) -> ObservationReview: ...

    def get_review(self, observation_id: str) -> ObservationReview | None: ...

    def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None: ...

    def list_notification_candidates(
        self,
        source_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[NotificationCandidate]: ...

    def update_notification_candidate(
        self,
        candidate: NotificationCandidate,
    ) -> NotificationCandidate: ...

    def claim_delivery_attempt(
        self,
        candidate_id: str,
        idempotency_key: str,
        adapter: str,
        *,
        created_at: datetime,
        retry_minutes: int,
        claim_owner: str | None = None,
    ) -> tuple[DeliveryAttempt, bool]: ...

    def update_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt: ...

    def get_delivery_attempt(self, attempt_id: str) -> DeliveryAttempt | None: ...

    def list_delivery_attempts(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryAttempt]: ...

    def reconcile_prepared_delivery_attempt(
        self,
        attempt_id: str,
        outcome: DeliveryAttemptState,
        *,
        reconciled_at: datetime,
        note: str,
        reconciled_by: str | None = None,
    ) -> DeliveryAttempt: ...

    def promote_baseline(self, source_id: str, observation_id: str) -> Observation: ...