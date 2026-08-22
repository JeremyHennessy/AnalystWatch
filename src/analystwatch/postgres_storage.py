from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .models import (
    DeliveryAttempt,
    DeliveryAttemptState,
    DeliveryMode,
    NotificationCandidate,
    NotificationCandidateState,
    Observation,
    ObservationReview,
    SourceDefinition,
    StorageVerification,
)
from .store import MonitoringStore
from .workspace import validate_workspace_id

POSTGRES_STORAGE_SCHEMA_VERSION = 1
POSTGRES_SCHEMA = "analystwatch"


class PostgresStorage:
    """Workspace-bound PostgreSQL implementation of ``MonitoringStore``."""

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
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.storage_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.sources (
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    baseline_observation_id TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY(workspace_id, id)
                )
                """
            )
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.observations (
                    sequence_id BIGSERIAL UNIQUE,
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    observation_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, id),
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES {POSTGRES_SCHEMA}.sources(workspace_id, id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_pg_observations_source_time
                ON {POSTGRES_SCHEMA}.observations(
                    workspace_id, source_id, observed_at DESC, sequence_id DESC
                )
                """
            )
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.observation_reviews (
                    workspace_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, observation_id),
                    FOREIGN KEY(workspace_id, observation_id)
                        REFERENCES {POSTGRES_SCHEMA}.observations(workspace_id, id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES {POSTGRES_SCHEMA}.sources(workspace_id, id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.notification_candidates (
                    sequence_id BIGSERIAL UNIQUE,
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    candidate_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, id),
                    UNIQUE(workspace_id, observation_id),
                    FOREIGN KEY(workspace_id, observation_id)
                        REFERENCES {POSTGRES_SCHEMA}.observations(workspace_id, id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES {POSTGRES_SCHEMA}.sources(workspace_id, id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_pg_candidates_source_time
                ON {POSTGRES_SCHEMA}.notification_candidates(
                    workspace_id, source_id, created_at DESC, sequence_id DESC
                )
                """
            )
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_SCHEMA}.delivery_attempts (
                    sequence_id BIGSERIAL UNIQUE,
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    attempt_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, id),
                    UNIQUE(workspace_id, idempotency_key),
                    UNIQUE(workspace_id, candidate_id, adapter, attempt_number),
                    FOREIGN KEY(workspace_id, candidate_id)
                        REFERENCES {POSTGRES_SCHEMA}.notification_candidates(workspace_id, id)
                        ON DELETE CASCADE,
                    FOREIGN KEY(workspace_id, source_id)
                        REFERENCES {POSTGRES_SCHEMA}.sources(workspace_id, id)
                        ON DELETE CASCADE
                )
                """
            )
            db.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_pg_attempts_candidate_time
                ON {POSTGRES_SCHEMA}.delivery_attempts(
                    workspace_id, candidate_id, created_at DESC, sequence_id DESC
                )
                """
            )
            db.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_pg_attempts_source_time
                ON {POSTGRES_SCHEMA}.delivery_attempts(
                    workspace_id, source_id, created_at DESC, sequence_id DESC
                )
                """
            )
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.storage_metadata(key, value)
                VALUES ('schema_version', %s)
                ON CONFLICT(key) DO NOTHING
                """,
                (str(POSTGRES_STORAGE_SCHEMA_VERSION),),
            )
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.storage_metadata(key, value)
                VALUES ('storage_id', %s)
                ON CONFLICT(key) DO NOTHING
                """,
                (str(uuid4()),),
            )
            row = db.execute(
                f"""
                SELECT value
                FROM {POSTGRES_SCHEMA}.storage_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None or int(row["value"]) != POSTGRES_STORAGE_SCHEMA_VERSION:
                raise ValueError("Database is not an AnalystWatch PostgreSQL schema-v1 store")

    @classmethod
    def verify_dsn(cls, dsn: str) -> StorageVerification:
        try:
            with psycopg.connect(dsn, row_factory=dict_row) as db:
                metadata_exists = db.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = 'storage_metadata'
                    ) AS exists
                    """,
                    (POSTGRES_SCHEMA,),
                ).fetchone()
                if not metadata_exists or not metadata_exists["exists"]:
                    return StorageVerification(
                        integrity_ok=False,
                        integrity_message="PostgreSQL database has no AnalystWatch metadata.",
                    )
                metadata = {
                    row["key"]: row["value"]
                    for row in db.execute(
                        f"SELECT key, value FROM {POSTGRES_SCHEMA}.storage_metadata"
                    ).fetchall()
                }
                schema_value = metadata.get("schema_version")
                schema_version = int(schema_value) if schema_value is not None else None
                counts: dict[str, int] = {}
                for table in (
                    "sources",
                    "observations",
                    "observation_reviews",
                    "notification_candidates",
                    "delivery_attempts",
                ):
                    row = db.execute(
                        f"SELECT COUNT(*) AS count FROM {POSTGRES_SCHEMA}.{table}"
                    ).fetchone()
                    counts[table] = int(row["count"]) if row else 0
                return StorageVerification(
                    storage_id=metadata.get("storage_id"),
                    schema_version=schema_version,
                    integrity_ok=(schema_version == POSTGRES_STORAGE_SCHEMA_VERSION),
                    integrity_message=(
                        "PostgreSQL connection and AnalystWatch schema verified."
                        if schema_version == POSTGRES_STORAGE_SCHEMA_VERSION
                        else "Unexpected AnalystWatch PostgreSQL schema version."
                    ),
                    source_count=counts["sources"],
                    observation_count=counts["observations"],
                    review_count=counts["observation_reviews"],
                    notification_candidate_count=counts["notification_candidates"],
                    delivery_attempt_count=counts["delivery_attempts"],
                )
        except psycopg.Error as exc:
            return StorageVerification(
                integrity_ok=False,
                integrity_message=f"PostgreSQL verification failed: {exc}",
            )

    def verify(self) -> StorageVerification:
        return self.verify_dsn(self.dsn)

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
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.sources(
                    workspace_id, id, definition_json
                ) VALUES (%s, %s, %s)
                ON CONFLICT(workspace_id, id)
                DO UPDATE SET definition_json = EXCLUDED.definition_json
                """,
                (self.workspace_id, source.id, source.model_dump_json()),
            )

    def get_source(self, source_id: str) -> SourceDefinition | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT definition_json
                FROM {POSTGRES_SCHEMA}.sources
                WHERE workspace_id = %s AND id = %s
                """,
                (self.workspace_id, source_id),
            ).fetchone()
        return SourceDefinition.model_validate_json(row["definition_json"]) if row else None

    def list_sources(self) -> list[SourceDefinition]:
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT definition_json
                FROM {POSTGRES_SCHEMA}.sources
                WHERE workspace_id = %s
                ORDER BY id
                """,
                (self.workspace_id,),
            ).fetchall()
        return [SourceDefinition.model_validate_json(row["definition_json"]) for row in rows]

    def save_observation(
        self,
        observation: Observation,
        *,
        set_baseline: bool = False,
        notification_candidate: NotificationCandidate | None = None,
    ) -> None:
        self._require_source(observation.source_id)
        if (
            notification_candidate is not None
            and notification_candidate.source_id != observation.source_id
        ):
            raise ValueError("Notification candidate must belong to the observation source")
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.observations(
                    workspace_id, id, source_id, observed_at, observation_json
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    self.workspace_id,
                    observation.id,
                    observation.source_id,
                    observation.observed_at,
                    observation.model_dump_json(),
                ),
            )
            if notification_candidate is not None:
                db.execute(
                    f"""
                    INSERT INTO {POSTGRES_SCHEMA}.notification_candidates(
                        workspace_id, id, source_id, observation_id,
                        created_at, candidate_json
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.workspace_id,
                        notification_candidate.id,
                        notification_candidate.source_id,
                        notification_candidate.observation_id,
                        notification_candidate.created_at,
                        notification_candidate.model_dump_json(),
                    ),
                )
            if set_baseline:
                db.execute(
                    f"""
                    UPDATE {POSTGRES_SCHEMA}.sources
                    SET baseline_observation_id = %s
                    WHERE workspace_id = %s AND id = %s
                    """,
                    (observation.id, self.workspace_id, observation.source_id),
                )

    def _observation_by_id(self, observation_id: str | None) -> Observation | None:
        if not observation_id:
            return None
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT observation_json
                FROM {POSTGRES_SCHEMA}.observations
                WHERE workspace_id = %s AND id = %s
                """,
                (self.workspace_id, observation_id),
            ).fetchone()
        return Observation.model_validate_json(row["observation_json"]) if row else None

    def get_observation(self, observation_id: str) -> Observation | None:
        return self._observation_by_id(observation_id)

    def get_baseline(self, source_id: str) -> Observation | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT baseline_observation_id
                FROM {POSTGRES_SCHEMA}.sources
                WHERE workspace_id = %s AND id = %s
                """,
                (self.workspace_id, source_id),
            ).fetchone()
        observation = self._observation_by_id(row["baseline_observation_id"]) if row else None
        return observation.model_copy(update={"is_baseline": True}) if observation else None

    def get_latest(self, source_id: str) -> Observation | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT observation_json
                FROM {POSTGRES_SCHEMA}.observations
                WHERE workspace_id = %s AND source_id = %s
                ORDER BY observed_at DESC, sequence_id DESC
                LIMIT 1
                """,
                (self.workspace_id, source_id),
            ).fetchone()
        if row is None:
            return None
        observation = Observation.model_validate_json(row["observation_json"])
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
                f"""
                SELECT observation_json
                FROM {POSTGRES_SCHEMA}.observations
                WHERE workspace_id = %s AND source_id = %s
                ORDER BY observed_at DESC, sequence_id DESC
                LIMIT %s
                """,
                (self.workspace_id, source_id, limit),
            ).fetchall()
        observations = [Observation.model_validate_json(row["observation_json"]) for row in rows]
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
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.observation_reviews(
                    workspace_id, observation_id, source_id, review_json
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT(workspace_id, observation_id) DO UPDATE SET
                    source_id = EXCLUDED.source_id,
                    review_json = EXCLUDED.review_json
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
                f"""
                SELECT review_json
                FROM {POSTGRES_SCHEMA}.observation_reviews
                WHERE workspace_id = %s AND observation_id = %s
                """,
                (self.workspace_id, observation_id),
            ).fetchone()
        return ObservationReview.model_validate_json(row["review_json"]) if row else None

    def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT candidate_json
                FROM {POSTGRES_SCHEMA}.notification_candidates
                WHERE workspace_id = %s AND id = %s
                """,
                (self.workspace_id, candidate_id),
            ).fetchone()
        return NotificationCandidate.model_validate_json(row["candidate_json"]) if row else None

    def list_notification_candidates(
        self,
        source_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[NotificationCandidate]:
        params: list[object] = [self.workspace_id]
        query = (
            f"SELECT candidate_json FROM {POSTGRES_SCHEMA}.notification_candidates "
            "WHERE workspace_id = %s"
        )
        if source_id is not None:
            if self.get_source(source_id) is None:
                return []
            query += " AND source_id = %s"
            params.append(source_id)
        query += " ORDER BY created_at DESC, sequence_id DESC LIMIT %s"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [NotificationCandidate.model_validate_json(row["candidate_json"]) for row in rows]

    def update_notification_candidate(
        self,
        candidate: NotificationCandidate,
    ) -> NotificationCandidate:
        self._require_source(candidate.source_id)
        with self.connect() as db:
            cursor = db.execute(
                f"""
                UPDATE {POSTGRES_SCHEMA}.notification_candidates
                SET candidate_json = %s
                WHERE workspace_id = %s AND id = %s
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
        try:
            with self.connect() as db:
                candidate_row = db.execute(
                    f"""
                    SELECT candidate_json
                    FROM {POSTGRES_SCHEMA}.notification_candidates
                    WHERE workspace_id = %s AND id = %s
                    FOR UPDATE
                    """,
                    (self.workspace_id, candidate_id),
                ).fetchone()
                if candidate_row is None:
                    raise KeyError(f"Unknown notification candidate: {candidate_id}")
                candidate = NotificationCandidate.model_validate_json(
                    candidate_row["candidate_json"]
                )
                if candidate.state != NotificationCandidateState.ELIGIBLE:
                    raise ValueError("Only Eligible notification candidates can be attempted")

                existing_row = db.execute(
                    f"""
                    SELECT attempt_json
                    FROM {POSTGRES_SCHEMA}.delivery_attempts
                    WHERE workspace_id = %s AND idempotency_key = %s
                    """,
                    (self.workspace_id, idempotency_key),
                ).fetchone()
                if existing_row is not None:
                    existing = DeliveryAttempt.model_validate_json(existing_row["attempt_json"])
                    if existing.candidate_id != candidate_id or existing.adapter != adapter:
                        raise ValueError(
                            "Idempotency key belongs to a different delivery attempt"
                        )
                    return existing, True

                latest_row = db.execute(
                    f"""
                    SELECT attempt_json
                    FROM {POSTGRES_SCHEMA}.delivery_attempts
                    WHERE workspace_id = %s AND candidate_id = %s AND adapter = %s
                    ORDER BY attempt_number DESC
                    LIMIT 1
                    """,
                    (self.workspace_id, candidate_id, adapter),
                ).fetchone()
                latest = (
                    DeliveryAttempt.model_validate_json(latest_row["attempt_json"])
                    if latest_row
                    else None
                )
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
                        raise ValueError(
                            "Failed delivery attempt is missing its completion timestamp"
                        )
                    next_retry_at = latest.completed_at + timedelta(minutes=retry_minutes)
                    if created_at < next_retry_at:
                        raise ValueError(
                            f"Delivery retry is not due until {next_retry_at.isoformat()}"
                        )
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
                    f"""
                    INSERT INTO {POSTGRES_SCHEMA}.delivery_attempts(
                        workspace_id, id, candidate_id, source_id, adapter,
                        attempt_number, idempotency_key, created_at, attempt_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.workspace_id,
                        prepared.id,
                        prepared.candidate_id,
                        prepared.source_id,
                        prepared.adapter,
                        prepared.attempt_number,
                        prepared.idempotency_key,
                        prepared.created_at,
                        prepared.model_dump_json(),
                    ),
                )
                return prepared, False
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("Delivery attempt uniqueness constraint was violated") from exc

    def create_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        self._require_source(attempt.source_id)
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO {POSTGRES_SCHEMA}.delivery_attempts(
                    workspace_id, id, candidate_id, source_id, adapter,
                    attempt_number, idempotency_key, created_at, attempt_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self.workspace_id,
                    attempt.id,
                    attempt.candidate_id,
                    attempt.source_id,
                    attempt.adapter,
                    attempt.attempt_number,
                    attempt.idempotency_key,
                    attempt.created_at,
                    attempt.model_dump_json(),
                ),
            )
        return attempt

    def update_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        self._require_source(attempt.source_id)
        with self.connect() as db:
            cursor = db.execute(
                f"""
                UPDATE {POSTGRES_SCHEMA}.delivery_attempts
                SET attempt_json = %s
                WHERE workspace_id = %s AND id = %s
                """,
                (attempt.model_dump_json(), self.workspace_id, attempt.id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Unknown delivery attempt: {attempt.id}")
        return attempt

    def get_delivery_attempt(self, attempt_id: str) -> DeliveryAttempt | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT attempt_json
                FROM {POSTGRES_SCHEMA}.delivery_attempts
                WHERE workspace_id = %s AND id = %s
                """,
                (self.workspace_id, attempt_id),
            ).fetchone()
        return DeliveryAttempt.model_validate_json(row["attempt_json"]) if row else None

    def get_delivery_attempt_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> DeliveryAttempt | None:
        with self.connect() as db:
            row = db.execute(
                f"""
                SELECT attempt_json
                FROM {POSTGRES_SCHEMA}.delivery_attempts
                WHERE workspace_id = %s AND idempotency_key = %s
                """,
                (self.workspace_id, idempotency_key),
            ).fetchone()
        return DeliveryAttempt.model_validate_json(row["attempt_json"]) if row else None

    def list_delivery_attempts(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryAttempt]:
        conditions = ["workspace_id = %s"]
        params: list[object] = [self.workspace_id]
        if candidate_id is not None:
            conditions.append("candidate_id = %s")
            params.append(candidate_id)
        if source_id is not None:
            if self.get_source(source_id) is None:
                return []
            conditions.append("source_id = %s")
            params.append(source_id)
        query = (
            f"SELECT attempt_json FROM {POSTGRES_SCHEMA}.delivery_attempts WHERE "
            + " AND ".join(conditions)
        )
        query += " ORDER BY created_at DESC, attempt_number DESC, sequence_id DESC LIMIT %s"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [DeliveryAttempt.model_validate_json(row["attempt_json"]) for row in rows]

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
            row = db.execute(
                f"""
                SELECT attempt_json
                FROM {POSTGRES_SCHEMA}.delivery_attempts
                WHERE workspace_id = %s AND id = %s
                FOR UPDATE
                """,
                (self.workspace_id, attempt_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown delivery attempt: {attempt_id}")
            attempt = DeliveryAttempt.model_validate_json(row["attempt_json"])
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
                f"""
                UPDATE {POSTGRES_SCHEMA}.delivery_attempts
                SET attempt_json = %s
                WHERE workspace_id = %s AND id = %s
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
                f"""
                UPDATE {POSTGRES_SCHEMA}.sources
                SET baseline_observation_id = %s
                WHERE workspace_id = %s AND id = %s
                """,
                (observation_id, self.workspace_id, source_id),
            )
        return observation.model_copy(update={"is_baseline": True})

    def clear_workspace(self) -> None:
        with self.connect() as db:
            db.execute(
                f"DELETE FROM {POSTGRES_SCHEMA}.sources WHERE workspace_id = %s",
                (self.workspace_id,),
            )

    def import_workspace(self, source_store: MonitoringStore) -> StorageVerification:
        if self.list_sources():
            raise ValueError("PostgreSQL destination workspace must be empty before import")
        sources = source_store.list_sources()
        if any(source.workspace_id != self.workspace_id for source in sources):
            raise ValueError("Source store contains records for another workspace")

        candidates = source_store.list_notification_candidates(limit=1_000_000)
        candidate_by_observation = {item.observation_id: item for item in candidates}
        baseline_by_source = {
            source.id: source_store.get_baseline(source.id) for source in sources
        }

        for source in sources:
            self.upsert_source(source)
            observations = source_store.list_observations(source.id, limit=1_000_000)
            for observation in reversed(observations):
                baseline = baseline_by_source[source.id]
                self.save_observation(
                    observation,
                    set_baseline=bool(baseline and baseline.id == observation.id),
                    notification_candidate=candidate_by_observation.get(observation.id),
                )
                review = source_store.get_review(observation.id)
                if review is not None:
                    self.save_review(review)

        for attempt in reversed(source_store.list_delivery_attempts(limit=1_000_000)):
            self.create_delivery_attempt(attempt)

        return self.verify()
