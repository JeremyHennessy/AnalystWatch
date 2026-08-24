from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .credential_store import (
    CredentialStore,
    ProviderCredentialRecord,
    revoke_credential_record,
    validate_credential_replacement,
)
from .postgres_storage import POSTGRES_SCHEMA
from .workspace import validate_workspace_id


class SQLiteCredentialStore(CredentialStore):
    """Encrypted credential records persisted separately from monitoring state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_credentials (
                    workspace_id TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, credential_id)
                )
                """
            )

    def upsert(self, record: ProviderCredentialRecord) -> ProviderCredentialRecord:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT record_json
                FROM provider_credentials
                WHERE workspace_id = ? AND credential_id = ?
                """,
                (record.workspace_id, record.credential_id),
            ).fetchone()
            if row is None:
                db.execute(
                    """
                    INSERT INTO provider_credentials(workspace_id, credential_id, record_json)
                    VALUES (?, ?, ?)
                    """,
                    (
                        record.workspace_id,
                        record.credential_id,
                        record.model_dump_json(),
                    ),
                )
            else:
                existing = ProviderCredentialRecord.model_validate_json(row["record_json"])
                validate_credential_replacement(existing, record)
                db.execute(
                    """
                    UPDATE provider_credentials
                    SET record_json = ?
                    WHERE workspace_id = ? AND credential_id = ?
                    """,
                    (
                        record.model_dump_json(),
                        record.workspace_id,
                        record.credential_id,
                    ),
                )
        return record.model_copy(deep=True)

    def get(self, workspace_id: str, credential_id: str) -> ProviderCredentialRecord | None:
        workspace_id = validate_workspace_id(workspace_id)
        credential_id = _validate_credential_id(credential_id)
        with self.connect() as db:
            row = db.execute(
                """
                SELECT record_json
                FROM provider_credentials
                WHERE workspace_id = ? AND credential_id = ?
                """,
                (workspace_id, credential_id),
            ).fetchone()
        if row is None:
            return None
        return ProviderCredentialRecord.model_validate_json(row["record_json"])

    def list(self, workspace_id: str) -> list[ProviderCredentialRecord]:
        workspace_id = validate_workspace_id(workspace_id)
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT record_json
                FROM provider_credentials
                WHERE workspace_id = ?
                ORDER BY credential_id
                """,
                (workspace_id,),
            ).fetchall()
        return [ProviderCredentialRecord.model_validate_json(row["record_json"]) for row in rows]

    def revoke(
        self,
        workspace_id: str,
        credential_id: str,
        *,
        revoked_at: datetime,
    ) -> ProviderCredentialRecord:
        workspace_id = validate_workspace_id(workspace_id)
        credential_id = _validate_credential_id(credential_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT record_json
                FROM provider_credentials
                WHERE workspace_id = ? AND credential_id = ?
                """,
                (workspace_id, credential_id),
            ).fetchone()
            if row is None:
                raise KeyError(credential_id)
            existing = ProviderCredentialRecord.model_validate_json(row["record_json"])
            revoked = revoke_credential_record(existing, revoked_at=revoked_at)
            db.execute(
                """
                UPDATE provider_credentials
                SET record_json = ?
                WHERE workspace_id = ? AND credential_id = ?
                """,
                (revoked.model_dump_json(), workspace_id, credential_id),
            )
        return revoked


class PostgresCredentialStore(CredentialStore):
    """Encrypted credential records in the managed AnalystWatch PostgreSQL schema."""

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
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.provider_credentials (
                    workspace_id TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    record_json JSONB NOT NULL,
                    PRIMARY KEY(workspace_id, credential_id)
                )
                """
            )

    def upsert(self, record: ProviderCredentialRecord) -> ProviderCredentialRecord:
        serialized = record.model_dump(mode="json")
        with self.connect() as db:
            inserted = db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.provider_credentials(
                    workspace_id, credential_id, record_json
                )
                VALUES (%s, %s, %s)
                ON CONFLICT(workspace_id, credential_id) DO NOTHING
                RETURNING record_json
                """,
                (record.workspace_id, record.credential_id, Jsonb(serialized)),
            ).fetchone()
            if inserted is not None:
                return record.model_copy(deep=True)

            row = db.execute(
                f"""
                SELECT record_json
                FROM {POSTGRES_SCHEMA}.provider_credentials
                WHERE workspace_id = %s AND credential_id = %s
                FOR UPDATE
                """,
                (record.workspace_id, record.credential_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("Credential row disappeared during locked replacement")
            existing = ProviderCredentialRecord.model_validate(row["record_json"])
            validate_credential_replacement(existing, record)
            db.execute(
                f"""
                UPDATE {POSTGRES_SCHEMA}.provider_credentials
                SET record_json = %s
                WHERE workspace_id = %s AND credential_id = %s
                """,
                (Jsonb(serialized), record.workspace_id, record.credential_id),
            )
        return record.model_copy(deep=True)

    def get(self, workspace_id: str, credential_id: str) -> ProviderCredentialRecord | None:
        workspace_id = validate_workspace_id(workspace_id)
        credential_id = _validate_credential_id(credential_id)
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT record_json
                FROM {POSTGRES_SCHEMA}.provider_credentials
                WHERE workspace_id = %s AND credential_id = %s
                """,
                (workspace_id, credential_id),
            ).fetchone()
        if row is None:
            return None
        return ProviderCredentialRecord.model_validate(row["record_json"])

    def list(self, workspace_id: str) -> list[ProviderCredentialRecord]:
        workspace_id = validate_workspace_id(workspace_id)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT record_json
                FROM {POSTGRES_SCHEMA}.provider_credentials
                WHERE workspace_id = %s
                ORDER BY credential_id
                """,
                (workspace_id,),
            ).fetchall()
        return [ProviderCredentialRecord.model_validate(row["record_json"]) for row in rows]

    def revoke(
        self,
        workspace_id: str,
        credential_id: str,
        *,
        revoked_at: datetime,
    ) -> ProviderCredentialRecord:
        workspace_id = validate_workspace_id(workspace_id)
        credential_id = _validate_credential_id(credential_id)
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT record_json
                FROM {POSTGRES_SCHEMA}.provider_credentials
                WHERE workspace_id = %s AND credential_id = %s
                FOR UPDATE
                """,
                (workspace_id, credential_id),
            ).fetchone()
            if row is None:
                raise KeyError(credential_id)
            existing = ProviderCredentialRecord.model_validate(row["record_json"])
            revoked = revoke_credential_record(existing, revoked_at=revoked_at)
            db.execute(
                f"""
                UPDATE {POSTGRES_SCHEMA}.provider_credentials
                SET record_json = %s
                WHERE workspace_id = %s AND credential_id = %s
                """,
                (Jsonb(revoked.model_dump(mode="json")), workspace_id, credential_id),
            )
        return revoked


def _validate_credential_id(credential_id: str) -> str:
    if not credential_id or credential_id != credential_id.strip() or len(credential_id) > 256:
        raise ValueError("credential_id must be non-empty, trimmed, and at most 256 characters")
    return credential_id
