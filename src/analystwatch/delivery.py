from __future__ import annotations

from dataclasses import dataclass

from .models import NotificationCandidate


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    summary: str | None = None
    error: str | None = None


class DryRunDeliveryAdapter:
    """Deterministic adapter that performs no network or external I/O."""

    name = "dry-run"

    def __init__(self, *, fail_with: str | None = None):
        self.fail_with = fail_with

    def deliver(self, candidate: NotificationCandidate) -> DeliveryResult:
        if self.fail_with is not None:
            return DeliveryResult(success=False, error=self.fail_with)
        return DeliveryResult(
            success=True,
            summary=(
                f"Dry run prepared {candidate.transition.value} candidate {candidate.id}; "
                "no external delivery was attempted."
            ),
        )
