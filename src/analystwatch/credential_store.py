from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator, model_validator

from .connection_discovery import ConnectionProvider
from .credential_crypto import (
    CredentialCryptoError,
    CredentialKeyring,
    EncryptedCredentialSecret,
    credential_associated_data,
)
from .workspace import validate_workspace_id


class ProviderCredentialRecord(BaseModel):
    credential_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=128)
    provider: ConnectionProvider
    subject_id: str = Field(min_length=1, max_length=512)
    display_name: str | None = Field(default=None, max_length=512)
    email: str | None = Field(default=None, max_length=512)
    scopes: tuple[str, ...] = ()
    access_token: EncryptedCredentialSecret
    refresh_token: EncryptedCredentialSecret | None = None
    access_token_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None

    @field_validator("credential_id", "subject_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Credential identifiers must be trimmed")
        return value

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        return validate_workspace_id(value)

    @field_validator("display_name", "email")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("Optional credential identity fields must be non-empty and trimmed")
        return value

    @field_validator("scopes", mode="before")
    @classmethod
    def normalize_scopes(cls, value: Iterable[str] | None) -> tuple[str, ...]:
        if value is None:
            return ()
        scopes: set[str] = set()
        for scope in value:
            invalid = (
                not isinstance(scope, str)
                or not scope
                or scope != scope.strip()
                or len(scope) > 512
            )
            if invalid:
                raise ValueError("Credential scopes must be non-empty, trimmed strings")
            scopes.add(scope)
        return tuple(sorted(scopes))

    @field_validator("access_token_expires_at", "created_at", "updated_at", "revoked_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Credential timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> ProviderCredentialRecord:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise ValueError("revoked_at must not precede created_at")
        return self


@runtime_checkable
class CredentialStore(Protocol):
    def initialize(self) -> None: ...

    def upsert(self, record: ProviderCredentialRecord) -> ProviderCredentialRecord: ...

    def get(self, workspace_id: str, credential_id: str) -> ProviderCredentialRecord | None: ...

    def list(self, workspace_id: str) -> list[ProviderCredentialRecord]: ...

    def revoke(
        self,
        workspace_id: str,
        credential_id: str,
        *,
        revoked_at: datetime,
    ) -> ProviderCredentialRecord: ...


class MemoryCredentialStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ProviderCredentialRecord] = {}

    def initialize(self) -> None:
        return None

    def upsert(self, record: ProviderCredentialRecord) -> ProviderCredentialRecord:
        key = (record.workspace_id, record.credential_id)
        existing = self._records.get(key)
        if existing is not None:
            if existing.provider != record.provider or existing.subject_id != record.subject_id:
                raise ValueError(
                    "Credential account/provider replacement requires an explicit "
                    "account-switch flow"
                )
            if existing.created_at != record.created_at:
                raise ValueError("Credential created_at is immutable")
            if record.updated_at < existing.updated_at:
                raise ValueError("Credential update is older than the stored record")
            if existing.revoked_at is not None and record.revoked_at is None:
                raise ValueError("A revoked credential cannot be silently reactivated")
        stored = record.model_copy(deep=True)
        self._records[key] = stored
        return stored.model_copy(deep=True)

    def get(self, workspace_id: str, credential_id: str) -> ProviderCredentialRecord | None:
        key = (_validated_lookup_workspace(workspace_id), _validated_credential_id(credential_id))
        record = self._records.get(key)
        return record.model_copy(deep=True) if record is not None else None

    def list(self, workspace_id: str) -> list[ProviderCredentialRecord]:
        workspace_id = _validated_lookup_workspace(workspace_id)
        records = [
            record.model_copy(deep=True)
            for (record_workspace, _), record in self._records.items()
            if record_workspace == workspace_id
        ]
        return sorted(records, key=lambda item: item.credential_id)

    def revoke(
        self,
        workspace_id: str,
        credential_id: str,
        *,
        revoked_at: datetime,
    ) -> ProviderCredentialRecord:
        workspace_id = _validated_lookup_workspace(workspace_id)
        credential_id = _validated_credential_id(credential_id)
        if revoked_at.tzinfo is None or revoked_at.utcoffset() is None:
            raise ValueError("revoked_at must be timezone-aware")
        key = (workspace_id, credential_id)
        record = self._records.get(key)
        if record is None:
            raise KeyError(credential_id)
        if record.revoked_at is not None:
            return record.model_copy(deep=True)
        if revoked_at < record.updated_at:
            raise ValueError("revoked_at must not precede the latest credential update")
        revoked = record.model_copy(
            update={"revoked_at": revoked_at, "updated_at": revoked_at},
            deep=True,
        )
        self._records[key] = revoked
        return revoked.model_copy(deep=True)


def seal_provider_credential(
    keyring: CredentialKeyring,
    *,
    credential_id: str,
    workspace_id: str,
    provider: ConnectionProvider | str,
    subject_id: str,
    access_token: str,
    refresh_token: str | None,
    scopes: Iterable[str] = (),
    access_token_expires_at: datetime | None = None,
    display_name: str | None = None,
    email: str | None = None,
    now: datetime,
) -> ProviderCredentialRecord:
    provider = ConnectionProvider(provider)
    if not access_token or not access_token.strip():
        raise ValueError("access_token must be non-empty")
    if refresh_token is not None and (not refresh_token or not refresh_token.strip()):
        raise ValueError("refresh_token must be non-empty when provided")
    access_aad = credential_associated_data(
        workspace_id,
        provider,
        credential_id,
        subject_id,
        "access_token",
    )
    refresh_aad = credential_associated_data(
        workspace_id,
        provider,
        credential_id,
        subject_id,
        "refresh_token",
    )
    encrypted_access = keyring.encrypt(access_token.encode("utf-8"), associated_data=access_aad)
    encrypted_refresh = (
        keyring.encrypt(refresh_token.encode("utf-8"), associated_data=refresh_aad)
        if refresh_token is not None
        else None
    )
    return ProviderCredentialRecord(
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
        subject_id=subject_id,
        display_name=display_name,
        email=email,
        scopes=tuple(scopes),
        access_token=encrypted_access,
        refresh_token=encrypted_refresh,
        access_token_expires_at=access_token_expires_at,
        created_at=now,
        updated_at=now,
    )


def unseal_access_token(record: ProviderCredentialRecord, keyring: CredentialKeyring) -> str:
    return _unseal(record, keyring, "access_token", record.access_token)


def unseal_refresh_token(
    record: ProviderCredentialRecord,
    keyring: CredentialKeyring,
) -> str | None:
    if record.refresh_token is None:
        return None
    return _unseal(record, keyring, "refresh_token", record.refresh_token)


def _unseal(
    record: ProviderCredentialRecord,
    keyring: CredentialKeyring,
    secret_kind: str,
    envelope: EncryptedCredentialSecret,
) -> str:
    if record.revoked_at is not None:
        raise CredentialCryptoError("Credential is revoked")
    associated_data = credential_associated_data(
        record.workspace_id,
        record.provider,
        record.credential_id,
        record.subject_id,
        secret_kind,  # type: ignore[arg-type]
    )
    plaintext = keyring.decrypt(envelope, associated_data=associated_data)
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialCryptoError("Credential plaintext encoding is invalid") from exc


def _validated_lookup_workspace(workspace_id: str) -> str:
    return validate_workspace_id(workspace_id)


def _validated_credential_id(credential_id: str) -> str:
    if not credential_id or credential_id != credential_id.strip() or len(credential_id) > 256:
        raise ValueError("credential_id must be non-empty, trimmed, and at most 256 characters")
    return credential_id
