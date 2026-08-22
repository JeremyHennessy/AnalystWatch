from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .models import (
    DeliveryAttemptState,
    DeliveryMode,
    HealthStatus,
    IncidentTransition,
)
from .store import MonitoringStore

DEFAULT_STALE_AFTER_MINUTES = 30
DEFAULT_SCAN_LIMIT = 5000
DEFAULT_QUEUE_LIMIT = 100


class DeliveryReconciliationQueueItem(BaseModel):
    attempt_id: str
    candidate_id: str
    source_id: str
    source_name: str
    adapter: str
    mode: DeliveryMode
    created_at: datetime
    age_minutes: int = Field(ge=0)
    stale: bool
    transition: IncidentTransition | None = None
    current_health: HealthStatus | None = None


class DeliveryReconciliationQueue(BaseModel):
    generated_at: datetime
    stale_after_minutes: int = Field(gt=0)
    scan_limit: int = Field(gt=0)
    scan_limit_reached: bool
    prepared_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)
    items: list[DeliveryReconciliationQueueItem] = Field(default_factory=list)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def build_delivery_reconciliation_queue(
    storage: MonitoringStore,
    *,
    now: datetime | None = None,
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
    limit: int = DEFAULT_QUEUE_LIMIT,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
) -> DeliveryReconciliationQueue:
    if stale_after_minutes <= 0:
        raise ValueError("stale_after_minutes must be greater than zero")
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    if scan_limit <= 0:
        raise ValueError("scan_limit must be greater than zero")

    current = _aware(now or datetime.now(timezone.utc))
    scanned = storage.list_delivery_attempts(limit=scan_limit)
    prepared = [item for item in scanned if item.state == DeliveryAttemptState.PREPARED]
    prepared.sort(key=lambda item: _aware(item.created_at))

    queue_items: list[DeliveryReconciliationQueueItem] = []
    stale_count = 0
    stale_seconds = stale_after_minutes * 60
    for attempt in prepared:
        age_seconds = max(0.0, (current - _aware(attempt.created_at)).total_seconds())
        stale = age_seconds >= stale_seconds
        if stale:
            stale_count += 1
        if len(queue_items) >= limit:
            continue
        candidate = storage.get_notification_candidate(attempt.candidate_id)
        source = storage.get_source(attempt.source_id)
        queue_items.append(
            DeliveryReconciliationQueueItem(
                attempt_id=attempt.id,
                candidate_id=attempt.candidate_id,
                source_id=attempt.source_id,
                source_name=source.name if source is not None else attempt.source_id,
                adapter=attempt.adapter,
                mode=attempt.mode,
                created_at=attempt.created_at,
                age_minutes=int(age_seconds // 60),
                stale=stale,
                transition=candidate.transition if candidate is not None else None,
                current_health=candidate.current_health if candidate is not None else None,
            )
        )

    return DeliveryReconciliationQueue(
        generated_at=current,
        stale_after_minutes=stale_after_minutes,
        scan_limit=scan_limit,
        scan_limit_reached=len(scanned) == scan_limit,
        prepared_count=len(prepared),
        stale_count=stale_count,
        items=queue_items,
    )
