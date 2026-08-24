from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .connection_discovery import ConnectionProvider
from .credential_persistence import PostgresCredentialStore, SQLiteCredentialStore
from .credential_runtime import CredentialKeyConfigurationError, load_credential_keyring
from .credential_store import CredentialStore
from .oauth_authorization import OAuthAuthorizationError
from .oauth_authorization_store import (
    OAuthAuthorizationStore,
    PostgresOAuthAuthorizationStore,
    SQLiteOAuthAuthorizationStore,
)
from .oauth_callback import (
    OAuthCallbackError,
    complete_oauth_authorization,
    consume_oauth_authorization_denial,
)
from .oauth_provider_config import (
    OAuthProviderConfigurationError,
    load_oauth_provider_config,
)
from .oauth_start import begin_persisted_oauth_authorization

LOCAL_OAUTH_USER_ID = "local-operator"


def configure_oauth_start_web(app: FastAPI) -> OAuthAuthorizationStore:
    authorization_store = _default_authorization_store(app)
    authorization_store.initialize()
    credential_store = _default_credential_store(app)
    credential_store.initialize()
    app.state.oauth_authorization_store = authorization_store
    app.state.oauth_credential_store = credential_store

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

    def callback_microsoft(
        state: str | None = None,
        code: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        return _callback_response(
            app,
            ConnectionProvider.MICROSOFT,
            state=state,
            code=code,
            provider_error=error,
        )

    def callback_google(
        state: str | None = None,
        code: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        return _callback_response(
            app,
            ConnectionProvider.GOOGLE,
            state=state,
            code=code,
            provider_error=error,
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
    app.add_api_route(
        "/api/oauth/microsoft/callback",
        callback_microsoft,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/api/oauth/google/callback",
        callback_google,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    return authorization_store


def _start_redirect(
    app: FastAPI,
    request: Request,
    provider: ConnectionProvider,
    credential_id: str,
) -> RedirectResponse:
    user_id = _request_user_id(request)
    try:
        if app.state.oauth_credential_store.get(app.state.workspace_id, credential_id) is not None:
            raise OAuthAuthorizationError(
                "Credential ID is already connected; use the explicit reconnect flow."
            )
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


def _callback_response(
    app: FastAPI,
    provider: ConnectionProvider,
    *,
    state: str | None,
    code: str | None,
    provider_error: str | None,
) -> HTMLResponse:
    if state is None:
        return _callback_page(False, "The connection callback was missing its security state.")
    if code is not None and provider_error is not None:
        return _callback_page(False, "The connection callback was malformed.")
    if code is None and provider_error is None:
        return _callback_page(False, "The connection callback did not contain a result.")
    if provider_error is not None and not _valid_provider_error(provider_error):
        return _callback_page(False, "The connection callback contained an invalid error code.")

    try:
        keyring = load_credential_keyring()
        now = datetime.now(timezone.utc)
        if provider_error is not None:
            consume_oauth_authorization_denial(
                app.state.oauth_authorization_store,
                keyring,
                provider=provider,
                workspace_id=app.state.workspace_id,
                state=state,
                now=now,
            )
            return _callback_page(
                False,
                "The provider did not complete the connection. Return to AnalystWatch to retry.",
            )

        config = load_oauth_provider_config(provider)
        complete_oauth_authorization(
            app.state.oauth_authorization_store,
            app.state.oauth_credential_store,
            keyring,
            config,
            provider=provider,
            workspace_id=app.state.workspace_id,
            state=state,
            code=code or "",
            now=now,
        )
    except (OAuthProviderConfigurationError, CredentialKeyConfigurationError) as exc:
        return _callback_page(False, str(exc), status_code=503)
    except OAuthCallbackError as exc:
        return _callback_page(False, str(exc))

    return _callback_page(
        True,
        "The provider connection was verified and encrypted successfully.",
        status_code=200,
    )


def _callback_page(success: bool, message: str, *, status_code: int = 400) -> HTMLResponse:
    title = "Connection complete" if success else "Connection not completed"
    body = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{title} · AnalystWatch</title></head><body>"
        f"<main><h1>{title}</h1><p>{message}</p>"
        "<p>You can close this page and return to AnalystWatch.</p></main></body></html>"
    )
    return HTMLResponse(content=body, status_code=status_code)


def _valid_provider_error(value: str) -> bool:
    if not value or value != value.strip() or len(value) > 256:
        return False
    return all(character.isalnum() or character in "_.-" for character in value)


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


def _default_credential_store(app: FastAPI) -> CredentialStore:
    raw_storage = app.state.storage
    if app.state.storage_backend == "postgres":
        dsn = getattr(raw_storage, "dsn", None)
        if not isinstance(dsn, str):
            raise ValueError("PostgreSQL credential store requires runtime DSN")
        return PostgresCredentialStore(dsn)

    path = getattr(raw_storage, "path", None)
    if not isinstance(path, Path):
        raise ValueError("SQLite credential store requires runtime database path")
    credential_path = path.with_suffix(path.suffix + ".credentials.db")
    return SQLiteCredentialStore(credential_path)
