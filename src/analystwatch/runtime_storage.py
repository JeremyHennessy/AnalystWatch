from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .models import StorageVerification
from .namespaced_storage import NAMESPACED_STORAGE_SCHEMA_VERSION, NamespacedStorage
from .storage import STORAGE_SCHEMA_VERSION, Storage
from .store import MonitoringStore
from .workspace import WorkspaceStore, validate_workspace_id

StorageBackend = Literal["legacy", "namespaced"]
DEFAULT_STORAGE_BACKEND: StorageBackend = "legacy"
SUPPORTED_STORAGE_BACKENDS: tuple[StorageBackend, ...] = ("legacy", "namespaced")


@dataclass(frozen=True)
class RuntimeStorage:
    backend: StorageBackend
    raw_storage: Storage | NamespacedStorage
    monitoring_store: MonitoringStore


def normalize_storage_backend(value: str) -> StorageBackend:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_STORAGE_BACKENDS:
        raise ValueError(
            f"storage backend must be one of: {', '.join(SUPPORTED_STORAGE_BACKENDS)}"
        )
    return normalized  # type: ignore[return-value]


def _expected_schema(backend: StorageBackend) -> int:
    return (
        STORAGE_SCHEMA_VERSION
        if backend == "legacy"
        else NAMESPACED_STORAGE_SCHEMA_VERSION
    )


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


def verify_runtime_database(
    path: str | Path,
    backend: str = DEFAULT_STORAGE_BACKEND,
) -> StorageVerification:
    selected = normalize_storage_backend(backend)
    verification = inspect_existing_database(path)
    if verification is None:
        raise FileNotFoundError(Path(path))
    expected = _expected_schema(selected)
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
) -> RuntimeStorage:
    selected = normalize_storage_backend(backend)
    workspace = validate_workspace_id(workspace_id)
    verification = inspect_existing_database(path)
    if verification is not None:
        expected = _expected_schema(selected)
        if verification.schema_version != expected:
            raise ValueError(
                f"Selected backend {selected!r} requires schema version {expected}, "
                f"but database reports schema version {verification.schema_version}"
            )

    if selected == "legacy":
        raw_storage = Storage(path)
        monitoring_store: MonitoringStore = WorkspaceStore(raw_storage, workspace)
    else:
        raw_storage = NamespacedStorage(path, workspace)
        monitoring_store = raw_storage

    return RuntimeStorage(
        backend=selected,
        raw_storage=raw_storage,
        monitoring_store=monitoring_store,
    )
