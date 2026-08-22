from __future__ import annotations

from dataclasses import dataclass
from html import escape
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

RESEND_EMAILS_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailDestination:
    from_address: str
    to_addresses: tuple[str, ...]
    base_url: str

    def __post_init__(self) -> None:
        if not self.from_address or self.from_address != self.from_address.strip():
            raise ValueError("from_address must be non-empty and trimmed")
        if not self.to_addresses or any(
            not item or item != item.strip() for item in self.to_addresses
        ):
            raise ValueError("to_addresses must contain trimmed non-empty addresses")
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


def _email_subject(source: SourceDefinition, candidate: NotificationCandidate) -> str:
    return (
        f"AnalystWatch {candidate.current_health.value}: "
        f"{source.name} {candidate.transition.value}"
    )


def _email_html(
    source: SourceDefinition,
    observation: Observation,
    candidate: NotificationCandidate,
    destination: EmailDestination,
) -> str:
    detail_url = f"{destination.base_url.rstrip('/')}/sources/{source.id}"
    finding_rows = "".join(
        "<li>"
        f"<strong>{escape(item.severity.value)}</strong> — {escape(item.description)}"
        + (f"<br>Impact: {escape(item.likely_impact)}" if item.likely_impact else "")
        + (
            f"<br>Suggested investigation: {escape(item.suggested_investigation)}"
            if item.suggested_investigation
            else ""
        )
        + "</li>"
        for item in observation.findings[:10]
    )
    if not finding_rows:
        finding_rows = "<li>No detailed findings were recorded for this observation.</li>"
    return (
        "<h2>AnalystWatch reliability alert</h2>"
        f"<p><strong>Source:</strong> {escape(source.name)}<br>"
        f"<strong>Workspace:</strong> {escape(source.workspace_id)}<br>"
        f"<strong>Transition:</strong> {escape(candidate.transition.value)}<br>"
        f"<strong>Severity:</strong> {escape(candidate.current_health.value)}<br>"
        f"<strong>Observed:</strong> {escape(observation.observed_at.isoformat())}</p>"
        f"<p>{escape(candidate.reason)}</p>"
        "<h3>Important findings</h3>"
        f"<ul>{finding_rows}</ul>"
        f'<p><a href="{escape(detail_url)}">Open source detail</a></p>'
    )


class ResendEmailAdapter:
    name = "resend-email"
    mode = DeliveryMode.LIVE

    def __init__(
        self,
        api_key: str,
        destination: EmailDestination,
        *,
        client: httpx.Client | None = None,
        endpoint: str = RESEND_EMAILS_URL,
    ) -> None:
        if not api_key or api_key != api_key.strip():
            raise ValueError("Resend API key must be non-empty and trimmed")
        self._api_key = api_key
        self.destination = destination
        self.client = client
        self.endpoint = endpoint

    def deliver(
        self,
        candidate: NotificationCandidate,
        source: SourceDefinition,
        observation: Observation,
        *,
        idempotency_key: str,
    ) -> str:
        payload = {
            "from": self.destination.from_address,
            "to": list(self.destination.to_addresses),
            "subject": _email_subject(source, candidate),
            "html": _email_html(source, observation, candidate, self.destination),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        owned_client = self.client is None
        client = self.client or httpx.Client(timeout=10.0)
        try:
            response = client.post(self.endpoint, headers=headers, json=payload)
        finally:
            if owned_client:
                client.close()
        if response.is_error:
            raise ResendRejectedError(response.status_code)
        response_payload = response.json()
        email_id = response_payload.get("id")
        if not isinstance(email_id, str) or not email_id:
            raise ResendRejectedError(response.status_code, "missing email id")
        return email_id


class ResendRejectedError(RuntimeError):
    """Definitive provider rejection; unlike transport uncertainty, it may be retried by policy."""

    def __init__(self, status_code: int, detail: str | None = None):
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"Resend rejected email with HTTP {status_code}{suffix}")
        self.status_code = status_code


def deliver_email_candidate(
    storage: DeliveryStorage,
    candidate_id: str,
    idempotency_key: str,
    adapter: ResendEmailAdapter,
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
        email_id = adapter.deliver(
            candidate,
            source,
            observation,
            idempotency_key=idempotency_key,
        )
    except ResendRejectedError as exc:
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
        # A transport failure may occur after the provider accepted the message.
        # Preserve Prepared so an operator must reconcile before any retry.
        return prepared

    return storage.update_delivery_attempt(
        prepared.model_copy(
            update={
                "state": DeliveryAttemptState.SUCCEEDED,
                "completed_at": created_at,
                "result_summary": f"Resend accepted email {email_id}.",
            }
        )
    )
