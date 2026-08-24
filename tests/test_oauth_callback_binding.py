from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from analystwatch.credential_crypto import CredentialKeyring
from analystwatch.oauth_authorization import OAuthAuthorizationError, begin_authorization_transaction
from analystwatch.oauth_authorization_store import (
    MemoryOAuthAuthorizationStore,
    PostgresOAuthAuthorizationStore,
    SQLiteOAuthAuthorizationStore,
)
from analystwatch.postgres_storage import POSTGRES_SCHEMA

NOW = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"active": bytes([31]) * 32}, active_key_id="active")


def started(*, workspace_id: str = "team-a", provider: str = "google"):
    return begin_authorization_transaction(
        keyring(),
        workspace_id=workspace_id,
        user_id="operator",
        provider=provider,
        credential_id="primary",
        now=NOW,
    )


def assert_wrong_binding_does_not_consume(store) -> None:
    value = started()
    store.initialize()
    store.create(value.transaction)

    with pytest.raises(OAuthAuthorizationError, match="callback workspace"):
        store.consume(
            value.state,
            keyring(),
            now=NOW + timedelta(minutes=1),
            expected_workspace_id="team-b",
            expected_provider="google",
        )
    assert store.get(value.transaction.transaction_id).consumed_at is None

    with pytest.raises(OAuthAuthorizationError, match="callback provider"):
        store.consume(
            value.state,
            keyring(),
            now=NOW + timedelta(minutes=1),
            expected_workspace_id="team-a",
            expected_provider="microsoft",
        )
    assert store.get(value.transaction.transaction_id).consumed_at is None

    consumed = store.consume(
        value.state,
        keyring(),
        now=NOW + timedelta(minutes=1),
        expected_workspace_id="team-a",
        expected_provider="google",
    )
    assert consumed.transaction.consumed_at == NOW + timedelta(minutes=1)


def test_memory_binding_is_checked_before_consume() -> None:
    assert_wrong_binding_does_not_consume(MemoryOAuthAuthorizationStore())


def test_sqlite_binding_is_checked_before_consume(tmp_path) -> None:
    assert_wrong_binding_does_not_consume(
        SQLiteOAuthAuthorizationStore(tmp_path / "oauth-binding.db")
    )


def test_postgres_binding_is_checked_before_consume() -> None:
    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    store = PostgresOAuthAuthorizationStore(dsn)
    store.initialize()
    value = started(workspace_id="oauth-pg-binding")
    with store.connect() as db:
        db.execute(
            f"""
            DELETE FROM {POSTGRES_SCHEMA}.oauth_authorization_transactions
            WHERE transaction_id = %s
            """,
            (value.transaction.transaction_id,),
        )
    try:
        store.create(value.transaction)
        with pytest.raises(OAuthAuthorizationError, match="callback provider"):
            store.consume(
                value.state,
                keyring(),
                now=NOW + timedelta(minutes=1),
                expected_workspace_id="oauth-pg-binding",
                expected_provider="microsoft",
            )
        assert store.get(value.transaction.transaction_id).consumed_at is None

        consumed = store.consume(
            value.state,
            keyring(),
            now=NOW + timedelta(minutes=1),
            expected_workspace_id="oauth-pg-binding",
            expected_provider="google",
        )
        assert consumed.transaction.consumed_at == NOW + timedelta(minutes=1)
    finally:
        with store.connect() as db:
            db.execute(
                f"""
                DELETE FROM {POSTGRES_SCHEMA}.oauth_authorization_transactions
                WHERE transaction_id = %s
                """,
                (value.transaction.transaction_id,),
            )
