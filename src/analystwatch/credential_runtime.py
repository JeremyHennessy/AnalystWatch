from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping

from .credential_crypto import AES_256_KEY_BYTES, CredentialKeyring

CREDENTIAL_KEYS_ENV = "ANALYSTWATCH_CREDENTIAL_KEYS_JSON"
CREDENTIAL_ACTIVE_KEY_ENV = "ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID"
MAX_KEYRING_KEYS = 16
MAX_KEYRING_JSON_CHARS = 32_768


class CredentialKeyConfigurationError(ValueError):
    """Safe deployment-key configuration error that never echoes key material."""


def load_credential_keyring(
    environ: Mapping[str, str] | None = None,
) -> CredentialKeyring:
    environment = os.environ if environ is None else environ
    active_key_id = environment.get(CREDENTIAL_ACTIVE_KEY_ENV)
    raw_keys = environment.get(CREDENTIAL_KEYS_ENV)
    if active_key_id is None or not active_key_id.strip():
        raise CredentialKeyConfigurationError("Active credential encryption key ID is not configured")
    if active_key_id != active_key_id.strip():
        raise CredentialKeyConfigurationError("Active credential encryption key ID must be trimmed")
    if raw_keys is None or not raw_keys.strip():
        raise CredentialKeyConfigurationError("Credential encryption keyring is not configured")
    if len(raw_keys) > MAX_KEYRING_JSON_CHARS:
        raise CredentialKeyConfigurationError("Credential encryption keyring configuration is too large")
    try:
        payload = json.loads(raw_keys)
    except json.JSONDecodeError as exc:
        raise CredentialKeyConfigurationError(
            "Credential encryption keyring configuration is not valid JSON"
        ) from exc
    if not isinstance(payload, dict) or not payload:
        raise CredentialKeyConfigurationError(
            "Credential encryption keyring must be a non-empty JSON object"
        )
    if len(payload) > MAX_KEYRING_KEYS:
        raise CredentialKeyConfigurationError(
            f"Credential encryption keyring must contain at most {MAX_KEYRING_KEYS} keys"
        )

    keys: dict[str, bytes] = {}
    for key_id, encoded in payload.items():
        if not isinstance(key_id, str) or not isinstance(encoded, str):
            raise CredentialKeyConfigurationError(
                "Credential encryption keyring keys and values must be strings"
            )
        try:
            decoded = _decode_key(encoded)
        except ValueError as exc:
            raise CredentialKeyConfigurationError(
                "Credential encryption key material is not valid base64url AES-256 key data"
            ) from exc
        keys[key_id] = decoded

    try:
        return CredentialKeyring(keys, active_key_id=active_key_id)
    except ValueError as exc:
        raise CredentialKeyConfigurationError(str(exc)) from exc


def _decode_key(value: str) -> bytes:
    if not value or value != value.strip():
        raise ValueError("invalid encoded key")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid encoded key") from exc
    if len(decoded) != AES_256_KEY_BYTES:
        raise ValueError("invalid key length")
    return decoded
