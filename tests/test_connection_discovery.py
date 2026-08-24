from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from analystwatch.connection_discovery import (
    ConnectionDiscoveryError,
    ConnectionProvider,
    build_google_sheets_location,
    build_microsoft_excel_location,
    check_connection,
    list_google_sheets,
    list_google_spreadsheets,
    list_microsoft_drives,
    list_microsoft_tables,
    search_microsoft_workbooks,
)
from analystwatch.google_sheets import parse_google_sheets_location
from analystwatch.microsoft_excel import parse_microsoft_excel_location


def test_missing_connection_credential_does_not_make_network_request(monkeypatch) -> None:
    monkeypatch.delenv("AW_MICROSOFT_AUTH", raising=False)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = check_connection(
        ConnectionProvider.MICROSOFT,
        "AW_MICROSOFT_AUTH",
        client=client,
    )
    client.close()

    assert result.configured is False
    assert result.reachable is False
    assert result.http_status is None
    assert "AW_MICROSOFT_AUTH" in (result.error or "")
    assert calls == 0


def test_connection_rejection_never_echoes_token_or_provider_body(monkeypatch) -> None:
    token = "Bearer super-secret-token"
    provider_secret = "private-provider-error"
    monkeypatch.setenv("AW_GOOGLE_AUTH", token)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == token
        return httpx.Response(403, json={"error": {"message": provider_secret}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = check_connection(
        ConnectionProvider.GOOGLE,
        "AW_GOOGLE_AUTH",
        client=client,
    )
    client.close()

    serialized = result.model_dump_json()
    assert result.configured is True
    assert result.reachable is False
    assert result.http_status == 403
    assert "Google Workspace returned HTTP 403" in (result.error or "")
    assert token not in serialized
    assert "super-secret-token" not in serialized
    assert provider_secret not in serialized


def test_microsoft_connection_check_uses_delegated_drive_surface(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer delegated-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/me/drives"
        assert request.url.params["$select"] == "id"
        assert request.url.params["$top"] == "1"
        assert request.headers["Authorization"] == "Bearer delegated-token"
        return httpx.Response(200, json={"value": [{"id": "drive-1"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = check_connection("microsoft", "AW_MICROSOFT_AUTH", client=client)
    client.close()

    assert result.configured is True
    assert result.reachable is True
    assert result.http_status == 200
    assert result.error is None


def test_microsoft_drive_discovery_follows_only_graph_next_links(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer delegated-token")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Authorization"] == "Bearer delegated-token"
        if calls == 1:
            assert request.url.path == "/v1.0/me/drives"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "drive-1",
                            "name": "OneDrive",
                            "driveType": "business",
                            "webUrl": "https://example.sharepoint.com/one",
                        }
                    ],
                    "@odata.nextLink": (
                        "https://graph.microsoft.com/v1.0/me/drives?$skipToken=next"
                    ),
                },
            )
        assert str(request.url).startswith("https://graph.microsoft.com/v1.0/me/drives")
        return httpx.Response(
            200,
            json={"value": [{"id": "drive-2", "name": "Shared Documents"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    drives = list_microsoft_drives("AW_MICROSOFT_AUTH", client=client)
    client.close()

    assert [drive.id for drive in drives] == ["drive-1", "drive-2"]
    assert drives[0].drive_type == "business"
    assert calls == 2


def test_microsoft_discovery_rejects_unexpected_pagination_host(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer delegated-token")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": "https://attacker.example/v1.0/me/drives?token=x",
                },
            )
        )
    )

    with pytest.raises(ConnectionDiscoveryError, match="unexpected pagination host") as exc:
        list_microsoft_drives("AW_MICROSOFT_AUTH", client=client)
    client.close()

    assert exc.value.code == "invalid_pagination"


def test_microsoft_workbook_search_filters_to_excel_files(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer delegated-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/drives/drive-1/root/search" in request.url.path
        assert request.headers["Authorization"] == "Bearer delegated-token"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "item-1",
                        "name": "Forecast.xlsx",
                        "file": {
                            "mimeType": (
                                "application/vnd.openxmlformats-officedocument."
                                "spreadsheetml.sheet"
                            )
                        },
                        "webUrl": "https://example.sharepoint.com/Forecast.xlsx",
                        "lastModifiedDateTime": "2026-08-23T15:00:00Z",
                    },
                    {"id": "item-2", "name": "Forecast.pdf", "file": {}},
                    {"id": "folder-1", "name": "Forecast.xlsx", "folder": {}},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    workbooks = search_microsoft_workbooks(
        "AW_MICROSOFT_AUTH",
        "drive-1",
        "Forecast",
        client=client,
    )
    client.close()

    assert len(workbooks) == 1
    assert workbooks[0].item_id == "item-1"
    assert workbooks[0].name == "Forecast.xlsx"
    assert workbooks[0].modified_at == datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc)


def test_microsoft_table_discovery_returns_existing_connector_selection(monkeypatch) -> None:
    monkeypatch.setenv("AW_MICROSOFT_AUTH", "Bearer delegated-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/drives/drive-1/items/item-1/workbook/tables")
        return httpx.Response(
            200,
            json={"value": [{"id": "1", "name": "Sales Table"}, {"id": "2", "name": "Rates"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    tables = list_microsoft_tables(
        "AW_MICROSOFT_AUTH",
        "drive-1",
        "item-1",
        client=client,
    )
    client.close()

    assert [table.name for table in tables] == ["Sales Table", "Rates"]
    location = build_microsoft_excel_location("drive-1", "item-1", tables[0].name)
    parsed = parse_microsoft_excel_location(location)
    assert parsed.drive_id == "drive-1"
    assert parsed.item_id == "item-1"
    assert parsed.table_name == "Sales Table"


def test_google_connection_check_uses_drive_metadata_discovery(monkeypatch) -> None:
    monkeypatch.setenv("AW_GOOGLE_AUTH", "Bearer oauth-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/drive/v3/files"
        assert request.url.params["pageSize"] == "1"
        assert "application/vnd.google-apps.spreadsheet" in request.url.params["q"]
        assert request.headers["Authorization"] == "Bearer oauth-token"
        return httpx.Response(200, json={"files": [{"id": "sheet-1"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = check_connection("google", "AW_GOOGLE_AUTH", client=client)
    client.close()

    assert result.configured is True
    assert result.reachable is True
    assert result.http_status == 200


def test_google_spreadsheet_discovery_follows_page_tokens(monkeypatch) -> None:
    monkeypatch.setenv("AW_GOOGLE_AUTH", "Bearer oauth-token")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/drive/v3/files"
        assert request.url.params["supportsAllDrives"] == "true"
        assert request.url.params["includeItemsFromAllDrives"] == "true"
        if calls == 1:
            assert "pageToken" not in request.url.params
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "id": "spreadsheet-1",
                            "name": "Pipeline",
                            "modifiedTime": "2026-08-23T16:00:00Z",
                            "webViewLink": "https://docs.google.com/spreadsheets/d/spreadsheet-1",
                        }
                    ],
                    "nextPageToken": "page-2",
                },
            )
        assert request.url.params["pageToken"] == "page-2"
        return httpx.Response(
            200,
            json={"files": [{"id": "spreadsheet-2", "name": "Claims"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    spreadsheets = list_google_spreadsheets("AW_GOOGLE_AUTH", client=client)
    client.close()

    assert [spreadsheet.id for spreadsheet in spreadsheets] == [
        "spreadsheet-1",
        "spreadsheet-2",
    ]
    assert spreadsheets[0].modified_at == datetime(2026, 8, 23, 16, 0, tzinfo=timezone.utc)
    assert calls == 2


def test_google_sheet_discovery_uses_metadata_only_and_filters_non_grid(monkeypatch) -> None:
    monkeypatch.setenv("AW_GOOGLE_AUTH", "Bearer oauth-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v4/spreadsheets/spreadsheet-1"
        assert "sheets.properties" in request.url.params["fields"]
        return httpx.Response(
            200,
            json={
                "sheets": [
                    {
                        "properties": {
                            "sheetId": 10,
                            "title": "Data",
                            "index": 1,
                            "sheetType": "GRID",
                            "gridProperties": {"rowCount": 500, "columnCount": 20},
                        }
                    },
                    {
                        "properties": {
                            "sheetId": 5,
                            "title": "Overview",
                            "index": 0,
                            "sheetType": "GRID",
                            "gridProperties": {"rowCount": 50, "columnCount": 8},
                        }
                    },
                    {
                        "properties": {
                            "sheetId": 99,
                            "title": "Connected Data",
                            "index": 2,
                            "sheetType": "DATA_SOURCE",
                        }
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sheets = list_google_sheets("AW_GOOGLE_AUTH", "spreadsheet-1", client=client)
    client.close()

    assert [sheet.title for sheet in sheets] == ["Overview", "Data"]
    assert sheets[0].row_count == 50
    assert sheets[1].column_count == 20


def test_google_location_builder_round_trips_existing_connector_contract() -> None:
    location = build_google_sheets_location(
        "spreadsheet-1",
        "Raw Data!A3:F500",
        header_row=2,
    )
    parsed = parse_google_sheets_location(location)

    assert parsed.spreadsheet_id == "spreadsheet-1"
    assert parsed.range_name == "Raw Data!A3:F500"
    assert parsed.header_row == 2


def test_location_builders_reject_uri_breaking_identifiers() -> None:
    with pytest.raises(ValueError, match="URI-reserved"):
        build_microsoft_excel_location("drive/1", "item-1", "Sales")
    with pytest.raises(ValueError, match="URI-reserved"):
        build_google_sheets_location("spreadsheet?1", "Data!A1:B10")


def test_discovery_pagination_limits_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("AW_GOOGLE_AUTH", "Bearer oauth-token")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"files": [], "nextPageToken": "still-more"},
            )
        )
    )

    with pytest.raises(ConnectionDiscoveryError, match="1-page safety limit") as exc:
        list_google_spreadsheets("AW_GOOGLE_AUTH", client=client, max_pages=1)
    client.close()

    assert exc.value.code == "pagination_limit"
