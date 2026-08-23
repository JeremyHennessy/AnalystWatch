from __future__ import annotations

import os
from datetime import datetime
from enum import Enum
from urllib.parse import quote, urlencode, urlparse

import httpx
from pydantic import BaseModel, Field

from .google_sheets import parse_google_sheets_location
from .microsoft_excel import parse_microsoft_excel_location

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GOOGLE_DRIVE_ROOT = "https://www.googleapis.com/drive/v3"
GOOGLE_SHEETS_ROOT = "https://sheets.googleapis.com/v4"
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_PAGES = 10


class ConnectionProvider(str, Enum):
    MICROSOFT = "microsoft"
    GOOGLE = "google"


class ConnectionCheck(BaseModel):
    provider: ConnectionProvider
    environment_variable: str
    configured: bool
    reachable: bool
    http_status: int | None = None
    error: str | None = None


class MicrosoftDriveOption(BaseModel):
    id: str
    name: str
    drive_type: str | None = None
    web_url: str | None = None


class MicrosoftWorkbookOption(BaseModel):
    drive_id: str
    item_id: str
    name: str
    web_url: str | None = None
    modified_at: datetime | None = None


class MicrosoftTableOption(BaseModel):
    id: str
    name: str


class GoogleSpreadsheetOption(BaseModel):
    id: str
    name: str
    modified_at: datetime | None = None
    web_view_link: str | None = None


class GoogleSheetOption(BaseModel):
    sheet_id: int = Field(ge=0)
    title: str
    index: int = Field(ge=0)
    row_count: int | None = Field(default=None, ge=0)
    column_count: int | None = Field(default=None, ge=0)


class ConnectionDiscoveryError(RuntimeError):
    def __init__(
        self,
        provider: ConnectionProvider,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.http_status = http_status


def _provider_label(provider: ConnectionProvider) -> str:
    if provider == ConnectionProvider.MICROSOFT:
        return "Microsoft Graph"
    return "Google Workspace"


def _validate_environment_variable(environment_variable: str) -> str:
    if not environment_variable or environment_variable != environment_variable.strip():
        raise ValueError("Authorization environment-variable name must be non-empty and trimmed")
    return environment_variable


def _authorization_headers(
    provider: ConnectionProvider,
    environment_variable: str,
) -> dict[str, str]:
    environment_variable = _validate_environment_variable(environment_variable)
    token = os.environ.get(environment_variable)
    if token is None or not token.strip():
        raise ConnectionDiscoveryError(
            provider,
            "credential_missing",
            f"Authorization environment variable '{environment_variable}' is not configured.",
        )
    return {"Authorization": token}


def _safe_json_response(
    provider: ConnectionProvider,
    response: httpx.Response,
) -> dict[str, object]:
    if response.status_code < 200 or response.status_code >= 300:
        raise ConnectionDiscoveryError(
            provider,
            "provider_rejected",
            f"{_provider_label(provider)} returned HTTP {response.status_code}.",
            http_status=response.status_code,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ConnectionDiscoveryError(
            provider,
            "invalid_response",
            f"{_provider_label(provider)} returned unusable JSON.",
            http_status=response.status_code,
        ) from exc
    if not isinstance(payload, dict):
        raise ConnectionDiscoveryError(
            provider,
            "invalid_response",
            f"{_provider_label(provider)} returned an unexpected response shape.",
            http_status=response.status_code,
        )
    return payload


def _request_json(
    provider: ConnectionProvider,
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    *,
    params: dict[str, object] | None = None,
) -> tuple[dict[str, object], int]:
    try:
        response = client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise ConnectionDiscoveryError(
            provider,
            "request_failed",
            f"{_provider_label(provider)} request failed ({type(exc).__name__}).",
        ) from exc
    return _safe_json_response(provider, response), response.status_code


def _validate_graph_next_link(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConnectionDiscoveryError(
            ConnectionProvider.MICROSOFT,
            "invalid_pagination",
            "Microsoft Graph returned an invalid pagination link.",
        )
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com":
        raise ConnectionDiscoveryError(
            ConnectionProvider.MICROSOFT,
            "invalid_pagination",
            "Microsoft Graph returned an unexpected pagination host.",
        )
    if not parsed.path.startswith("/v1.0/"):
        raise ConnectionDiscoveryError(
            ConnectionProvider.MICROSOFT,
            "invalid_pagination",
            "Microsoft Graph returned an unexpected pagination path.",
        )
    return value


def _graph_collection(
    url: str,
    headers: dict[str, str],
    client: httpx.Client,
    *,
    params: dict[str, object] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list[object]:
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    items: list[object] = []
    current_url = url
    current_params = params
    for _ in range(max_pages):
        payload, _ = _request_json(
            ConnectionProvider.MICROSOFT,
            client,
            current_url,
            headers,
            params=current_params,
        )
        page = payload.get("value")
        if not isinstance(page, list):
            raise ConnectionDiscoveryError(
                ConnectionProvider.MICROSOFT,
                "invalid_response",
                "Microsoft Graph collection response did not contain a value array.",
            )
        items.extend(page)
        next_link = _validate_graph_next_link(payload.get("@odata.nextLink"))
        if next_link is None:
            return items
        current_url = next_link
        current_params = None
    raise ConnectionDiscoveryError(
        ConnectionProvider.MICROSOFT,
        "pagination_limit",
        f"Microsoft Graph discovery exceeded the {max_pages}-page safety limit.",
    )


def _active_client(
    client: httpx.Client | None,
    timeout_seconds: float,
) -> tuple[httpx.Client, bool]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    if client is not None:
        return client, False
    return httpx.Client(timeout=timeout_seconds), True


def check_connection(
    provider: ConnectionProvider | str,
    environment_variable: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> ConnectionCheck:
    provider = ConnectionProvider(provider)
    environment_variable = _validate_environment_variable(environment_variable)
    if not os.environ.get(environment_variable, "").strip():
        return ConnectionCheck(
            provider=provider,
            environment_variable=environment_variable,
            configured=False,
            reachable=False,
            error=f"Authorization environment variable '{environment_variable}' is not configured.",
        )

    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _authorization_headers(provider, environment_variable)
        if provider == ConnectionProvider.MICROSOFT:
            _, status = _request_json(
                provider,
                active_client,
                f"{GRAPH_ROOT}/me/drives",
                headers,
                params={"$select": "id", "$top": 1},
            )
        else:
            _, status = _request_json(
                provider,
                active_client,
                f"{GOOGLE_DRIVE_ROOT}/files",
                headers,
                params={
                    "pageSize": 1,
                    "spaces": "drive",
                    "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                    "fields": "files(id)",
                },
            )
        return ConnectionCheck(
            provider=provider,
            environment_variable=environment_variable,
            configured=True,
            reachable=True,
            http_status=status,
        )
    except ConnectionDiscoveryError as exc:
        return ConnectionCheck(
            provider=provider,
            environment_variable=environment_variable,
            configured=True,
            reachable=False,
            http_status=exc.http_status,
            error=str(exc),
        )
    finally:
        if owns_client:
            active_client.close()


def list_microsoft_drives(
    environment_variable: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    client: httpx.Client | None = None,
) -> list[MicrosoftDriveOption]:
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _authorization_headers(ConnectionProvider.MICROSOFT, environment_variable)
        raw_items = _graph_collection(
            f"{GRAPH_ROOT}/me/drives",
            headers,
            active_client,
            params={"$select": "id,name,driveType,webUrl", "$top": 100},
            max_pages=max_pages,
        )
        drives: list[MicrosoftDriveOption] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            drive_id = item.get("id")
            name = item.get("name")
            if not isinstance(drive_id, str) or not drive_id:
                continue
            if not isinstance(name, str) or not name:
                continue
            drives.append(
                MicrosoftDriveOption(
                    id=drive_id,
                    name=name,
                    drive_type=item.get("driveType")
                    if isinstance(item.get("driveType"), str)
                    else None,
                    web_url=item.get("webUrl") if isinstance(item.get("webUrl"), str) else None,
                )
            )
        return drives
    finally:
        if owns_client:
            active_client.close()


def search_microsoft_workbooks(
    environment_variable: str,
    drive_id: str,
    query: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    client: httpx.Client | None = None,
) -> list[MicrosoftWorkbookOption]:
    drive_id = _location_identifier(drive_id, "Microsoft drive ID")
    if not query or query != query.strip():
        raise ValueError("Microsoft workbook search query must be non-empty and trimmed")
    if len(query) > 200:
        raise ValueError("Microsoft workbook search query must not exceed 200 characters")
    escaped_query = quote(query.replace("'", "''"), safe="")
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _authorization_headers(ConnectionProvider.MICROSOFT, environment_variable)
        raw_items = _graph_collection(
            f"{GRAPH_ROOT}/drives/{quote(drive_id, safe='')}/root/search(q='{escaped_query}')",
            headers,
            active_client,
            params={
                "$select": "id,name,webUrl,lastModifiedDateTime,file",
                "$top": 100,
            },
            max_pages=max_pages,
        )
        workbooks: list[MicrosoftWorkbookOption] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            name = item.get("name")
            if not isinstance(item_id, str) or not item_id:
                continue
            if not isinstance(name, str) or not name.lower().endswith(".xlsx"):
                continue
            if not isinstance(item.get("file"), dict):
                continue
            modified_at = _parse_datetime(item.get("lastModifiedDateTime"))
            workbooks.append(
                MicrosoftWorkbookOption(
                    drive_id=drive_id,
                    item_id=item_id,
                    name=name,
                    web_url=item.get("webUrl") if isinstance(item.get("webUrl"), str) else None,
                    modified_at=modified_at,
                )
            )
        return workbooks
    finally:
        if owns_client:
            active_client.close()


def list_microsoft_tables(
    environment_variable: str,
    drive_id: str,
    item_id: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    client: httpx.Client | None = None,
) -> list[MicrosoftTableOption]:
    drive_id = _location_identifier(drive_id, "Microsoft drive ID")
    item_id = _location_identifier(item_id, "Microsoft workbook item ID")
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _authorization_headers(ConnectionProvider.MICROSOFT, environment_variable)
        raw_items = _graph_collection(
            (
                f"{GRAPH_ROOT}/drives/{quote(drive_id, safe='')}/items/"
                f"{quote(item_id, safe='')}/workbook/tables"
            ),
            headers,
            active_client,
            params={"$select": "id,name", "$top": 100},
            max_pages=max_pages,
        )
        tables: list[MicrosoftTableOption] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            table_id = item.get("id")
            name = item.get("name")
            if isinstance(table_id, str) and table_id and isinstance(name, str) and name:
                tables.append(MicrosoftTableOption(id=table_id, name=name))
        return tables
    finally:
        if owns_client:
            active_client.close()


def list_google_spreadsheets(
    environment_variable: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    client: httpx.Client | None = None,
) -> list[GoogleSpreadsheetOption]:
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _authorization_headers(ConnectionProvider.GOOGLE, environment_variable)
        spreadsheets: list[GoogleSpreadsheetOption] = []
        page_token: str | None = None
        for _ in range(max_pages):
            params: dict[str, object] = {
                "pageSize": 100,
                "spaces": "drive",
                "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                "orderBy": "modifiedTime desc,name",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "fields": "nextPageToken,files(id,name,modifiedTime,webViewLink)",
            }
            if page_token is not None:
                params["pageToken"] = page_token
            payload, _ = _request_json(
                ConnectionProvider.GOOGLE,
                active_client,
                f"{GOOGLE_DRIVE_ROOT}/files",
                headers,
                params=params,
            )
            files = payload.get("files")
            if not isinstance(files, list):
                raise ConnectionDiscoveryError(
                    ConnectionProvider.GOOGLE,
                    "invalid_response",
                    "Google Drive response did not contain a files array.",
                )
            for item in files:
                if not isinstance(item, dict):
                    continue
                file_id = item.get("id")
                name = item.get("name")
                if not isinstance(file_id, str) or not file_id:
                    continue
                if not isinstance(name, str) or not name:
                    continue
                spreadsheets.append(
                    GoogleSpreadsheetOption(
                        id=file_id,
                        name=name,
                        modified_at=_parse_datetime(item.get("modifiedTime")),
                        web_view_link=item.get("webViewLink")
                        if isinstance(item.get("webViewLink"), str)
                        else None,
                    )
                )
            raw_next = payload.get("nextPageToken")
            if raw_next is None:
                return spreadsheets
            if not isinstance(raw_next, str) or not raw_next:
                raise ConnectionDiscoveryError(
                    ConnectionProvider.GOOGLE,
                    "invalid_pagination",
                    "Google Drive returned an invalid page token.",
                )
            page_token = raw_next
        raise ConnectionDiscoveryError(
            ConnectionProvider.GOOGLE,
            "pagination_limit",
            f"Google Drive discovery exceeded the {max_pages}-page safety limit.",
        )
    finally:
        if owns_client:
            active_client.close()


def list_google_sheets(
    environment_variable: str,
    spreadsheet_id: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> list[GoogleSheetOption]:
    spreadsheet_id = _location_identifier(spreadsheet_id, "Google spreadsheet ID")
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _authorization_headers(ConnectionProvider.GOOGLE, environment_variable)
        payload, _ = _request_json(
            ConnectionProvider.GOOGLE,
            active_client,
            f"{GOOGLE_SHEETS_ROOT}/spreadsheets/{quote(spreadsheet_id, safe='')}",
            headers,
            params={
                "fields": (
                    "sheets.properties(sheetId,title,index,sheetType,"
                    "gridProperties(rowCount,columnCount))"
                )
            },
        )
        raw_sheets = payload.get("sheets")
        if not isinstance(raw_sheets, list):
            raise ConnectionDiscoveryError(
                ConnectionProvider.GOOGLE,
                "invalid_response",
                "Google Sheets response did not contain a sheets array.",
            )
        sheets: list[GoogleSheetOption] = []
        for item in raw_sheets:
            properties = item.get("properties") if isinstance(item, dict) else None
            if not isinstance(properties, dict):
                continue
            if properties.get("sheetType", "GRID") != "GRID":
                continue
            sheet_id = properties.get("sheetId")
            title = properties.get("title")
            index = properties.get("index")
            if not isinstance(sheet_id, int) or sheet_id < 0:
                continue
            if not isinstance(title, str) or not title:
                continue
            if not isinstance(index, int) or index < 0:
                continue
            grid = properties.get("gridProperties")
            row_count = grid.get("rowCount") if isinstance(grid, dict) else None
            column_count = grid.get("columnCount") if isinstance(grid, dict) else None
            sheets.append(
                GoogleSheetOption(
                    sheet_id=sheet_id,
                    title=title,
                    index=index,
                    row_count=row_count if isinstance(row_count, int) and row_count >= 0 else None,
                    column_count=(
                        column_count
                        if isinstance(column_count, int) and column_count >= 0
                        else None
                    ),
                )
            )
        return sorted(sheets, key=lambda sheet: sheet.index)
    finally:
        if owns_client:
            active_client.close()


def build_microsoft_excel_location(
    drive_id: str,
    item_id: str,
    table_name: str,
    *,
    worksheet_name: str | None = None,
) -> str:
    drive_id = _location_identifier(drive_id, "Microsoft drive ID")
    item_id = _location_identifier(item_id, "Microsoft workbook item ID")
    table_name = _trimmed_text(table_name, "Microsoft Excel table name")
    params = {"table": table_name}
    if worksheet_name is not None:
        params["worksheet"] = _trimmed_text(worksheet_name, "Microsoft worksheet name")
    location = f"m365://{drive_id}/{item_id}?{urlencode(params)}"
    parse_microsoft_excel_location(location)
    return location


def build_google_sheets_location(
    spreadsheet_id: str,
    range_name: str,
    *,
    header_row: int = 1,
) -> str:
    spreadsheet_id = _location_identifier(spreadsheet_id, "Google spreadsheet ID")
    range_name = _trimmed_text(range_name, "Google Sheets A1 range")
    if header_row < 1 or header_row > 1000:
        raise ValueError("Google Sheets header_row must be between 1 and 1000")
    location = f"gsheets://{spreadsheet_id}?{urlencode({'range': range_name, 'header_row': header_row})}"
    parse_google_sheets_location(location)
    return location


def _location_identifier(value: str, label: str) -> str:
    value = _trimmed_text(value, label)
    if any(character in value for character in "/?#:"):
        raise ValueError(f"{label} contains a URI-reserved character")
    return value


def _trimmed_text(value: str, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty and trimmed")
    return value


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
