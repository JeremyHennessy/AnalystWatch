from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol, runtime_checkable

import psycopg
from psycopg.rows import dict_row

from .dependencies import DependencyEdge
from .postgres_storage import POSTGRES_SCHEMA
from .workspace import validate_workspace_id


@runtime_checkable
class DependencyStore(Protocol):
    def initialize(self) -> None: ...
    def upsert_edge(self, edge: DependencyEdge) -> DependencyEdge: ...
    def get_edge(self, edge_id: str) -> DependencyEdge | None: ...
    def list_edges(self) -> list[DependencyEdge]: ...
    def delete_edge(self, edge_id: str) -> bool: ...


class SQLiteDependencyStore:
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
                CREATE TABLE IF NOT EXISTS dependency_edges (
                    workspace_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    edge_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, edge_id)
                )
                """
            )

    def _require_workspace(self, edge: DependencyEdge) -> None:
        if edge.workspace_id != self.workspace_id:
            raise ValueError("dependency edge belongs to another workspace")

    def upsert_edge(self, edge: DependencyEdge) -> DependencyEdge:
        self._require_workspace(edge)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO dependency_edges(workspace_id, edge_id, edge_json)
                VALUES (?, ?, ?)
                ON CONFLICT(workspace_id, edge_id)
                DO UPDATE SET edge_json = excluded.edge_json
                """,
                (self.workspace_id, edge.id, edge.model_dump_json()),
            )
        return edge

    def get_edge(self, edge_id: str) -> DependencyEdge | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT edge_json FROM dependency_edges
                WHERE workspace_id = ? AND edge_id = ?
                """,
                (self.workspace_id, edge_id),
            ).fetchone()
        return DependencyEdge.model_validate_json(row["edge_json"]) if row else None

    def list_edges(self) -> list[DependencyEdge]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT edge_json FROM dependency_edges
                WHERE workspace_id = ? ORDER BY edge_id
                """,
                (self.workspace_id,),
            ).fetchall()
        return [DependencyEdge.model_validate_json(row["edge_json"]) for row in rows]

    def delete_edge(self, edge_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM dependency_edges WHERE workspace_id = ? AND edge_id = ?",
                (self.workspace_id, edge_id),
            )
        return cursor.rowcount > 0


class PostgresDependencyStore:
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
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.dependency_edges (
                    workspace_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    edge_json JSONB NOT NULL,
                    PRIMARY KEY(workspace_id, edge_id)
                )
                """
            )

    def _require_workspace(self, edge: DependencyEdge) -> None:
        if edge.workspace_id != self.workspace_id:
            raise ValueError("dependency edge belongs to another workspace")

    def upsert_edge(self, edge: DependencyEdge) -> DependencyEdge:
        self._require_workspace(edge)
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.dependency_edges(
                    workspace_id, edge_id, edge_json
                ) VALUES (%s, %s, %s::jsonb)
                ON CONFLICT(workspace_id, edge_id)
                DO UPDATE SET edge_json = EXCLUDED.edge_json
                """,
                (self.workspace_id, edge.id, edge.model_dump_json()),
            )
        return edge

    def get_edge(self, edge_id: str) -> DependencyEdge | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT edge_json FROM {POSTGRES_SCHEMA}.dependency_edges
                WHERE workspace_id = %s AND edge_id = %s
                """,
                (self.workspace_id, edge_id),
            ).fetchone()
        return DependencyEdge.model_validate(row["edge_json"]) if row else None

    def list_edges(self) -> list[DependencyEdge]:
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT edge_json FROM {POSTGRES_SCHEMA}.dependency_edges
                WHERE workspace_id = %s ORDER BY edge_id
                """,
                (self.workspace_id,),
            ).fetchall()
        return [DependencyEdge.model_validate(row["edge_json"]) for row in rows]

    def delete_edge(self, edge_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                f"""
                DELETE FROM {POSTGRES_SCHEMA}.dependency_edges
                WHERE workspace_id = %s AND edge_id = %s
                """,
                (self.workspace_id, edge_id),
            )
        return cursor.rowcount > 0
