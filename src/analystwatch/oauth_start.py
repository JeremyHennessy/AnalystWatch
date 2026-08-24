from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from .connection_discovery import ConnectionProvider
from .credential_crypto import CredentialKeyring
from .oauth_authorization import begin_authorization_transaction
from .oauth_authorization_store import OAuthAuthorizationStore
from .oauth_provider_config import OAuthProviderRuntimeConfig


def begin_persisted_oauth_authorization(
    store: OAuthAuthorizationStore,
    keyring: CredentialKeyring,
    config: OAuthProviderRuntimeConfig,
    *,
    workspace_id: str,
    user_id: str,
    credential_id: str,
    now: datetime,
) -> str:
    started = begin_authorization_transaction(
        keyring,
        workspace_id=workspace_id,
        user_id=user_id,
        provider=config.public.provider,
        credential_id=credential_id,
        now=now,
    )
    authorization_url = build_provider_authorization_url(config, started)
    store.create(started.transaction)
    return authorization_url


def build_provider_authorization_url(config: OAuthProviderRuntimeConfig, started) -> str:
    public = config.public
    parameters = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": public.redirect_uri,
        "scope": " ".join(public.scopes),
        "state": started.state,
        "code_challenge": started.code_challenge,
        "code_challenge_method": started.code_challenge_method,
    }
    if public.provider == ConnectionProvider.MICROSOFT:
        parameters["response_mode"] = "query"
    elif public.provider == ConnectionProvider.GOOGLE:
        parameters["access_type"] = "offline"
        parameters["include_granted_scopes"] = "true"
    else:  # pragma: no cover - config model constrains this today
        raise ValueError("Unsupported OAuth provider")
    return f"{public.authorization_endpoint}?{urlencode(parameters)}"
