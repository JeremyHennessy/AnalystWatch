from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .auth import (
    AuthenticationContext,
    SignedSessionAuthenticator,
    WorkspaceMembership,
    WorkspaceRole,
    role_allows,
)
from .auth_storage import MembershipStore, PostgresMembershipStore, SQLiteMembershipStore

AuthMode = Literal["local", "signed-bearer"]
DEFAULT_AUTH_MODE: AuthMode = "local"
SUPPORTED_AUTH_MODES: tuple[AuthMode, ...] = ("local", "signed-bearer")

_OPERATOR_MUTATIONS = (
    re.compile(r"^/sources/[^/]+/(check|review)$"),
    re.compile(r"^/api/sources/[^/]+/check$"),
    re.compile(r"^/api/sources/[^/]+/observations/[^/]+/review$"),
    re.compile(r"^/api/notification-candidates/evaluate$"),
    re.compile(r"^/api/delivery-attempts/dry-run$"),
    re.compile(r"^/api/delivery-attempts/[^/]+/reconcile$"),
    re.compile(r"^/api/check-due$"),
)


def normalize_auth_mode(value: str) -> AuthMode:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_AUTH_MODES:
        raise ValueError(f"auth mode must be one of: {', '.join(SUPPORTED_AUTH_MODES)}")
    return normalized  # type: ignore[return-value]


def required_role(method: str, path: str) -> WorkspaceRole:
    normalized_method = method.upper()
    if path == "/api/workspace/memberships" or path.startswith(
        "/api/workspace/memberships/"
    ):
        return WorkspaceRole.ADMIN
    if normalized_method in {"GET", "HEAD", "OPTIONS"}:
        return WorkspaceRole.VIEWER
    if any(pattern.fullmatch(path) for pattern in _OPERATOR_MUTATIONS):
        return WorkspaceRole.OPERATOR
    # Mutations not explicitly classified above fail closed as Admin-only.
    return WorkspaceRole.ADMIN


def _default_membership_store(
    *,
    storage_backend: str,
    postgres_dsn: str | None,
    db_path: Path,
    auth_db_path: str | Path | None,
) -> MembershipStore:
    if storage_backend == "postgres":
        if not postgres_dsn:
            raise ValueError("signed-bearer PostgreSQL auth requires a PostgreSQL DSN")
        return PostgresMembershipStore(postgres_dsn)
    path = Path(auth_db_path) if auth_db_path is not None else db_path.with_suffix(
        db_path.suffix + ".auth.db"
    )
    return SQLiteMembershipStore(path)


def configure_web_authorization(
    app: FastAPI,
    *,
    workspace_id: str,
    storage_backend: str,
    db_path: Path,
    postgres_dsn: str | None,
    auth_mode: str | None = None,
    auth_secret: str | None = None,
    membership_store: MembershipStore | None = None,
    auth_db_path: str | Path | None = None,
) -> None:
    resolved_mode = normalize_auth_mode(
        auth_mode
        if auth_mode is not None
        else os.environ.get("ANALYSTWATCH_AUTH_MODE", DEFAULT_AUTH_MODE)
    )
    app.state.auth_mode = resolved_mode

    if resolved_mode == "local":
        app.state.authenticator = None
        app.state.membership_store = None
        return

    secret = (
        auth_secret
        if auth_secret is not None
        else os.environ.get("ANALYSTWATCH_AUTH_SECRET")
    )
    if secret is None:
        raise ValueError("signed-bearer auth requires ANALYSTWATCH_AUTH_SECRET or auth_secret")
    authenticator = SignedSessionAuthenticator(secret)
    memberships = membership_store or _default_membership_store(
        storage_backend=storage_backend,
        postgres_dsn=postgres_dsn,
        db_path=db_path,
        auth_db_path=auth_db_path,
    )
    memberships.initialize()
    app.state.authenticator = authenticator
    app.state.membership_store = memberships

    @app.middleware("http")
    async def authorize_request(request, call_next):
        path = request.url.path
        if path == "/healthz" or path.startswith("/static/"):
            return await call_next(request)
        try:
            principal = authenticator.authenticate(request.headers.get("Authorization"))
        except ValueError as exc:
            return JSONResponse(
                status_code=401,
                content={"detail": str(exc)},
                headers={"WWW-Authenticate": "Bearer"},
            )
        membership = memberships.get_membership(workspace_id, principal.user_id)
        if membership is None:
            return JSONResponse(
                status_code=403,
                content={"detail": "Principal is not a member of this workspace"},
            )
        required = required_role(request.method, path)
        if not role_allows(membership.role, required):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        f"Workspace role {membership.role.value} does not permit "
                        f"{required.value} operation"
                    )
                },
            )
        request.state.auth_context = AuthenticationContext(
            principal=principal,
            workspace_id=workspace_id,
            role=membership.role,
        )
        return await call_next(request)

    def list_memberships() -> list[WorkspaceMembership]:
        return memberships.list_memberships(workspace_id)

    def upsert_membership(user_id: str, role: WorkspaceRole) -> WorkspaceMembership:
        return memberships.upsert_membership(
            WorkspaceMembership(workspace_id=workspace_id, user_id=user_id, role=role)
        )

    app.add_api_route(
        "/api/workspace/memberships",
        list_memberships,
        methods=["GET"],
        response_model=list[WorkspaceMembership],
    )
    app.add_api_route(
        "/api/workspace/memberships/{user_id}",
        upsert_membership,
        methods=["PUT"],
        response_model=WorkspaceMembership,
    )
