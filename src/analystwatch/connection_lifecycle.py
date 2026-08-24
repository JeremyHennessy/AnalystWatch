from __future__ import annotations

from collections.abc import Callable
from enum import Enum

import httpx
from pydantic import BaseModel

from .connection_discovery import (
    DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    ConnectionCheck,
    ConnectionDiscoveryError,
    ConnectionProvider,
    check_connection,
)
from .connection_identity import (
    ConnectionAccountIdentity,
    inspect_connection_identity,
    inspect_connection_identity_with_access_token,
)
from .connection_oauth import check_connection_with_access_token


class CredentialLifecycleState(str, Enum):
    NEEDS_CREDENTIAL = "needs_credential"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    IDENTITY_UNVERIFIED = "identity_unverified"
    VERIFIED = "verified"


class CredentialNextAction(str, Enum):
    CONFIGURE = "configure"
    RECONNECT = "reconnect"
    RETRY = "retry"
    REVIEW_SCOPES = "review_scopes"
    NONE = "none"


class CredentialLifecycle(BaseModel):
    provider: ConnectionProvider
    state: CredentialLifecycleState
    next_action: CredentialNextAction
    configured: bool
    reachable: bool
    identity_verified: bool
    http_status: int | None = None
    identity: ConnectionAccountIdentity | None = None
    guidance: str


def credential_lifecycle(
    provider: ConnectionProvider | str,
    environment_variable: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> CredentialLifecycle:
    """Derive non-persistent lifecycle evidence for an environment-backed credential."""
    provider = ConnectionProvider(provider)
    check = check_connection(
        provider,
        environment_variable,
        timeout_seconds=timeout_seconds,
        client=client,
    )
    return _derive_credential_lifecycle(
        provider,
        check,
        lambda: inspect_connection_identity(
            provider,
            environment_variable,
            timeout_seconds=timeout_seconds,
            client=client,
        ),
    )


def credential_lifecycle_with_access_token(
    provider: ConnectionProvider | str,
    access_token: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> CredentialLifecycle:
    """Derive lifecycle evidence for one decrypted in-memory OAuth access token."""
    provider = ConnectionProvider(provider)
    check = check_connection_with_access_token(
        provider,
        access_token,
        timeout_seconds=timeout_seconds,
        client=client,
    )
    return _derive_credential_lifecycle(
        provider,
        check,
        lambda: inspect_connection_identity_with_access_token(
            provider,
            access_token,
            timeout_seconds=timeout_seconds,
            client=client,
        ),
    )


def _derive_credential_lifecycle(
    provider: ConnectionProvider,
    check: ConnectionCheck,
    identity_loader: Callable[[], ConnectionAccountIdentity],
) -> CredentialLifecycle:
    if not check.configured:
        return CredentialLifecycle(
            provider=provider,
            state=CredentialLifecycleState.NEEDS_CREDENTIAL,
            next_action=CredentialNextAction.CONFIGURE,
            configured=False,
            reachable=False,
            identity_verified=False,
            guidance="Configure the server credential before testing this provider connection.",
        )

    if not check.reachable:
        if check.http_status in {401, 403}:
            return CredentialLifecycle(
                provider=provider,
                state=CredentialLifecycleState.REJECTED,
                next_action=CredentialNextAction.RECONNECT,
                configured=True,
                reachable=False,
                identity_verified=False,
                http_status=check.http_status,
                guidance=(
                    "The provider rejected the configured credential. Reconnect with a valid "
                    "credential before using this connection."
                ),
            )
        return CredentialLifecycle(
            provider=provider,
            state=CredentialLifecycleState.UNAVAILABLE,
            next_action=CredentialNextAction.RETRY,
            configured=True,
            reachable=False,
            identity_verified=False,
            http_status=check.http_status,
            guidance=(
                "The provider could not be reached reliably. Retry before changing credentials."
            ),
        )

    try:
        identity = identity_loader()
    except ConnectionDiscoveryError as exc:
        if exc.code == "provider_rejected" and exc.http_status in {401, 403}:
            guidance = (
                "The credential can reach connector resources but account identity could not be "
                "verified. Review identity permissions/scopes before relying on account evidence."
            )
            action = CredentialNextAction.REVIEW_SCOPES
        else:
            guidance = (
                "Connector access is reachable but account identity could not be verified. Retry "
                "identity verification before changing credentials."
            )
            action = CredentialNextAction.RETRY
        return CredentialLifecycle(
            provider=provider,
            state=CredentialLifecycleState.IDENTITY_UNVERIFIED,
            next_action=action,
            configured=True,
            reachable=True,
            identity_verified=False,
            http_status=exc.http_status,
            guidance=guidance,
        )

    return CredentialLifecycle(
        provider=provider,
        state=CredentialLifecycleState.VERIFIED,
        next_action=CredentialNextAction.NONE,
        configured=True,
        reachable=True,
        identity_verified=True,
        http_status=check.http_status,
        identity=identity,
        guidance="The provider credential is reachable and its account identity is verified.",
    )
