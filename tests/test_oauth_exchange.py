from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from analystwatch.oauth_exchange import OAuthTokenExchangeError, exchange_authorization_code
from analystwatch.oauth_provider_config import load_oauth_provider_config

NOW = datetime(2026, 8, 24, 16, 30, tzinfo=timezone.utc)


def environment() -> dict[str, str]:
    return {
        "ANALYSTWATCH_PUBLIC_BASE_URL": "https://analystwatch.example",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID": "microsoft-client",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET": "microsoft-secret",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
    }


def test_microsoft_exchange_uses_exact_pkce_confidential_web_request() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["data"] = parse_qs(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "token_type": "Bearer",
                "scope": "User.Read Files.Read.All offline_access",
                "expires_in": 3600,
                "access_token": "microsoft-access-token",
                "refresh_token": "microsoft-refresh-token",
                "id_token": "ignored-id-token",
            },
        )

    config = load_oauth_provider_config("microsoft", environment())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        tokens = exchange_authorization_code(
            config,
            code="microsoft-code",
            code_verifier="v" * 43,
            now=NOW,
            client=client,
        )

    assert captured["url"] == config.public.token_endpoint
    assert captured["data"] == {
        "client_id": ["microsoft-client"],
        "client_secret": ["microsoft-secret"],
        "code": ["microsoft-code"],
        "redirect_uri": ["https://analystwatch.example/api/oauth/microsoft/callback"],
        "grant_type": ["authorization_code"],
        "code_verifier": ["v" * 43],
        "scope": [" ".join(config.public.scopes)],
    }
    assert tokens.access_token == "microsoft-access-token"
    assert tokens.refresh_token == "microsoft-refresh-token"
    assert tokens.scopes == ("Files.Read.All", "User.Read", "offline_access")
    assert tokens.access_token_expires_at == NOW + timedelta(hours=1)
    assert "microsoft-access-token" not in repr(tokens)
    assert "microsoft-refresh-token" not in repr(tokens)


def test_google_exchange_omits_scope_parameter_and_allows_missing_refresh_token() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["data"] = parse_qs(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "token_type": "bearer",
                "scope": "openid email",
                "expires_in": "3600",
                "access_token": "google-access-token",
            },
        )

    config = load_oauth_provider_config("google", environment())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        tokens = exchange_authorization_code(
            config,
            code="google-code",
            code_verifier="k" * 43,
            now=NOW,
            client=client,
        )

    assert captured["data"] == {
        "client_id": ["google-client"],
        "client_secret": ["google-secret"],
        "code": ["google-code"],
        "redirect_uri": ["https://analystwatch.example/api/oauth/google/callback"],
        "grant_type": ["authorization_code"],
        "code_verifier": ["k" * 43],
    }
    assert tokens.access_token == "google-access-token"
    assert tokens.refresh_token is None
    assert tokens.scopes == ("email", "openid")


def test_rejected_or_invalid_provider_responses_never_echo_secret_material() -> None:
    config = load_oauth_provider_config("google", environment())
    code = "provider-secret-code"
    body_secret = "provider-secret-error-body"

    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=body_secret)

    with httpx.Client(transport=httpx.MockTransport(rejected)) as client:
        with pytest.raises(OAuthTokenExchangeError, match="HTTP 400") as exc:
            exchange_authorization_code(
                config,
                code=code,
                code_verifier="p" * 43,
                now=NOW,
                client=client,
            )
    assert code not in str(exc.value)
    assert body_secret not in str(exc.value)
    assert "google-secret" not in str(exc.value)

    invalid_payloads = [
        {"token_type": "Bearer", "expires_in": 3600, "access_token": " bad "},
        {"token_type": "MAC", "expires_in": 3600, "access_token": "token"},
        {"token_type": "Bearer", "expires_in": 0, "access_token": "token"},
        {"token_type": "Bearer", "expires_in": 9999999, "access_token": "token"},
        {"token_type": "Bearer", "expires_in": 3600, "access_token": "token", "scope": 7},
    ]
    for payload in invalid_payloads:
        transport = httpx.MockTransport(
            lambda _request, value=payload: httpx.Response(200, json=value)
        )
        with httpx.Client(transport=transport) as client:
            with pytest.raises(OAuthTokenExchangeError):
                exchange_authorization_code(
                    config,
                    code="safe-code",
                    code_verifier="q" * 43,
                    now=NOW,
                    client=client,
                )


def test_invalid_code_and_request_failure_are_bounded() -> None:
    config = load_oauth_provider_config("microsoft", environment())
    with pytest.raises(OAuthTokenExchangeError, match="authorization code is invalid"):
        exchange_authorization_code(
            config,
            code=" bad-code ",
            code_verifier="q" * 43,
            now=NOW,
        )

    def failed(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("contains-provider-secret")

    with httpx.Client(transport=httpx.MockTransport(failed)) as client:
        with pytest.raises(OAuthTokenExchangeError, match="request failed") as exc:
            exchange_authorization_code(
                config,
                code="safe-code",
                code_verifier="q" * 43,
                now=NOW,
                client=client,
            )
    assert "contains-provider-secret" not in str(exc.value)
