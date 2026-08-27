from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

import httpx

from .connection_discovery import ConnectionProvider
from .credential_crypto import CredentialCryptoError
from .credential_persistence import PostgresCredentialStore, SQLiteCredentialStore
from .credential_refresh import OAuthCredentialRefreshError, refresh_provider_credential_if_expired
from .credential_runtime import CredentialKeyConfigurationError, load_credential_keyring
from .credential_store import CredentialStore, unseal_access_token
from .models import SourceDefinition, SourceType
from .oauth_provider_config import OAuthProviderConfigurationError, load_oauth_provider_config
from .store import MonitoringStore
from .workspace import validate_workspace_id


class SourceCredentialResolutionError(ValueError):
    """Bounded source-credential error that never exposes token or key material."""


@runtime_checkable
class SourceCredentialResolver(Protocol):
    def resolve(self, source: SourceDefinition) -> dict[str, str] | None: ...


_SOURCE_PROVIDERS = {
    SourceType.MICROSOFT_EXCEL: ConnectionProvider.MICROSOFT,
    SourceType.GOOGLE_SHEETS: ConnectionProvider.GOOGLE,
}


class StoredSourceCredentialResolver:
    """Resolve a workspace-bound encrypted OAuth credential for source ingestion."""

    def __init__(
        self,
        store: CredentialStore,
        *,
        workspace_id: str,
        refresh_client: httpx.Client | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.workspace_id = validate_workspace_id(workspace_id)
        self.refresh_client = refresh_client
        self.now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._initialized = False

    @classmethod
    def from_monitoring_store(
        cls,
        storage: MonitoringStore,
    ) -> StoredSourceCredentialResolver | None:
        workspace_id = getattr(storage, "workspace_id", None)
        if not isinstance(workspace_id, str):
            return None

        dsn = getattr(storage, "dsn", None)
        if isinstance(dsn, str) and dsn:
            return cls(PostgresCredentialStore(dsn), workspace_id=workspace_id)

        path = getattr(storage, "path", None)
        if path is None:
            return None
        database_path = Path(path)
        credential_path = database_path.with_suffix(database_path.suffix + ".credentials.db")
        return cls(SQLiteCredentialStore(credential_path), workspace_id=workspace_id)

    def resolve(self, source: SourceDefinition) -> dict[str, str] | None:
        credential_id = source.config.credential_id
        if credential_id is None:
            return None
        if source.workspace_id != self.workspace_id:
            raise SourceCredentialResolutionError(
                "Stored source credential is not available in this workspace."
            )
        provider = _SOURCE_PROVIDERS.get(source.source_type)
        if provider is None:
            raise SourceCredentialResolutionError(
                "Stored OAuth credentials are supported only for Microsoft Excel and Google Sheets."
            )

        if not self._initialized:
            self.store.initialize()
            self._initialized = True
        record = self.store.get(self.workspace_id, credential_id)
        if record is None:
            raise SourceCredentialResolutionError(
                "Stored OAuth credential is not connected for this source."
            )
        if record.provider != provider:
            raise SourceCredentialResolutionError(
                "Stored OAuth credential provider does not match this source type."
            )
        if record.revoked_at is not None:
            raise SourceCredentialResolutionError(
                "Stored OAuth credential is revoked; reconnect before monitoring this source."
            )

        now = self.now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise SourceCredentialResolutionError(
                "Stored OAuth credential resolution time must be timezone-aware."
            )

        try:
            keyring = load_credential_keyring()
        except CredentialKeyConfigurationError as exc:
            raise SourceCredentialResolutionError(str(exc)) from exc

        expired_or_unknown = (
            record.access_token_expires_at is None or record.access_token_expires_at <= now
        )
        if expired_or_unknown:
            try:
                config = load_oauth_provider_config(provider)
            except OAuthProviderConfigurationError as exc:
                raise SourceCredentialResolutionError(
                    "Stored OAuth access token is expired or has no verified expiry, and automatic "
                    "refresh is unavailable; reconnect is required."
                ) from exc
            try:
                record = refresh_provider_credential_if_expired(
                    self.store,
                    keyring,
                    config,
                    workspace_id=self.workspace_id,
                    credential_id=credential_id,
                    now=now,
                    client=self.refresh_client,
                )
            except OAuthCredentialRefreshError as exc:
                raise SourceCredentialResolutionError(str(exc)) from exc

        if record.access_token_expires_at is None or record.access_token_expires_at <= now:
            raise SourceCredentialResolutionError(
                "Stored OAuth access token is not usable after refresh; reconnect is required."
            )

        try:
            access_token = unseal_access_token(record, keyring)
        except CredentialCryptoError as exc:
            raise SourceCredentialResolutionError(
                "Stored OAuth credential could not be decrypted safely."
            ) from exc

        return {"Authorization": f"Bearer {access_token}"}
