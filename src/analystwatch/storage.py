from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    DeliveryAttempt,
    NotificationCandidate,
    Observation,
    ObservationReview,
    SourceDefinition,
)


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    definition_json TEXT NOT NULL,
                    baseline_observation_id TEXT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    observation_json TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_observations_source_time
                ON observations(source_id, observed_at DESC);

                CREATE TABLE IF NOT EXISTS observation_reviews (
                    observation_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    FOREIGN KEY(observation_id) REFERENCES observations(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notification_candidates (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    FOREIGN KEY(observation_id) REFERENCES observations(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_notification_candidates_source_time
                ON notification_candidates(source_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS delivery_attempts (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    attempt_json TEXT NOT NULL,
                    FOREIGN KEY(candidate_id)
                        REFERENCES notification_candidates(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
                    UNIQUE(candidate_id, adapter, attempt_number)
                );

                CREATE INDEX IF NOT EXISTS idx_delivery_attempts_candidate_time
                ON delivery_attempts(candidate_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_delivery_attempts_source_time
                ON delivery_attempts(source_id, created_at DESC);
                """
            )

    def upsert_source(self, source: SourceDefinition) -> None:
        payload = source.model_dump_json()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO sources(id, definition_json)
                VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET definition_json=excluded.definition_json
                """,
                (source.id, payload),
            )

    def get_source(self, source_id: str) -> SourceDefinition | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT definition_json FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        return SourceDefinition.model_validate_json(row[0]) if row else None

    def list_sources(self) -> list[SourceDefinition]:
        with self.connect() as db:
            rows = db.execute("SELECT definition_json FROM sources ORDER BY id").fetchall()
        return [SourceDefinition.model_validate_json(row[0]) for row in rows]

    def save_observation(
        self,
        observation: Observation,
        *,
        set_baseline: bool = False,
        notification_candidate: NotificationCandidate | None = None,
    ) -> None:
        payload = observation.model_dump_json()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO observations(id, source_id, observed_at, observation_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    observation.id,
                    observation.source_id,
                    observation.observed_at.isoformat(),
                    payload,
                ),
            )
            if notification_candidate is not None:
                db.execute(
                    """
                    INSERT INTO notification_candidates(
                        id, source_id, observation_id, created_at, candidate_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        notification_candidate.id,
                        notification_candidate.source_id,
                        notification_candidate.observation_id,
                        notification_candidate.created_at.isoformat(),
                        notification_candidate.model_dump_json(),
                    ),
                )
            if set_baseline:
                db.execute(
                    "UPDATE sources SET baseline_observation_id = ? WHERE id = ?",
                    (observation.id, observation.source_id),
                )

    def _observation_by_id(self, observation_id: str | None) -> Observation | None:
        if not observation_id:
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT observation_json FROM observations WHERE id = ?", (observation_id,)
            ).fetchone()
        return Observation.model_validate_json(row[0]) if row else None

    def get_observation(self, observation_id: str) -> Observation | None:
        return self._observation_by_id(observation_id)

    def get_baseline(self, source_id: str) -> Observation | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT baseline_observation_id FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        observation = self._observation_by_id(row[0]) if row and row[0] else None
        return observation.model_copy(update={"is_baseline": True}) if observation else None

    def get_latest(self, source_id: str) -> Observation | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT observation_json
                FROM observations
                WHERE source_id = ?
                ORDER BY observed_at DESC, rowid DESC
                LIMIT 1
                """,
                (source_id,),
            ).fetchone()
        if not row:
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

    def list_reference_observations(self, source_id: str, limit: int = 5) -> list[Observation]:
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
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT observation_json
                FROM observations
                WHERE source_id = ?
                ORDER BY observed_at DESC, rowid DESC
                LIMIT ?
                """,
                (source_id, limit),
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
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO observation_reviews(observation_id, source_id, review_json)
                VALUES (?, ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET
                    source_id=excluded.source_id,
                    review_json=excluded.review_json
                """,
                (review.observation_id, review.source_id, review.model_dump_json()),
            )
        return review

    def get_review(self, observation_id: str) -> ObservationReview | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT review_json FROM observation_reviews WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        return ObservationReview.model_validate_json(row[0]) if row else None

    def get_notification_candidate(self, candidate_id: str) -> NotificationCandidate | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT candidate_json FROM notification_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        return NotificationCandidate.model_validate_json(row[0]) if row else None

    def list_notification_candidates(
        self,
        source_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[NotificationCandidate]:
        query = "SELECT candidate_json FROM notification_candidates"
        params: tuple[object, ...]
        if source_id is None:
            query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
            params = (limit,)
        else:
            query += " WHERE source_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?"
            params = (source_id, limit)
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [NotificationCandidate.model_validate_json(row[0]) for row in rows]

    def update_notification_candidate(
        self,
        candidate: NotificationCandidate,
    ) -> NotificationCandidate:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE notification_candidates SET candidate_json = ? WHERE id = ?",
                (candidate.model_dump_json(), candidate.id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Unknown notification candidate: {candidate.id}")
        return candidate

    def create_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO delivery_attempts(
                    id, candidate_id, source_id, adapter, attempt_number,
                    idempotency_key, created_at, attempt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.id,
                    attempt.candidate_id,
                    attempt.source_id,
                    attempt.adapter,
                    attempt.attempt_number,
                    attempt.idempotency_key,
                    attempt.created_at.isoformat(),
                    attempt.model_dump_json(),
                ),
            )
        return attempt

    def update_delivery_attempt(self, attempt: DeliveryAttempt) -> DeliveryAttempt:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE delivery_attempts SET attempt_json = ? WHERE id = ?",
                (attempt.model_dump_json(), attempt.id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Unknown delivery attempt: {attempt.id}")
        return attempt

    def get_delivery_attempt_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> DeliveryAttempt | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT attempt_json FROM delivery_attempts WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return DeliveryAttempt.model_validate_json(row[0]) if row else None

    def list_delivery_attempts(
        self,
        *,
        candidate_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[DeliveryAttempt]:
        conditions: list[str] = []
        params: list[object] = []
        if candidate_id is not None:
            conditions.append("candidate_id = ?")
            params.append(candidate_id)
        if source_id is not None:
            conditions.append("source_id = ?")
            params.append(source_id)
        query = "SELECT attempt_json FROM delivery_attempts"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, attempt_number DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [DeliveryAttempt.model_validate_json(row[0]) for row in rows]

    def promote_baseline(self, source_id: str, observation_id: str) -> Observation:
        observation = self._observation_by_id(observation_id)
        if observation is None or observation.source_id != source_id:
            raise ValueError("Observation does not belong to this source")
        if not observation.available or observation.profile is None:
            raise ValueError("Unavailable observations cannot become a baseline")
        with self.connect() as db:
            db.execute(
                "UPDATE sources SET baseline_observation_id = ? WHERE id = ?",
                (observation_id, source_id),
            )
        return observation.model_copy(update={"is_baseline": True})

    def export_debug_state(self) -> dict[str, object]:
        """Small inspectable snapshot useful during development and support."""
        return {
            "sources": [json.loads(source.model_dump_json()) for source in self.list_sources()],
            "observations": {
                source.id: [
                    json.loads(observation.model_dump_json())
                    for observation in self.list_observations(source.id)
                ]
                for source in self.list_sources()
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
