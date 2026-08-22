from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from .models import (
    DeliveryAttempt,
    DeliveryAttemptState,
    DeliveryMode,
    NotificationCandidate,
    Observation,
    SourceDefinition,
)


@dataclass(frozen=True)
class TeamsWorkflowDestination:
    webhook_url: str
    base_url: str

    def __post_init__(self) -> None:
        if not self.webhook_url or self.webhook_url != self.webhook_url.strip():
            raise ValueError("webhook_url must be non-empty and trimmed")
        if not self.base_url or self.base_url != self.base_url.strip():
            raise ValueError("base_url must be non-empty and trimmed")


class DeliveryStorage(Protocol):
    def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None: ...
    def get_source(self, source_id: str) -> SourceDefinition | None: ...
    def get_observation(self, observation_id: str) -> Observation | None: ...
    def claim_delivery_attempt(
        self,
        candidate_id: str,
        idempotency_key: str,
        adapter: str,
        *,
        created_at,
        retry_minutes: int,
        claim_owner: str | None = None,
    ) -> tuple[DeliveryAttempt, bool]: ...
    def update_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt: ...


def _fact(title: str, value: str) -> dict[str, str]:
    return {"title": title, "value": value}


def _teams_payload(
    source: SourceDefinition,
    observation: Observation,
    candidate: NotificationCandidate,
    destination: TeamsWorkflowDestination,
) -> dict[str, object]:
    detail_url = f"{destination.base_url.rstrip('/')}/sources/{source.id}"
    important = [finding.description for finding in observation.findings[:5]]
    findings_text = "\n".join(f"• {item}" for item in important)
    if not findings_text:
        findings_text = "No detailed findings were recorded for this observation."

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"AnalystWatch · {candidate.current_health.value}",
                "weight": "Bolder",
                "size": "Large",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"{source.name} · {candidate.transition.value}",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    _fact("Workspace", source.workspace_id),
                    _fact("Severity", candidate.current_health.value),
                    _fact("Observed", observation.observed_at.isoformat()),
                ],
            },
            {
                "type": "TextBlock",
                "text": candidate.reason,
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "Important findings",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "TextBlock",
                "text": findings_text,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Open source detail",
                "url": detail_url,
            }
        ],
    }
    return {
        "type": "message",
        "summary": f"AnalystWatch {candidate.current_health.value}: {source.name}",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


class TeamsWorkflowAdapter:
    name = "teams-workflow"
    mode = DeliveryMode.LIVE

    def __init__(
        self,
        destination: TeamsWorkflowDestination,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.destination = destination
        self.client = client

    def deliver(
        self,
        candidate: NotificationCandidate,
        source: SourceDefinition,
        observation: Observation,
    ) -> None:
        payload = _teams_payload(source, observation, candidate, self.destination)
        owned_client = self.client is None
        client = self.client or httpx.Client(timeout=10.0)
        try:
            response = client.post(
                self.destination.webhook_url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
        finally:
            if owned_client:
                client.close()
        if response.is_error:
            raise TeamsWorkflowRejectedError(response.status_code)


class TeamsWorkflowRejectedError(RuntimeError):
    """Definitive Workflows webhook rejection."""

    def __init__(self, status_code: int):
        super().__init__(f"Teams Workflows webhook rejected message with HTTP {status_code}")
        self.status_code = status_code


def deliver_teams_candidate(
    storage: DeliveryStorage,
    candidate_id: str,
    idempotency_key: str,
    adapter: TeamsWorkflowAdapter,
    *,
    created_at,
    claim_owner: str,
) -> DeliveryAttempt:
    if not idempotency_key or idempotency_key != idempotency_key.strip():
        raise ValueError("idempotency_key must be non-empty and trimmed")
    candidate = storage.get_notification_candidate(candidate_id)
    if candidate is None:
        raise KeyError(f"Unknown notification candidate: {candidate_id}")
    source = storage.get_source(candidate.source_id)
    if source is None:
        raise KeyError(f"Unknown source: {candidate.source_id}")
    observation = storage.get_observation(candidate.observation_id)
    if observation is None or observation.source_id != source.id:
        raise KeyError(f"Unknown observation: {candidate.observation_id}")

    prepared, replayed = storage.claim_delivery_attempt(
        candidate_id,
        idempotency_key,
        adapter.name,
        created_at=created_at,
        retry_minutes=source.config.delivery_retry_minutes,
        claim_owner=claim_owner,
    )
    if prepared.mode != DeliveryMode.LIVE:
        prepared = storage.update_delivery_attempt(
            prepared.model_copy(update={"mode": DeliveryMode.LIVE})
        )
    if replayed:
        return prepared

    try:
        adapter.deliver(candidate, source, observation)
    except TeamsWorkflowRejectedError as exc:
        return storage.update_delivery_attempt(
            prepared.model_copy(
                update={
                    "state": DeliveryAttemptState.FAILED,
                    "completed_at": created_at,
                    "error": str(exc),
                }
            )
        )
    except httpx.RequestError:
        # The workflow may have accepted the request before the client observed a transport error.
        # Preserve Prepared so retry requires explicit reconciliation.
        return prepared

    return storage.update_delivery_attempt(
        prepared.model_copy(
            update={
                "state": DeliveryAttemptState.SUCCEEDED,
                "completed_at": created_at,
                "result_summary": "Microsoft Teams Workflows accepted the alert.",
            }
        )
    )
