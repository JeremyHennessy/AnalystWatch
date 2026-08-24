from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analystwatch.credential_crypto import CredentialKeyring
from analystwatch.oauth_authorization import (
    OAuthAuthorizationError,
    begin_authorization_transaction,
    consume_authorization_transaction,
)

NOW = datetime(2026, 8, 24, 11, 40, tzinfo=timezone.utc)


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"key-1": bytes([13]) * 32}, active_key_id="key-1")


def start():
    return begin_authorization_transaction(
        keyring(),
        workspace_id="workspace-a",
        user_id="user-1",
        provider="microsoft",
        credential_id="microsoft-primary",
        now=NOW,
    )


def test_authorization_start_uses_hashed_state_and_encrypted_pkce_verifier() -> None:
    started = start()
    serialized = started.transaction.model_dump_json()

    assert len(started.state) == 43
    assert len(started.code_challenge) == 43
    assert started.code_challenge_method == "S256"
    assert started.state not in serialized
    assert "pkce_verifier" in serialized
    assert started.code_challenge not in serialized
    assert started.transaction.expires_at == NOW + timedelta(minutes=10)


def test_matching_state_consumes_once_and_recovers_pkce_verifier() -> None:
    started = start()
    consumed = consume_authorization_transaction(
        started.transaction,
        keyring(),
        state=started.state,
        now=NOW + timedelta(minutes=1),
    )

    assert consumed.transaction.consumed_at == NOW + timedelta(minutes=1)
    assert len(consumed.pkce_verifier) == 43
    assert consumed.pkce_verifier not in consumed.transaction.model_dump_json()

    with pytest.raises(OAuthAuthorizationError, match="already consumed"):
        consume_authorization_transaction(
            consumed.transaction,
            keyring(),
            state=started.state,
            now=NOW + timedelta(minutes=2),
        )


def test_state_mismatch_and_expiry_fail_closed_without_echoing_state() -> None:
    started = start()
    wrong_state = "x" * 43

    with pytest.raises(OAuthAuthorizationError, match="did not match") as mismatch:
        consume_authorization_transaction(
            started.transaction,
            keyring(),
            state=wrong_state,
            now=NOW + timedelta(minutes=1),
        )
    assert wrong_state not in str(mismatch.value)
    assert started.state not in str(mismatch.value)

    with pytest.raises(OAuthAuthorizationError, match="expired"):
        consume_authorization_transaction(
            started.transaction,
            keyring(),
            state=started.state,
            now=NOW + timedelta(minutes=10),
        )


def test_pkce_ciphertext_is_bound_to_user_provider_credential_and_transaction() -> None:
    started = start()
    mutations = [
        {"workspace_id": "workspace-b"},
        {"user_id": "user-2"},
        {"provider": "google"},
        {"credential_id": "other-credential"},
        {"transaction_id": "other-transaction"},
    ]
    for mutation in mutations:
        tampered = started.transaction.model_copy(update=mutation, deep=True)
        with pytest.raises(OAuthAuthorizationError, match="could not be authenticated"):
            consume_authorization_transaction(
                tampered,
                keyring(),
                state=started.state,
                now=NOW + timedelta(minutes=1),
            )


def test_authorization_transaction_rejects_bad_ttl_and_naive_time() -> None:
    for ttl in [0, 16]:
        with pytest.raises(ValueError, match="TTL"):
            begin_authorization_transaction(
                keyring(),
                workspace_id="workspace-a",
                user_id="user-1",
                provider="google",
                credential_id="google-primary",
                now=NOW,
                ttl_minutes=ttl,
            )

    with pytest.raises(ValueError, match="timezone-aware"):
        begin_authorization_transaction(
            keyring(),
            workspace_id="workspace-a",
            user_id="user-1",
            provider="google",
            credential_id="google-primary",
            now=NOW.replace(tzinfo=None),
        )
