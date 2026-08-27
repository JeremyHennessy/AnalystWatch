from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from analystwatch.auth import SignedSessionAuthenticator, WorkspaceMembership, WorkspaceRole
from analystwatch.auth_storage import SQLiteMembershipStore
from analystwatch.credential_crypto import CredentialKeyring
from analystwatch.credential_persistence import PostgresCredentialStore, SQLiteCredentialStore
from analystwatch.credential_store import (
    MemoryCredentialStore,
    seal_provider_credential,
    unseal_access_token,
    unseal_refresh_token,
)
from analystwatch.oauth_authorization import (
    OAuthAuthorizationError,
    _authorization_associated_data,
    begin_authorization_transaction,
    consume_authorization_transaction,
)
from analystwatch.oauth_authorization_store import MemoryOAuthAuthorizationStore
from analystwatch.oauth_callback import OAuthCallbackError, complete_oauth_authorization
from analystwatch.oauth_provider_config import load_oauth_provider_config
from analystwatch.oauth_start import begin_persisted_oauth_authorization
from analystwatch.web import create_app

NOW = datetime(2026, 8, 27, 20, 0, tzinfo=timezone.utc)
AUTH_SECRET = "analystwatch-reconnect-test-auth-secret-32-bytes"


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"active": bytes([81]) * 32}, active_key_id="active")


def oauth_environment() -> dict[str, str]:
    return {
        "ANALYSTWATCH_PUBLIC_BASE_URL": "https://analystwatch.example",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID": "microsoft-client",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET": "microsoft-secret",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
    }


def _existing_record(
    *,
    provider: str = "microsoft",
    workspace_id: str = "team-a",
    credential_id: str = "primary",
    subject_id: str = "subject-1",
):
    config = load_oauth_provider_config(provider, oauth_environment())
    return seal_provider_credential(
        keyring(),
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
        subject_id=subject_id,
        display_name="Original User",
        email="original@example.com",
        access_token="old-access",
        refresh_token="old-refresh",
        scopes=config.public.scopes,
        access_token_expires_at=NOW + timedelta(minutes=5),
        now=NOW,
    )


def _reconnect_transaction(provider: str = "microsoft", credential_id: str = "primary"):
    started = begin_authorization_transaction(
        keyring(),
        workspace_id="team-a",
        user_id="admin",
        provider=provider,
        credential_id=credential_id,
        now=NOW + timedelta(minutes=1),
        operation="reconnect",
    )
    store = MemoryOAuthAuthorizationStore()
    store.initialize()
    store.create(started.transaction)
    return store, started


def test_v2_operation_is_authenticated_and_legacy_v1_connect_still_consumes() -> None:
    reconnect = begin_authorization_transaction(
        keyring(),
        workspace_id="team-a",
        user_id="admin",
        provider="microsoft",
        credential_id="primary",
        now=NOW,
        operation="reconnect",
    )
    assert reconnect.transaction.operation == "reconnect"
    assert reconnect.transaction.aad_version == 2

    tampered = reconnect.transaction.model_copy(update={"operation": "connect"}, deep=True)
    with pytest.raises(OAuthAuthorizationError, match="could not be authenticated"):
        consume_authorization_transaction(
            tampered,
            keyring(),
            state=reconnect.state,
            now=NOW + timedelta(minutes=1),
        )

    connected = begin_authorization_transaction(
        keyring(),
        workspace_id="team-a",
        user_id="operator",
        provider="google",
        credential_id="google-primary",
        now=NOW,
    )
    recovered = consume_authorization_transaction(
        connected.transaction,
        keyring(),
        state=connected.state,
        now=NOW + timedelta(seconds=1),
    ).pkce_verifier
    legacy_aad = _authorization_associated_data(
        workspace_id=connected.transaction.workspace_id,
        user_id=connected.transaction.user_id,
        provider=connected.transaction.provider,
        credential_id=connected.transaction.credential_id,
        transaction_id=connected.transaction.transaction_id,
        operation="connect",
        aad_version=1,
    )
    legacy_envelope = keyring().encrypt(recovered.encode("ascii"), associated_data=legacy_aad)
    legacy = connected.transaction.model_copy(
        update={
            "operation": "connect",
            "aad_version": 1,
            "pkce_verifier": legacy_envelope,
        },
        deep=True,
    )
    consumed_legacy = consume_authorization_transaction(
        legacy,
        keyring(),
        state=connected.state,
        now=NOW + timedelta(minutes=1),
    )
    assert consumed_legacy.pkce_verifier == recovered

    invalid_legacy_reconnect = legacy.model_copy(update={"operation": "reconnect"}, deep=True)
    with pytest.raises(OAuthAuthorizationError, match="metadata is invalid"):
        consume_authorization_transaction(
            invalid_legacy_reconnect,
            keyring(),
            state=connected.state,
            now=NOW + timedelta(minutes=1),
        )


def test_reconnect_authorization_explicitly_prompts_for_provider_consent() -> None:
    for provider in ("microsoft", "google"):
        store = MemoryOAuthAuthorizationStore()
        store.initialize()
        config = load_oauth_provider_config(provider, oauth_environment())
        url = begin_persisted_oauth_authorization(
            store,
            keyring(),
            config,
            workspace_id="team-a",
            user_id="admin",
            credential_id=f"{provider}-primary",
            now=NOW,
            operation="reconnect",
        )
        query = parse_qs(urlsplit(url).query)
        assert query["prompt"] == ["consent"]


def _same_account_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        return httpx.Response(
            200,
            json={
                "token_type": "Bearer",
                "scope": "User.Read Files.Read.All offline_access",
                "expires_in": 3600,
                "access_token": "new-access",
                "refresh_token": "new-refresh",
            },
        )
    return httpx.Response(
        200,
        json={
            "id": "subject-1",
            "displayName": "Reconnected User",
            "mail": "new@example.com",
        },
    )


def _assert_same_account_reconnect(store) -> None:
    original = _existing_record()
    store.initialize()
    store.upsert(original)
    authorization_store, started = _reconnect_transaction()
    config = load_oauth_provider_config("microsoft", oauth_environment())

    with httpx.Client(transport=httpx.MockTransport(_same_account_handler)) as client:
        replacement = complete_oauth_authorization(
            authorization_store,
            store,
            keyring(),
            config,
            provider="microsoft",
            workspace_id="team-a",
            state=started.state,
            code="provider-code",
            now=NOW + timedelta(minutes=2),
            client=client,
        )

    assert replacement.created_at == original.created_at
    assert replacement.updated_at == NOW + timedelta(minutes=2)
    assert replacement.subject_id == original.subject_id
    assert replacement.display_name == "Reconnected User"
    assert replacement.email == "new@example.com"
    assert unseal_access_token(replacement, keyring()) == "new-access"
    assert unseal_refresh_token(replacement, keyring()) == "new-refresh"
    persisted = store.get("team-a", "primary")
    assert persisted == replacement


def test_same_account_reconnect_replaces_memory_and_sqlite_credentials(tmp_path: Path) -> None:
    _assert_same_account_reconnect(MemoryCredentialStore())
    _assert_same_account_reconnect(SQLiteCredentialStore(tmp_path / "credentials.db"))


def test_same_account_reconnect_replaces_postgres_credential() -> None:
    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    workspace_id = f"reconnect-{uuid4().hex[:10]}"
    store = PostgresCredentialStore(dsn)
    store.initialize()
    original = _existing_record(workspace_id=workspace_id)
    store.upsert(original)
    started = begin_authorization_transaction(
        keyring(),
        workspace_id=workspace_id,
        user_id="admin",
        provider="microsoft",
        credential_id="primary",
        now=NOW + timedelta(minutes=1),
        operation="reconnect",
    )
    authorization_store = MemoryOAuthAuthorizationStore()
    authorization_store.initialize()
    authorization_store.create(started.transaction)
    config = load_oauth_provider_config("microsoft", oauth_environment())

    with httpx.Client(transport=httpx.MockTransport(_same_account_handler)) as client:
        replacement = complete_oauth_authorization(
            authorization_store,
            store,
            keyring(),
            config,
            provider="microsoft",
            workspace_id=workspace_id,
            state=started.state,
            code="provider-code",
            now=NOW + timedelta(minutes=2),
            client=client,
        )

    assert replacement.created_at == original.created_at
    assert replacement.subject_id == original.subject_id
    assert unseal_access_token(replacement, keyring()) == "new-access"


def test_different_account_reconnect_is_rejected_without_replacing_credential() -> None:
    store = MemoryCredentialStore()
    original = _existing_record()
    store.upsert(original)
    authorization_store, started = _reconnect_transaction()
    config = load_oauth_provider_config("microsoft", oauth_environment())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "access_token": "other-access",
                    "refresh_token": "other-refresh",
                },
            )
        return httpx.Response(200, json={"id": "different-subject", "displayName": "Other"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OAuthCallbackError, match="explicit account switch"):
            complete_oauth_authorization(
                authorization_store,
                store,
                keyring(),
                config,
                provider="microsoft",
                workspace_id="team-a",
                state=started.state,
                code="provider-code",
                now=NOW + timedelta(minutes=2),
                client=client,
            )

    assert store.get("team-a", "primary") == original
    assert authorization_store.get(started.transaction.transaction_id).consumed_at is not None


def test_missing_provider_mismatch_and_revoked_reconnect_fail_before_exchange() -> None:
    config = load_oauth_provider_config("microsoft", oauth_environment())

    for case in ("missing", "provider", "revoked"):
        store = MemoryCredentialStore()
        credential_id = f"{case}-credential"
        if case == "provider":
            store.upsert(
                _existing_record(
                    provider="google",
                    credential_id=credential_id,
                )
            )
        elif case == "revoked":
            store.upsert(_existing_record(credential_id=credential_id))
            store.revoke(
                "team-a",
                credential_id,
                revoked_at=NOW + timedelta(seconds=30),
            )
        authorization_store, started = _reconnect_transaction("microsoft", credential_id)
        calls: list[str] = []

        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: calls.append(str(request.url)) or httpx.Response(500)
            )
        ) as client:
            with pytest.raises(OAuthCallbackError):
                complete_oauth_authorization(
                    authorization_store,
                    store,
                    keyring(),
                    config,
                    provider="microsoft",
                    workspace_id="team-a",
                    state=started.state,
                    code="provider-code",
                    now=NOW + timedelta(minutes=2),
                    client=client,
                )
        assert calls == []


def _configure_runtime_secrets(monkeypatch) -> None:
    encoded = base64.urlsafe_b64encode(bytes([82]) * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID", "active")
    monkeypatch.setenv("ANALYSTWATCH_CREDENTIAL_KEYS_JSON", json.dumps({"active": encoded}))
    for name, value in oauth_environment().items():
        monkeypatch.setenv(name, value)


def _auth_header(user_id: str) -> dict[str, str]:
    token = SignedSessionAuthenticator(AUTH_SECRET).issue_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def test_reconnect_start_is_admin_only_and_requires_existing_same_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_runtime_secrets(monkeypatch)
    memberships = SQLiteMembershipStore(tmp_path / "memberships.db")
    memberships.initialize()
    memberships.upsert_membership(
        WorkspaceMembership(workspace_id="team-a", user_id="operator", role=WorkspaceRole.OPERATOR)
    )
    memberships.upsert_membership(
        WorkspaceMembership(workspace_id="team-a", user_id="admin", role=WorkspaceRole.ADMIN)
    )
    app = create_app(
        tmp_path / "app.db",
        workspace_id="team-a",
        auth_mode="signed-bearer",
        auth_secret=AUTH_SECRET,
        membership_store=memberships,
    )
    runtime_keyring = CredentialKeyring({"active": bytes([82]) * 32}, active_key_id="active")
    existing = seal_provider_credential(
        runtime_keyring,
        credential_id="microsoft-primary",
        workspace_id="team-a",
        provider="microsoft",
        subject_id="subject-1",
        access_token="old-access",
        refresh_token="old-refresh",
        now=datetime.now(timezone.utc),
    )
    app.state.oauth_credential_store.upsert(existing)
    client = TestClient(app, follow_redirects=False)

    operator = client.post(
        "/api/oauth/microsoft/reconnect/start",
        params={"credential_id": "microsoft-primary"},
        headers=_auth_header("operator"),
    )
    assert operator.status_code == 403

    admin = client.post(
        "/api/oauth/microsoft/reconnect/start",
        params={"credential_id": "microsoft-primary"},
        headers=_auth_header("admin"),
    )
    assert admin.status_code == 303
    query = parse_qs(urlsplit(admin.headers["location"]).query)
    assert query["prompt"] == ["consent"]

    missing = client.post(
        "/api/oauth/google/reconnect/start",
        params={"credential_id": "missing"},
        headers=_auth_header("admin"),
    )
    assert missing.status_code == 409

    wrong_provider = client.post(
        "/api/oauth/google/reconnect/start",
        params={"credential_id": "microsoft-primary"},
        headers=_auth_header("admin"),
    )
    assert wrong_provider.status_code == 409
