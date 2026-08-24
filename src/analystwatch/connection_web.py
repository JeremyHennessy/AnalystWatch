from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .connection_discovery import (
    ConnectionCheck,
    ConnectionDiscoveryError,
    ConnectionProvider,
    GoogleSheetOption,
    GoogleSpreadsheetOption,
    MicrosoftDriveOption,
    MicrosoftTableOption,
    MicrosoftWorkbookOption,
    check_connection,
    list_google_sheets,
    list_google_spreadsheets,
    list_microsoft_drives,
    list_microsoft_tables,
    search_microsoft_workbooks,
)
from .connection_identity import (
    ConnectionAccountIdentity,
    inspect_connection_identity,
    inspect_connection_identity_with_access_token,
)
from .connection_lifecycle import (
    CredentialLifecycle,
    credential_lifecycle,
    credential_lifecycle_with_access_token,
)
from .connection_oauth import (
    check_connection_with_access_token,
    list_google_sheets_with_access_token,
    list_google_spreadsheets_with_access_token,
    list_microsoft_drives_with_access_token,
    list_microsoft_tables_with_access_token,
    search_microsoft_workbooks_with_access_token,
)
from .credential_crypto import CredentialCryptoError
from .credential_runtime import CredentialKeyConfigurationError, load_credential_keyring
from .credential_store import unseal_access_token
from .oauth_web import configure_oauth_start_web

MICROSOFT_AUTH_ENV = "ANALYSTWATCH_MICROSOFT_AUTHORIZATION"
GOOGLE_AUTH_ENV = "ANALYSTWATCH_GOOGLE_AUTHORIZATION"
DEFAULT_OAUTH_CREDENTIAL_IDS = {
    ConnectionProvider.MICROSOFT: "microsoft-primary",
    ConnectionProvider.GOOGLE: "google-primary",
}


class PublicConnectionCheck(BaseModel):
    provider: ConnectionProvider
    configured: bool
    reachable: bool
    http_status: int | None = None
    error: str | None = None


class MicrosoftWorkbookSearchRequest(BaseModel):
    drive_id: str
    query: str


class MicrosoftTablesRequest(BaseModel):
    drive_id: str
    item_id: str


class GoogleSheetsRequest(BaseModel):
    spreadsheet_id: str


def _public_check(check: ConnectionCheck) -> PublicConnectionCheck:
    error = check.error
    if not check.configured:
        error = "Server credential is not configured."
    return PublicConnectionCheck(
        provider=check.provider,
        configured=check.configured,
        reachable=check.reachable,
        http_status=check.http_status,
        error=error,
    )


def _discovery_error(exc: ConnectionDiscoveryError) -> HTTPException:
    if exc.code == "credential_missing":
        status_code = 409
    elif exc.code in {"provider_rejected", "request_failed"}:
        status_code = 502
    else:
        status_code = 422
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _validated_call(callable_, *args):
    try:
        return callable_(*args)
    except ConnectionDiscoveryError as exc:
        raise _discovery_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _stored_access_token(app: FastAPI, provider: ConnectionProvider) -> str | None:
    store = getattr(app.state, "oauth_credential_store", None)
    if store is None:
        return None
    credential_id = DEFAULT_OAUTH_CREDENTIAL_IDS[provider]
    record = store.get(app.state.workspace_id, credential_id)
    if record is None:
        return None
    if record.provider != provider:
        raise HTTPException(
            status_code=409,
            detail="Stored OAuth credential provider did not match the requested connection.",
        )
    if record.revoked_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Stored OAuth credential is revoked; reconnect before using this connection.",
        )
    if record.access_token_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=409,
            detail=(
                "Stored OAuth access token has expired; reconnect is required until refresh "
                "support is enabled."
            ),
        )
    try:
        keyring = load_credential_keyring()
        return unseal_access_token(record, keyring)
    except CredentialKeyConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CredentialCryptoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Stored OAuth credential could not be decrypted safely.",
        ) from exc


def configure_connection_web(app: FastAPI) -> None:
    def microsoft_check() -> PublicConnectionCheck:
        token = _stored_access_token(app, ConnectionProvider.MICROSOFT)
        if token is not None:
            return _public_check(
                check_connection_with_access_token(ConnectionProvider.MICROSOFT, token)
            )
        return _public_check(check_connection(ConnectionProvider.MICROSOFT, MICROSOFT_AUTH_ENV))

    def microsoft_identity() -> ConnectionAccountIdentity:
        token = _stored_access_token(app, ConnectionProvider.MICROSOFT)
        if token is not None:
            return _validated_call(
                inspect_connection_identity_with_access_token,
                ConnectionProvider.MICROSOFT,
                token,
            )
        return _validated_call(
            inspect_connection_identity,
            ConnectionProvider.MICROSOFT,
            MICROSOFT_AUTH_ENV,
        )

    def microsoft_lifecycle() -> CredentialLifecycle:
        token = _stored_access_token(app, ConnectionProvider.MICROSOFT)
        if token is not None:
            return credential_lifecycle_with_access_token(ConnectionProvider.MICROSOFT, token)
        return credential_lifecycle(ConnectionProvider.MICROSOFT, MICROSOFT_AUTH_ENV)

    def microsoft_drives() -> list[MicrosoftDriveOption]:
        token = _stored_access_token(app, ConnectionProvider.MICROSOFT)
        if token is not None:
            return _validated_call(list_microsoft_drives_with_access_token, token)
        return _validated_call(list_microsoft_drives, MICROSOFT_AUTH_ENV)

    def microsoft_workbooks(
        request: MicrosoftWorkbookSearchRequest,
    ) -> list[MicrosoftWorkbookOption]:
        token = _stored_access_token(app, ConnectionProvider.MICROSOFT)
        if token is not None:
            return _validated_call(
                search_microsoft_workbooks_with_access_token,
                token,
                request.drive_id,
                request.query,
            )
        return _validated_call(
            search_microsoft_workbooks,
            MICROSOFT_AUTH_ENV,
            request.drive_id,
            request.query,
        )

    def microsoft_tables(request: MicrosoftTablesRequest) -> list[MicrosoftTableOption]:
        token = _stored_access_token(app, ConnectionProvider.MICROSOFT)
        if token is not None:
            return _validated_call(
                list_microsoft_tables_with_access_token,
                token,
                request.drive_id,
                request.item_id,
            )
        return _validated_call(
            list_microsoft_tables,
            MICROSOFT_AUTH_ENV,
            request.drive_id,
            request.item_id,
        )

    def google_check() -> PublicConnectionCheck:
        token = _stored_access_token(app, ConnectionProvider.GOOGLE)
        if token is not None:
            return _public_check(
                check_connection_with_access_token(ConnectionProvider.GOOGLE, token)
            )
        return _public_check(check_connection(ConnectionProvider.GOOGLE, GOOGLE_AUTH_ENV))

    def google_identity() -> ConnectionAccountIdentity:
        token = _stored_access_token(app, ConnectionProvider.GOOGLE)
        if token is not None:
            return _validated_call(
                inspect_connection_identity_with_access_token,
                ConnectionProvider.GOOGLE,
                token,
            )
        return _validated_call(
            inspect_connection_identity,
            ConnectionProvider.GOOGLE,
            GOOGLE_AUTH_ENV,
        )

    def google_lifecycle() -> CredentialLifecycle:
        token = _stored_access_token(app, ConnectionProvider.GOOGLE)
        if token is not None:
            return credential_lifecycle_with_access_token(ConnectionProvider.GOOGLE, token)
        return credential_lifecycle(ConnectionProvider.GOOGLE, GOOGLE_AUTH_ENV)

    def google_spreadsheets() -> list[GoogleSpreadsheetOption]:
        token = _stored_access_token(app, ConnectionProvider.GOOGLE)
        if token is not None:
            return _validated_call(list_google_spreadsheets_with_access_token, token)
        return _validated_call(list_google_spreadsheets, GOOGLE_AUTH_ENV)

    def google_sheets(request: GoogleSheetsRequest) -> list[GoogleSheetOption]:
        token = _stored_access_token(app, ConnectionProvider.GOOGLE)
        if token is not None:
            return _validated_call(
                list_google_sheets_with_access_token,
                token,
                request.spreadsheet_id,
            )
        return _validated_call(
            list_google_sheets,
            GOOGLE_AUTH_ENV,
            request.spreadsheet_id,
        )

    app.add_api_route(
        "/api/connections/microsoft/check",
        microsoft_check,
        methods=["POST"],
        response_model=PublicConnectionCheck,
    )
    app.add_api_route(
        "/api/connections/microsoft/identity",
        microsoft_identity,
        methods=["POST"],
        response_model=ConnectionAccountIdentity,
    )
    app.add_api_route(
        "/api/connections/microsoft/lifecycle",
        microsoft_lifecycle,
        methods=["POST"],
        response_model=CredentialLifecycle,
    )
    app.add_api_route(
        "/api/connections/microsoft/drives",
        microsoft_drives,
        methods=["POST"],
        response_model=list[MicrosoftDriveOption],
    )
    app.add_api_route(
        "/api/connections/microsoft/workbooks",
        microsoft_workbooks,
        methods=["POST"],
        response_model=list[MicrosoftWorkbookOption],
    )
    app.add_api_route(
        "/api/connections/microsoft/tables",
        microsoft_tables,
        methods=["POST"],
        response_model=list[MicrosoftTableOption],
    )
    app.add_api_route(
        "/api/connections/google/check",
        google_check,
        methods=["POST"],
        response_model=PublicConnectionCheck,
    )
    app.add_api_route(
        "/api/connections/google/identity",
        google_identity,
        methods=["POST"],
        response_model=ConnectionAccountIdentity,
    )
    app.add_api_route(
        "/api/connections/google/lifecycle",
        google_lifecycle,
        methods=["POST"],
        response_model=CredentialLifecycle,
    )
    app.add_api_route(
        "/api/connections/google/spreadsheets",
        google_spreadsheets,
        methods=["POST"],
        response_model=list[GoogleSpreadsheetOption],
    )
    app.add_api_route(
        "/api/connections/google/sheets",
        google_sheets,
        methods=["POST"],
        response_model=list[GoogleSheetOption],
    )
    configure_oauth_start_web(app)
