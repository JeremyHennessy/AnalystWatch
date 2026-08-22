from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol, runtime_checkable

import psycopg
from psycopg.rows import dict_row

from .postgres_storage import POSTGRES_SCHEMA
from .power_bi import PowerBIGuardDefinition, PowerBIGuardSnapshot
from .workspace import validate_workspace_id


@runtime_checkable
class PowerBIGuardStore(Protocol):
    def initialize(self) -> None: ...

    def upsert_guard(self, definition: PowerBIGuardDefinition) -> PowerBIGuardDefinition: ...

    def get_guard(self, guard_id: str) -> PowerBIGuardDefinition | None: ...

    def list_guards(self) -> list[PowerBIGuardDefinition]: ...

    def save_snapshot(self, snapshot: PowerBIGuardSnapshot) -> PowerBIGuardSnapshot: ...

    def latest_snapshot(self, guard_id: str) -> PowerBIGuardSnapshot | None: ...

    def list_snapshots(self, guard_id: str, limit: int = 30) -> list[PowerBIGuardSnapshot]: ...


class SQLitePowerBIGuardStore:
    """SQLite Power BI Guard state kept separate from monitoring SQLite schemas."""

    def __init__(self, path: str | Path, workspace_id: str):
        self.path = Path(path)
        self.workspace_id = validate_workspace_id(workspace_id)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS power_bi_guards (
                    workspace_id TEXT NOT NULL,
                    guard_id TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, guard_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS power_bi_guard_snapshots (
                    workspace_id TEXT NOT NULL,
                    guard_id TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, guard_id, checked_at)
                )
                """
            )

    def _require_workspace(self, definition: PowerBIGuardDefinition) -> None:
        if definition.workspace_id != self.workspace_id:
            raise ValueError("Power BI Guard definition belongs to another workspace")

    def upsert_guard(self, definition: PowerBIGuardDefinition) -> PowerBIGuardDefinition:
        self._require_workspace(definition)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO power_bi_guards(workspace_id, guard_id, definition_json)
                VALUES (?, ?, ?)
                ON CONFLICT(workspace_id, guard_id)
                DO UPDATE SET definition_json = excluded.definition_json
                """,
                (self.workspace_id, definition.id, definition.model_dump_json()),
            )
        return definition

    def get_guard(self, guard_id: str) -> PowerBIGuardDefinition | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT definition_json
                FROM power_bi_guards
                WHERE workspace_id = ? AND guard_id = ?
                """,
                (self.workspace_id, guard_id),
            ).fetchone()
        return PowerBIGuardDefinition.model_validate_json(row["definition_json"]) if row else None

    def list_guards(self) -> list[PowerBIGuardDefinition]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT definition_json
                FROM power_bi_guards
                WHERE workspace_id = ?
                ORDER BY guard_id
                """,
                (self.workspace_id,),
            ).fetchall()
        return [PowerBIGuardDefinition.model_validate_json(row["definition_json"]) for row in rows]

    def save_snapshot(self, snapshot: PowerBIGuardSnapshot) -> PowerBIGuardSnapshot:
        if self.get_guard(snapshot.guard_id) is None:
            message = (
                f"Unknown Power BI Guard in workspace {self.workspace_id}: "
                f"{snapshot.guard_id}"
            )
            raise KeyError(message)
        checked_at = snapshot.checked_at.isoformat()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO power_bi_guard_snapshots(
                    workspace_id, guard_id, checked_at, snapshot_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id, guard_id, checked_at)
                DO UPDATE SET snapshot_json = excluded.snapshot_json
                """,
                (self.workspace_id, snapshot.guard_id, checked_at, snapshot.model_dump_json()),
            )
        return snapshot

    def latest_snapshot(self, guard_id: str) -> PowerBIGuardSnapshot | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT snapshot_json
                FROM power_bi_guard_snapshots
                WHERE workspace_id = ? AND guard_id = ?
                ORDER BY checked_at DESC
                LIMIT 1
                """,
                (self.workspace_id, guard_id),
            ).fetchone()
        return PowerBIGuardSnapshot.model_validate_json(row["snapshot_json"]) if row else None

    def list_snapshots(self, guard_id: str, limit: int = 30) -> list[PowerBIGuardSnapshot]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT snapshot_json
                FROM power_bi_guard_snapshots
                WHERE workspace_id = ? AND guard_id = ?
                ORDER BY checked_at DESC
                LIMIT ?
                """,
                (self.workspace_id, guard_id, limit),
            ).fetchall()
        return [PowerBIGuardSnapshot.model_validate_json(row["snapshot_json"]) for row in rows]


class PostgresPowerBIGuardStore:
    """Workspace-scoped Power BI Guard state in managed PostgreSQL."""

    def __init__(self, dsn: str, workspace_id: str):
        if not dsn or dsn != dsn.strip():
            raise ValueError("PostgreSQL DSN must be non-empty and trimmed")
        self.dsn = dsn
        self.workspace_id = validate_workspace_id(workspace_id)

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute(f"CREATE SCHEMA IF NOT EXISTS {POSTGRES_SCHEMA}")
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.power_bi_guards (
                    workspace_id TEXT NOT NULL,
                    guard_id TEXT NOT NULL,
                    definition_json JSONB NOT NULL,
                    PRIMARY KEY(workspace_id, guard_id)
                )
                """
            )
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.power_bi_guard_snapshots (
                    workspace_id TEXT NOT NULL,
                    guard_id TEXT NOT NULL,
                    checked_at TIMESTAMPTZ NOT NULL,
                    snapshot_json JSONB NOT NULL,
                    PRIMARY KEY(workspace_id, guard_id, checked_at)
                )
                """
            )

    def _require_workspace(self, definition: PowerBIGuardDefinition) -> None:
        if definition.workspace_id != self.workspace_id:
            raise ValueError("Power BI Guard definition belongs to another workspace")

    def upsert_guard(self, definition: PowerBIGuardDefinition) -> PowerBIGuardDefinition:
        self._require_workspace(definition)
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.power_bi_guards(
                    workspace_id, guard_id, definition_json
                ) VALUES (%s, %s, %s::jsonb)
                ON CONFLICT(workspace_id, guard_id)
                DO UPDATE SET definition_json = EXCLUDED.definition_json
                """,
                (self.workspace_id, definition.id, definition.model_dump_json()),
            )
        return definition

    def get_guard(self, guard_id: str) -> PowerBIGuardDefinition | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT definition_json
                FROM {POSTGRES_SCHEMA}.power_bi_guards
                WHERE workspace_id = %s AND guard_id = %s
                """,
                (self.workspace_id, guard_id),
            ).fetchone()
        return PowerBIGuardDefinition.model_validate(row["definition_json"]) if row else None

    def list_guards(self) -> list[PowerBIGuardDefinition]:
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT definition_json
                FROM {POSTGRES_SCHEMA}.power_bi_guards
                WHERE workspace_id = %s
                ORDER BY guard_id
                """,
                (self.workspace_id,),
            ).fetchall()
        return [PowerBIGuardDefinition.model_validate(row["definition_json"]) for row in rows]

    def save_snapshot(self, snapshot: PowerBIGuardSnapshot) -> PowerBIGuardSnapshot:
        if self.get_guard(snapshot.guard_id) is None:
            message = (
                f"Unknown Power BI Guard in workspace {self.workspace_id}: "
                f"{snapshot.guard_id}"
            )
            raise KeyError(message)
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.power_bi_guard_snapshots(
                    workspace_id, guard_id, checked_at, snapshot_json
                ) VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT(workspace_id, guard_id, checked_at)
                DO UPDATE SET snapshot_json = EXCLUDED.snapshot_json
                """,
                (
                    self.workspace_id,
                    snapshot.guard_id,
                    snapshot.checked_at,
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def latest_snapshot(self, guard_id: str) -> PowerBIGuardSnapshot | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT snapshot_json
                FROM {POSTGRES_SCHEMA}.power_bi_guard_snapshots
                WHERE workspace_id = %s AND guard_id = %s
                ORDER BY checked_at DESC
                LIMIT 1
                """,
                (self.workspace_id, guard_id),
            ).fetchone()
        return PowerBIGuardSnapshot.model_validate(row["snapshot_json"]) if row else None

    def list_snapshots(self, guard_id: str, limit: int = 30) -> list[PowerBIGuardSnapshot]:
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT snapshot_json
                FROM {POSTGRES_SCHEMA}.power_bi_guard_snapshots
                WHERE workspace_id = %s AND guard_id = %s
                ORDER BY checked_at DESC
                LIMIT %s
                """,
                (self.workspace_id, guard_id, limit),
            ).fetchall()
        return [PowerBIGuardSnapshot.model_validate(row["snapshot_json"]) for row in rows]
