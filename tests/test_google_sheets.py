from __future__ import annotations

import httpx

from analystwatch.google_sheets import (
    parse_google_sheets_location,
    public_google_sheets_location,
)
from analystwatch.ingest import ingest_source
from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.preflight import preflight_source


def _source(
    location: str = "gsheets://spreadsheet-1?range=Data%21A1%3AD100",
    *,
    expected_refresh_minutes: int | None = None,
    latest_date_field: str | None = None,
) -> SourceDefinition:
    return SourceDefinition(
        id="google-sales",
        name="Google Sales Sheet",
        source_type=SourceType.GOOGLE_SHEETS,
        location=location,
        config=MonitoringConfig(
            request_header_env={"Authorization": "GOOGLE_SHEETS_AUTH"},
            numeric_fields=["Amount"],
            unique_keys=["ID"],
            expected_refresh_minutes=expected_refresh_minutes,
            latest_date_field=latest_date_field,
        ),
    )


def test_google_sheets_location_parses_range_and_relative_header_row() -> None:
    location = parse_google_sheets_location(
        "gsheets://spreadsheet-1?range=Raw%20Data%21A3%3AF500&header_row=2"
    )
    assert location.spreadsheet_id == "spreadsheet-1"
    assert location.range_name == "Raw Data!A3:F500"
    assert location.header_row == 2
    assert public_google_sheets_location(
        "gsheets://spreadsheet-1?range=Raw%20Data%21A3%3AF500&header_row=2"
    ) == "Google Sheets · Raw Data!A3:F500"


def test_google_sheets_ingestion_reads_range_with_stable_rendering(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_AUTH", "Bearer oauth-token")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer oauth-token"
        assert request.url.path.endswith(
            "/spreadsheets/spreadsheet-1/values/Data!A1:D100"
        )
        assert request.url.params["majorDimension"] == "ROWS"
        assert request.url.params["valueRenderOption"] == "UNFORMATTED_VALUE"
        assert request.url.params["dateTimeRenderOption"] == "FORMATTED_STRING"
        return httpx.Response(
            200,
            headers={"ETag": '"sheet-etag"'},
            json={
                "range": "Data!A1:D100",
                "majorDimension": "ROWS",
                "values": [
                    ["ID", "Amount", "Status", "As Of"],
                    [1, 100.5, "Open", "2026-08-22"],
                    [2, 125.0, "Closed"],
                    [],
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = ingest_source(_source(), client=client)
    client.close()

    assert len(requests) == 1
    assert result.available is True
    assert result.http_status == 200
    assert result.response_etag == '"sheet-etag"'
    assert result.source_modified_at is None
    assert result.dataframe is not None
    assert result.dataframe.to_dict(orient="records") == [
        {"ID": 1, "Amount": 100.5, "Status": "Open", "As Of": "2026-08-22"},
        {"ID": 2, "Amount": 125.0, "Status": "Closed", "As Of": None},
    ]


def test_google_sheets_header_row_is_relative_to_returned_range(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_AUTH", "Bearer oauth-token")
    source = _source(
        "gsheets://spreadsheet-1?range=Data%21A5%3AC50&header_row=2"
    ).model_copy(
        update={
            "config": MonitoringConfig(
                request_header_env={"Authorization": "GOOGLE_SHEETS_AUTH"},
                numeric_fields=["Amount"],
                unique_keys=["ID"],
            )
        }
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "values": [
                        ["Generated", "2026-08-22"],
                        ["ID", "Amount", "Status"],
                        [1, 10.0, "Open"],
                    ]
                },
            )
        )
    )
    result = ingest_source(source, client=client)
    client.close()

    assert result.available is True
    assert result.dataframe is not None
    assert result.dataframe.columns.tolist() == ["ID", "Amount", "Status"]
    assert result.dataframe.iloc[0].to_dict() == {"ID": 1, "Amount": 10.0, "Status": "Open"}


def test_google_sheets_missing_auth_is_availability_failure(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_SHEETS_AUTH", raising=False)
    result = ingest_source(_source())
    assert result.available is False
    assert result.error is not None
    assert "GOOGLE_SHEETS_AUTH" in result.error


def test_google_sheets_provider_rejection_records_status(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_AUTH", "Bearer bad-token")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"error": {}}))
    )
    result = ingest_source(_source(), client=client)
    client.close()

    assert result.available is False
    assert result.http_status == 403
    assert result.error == "Google Sheets API returned HTTP 403"


def test_google_sheets_rejects_ambiguous_headers_and_wider_rows(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_AUTH", "Bearer oauth-token")
    payloads = [
        {"values": [["ID", "ID"], [1, 2]]},
        {"values": [["ID", ""], [1, 2]]},
        {"values": [["ID", "Amount"], [1, 2, 3]]},
    ]
    expected = ["duplicate column names", "empty column name", "more values than"]

    for payload, message in zip(payloads, expected, strict=True):
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request, body=payload: httpx.Response(200, json=body)
            )
        )
        result = ingest_source(_source(), client=client)
        client.close()
        assert result.available is False
        assert result.error is not None
        assert message in result.error


def test_google_sheets_preflight_reuses_existing_numeric_and_key_contracts(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_AUTH", "Bearer oauth-token")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "values": [
                        ["ID", "Amount", "As Of"],
                        [1, "100.50", "2026-08-22"],
                        [2, "125.00", "2026-08-22"],
                    ]
                },
            )
        )
    )
    result = preflight_source(_source(latest_date_field="As Of"), client=client)
    client.close()

    assert result.ready is True
    assert result.profile is not None
    assert result.profile.row_count == 2
    assert result.profile.columns["Amount"].numeric is not None
    assert result.profile.latest_date_field == "As Of"


def test_google_sheets_refresh_expectation_requires_content_date_evidence(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_AUTH", "Bearer oauth-token")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"values": [["ID", "Amount"], [1, 100.0], [2, 125.0]]},
            )
        )
    )
    result = preflight_source(_source(expected_refresh_minutes=60), client=client)
    client.close()

    assert result.ready is False
    assert any(issue.code == "freshness_unverifiable" for issue in result.issues)
