from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from .connection_discovery import ConnectionProvider
from .credential_runtime import CredentialKeyConfigurationError, load_credential_keyring
from .oauth_authorization import OAuthAuthorizationError
from .oauth_authorization_store import (
    OAuthAuthorizationStore,
    PostgresOAuthAuthorizationStore,
    SQLiteOAuthAuthorizationStore,
)
from .oauth_provider_config import (
    OAuthProviderConfigurationError,
    load_oauth_provider_config,
)
from .oauth_start import begin_persisted_oauth_authorization

LOCAL_OAUTH_USER_ID = "local-operator"


def configure_oauth_start_web(app: FastAPI) -> OAuthAuthorizationStore:
    store = _default_authorization_store(app)
    store.initialize()
    app.state.oauth_authorization_store = store

    def start_microsoft(request: Request, credential_id: str) -> RedirectResponse:
        return _start_redirect(
            app,
            request,
            ConnectionProvider.MICROSOFT,
            credential_id,
        )

    def start_google(request: Request, credential_id: str) -> RedirectResponse:
        return _start_redirect(
            app,
            request,
            ConnectionProvider.GOOGLE,
            credential_id,
        )

    app.add_api_route(
        "/api/oauth/microsoft/start",
        start_microsoft,
        methods=["POST"],
        response_class=RedirectResponse,
        status_code=303,
    )
    app.add_api_route(
        "/api/oauth/google/start",
        start_google,
        methods=["POST"],
        response_class=RedirectResponse,
        status_code=303,
    )
    return store


def _start_redirect(
    app: FastAPI,
    request: Request,
    provider: ConnectionProvider,
    credential_id: str,
) -> RedirectResponse:
    user_id = _request_user_id(request)
    try:
        config = load_oauth_provider_config(provider)
        keyring = load_credential_keyring()
        authorization_url = begin_persisted_oauth_authorization(
            app.state.oauth_authorization_store,
            keyring,
            config,
            workspace_id=app.state.workspace_id,
            user_id=user_id,
            credential_id=credential_id,
            now=datetime.now(timezone.utc),
        )
    except (OAuthProviderConfigurationError, CredentialKeyConfigurationError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OAuthAuthorizationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(url=authorization_url, status_code=303)


def _request_user_id(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return LOCAL_OAUTH_USER_ID
    return auth_context.principal.user_id


def _default_authorization_store(app: FastAPI) -> OAuthAuthorizationStore:
    raw_storage = app.state.storage
    if app.state.storage_backend == "postgres":
        dsn = getattr(raw_storage, "dsn", None)
        if not isinstance(dsn, str):
            raise ValueError("PostgreSQL OAuth store requires runtime DSN")
        return PostgresOAuthAuthorizationStore(dsn)

    path = getattr(raw_storage, "path", None)
    if not isinstance(path, Path):
        raise ValueError("SQLite OAuth store requires runtime database path")
    oauth_path = path.with_suffix(path.suffix + ".oauth.db")
    return SQLiteOAuthAuthorizationStore(oauth_path)
