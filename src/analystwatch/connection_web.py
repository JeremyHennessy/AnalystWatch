from __future__ import annotations

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
from .connection_identity import ConnectionAccountIdentity, inspect_connection_identity
from .connection_lifecycle import CredentialLifecycle, credential_lifecycle
from .oauth_web import configure_oauth_start_web

MICROSOFT_AUTH_ENV = "ANALYSTWATCH_MICROSOFT_AUTHORIZATION"
GOOGLE_AUTH_ENV = "ANALYSTWATCH_GOOGLE_AUTHORIZATION"


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


def configure_connection_web(app: FastAPI) -> None:
    def microsoft_check() -> PublicConnectionCheck:
        return _public_check(check_connection(ConnectionProvider.MICROSOFT, MICROSOFT_AUTH_ENV))

    def microsoft_identity() -> ConnectionAccountIdentity:
        return _validated_call(
            inspect_connection_identity,
            ConnectionProvider.MICROSOFT,
            MICROSOFT_AUTH_ENV,
        )

    def microsoft_lifecycle() -> CredentialLifecycle:
        return credential_lifecycle(ConnectionProvider.MICROSOFT, MICROSOFT_AUTH_ENV)

    def microsoft_drives() -> list[MicrosoftDriveOption]:
        return _validated_call(list_microsoft_drives, MICROSOFT_AUTH_ENV)

    def microsoft_workbooks(
        request: MicrosoftWorkbookSearchRequest,
    ) -> list[MicrosoftWorkbookOption]:
        return _validated_call(
            search_microsoft_workbooks,
            MICROSOFT_AUTH_ENV,
            request.drive_id,
            request.query,
        )

    def microsoft_tables(request: MicrosoftTablesRequest) -> list[MicrosoftTableOption]:
        return _validated_call(
            list_microsoft_tables,
            MICROSOFT_AUTH_ENV,
            request.drive_id,
            request.item_id,
        )

    def google_check() -> PublicConnectionCheck:
        return _public_check(check_connection(ConnectionProvider.GOOGLE, GOOGLE_AUTH_ENV))

    def google_identity() -> ConnectionAccountIdentity:
        return _validated_call(
            inspect_connection_identity,
            ConnectionProvider.GOOGLE,
            GOOGLE_AUTH_ENV,
        )

    def google_lifecycle() -> CredentialLifecycle:
        return credential_lifecycle(ConnectionProvider.GOOGLE, GOOGLE_AUTH_ENV)

    def google_spreadsheets() -> list[GoogleSpreadsheetOption]:
        return _validated_call(list_google_spreadsheets, GOOGLE_AUTH_ENV)

    def google_sheets(request: GoogleSheetsRequest) -> list[GoogleSheetOption]:
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
