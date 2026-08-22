from __future__ import annotations

from typing import Any

from .memory_store import MemoryStore
from .models import Observation
from .namespaced_storage import NamespacedStorage
from .postgres_storage import POSTGRES_SCHEMA, PostgresStorage
from .row_diff import strip_row_diff_raw_payloads
from .storage import Storage


def _needs_pruning(observation: Observation) -> bool:
    if observation.row_snapshot is not None:
        return True
    if observation.row_diff is None:
        return False
    for comparison in (observation.row_diff.previous, observation.row_diff.baseline):
        if comparison is None:
            continue
        if comparison.added_samples or comparison.removed_samples or comparison.changed_samples:
            return True
    return False


def _prune_legacy_sqlite(
    storage: Storage,
    source_id: str,
    keep_observation_ids: set[str],
) -> None:
    with storage.connect() as db:
        rows = db.execute(
            "SELECT id, observation_json FROM observations WHERE source_id = ?",
            (source_id,),
        ).fetchall()
        for row in rows:
            observation_id = str(row["id"])
            if observation_id in keep_observation_ids:
                continue
            observation = Observation.model_validate_json(row["observation_json"])
            if not _needs_pruning(observation):
                continue
            stripped = strip_row_diff_raw_payloads(observation)
            db.execute(
                "UPDATE observations SET observation_json = ? WHERE id = ?",
                (stripped.model_dump_json(), observation_id),
            )


def _prune_namespaced_sqlite(
    storage: NamespacedStorage,
    source_id: str,
    keep_observation_ids: set[str],
) -> None:
    if storage.get_source(source_id) is None:
        raise KeyError(f"Unknown source in workspace {storage.workspace_id}: {source_id}")
    with storage.connect() as db:
        rows = db.execute(
            """
            SELECT id, observation_json
            FROM observations
            WHERE workspace_id = ? AND source_id = ?
            """,
            (storage.workspace_id, source_id),
        ).fetchall()
        for row in rows:
            observation_id = str(row["id"])
            if observation_id in keep_observation_ids:
                continue
            observation = Observation.model_validate_json(row["observation_json"])
            if not _needs_pruning(observation):
                continue
            stripped = strip_row_diff_raw_payloads(observation)
            db.execute(
                """
                UPDATE observations
                SET observation_json = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (stripped.model_dump_json(), storage.workspace_id, observation_id),
            )


def _prune_postgres(
    storage: PostgresStorage,
    source_id: str,
    keep_observation_ids: set[str],
) -> None:
    if storage.get_source(source_id) is None:
        raise KeyError(f"Unknown source in workspace {storage.workspace_id}: {source_id}")
    with storage.connect() as db:
        rows = db.execute(
            f"""
            SELECT id, observation_json
            FROM {POSTGRES_SCHEMA}.observations
            WHERE workspace_id = %s AND source_id = %s
            """,
            (storage.workspace_id, source_id),
        ).fetchall()
        for row in rows:
            observation_id = str(row["id"])
            if observation_id in keep_observation_ids:
                continue
            observation = Observation.model_validate_json(row["observation_json"])
            if not _needs_pruning(observation):
                continue
            stripped = strip_row_diff_raw_payloads(observation)
            db.execute(
                f"""
                UPDATE {POSTGRES_SCHEMA}.observations
                SET observation_json = %s
                WHERE workspace_id = %s AND id = %s
                """,
                (stripped.model_dump_json(), storage.workspace_id, observation_id),
            )


def prune_row_diff_payloads(
    storage: Any,
    source_id: str,
    keep_observation_ids: set[str],
) -> None:
    """Strip retained row values outside the configured comparison window.

    Row-diff evidence is a feature-specific persistence concern rather than part
    of the general MonitoringStore protocol. This helper supports every store
    used by AnalystWatch without changing their database schemas.
    """

    delegate = getattr(storage, "delegate", None)
    if delegate is not None:
        if storage.get_source(source_id) is None:
            workspace_id = getattr(storage, "workspace_id", "unknown")
            raise KeyError(f"Unknown source in workspace {workspace_id}: {source_id}")
        prune_row_diff_payloads(delegate, source_id, keep_observation_ids)
        return
    if isinstance(storage, MemoryStore):
        storage.prune_row_diff_payloads(source_id, keep_observation_ids)
        return
    if isinstance(storage, NamespacedStorage):
        _prune_namespaced_sqlite(storage, source_id, keep_observation_ids)
        return
    if isinstance(storage, PostgresStorage):
        _prune_postgres(storage, source_id, keep_observation_ids)
        return
    if isinstance(storage, Storage):
        _prune_legacy_sqlite(storage, source_id, keep_observation_ids)
        return
    raise TypeError(f"Unsupported row-diff retention store: {type(storage).__name__}")
