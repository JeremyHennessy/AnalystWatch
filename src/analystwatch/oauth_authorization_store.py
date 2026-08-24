from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Protocol, runtime_checkable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .credential_crypto import CredentialKeyring
from .oauth_authorization import (
    OAuthAuthorizationConsumption,
    OAuthAuthorizationError,
    OAuthAuthorizationTransaction,
    authorization_state_digest,
    consume_authorization_transaction,
    revalidate_authorization_transaction,
)
from .postgres_storage import POSTGRES_SCHEMA


@runtime_checkable
class OAuthAuthorizationStore(Protocol):
    def initialize(self) -> None: ...

    def create(
        self,
        transaction: OAuthAuthorizationTransaction,
    ) -> OAuthAuthorizationTransaction: ...

    def get(self, transaction_id: str) -> OAuthAuthorizationTransaction | None: ...

    def consume(
        self,
        state: str,
        keyring: CredentialKeyring,
        *,
        now: datetime,
    ) -> OAuthAuthorizationConsumption: ...


class MemoryOAuthAuthorizationStore(OAuthAuthorizationStore):
    def __init__(self) -> None:
        self._records: dict[str, OAuthAuthorizationTransaction] = {}
        self._state_index: dict[str, str] = {}
        self._lock = RLock()

    def initialize(self) -> None:
        return None

    def create(
        self,
        transaction: OAuthAuthorizationTransaction,
    ) -> OAuthAuthorizationTransaction:
        transaction = _transaction_for_create(transaction)
        with self._lock:
            if transaction.transaction_id in self._records:
                raise OAuthAuthorizationError("Authorization transaction already exists")
            if transaction.state_sha256_b64 in self._state_index:
                raise OAuthAuthorizationError("Authorization transaction already exists")
            stored = transaction.model_copy(deep=True)
            self._records[stored.transaction_id] = stored
            self._state_index[stored.state_sha256_b64] = stored.transaction_id
            return stored.model_copy(deep=True)

    def get(self, transaction_id: str) -> OAuthAuthorizationTransaction | None:
        transaction_id = _validate_transaction_id(transaction_id)
        with self._lock:
            stored = self._records.get(transaction_id)
            return stored.model_copy(deep=True) if stored is not None else None

    def consume(
        self,
        state: str,
        keyring: CredentialKeyring,
        *,
        now: datetime,
    ) -> OAuthAuthorizationConsumption:
        state_digest = authorization_state_digest(state)
        with self._lock:
            transaction_id = self._state_index.get(state_digest)
            if transaction_id is None:
                raise OAuthAuthorizationError("Authorization transaction was not found")
            transaction = self._records[transaction_id]
            consumed = consume_authorization_transaction(
                transaction,
                keyring,
                state=state,
                now=now,
            )
            self._records[transaction_id] = consumed.transaction.model_copy(deep=True)
            return _copy_consumption(consumed)


class SQLiteOAuthAuthorizationStore(OAuthAuthorizationStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_authorization_transactions (
                    transaction_id TEXT NOT NULL PRIMARY KEY,
                    state_sha256_b64 TEXT NOT NULL UNIQUE,
                    record_json TEXT NOT NULL
                )
                """
            )

    def create(
        self,
        transaction: OAuthAuthorizationTransaction,
    ) -> OAuthAuthorizationTransaction:
        transaction = _transaction_for_create(transaction)
        try:
            with self.connect() as db:
                db.execute(
                    """
                    INSERT INTO oauth_authorization_transactions(
                        transaction_id, state_sha256_b64, record_json
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        transaction.transaction_id,
                        transaction.state_sha256_b64,
                        transaction.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise OAuthAuthorizationError("Authorization transaction already exists") from exc
        return transaction.model_copy(deep=True)

    def get(self, transaction_id: str) -> OAuthAuthorizationTransaction | None:
        transaction_id = _validate_transaction_id(transaction_id)
        with self.connect() as db:
            row = db.execute(
                """
                SELECT record_json
                FROM oauth_authorization_transactions
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
        if row is None:
            return None
        return OAuthAuthorizationTransaction.model_validate_json(row["record_json"])

    def consume(
        self,
        state: str,
        keyring: CredentialKeyring,
        *,
        now: datetime,
    ) -> OAuthAuthorizationConsumption:
        state_digest = authorization_state_digest(state)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT record_json
                FROM oauth_authorization_transactions
                WHERE state_sha256_b64 = ?
                """,
                (state_digest,),
            ).fetchone()
            if row is None:
                raise OAuthAuthorizationError("Authorization transaction was not found")
            transaction = OAuthAuthorizationTransaction.model_validate_json(row["record_json"])
            consumed = consume_authorization_transaction(
                transaction,
                keyring,
                state=state,
                now=now,
            )
            db.execute(
                """
                UPDATE oauth_authorization_transactions
                SET record_json = ?
                WHERE transaction_id = ?
                """,
                (
                    consumed.transaction.model_dump_json(),
                    consumed.transaction.transaction_id,
                ),
            )
        return _copy_consumption(consumed)


class PostgresOAuthAuthorizationStore(OAuthAuthorizationStore):
    def __init__(self, dsn: str) -> None:
        if not dsn or dsn != dsn.strip():
            raise ValueError("PostgreSQL DSN must be non-empty and trimmed")
        self.dsn = dsn

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute(f"CREATE SCHEMA IF NOT EXISTS {POSTGRES_SCHEMA}")
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.oauth_authorization_transactions (
                    transaction_id TEXT NOT NULL PRIMARY KEY,
                    state_sha256_b64 TEXT NOT NULL UNIQUE,
                    record_json JSONB NOT NULL
                )
                """
            )

    def create(
        self,
        transaction: OAuthAuthorizationTransaction,
    ) -> OAuthAuthorizationTransaction:
        transaction = _transaction_for_create(transaction)
        try:
            with self.connect() as db:
                db.execute(
                    f"""
                    INSERT INTO {POSTGRES_SCHEMA}.oauth_authorization_transactions(
                        transaction_id, state_sha256_b64, record_json
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (
                        transaction.transaction_id,
                        transaction.state_sha256_b64,
                        Jsonb(transaction.model_dump(mode="json")),
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise OAuthAuthorizationError("Authorization transaction already exists") from exc
        return transaction.model_copy(deep=True)

    def get(self, transaction_id: str) -> OAuthAuthorizationTransaction | None:
        transaction_id = _validate_transaction_id(transaction_id)
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT record_json
                FROM {POSTGRES_SCHEMA}.oauth_authorization_transactions
                WHERE transaction_id = %s
                """,
                (transaction_id,),
            ).fetchone()
        if row is None:
            return None
        return OAuthAuthorizationTransaction.model_validate(row["record_json"])

    def consume(
        self,
        state: str,
        keyring: CredentialKeyring,
        *,
        now: datetime,
    ) -> OAuthAuthorizationConsumption:
        state_digest = authorization_state_digest(state)
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT record_json
                FROM {POSTGRES_SCHEMA}.oauth_authorization_transactions
                WHERE state_sha256_b64 = %s
                FOR UPDATE
                """,
                (state_digest,),
            ).fetchone()
            if row is None:
                raise OAuthAuthorizationError("Authorization transaction was not found")
            transaction = OAuthAuthorizationTransaction.model_validate(row["record_json"])
            consumed = consume_authorization_transaction(
                transaction,
                keyring,
                state=state,
                now=now,
            )
            db.execute(
                f"""
                UPDATE {POSTGRES_SCHEMA}.oauth_authorization_transactions
                SET record_json = %s
                WHERE transaction_id = %s
                """,
                (
                    Jsonb(consumed.transaction.model_dump(mode="json")),
                    consumed.transaction.transaction_id,
                ),
            )
        return _copy_consumption(consumed)


def _transaction_for_create(
    transaction: OAuthAuthorizationTransaction,
) -> OAuthAuthorizationTransaction:
    transaction = revalidate_authorization_transaction(transaction)
    if transaction.consumed_at is not None:
        raise OAuthAuthorizationError("Authorization transaction must be unconsumed when created")
    return transaction


def _validate_transaction_id(transaction_id: str) -> str:
    if (
        not isinstance(transaction_id, str)
        or not transaction_id
        or transaction_id != transaction_id.strip()
        or len(transaction_id) > 128
    ):
        raise ValueError("transaction_id must be non-empty, trimmed, and at most 128 characters")
    return transaction_id


def _copy_consumption(
    consumption: OAuthAuthorizationConsumption,
) -> OAuthAuthorizationConsumption:
    return OAuthAuthorizationConsumption(
        transaction=consumption.transaction.model_copy(deep=True),
        pkce_verifier=consumption.pkce_verifier,
    )
