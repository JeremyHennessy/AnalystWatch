from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from analystwatch.credential_crypto import CredentialKeyring
from analystwatch.credential_store import (
    MemoryCredentialStore,
    seal_provider_credential,
    unseal_access_token,
    unseal_refresh_token,
)
from analystwatch.oauth_authorization import begin_authorization_transaction
from analystwatch.oauth_authorization_store import MemoryOAuthAuthorizationStore
from analystwatch.oauth_callback import (
    OAuthCallbackError,
    complete_oauth_authorization,
    consume_oauth_authorization_denial,
)
from analystwatch.oauth_provider_config import load_oauth_provider_config

NOW = datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc)


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"active": bytes([37]) * 32}, active_key_id="active")


def environment() -> dict[str, str]:
    return {
        "ANALYSTWATCH_PUBLIC_BASE_URL": "https://analystwatch.example",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID": "microsoft-client",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET": "microsoft-secret",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
    }


def started(provider: str = "microsoft", credential_id: str = "primary"):
    value = begin_authorization_transaction(
        keyring(),
        workspace_id="team-a",
        user_id="operator",
        provider=provider,
        credential_id=credential_id,
        now=NOW,
    )
    store = MemoryOAuthAuthorizationStore()
    store.initialize()
    store.create(value.transaction)
    return store, value


def test_microsoft_callback_writes_only_encrypted_verified_credential() -> None:
    authorization_store, value = started()
    credential_store = MemoryCredentialStore()
    config = load_oauth_provider_config("microsoft", environment())
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            form = parse_qs(request.content.decode("utf-8"))
            assert form["code"] == ["provider-code"]
            assert form["code_verifier"][0]
            assert form["client_secret"] == ["microsoft-secret"]
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "scope": "User.Read Files.Read.All offline_access",
                    "expires_in": 3600,
                    "access_token": "microsoft-access-secret",
                    "refresh_token": "microsoft-refresh-secret",
                },
            )
        assert request.url.path == "/v1.0/me"
        assert request.headers["Authorization"] == "Bearer microsoft-access-secret"
        return httpx.Response(
            200,
            json={
                "id": "microsoft-subject",
                "displayName": "Connected Analyst",
                "mail": "analyst@example.com",
                "userPrincipalName": "fallback@example.com",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = complete_oauth_authorization(
            authorization_store,
            credential_store,
            keyring(),
            config,
            provider="microsoft",
            workspace_id="team-a",
            state=value.state,
            code="provider-code",
            now=NOW + timedelta(minutes=1),
            client=client,
        )

    assert requests == [("POST", "/organizations/oauth2/v2.0/token"), ("GET", "/v1.0/me")]
    assert record.subject_id == "microsoft-subject"
    assert record.display_name == "Connected Analyst"
    assert record.email == "analyst@example.com"
    assert record.scopes == ("Files.Read.All", "User.Read", "offline_access")
    assert record.access_token_expires_at == NOW + timedelta(minutes=61)
    assert unseal_access_token(record, keyring()) == "microsoft-access-secret"
    assert unseal_refresh_token(record, keyring()) == "microsoft-refresh-secret"
    serialized = record.model_dump_json()
    assert "microsoft-access-secret" not in serialized
    assert "microsoft-refresh-secret" not in serialized
    assert credential_store.get("team-a", "primary") == record


def test_google_callback_uses_drive_identity_and_allows_access_only_initial_token() -> None:
    authorization_store, value = started("google", "google-primary")
    credential_store = MemoryCredentialStore()
    config = load_oauth_provider_config("google", environment())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "scope": "openid email",
                    "expires_in": 3600,
                    "access_token": "google-access-secret",
                },
            )
        assert request.url.path == "/drive/v3/about"
        return httpx.Response(
            200,
            json={
                "user": {
                    "permissionId": "google-subject",
                    "displayName": "Google Analyst",
                    "emailAddress": "google@example.com",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = complete_oauth_authorization(
            authorization_store,
            credential_store,
            keyring(),
            config,
            provider="google",
            workspace_id="team-a",
            state=value.state,
            code="provider-code",
            now=NOW + timedelta(minutes=1),
            client=client,
        )

    assert record.subject_id == "google-subject"
    assert record.refresh_token is None
    assert unseal_access_token(record, keyring()) == "google-access-secret"


def test_wrong_callback_binding_does_not_consume_or_contact_provider() -> None:
    authorization_store, value = started("google")
    credential_store = MemoryCredentialStore()
    config = load_oauth_provider_config("microsoft", environment())
    calls = []

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: calls.append(str(request.url)) or httpx.Response(500)
        )
    ) as client:
        with pytest.raises(OAuthCallbackError, match="callback provider"):
            complete_oauth_authorization(
                authorization_store,
                credential_store,
                keyring(),
                config,
                provider="microsoft",
                workspace_id="team-a",
                state=value.state,
                code="provider-code",
                now=NOW + timedelta(minutes=1),
                client=client,
            )

    assert calls == []
    assert authorization_store.get(value.transaction.transaction_id).consumed_at is None


def test_existing_credential_id_is_rejected_before_token_exchange() -> None:
    authorization_store, value = started("microsoft", "existing")
    credential_store = MemoryCredentialStore()
    existing = seal_provider_credential(
        keyring(),
        credential_id="existing",
        workspace_id="team-a",
        provider="microsoft",
        subject_id="existing-subject",
        access_token="old-access",
        refresh_token="old-refresh",
        now=NOW,
    )
    credential_store.upsert(existing)
    calls = []
    config = load_oauth_provider_config("microsoft", environment())

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: calls.append(str(request.url)) or httpx.Response(500)
        )
    ) as client:
        with pytest.raises(OAuthCallbackError, match="already connected"):
            complete_oauth_authorization(
                authorization_store,
                credential_store,
                keyring(),
                config,
                provider="microsoft",
                workspace_id="team-a",
                state=value.state,
                code="provider-code",
                now=NOW + timedelta(minutes=1),
                client=client,
            )

    assert calls == []
    assert authorization_store.get(value.transaction.transaction_id).consumed_at is not None
    assert credential_store.get("team-a", "existing") == existing


def test_exchange_failure_consumes_state_and_never_persists_credential_or_error_body() -> None:
    authorization_store, value = started()
    credential_store = MemoryCredentialStore()
    config = load_oauth_provider_config("microsoft", environment())
    provider_body = "provider-secret-error-body"

    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(400, text=provider_body))
    ) as client:
        with pytest.raises(OAuthCallbackError, match="HTTP 400") as exc:
            complete_oauth_authorization(
                authorization_store,
                credential_store,
                keyring(),
                config,
                provider="microsoft",
                workspace_id="team-a",
                state=value.state,
                code="provider-code",
                now=NOW + timedelta(minutes=1),
                client=client,
            )

    assert provider_body not in str(exc.value)
    assert credential_store.list("team-a") == []
    assert authorization_store.get(value.transaction.transaction_id).consumed_at is not None
    with pytest.raises(OAuthCallbackError, match="already consumed"):
        complete_oauth_authorization(
            authorization_store,
            credential_store,
            keyring(),
            config,
            provider="microsoft",
            workspace_id="team-a",
            state=value.state,
            code="provider-code-2",
            now=NOW + timedelta(minutes=2),
        )


def test_provider_denial_consumes_matching_state_without_token_exchange() -> None:
    authorization_store, value = started("google")
    consumed = consume_oauth_authorization_denial(
        authorization_store,
        keyring(),
        provider="google",
        workspace_id="team-a",
        state=value.state,
        now=NOW + timedelta(minutes=1),
    )
    assert consumed.consumed_at == NOW + timedelta(minutes=1)

    with pytest.raises(OAuthCallbackError, match="already consumed"):
        consume_oauth_authorization_denial(
            authorization_store,
            keyring(),
            provider="google",
            workspace_id="team-a",
            state=value.state,
            now=NOW + timedelta(minutes=2),
        )
