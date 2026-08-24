from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field, field_validator

from .connection_discovery import ConnectionProvider
from .workspace import validate_workspace_id

AES_256_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
CredentialSecretKind = Literal["access_token", "refresh_token"]


class CredentialCryptoError(ValueError):
    """Safe credential-encryption failure that never includes secret material."""


class EncryptedCredentialSecret(BaseModel):
    version: Literal[1] = 1
    algorithm: Literal["AES-256-GCM"] = "AES-256-GCM"
    key_id: str = Field(min_length=1, max_length=128)
    nonce_b64: str = Field(min_length=1)
    ciphertext_b64: str = Field(min_length=1)

    @field_validator("key_id")
    @classmethod
    def validate_key_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("key_id must be trimmed")
        return value


class CredentialKeyring:
    """In-memory keyring for authenticated credential encryption and key rotation.

    Key bytes are supplied by deployment configuration; they are never serialized by this class.
    Existing ciphertext remains decryptable while its key ID remains present in the keyring.
    New ciphertext always uses `active_key_id`.
    """

    def __init__(self, keys: Mapping[str, bytes], *, active_key_id: str) -> None:
        if not keys:
            raise ValueError("At least one credential encryption key is required")
        normalized: dict[str, bytes] = {}
        for key_id, key in keys.items():
            if not key_id or key_id != key_id.strip() or len(key_id) > 128:
                raise ValueError("Credential encryption key IDs must be non-empty and trimmed")
            if len(key) != AES_256_KEY_BYTES:
                raise ValueError("Credential encryption keys must be exactly 32 bytes")
            normalized[key_id] = bytes(key)
        if active_key_id not in normalized:
            raise ValueError("Active credential encryption key ID is not present in the keyring")
        self._keys = normalized
        self._active_key_id = active_key_id

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> EncryptedCredentialSecret:
        if not plaintext:
            raise ValueError("Credential secret must not be empty")
        if not associated_data:
            raise ValueError("Credential associated data must not be empty")
        nonce = os.urandom(AES_GCM_NONCE_BYTES)
        ciphertext = AESGCM(self._keys[self._active_key_id]).encrypt(
            nonce,
            plaintext,
            associated_data,
        )
        return EncryptedCredentialSecret(
            key_id=self._active_key_id,
            nonce_b64=_encode_base64(nonce),
            ciphertext_b64=_encode_base64(ciphertext),
        )

    def decrypt(
        self,
        envelope: EncryptedCredentialSecret,
        *,
        associated_data: bytes,
    ) -> bytes:
        if not associated_data:
            raise ValueError("Credential associated data must not be empty")
        key = self._keys.get(envelope.key_id)
        if key is None:
            raise CredentialCryptoError("Credential encryption key is not available")
        try:
            nonce = _decode_base64(envelope.nonce_b64)
            ciphertext = _decode_base64(envelope.ciphertext_b64)
        except ValueError as exc:
            raise CredentialCryptoError("Credential ciphertext encoding is invalid") from exc
        if len(nonce) != AES_GCM_NONCE_BYTES:
            raise CredentialCryptoError("Credential ciphertext nonce is invalid")
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, associated_data)
        except InvalidTag as exc:
            raise CredentialCryptoError(
                "Credential ciphertext could not be authenticated"
            ) from exc

    def reencrypt(
        self,
        envelope: EncryptedCredentialSecret,
        *,
        associated_data: bytes,
    ) -> EncryptedCredentialSecret:
        plaintext = self.decrypt(envelope, associated_data=associated_data)
        return self.encrypt(plaintext, associated_data=associated_data)


def credential_associated_data(
    workspace_id: str,
    provider: ConnectionProvider | str,
    credential_id: str,
    subject_id: str,
    secret_kind: CredentialSecretKind,
) -> bytes:
    workspace_id = validate_workspace_id(workspace_id)
    provider = ConnectionProvider(provider)
    if not credential_id or credential_id != credential_id.strip() or len(credential_id) > 256:
        raise ValueError("credential_id must be non-empty, trimmed, and at most 256 characters")
    if not subject_id or subject_id != subject_id.strip() or len(subject_id) > 512:
        raise ValueError("subject_id must be non-empty, trimmed, and at most 512 characters")
    if secret_kind not in {"access_token", "refresh_token"}:
        raise ValueError("secret_kind must be access_token or refresh_token")
    payload = {
        "credential_id": credential_id,
        "provider": provider.value,
        "secret_kind": secret_kind,
        "subject_id": subject_id,
        "version": 1,
        "workspace_id": workspace_id,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64(value: str) -> bytes:
    if not value or value != value.strip():
        raise ValueError("Invalid base64")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)
