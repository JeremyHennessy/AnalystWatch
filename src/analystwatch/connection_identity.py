from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from .connection_discovery import (
    DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    GOOGLE_DRIVE_ROOT,
    GRAPH_ROOT,
    ConnectionDiscoveryError,
    ConnectionProvider,
    _active_client,
    _authorization_headers,
    _request_json,
)


class ConnectionAccountIdentity(BaseModel):
    provider: ConnectionProvider
    subject_id: str = Field(min_length=1, max_length=512)
    display_name: str | None = Field(default=None, max_length=512)
    email: str | None = Field(default=None, max_length=512)


def _provider_text(
    provider: ConnectionProvider,
    payload: dict[str, object],
    field: str,
    *,
    required: bool = False,
) -> str | None:
    value = payload.get(field)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConnectionDiscoveryError(
            provider,
            "invalid_identity",
            f"{provider.value.title()} account identity did not contain a usable {field}.",
        )
    if len(value) > 512:
        raise ConnectionDiscoveryError(
            provider,
            "invalid_identity",
            f"{provider.value.title()} account identity contained an oversized {field}.",
        )
    return value


def inspect_connection_identity(
    provider: ConnectionProvider | str,
    environment_variable: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> ConnectionAccountIdentity:
    """Resolve bounded account identity for the configured delegated provider credential.

    This performs a provider request but never returns the credential reference or value. Identity
    verification is intentionally separate from the existing reachability check so a missing
    identity-specific provider scope cannot silently redefine connector reachability.
    """
    provider = ConnectionProvider(provider)
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _authorization_headers(provider, environment_variable)
        if provider == ConnectionProvider.MICROSOFT:
            payload, _ = _request_json(
                provider,
                active_client,
                f"{GRAPH_ROOT}/me",
                headers,
                params={"$select": "id,displayName,mail,userPrincipalName"},
            )
            email = _provider_text(provider, payload, "mail")
            if email is None:
                email = _provider_text(provider, payload, "userPrincipalName")
            return ConnectionAccountIdentity(
                provider=provider,
                subject_id=_provider_text(provider, payload, "id", required=True),  # type: ignore[arg-type]
                display_name=_provider_text(provider, payload, "displayName"),
                email=email,
            )

        payload, _ = _request_json(
            provider,
            active_client,
            f"{GOOGLE_DRIVE_ROOT}/about",
            headers,
            params={"fields": "user(displayName,emailAddress,permissionId)"},
        )
        user = payload.get("user")
        if not isinstance(user, dict):
            raise ConnectionDiscoveryError(
                provider,
                "invalid_identity",
                "Google account identity did not contain a usable user object.",
            )
        return ConnectionAccountIdentity(
            provider=provider,
            subject_id=_provider_text(provider, user, "permissionId", required=True),  # type: ignore[arg-type]
            display_name=_provider_text(provider, user, "displayName"),
            email=_provider_text(provider, user, "emailAddress"),
        )
    finally:
        if owns_client:
            active_client.close()
