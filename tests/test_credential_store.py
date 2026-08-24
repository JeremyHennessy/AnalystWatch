from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analystwatch.credential_crypto import CredentialCryptoError, CredentialKeyring
from analystwatch.credential_store import (
    MemoryCredentialStore,
    ProviderCredentialRecord,
    seal_provider_credential,
    unseal_access_token,
    unseal_refresh_token,
)

NOW = datetime(2026, 8, 24, 11, 20, tzinfo=timezone.utc)


def key(byte: int) -> bytes:
    return bytes([byte]) * 32


def keyring() -> CredentialKeyring:
    return CredentialKeyring({"key-1": key(1)}, active_key_id="key-1")


def record(
    *,
    credential_id: str = "microsoft-primary",
    workspace_id: str = "workspace-a",
    provider: str = "microsoft",
    subject_id: str = "subject-1",
    access_token: str = "access-private",
    refresh_token: str | None = "refresh-private",
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
        scopes=["Files.Read", "User.Read", "Files.Read"],
        access_token_expires_at=now + timedelta(hours=1),
        display_name="Analyst User",
        email="analyst@example.com",
        now=now,
    )


def test_sealed_record_round_trip_never_serializes_plaintext_tokens() -> None:
    stored = record()
    serialized = stored.model_dump_json()

    assert stored.scopes == ("Files.Read", "User.Read")
    assert "access-private" not in serialized
    assert "refresh-private" not in serialized
    assert unseal_access_token(stored, keyring()) == "access-private"
    assert unseal_refresh_token(stored, keyring()) == "refresh-private"


def test_access_and_refresh_envelopes_cannot_be_swapped() -> None:
    stored = record()
    assert stored.refresh_token is not None
    swapped = stored.model_copy(update={"access_token": stored.refresh_token}, deep=True)

    with pytest.raises(CredentialCryptoError, match="could not be authenticated"):
        unseal_access_token(swapped, keyring())


def test_account_metadata_tampering_breaks_ciphertext_authentication() -> None:
    stored = record()
    tampered = stored.model_copy(update={"subject_id": "subject-2"}, deep=True)

    with pytest.raises(CredentialCryptoError, match="could not be authenticated"):
        unseal_access_token(tampered, keyring())


def test_revoked_credentials_cannot_be_unsealed() -> None:
    store = MemoryCredentialStore()
    store.initialize()
    store.upsert(record())
    revoked = store.revoke(
        "workspace-a",
        "microsoft-primary",
        revoked_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(CredentialCryptoError, match="revoked"):
        unseal_access_token(revoked, keyring())
    with pytest.raises(CredentialCryptoError, match="revoked"):
        unseal_refresh_token(revoked, keyring())


def test_memory_store_isolates_workspaces_and_returns_copies() -> None:
    store = MemoryCredentialStore()
    first = record(workspace_id="workspace-a", credential_id="shared")
    second = record(
        workspace_id="workspace-b",
        credential_id="shared",
        provider="google",
        subject_id="google-subject",
    )
    store.upsert(first)
    store.upsert(second)

    assert store.get("workspace-a", "shared").provider.value == "microsoft"  # type: ignore[union-attr]
    assert store.get("workspace-b", "shared").provider.value == "google"  # type: ignore[union-attr]
    assert [item.credential_id for item in store.list("workspace-a")] == ["shared"]
    fetched = store.get("workspace-a", "shared")
    assert fetched is not None
    fetched.display_name = "Mutated caller copy"
    assert store.get("workspace-a", "shared").display_name == "Analyst User"  # type: ignore[union-attr]


def test_memory_store_blocks_silent_account_switch_and_stale_update() -> None:
    store = MemoryCredentialStore()
    original = record()
    store.upsert(original)

    switched = record(subject_id="other-subject", now=NOW + timedelta(minutes=1)).model_copy(
        update={"created_at": NOW}
    )
    with pytest.raises(ValueError, match="account-switch"):
        store.upsert(switched)

    stale = original.model_copy(update={"updated_at": NOW - timedelta(seconds=1)})
    with pytest.raises(ValueError, match="older"):
        store.upsert(stale)


def test_revocation_is_idempotent_and_cannot_be_silently_reactivated() -> None:
    store = MemoryCredentialStore()
    original = record()
    store.upsert(original)
    revoked_at = NOW + timedelta(minutes=5)
    revoked = store.revoke("workspace-a", "microsoft-primary", revoked_at=revoked_at)
    repeated = store.revoke(
        "workspace-a",
        "microsoft-primary",
        revoked_at=revoked_at + timedelta(minutes=1),
    )

    assert repeated.revoked_at == revoked_at
    reactivated = revoked.model_copy(
        update={"revoked_at": None, "updated_at": revoked_at + timedelta(minutes=2)}
    )
    with pytest.raises(ValueError, match="silently reactivated"):
        store.upsert(reactivated)


def test_record_requires_timezone_aware_ordered_timestamps() -> None:
    stored = record()
    with pytest.raises(ValueError, match="timezone-aware"):
        ProviderCredentialRecord(**{**stored.model_dump(), "created_at": NOW.replace(tzinfo=None)})
    with pytest.raises(ValueError, match="updated_at must not precede"):
        ProviderCredentialRecord(
            **{
                **stored.model_dump(),
                "updated_at": NOW - timedelta(seconds=1),
            }
        )


def test_refresh_token_is_optional() -> None:
    stored = record(refresh_token=None)

    assert stored.refresh_token is None
    assert unseal_refresh_token(stored, keyring()) is None
