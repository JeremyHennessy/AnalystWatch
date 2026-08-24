from __future__ import annotations

import base64

import pytest

from analystwatch.connection_discovery import ConnectionProvider
from analystwatch.credential_crypto import (
    CredentialCryptoError,
    CredentialKeyring,
    EncryptedCredentialSecret,
    credential_associated_data,
)


def key(byte: int) -> bytes:
    return bytes([byte]) * 32


def test_aes_gcm_round_trip_never_serializes_plaintext_or_key() -> None:
    keyring = CredentialKeyring({"key-2026-08": key(7)}, active_key_id="key-2026-08")
    aad = credential_associated_data("default-local", "microsoft", "credential-1")
    plaintext = b"Bearer provider-secret-token"

    envelope = keyring.encrypt(plaintext, associated_data=aad)

    assert envelope.algorithm == "AES-256-GCM"
    assert envelope.key_id == "key-2026-08"
    assert plaintext.decode() not in envelope.model_dump_json()
    assert base64.urlsafe_b64encode(key(7)).decode() not in envelope.model_dump_json()
    assert keyring.decrypt(envelope, associated_data=aad) == plaintext


def test_ciphertext_is_bound_to_workspace_provider_and_credential() -> None:
    keyring = CredentialKeyring({"active": key(9)}, active_key_id="active")
    original_aad = credential_associated_data("workspace-a", "google", "credential-1")
    envelope = keyring.encrypt(b"refresh-secret", associated_data=original_aad)

    for mismatched_aad in [
        credential_associated_data("workspace-b", "google", "credential-1"),
        credential_associated_data("workspace-a", "microsoft", "credential-1"),
        credential_associated_data("workspace-a", "google", "credential-2"),
    ]:
        with pytest.raises(CredentialCryptoError, match="could not be authenticated"):
            keyring.decrypt(envelope, associated_data=mismatched_aad)


def test_tampered_ciphertext_fails_with_safe_error() -> None:
    keyring = CredentialKeyring({"active": key(3)}, active_key_id="active")
    aad = credential_associated_data("default-local", "google", "credential-1")
    envelope = keyring.encrypt(b"private-token", associated_data=aad)
    raw = bytearray(base64.urlsafe_b64decode(envelope.ciphertext_b64 + "=="))
    raw[-1] ^= 1
    tampered = envelope.model_copy(
        update={"ciphertext_b64": base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")}
    )

    with pytest.raises(CredentialCryptoError, match="could not be authenticated") as exc:
        keyring.decrypt(tampered, associated_data=aad)

    assert "private-token" not in str(exc.value)
    assert tampered.ciphertext_b64 not in str(exc.value)


def test_key_rotation_keeps_old_ciphertext_decryptable_and_reencrypts_with_active_key() -> None:
    old_keyring = CredentialKeyring({"old": key(1)}, active_key_id="old")
    aad = credential_associated_data("default-local", ConnectionProvider.MICROSOFT, "cred")
    old_envelope = old_keyring.encrypt(b"secret", associated_data=aad)

    rotating = CredentialKeyring(
        {"old": key(1), "new": key(2)},
        active_key_id="new",
    )
    new_envelope = rotating.reencrypt(old_envelope, associated_data=aad)

    assert rotating.decrypt(old_envelope, associated_data=aad) == b"secret"
    assert new_envelope.key_id == "new"
    assert new_envelope.ciphertext_b64 != old_envelope.ciphertext_b64
    assert rotating.decrypt(new_envelope, associated_data=aad) == b"secret"


def test_unknown_key_id_fails_without_exposing_envelope() -> None:
    envelope = CredentialKeyring({"old": key(4)}, active_key_id="old").encrypt(
        b"secret",
        associated_data=b"bound-record",
    )
    active_only = CredentialKeyring({"new": key(5)}, active_key_id="new")

    with pytest.raises(CredentialCryptoError, match="key is not available") as exc:
        active_only.decrypt(envelope, associated_data=b"bound-record")

    assert envelope.ciphertext_b64 not in str(exc.value)


def test_keyring_rejects_invalid_key_material_and_active_key() -> None:
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        CredentialKeyring({"bad": b"short"}, active_key_id="bad")
    with pytest.raises(ValueError, match="not present"):
        CredentialKeyring({"one": key(1)}, active_key_id="missing")
    with pytest.raises(ValueError, match="non-empty and trimmed"):
        CredentialKeyring({" bad ": key(1)}, active_key_id=" bad ")


def test_envelope_rejects_untrimmed_key_id() -> None:
    with pytest.raises(ValueError, match="key_id must be trimmed"):
        EncryptedCredentialSecret(
            key_id=" key ",
            nonce_b64="abc",
            ciphertext_b64="def",
        )


def test_associated_data_is_canonical_and_validated() -> None:
    first = credential_associated_data("default-local", "google", "credential-1")
    second = credential_associated_data(
        "default-local",
        ConnectionProvider.GOOGLE,
        "credential-1",
    )

    assert first == second
    assert b"default-local" in first
    assert b"google" in first
    with pytest.raises(ValueError, match="credential_id"):
        credential_associated_data("default-local", "google", " bad ")
