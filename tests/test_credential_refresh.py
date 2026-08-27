from __future__ import annotations

import base64
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest

from analystwatch.credential_crypto import CredentialKeyring
from analystwatch.credential_persistence import PostgresCredentialStore, SQLiteCredentialStore
from analystwatch.credential_refresh import (
    OAuthCredentialRefreshError,
    refresh_provider_credential_if_expired,
)
from analystwatch.credential_runtime import load_credential_keyring
from analystwatch.credential_store import (
    MemoryCredentialStore,
    seal_provider_credential,
    unseal_access_token,
    unseal_refresh_token,
)
from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.oauth_provider_config import load_oauth_provider_config
from analystwatch.source_credentials import StoredSourceCredentialResolver

NOW = datetime(2026, 8, 27, 18, 30, tzinfo=timezone.utc)


def environment() -> dict[str, str]:
    return {
        "ANALYSTWATCH_PUBLIC_BASE_URL": "https://analystwatch.example",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID": "microsoft-client",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET": "microsoft-secret",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
    }


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"key-1": bytes([71]) * 32}, active_key_id="key-1")


def expired_record(
    *,
    provider: str,
    workspace_id: str = "workspace-a",
    credential_id: str = "primary",
    subject_id: str = "subject-1",
    access_token: str = "old-access",
    refresh_token: str | None = "old-refresh",
):
    config = load_oauth_provider_config(provider, environment())
    return seal_provider_credential(
        keyring(),
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
        subject_id=subject_id,
        access_token=access_token,
        refresh_token=refresh_token,
        scopes=config.public.scopes,
        access_token_expires_at=NOW - timedelta(minutes=1),
        display_name="Original User",
        email="original@example.com",
        now=NOW - timedelta(hours=2),
    )


def test_microsoft_refresh_rotates_access_and_refresh_tokens() -> None:
    store = MemoryCredentialStore()
    original = expired_record(provider="microsoft")
    store.upsert(original)
    config = load_oauth_provider_config("microsoft", environment())
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            captured["token_data"] = parse_qs(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "User.Read Files.Read.All offline_access",
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                },
            )
        if request.url.host == "graph.microsoft.com":
            assert request.headers["Authorization"] == "Bearer new-access"
            return httpx.Response(
                200,
                json={
                    "id": "subject-1",
                    "displayName": "Refreshed User",
                    "mail": "refreshed@example.com",
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        refreshed = refresh_provider_credential_if_expired(
            store,
            keyring(),
            config,
            workspace_id="workspace-a",
            credential_id="primary",
            now=NOW,
            client=client,
        )

    assert captured["token_data"] == {
        "client_id": ["microsoft-client"],
        "client_secret": ["microsoft-secret"],
        "grant_type": ["refresh_token"],
        "refresh_token": ["old-refresh"],
    }
    assert refreshed.created_at == original.created_at
    assert refreshed.updated_at == NOW
    assert refreshed.access_token_expires_at == NOW + timedelta(hours=1)
    assert unseal_access_token(refreshed, keyring()) == "new-access"
    assert unseal_refresh_token(refreshed, keyring()) == "new-refresh"
    assert refreshed.display_name == "Refreshed User"
    assert refreshed.email == "refreshed@example.com"
    serialized = refreshed.model_dump_json()
    assert "new-access" not in serialized
    assert "new-refresh" not in serialized


def test_google_refresh_preserves_existing_refresh_token_when_response_omits_one() -> None:
    store = MemoryCredentialStore()
    store.upsert(expired_record(provider="google"))
    config = load_oauth_provider_config("google", environment())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            assert parse_qs(request.content.decode("utf-8")) == {
                "client_id": ["google-client"],
                "client_secret": ["google-secret"],
                "grant_type": ["refresh_token"],
                "refresh_token": ["old-refresh"],
            }
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "openid email https://www.googleapis.com/auth/spreadsheets.readonly",
                    "access_token": "google-new-access",
                },
            )
        if request.url.host == "www.googleapis.com":
            assert request.headers["Authorization"] == "Bearer google-new-access"
            return httpx.Response(
                200,
                json={
                    "user": {
                        "permissionId": "subject-1",
                        "displayName": "Google User",
                        "emailAddress": "google@example.com",
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        refreshed = refresh_provider_credential_if_expired(
            store,
            keyring(),
            config,
            workspace_id="workspace-a",
            credential_id="primary",
            now=NOW,
            client=client,
        )

    assert unseal_access_token(refreshed, keyring()) == "google-new-access"
    assert unseal_refresh_token(refreshed, keyring()) == "old-refresh"


def test_refresh_account_mismatch_and_provider_rejection_leave_record_unchanged() -> None:
    store = MemoryCredentialStore()
    original = expired_record(provider="microsoft")
    store.upsert(original)
    config = load_oauth_provider_config("microsoft", environment())

    def mismatch(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "access_token": "different-account-access",
                    "refresh_token": "different-account-refresh",
                },
            )
        return httpx.Response(200, json={"id": "other-subject", "displayName": "Other"})

    with httpx.Client(transport=httpx.MockTransport(mismatch)) as client:
        with pytest.raises(OAuthCredentialRefreshError, match="different provider account"):
            refresh_provider_credential_if_expired(
                store,
                keyring(),
                config,
                workspace_id="workspace-a",
                credential_id="primary",
                now=NOW,
                client=client,
            )

    unchanged = store.get("workspace-a", "primary")
    assert unchanged == original

    provider_body_secret = "provider-secret-invalid-grant"

    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=provider_body_secret)

    with httpx.Client(transport=httpx.MockTransport(rejected)) as client:
        with pytest.raises(OAuthCredentialRefreshError, match="HTTP 400") as exc:
            refresh_provider_credential_if_expired(
                store,
                keyring(),
                config,
                workspace_id="workspace-a",
                credential_id="primary",
                now=NOW,
                client=client,
            )
    assert provider_body_secret not in str(exc.value)
    assert store.get("workspace-a", "primary") == original


def test_missing_refresh_token_requires_reconnect_without_network() -> None:
    store = MemoryCredentialStore()
    store.upsert(expired_record(provider="google", refresh_token=None))
    config = load_oauth_provider_config("google", environment())
    calls = 0

    def forbidden(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("Refresh without a refresh token must not call the provider")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(OAuthCredentialRefreshError, match="no refresh token"):
            refresh_provider_credential_if_expired(
                store,
                keyring(),
                config,
                workspace_id="workspace-a",
                credential_id="primary",
                now=NOW,
                client=client,
            )
    assert calls == 0


def test_sqlite_concurrent_refresh_is_serialized(tmp_path) -> None:
    store = SQLiteCredentialStore(tmp_path / "credentials.db")
    store.initialize()
    store.upsert(expired_record(provider="microsoft"))
    config = load_oauth_provider_config("microsoft", environment())
    token_calls = 0
    calls_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.host == "login.microsoftonline.com":
            with calls_lock:
                token_calls += 1
            time.sleep(0.15)
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "access_token": "sqlite-access",
                    "refresh_token": "sqlite-refresh",
                },
            )
        return httpx.Response(200, json={"id": "subject-1", "displayName": "User"})

    def worker():
        barrier.wait()
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return refresh_provider_credential_if_expired(
                store,
                keyring(),
                config,
                workspace_id="workspace-a",
                credential_id="primary",
                now=NOW,
                client=client,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(worker)
        second = executor.submit(worker)
        records = [first.result(), second.result()]

    assert token_calls == 1
    assert {unseal_access_token(item, keyring()) for item in records} == {"sqlite-access"}
    stored = store.get("workspace-a", "primary")
    assert stored is not None
    assert unseal_refresh_token(stored, keyring()) == "sqlite-refresh"


def test_postgres_concurrent_refresh_is_serialized() -> None:
    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    workspace_id = f"refresh-{uuid4().hex[:10]}"
    store = PostgresCredentialStore(dsn)
    store.initialize()
    store.upsert(expired_record(provider="microsoft", workspace_id=workspace_id))
    config = load_oauth_provider_config("microsoft", environment())
    token_calls = 0
    calls_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.host == "login.microsoftonline.com":
            with calls_lock:
                token_calls += 1
            time.sleep(0.15)
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "access_token": "postgres-access",
                    "refresh_token": "postgres-refresh",
                },
            )
        return httpx.Response(200, json={"id": "subject-1", "displayName": "User"})

    def worker():
        barrier.wait()
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return refresh_provider_credential_if_expired(
                store,
                keyring(),
                config,
                workspace_id=workspace_id,
                credential_id="primary",
                now=NOW,
                client=client,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(worker)
        second = executor.submit(worker)
        records = [first.result(), second.result()]

    assert token_calls == 1
    assert {unseal_access_token(item, keyring()) for item in records} == {"postgres-access"}


def test_source_resolver_refreshes_expired_google_credential_once(monkeypatch) -> None:
    for name, value in environment().items():
        monkeypatch.setenv(name, value)
    encoded_key = base64.urlsafe_b64encode(bytes([72]) * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID", "active")
    monkeypatch.setenv("ANALYSTWATCH_CREDENTIAL_KEYS_JSON", json.dumps({"active": encoded_key}))
    runtime_keyring = load_credential_keyring()
    config = load_oauth_provider_config("google")
    store = MemoryCredentialStore()
    store.upsert(
        seal_provider_credential(
            runtime_keyring,
            credential_id="google-primary",
            workspace_id="local",
            provider="google",
            subject_id="subject-1",
            access_token="expired-access",
            refresh_token="stored-refresh",
            scopes=config.public.scopes,
            access_token_expires_at=NOW - timedelta(seconds=1),
            now=NOW - timedelta(hours=1),
        )
    )
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.host == "oauth2.googleapis.com":
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "access_token": "resolver-new-access",
                },
            )
        return httpx.Response(
            200,
            json={"user": {"permissionId": "subject-1", "displayName": "Google User"}},
        )

    source = SourceDefinition(
        id="google-source",
        name="Google workbook",
        source_type=SourceType.GOOGLE_SHEETS,
        location="gsheets://sheet-1?range=Data%21A1%3AB2&header_row=1",
        config=MonitoringConfig(credential_id="google-primary"),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resolver = StoredSourceCredentialResolver(
            store,
            workspace_id="local",
            refresh_client=client,
            now_factory=lambda: NOW,
        )
        first = resolver.resolve(source)
        second = resolver.resolve(source)

    assert first == {"Authorization": "Bearer resolver-new-access"}
    assert second == first
    assert token_calls == 1
