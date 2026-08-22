from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .microsoft_excel import read_microsoft_excel_table
from .models import SourceDefinition, SourceType


@dataclass
class IngestionResult:
    available: bool
    dataframe: pd.DataFrame | None = None
    http_status: int | None = None
    response_ms: float | None = None
    source_modified_at: datetime | None = None
    response_etag: str | None = None
    error: str | None = None


def _extract_path(payload: Any, record_path: str | None) -> Any:
    current = payload
    if record_path:
        for part in record_path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"JSON record path '{record_path}' was not found")
            current = current[part]
    return current


def _json_to_frame(payload: Any, record_path: str | None = None) -> pd.DataFrame:
    payload = _extract_path(payload, record_path)
    if isinstance(payload, list):
        if not payload:
            return pd.DataFrame()
        if not all(isinstance(item, dict) for item in payload):
            raise ValueError("JSON arrays must contain objects in v0.1")
        return pd.json_normalize(payload)
    if isinstance(payload, dict):
        for key in ("records", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list) and all(isinstance(item, dict) for item in candidate):
                return pd.json_normalize(candidate)
        if all(not isinstance(value, (dict, list)) for value in payload.values()):
            return pd.DataFrame([payload])
    raise ValueError(
        "Unsupported JSON shape; use an array of objects, a flat object, "
        "a records/data array, or configure json_record_path"
    )


def _request_headers(source: SourceDefinition) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header, env_name in source.config.request_header_env.items():
        value = os.environ.get(env_name)
        if value is None:
            raise ValueError(
                f"Missing environment variable '{env_name}' for request header '{header}'."
            )
        headers[header] = value
    return headers


def ingest_source(
    source: SourceDefinition,
    *,
    client: httpx.Client | None = None,
) -> IngestionResult:
    try:
        if source.source_type == SourceType.API:
            return _ingest_api(source, client=client)
        if source.source_type == SourceType.MICROSOFT_EXCEL:
            result = read_microsoft_excel_table(
                source.location,
                headers=_request_headers(source),
                timeout_seconds=source.config.request_timeout_seconds,
                client=client,
            )
            return IngestionResult(
                available=result.available,
                dataframe=result.dataframe,
                http_status=result.http_status,
                response_ms=result.response_ms,
                source_modified_at=result.source_modified_at,
                response_etag=result.response_etag,
                error=result.error,
            )

        path = Path(source.location)
        if not path.exists() or not path.is_file():
            return IngestionResult(available=False, error=f"File does not exist: {path}")
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

        if source.source_type == SourceType.CSV:
            frame = pd.read_csv(path)
        elif source.source_type == SourceType.XLSX:
            sheet = source.config.sheet_name if source.config.sheet_name is not None else 0
            frame = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
        elif source.source_type == SourceType.JSON:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            frame = _json_to_frame(payload, source.config.json_record_path)
        else:  # pragma: no cover - enum guards this branch
            raise ValueError(f"Unsupported source type: {source.source_type}")

        return IngestionResult(
            available=True,
            dataframe=frame,
            source_modified_at=modified,
        )
    except Exception as exc:  # ingestion must return evidence, not crash the monitor
        return IngestionResult(available=False, error=f"{type(exc).__name__}: {exc}")


def _ingest_api(
    source: SourceDefinition,
    *,
    client: httpx.Client | None,
) -> IngestionResult:
    owns_client = client is None
    active_client = client or httpx.Client(timeout=source.config.request_timeout_seconds)
    start = time.perf_counter()
    try:
        response = active_client.get(source.location, headers=_request_headers(source))
        elapsed_ms = (time.perf_counter() - start) * 1000
        if response.status_code < 200 or response.status_code >= 300:
            return IngestionResult(
                available=False,
                http_status=response.status_code,
                response_ms=elapsed_ms,
                error=f"HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            return IngestionResult(
                available=False,
                http_status=response.status_code,
                response_ms=elapsed_ms,
                error=f"Response was not usable JSON: {exc}",
            )
        frame = _json_to_frame(payload, source.config.json_record_path)
        modified = None
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            try:
                modified = parsedate_to_datetime(last_modified)
                if modified.tzinfo is None:
                    modified = modified.replace(tzinfo=timezone.utc)
                else:
                    modified = modified.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                modified = None
        return IngestionResult(
            available=True,
            dataframe=frame,
            http_status=response.status_code,
            response_ms=elapsed_ms,
            source_modified_at=modified,
            response_etag=response.headers.get("ETag"),
        )
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return IngestionResult(
            available=False,
            response_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if owns_client:
            active_client.close()
