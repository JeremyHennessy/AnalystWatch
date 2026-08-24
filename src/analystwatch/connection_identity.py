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

MAX_OAUTH_ACCESS_TOKEN_CHARS = 32_768


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
    """Resolve account identity for the existing environment-backed credential."""
    provider = ConnectionProvider(provider)
    headers = _authorization_headers(provider, environment_variable)
    return _inspect_connection_identity(
        provider,
        headers,
        timeout_seconds=timeout_seconds,
        client=client,
    )


def inspect_connection_identity_with_access_token(
    provider: ConnectionProvider | str,
    access_token: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> ConnectionAccountIdentity:
    """Resolve provider account identity from one in-memory OAuth access token.

    The token is never persisted or copied into an environment variable by this helper.
    """
    provider = ConnectionProvider(provider)
    if (
        not isinstance(access_token, str)
        or not access_token
        or access_token != access_token.strip()
        or len(access_token) > MAX_OAUTH_ACCESS_TOKEN_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in access_token)
    ):
        raise ConnectionDiscoveryError(
            provider,
            "invalid_credential",
            "OAuth access token was not usable for account identity verification.",
        )
    return _inspect_connection_identity(
        provider,
        {"Authorization": f"Bearer {access_token}"},
        timeout_seconds=timeout_seconds,
        client=client,
    )


def _inspect_connection_identity(
    provider: ConnectionProvider,
    headers: dict[str, str],
    *,
    timeout_seconds: float,
    client: httpx.Client | None,
) -> ConnectionAccountIdentity:
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
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
