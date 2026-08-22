from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .models import StorageVerification
from .namespaced_storage import NAMESPACED_STORAGE_SCHEMA_VERSION, NamespacedStorage
from .postgres_storage import PostgresStorage
from .storage import STORAGE_SCHEMA_VERSION, Storage
from .store import MonitoringStore
from .workspace import WorkspaceStore, validate_workspace_id

StorageBackend = Literal["legacy", "namespaced", "postgres"]
DEFAULT_STORAGE_BACKEND: StorageBackend = "legacy"
SUPPORTED_STORAGE_BACKENDS: tuple[StorageBackend, ...] = (
    "legacy",
    "namespaced",
    "postgres",
)


@dataclass(frozen=True)
class RuntimeStorage:
    backend: StorageBackend
    raw_storage: Storage | NamespacedStorage | PostgresStorage
    monitoring_store: MonitoringStore


def normalize_storage_backend(value: str) -> StorageBackend:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_STORAGE_BACKENDS:
        raise ValueError(
            f"storage backend must be one of: {', '.join(SUPPORTED_STORAGE_BACKENDS)}"
        )
    return normalized  # type: ignore[return-value]


def _expected_file_schema(backend: StorageBackend) -> int:
    if backend == "legacy":
        return STORAGE_SCHEMA_VERSION
    if backend == "namespaced":
        return NAMESPACED_STORAGE_SCHEMA_VERSION
    raise ValueError("PostgreSQL does not use the SQLite file schema selector")


def inspect_existing_database(path: str | Path) -> StorageVerification | None:
    database_path = Path(path)
    if not database_path.exists():
        return None
    verification = Storage.verify_database(database_path)
    if not verification.integrity_ok:
        raise ValueError(
            f"Existing database failed read-only integrity verification: "
            f"{verification.integrity_message}"
        )
    if verification.schema_version is None:
        raise ValueError("Existing database has no AnalystWatch schema metadata")
    return verification


def _require_postgres_dsn(postgres_dsn: str | None) -> str:
    if postgres_dsn is None or not postgres_dsn.strip():
        raise ValueError(
            "PostgreSQL backend requires ANALYSTWATCH_POSTGRES_DSN or --postgres-dsn"
        )
    if postgres_dsn != postgres_dsn.strip():
        raise ValueError("PostgreSQL DSN must be trimmed")
    return postgres_dsn


def verify_runtime_database(
    path: str | Path,
    backend: str = DEFAULT_STORAGE_BACKEND,
    *,
    postgres_dsn: str | None = None,
) -> StorageVerification:
    selected = normalize_storage_backend(backend)
    if selected == "postgres":
        verification = PostgresStorage.verify_dsn(_require_postgres_dsn(postgres_dsn))
        if not verification.integrity_ok:
            raise ValueError(verification.integrity_message)
        return verification

    verification = inspect_existing_database(path)
    if verification is None:
        raise FileNotFoundError(Path(path))
    expected = _expected_file_schema(selected)
    if verification.schema_version != expected:
        raise ValueError(
            f"Selected backend {selected!r} requires schema version {expected}, "
            f"but database reports schema version {verification.schema_version}"
        )
    return verification


def create_runtime_storage(
    path: str | Path,
    workspace_id: str,
    backend: str = DEFAULT_STORAGE_BACKEND,
    *,
    postgres_dsn: str | None = None,
) -> RuntimeStorage:
    selected = normalize_storage_backend(backend)
    workspace = validate_workspace_id(workspace_id)

    if selected == "postgres":
        raw_storage = PostgresStorage(_require_postgres_dsn(postgres_dsn), workspace)
        monitoring_store: MonitoringStore = raw_storage
        return RuntimeStorage(
            backend=selected,
            raw_storage=raw_storage,
            monitoring_store=monitoring_store,
        )

    verification = inspect_existing_database(path)
    if verification is not None:
        expected = _expected_file_schema(selected)
        if verification.schema_version != expected:
            raise ValueError(
                f"Selected backend {selected!r} requires schema version {expected}, "
                f"but database reports schema version {verification.schema_version}"
            )

    if selected == "legacy":
        raw_storage = Storage(path)
        monitoring_store = WorkspaceStore(raw_storage, workspace)
    else:
        raw_storage = NamespacedStorage(path, workspace)
        monitoring_store = raw_storage

    return RuntimeStorage(
        backend=selected,
        raw_storage=raw_storage,
        monitoring_store=monitoring_store,
    )
