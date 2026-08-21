from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .models import (
    DeliveryAttempt,
    DeliveryAttemptState,
    DeliveryMode,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    ObservationReview,
    SourceDefinition,
    StorageSnapshotResult,
    StorageVerification,
)
from .storage import STORAGE_SCHEMA_VERSION, Storage
from .workspace import validate_workspace_id

NAMESPACED_STORAGE_SCHEMA_VERSION = 2


class NamespacedStorage:
    """Workspace-bound persistent store with composite workspace/domain keys.

    This is intentionally separate from the legacy ``Storage`` schema. One
    instance is bound to one workspace, while multiple instances can safely
    share the same SQLite file and reuse source/candidate/attempt identifiers.
    """

    def __init__(self, path: str | Path, workspace_id: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_id = validate_workspace_id(workspace_id)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS storage_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sources (
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    baseline_observation_id TEXT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(workspace_id, id)
                );

                CREATE TABLE IF NOT EXISTS observations (
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    observation_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, id),
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES sources(workspace_id, id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_ns_observations_source_time
                ON observations(workspace_id, source_id, observed_at DESC);

                CREATE TABLE IF NOT EXISTS observation_reviews (
                    workspace_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, observation_id),
                    FOREIGN KEY(workspace_id, observation_id)
                        REFERENCES observations(workspace_id, id) ON DELETE CASCADE,
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES sources(workspace_id, id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notification_candidates (
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, id),
                    UNIQUE(workspace_id, observation_id),
                    FOREIGN KEY(workspace_id, observation_id)
                        REFERENCES observations(workspace_id, id) ON DELETE CASCADE,
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES sources(workspace_id, id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_ns_candidates_source_time
                ON notification_candidates(workspace_id, source_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS delivery_attempts (
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    attempt_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, id),
                    UNIQUE(workspace_id, idempotency_key),
                    UNIQUE(workspace_id, candidate_id, adapter, attempt_number),
                    FOREIGN KEY(workspace_id, candidate_id)
                        REFERENCES notification_candidates(workspace_id, id) ON DELETE CASCADE,
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES sources(workspace_id, id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_ns_attempts_candidate_time
                ON delivery_attempts(workspace_id, candidate_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_ns_attempts_source_time
                ON delivery_attempts(workspace_id, source_id, created_at DESC);
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO storage_metadata(key, value) VALUES ('schema_version', ?)",
                (str(NAMESPACED_STORAGE_SCHEMA_VERSION),),
            )
            db.execute(
                "INSERT OR IGNORE INTO storage_metadata(key, value) VALUES ('storage_id', ?)",
                (str(uuid4()),),
            )
            schema_row = db.execute(
                "SELECT value FROM storage_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if schema_row is None or int(schema_row[0]) != NAMESPACED_STORAGE_SCHEMA_VERSION:
                raise ValueError("Database is not an AnalystWatch namespaced schema-v2 store")

    @staticmethod
    def _table_exists(db: sqlite3.Connection, table: str) -> bool:
        row = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    @classmethod
    def _table_count(cls, db: sqlite3.Connection, table: str) -> int:
        if not cls._table_exists(db, table):
            return 0
        row = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0

    @classmethod
    def verify_database(cls, path: str | Path) -> StorageVerification:
        database_path = Path(path)
        if not database_path.exists():
            raise FileNotFoundError(database_path)
        uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
        try:
            db = sqlite3.connect(uri, uri=True)
            try:
                integrity_rows = db.execute("PRAGMA integrity_check").fetchall()
                messages = [str(row[0]) for row in integrity_rows]
                integrity_ok = messages == ["ok"]
                metadata: dict[str, str] = {}
                if cls._table_exists(db, "storage_metadata"):
                    metadata = {
                        str(row[0]): str(row[1])
                        for row in db.execute(
                            "SELECT key, value FROM storage_metadata"
                        ).fetchall()
                    }
                schema_value = metadata.get("schema_version")
                schema_version = int(schema_value) if schema_value is not None else None
                return StorageVerification(
                    storage_id=metadata.get("storage_id"),
                    schema_version=schema_version,
                    integrity_ok=integrity_ok,
                    integrity_message="; ".join(messages),
                    source_count=cls._table_count(db, "sources"),
                    observation_count=cls._table_count(db, "observations"),
                    review_count=cls._table_count(db, "observation_reviews"),
                    notification_candidate_count=cls._table_count(
                        db, "notification_candidates"
                    ),
                    delivery_attempt_count=cls._table_count(db, "delivery_attempts"),
                )
            finally:
                db.close()
        except sqlite3.DatabaseError as exc:
            return StorageVerification(
                integrity_ok=False,
                integrity_message=f"SQLite verification failed: {exc}",
            )

    def verify(self) -> StorageVerification:
        return self.verify_database(self.path)

    def _require_source(self, source_id: str) -> SourceDefinition:
        source = self.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source in workspace {self.workspace_id}: {source_id}")
        return source

    def upsert_source(self, source: SourceDefinition) -> None:
        if source.workspace_id != self.workspace_id:
            raise ValueError(
                f"Source workspace {source.workspace_id!r} does not match bound workspace "
                f"{self.workspace_id!r}"
            )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO sources(workspace_id, id, definition_json)
                VALUES (?, ?, ?)
                ON CONFLICT(workspace_id, id)
                DO UPDATE SET definition_json=excluded.definition_json
                """,
                (self.workspace_id, source.id, source.model_dump_json()),
            )

    def get_source(self, source_id: str) -> SourceDefinition | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT definition_json
                FROM sources
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, source_id),
            ).fetchone()
        return SourceDefinition.model_validate_json(row[0]) if row else None

    def list_sources(self) -> list[SourceDefinition]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT definition_json
                FROM sources
                WHERE workspace_id = ?
                ORDER BY id
                """,
                (self.workspace_id,),
            ).fetchall()
        return [SourceDefinition.model_validate_json(row[0]) for row in rows]

    def save_observation(
        self,
        observation: Observation,
        *,
        set_baseline: bool = False,
        notification_candidate: NotificationCandidate | None = None,
    ) -> None:
        self._require_source(observation.source_id)
        if notification_candidate is not None:
            if notification_candidate.source_id != observation.source_id:
                raise ValueError("Notification candidate must belong to the observation source")
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO observations(
                    workspace_id, id, source_id, observed_at, observation_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self.workspace_id,
                    observation.id,
                    observation.source_id,
                    observation.observed_at.isoformat(),
                    observation.model_dump_json(),
                ),
            )
            if notification_candidate is not None:
                db.execute(
                    """
                    INSERT INTO notification_candidates(
                        workspace_id, id, source_id, observation_id,
                        created_at, candidate_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.workspace_id,
                        notification_candidate.id,
                        notification_candidate.source_id,
                        notification_candidate.observation_id,
                        notification_candidate.created_at.isoformat(),
                        notification_candidate.model_dump_json(),
                    ),
                )
            if set_baseline:
                db.execute(
                    """
                    UPDATE sources
                    SET baseline_observation_id = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (observation.id, self.workspace_id, observation.source_id),
                )

    def _observation_by_id(self, observation_id: str | None) -> Observation | None:
        if not observation_id:
            return None
        with self.connect() as db:
            row = db.execute(
                """
                SELECT observation_json
                FROM observations
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, observation_id),
            ).fetchone()
        return Observation.model_validate_json(row[0]) if row else None

    def get_observation(self, observation_id: str) -> Observation | None:
        return self._observation_by_id(observation_id)

    def get_baseline(self, source_id: str) -> Observation | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT baseline_observation_id
                FROM sources
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, source_id),
            ).fetchone()
        observation = self._observation_by_id(row[0]) if row and row[0] else None
        return observation.model_copy(update={"is_baseline": True}) if observation else None

    def get_latest(self, source_id: str) -> Observation | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT observation_json
                FROM observations
                WHERE workspace_id = ? AND source_id = ?
                ORDER BY observed_at DESC, rowid DESC
                LIMIT 1
                """,
                (self.workspace_id, source_id),
            ).fetchone()
        if row is None:
            return None
        observation = Observation.model_validate_json(row[0])
        baseline = self.get_baseline(source_id)
        if baseline and observation.id == baseline.id:
            observation = observation.model_copy(update={"is_baseline": True})
        return observation

    def get_last_successful(self, source_id: str) -> Observation | None:
        for observation in self.list_observations(source_id, limit=100):
            if observation.available and observation.profile is not None:
                return observation
        return None

    def list_reference_observations(
        self,
        source_id: str,
        limit: int = 5,
    ) -> list[Observation]:
        references: list[Observation] = []
        for observation in self.list_observations(source_id, limit=max(limit * 4, 20)):
            if (
                observation.available
                and observation.profile is not None
                and observation.health.value == "Healthy"
            ):
                references.append(observation)
            if len(references) >= limit:
                break
        return references

    def list_observations(self, source_id: str, limit: int = 20) -> list[Observation]:
        if self.get_source(source_id) is None:
            return []
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT observation_json
                FROM observations
                WHERE workspace_id = ? AND source_id = ?
                ORDER BY observed_at DESC, rowid DESC
                LIMIT ?
                """,
                (self.workspace_id, source_id, limit),
            ).fetchall()
        observations = [Observation.model_validate_json(row[0]) for row in rows]
        baseline = self.get_baseline(source_id)
        if baseline:
            observations = [
                item.model_copy(update={"is_baseline": True}) if item.id == baseline.id else item
                for item in observations
            ]
        return observations

    def save_review(self, review: ObservationReview) -> ObservationReview:
        self._require_source(review.source_id)
        observation = self.get_observation(review.observation_id)
        if observation is None or observation.source_id != review.source_id:
            raise ValueError("Observation review does not belong to this workspace/source")
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO observation_reviews(
                    workspace_id, observation_id, source_id, review_json
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id, observation_id) DO UPDATE SET
                    source_id=excluded.source_id,
                    review_json=excluded.review_json
                """,
                (
                    self.workspace_id,
                    review.observation_id,
                    review.source_id,
                    review.model_dump_json(),
                ),
            )
        return review

    def get_review(self, observation_id: str) -> ObservationReview | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT review_json
                FROM observation_reviews
                WHERE workspace_id = ? AND observation_id = ?
                """,
                (self.workspace_id, observation_id),
            ).fetchone()
        return ObservationReview.model_validate_json(row[0]) if row else None

    def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT candidate_json
                FROM notification_candidates
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, candidate_id),
            ).fetchone()
        return NotificationCandidate.model_validate_json(row[0]) if row else None

    def list_notification_candidates(
        self,
        source_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[NotificationCandidate]:
        params: list[object] = [self.workspace_id]
        query = "SELECT candidate_json FROM notification_candidates WHERE workspace_id = ?"
        if source_id is not None:
            if self.get_source(source_id) is None:
                return []
            query += " AND source_id = ?"
            params.append(source_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [NotificationCandidate.model_validate_json(row[0]) for row in rows]

    def update_notification_candidate(
        self,
        candidate: NotificationCandidate,
    ) -> NotificationCandidate:
        self._require_source(candidate.source_id)
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE notification_candidates
                SET candidate_json = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (candidate.model_dump_json(), self.workspace_id, candidate.id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Unknown notification candidate: {candidate.id}")
        return candidate

    def claim_delivery_attempt(
        self,
        candidate_id: str,
        idempotency_key: str,
        adapter: str,
        *,
        created_at: datetime,
        retry_minutes: int,
        claim_owner: str | None = None,
    ) -> tuple[DeliveryAttempt, bool]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            candidate_row = db.execute(
                """
                SELECT candidate_json
                FROM notification_candidates
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, candidate_id),
            ).fetchone()
            if candidate_row is None:
                raise KeyError(f"Unknown notification candidate: {candidate_id}")
            candidate = NotificationCandidate.model_validate_json(candidate_row[0])
            if candidate.state != NotificationCandidateState.ELIGIBLE:
                raise ValueError("Only Eligible notification candidates can be attempted")

            existing_row = db.execute(
                """
                SELECT attempt_json
                FROM delivery_attempts
                WHERE workspace_id = ? AND idempotency_key = ?
                """,
                (self.workspace_id, idempotency_key),
            ).fetchone()
            if existing_row is not None:
                existing = DeliveryAttempt.model_validate_json(existing_row[0])
                if existing.candidate_id != candidate_id or existing.adapter != adapter:
                    raise ValueError("Idempotency key belongs to a different delivery attempt")
                return existing, True

            latest_row = db.execute(
                """
                SELECT attempt_json
                FROM delivery_attempts
                WHERE workspace_id = ? AND candidate_id = ? AND adapter = ?
                ORDER BY attempt_number DESC
                LIMIT 1
                """,
                (self.workspace_id, candidate_id, adapter),
            ).fetchone()
            latest = DeliveryAttempt.model_validate_json(latest_row[0]) if latest_row else None

            if latest is not None and latest.state == DeliveryAttemptState.SUCCEEDED:
                raise ValueError("Candidate already has a successful dry-run delivery attempt")
            if latest is not None and latest.state == DeliveryAttemptState.PREPARED:
                raise ValueError("Candidate already has a Prepared dry-run delivery attempt")

            attempt_number = 1
            if latest is not None:
                if latest.state != DeliveryAttemptState.FAILED:
                    raise ValueError(
                        "A new delivery attempt requires the previous attempt to have Failed"
                    )
                if latest.completed_at is None:
                    raise ValueError("Failed delivery attempt is missing its completion timestamp")
                next_retry_at = latest.completed_at + timedelta(minutes=retry_minutes)
                if created_at < next_retry_at:
                    raise ValueError(f"Delivery retry is not due until {next_retry_at.isoformat()}")
                attempt_number = latest.attempt_number + 1

            prepared = DeliveryAttempt(
                id=f"{candidate.id}:{adapter}:{attempt_number}",
                candidate_id=candidate.id,
                source_id=candidate.source_id,
                adapter=adapter,
                mode=DeliveryMode.DRY_RUN,
                idempotency_key=idempotency_key,
                attempt_number=attempt_number,
                state=DeliveryAttemptState.PREPARED,
                created_at=created_at,
                claim_owner=claim_owner,
            )
            db.execute(
                """
                INSERT INTO delivery_attempts(
                    workspace_id, id, candidate_id, source_id, adapter,
                    attempt_number, idempotency_key, created_at, attempt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.workspace_id,
                    prepared.id,
                    prepared.candidate_id,
                    prepared.source_id,
                    prepared.adapter,
                    prepared.attempt_number,
                    prepared.idempotency_key,
                    prepared.created_at.isoformat(),
                    prepared.model_dump_json(),
                ),
            )
        return prepared, False

    def update_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        self._require_source(attempt.source_id)
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE delivery_attempts
                SET attempt_json = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (attempt.model_dump_json(), self.workspace_id, attempt.id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Unknown delivery attempt: {attempt.id}")
        return attempt

    def get_delivery_attempt(self, attempt_id: str) -> DeliveryAttempt | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT attempt_json
                FROM delivery_attempts
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, attempt_id),
            ).fetchone()
        return DeliveryAttempt.model_validate_json(row[0]) if row else None

    def list_delivery_attempts(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryAttempt]:
        conditions = ["workspace_id = ?"]
        params: list[object] = [self.workspace_id]
        if candidate_id is not None:
            conditions.append("candidate_id = ?")
            params.append(candidate_id)
        if source_id is not None:
            if self.get_source(source_id) is None:
                return []
            conditions.append("source_id = ?")
            params.append(source_id)
        query = "SELECT attempt_json FROM delivery_attempts WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, attempt_number DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [DeliveryAttempt.model_validate_json(row[0]) for row in rows]

    def reconcile_prepared_delivery_attempt(
        self,
        attempt_id: str,
        outcome: DeliveryAttemptState,
        *,
        reconciled_at: datetime,
        note: str,
        reconciled_by: str | None = None,
    ) -> DeliveryAttempt:
        if outcome not in {DeliveryAttemptState.SUCCEEDED, DeliveryAttemptState.FAILED}:
            raise ValueError("Prepared attempts can reconcile only to Succeeded or Failed")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT attempt_json
                FROM delivery_attempts
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, attempt_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown delivery attempt: {attempt_id}")
            attempt = DeliveryAttempt.model_validate_json(row[0])
            if attempt.state != DeliveryAttemptState.PREPARED:
                raise ValueError("Only Prepared delivery attempts can be reconciled")
            reconciled = attempt.model_copy(
                update={
                    "state": outcome,
                    "completed_at": reconciled_at,
                    "reconciled_at": reconciled_at,
                    "reconciled_by": reconciled_by,
                    "reconciliation_note": note,
                    "result_summary": (
                        "Prepared attempt reconciled as successful after explicit review."
                        if outcome == DeliveryAttemptState.SUCCEEDED
                        else None
                    ),
                    "error": (
                        "Prepared attempt reconciled as failed after explicit review."
                        if outcome == DeliveryAttemptState.FAILED
                        else None
                    ),
                }
            )
            db.execute(
                """
                UPDATE delivery_attempts
                SET attempt_json = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (reconciled.model_dump_json(), self.workspace_id, reconciled.id),
            )
        return reconciled

    def promote_baseline(self, source_id: str, observation_id: str) -> Observation:
        observation = self._observation_by_id(observation_id)
        if observation is None or observation.source_id != source_id:
            raise ValueError("Observation does not belong to this source")
        if not observation.available or observation.profile is None:
            raise ValueError("Unavailable observations cannot become a baseline")
        with self.connect() as db:
            db.execute(
                """
                UPDATE sources
                SET baseline_observation_id = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (observation_id, self.workspace_id, source_id),
            )
        return observation.model_copy(update={"is_baseline": True})

    @classmethod
    def import_legacy_snapshot(
        cls,
        snapshot: str | Path,
        destination: str | Path,
        *,
        workspace_id: str,
    ) -> StorageSnapshotResult:
        source_path = Path(snapshot)
        target = Path(destination)
        selected_workspace = validate_workspace_id(workspace_id)
        if source_path.resolve() == target.resolve():
            raise ValueError("Import destination must differ from the legacy snapshot")
        if target.exists():
            raise FileExistsError(target)

        legacy_verification = Storage.verify_database(source_path)
        if not legacy_verification.integrity_ok:
            raise ValueError("Legacy snapshot failed integrity verification")
        if legacy_verification.schema_version != STORAGE_SCHEMA_VERSION:
            raise ValueError("Import requires an AnalystWatch legacy schema-v1 snapshot")

        uri = f"file:{source_path.resolve().as_posix()}?mode=ro"
        source_db = sqlite3.connect(uri, uri=True)
        source_db.row_factory = sqlite3.Row
        target_store = cls(target, selected_workspace)
        try:
            source_rows = source_db.execute(
                """
                SELECT id, definition_json, baseline_observation_id, created_at
                FROM sources
                ORDER BY id
                """
            ).fetchall()
            selected_sources = [
                row
                for row in source_rows
                if SourceDefinition.model_validate_json(row["definition_json"]).workspace_id
                == selected_workspace
            ]
            selected_source_ids = [str(row["id"]) for row in selected_sources]

            target_store.initialize()
            with target_store.connect() as target_db:
                for row in selected_sources:
                    target_db.execute(
                        """
                        INSERT INTO sources(
                            workspace_id, id, definition_json,
                            baseline_observation_id, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            selected_workspace,
                            row["id"],
                            row["definition_json"],
                            row["baseline_observation_id"],
                            row["created_at"],
                        ),
                    )

                if selected_source_ids:
                    placeholders = ",".join("?" for _ in selected_source_ids)
                    source_filter = f"source_id IN ({placeholders})"
                    for row in source_db.execute(
                        """
                        SELECT id, source_id, observed_at, observation_json
                        FROM observations
                        WHERE """ + source_filter,
                        tuple(selected_source_ids),
                    ).fetchall():
                        target_db.execute(
                            """
                            INSERT INTO observations(
                                workspace_id, id, source_id, observed_at, observation_json
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                selected_workspace,
                                row["id"],
                                row["source_id"],
                                row["observed_at"],
                                row["observation_json"],
                            ),
                        )

                    for row in source_db.execute(
                        """
                        SELECT observation_id, source_id, review_json
                        FROM observation_reviews
                        WHERE """ + source_filter,
                        tuple(selected_source_ids),
                    ).fetchall():
                        target_db.execute(
                            """
                            INSERT INTO observation_reviews(
                                workspace_id, observation_id, source_id, review_json
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (
                                selected_workspace,
                                row["observation_id"],
                                row["source_id"],
                                row["review_json"],
                            ),
                        )

                    for row in source_db.execute(
                        """
                        SELECT id, source_id, observation_id, created_at, candidate_json
                        FROM notification_candidates
                        WHERE """ + source_filter,
                        tuple(selected_source_ids),
                    ).fetchall():
                        target_db.execute(
                            """
                            INSERT INTO notification_candidates(
                                workspace_id, id, source_id, observation_id,
                                created_at, candidate_json
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                selected_workspace,
                                row["id"],
                                row["source_id"],
                                row["observation_id"],
                                row["created_at"],
                                row["candidate_json"],
                            ),
                        )

                    for row in source_db.execute(
                        """
                        SELECT id, candidate_id, source_id, adapter, attempt_number,
                               idempotency_key, created_at, attempt_json
                        FROM delivery_attempts
                        WHERE """ + source_filter,
                        tuple(selected_source_ids),
                    ).fetchall():
                        target_db.execute(
                            """
                            INSERT INTO delivery_attempts(
                                workspace_id, id, candidate_id, source_id, adapter,
                                attempt_number, idempotency_key, created_at, attempt_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                selected_workspace,
                                row["id"],
                                row["candidate_id"],
                                row["source_id"],
                                row["adapter"],
                                row["attempt_number"],
                                row["idempotency_key"],
                                row["created_at"],
                                row["attempt_json"],
                            ),
                        )

            verification = cls.verify_database(target)
            if not verification.integrity_ok:
                raise ValueError("Imported namespaced database failed integrity verification")
            if verification.schema_version != NAMESPACED_STORAGE_SCHEMA_VERSION:
                raise ValueError("Imported database is not schema-v2")
            if verification.storage_id == legacy_verification.storage_id:
                raise ValueError("Imported database must receive a new storage identity")
            return StorageSnapshotResult(
                snapshot_path=str(target),
                verification=verification,
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            source_db.close()
