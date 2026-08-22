from __future__ import annotations

from datetime import datetime, timezone

import httpx

from analystwatch.ingest import ingest_source
from analystwatch.microsoft_excel import parse_microsoft_excel_location
from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.preflight import preflight_source


def _source(location: str = "m365://drive-1/item-1?table=Sales") -> SourceDefinition:
    return SourceDefinition(
        id="sales-workbook",
        name="Sales Workbook",
        source_type=SourceType.MICROSOFT_EXCEL,
        location=location,
        config=MonitoringConfig(
            request_header_env={"Authorization": "MS_GRAPH_AUTH"},
            numeric_fields=["Amount"],
            unique_keys=["ID"],
        ),
    )


def test_microsoft_excel_location_parses_table_and_worksheet():
    location = parse_microsoft_excel_location(
        "m365://drive-1/item-1?table=Sales%20Table&worksheet=Data&page_size=250"
    )
    assert location.drive_id == "drive-1"
    assert location.item_id == "item-1"
    assert location.table_name == "Sales Table"
    assert location.worksheet_name == "Data"
    assert location.page_size == 250


def test_microsoft_excel_ingestion_normalizes_table_rows(monkeypatch):
    monkeypatch.setenv("MS_GRAPH_AUTH", "Bearer delegated-token")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer delegated-token"
        path = request.url.path
        if path.endswith("/items/item-1"):
            return httpx.Response(
                200,
                json={
                    "id": "item-1",
                    "name": "Sales.xlsx",
                    "eTag": '"etag-1"',
                    "lastModifiedDateTime": "2026-08-21T21:30:00Z",
                },
            )
        if path.endswith("/tables/Sales/columns"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"index": 0, "name": "ID"},
                        {"index": 1, "name": "Amount"},
                        {"index": 2, "name": "Status"},
                    ]
                },
            )
        if path.endswith("/tables/Sales/rows"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"index": 0, "values": [[1, 100.5, "Open"]]},
                        {"index": 1, "values": [[2, 125.0, "Closed"]]},
                    ]
                },
            )
        raise AssertionError(f"Unexpected Graph request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = ingest_source(_source(), client=client)
    client.close()

    assert result.available is True
    assert result.dataframe is not None
    assert result.dataframe.to_dict(orient="records") == [
        {"ID": 1, "Amount": 100.5, "Status": "Open"},
        {"ID": 2, "Amount": 125.0, "Status": "Closed"},
    ]
    assert result.source_modified_at == datetime(2026, 8, 21, 21, 30, tzinfo=timezone.utc)
    assert result.response_etag == '"etag-1"'
    assert any("%24select=id" in item or "$select=id" in item for item in requests)


def test_microsoft_excel_rows_follow_graph_next_link(monkeypatch):
    monkeypatch.setenv("MS_GRAPH_AUTH", "Bearer delegated-token")
    page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_calls
        path = request.url.path
        if path.endswith("/items/item-1"):
            return httpx.Response(200, json={"id": "item-1"})
        if path.endswith("/tables/Sales/columns"):
            return httpx.Response(200, json={"value": [{"index": 0, "name": "ID"}]})
        if path.endswith("/tables/Sales/rows"):
            page_calls += 1
            if page_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "value": [{"index": 0, "values": [[1]]}],
                        "@odata.nextLink": (
                            "https://graph.microsoft.com/v1.0/drives/drive-1/items/item-1/"
                            "workbook/tables/Sales/rows?$top=1&$skip=1"
                        ),
                    },
                )
            return httpx.Response(200, json={"value": [{"index": 1, "values": [[2]]}]})
        raise AssertionError(f"Unexpected Graph request: {request.url}")

    source = _source("m365://drive-1/item-1?table=Sales&page_size=1")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = ingest_source(source, client=client)
    client.close()

    assert result.available is True
    assert result.dataframe is not None
    assert result.dataframe["ID"].tolist() == [1, 2]
    assert page_calls == 2


def test_microsoft_excel_missing_delegated_auth_is_availability_failure(monkeypatch):
    monkeypatch.delenv("MS_GRAPH_AUTH", raising=False)
    result = ingest_source(_source())
    assert result.available is False
    assert result.error is not None
    assert "MS_GRAPH_AUTH" in result.error


def test_microsoft_excel_graph_rejection_records_status(monkeypatch):
    monkeypatch.setenv("MS_GRAPH_AUTH", "Bearer bad-token")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"error": {}}))
    )
    result = ingest_source(_source(), client=client)
    client.close()
    assert result.available is False
    assert result.http_status == 403
    assert result.error == "Microsoft Graph returned HTTP 403"


def test_microsoft_excel_preflight_uses_existing_contract_pipeline(monkeypatch):
    monkeypatch.setenv("MS_GRAPH_AUTH", "Bearer delegated-token")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/items/item-1"):
            return httpx.Response(
                200,
                json={"id": "item-1", "lastModifiedDateTime": "2026-08-21T21:30:00Z"},
            )
        if path.endswith("/tables/Sales/columns"):
            return httpx.Response(
                200,
                json={"value": [{"name": "ID"}, {"name": "Amount"}]},
            )
        if path.endswith("/tables/Sales/rows"):
            return httpx.Response(
                200,
                json={"value": [{"values": [[1, "100.50"]]}, {"values": [[2, "125.00"]]}]},
            )
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = preflight_source(_source(), client=client)
    client.close()
    assert result.ready is True
    assert result.profile is not None
    assert result.profile.row_count == 2
    assert result.profile.columns["Amount"].numeric is not None
