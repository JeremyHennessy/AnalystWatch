from __future__ import annotations

from urllib.parse import quote

import httpx

from .connection_discovery import (
    DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    DEFAULT_MAX_PAGES,
    GOOGLE_DRIVE_ROOT,
    GOOGLE_SHEETS_ROOT,
    GRAPH_ROOT,
    ConnectionCheck,
    ConnectionDiscoveryError,
    ConnectionProvider,
    GoogleSheetOption,
    GoogleSpreadsheetOption,
    MicrosoftDriveOption,
    MicrosoftTableOption,
    MicrosoftWorkbookOption,
    _active_client,
    _graph_collection,
    _location_identifier,
    _parse_datetime,
    _request_json,
)
from .connection_identity import MAX_OAUTH_ACCESS_TOKEN_CHARS

STORED_OAUTH_REFERENCE = "stored_oauth"


def _oauth_headers(provider: ConnectionProvider, access_token: str) -> dict[str, str]:
    if (
        not isinstance(access_token, str)
        or not access_token
        or access_token != access_token.strip()
        or len(access_token) > MAX_OAUTH_ACCESS_TOKEN_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in access_token)
    ):
        raise ConnectionDiscoveryError(
            provider,
            "invalid_credential",
            "Stored OAuth access token is not usable for provider discovery.",
        )
    return {"Authorization": f"Bearer {access_token}"}


def check_connection_with_access_token(
    provider: ConnectionProvider | str,
    access_token: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> ConnectionCheck:
    provider = ConnectionProvider(provider)
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _oauth_headers(provider, access_token)
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
            environment_variable=STORED_OAUTH_REFERENCE,
            configured=True,
            reachable=True,
            http_status=status,
        )
    except ConnectionDiscoveryError as exc:
        return ConnectionCheck(
            provider=provider,
            environment_variable=STORED_OAUTH_REFERENCE,
            configured=True,
            reachable=False,
            http_status=exc.http_status,
            error=str(exc),
        )
    finally:
        if owns_client:
            active_client.close()


def list_microsoft_drives_with_access_token(
    access_token: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    client: httpx.Client | None = None,
) -> list[MicrosoftDriveOption]:
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _oauth_headers(ConnectionProvider.MICROSOFT, access_token)
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
                    drive_type=(
                        item.get("driveType")
                        if isinstance(item.get("driveType"), str)
                        else None
                    ),
                    web_url=item.get("webUrl") if isinstance(item.get("webUrl"), str) else None,
                )
            )
        return drives
    finally:
        if owns_client:
            active_client.close()


def search_microsoft_workbooks_with_access_token(
    access_token: str,
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
        headers = _oauth_headers(ConnectionProvider.MICROSOFT, access_token)
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
            workbooks.append(
                MicrosoftWorkbookOption(
                    drive_id=drive_id,
                    item_id=item_id,
                    name=name,
                    web_url=item.get("webUrl") if isinstance(item.get("webUrl"), str) else None,
                    modified_at=_parse_datetime(item.get("lastModifiedDateTime")),
                )
            )
        return workbooks
    finally:
        if owns_client:
            active_client.close()


def list_microsoft_tables_with_access_token(
    access_token: str,
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
        headers = _oauth_headers(ConnectionProvider.MICROSOFT, access_token)
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


def list_google_spreadsheets_with_access_token(
    access_token: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    max_pages: int = DEFAULT_MAX_PAGES,
    client: httpx.Client | None = None,
) -> list[GoogleSpreadsheetOption]:
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _oauth_headers(ConnectionProvider.GOOGLE, access_token)
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
                        web_view_link=(
                            item.get("webViewLink")
                            if isinstance(item.get("webViewLink"), str)
                            else None
                        ),
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


def list_google_sheets_with_access_token(
    access_token: str,
    spreadsheet_id: str,
    *,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> list[GoogleSheetOption]:
    spreadsheet_id = _location_identifier(spreadsheet_id, "Google spreadsheet ID")
    active_client, owns_client = _active_client(client, timeout_seconds)
    try:
        headers = _oauth_headers(ConnectionProvider.GOOGLE, access_token)
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
                    row_count=(
                        row_count if isinstance(row_count, int) and row_count >= 0 else None
                    ),
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
