from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import RunDecision, SourceDefinition
from .storage import Storage


def run_decision(
    storage: Storage,
    source: SourceDefinition,
    *,
    now: datetime | None = None,
) -> RunDecision:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    latest = storage.get_latest(source.id)
    if not source.enabled:
        return RunDecision(
            source_id=source.id,
            due=False,
            reason="Source is disabled.",
            last_checked_at=latest.observed_at if latest else None,
        )
    if latest is None:
        return RunDecision(source_id=source.id, due=True, reason="Source has never been checked.")

    next_check = latest.observed_at + timedelta(minutes=source.config.monitor_interval_minutes)
    due = current_time >= next_check
    return RunDecision(
        source_id=source.id,
        due=due,
        reason=(
            "Monitoring interval has elapsed."
            if due
            else "Monitoring interval has not elapsed."
        ),
        last_checked_at=latest.observed_at,
        next_check_at=next_check,
    )
