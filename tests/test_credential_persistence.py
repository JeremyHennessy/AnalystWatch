from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from analystwatch.credential_crypto import CredentialCryptoError, CredentialKeyring
from analystwatch.credential_persistence import (
    PostgresCredentialStore,
    SQLiteCredentialStore,
)
from analystwatch.credential_store import (
    ProviderCredentialRecord,
    seal_provider_credential,
    unseal_access_token,
    unseal_refresh_token,
)
from analystwatch.postgres_storage import POSTGRES_SCHEMA

NOW = datetime(2026, 8, 24, 11, 30, tzinfo=timezone.utc)


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"key-1": bytes([11]) * 32}, active_key_id="key-1")


def record(
    *,
    workspace_id: str,
    credential_id: str,
    provider: str = "microsoft",
    subject_id: str = "subject-1",
    access_token: str = "access-private-token",
    refresh_token: str | None = "refresh-private-token",
    now: datetime = NOW,
) -> ProviderCredentialRecord:
    return seal_provider_credential(
        keyring(),
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
        subject_id=subject_id,
        access_token=access_token,
        refresh_token=refresh_token,
        scopes=["scope-b", "scope-a"],
        access_token_expires_at=now + timedelta(hours=1),
        display_name="Analyst User",
        email="analyst@example.com",
        now=now,
    )


def replacement(
    existing: ProviderCredentialRecord,
    *,
    access_token: str = "replacement-access-token",
    refresh_token: str | None = "replacement-refresh-token",
    subject_id: str | None = None,
) -> ProviderCredentialRecord:
    updated = seal_provider_credential(
        keyring(),
        credential_id=existing.credential_id,
        workspace_id=existing.workspace_id,
        provider=existing.provider,
        subject_id=subject_id or existing.subject_id,
        access_token=access_token,
        refresh_token=refresh_token,
        scopes=existing.scopes,
        access_token_expires_at=NOW + timedelta(hours=2),
        display_name=existing.display_name,
        email=existing.email,
        now=NOW + timedelta(minutes=5),
    )
    return updated.model_copy(update={"created_at": existing.created_at}, deep=True)


def test_sqlite_store_persists_encrypted_records_across_reopen(tmp_path) -> None:
    path = tmp_path / "credentials.db"
    first = SQLiteCredentialStore(path)
    first.initialize()
    stored = record(workspace_id="workspace-a", credential_id="primary")
    first.upsert(stored)

    reopened = SQLiteCredentialStore(path)
    reopened.initialize()
    loaded = reopened.get("workspace-a", "primary")

    assert loaded == stored
    assert unseal_access_token(loaded, keyring()) == "access-private-token"  # type: ignore[arg-type]
    assert unseal_refresh_token(loaded, keyring()) == "refresh-private-token"  # type: ignore[arg-type]


def test_sqlite_raw_database_contains_no_plaintext_tokens(tmp_path) -> None:
    store = SQLiteCredentialStore(tmp_path / "credentials.db")
    store.initialize()
    store.upsert(record(workspace_id="workspace-a", credential_id="primary"))

    with store.connect() as db:
        raw = db.execute(
            "SELECT record_json FROM provider_credentials WHERE workspace_id = ?",
            ("workspace-a",),
        ).fetchone()["record_json"]

    assert "access-private-token" not in raw
    assert "refresh-private-token" not in raw
    assert "AES-256-GCM" in raw


def test_sqlite_workspace_isolation_update_guard_and_revoke(tmp_path) -> None:
    store = SQLiteCredentialStore(tmp_path / "credentials.db")
    store.initialize()
    original = record(workspace_id="workspace-a", credential_id="shared")
    other = record(
        workspace_id="workspace-b",
        credential_id="shared",
        provider="google",
        subject_id="google-subject",
    )
    store.upsert(original)
    store.upsert(other)

    updated = replacement(original)
    store.upsert(updated)
    assert unseal_access_token(store.get("workspace-a", "shared"), keyring()) == (
        "replacement-access-token"
    )
    assert store.get("workspace-b", "shared").provider.value == "google"  # type: ignore[union-attr]

    switched = replacement(updated, subject_id="other-subject")
    with pytest.raises(ValueError, match="account-switch"):
        store.upsert(switched)

    revoked = store.revoke(
        "workspace-a",
        "shared",
        revoked_at=NOW + timedelta(minutes=10),
    )
    assert store.get("workspace-a", "shared").revoked_at == revoked.revoked_at  # type: ignore[union-attr]
    with pytest.raises(CredentialCryptoError, match="revoked"):
        unseal_access_token(revoked, keyring())


def _postgres_store() -> PostgresCredentialStore:
    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    store = PostgresCredentialStore(dsn)
    store.initialize()
    return store


def _clear_postgres(store: PostgresCredentialStore, *workspaces: str) -> None:
    with store.connect() as db:
        db.execute(
            f"DELETE FROM {POSTGRES_SCHEMA}.provider_credentials WHERE workspace_id = ANY(%s)",
            (list(workspaces),),
        )


def test_postgres_store_persists_ciphertext_workspace_isolation_and_updates() -> None:
    store = _postgres_store()
    workspaces = ("cred-pg-a", "cred-pg-b")
    _clear_postgres(store, *workspaces)
    try:
        original = record(workspace_id=workspaces[0], credential_id="shared")
        other = record(
            workspace_id=workspaces[1],
            credential_id="shared",
            provider="google",
            subject_id="google-subject",
        )
        store.upsert(original)
        store.upsert(other)

        updated = replacement(original)
        store.upsert(updated)
        loaded = store.get(workspaces[0], "shared")
        assert loaded == updated
        assert unseal_access_token(loaded, keyring()) == "replacement-access-token"  # type: ignore[arg-type]
        assert store.get(workspaces[1], "shared").provider.value == "google"  # type: ignore[union-attr]

        with store.connect() as db:
            raw = db.execute(
                f"""
                SELECT record_json::text AS record_text
                FROM {POSTGRES_SCHEMA}.provider_credentials
                WHERE workspace_id = %s AND credential_id = %s
                """,
                (workspaces[0], "shared"),
            ).fetchone()["record_text"]
        assert "replacement-access-token" not in raw
        assert "replacement-refresh-token" not in raw
        assert "AES-256-GCM" in raw
    finally:
        _clear_postgres(store, *workspaces)


def test_postgres_store_blocks_account_switch_and_persists_revoke() -> None:
    store = _postgres_store()
    workspace = "cred-pg-guard"
    _clear_postgres(store, workspace)
    try:
        original = record(workspace_id=workspace, credential_id="primary")
        store.upsert(original)
        switched = replacement(original, subject_id="different-account")
        with pytest.raises(ValueError, match="account-switch"):
            store.upsert(switched)

        revoked = store.revoke(
            workspace,
            "primary",
            revoked_at=NOW + timedelta(minutes=10),
        )
        reopened = PostgresCredentialStore(store.dsn)
        loaded = reopened.get(workspace, "primary")
        assert loaded is not None
        assert loaded.revoked_at == revoked.revoked_at
        with pytest.raises(CredentialCryptoError, match="revoked"):
            unseal_refresh_token(loaded, keyring())
    finally:
        _clear_postgres(store, workspace)
