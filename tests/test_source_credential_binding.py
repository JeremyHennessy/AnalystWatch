from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from analystwatch.connection_discovery import ConnectionProvider
from analystwatch.credential_persistence import SQLiteCredentialStore
from analystwatch.credential_runtime import load_credential_keyring
from analystwatch.credential_store import MemoryCredentialStore, seal_provider_credential
from analystwatch.memory_store import MemoryStore
from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.service import MonitorService
from analystwatch.source_credentials import StoredSourceCredentialResolver
from analystwatch.storage import Storage
from analystwatch.workspace import WorkspaceStore


def _key() -> str:
    return base64.urlsafe_b64encode(bytes([47]) * 32).decode("ascii").rstrip("=")


def _configure_keyring(monkeypatch) -> None:
    monkeypatch.setenv("ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID", "active")
    monkeypatch.setenv(
        "ANALYSTWATCH_CREDENTIAL_KEYS_JSON",
        json.dumps({"active": _key()}),
    )


def _microsoft_source(credential_id: str = "microsoft-primary") -> SourceDefinition:
    return SourceDefinition(
        id="microsoft-source",
        name="Microsoft workbook",
        source_type=SourceType.MICROSOFT_EXCEL,
        location="m365://drive-1/item-1?table=Sales",
        config=MonitoringConfig(credential_id=credential_id),
    )


def _google_source(credential_id: str = "google-primary") -> SourceDefinition:
    return SourceDefinition(
        id="google-source",
        name="Google workbook",
        source_type=SourceType.GOOGLE_SHEETS,
        location="gsheets://sheet-1?range=Data%21A1%3AB2&header_row=1",
        config=MonitoringConfig(credential_id=credential_id),
    )


def _install_memory_credential(
    store: MemoryCredentialStore,
    monkeypatch,
    provider: ConnectionProvider,
    credential_id: str,
    token: str,
    *,
    expires_at: datetime | None = None,
) -> None:
    _configure_keyring(monkeypatch)
    now = datetime.now(timezone.utc)
    record = seal_provider_credential(
        load_credential_keyring(),
        credential_id=credential_id,
        workspace_id="local",
        provider=provider,
        subject_id=f"{provider.value}-subject",
        access_token=token,
        refresh_token=f"{provider.value}-refresh",
        scopes=["scope-a"],
        access_token_expires_at=expires_at or now + timedelta(hours=1),
        now=now,
    )
    store.upsert(record)


def test_source_credential_binding_rejects_unsupported_or_ambiguous_auth() -> None:
    with pytest.raises(ValidationError, match="supported only"):
        SourceDefinition(
            id="api-source",
            name="API source",
            source_type=SourceType.API,
            location="https://example.test/data",
            config=MonitoringConfig(credential_id="microsoft-primary"),
        )

    with pytest.raises(ValidationError, match="cannot both"):
        SourceDefinition(
            id="microsoft-source",
            name="Microsoft workbook",
            source_type=SourceType.MICROSOFT_EXCEL,
            location="m365://drive-1/item-1?table=Sales",
            config=MonitoringConfig(
                credential_id="microsoft-primary",
                request_header_env={"Authorization": "OLD_TOKEN_ENV"},
            ),
        )


def test_microsoft_preflight_uses_stored_oauth_credential(monkeypatch) -> None:
    credential_store = MemoryCredentialStore()
    expected_token = "microsoft-stored-token"
    _install_memory_credential(
        credential_store,
        monkeypatch,
        ConnectionProvider.MICROSOFT,
        "microsoft-primary",
        expected_token,
    )
    resolver = StoredSourceCredentialResolver(credential_store, workspace_id="local")
    service = MonitorService(MemoryStore(), source_credential_resolver=resolver)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization", ""))
        path = request.url.path
        if path.endswith("/items/item-1"):
            return httpx.Response(
                200,
                json={
                    "id": "item-1",
                    "name": "Book.xlsx",
                    "eTag": "etag-1",
                    "lastModifiedDateTime": "2026-08-27T12:00:00Z",
                    "webUrl": "https://example.test/book",
                },
            )
        if path.endswith("/tables/Sales/columns"):
            return httpx.Response(
                200,
                json={"value": [{"name": "id", "index": 0}, {"name": "amount", "index": 1}]},
            )
        if path.endswith("/tables/Sales/rows"):
            return httpx.Response(200, json={"value": [{"values": [["1", 10.0]]}]})
        raise AssertionError(f"Unexpected Microsoft Graph request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = service.preflight_source(_microsoft_source(), client=client)

    assert result.ready is True
    assert result.available is True
    assert result.profile is not None and result.profile.row_count == 1
    assert seen and set(seen) == {f"Bearer {expected_token}"}
    assert expected_token not in result.model_dump_json()


def test_google_scheduled_check_uses_stored_oauth_credential(monkeypatch) -> None:
    credential_store = MemoryCredentialStore()
    expected_token = "google-stored-token"
    _install_memory_credential(
        credential_store,
        monkeypatch,
        ConnectionProvider.GOOGLE,
        "google-primary",
        expected_token,
    )
    resolver = StoredSourceCredentialResolver(credential_store, workspace_id="local")
    service = MonitorService(MemoryStore(), source_credential_resolver=resolver)
    source = _google_source()
    service.add_source(source)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization", ""))
        return httpx.Response(
            200,
            json={"values": [["id", "amount"], ["1", 10.0]]},
            headers={"ETag": "google-etag"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        observation = service.check_source(source.id, client=client)

    assert observation.available is True
    assert observation.health.value == "Healthy"
    assert seen == [f"Bearer {expected_token}"]
    assert expected_token not in observation.model_dump_json()


def test_missing_and_expired_stored_credentials_fail_closed_without_network(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANALYSTWATCH_GOOGLE_AUTHORIZATION", "Bearer environment-fallback")
    credential_store = MemoryCredentialStore()
    resolver = StoredSourceCredentialResolver(credential_store, workspace_id="local")
    service = MonitorService(MemoryStore(), source_credential_resolver=resolver)
    missing = _google_source("missing-credential")
    service.add_source(missing)
    calls = 0

    def forbidden(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError(f"Network must not run when credential resolution fails: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        missing_observation = service.check_source(missing.id, client=client)

    assert missing_observation.available is False
    assert missing_observation.health.value == "Critical"
    assert "not connected" in (missing_observation.error or "").lower()
    assert "environment-fallback" not in missing_observation.model_dump_json()
    assert calls == 0

    _install_memory_credential(
        credential_store,
        monkeypatch,
        ConnectionProvider.GOOGLE,
        "expired-google",
        "expired-token",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    expired = _google_source("expired-google").model_copy(update={"id": "expired-google-source"})
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        result = service.preflight_source(expired, client=client)

    assert result.ready is False
    assert result.available is False
    assert "expired" in result.issues[0].message.lower()
    assert "expired-token" not in result.model_dump_json()
    assert calls == 0


def test_default_legacy_runtime_resolver_uses_existing_oauth_sidecar(
    tmp_path,
    monkeypatch,
) -> None:
    _configure_keyring(monkeypatch)
    database_path = tmp_path / "analystwatch.db"
    workspace_storage = WorkspaceStore(Storage(database_path), "local")
    service = MonitorService(workspace_storage)
    sidecar = SQLiteCredentialStore(
        database_path.with_suffix(database_path.suffix + ".credentials.db")
    )
    sidecar.initialize()
    now = datetime.now(timezone.utc)
    sidecar.upsert(
        seal_provider_credential(
            load_credential_keyring(),
            credential_id="google-primary",
            workspace_id="local",
            provider=ConnectionProvider.GOOGLE,
            subject_id="google-subject",
            access_token="sidecar-token",
            refresh_token="sidecar-refresh",
            scopes=["scope-a"],
            access_token_expires_at=now + timedelta(hours=1),
            now=now,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sidecar-token"
        return httpx.Response(200, json={"values": [["id"], ["1"]]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = service.preflight_source(_google_source(), client=client)

    assert result.ready is True
    assert result.available is True
