from __future__ import annotations

import pytest

from analystwatch.oauth_provider_config import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_ENDPOINT,
    MICROSOFT_AUTHORIZATION_ENDPOINT,
    MICROSOFT_SCOPES,
    MICROSOFT_TOKEN_ENDPOINT,
    OAuthProviderConfigurationError,
    load_oauth_provider_config,
)


def environment(base_url: str = "https://analystwatch.example") -> dict[str, str]:
    return {
        "ANALYSTWATCH_PUBLIC_BASE_URL": base_url,
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID": "microsoft-client-id",
        "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET": "microsoft-client-secret",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID": "google-client-id.apps.googleusercontent.com",
        "ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET": "google-client-secret",
    }


def test_microsoft_oauth_contract_uses_fixed_organizations_endpoints_and_read_scopes() -> None:
    config = load_oauth_provider_config("microsoft", environment())

    assert config.public.authorization_endpoint == MICROSOFT_AUTHORIZATION_ENDPOINT
    assert config.public.token_endpoint == MICROSOFT_TOKEN_ENDPOINT
    assert config.public.authorization_endpoint == (
        "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
    )
    assert config.public.token_endpoint == (
        "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"
    )
    assert config.public.redirect_uri == "https://analystwatch.example/api/oauth/microsoft/callback"
    assert config.public.scopes == MICROSOFT_SCOPES
    assert set(config.public.scopes) == {
        "openid",
        "profile",
        "email",
        "offline_access",
        "User.Read",
        "Files.Read.All",
    }


def test_google_oauth_contract_uses_fixed_endpoints_and_read_only_scopes() -> None:
    config = load_oauth_provider_config("google", environment())

    assert config.public.authorization_endpoint == GOOGLE_AUTHORIZATION_ENDPOINT
    assert config.public.token_endpoint == GOOGLE_TOKEN_ENDPOINT
    assert config.public.authorization_endpoint == "https://accounts.google.com/o/oauth2/v2/auth"
    assert config.public.token_endpoint == "https://oauth2.googleapis.com/token"
    assert config.public.redirect_uri == "https://analystwatch.example/api/oauth/google/callback"
    assert config.public.scopes == GOOGLE_SCOPES
    assert set(config.public.scopes) == {
        "openid",
        "profile",
        "email",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    }


def test_runtime_secret_is_not_part_of_public_config_or_repr() -> None:
    config = load_oauth_provider_config("microsoft", environment())
    serialized = config.public.model_dump_json()
    rendered = repr(config)

    assert config.client_secret == "microsoft-client-secret"
    assert "microsoft-client-secret" not in serialized
    assert "microsoft-client-secret" not in rendered
    assert "ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET" not in serialized
    assert "client_secret=<redacted>" in rendered


def test_redirect_uri_is_derived_from_one_validated_public_base_url() -> None:
    https = load_oauth_provider_config(
        "google",
        environment("https://Aw.Example:8443/"),
    )
    local = load_oauth_provider_config(
        "microsoft",
        environment("http://127.0.0.1:8080"),
    )

    assert https.public.redirect_uri == "https://aw.example:8443/api/oauth/google/callback"
    assert local.public.redirect_uri == "http://127.0.0.1:8080/api/oauth/microsoft/callback"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://analystwatch.example",
        "ftp://analystwatch.example",
        "https://user:password@analystwatch.example",
        "https://analystwatch.example/app",
        "https://analystwatch.example?next=evil",
        "https://analystwatch.example#fragment",
        "",
        " https://analystwatch.example",
    ],
)
def test_public_base_url_fails_closed_for_unsafe_shapes(base_url: str) -> None:
    with pytest.raises(OAuthProviderConfigurationError):
        load_oauth_provider_config("microsoft", environment(base_url))


def test_loopback_http_is_limited_to_local_hosts() -> None:
    for base_url in [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ]:
        config = load_oauth_provider_config("google", environment(base_url))
        assert config.public.redirect_uri.endswith("/api/oauth/google/callback")


def test_missing_client_configuration_fails_without_echoing_other_secret_material() -> None:
    values = environment()
    values.pop("ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET")
    values["UNRELATED_SECRET"] = "do-not-echo-this-secret"

    with pytest.raises(OAuthProviderConfigurationError, match="Google OAuth client secret") as exc:
        load_oauth_provider_config("google", values)

    assert "do-not-echo-this-secret" not in str(exc.value)
    assert "google-client-id.apps.googleusercontent.com" not in str(exc.value)


def test_callers_cannot_override_provider_endpoints_scopes_or_secret_env_names() -> None:
    values = environment()
    values.update(
        {
            "ANALYSTWATCH_OAUTH_AUTHORIZATION_ENDPOINT": "https://evil.example/authorize",
            "ANALYSTWATCH_OAUTH_TOKEN_ENDPOINT": "https://evil.example/token",
            "ANALYSTWATCH_OAUTH_SCOPES": "admin.everything",
            "ANALYSTWATCH_OAUTH_SECRET_ENV": "UNRELATED_SECRET",
            "UNRELATED_SECRET": "attacker-selected-secret",
        }
    )

    microsoft = load_oauth_provider_config("microsoft", values)
    google = load_oauth_provider_config("google", values)

    assert microsoft.public.authorization_endpoint == MICROSOFT_AUTHORIZATION_ENDPOINT
    assert microsoft.public.token_endpoint == MICROSOFT_TOKEN_ENDPOINT
    assert microsoft.public.scopes == MICROSOFT_SCOPES
    assert microsoft.client_secret == "microsoft-client-secret"
    assert google.public.authorization_endpoint == GOOGLE_AUTHORIZATION_ENDPOINT
    assert google.public.token_endpoint == GOOGLE_TOKEN_ENDPOINT
    assert google.public.scopes == GOOGLE_SCOPES
    assert google.client_secret == "google-client-secret"
