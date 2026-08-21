from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .models import (
    DeliveryAttempt,
    DeliveryAttemptState,
    NotificationCandidate,
    Observation,
    ObservationReview,
    SourceDefinition,
)
from .store import MonitoringStore

if TYPE_CHECKING:
    from .service import MonitorService

DEFAULT_WORKSPACE_ID = "local"
WORKSPACE_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"
_WORKSPACE_ID = re.compile(WORKSPACE_ID_PATTERN)


def validate_workspace_id(value: str) -> str:
    if not value or value != value.strip() or _WORKSPACE_ID.fullmatch(value) is None:
        raise ValueError(
            "workspace_id must be non-empty, trimmed, and contain only letters, "
            "numbers, '.', '_' or '-'"
        )
    return value


class WorkspaceStore:
    """Workspace-bound view over an existing monitoring store.

    Core v0.10 intentionally does not change SQLite keys. Source IDs therefore
    remain globally unique in the underlying store; this wrapper adds an
    ownership boundary, not multi-tenant persistence.
    """

    def __init__(self, delegate: MonitoringStore, workspace_id: str = DEFAULT_WORKSPACE_ID):
        self.delegate = delegate
        self.workspace_id = validate_workspace_id(workspace_id)

    @property
    def path(self) -> Path | None:
        return getattr(self.delegate, "path", None)

    def initialize(self) -> None:
        self.delegate.initialize()

    def _owns_source(self, source: SourceDefinition | None) -> bool:
        return source is not None and source.workspace_id == self.workspace_id

    def _require_source(self, source_id: str) -> SourceDefinition:
        source = self.delegate.get_source(source_id)
        if not self._owns_source(source):
            raise KeyError(f"Unknown source in workspace {self.workspace_id}: {source_id}")
        return source

    def upsert_source(self, source: SourceDefinition) -> None:
        if source.workspace_id != self.workspace_id:
            raise ValueError(
                f"Source workspace {source.workspace_id!r} does not match bound workspace "
                f"{self.workspace_id!r}"
            )
        existing = self.delegate.get_source(source.id)
        if existing is not None and existing.workspace_id != self.workspace_id:
            raise ValueError("Source ID is already owned by another workspace")
        self.delegate.upsert_source(source)

    def get_source(self, source_id: str) -> SourceDefinition | None:
        source = self.delegate.get_source(source_id)
        return source if self._owns_source(source) else None

    def list_sources(self) -> list[SourceDefinition]:
        return [source for source in self.delegate.list_sources() if self._owns_source(source)]

    def save_observation(
        self,
        observation: Observation,
        *,
        set_baseline: bool = False,
        notification_candidate: NotificationCandidate | None = None,
    ) -> None:
        self._require_source(observation.source_id)
        if notification_candidate is not None:
            if notification_candidate.source_id != observation.source_id:
                raise ValueError("Notification candidate must belong to the observation source")
            self._require_source(notification_candidate.source_id)
        self.delegate.save_observation(
            observation,
            set_baseline=set_baseline,
            notification_candidate=notification_candidate,
        )

    def get_observation(self, observation_id: str) -> Observation | None:
        observation = self.delegate.get_observation(observation_id)
        if observation is None or self.get_source(observation.source_id) is None:
            return None
        return observation

    def get_baseline(self, source_id: str) -> Observation | None:
        if self.get_source(source_id) is None:
            return None
        return self.delegate.get_baseline(source_id)

    def get_latest(self, source_id: str) -> Observation | None:
        if self.get_source(source_id) is None:
            return None
        return self.delegate.get_latest(source_id)

    def get_last_successful(self, source_id: str) -> Observation | None:
        if self.get_source(source_id) is None:
            return None
        return self.delegate.get_last_successful(source_id)

    def list_reference_observations(
        self,
        source_id: str,
        limit: int = 5,
    ) -> list[Observation]:
        if self.get_source(source_id) is None:
            return []
        return self.delegate.list_reference_observations(source_id, limit=limit)

    def list_observations(self, source_id: str, limit: int = 20) -> list[Observation]:
        if self.get_source(source_id) is None:
            return []
        return self.delegate.list_observations(source_id, limit=limit)

    def save_review(self, review: ObservationReview) -> ObservationReview:
        self._require_source(review.source_id)
        observation = self.get_observation(review.observation_id)
        if observation is None or observation.source_id != review.source_id:
            raise ValueError("Observation review does not belong to this workspace/source")
        return self.delegate.save_review(review)

    def get_review(self, observation_id: str) -> ObservationReview | None:
        if self.get_observation(observation_id) is None:
            return None
        return self.delegate.get_review(observation_id)

    def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None:
        candidate = self.delegate.get_notification_candidate(candidate_id)
        if candidate is None or self.get_source(candidate.source_id) is None:
            return None
        return candidate

    def list_notification_candidates(
        self,
        source_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[NotificationCandidate]:
        if source_id is not None:
            if self.get_source(source_id) is None:
                return []
            return self.delegate.list_notification_candidates(source_id, limit=limit)
        return [
            candidate
            for candidate in self.delegate.list_notification_candidates(limit=limit)
            if self.get_source(candidate.source_id) is not None
        ]

    def update_notification_candidate(
        self,
        candidate: NotificationCandidate,
    ) -> NotificationCandidate:
        self._require_source(candidate.source_id)
        existing = self.get_notification_candidate(candidate.id)
        if existing is None:
            raise ValueError(f"Unknown notification candidate: {candidate.id}")
        return self.delegate.update_notification_candidate(candidate)

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
        if self.get_notification_candidate(candidate_id) is None:
            raise KeyError(
                f"Unknown notification candidate in workspace {self.workspace_id}: {candidate_id}"
            )
        return self.delegate.claim_delivery_attempt(
            candidate_id,
            idempotency_key,
            adapter,
            created_at=created_at,
            retry_minutes=retry_minutes,
            claim_owner=claim_owner,
        )

    def update_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        self._require_source(attempt.source_id)
        existing = self.get_delivery_attempt(attempt.id)
        if existing is None:
            raise ValueError(f"Unknown delivery attempt: {attempt.id}")
        return self.delegate.update_delivery_attempt(attempt)

    def get_delivery_attempt(self, attempt_id: str) -> DeliveryAttempt | None:
        attempt = self.delegate.get_delivery_attempt(attempt_id)
        if attempt is None or self.get_source(attempt.source_id) is None:
            return None
        return attempt

    def list_delivery_attempts(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryAttempt]:
        if source_id is not None and self.get_source(source_id) is None:
            return []
        if candidate_id is not None and self.get_notification_candidate(candidate_id) is None:
            return []
        return [
            attempt
            for attempt in self.delegate.list_delivery_attempts(
                candidate_id=candidate_id,
                source_id=source_id,
                limit=limit,
            )
            if self.get_source(attempt.source_id) is not None
        ]

    def reconcile_prepared_delivery_attempt(
        self,
        attempt_id: str,
        outcome: DeliveryAttemptState,
        *,
        reconciled_at: datetime,
        note: str,
        reconciled_by: str | None = None,
    ) -> DeliveryAttempt:
        if self.get_delivery_attempt(attempt_id) is None:
            raise KeyError(
                f"Unknown delivery attempt in workspace {self.workspace_id}: {attempt_id}"
            )
        return self.delegate.reconcile_prepared_delivery_attempt(
            attempt_id,
            outcome,
            reconciled_at=reconciled_at,
            note=note,
            reconciled_by=reconciled_by,
        )

    def promote_baseline(self, source_id: str, observation_id: str) -> Observation:
        self._require_source(source_id)
        observation = self.get_observation(observation_id)
        if observation is None or observation.source_id != source_id:
            raise ValueError("Observation does not belong to this workspace/source")
        return self.delegate.promote_baseline(source_id, observation_id)


def create_workspace_service(
    storage: MonitoringStore,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    execution_owner: str | None = None,
) -> MonitorService:
    """Create a MonitorService bound to one workspace without changing its core logic."""
    from .service import MonitorService

    return MonitorService(
        WorkspaceStore(storage, workspace_id),
        execution_owner=execution_owner,
    )
