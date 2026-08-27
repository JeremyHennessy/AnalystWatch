from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from .connection_discovery import ConnectionProvider
from .credential_crypto import CredentialCryptoError
from .credential_persistence import PostgresCredentialStore, SQLiteCredentialStore
from .credential_runtime import CredentialKeyConfigurationError, load_credential_keyring
from .credential_store import CredentialStore, unseal_access_token
from .models import SourceDefinition, SourceType
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

    def __init__(self, store: CredentialStore, *, workspace_id: str) -> None:
        self.store = store
        self.workspace_id = validate_workspace_id(workspace_id)
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

        now = datetime.now(timezone.utc)
        if record.access_token_expires_at is None:
            raise SourceCredentialResolutionError(
                "Stored OAuth credential has no verified access-token expiry; "
                "reconnect is required."
            )
        if record.access_token_expires_at <= now:
            raise SourceCredentialResolutionError(
                "Stored OAuth access token has expired; reconnect is required until "
                "refresh support is enabled."
            )

        try:
            keyring = load_credential_keyring()
            access_token = unseal_access_token(record, keyring)
        except CredentialKeyConfigurationError as exc:
            raise SourceCredentialResolutionError(str(exc)) from exc
        except CredentialCryptoError as exc:
            raise SourceCredentialResolutionError(
                "Stored OAuth credential could not be decrypted safely."
            ) from exc

        return {"Authorization": f"Bearer {access_token}"}
