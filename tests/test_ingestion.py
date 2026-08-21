from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd

from analystwatch.ingest import ingest_source
from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType


def test_csv_xlsx_and_json_ingestion(tmp_path: Path):
    frame = pd.DataFrame({"id": [1, 2], "amount": [10.0, 20.0]})
    csv_path = tmp_path / "data.csv"
    xlsx_path = tmp_path / "data.xlsx"
    json_path = tmp_path / "data.json"
    frame.to_csv(csv_path, index=False)
    frame.to_excel(xlsx_path, index=False, sheet_name="Sheet1")
    json_path.write_text(json.dumps({"records": frame.to_dict(orient="records")}), encoding="utf-8")

    sources = [
        SourceDefinition(id="csv", name="CSV", source_type=SourceType.CSV, location=str(csv_path)),
        SourceDefinition(
            id="xlsx",
            name="Excel",
            source_type=SourceType.XLSX,
            location=str(xlsx_path),
            config=MonitoringConfig(sheet_name="Sheet1"),
        ),
        SourceDefinition(
            id="json", name="JSON", source_type=SourceType.JSON, location=str(json_path)
        ),
    ]

    for source in sources:
        result = ingest_source(source)
        assert result.available is True
        assert result.dataframe is not None
        assert list(result.dataframe.columns) == ["id", "amount"]
        assert len(result.dataframe) == 2


def test_nested_json_record_path(tmp_path: Path):
    path = tmp_path / "nested.json"
    path.write_text(json.dumps({"payload": {"items": [{"id": 1}, {"id": 2}]}}), encoding="utf-8")
    source = SourceDefinition(
        id="json",
        name="JSON",
        source_type=SourceType.JSON,
        location=str(path),
        config=MonitoringConfig(json_record_path="payload.items"),
    )
    result = ingest_source(source)
    assert result.available is True
    assert result.dataframe is not None
    assert result.dataframe["id"].tolist() == [1, 2]


def test_rest_api_json_ingestion_records_status_and_timing():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    )
    client = httpx.Client(transport=transport)
    source = SourceDefinition(
        id="api",
        name="API",
        source_type=SourceType.API,
        location="https://example.test/data",
    )
    result = ingest_source(source, client=client)
    assert result.available is True
    assert result.http_status == 200
    assert result.response_ms is not None
    assert result.dataframe is not None
    assert len(result.dataframe) == 2
    client.close()


def test_unusable_api_response_is_availability_failure():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="unavailable"))
    client = httpx.Client(transport=transport)
    source = SourceDefinition(
        id="api",
        name="API",
        source_type=SourceType.API,
        location="https://example.test/data",
    )
    result = ingest_source(source, client=client)
    assert result.available is False
    assert result.http_status == 503
    assert result.error == "HTTP 503"
    client.close()
