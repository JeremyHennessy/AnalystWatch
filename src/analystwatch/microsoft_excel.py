from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

import httpx
import pandas as pd

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class MicrosoftExcelLocation:
    drive_id: str
    item_id: str
    table_name: str
    worksheet_name: str | None = None
    page_size: int = 500


@dataclass
class MicrosoftExcelResult:
    available: bool
    dataframe: pd.DataFrame | None = None
    http_status: int | None = None
    response_ms: float | None = None
    source_modified_at: datetime | None = None
    response_etag: str | None = None
    error: str | None = None


def parse_microsoft_excel_location(location: str) -> MicrosoftExcelLocation:
    """Parse an AnalystWatch Microsoft Excel table location.

    Format:
      m365://<drive-id>/<item-id>?table=<table-name>[&worksheet=<sheet>][&page_size=500]
    """
    parsed = urlparse(location)
    if parsed.scheme != "m365":
        raise ValueError("Microsoft Excel location must start with m365://")
    drive_id = parsed.netloc.strip()
    item_id = parsed.path.lstrip("/").strip()
    query = parse_qs(parsed.query)
    table_name = (query.get("table") or [""])[0].strip()
    worksheet_name = (query.get("worksheet") or [None])[0]
    if worksheet_name is not None:
        worksheet_name = worksheet_name.strip() or None
    raw_page_size = (query.get("page_size") or ["500"])[0]
    try:
        page_size = int(raw_page_size)
    except ValueError as exc:
        raise ValueError("Microsoft Excel page_size must be an integer") from exc
    if not drive_id or not item_id or not table_name:
        raise ValueError("Microsoft Excel location requires drive ID, item ID, and table name")
    if page_size < 1 or page_size > 5000:
        raise ValueError("Microsoft Excel page_size must be between 1 and 5000")
    return MicrosoftExcelLocation(
        drive_id=drive_id,
        item_id=item_id,
        table_name=table_name,
        worksheet_name=worksheet_name,
        page_size=page_size,
    )


def _graph_path(location: MicrosoftExcelLocation, suffix: str) -> str:
    drive = quote(location.drive_id, safe="")
    item = quote(location.item_id, safe="")
    table = quote(location.table_name, safe="")
    base = f"{GRAPH_ROOT}/drives/{drive}/items/{item}/workbook"
    if location.worksheet_name:
        sheet = quote(location.worksheet_name, safe="")
        base += f"/worksheets/{sheet}"
    return f"{base}/tables/{table}/{suffix}"


def _request(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
) -> httpx.Response:
    response = client.get(url, headers=headers)
    if response.status_code < 200 or response.status_code >= 300:
        raise MicrosoftGraphResponseError(response.status_code)
    return response


class MicrosoftGraphResponseError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"Microsoft Graph returned HTTP {status_code}")
        self.status_code = status_code


def read_microsoft_excel_table(
    location_text: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    client: httpx.Client | None = None,
) -> MicrosoftExcelResult:
    if "Authorization" not in headers:
        return MicrosoftExcelResult(
            available=False,
            error=(
                "Microsoft Excel sources require an Authorization request-header environment "
                "reference containing a delegated Microsoft Graph bearer token."
            ),
        )

    try:
        location = parse_microsoft_excel_location(location_text)
    except ValueError as exc:
        return MicrosoftExcelResult(available=False, error=str(exc))

    owns_client = client is None
    active_client = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    last_status: int | None = None
    try:
        drive = quote(location.drive_id, safe="")
        item = quote(location.item_id, safe="")
        metadata_url = (
            f"{GRAPH_ROOT}/drives/{drive}/items/{item}"
            "?$select=id,name,eTag,lastModifiedDateTime,webUrl"
        )
        metadata_response = _request(active_client, metadata_url, headers)
        last_status = metadata_response.status_code
        metadata = metadata_response.json()

        columns_response = _request(
            active_client,
            _graph_path(location, "columns") + "?$select=name,index",
            headers,
        )
        last_status = columns_response.status_code
        column_items = columns_response.json().get("value", [])
        columns = [item.get("name") for item in column_items if isinstance(item.get("name"), str)]
        if not columns:
            return MicrosoftExcelResult(
                available=False,
                http_status=last_status,
                response_ms=(time.perf_counter() - started) * 1000,
                error="Microsoft Excel table returned no usable column names.",
            )

        rows: list[list[object]] = []
        skip = 0
        while True:
            rows_url = _graph_path(location, "rows") + f"?$top={location.page_size}&$skip={skip}"
            rows_response = _request(active_client, rows_url, headers)
            last_status = rows_response.status_code
            payload = rows_response.json()
            page_items = payload.get("value", [])
            if not isinstance(page_items, list):
                raise ValueError("Microsoft Graph rows response did not contain a value array")
            for row in page_items:
                values = row.get("values") if isinstance(row, dict) else None
                if isinstance(values, list) and values and isinstance(values[0], list):
                    rows.append(values[0])
            next_link = payload.get("@odata.nextLink")
            if isinstance(next_link, str) and next_link:
                if not next_link.startswith(GRAPH_ROOT + "/"):
                    raise ValueError("Microsoft Graph returned an unexpected pagination URL")
                next_response = _request(active_client, next_link, headers)
                last_status = next_response.status_code
                payload = next_response.json()
                page_items = payload.get("value", [])
                if not isinstance(page_items, list):
                    raise ValueError("Microsoft Graph rows response did not contain a value array")
                for row in page_items:
                    values = row.get("values") if isinstance(row, dict) else None
                    if isinstance(values, list) and values and isinstance(values[0], list):
                        rows.append(values[0])
                while isinstance(payload.get("@odata.nextLink"), str):
                    next_url = payload["@odata.nextLink"]
                    if not next_url.startswith(GRAPH_ROOT + "/"):
                        raise ValueError("Microsoft Graph returned an unexpected pagination URL")
                    next_response = _request(active_client, next_url, headers)
                    last_status = next_response.status_code
                    payload = next_response.json()
                    extra_items = payload.get("value", [])
                    if not isinstance(extra_items, list):
                        raise ValueError("Microsoft Graph rows response did not contain a value array")
                    for row in extra_items:
                        values = row.get("values") if isinstance(row, dict) else None
                        if isinstance(values, list) and values and isinstance(values[0], list):
                            rows.append(values[0])
                break
            if len(page_items) < location.page_size:
                break
            skip += len(page_items)

        width = len(columns)
        normalized_rows = [
            (row[:width] + [None] * width)[:width] if len(row) < width else row[:width]
            for row in rows
        ]
        modified = None
        modified_text = metadata.get("lastModifiedDateTime")
        if isinstance(modified_text, str) and modified_text:
            modified = datetime.fromisoformat(modified_text.replace("Z", "+00:00"))
        return MicrosoftExcelResult(
            available=True,
            dataframe=pd.DataFrame(normalized_rows, columns=columns),
            http_status=last_status,
            response_ms=(time.perf_counter() - started) * 1000,
            source_modified_at=modified,
            response_etag=metadata.get("eTag") if isinstance(metadata.get("eTag"), str) else None,
        )
    except MicrosoftGraphResponseError as exc:
        return MicrosoftExcelResult(
            available=False,
            http_status=exc.status_code,
            response_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    except (httpx.HTTPError, ValueError) as exc:
        return MicrosoftExcelResult(
            available=False,
            http_status=last_status,
            response_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if owns_client:
            active_client.close()
