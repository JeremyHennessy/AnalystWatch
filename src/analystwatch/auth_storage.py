from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol, runtime_checkable

import psycopg
from psycopg.rows import dict_row

from .auth import WorkspaceMembership, WorkspaceRole
from .postgres_storage import POSTGRES_SCHEMA
from .workspace import validate_workspace_id


@runtime_checkable
class MembershipStore(Protocol):
    def initialize(self) -> None: ...

    def upsert_membership(self, membership: WorkspaceMembership) -> WorkspaceMembership: ...

    def get_membership(self, workspace_id: str, user_id: str) -> WorkspaceMembership | None: ...

    def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]: ...


class SQLiteMembershipStore:
    """Persistent membership store kept separate from monitoring SQLite schemas."""

    def __init__(self, path: str | Path):
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
                CREATE TABLE IF NOT EXISTS workspace_memberships (
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, user_id)
                )
                """
            )

    def upsert_membership(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO workspace_memberships(workspace_id, user_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(workspace_id, user_id)
                DO UPDATE SET role = excluded.role
                """,
                (membership.workspace_id, membership.user_id, membership.role.value),
            )
        return membership

    def get_membership(self, workspace_id: str, user_id: str) -> WorkspaceMembership | None:
        workspace = validate_workspace_id(workspace_id)
        with self.connect() as db:
            row = db.execute(
                """
                SELECT workspace_id, user_id, role
                FROM workspace_memberships
                WHERE workspace_id = ? AND user_id = ?
                """,
                (workspace, user_id),
            ).fetchone()
        if row is None:
            return None
        return WorkspaceMembership(
            workspace_id=row["workspace_id"],
            user_id=row["user_id"],
            role=WorkspaceRole(row["role"]),
        )

    def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]:
        workspace = validate_workspace_id(workspace_id)
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT workspace_id, user_id, role
                FROM workspace_memberships
                WHERE workspace_id = ?
                ORDER BY user_id
                """,
                (workspace,),
            ).fetchall()
        return [
            WorkspaceMembership(
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                role=WorkspaceRole(row["role"]),
            )
            for row in rows
        ]


class PostgresMembershipStore:
    """Workspace-membership persistence in the same managed PostgreSQL service."""

    def __init__(self, dsn: str):
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
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.workspace_memberships (
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY(workspace_id, user_id)
                )
                """
            )

    def upsert_membership(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.workspace_memberships(workspace_id, user_id, role)
                VALUES (%s, %s, %s)
                ON CONFLICT(workspace_id, user_id)
                DO UPDATE SET role = EXCLUDED.role, updated_at = NOW()
                """,
                (membership.workspace_id, membership.user_id, membership.role.value),
            )
        return membership

    def get_membership(self, workspace_id: str, user_id: str) -> WorkspaceMembership | None:
        workspace = validate_workspace_id(workspace_id)
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT workspace_id, user_id, role
                FROM {POSTGRES_SCHEMA}.workspace_memberships
                WHERE workspace_id = %s AND user_id = %s
                """,
                (workspace, user_id),
            ).fetchone()
        if row is None:
            return None
        return WorkspaceMembership(
            workspace_id=row["workspace_id"],
            user_id=row["user_id"],
            role=WorkspaceRole(row["role"]),
        )

    def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]:
        workspace = validate_workspace_id(workspace_id)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT workspace_id, user_id, role
                FROM {POSTGRES_SCHEMA}.workspace_memberships
                WHERE workspace_id = %s
                ORDER BY user_id
                """,
                (workspace,),
            ).fetchall()
        return [
            WorkspaceMembership(
                workspace_id=row["workspace_id"],
                user_id=row["user_id"],
                role=WorkspaceRole(row["role"]),
            )
            for row in rows
        ]
