from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from analystwatch.auth import (
    SignedSessionAuthenticator,
    WorkspaceMembership,
    WorkspaceRole,
    role_allows,
)
from analystwatch.auth_storage import PostgresMembershipStore, SQLiteMembershipStore

SECRET = "analystwatch-test-auth-secret-32-bytes-minimum"
NOW = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)


def test_role_hierarchy_is_explicit_and_minimal() -> None:
    assert role_allows(WorkspaceRole.VIEWER, WorkspaceRole.VIEWER)
    assert not role_allows(WorkspaceRole.VIEWER, WorkspaceRole.OPERATOR)
    assert role_allows(WorkspaceRole.OPERATOR, WorkspaceRole.VIEWER)
    assert role_allows(WorkspaceRole.OPERATOR, WorkspaceRole.OPERATOR)
    assert not role_allows(WorkspaceRole.OPERATOR, WorkspaceRole.ADMIN)
    assert role_allows(WorkspaceRole.ADMIN, WorkspaceRole.ADMIN)


def test_signed_session_authenticates_principal_without_workspace_authority() -> None:
    authenticator = SignedSessionAuthenticator(SECRET)
    token = authenticator.issue_token("user-a", expires_at=NOW + timedelta(hours=1))

    principal = authenticator.authenticate(f"Bearer {token}", now=NOW)

    assert principal.user_id == "user-a"
    assert "workspace" not in token


def test_signed_session_rejects_tamper_and_expiry() -> None:
    authenticator = SignedSessionAuthenticator(SECRET)
    token = authenticator.issue_token("user-a", expires_at=NOW + timedelta(minutes=5))
    payload, signature = token.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    tampered = f"{payload[:-1]}{replacement}.{signature}"

    with pytest.raises(ValueError, match="signature"):
        authenticator.authenticate(f"Bearer {tampered}", now=NOW)
    with pytest.raises(ValueError, match="expired"):
        authenticator.authenticate(f"Bearer {token}", now=NOW + timedelta(minutes=5))


def test_signed_session_requires_real_secret_and_bearer_syntax() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SignedSessionAuthenticator("short")
    authenticator = SignedSessionAuthenticator(SECRET)
    with pytest.raises(ValueError, match="Missing"):
        authenticator.authenticate(None, now=NOW)
    with pytest.raises(ValueError, match="Bearer"):
        authenticator.authenticate("Basic abc", now=NOW)


def test_sqlite_memberships_persist_roles_and_workspace_isolation(tmp_path: Path) -> None:
    path = tmp_path / "auth.db"
    first = SQLiteMembershipStore(path)
    first.initialize()
    first.upsert_membership(
        WorkspaceMembership(workspace_id="team-a", user_id="user-1", role=WorkspaceRole.VIEWER)
    )
    first.upsert_membership(
        WorkspaceMembership(workspace_id="team-b", user_id="user-1", role=WorkspaceRole.ADMIN)
    )

    reopened = SQLiteMembershipStore(path)
    reopened.initialize()

    assert reopened.get_membership("team-a", "user-1").role == WorkspaceRole.VIEWER  # type: ignore[union-attr]
    assert reopened.get_membership("team-b", "user-1").role == WorkspaceRole.ADMIN  # type: ignore[union-attr]
    assert reopened.get_membership("team-a", "unknown") is None
    assert [item.user_id for item in reopened.list_memberships("team-a")] == ["user-1"]


def test_postgres_memberships_persist_roles_and_workspace_isolation() -> None:
    dsn = os.environ.get("ANALYSTWATCH_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("ANALYSTWATCH_TEST_POSTGRES_DSN is not configured")
    store = PostgresMembershipStore(dsn)
    store.initialize()
    with store.connect() as db:
        db.execute(
            "DELETE FROM analystwatch.workspace_memberships WHERE workspace_id IN (%s, %s)",
            ("auth-test-a", "auth-test-b"),
        )
    try:
        store.upsert_membership(
            WorkspaceMembership(
                workspace_id="auth-test-a", user_id="same-user", role=WorkspaceRole.OPERATOR
            )
        )
        store.upsert_membership(
            WorkspaceMembership(
                workspace_id="auth-test-b", user_id="same-user", role=WorkspaceRole.ADMIN
            )
        )

        assert store.get_membership("auth-test-a", "same-user").role == WorkspaceRole.OPERATOR  # type: ignore[union-attr]
        assert store.get_membership("auth-test-b", "same-user").role == WorkspaceRole.ADMIN  # type: ignore[union-attr]
    finally:
        with store.connect() as db:
            db.execute(
                "DELETE FROM analystwatch.workspace_memberships WHERE workspace_id IN (%s, %s)",
                ("auth-test-a", "auth-test-b"),
            )
