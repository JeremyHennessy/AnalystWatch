from __future__ import annotations

from datetime import datetime

import httpx

from .connection_discovery import ConnectionDiscoveryError, ConnectionProvider
from .connection_identity import inspect_connection_identity_with_access_token
from .credential_crypto import CredentialCryptoError, CredentialKeyring
from .credential_store import CredentialStore, seal_provider_credential
from .oauth_authorization import OAuthAuthorizationError, OAuthAuthorizationTransaction
from .oauth_authorization_store import OAuthAuthorizationStore
from .oauth_exchange import OAuthTokenExchangeError, exchange_authorization_code
from .oauth_provider_config import OAuthProviderRuntimeConfig
from .workspace import validate_workspace_id


class OAuthCallbackError(RuntimeError):
    """Bounded OAuth callback failure without state/code/token material."""


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
):
    provider = ConnectionProvider(provider)
    workspace_id = validate_workspace_id(workspace_id)
    if provider != config.public.provider:
        raise OAuthCallbackError("OAuth callback provider did not match configured provider")
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
    credential_store.initialize()
    existing = credential_store.get(workspace_id, transaction.credential_id)
    _validate_credential_operation(transaction, existing, provider)

    try:
        tokens = exchange_authorization_code(
            config,
            code=code,
            pkce_verifier=consumed.pkce_verifier,
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
            f"{provider.value.title()} account identity could not be verified after OAuth."
        ) from exc

    if transaction.operation == "reconnect":
        assert existing is not None  # validated before provider exchange
        if identity.subject_id != existing.subject_id:
            raise OAuthCallbackError(
                "Reconnect resolved a different provider account; explicit account switch is required."
            )

    scopes = tokens.scopes or (existing.scopes if existing is not None else ())
    try:
        record = seal_provider_credential(
            keyring,
            credential_id=transaction.credential_id,
            workspace_id=workspace_id,
            provider=provider,
            subject_id=identity.subject_id,
            display_name=identity.display_name,
            email=identity.email,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            scopes=scopes,
            access_token_expires_at=tokens.access_token_expires_at,
            now=now,
        )
    except (CredentialCryptoError, ValueError) as exc:
        raise OAuthCallbackError("OAuth credential could not be encrypted safely") from exc

    if existing is not None:
        update = {"created_at": existing.created_at}
        if record.refresh_token is None and existing.refresh_token is not None:
            update["refresh_token"] = existing.refresh_token.model_copy(deep=True)
        record = record.model_copy(update=update, deep=True)

    try:
        return credential_store.upsert(record)
    except ValueError as exc:
        raise OAuthCallbackError(str(exc)) from exc


def consume_oauth_authorization_denial(
    authorization_store: OAuthAuthorizationStore,
    keyring: CredentialKeyring,
    *,
    provider: ConnectionProvider | str,
    workspace_id: str,
    state: str,
    now: datetime,
) -> OAuthAuthorizationTransaction:
    try:
        return authorization_store.consume(
            state,
            keyring,
            now=now,
            expected_workspace_id=workspace_id,
            expected_provider=provider,
        ).transaction
    except OAuthAuthorizationError as exc:
        raise OAuthCallbackError(str(exc)) from exc


def _validate_credential_operation(
    transaction: OAuthAuthorizationTransaction,
    existing,
    provider: ConnectionProvider,
) -> None:
    if transaction.operation == "connect":
        if existing is not None:
            raise OAuthCallbackError(
                "Credential ID is already connected; use the explicit reconnect flow."
            )
        return

    if existing is None:
        raise OAuthCallbackError("Reconnect requires an existing stored OAuth credential.")
    if existing.provider != provider:
        raise OAuthCallbackError(
            "Stored OAuth credential provider did not match the reconnect provider."
        )
    if existing.revoked_at is not None:
        raise OAuthCallbackError(
            "Revoked OAuth credential cannot be silently reactivated by reconnect."
        )
