from __future__ import annotations

import httpx
import pytest

from analystwatch.connection_discovery import ConnectionDiscoveryError, ConnectionProvider
from analystwatch.connection_identity import inspect_connection_identity


def test_microsoft_identity_uses_me_and_falls_back_to_upn(monkeypatch) -> None:
    token = "Bearer microsoft-private-token"
    monkeypatch.setenv("AW_MICROSOFT_AUTH", token)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/me"
        assert request.url.params["$select"] == "id,displayName,mail,userPrincipalName"
        assert request.headers["Authorization"] == token
        return httpx.Response(
            200,
            json={
                "id": "user-123",
                "displayName": "Analyst User",
                "mail": None,
                "userPrincipalName": "analyst@example.com",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    identity = inspect_connection_identity(
        ConnectionProvider.MICROSOFT,
        "AW_MICROSOFT_AUTH",
        client=client,
    )
    client.close()

    assert identity.provider == ConnectionProvider.MICROSOFT
    assert identity.subject_id == "user-123"
    assert identity.display_name == "Analyst User"
    assert identity.email == "analyst@example.com"
    assert token not in identity.model_dump_json()
    assert "AW_MICROSOFT_AUTH" not in identity.model_dump_json()


def test_google_identity_uses_drive_about_user(monkeypatch) -> None:
    token = "Bearer google-private-token"
    monkeypatch.setenv("AW_GOOGLE_AUTH", token)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/drive/v3/about"
        assert request.url.params["fields"] == "user(displayName,emailAddress,permissionId)"
        assert request.headers["Authorization"] == token
        return httpx.Response(
            200,
            json={
                "user": {
                    "displayName": "Finance Analyst",
                    "emailAddress": "finance@example.com",
                    "permissionId": "permission-456",
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    identity = inspect_connection_identity("google", "AW_GOOGLE_AUTH", client=client)
    client.close()

    assert identity.provider == ConnectionProvider.GOOGLE
    assert identity.subject_id == "permission-456"
    assert identity.display_name == "Finance Analyst"
    assert identity.email == "finance@example.com"
    assert token not in identity.model_dump_json()
    assert "AW_GOOGLE_AUTH" not in identity.model_dump_json()


def test_identity_rejection_never_echoes_provider_body_or_token(monkeypatch) -> None:
    token = "Bearer secret-token"
    provider_body = "private-provider-diagnostic"
    monkeypatch.setenv("AW_MICROSOFT_AUTH", token)

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"error": {"message": provider_body}})
        )
    )
    with pytest.raises(ConnectionDiscoveryError) as exc:
        inspect_connection_identity("microsoft", "AW_MICROSOFT_AUTH", client=client)
    client.close()

    assert exc.value.code == "provider_rejected"
    assert token not in str(exc.value)
    assert provider_body not in str(exc.value)


def test_google_identity_fails_closed_without_user_object(monkeypatch) -> None:
    monkeypatch.setenv("AW_GOOGLE_AUTH", "Bearer token")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"user": None}))
    )

    with pytest.raises(ConnectionDiscoveryError, match="usable user object") as exc:
        inspect_connection_identity("google", "AW_GOOGLE_AUTH", client=client)
    client.close()

    assert exc.value.code == "invalid_identity"


def test_identity_rejects_oversized_provider_fields(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer token")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"id": "user-1", "displayName": "x" * 513},
            )
        )
    )

    with pytest.raises(ConnectionDiscoveryError, match="oversized displayName") as exc:
        inspect_connection_identity("microsoft", "AW_MICROSOFT_AUTH", client=client)
    client.close()

    assert exc.value.code == "invalid_identity"
