from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .workspace import validate_workspace_id


class WorkspaceRole(StrEnum):
    VIEWER = "Viewer"
    OPERATOR = "Operator"
    ADMIN = "Admin"


_ROLE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.VIEWER: 10,
    WorkspaceRole.OPERATOR: 20,
    WorkspaceRole.ADMIN: 30,
}


class AuthenticatedPrincipal(BaseModel):
    user_id: str = Field(min_length=1)


class WorkspaceMembership(BaseModel):
    workspace_id: str
    user_id: str = Field(min_length=1)
    role: WorkspaceRole

    def model_post_init(self, __context: object) -> None:
        self.workspace_id = validate_workspace_id(self.workspace_id)
        if self.user_id != self.user_id.strip():
            raise ValueError("user_id must be trimmed")


class AuthenticationContext(BaseModel):
    principal: AuthenticatedPrincipal
    workspace_id: str
    role: WorkspaceRole

    def model_post_init(self, __context: object) -> None:
        self.workspace_id = validate_workspace_id(self.workspace_id)


@runtime_checkable
class Authenticator(Protocol):
    def authenticate(
        self,
        authorization_header: str | None,
        *,
        now: datetime | None = None,
    ) -> AuthenticatedPrincipal: ...


def role_allows(actual: WorkspaceRole, required: WorkspaceRole) -> bool:
    return _ROLE_RANK[actual] >= _ROLE_RANK[required]


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class SignedSessionAuthenticator:
    """Provider-neutral HMAC bearer-token verifier.

    Tokens assert only authenticated principal identity and expiry. Workspace
    authorization is deliberately excluded and must come from membership storage.
    """

    def __init__(self, secret: str):
        if not secret or secret != secret.strip() or len(secret.encode("utf-8")) < 32:
            raise ValueError("Authentication secret must be trimmed and at least 32 bytes")
        self._secret = secret.encode("utf-8")

    def issue_token(
        self,
        user_id: str,
        *,
        expires_at: datetime | None = None,
    ) -> str:
        principal = AuthenticatedPrincipal(user_id=user_id)
        if principal.user_id != principal.user_id.strip():
            raise ValueError("user_id must be trimmed")
        payload: dict[str, object] = {"sub": principal.user_id}
        if expires_at is not None:
            if expires_at.tzinfo is None:
                raise ValueError("expires_at must be timezone-aware")
            payload["exp"] = int(expires_at.timestamp())
        encoded_payload = _b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_b64encode(signature)}"

    def authenticate(
        self,
        authorization_header: str | None,
        *,
        now: datetime | None = None,
    ) -> AuthenticatedPrincipal:
        if authorization_header is None:
            raise ValueError("Missing Authorization header")
        scheme, separator, token = authorization_header.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token:
            raise ValueError("Authorization header must use Bearer token syntax")
        payload_part, dot, signature_part = token.partition(".")
        if not dot or not payload_part or not signature_part:
            raise ValueError("Malformed bearer token")
        try:
            supplied_signature = _b64decode(signature_part)
            payload_bytes = _b64decode(payload_part)
        except (ValueError, TypeError) as exc:
            raise ValueError("Malformed bearer token") from exc
        expected_signature = hmac.new(
            self._secret,
            payload_part.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("Invalid bearer token signature")
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed bearer token payload") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("sub"), str):
            raise ValueError("Bearer token is missing principal identity")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        expires = payload.get("exp")
        if expires is not None:
            if not isinstance(expires, int):
                raise ValueError("Bearer token expiry is invalid")
            if int(current.timestamp()) >= expires:
                raise ValueError("Bearer token has expired")
        principal = AuthenticatedPrincipal(user_id=payload["sub"])
        if principal.user_id != principal.user_id.strip():
            raise ValueError("Bearer token principal identity is invalid")
        return principal
