from __future__ import annotations

import base64
import json

import pytest

from analystwatch.credential_runtime import (
    CREDENTIAL_ACTIVE_KEY_ENV,
    CREDENTIAL_KEYS_ENV,
    CredentialKeyConfigurationError,
    load_credential_keyring,
)


def encoded(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def test_keyring_loads_active_and_previous_keys_without_exposing_material() -> None:
    active = encoded(1)
    previous = encoded(2)
    keyring = load_credential_keyring(
        {
            CREDENTIAL_ACTIVE_KEY_ENV: "current",
            CREDENTIAL_KEYS_ENV: json.dumps({"current": active, "previous": previous}),
        }
    )

    assert keyring.active_key_id == "current"
    envelope = keyring.encrypt(b"private-token", associated_data=b"record-binding")
    assert envelope.key_id == "current"
    assert active not in envelope.model_dump_json()
    assert previous not in envelope.model_dump_json()


def test_keyring_configuration_fails_closed_when_missing() -> None:
    with pytest.raises(CredentialKeyConfigurationError, match="Active credential"):
        load_credential_keyring({})
    with pytest.raises(CredentialKeyConfigurationError, match="keyring is not configured"):
        load_credential_keyring({CREDENTIAL_ACTIVE_KEY_ENV: "key-1"})


def test_keyring_rejects_invalid_json_shape_and_key_material() -> None:
    cases = [
        "not-json",
        "[]",
        "{}",
        json.dumps({"key-1": "not-base64!"}),
        json.dumps({"key-1": base64.urlsafe_b64encode(b"short").decode("ascii")}),
    ]
    for raw in cases:
        with pytest.raises(CredentialKeyConfigurationError):
            load_credential_keyring(
                {
                    CREDENTIAL_ACTIVE_KEY_ENV: "key-1",
                    CREDENTIAL_KEYS_ENV: raw,
                }
            )


def test_keyring_errors_never_echo_encoded_key_material() -> None:
    private_material = "private-key-material-that-must-not-appear"
    with pytest.raises(CredentialKeyConfigurationError) as exc:
        load_credential_keyring(
            {
                CREDENTIAL_ACTIVE_KEY_ENV: "key-1",
                CREDENTIAL_KEYS_ENV: json.dumps({"key-1": private_material}),
            }
        )

    assert private_material not in str(exc.value)


def test_keyring_rejects_missing_active_key_and_too_many_keys() -> None:
    with pytest.raises(CredentialKeyConfigurationError, match="not present"):
        load_credential_keyring(
            {
                CREDENTIAL_ACTIVE_KEY_ENV: "missing",
                CREDENTIAL_KEYS_ENV: json.dumps({"key-1": encoded(1)}),
            }
        )
    too_many = {f"key-{index}": encoded(index % 250) for index in range(17)}
    with pytest.raises(CredentialKeyConfigurationError, match="at most 16"):
        load_credential_keyring(
            {
                CREDENTIAL_ACTIVE_KEY_ENV: "key-0",
                CREDENTIAL_KEYS_ENV: json.dumps(too_many),
            }
        )
