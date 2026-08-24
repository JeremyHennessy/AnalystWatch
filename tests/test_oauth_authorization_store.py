from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from analystwatch.credential_crypto import CredentialKeyring
from analystwatch.oauth_authorization import (
    OAuthAuthorizationError,
    OAuthAuthorizationTransaction,
    authorization_state_digest,
    begin_authorization_transaction,
)
from analystwatch.oauth_authorization_store import (
    MemoryOAuthAuthorizationStore,
    OAuthAuthorizationStore,
    PostgresOAuthAuthorizationStore,
    SQLiteOAuthAuthorizationStore,
)
from analystwatch.postgres_storage import POSTGRES_SCHEMA

NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"key-1": bytes([17]) * 32}, active_key_id="key-1")


def start(
    *,
    workspace_id: str = "oauth-store-a",
    user_id: str = "user-1",
    provider: str = "microsoft",
    credential_id: str = "primary",
):
    return begin_authorization_transaction(
        keyring(),
        workspace_id=workspace_id,
        user_id=user_id,
        provider=provider,
        credential_id=credential_id,
        now=NOW,
    )


def exercise_store(store: OAuthAuthorizationStore) -> None:
    store.initialize()
    started = start()
    stored = store.create(started.transaction)

    assert stored == started.transaction
    assert store.get(started.transaction.transaction_id) == started.transaction

    consumed = store.consume(
        started.state,
        keyring(),
        now=NOW + timedelta(minutes=1),
    )
    assert consumed.transaction.consumed_at == NOW + timedelta(minutes=1)
    assert len(consumed.pkce_verifier) == 43
    assert store.get(started.transaction.transaction_id) == consumed.transaction

    with pytest.raises(OAuthAuthorizationError, match="already consumed"):
        store.consume(
            started.state,
            keyring(),
            now=NOW + timedelta(minutes=2),
        )


def test_memory_store_persists_one_time_consumption() -> None:
    exercise_store(MemoryOAuthAuthorizationStore())


def test_sqlite_store_persists_one_time_consumption_across_reopen(tmp_path) -> None:
    path = tmp_path / "oauth.db"
    store = SQLiteOAuthAuthorizationStore(path)
    store.initialize()
    started = start()
    store.create(started.transaction)

    reopened = SQLiteOAuthAuthorizationStore(path)
    consumed = reopened.consume(
        started.state,
        keyring(),
        now=NOW + timedelta(minutes=1),
    )
    assert consumed.transaction.consumed_at == NOW + timedelta(minutes=1)

    again = SQLiteOAuthAuthorizationStore(path)
    with pytest.raises(OAuthAuthorizationError, match="already consumed"):
        again.consume(
            started.state,
            keyring(),
            now=NOW + timedelta(minutes=2),
        )


def test_store_rejects_duplicates_consumed_create_and_unknown_state(tmp_path) -> None:
    store = SQLiteOAuthAuthorizationStore(tmp_path / "oauth.db")
    store.initialize()
    first = start()
    store.create(first.transaction)

    with pytest.raises(OAuthAuthorizationError, match="already exists"):
        store.create(first.transaction)

    second = start(credential_id="secondary")
    duplicate_state = second.transaction.model_copy(
        update={"state_sha256_b64": first.transaction.state_sha256_b64},
        deep=True,
    )
    with pytest.raises(OAuthAuthorizationError, match="already exists"):
        store.create(duplicate_state)

    consumed_at_create = second.transaction.model_copy(
        update={"consumed_at": NOW + timedelta(minutes=1)},
        deep=True,
    )
    with pytest.raises(OAuthAuthorizationError, match="must be unconsumed"):
        store.create(consumed_at_create)

    unknown = "A" * 43
    assert authorization_state_digest(unknown) != first.transaction.state_sha256_b64
    with pytest.raises(OAuthAuthorizationError, match="not found"):
        store.consume(unknown, keyring(), now=NOW + timedelta(minutes=1))


def test_authorization_state_digest_rejects_noncanonical_callback_state() -> None:
    for value in ["short", "*" * 43, "A" * 42 + "="]:
        with pytest.raises(OAuthAuthorizationError, match="state is invalid"):
            authorization_state_digest(value)


def _consume_concurrently(store: OAuthAuthorizationStore, state: str) -> list[str]:
    barrier = Barrier(2)

    def consume_once() -> str:
        barrier.wait()
        try:
            result = store.consume(
                state,
                keyring(),
                now=NOW + timedelta(minutes=1),
            )
            assert len(result.pkce_verifier) == 43
            return "consumed"
        except OAuthAuthorizationError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: consume_once(), range(2)))
    return results


def _assert_one_consumer_wins(results: list[str]) -> None:
    assert results.count("consumed") == 1
    failures = [result for result in results if result != "consumed"]
    assert len(failures) == 1
    assert "already consumed" in failures[0]


def test_memory_consume_is_atomic_under_concurrency() -> None:
    store = MemoryOAuthAuthorizationStore()
    store.initialize()
    started = start(credential_id="memory-race")
    store.create(started.transaction)

    _assert_one_consumer_wins(_consume_concurrently(store, started.state))


def test_sqlite_consume_is_atomic_under_concurrency(tmp_path) -> None:
    path = tmp_path / "oauth-race.db"
    creator = SQLiteOAuthAuthorizationStore(path)
    creator.initialize()
    started = start(credential_id="sqlite-race")
    creator.create(started.transaction)

    store = SQLiteOAuthAuthorizationStore(path)
    _assert_one_consumer_wins(_consume_concurrently(store, started.state))


def test_sqlite_raw_record_never_persists_state_or_pkce_plaintext(tmp_path) -> None:
    store = SQLiteOAuthAuthorizationStore(tmp_path / "oauth-private.db")
    store.initialize()
    started = start(credential_id="sqlite-private")
    store.create(started.transaction)

    with store.connect() as db:
        raw_before = db.execute(
            """
            SELECT record_json
            FROM oauth_authorization_transactions
            WHERE transaction_id = ?
            """,
            (started.transaction.transaction_id,),
        ).fetchone()["record_json"]
    assert started.state not in raw_before

    consumed = store.consume(
        started.state,
        keyring(),
        now=NOW + timedelta(minutes=1),
    )
    with store.connect() as db:
        raw_after = db.execute(
            """
            SELECT record_json
            FROM oauth_authorization_transactions
            WHERE transaction_id = ?
            """,
            (started.transaction.transaction_id,),
        ).fetchone()["record_json"]

    assert started.state not in raw_after
    assert consumed.pkce_verifier not in raw_after
    assert "ciphertext_b64" in raw_after


def _postgres_store() -> PostgresOAuthAuthorizationStore:
    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    store = PostgresOAuthAuthorizationStore(dsn)
    store.initialize()
    return store


def _clear_postgres(store: PostgresOAuthAuthorizationStore, *transaction_ids: str) -> None:
    if not transaction_ids:
        return
    with store.connect() as db:
        db.execute(
            f"""
            DELETE FROM {POSTGRES_SCHEMA}.oauth_authorization_transactions
            WHERE transaction_id = ANY(%s)
            """,
            (list(transaction_ids),),
        )


def test_postgres_store_persists_and_raw_json_has_no_state_or_verifier() -> None:
    store = _postgres_store()
    started = start(
        workspace_id="oauth-pg-persist",
        credential_id="postgres-private",
    )
    _clear_postgres(store, started.transaction.transaction_id)
    try:
        store.create(started.transaction)
        reopened = PostgresOAuthAuthorizationStore(store.dsn)
        assert reopened.get(started.transaction.transaction_id) == started.transaction

        consumed = reopened.consume(
            started.state,
            keyring(),
            now=NOW + timedelta(minutes=1),
        )
        with store.connect() as db:
            raw = db.execute(
                f"""
                SELECT record_json::text AS record_text
                FROM {POSTGRES_SCHEMA}.oauth_authorization_transactions
                WHERE transaction_id = %s
                """,
                (started.transaction.transaction_id,),
            ).fetchone()["record_text"]
        assert started.state not in raw
        assert consumed.pkce_verifier not in raw
        assert "ciphertext_b64" in raw
    finally:
        _clear_postgres(store, started.transaction.transaction_id)


def test_postgres_consume_is_atomic_under_concurrency() -> None:
    store = _postgres_store()
    started = start(
        workspace_id="oauth-pg-race",
        credential_id="postgres-race",
    )
    _clear_postgres(store, started.transaction.transaction_id)
    try:
        store.create(started.transaction)
        _assert_one_consumer_wins(_consume_concurrently(store, started.state))
    finally:
        _clear_postgres(store, started.transaction.transaction_id)


def test_postgres_duplicate_state_digest_is_rejected() -> None:
    store = _postgres_store()
    first = start(workspace_id="oauth-pg-duplicate", credential_id="first")
    second = start(workspace_id="oauth-pg-duplicate", credential_id="second")
    duplicate = second.transaction.model_copy(
        update={"state_sha256_b64": first.transaction.state_sha256_b64},
        deep=True,
    )
    transaction_ids = (first.transaction.transaction_id, second.transaction.transaction_id)
    _clear_postgres(store, *transaction_ids)
    try:
        store.create(first.transaction)
        with pytest.raises(OAuthAuthorizationError, match="already exists"):
            store.create(duplicate)
    finally:
        _clear_postgres(store, *transaction_ids)
