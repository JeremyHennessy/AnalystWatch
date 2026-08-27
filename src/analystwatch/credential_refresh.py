from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from datetime import datetime

import httpx
from psycopg.types.json import Jsonb

from .connection_discovery import ConnectionDiscoveryError, ConnectionProvider
from .connection_identity import inspect_connection_identity_with_access_token
from .credential_crypto import CredentialCryptoError, CredentialKeyring
from .credential_persistence import PostgresCredentialStore, SQLiteCredentialStore
from .credential_store import (
    CredentialStore,
    MemoryCredentialStore,
    ProviderCredentialRecord,
    seal_provider_credential,
    unseal_refresh_token,
    validate_credential_replacement,
)
from .oauth_exchange import (
    MAX_OAUTH_TOKEN_CHARS,
    OAuthTokenExchangeError,
    OAuthTokenSet,
    _parse_token_payload,
    _required_secret,
    _validate_now,
)
from .oauth_provider_config import OAuthProviderRuntimeConfig
from .postgres_storage import POSTGRES_SCHEMA
from .workspace import validate_workspace_id


class OAuthCredentialRefreshError(RuntimeError):
    """Bounded refresh error that never includes provider token material."""


CredentialUpdater = Callable[[ProviderCredentialRecord], ProviderCredentialRecord]
_MEMORY_LOCKS_GUARD = threading.Lock()
_MEMORY_LOCKS: weakref.WeakKeyDictionary[MemoryCredentialStore, threading.RLock] = (
    weakref.WeakKeyDictionary()
)


def refresh_provider_credential_if_expired(
    store: CredentialStore,
    keyring: CredentialKeyring,
    config: OAuthProviderRuntimeConfig,
    *,
    workspace_id: str,
    credential_id: str,
    now: datetime,
    client: httpx.Client | None = None,
) -> ProviderCredentialRecord:
    """Atomically refresh one expired provider credential.

    The credential-store lock remains held across the provider refresh and identity check so two
    workers cannot independently rotate the same refresh token and then overwrite one another.
    """
    _validate_now(now)
    workspace_id = validate_workspace_id(workspace_id)
    credential_id = _validate_credential_id(credential_id)
    store.initialize()

    def update(existing: ProviderCredentialRecord) -> ProviderCredentialRecord:
        if existing.provider != config.public.provider:
            raise OAuthCredentialRefreshError(
                "Stored OAuth credential provider does not match refresh configuration."
            )
        if existing.revoked_at is not None:
            raise OAuthCredentialRefreshError(
                "Stored OAuth credential is revoked; reconnect before refreshing it."
            )
        if existing.access_token_expires_at is not None:
            if existing.access_token_expires_at > now:
                return existing
        if now < existing.updated_at:
            raise OAuthCredentialRefreshError(
                "Credential refresh time precedes the latest stored credential update."
            )

        try:
            refresh_token = unseal_refresh_token(existing, keyring)
        except CredentialCryptoError as exc:
            raise OAuthCredentialRefreshError(
                "Stored OAuth refresh token could not be decrypted safely."
            ) from exc
        if refresh_token is None:
            raise OAuthCredentialRefreshError(
                "Stored OAuth credential has no refresh token; reconnect is required."
            )

        tokens = _exchange_refresh_token(
            config,
            refresh_token=refresh_token,
            now=now,
            client=client,
        )
        if tokens.access_token_expires_at is None:
            raise OAuthCredentialRefreshError(
                "OAuth token refresh returned no verified access-token expiry."
            )
        if tokens.scopes and not set(tokens.scopes).issubset(set(config.public.scopes)):
            raise OAuthCredentialRefreshError(
                "OAuth token refresh returned scope evidence outside the configured provider scope."
            )

        try:
            identity = inspect_connection_identity_with_access_token(
                existing.provider,
                tokens.access_token,
                client=client,
            )
        except ConnectionDiscoveryError as exc:
            raise OAuthCredentialRefreshError(
                f"{existing.provider.value.title()} account identity could not be verified "
                "after token refresh."
            ) from exc
        if identity.subject_id != existing.subject_id:
            raise OAuthCredentialRefreshError(
                "OAuth token refresh resolved a different provider account; reconnect/account "
                "switch is required."
            )

        rotated_refresh_token = tokens.refresh_token or refresh_token
        scopes = tokens.scopes or existing.scopes
        try:
            replacement = seal_provider_credential(
                keyring,
                credential_id=existing.credential_id,
                workspace_id=existing.workspace_id,
                provider=existing.provider,
                subject_id=existing.subject_id,
                access_token=tokens.access_token,
                refresh_token=rotated_refresh_token,
                scopes=scopes,
                access_token_expires_at=tokens.access_token_expires_at,
                display_name=identity.display_name,
                email=identity.email,
                now=now,
            )
        except ValueError as exc:
            raise OAuthCredentialRefreshError(
                "Refreshed provider credential could not be encrypted safely."
            ) from exc
        return replacement.model_copy(update={"created_at": existing.created_at})

    try:
        return _locked_credential_update(store, workspace_id, credential_id, update)
    except KeyError as exc:
        raise OAuthCredentialRefreshError(
            "Stored OAuth credential is not connected for refresh."
        ) from exc


def _exchange_refresh_token(
    config: OAuthProviderRuntimeConfig,
    *,
    refresh_token: str,
    now: datetime,
    client: httpx.Client | None,
) -> OAuthTokenSet:
    refresh_token = _required_secret(refresh_token, "refresh token", MAX_OAUTH_TOKEN_CHARS)
    request_data = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    active_client = client or httpx.Client(timeout=10.0, follow_redirects=False)
    owns_client = client is None
    try:
        try:
            response = active_client.post(config.public.token_endpoint, data=request_data)
        except httpx.HTTPError as exc:
            raise OAuthCredentialRefreshError(
                f"{config.public.provider.value.title()} token refresh request failed."
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise OAuthCredentialRefreshError(
                f"{config.public.provider.value.title()} token refresh was rejected "
                f"with HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthCredentialRefreshError(
                f"{config.public.provider.value.title()} token refresh returned unusable JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise OAuthCredentialRefreshError(
                f"{config.public.provider.value.title()} token refresh returned an invalid shape."
            )
        try:
            return _parse_token_payload(config.public.provider, payload, now=now)
        except OAuthTokenExchangeError as exc:
            raise OAuthCredentialRefreshError(
                f"{config.public.provider.value.title()} token refresh returned invalid token "
                "evidence."
            ) from exc
    finally:
        if owns_client:
            active_client.close()


def _locked_credential_update(
    store: CredentialStore,
    workspace_id: str,
    credential_id: str,
    updater: CredentialUpdater,
) -> ProviderCredentialRecord:
    if isinstance(store, MemoryCredentialStore):
        lock = _memory_lock(store)
        with lock:
            existing = store.get(workspace_id, credential_id)
            if existing is None:
                raise KeyError(credential_id)
            replacement = updater(existing)
            if replacement == existing:
                return existing
            validate_credential_replacement(existing, replacement)
            return store.upsert(replacement)

    if isinstance(store, SQLiteCredentialStore):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT record_json
                FROM provider_credentials
                WHERE workspace_id = ? AND credential_id = ?
                """,
                (workspace_id, credential_id),
            ).fetchone()
            if row is None:
                raise KeyError(credential_id)
            existing = ProviderCredentialRecord.model_validate_json(row["record_json"])
            replacement = updater(existing)
            if replacement == existing:
                return existing
            validate_credential_replacement(existing, replacement)
            db.execute(
                """
                UPDATE provider_credentials
                SET record_json = ?
                WHERE workspace_id = ? AND credential_id = ?
                """,
                (replacement.model_dump_json(), workspace_id, credential_id),
            )
            return replacement.model_copy(deep=True)

    if isinstance(store, PostgresCredentialStore):
        with store.connect() as db:
            row = db.execute(
                f"""
                SELECT record_json
                FROM {POSTGRES_SCHEMA}.provider_credentials
                WHERE workspace_id = %s AND credential_id = %s
                FOR UPDATE
                """,
                (workspace_id, credential_id),
            ).fetchone()
            if row is None:
                raise KeyError(credential_id)
            existing = ProviderCredentialRecord.model_validate(row["record_json"])
            replacement = updater(existing)
            if replacement == existing:
                return existing
            validate_credential_replacement(existing, replacement)
            db.execute(
                f"""
                UPDATE {POSTGRES_SCHEMA}.provider_credentials
                SET record_json = %s
                WHERE workspace_id = %s AND credential_id = %s
                """,
                (
                    Jsonb(replacement.model_dump(mode="json")),
                    workspace_id,
                    credential_id,
                ),
            )
            return replacement.model_copy(deep=True)

    raise OAuthCredentialRefreshError(
        "Credential store does not support atomic OAuth refresh rotation."
    )


def _memory_lock(store: MemoryCredentialStore) -> threading.RLock:
    with _MEMORY_LOCKS_GUARD:
        lock = _MEMORY_LOCKS.get(store)
        if lock is None:
            lock = threading.RLock()
            _MEMORY_LOCKS[store] = lock
        return lock


def _validate_credential_id(credential_id: str) -> str:
    if not credential_id or credential_id != credential_id.strip() or len(credential_id) > 256:
        raise ValueError("credential_id must be non-empty, trimmed, and at most 256 characters")
    return credential_id
