from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from .connection_discovery import ConnectionProvider

PUBLIC_BASE_URL_ENV = "ANALYSTWATCH_PUBLIC_BASE_URL"

MICROSOFT_CLIENT_ID_ENV = "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID"
MICROSOFT_CLIENT_SECRET_ENV = "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET"
GOOGLE_CLIENT_ID_ENV = "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID"
GOOGLE_CLIENT_SECRET_ENV = "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET"

MICROSOFT_AUTHORIZATION_ENDPOINT = (
    "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
)
MICROSOFT_TOKEN_ENDPOINT = "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

MICROSOFT_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "User.Read",
    "Files.Read.All",
)
GOOGLE_SCOPES = (
    "openid",
    "profile",
    "email",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
)

CALLBACK_PATHS = {
    ConnectionProvider.MICROSOFT: "/api/oauth/microsoft/callback",
    ConnectionProvider.GOOGLE: "/api/oauth/google/callback",
}

MAX_CLIENT_ID_CHARS = 512
MAX_CLIENT_SECRET_CHARS = 4096
MAX_PUBLIC_BASE_URL_CHARS = 2048


class OAuthProviderConfigurationError(ValueError):
    """Bounded OAuth configuration error that never includes secret values."""


class OAuthProviderPublicConfig(BaseModel):
    provider: ConnectionProvider
    authorization_endpoint: str
    token_endpoint: str
    redirect_uri: str
    scopes: tuple[str, ...]


class OAuthProviderRuntimeConfig:
    __slots__ = ("client_id", "public", "_client_secret")

    def __init__(
        self,
        *,
        public: OAuthProviderPublicConfig,
        client_id: str,
        client_secret: str,
    ) -> None:
        self.public = public
        self.client_id = client_id
        self._client_secret = client_secret

    @property
    def client_secret(self) -> str:
        return self._client_secret

    def __repr__(self) -> str:
        return (
            "OAuthProviderRuntimeConfig("
            f"provider={self.public.provider.value!r}, client_id={self.client_id!r}, "
            "client_secret=<redacted>)"
        )


def load_oauth_provider_config(
    provider: ConnectionProvider | str,
    environ: Mapping[str, str] | None = None,
) -> OAuthProviderRuntimeConfig:
    provider = ConnectionProvider(provider)
    environment = os.environ if environ is None else environ
    base_url = _validate_public_base_url(environment.get(PUBLIC_BASE_URL_ENV))

    if provider == ConnectionProvider.MICROSOFT:
        client_id = _required_runtime_value(
            environment.get(MICROSOFT_CLIENT_ID_ENV),
            "Microsoft OAuth client ID",
            MAX_CLIENT_ID_CHARS,
        )
        client_secret = _required_runtime_value(
            environment.get(MICROSOFT_CLIENT_SECRET_ENV),
            "Microsoft OAuth client secret",
            MAX_CLIENT_SECRET_CHARS,
        )
        authorization_endpoint = MICROSOFT_AUTHORIZATION_ENDPOINT
        token_endpoint = MICROSOFT_TOKEN_ENDPOINT
        scopes = MICROSOFT_SCOPES
    else:
        client_id = _required_runtime_value(
            environment.get(GOOGLE_CLIENT_ID_ENV),
            "Google OAuth client ID",
            MAX_CLIENT_ID_CHARS,
        )
        client_secret = _required_runtime_value(
            environment.get(GOOGLE_CLIENT_SECRET_ENV),
            "Google OAuth client secret",
            MAX_CLIENT_SECRET_CHARS,
        )
        authorization_endpoint = GOOGLE_AUTHORIZATION_ENDPOINT
        token_endpoint = GOOGLE_TOKEN_ENDPOINT
        scopes = GOOGLE_SCOPES

    redirect_uri = f"{base_url}{CALLBACK_PATHS[provider]}"
    return OAuthProviderRuntimeConfig(
        public=OAuthProviderPublicConfig(
            provider=provider,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            redirect_uri=redirect_uri,
            scopes=scopes,
        ),
        client_id=client_id,
        client_secret=client_secret,
    )


def _validate_public_base_url(value: str | None) -> str:
    if value is None or not value or value != value.strip():
        raise OAuthProviderConfigurationError("Public base URL is not configured")
    if len(value) > MAX_PUBLIC_BASE_URL_CHARS:
        raise OAuthProviderConfigurationError("Public base URL is too long")
    parts = urlsplit(value)
    if parts.username is not None or parts.password is not None:
        raise OAuthProviderConfigurationError("Public base URL must not contain user information")
    if parts.query or parts.fragment:
        raise OAuthProviderConfigurationError("Public base URL must not contain query or fragment")
    if parts.path not in {"", "/"}:
        raise OAuthProviderConfigurationError("Public base URL must not contain an application path")
    if not parts.hostname:
        raise OAuthProviderConfigurationError("Public base URL must contain a hostname")
    hostname = parts.hostname.lower()
    if parts.scheme == "https":
        pass
    elif parts.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"}:
        pass
    else:
        raise OAuthProviderConfigurationError(
            "Public base URL must use HTTPS except for loopback local development"
        )
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc, "", "", "")).rstrip("/")


def _required_runtime_value(value: str | None, label: str, max_chars: int) -> str:
    if value is None or not value or value != value.strip():
        raise OAuthProviderConfigurationError(f"{label} is not configured")
    if len(value) > max_chars:
        raise OAuthProviderConfigurationError(f"{label} is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise OAuthProviderConfigurationError(f"{label} contains invalid characters")
    return value
