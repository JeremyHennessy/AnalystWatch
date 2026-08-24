from __future__ import annotations

import httpx

from analystwatch.connection_discovery import ConnectionProvider
from analystwatch.connection_lifecycle import (
    CredentialLifecycleState,
    CredentialNextAction,
    credential_lifecycle,
)


def test_missing_credential_requires_configuration_without_network(monkeypatch) -> None:
    monkeypatch.delenv("AW_GOOGLE_AUTH", raising=False)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    lifecycle = credential_lifecycle("google", "AW_GOOGLE_AUTH", client=client)
    client.close()

    assert lifecycle.state == CredentialLifecycleState.NEEDS_CREDENTIAL
    assert lifecycle.next_action == CredentialNextAction.CONFIGURE
    assert lifecycle.configured is False
    assert lifecycle.reachable is False
    assert lifecycle.identity_verified is False
    assert lifecycle.identity is None
    assert calls == 0
    assert "AW_GOOGLE_AUTH" not in lifecycle.model_dump_json()


def test_rejected_connector_credential_requires_reconnect(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer rejected-token")

    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "x"}))
    )
    lifecycle = credential_lifecycle("microsoft", "AW_MICROSOFT_AUTH", client=client)
    client.close()

    assert lifecycle.state == CredentialLifecycleState.REJECTED
    assert lifecycle.next_action == CredentialNextAction.RECONNECT
    assert lifecycle.configured is True
    assert lifecycle.reachable is False
    assert lifecycle.http_status == 401
    assert lifecycle.identity is None
    assert "rejected-token" not in lifecycle.model_dump_json()


def test_verified_lifecycle_requires_reachability_and_identity(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer valid-token")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1.0/me/drives":
            return httpx.Response(200, json={"value": [{"id": "drive-1"}]})
        if request.url.path == "/v1.0/me":
            return httpx.Response(
                200,
                json={
                    "id": "user-123",
                    "displayName": "Analyst User",
                    "mail": "analyst@example.com",
                },
            )
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    lifecycle = credential_lifecycle(
        ConnectionProvider.MICROSOFT,
        "AW_MICROSOFT_AUTH",
        client=client,
    )
    client.close()

    assert lifecycle.state == CredentialLifecycleState.VERIFIED
    assert lifecycle.next_action == CredentialNextAction.NONE
    assert lifecycle.reachable is True
    assert lifecycle.identity_verified is True
    assert lifecycle.identity is not None
    assert lifecycle.identity.subject_id == "user-123"
    assert paths == ["/v1.0/me/drives", "/v1.0/me"]


def test_identity_scope_rejection_does_not_redefine_connector_reachability(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer file-token")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/me/drives":
            return httpx.Response(200, json={"value": [{"id": "drive-1"}]})
        if request.url.path == "/v1.0/me":
            return httpx.Response(403, json={"error": {"message": "private scope detail"}})
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    lifecycle = credential_lifecycle("microsoft", "AW_MICROSOFT_AUTH", client=client)
    client.close()

    assert lifecycle.state == CredentialLifecycleState.IDENTITY_UNVERIFIED
    assert lifecycle.next_action == CredentialNextAction.REVIEW_SCOPES
    assert lifecycle.reachable is True
    assert lifecycle.identity_verified is False
    assert lifecycle.http_status == 403
    assert "private scope detail" not in lifecycle.model_dump_json()


def test_transport_failure_recommends_retry_not_reconnect(monkeypatch) -> None:
    monkeypatch.setenv("AW_GOOGLE_AUTH", "Bearer valid-token")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network detail", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    lifecycle = credential_lifecycle("google", "AW_GOOGLE_AUTH", client=client)
    client.close()

    assert lifecycle.state == CredentialLifecycleState.UNAVAILABLE
    assert lifecycle.next_action == CredentialNextAction.RETRY
    assert lifecycle.configured is True
    assert lifecycle.reachable is False
    assert lifecycle.identity is None
    assert "network detail" not in lifecycle.model_dump_json()
