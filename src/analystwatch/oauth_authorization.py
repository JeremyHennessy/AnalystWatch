from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .connection_discovery import ConnectionProvider
from .credential_crypto import (
    CredentialCryptoError,
    CredentialKeyring,
    EncryptedCredentialSecret,
)
from .workspace import validate_workspace_id

DEFAULT_AUTHORIZATION_TTL_MINUTES = 10
MAX_AUTHORIZATION_TTL_MINUTES = 15
PKCE_METHOD: Literal["S256"] = "S256"
OPAQUE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
OAuthAuthorizationOperation = Literal["connect", "reconnect"]
OAuthAuthorizationAadVersion = Literal[1, 2]


class OAuthAuthorizationError(ValueError):
    """Bounded authorization-transaction error without state/verifier material."""


class OAuthAuthorizationTransaction(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=256)
    provider: ConnectionProvider
    credential_id: str = Field(min_length=1, max_length=256)
    operation: OAuthAuthorizationOperation = "connect"
    aad_version: OAuthAuthorizationAadVersion = 1
    state_sha256_b64: str = Field(min_length=43, max_length=43)
    pkce_verifier: EncryptedCredentialSecret
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None

    @field_validator("transaction_id", "user_id", "credential_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Authorization transaction identifiers must be trimmed")
        return value

    @field_validator("state_sha256_b64")
    @classmethod
    def validate_state_digest(cls, value: str) -> str:
        if OPAQUE_TOKEN_PATTERN.fullmatch(value) is None:
            raise ValueError("Authorization state digest must be canonical base64url")
        return value

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        return validate_workspace_id(value)

    @field_validator("created_at", "expires_at", "consumed_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Authorization transaction timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_order_and_operation(self) -> OAuthAuthorizationTransaction:
        if self.expires_at <= self.created_at:
            raise ValueError("Authorization transaction expiry must follow creation")
        if self.consumed_at is not None and self.consumed_at < self.created_at:
            raise ValueError("Authorization transaction consumption must not precede creation")
        if self.aad_version == 1 and self.operation != "connect":
            raise ValueError("Legacy authorization transactions can represent connect only")
        return self


class OAuthAuthorizationStart(BaseModel):
    transaction: OAuthAuthorizationTransaction
    state: str = Field(min_length=43, max_length=43)
    code_challenge: str = Field(min_length=43, max_length=43)
    code_challenge_method: Literal["S256"] = PKCE_METHOD

    @field_validator("state", "code_challenge")
    @classmethod
    def validate_opaque_token(cls, value: str) -> str:
        if OPAQUE_TOKEN_PATTERN.fullmatch(value) is None:
            raise ValueError("OAuth state/challenge must be canonical base64url")
        return value


@dataclass(frozen=True)
class OAuthAuthorizationConsumption:
    transaction: OAuthAuthorizationTransaction
    pkce_verifier: str = field(repr=False)


def begin_authorization_transaction(
    keyring: CredentialKeyring,
    *,
    workspace_id: str,
    user_id: str,
    provider: ConnectionProvider | str,
    credential_id: str,
    now: datetime,
    ttl_minutes: int = DEFAULT_AUTHORIZATION_TTL_MINUTES,
    operation: OAuthAuthorizationOperation = "connect",
) -> OAuthAuthorizationStart:
    _validate_now(now)
    if ttl_minutes < 1 or ttl_minutes > MAX_AUTHORIZATION_TTL_MINUTES:
        message = (
            "Authorization transaction TTL must be between 1 and "
            f"{MAX_AUTHORIZATION_TTL_MINUTES} minutes"
        )
        raise ValueError(message)
    workspace_id = validate_workspace_id(workspace_id)
    provider = ConnectionProvider(provider)
    user_id = _trimmed_identifier(user_id, "user_id", 256)
    credential_id = _trimmed_identifier(credential_id, "credential_id", 256)
    transaction_id = _random_token(24)
    state = _random_token(32)
    verifier = _random_token(32)
    state_digest = authorization_state_digest(state)
    aad_version: OAuthAuthorizationAadVersion = 2
    verifier_aad = _authorization_associated_data(
        workspace_id=workspace_id,
        user_id=user_id,
        provider=provider,
        credential_id=credential_id,
        transaction_id=transaction_id,
        operation=operation,
        aad_version=aad_version,
    )
    encrypted_verifier = keyring.encrypt(
        verifier.encode("ascii"),
        associated_data=verifier_aad,
    )
    transaction = OAuthAuthorizationTransaction(
        transaction_id=transaction_id,
        workspace_id=workspace_id,
        user_id=user_id,
        provider=provider,
        credential_id=credential_id,
        operation=operation,
        aad_version=aad_version,
        state_sha256_b64=state_digest,
        pkce_verifier=encrypted_verifier,
        created_at=now,
        expires_at=now + timedelta(minutes=ttl_minutes),
    )
    return OAuthAuthorizationStart(
        transaction=transaction,
        state=state,
        code_challenge=_sha256_b64(verifier.encode("ascii")),
    )


def authorization_state_digest(state: str) -> str:
    if not isinstance(state, str) or OPAQUE_TOKEN_PATTERN.fullmatch(state) is None:
        raise OAuthAuthorizationError("Authorization state is invalid")
    return _sha256_b64(state.encode("ascii"))


def consume_authorization_transaction(
    transaction: OAuthAuthorizationTransaction,
    keyring: CredentialKeyring,
    *,
    state: str,
    now: datetime,
) -> OAuthAuthorizationConsumption:
    _validate_now(now)
    transaction = revalidate_authorization_transaction(transaction)
    if transaction.consumed_at is not None:
        raise OAuthAuthorizationError("Authorization transaction was already consumed")
    if now >= transaction.expires_at:
        raise OAuthAuthorizationError("Authorization transaction has expired")
    state_digest = authorization_state_digest(state)
    if not hmac.compare_digest(state_digest, transaction.state_sha256_b64):
        raise OAuthAuthorizationError("Authorization state did not match")
    aad = _authorization_associated_data(
        workspace_id=transaction.workspace_id,
        user_id=transaction.user_id,
        provider=transaction.provider,
        credential_id=transaction.credential_id,
        transaction_id=transaction.transaction_id,
        operation=transaction.operation,
        aad_version=transaction.aad_version,
    )
    try:
        verifier_bytes = keyring.decrypt(transaction.pkce_verifier, associated_data=aad)
    except CredentialCryptoError as exc:
        raise OAuthAuthorizationError(
            "Authorization transaction secret could not be authenticated"
        ) from exc
    try:
        verifier = verifier_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise OAuthAuthorizationError(
            "Authorization transaction verifier encoding is invalid"
        ) from exc
    consumed = transaction.model_copy(update={"consumed_at": now}, deep=True)
    return OAuthAuthorizationConsumption(transaction=consumed, pkce_verifier=verifier)


def revalidate_authorization_transaction(
    transaction: OAuthAuthorizationTransaction,
) -> OAuthAuthorizationTransaction:
    payload = {
        "transaction_id": transaction.transaction_id,
        "workspace_id": transaction.workspace_id,
        "user_id": transaction.user_id,
        "provider": transaction.provider,
        "credential_id": transaction.credential_id,
        "operation": transaction.operation,
        "aad_version": transaction.aad_version,
        "state_sha256_b64": transaction.state_sha256_b64,
        "pkce_verifier": transaction.pkce_verifier,
        "created_at": transaction.created_at,
        "expires_at": transaction.expires_at,
        "consumed_at": transaction.consumed_at,
    }
    try:
        return OAuthAuthorizationTransaction.model_validate(payload)
    except ValueError as exc:
        raise OAuthAuthorizationError("Authorization transaction metadata is invalid") from exc


def _authorization_associated_data(
    *,
    workspace_id: str,
    user_id: str,
    provider: ConnectionProvider,
    credential_id: str,
    transaction_id: str,
    operation: OAuthAuthorizationOperation,
    aad_version: OAuthAuthorizationAadVersion,
) -> bytes:
    payload = {
        "credential_id": credential_id,
        "provider": provider.value,
        "purpose": "oauth_pkce_verifier",
        "transaction_id": transaction_id,
        "user_id": user_id,
        "version": aad_version,
        "workspace_id": workspace_id,
    }
    if aad_version == 2:
        payload["operation"] = operation
    elif operation != "connect":  # pragma: no cover - model validation blocks this
        raise OAuthAuthorizationError("Legacy authorization operation is invalid")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _random_token(byte_count: int) -> str:
    return _encode_base64(secrets.token_bytes(byte_count))


def _sha256_b64(value: bytes) -> str:
    return _encode_base64(hashlib.sha256(value).digest())


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _trimmed_identifier(value: str, label: str, max_length: int) -> str:
    if not value or value != value.strip() or len(value) > max_length:
        raise ValueError(f"{label} must be non-empty, trimmed, and at most {max_length} characters")
    return value


def _validate_now(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Authorization transaction time must be timezone-aware")
