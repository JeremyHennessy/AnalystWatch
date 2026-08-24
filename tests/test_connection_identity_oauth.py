from __future__ import annotations

import httpx
import pytest

from analystwatch.connection_discovery import ConnectionDiscoveryError
from analystwatch.connection_identity import inspect_connection_identity_with_access_token


def test_microsoft_oauth_access_token_verifies_graph_identity_without_environment() -> None:
    token = "oauth-microsoft-token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/me"
        assert request.headers["Authorization"] == f"Bearer {token}"
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
        identity = inspect_connection_identity_with_access_token(
            "microsoft",
            token,
            client=client,
        )

    assert identity.subject_id == "microsoft-subject"
    assert identity.display_name == "Connected Analyst"
    assert identity.email == "analyst@example.com"
    assert token not in identity.model_dump_json()


def test_google_oauth_access_token_verifies_drive_permission_identity() -> None:
    token = "oauth-google-token"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/drive/v3/about"
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(
            200,
            json={
                "user": {
                    "permissionId": "google-permission-subject",
                    "displayName": "Connected Analyst",
                    "emailAddress": "analyst@example.com",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        identity = inspect_connection_identity_with_access_token(
            "google",
            token,
            client=client,
        )

    assert identity.subject_id == "google-permission-subject"
    assert identity.display_name == "Connected Analyst"
    assert identity.email == "analyst@example.com"
    assert token not in identity.model_dump_json()


def test_oauth_identity_token_and_provider_rejection_are_never_echoed() -> None:
    token = "secret-oauth-access-token"
    provider_body = "secret-provider-body"

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(403, json={"error": provider_body})
        )
    ) as client:
        with pytest.raises(ConnectionDiscoveryError) as exc:
            inspect_connection_identity_with_access_token("microsoft", token, client=client)

    assert token not in str(exc.value)
    assert provider_body not in str(exc.value)

    for invalid in ["", " bad-token ", "line\nbreak"]:
        with pytest.raises(ConnectionDiscoveryError, match="not usable") as invalid_exc:
            inspect_connection_identity_with_access_token("google", invalid)
        if invalid:
            assert invalid not in str(invalid_exc.value)
