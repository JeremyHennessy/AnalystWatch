from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from analystwatch.credential_crypto import CredentialKeyring
from analystwatch.oauth_authorization import OAuthAuthorizationTransaction
from analystwatch.oauth_authorization_store import OAuthAuthorizationStore
from analystwatch.oauth_provider_config import load_oauth_provider_config
from analystwatch.oauth_start import begin_persisted_oauth_authorization

NOW = datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc)


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"active": bytes([21]) * 32}, active_key_id="active")


def environment() -> dict[str, str]:
    return {
        "ANALYSTWATCH_PUBLIC_BASE_URL": "https://analystwatch.example",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID": "microsoft-client",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET": "microsoft-secret",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
    }


class RecordingStore(OAuthAuthorizationStore):
    def __init__(self, *, fail_create: bool = False) -> None:
        self.created: OAuthAuthorizationTransaction | None = None
        self.fail_create = fail_create

    def initialize(self) -> None:
        return None

    def create(
        self,
        transaction: OAuthAuthorizationTransaction,
    ) -> OAuthAuthorizationTransaction:
        if self.fail_create:
            raise RuntimeError("persistence unavailable")
        self.created = transaction
        return transaction

    def get(self, transaction_id: str) -> OAuthAuthorizationTransaction | None:
        if self.created is not None and self.created.transaction_id == transaction_id:
            return self.created
        return None

    def consume(self, state, keyring, *, now):  # pragma: no cover - not used here
        raise NotImplementedError


def parse(url: str) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}", parse_qs(parts.query)


def test_microsoft_start_persists_transaction_and_builds_pkce_redirect() -> None:
    store = RecordingStore()
    config = load_oauth_provider_config("microsoft", environment())

    url = begin_persisted_oauth_authorization(
        store,
        keyring(),
        config,
        workspace_id="team-a",
        user_id="operator",
        credential_id="microsoft-primary",
        now=NOW,
    )
    endpoint, query = parse(url)

    assert endpoint == config.public.authorization_endpoint
    assert query["client_id"] == ["microsoft-client"]
    assert query["response_type"] == ["code"]
    assert query["response_mode"] == ["query"]
    assert query["redirect_uri"] == ["https://analystwatch.example/api/oauth/microsoft/callback"]
    assert query["scope"] == [" ".join(config.public.scopes)]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["state"][0]) == 43
    assert len(query["code_challenge"][0]) == 43
    assert "microsoft-secret" not in url
    assert store.created is not None
    assert store.created.workspace_id == "team-a"
    assert store.created.user_id == "operator"
    assert store.created.credential_id == "microsoft-primary"


def test_google_start_uses_offline_incremental_authorization_parameters() -> None:
    store = RecordingStore()
    config = load_oauth_provider_config("google", environment())

    url = begin_persisted_oauth_authorization(
        store,
        keyring(),
        config,
        workspace_id="team-a",
        user_id="operator",
        credential_id="google-primary",
        now=NOW,
    )
    endpoint, query = parse(url)

    assert endpoint == config.public.authorization_endpoint
    assert query["client_id"] == ["google-client"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["https://analystwatch.example/api/oauth/google/callback"]
    assert query["scope"] == [" ".join(config.public.scopes)]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["code_challenge_method"] == ["S256"]
    assert "google-secret" not in url
    assert "prompt" not in query


def test_persistence_failure_prevents_authorization_url_return() -> None:
    store = RecordingStore(fail_create=True)
    config = load_oauth_provider_config("microsoft", environment())

    with pytest.raises(RuntimeError, match="persistence unavailable"):
        begin_persisted_oauth_authorization(
            store,
            keyring(),
            config,
            workspace_id="team-a",
            user_id="operator",
            credential_id="microsoft-primary",
            now=NOW,
        )
