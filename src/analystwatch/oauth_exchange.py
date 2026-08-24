from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from .connection_discovery import DEFAULT_DISCOVERY_TIMEOUT_SECONDS, ConnectionProvider
from .oauth_provider_config import OAuthProviderRuntimeConfig

MAX_AUTHORIZATION_CODE_CHARS = 8192
MAX_OAUTH_TOKEN_CHARS = 32_768
MAX_SCOPE_RESPONSE_CHARS = 16_384
MAX_ACCESS_TOKEN_LIFETIME_SECONDS = 7 * 24 * 60 * 60


class OAuthTokenExchangeError(RuntimeError):
    """Bounded token-exchange error that never includes codes, tokens or provider bodies."""


@dataclass(frozen=True, repr=False)
class OAuthTokenSet:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    scopes: tuple[str, ...] = ()
    access_token_expires_at: datetime | None = None

    def __repr__(self) -> str:
        return (
            "OAuthTokenSet(access_token=<redacted>, refresh_token=<redacted>, "
            f"scopes={self.scopes!r}, access_token_expires_at={self.access_token_expires_at!r})"
        )


def exchange_authorization_code(
    config: OAuthProviderRuntimeConfig,
    *,
    code: str,
    code_verifier: str,
    now: datetime,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> OAuthTokenSet:
    _validate_now(now)
    code = validate_authorization_code(code)
    code_verifier = _required_secret(code_verifier, "PKCE verifier", 256)
    request_data = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": code,
        "redirect_uri": config.public.redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    if config.public.provider == ConnectionProvider.MICROSOFT:
        request_data["scope"] = " ".join(config.public.scopes)

    active_client = client or httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=False,
    )
    owns_client = client is None
    try:
        try:
            response = active_client.post(config.public.token_endpoint, data=request_data)
        except httpx.HTTPError as exc:
            raise OAuthTokenExchangeError(
                f"{config.public.provider.value.title()} token exchange request failed."
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise OAuthTokenExchangeError(
                f"{config.public.provider.value.title()} token exchange was rejected "
                f"with HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthTokenExchangeError(
                f"{config.public.provider.value.title()} token exchange returned unusable JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise OAuthTokenExchangeError(
                f"{config.public.provider.value.title()} token exchange returned an invalid shape."
            )
        return _parse_token_payload(config.public.provider, payload, now=now)
    finally:
        if owns_client:
            active_client.close()


def validate_authorization_code(value: str) -> str:
    return _required_secret(value, "authorization code", MAX_AUTHORIZATION_CODE_CHARS)


def _parse_token_payload(
    provider: ConnectionProvider,
    payload: dict[str, object],
    *,
    now: datetime,
) -> OAuthTokenSet:
    access_token = _payload_secret(provider, payload, "access_token", required=True)
    refresh_token = _payload_secret(provider, payload, "refresh_token", required=False)
    token_type = payload.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise OAuthTokenExchangeError(
            f"{provider.value.title()} token exchange did not return a Bearer token."
        )
    expires_at = _parse_expiry(provider, payload.get("expires_in"), now=now)
    scopes = _parse_scopes(provider, payload.get("scope"))
    return OAuthTokenSet(
        access_token=access_token,
        refresh_token=refresh_token,
        scopes=scopes,
        access_token_expires_at=expires_at,
    )


def _payload_secret(
    provider: ConnectionProvider,
    payload: dict[str, object],
    field_name: str,
    *,
    required: bool,
) -> str | None:
    value = payload.get(field_name)
    if value is None and not required:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_OAUTH_TOKEN_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise OAuthTokenExchangeError(
            f"{provider.value.title()} token exchange returned an invalid {field_name}."
        )
    return value


def _parse_expiry(
    provider: ConnectionProvider,
    value: object,
    *,
    now: datetime,
) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool):
        valid = False
        seconds = 0
    elif isinstance(value, int):
        seconds = value
        valid = True
    elif isinstance(value, str) and value.isdigit():
        seconds = int(value)
        valid = True
    else:
        valid = False
        seconds = 0
    if not valid or seconds < 1 or seconds > MAX_ACCESS_TOKEN_LIFETIME_SECONDS:
        raise OAuthTokenExchangeError(
            f"{provider.value.title()} token exchange returned an invalid expires_in."
        )
    return now + timedelta(seconds=seconds)


def _parse_scopes(provider: ConnectionProvider, value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, str) or len(value) > MAX_SCOPE_RESPONSE_CHARS:
        raise OAuthTokenExchangeError(
            f"{provider.value.title()} token exchange returned invalid scope evidence."
        )
    scopes = value.split()
    if not scopes:
        return ()
    for scope in scopes:
        invalid = len(scope) > 512 or any(
            ord(character) < 33 or ord(character) == 127 for character in scope
        )
        if invalid:
            raise OAuthTokenExchangeError(
                f"{provider.value.title()} token exchange returned invalid scope evidence."
            )
    return tuple(sorted(set(scopes)))


def _required_secret(value: str, label: str, max_chars: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_chars
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise OAuthTokenExchangeError(f"OAuth {label} is invalid.")
    return value


def _validate_now(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("OAuth token exchange time must be timezone-aware")
