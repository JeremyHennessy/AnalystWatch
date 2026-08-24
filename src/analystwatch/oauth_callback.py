from __future__ import annotations

from datetime import datetime

import httpx

from .connection_discovery import ConnectionDiscoveryError, ConnectionProvider
from .connection_identity import inspect_connection_identity_with_access_token
from .credential_crypto import CredentialKeyring
from .credential_store import CredentialStore, ProviderCredentialRecord, seal_provider_credential
from .oauth_authorization import OAuthAuthorizationError, OAuthAuthorizationTransaction
from .oauth_authorization_store import OAuthAuthorizationStore
from .oauth_exchange import (
    OAuthTokenExchangeError,
    exchange_authorization_code,
    validate_authorization_code,
)
from .oauth_provider_config import OAuthProviderRuntimeConfig
from .workspace import validate_workspace_id


class OAuthCallbackError(RuntimeError):
    """Bounded callback completion error that never includes codes, tokens or provider bodies."""


def complete_oauth_authorization(
    authorization_store: OAuthAuthorizationStore,
    credential_store: CredentialStore,
    keyring: CredentialKeyring,
    config: OAuthProviderRuntimeConfig,
    *,
    provider: ConnectionProvider | str,
    workspace_id: str,
    state: str,
    code: str,
    now: datetime,
    client: httpx.Client | None = None,
) -> ProviderCredentialRecord:
    provider = ConnectionProvider(provider)
    workspace_id = validate_workspace_id(workspace_id)
    if config.public.provider != provider:
        raise OAuthCallbackError("OAuth callback provider configuration did not match the route.")
    code = validate_authorization_code(code)
    try:
        consumed = authorization_store.consume(
            state,
            keyring,
            now=now,
            expected_workspace_id=workspace_id,
            expected_provider=provider,
        )
    except OAuthAuthorizationError as exc:
        raise OAuthCallbackError(str(exc)) from exc

    transaction = consumed.transaction
    if credential_store.get(workspace_id, transaction.credential_id) is not None:
        raise OAuthCallbackError(
            "Credential ID is already connected; use the explicit reconnect/account-switch flow."
        )

    try:
        tokens = exchange_authorization_code(
            config,
            code=code,
            code_verifier=consumed.pkce_verifier,
            now=now,
            client=client,
        )
    except OAuthTokenExchangeError as exc:
        raise OAuthCallbackError(str(exc)) from exc

    try:
        identity = inspect_connection_identity_with_access_token(
            provider,
            tokens.access_token,
            client=client,
        )
    except ConnectionDiscoveryError as exc:
        raise OAuthCallbackError(
            f"{provider.value.title()} account identity could not be verified after token exchange."
        ) from exc

    try:
        record = seal_provider_credential(
            keyring,
            credential_id=transaction.credential_id,
            workspace_id=workspace_id,
            provider=provider,
            subject_id=identity.subject_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            scopes=tokens.scopes,
            access_token_expires_at=tokens.access_token_expires_at,
            display_name=identity.display_name,
            email=identity.email,
            now=now,
        )
        return credential_store.upsert(record)
    except ValueError as exc:
        raise OAuthCallbackError(
            "Encrypted provider credential could not be persisted safely."
        ) from exc


def consume_oauth_authorization_denial(
    authorization_store: OAuthAuthorizationStore,
    keyring: CredentialKeyring,
    *,
    provider: ConnectionProvider | str,
    workspace_id: str,
    state: str,
    now: datetime,
) -> OAuthAuthorizationTransaction:
    provider = ConnectionProvider(provider)
    workspace_id = validate_workspace_id(workspace_id)
    try:
        consumed = authorization_store.consume(
            state,
            keyring,
            now=now,
            expected_workspace_id=workspace_id,
            expected_provider=provider,
        )
    except OAuthAuthorizationError as exc:
        raise OAuthCallbackError(str(exc)) from exc
    return consumed.transaction
