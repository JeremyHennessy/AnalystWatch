from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlparse

import httpx
import pandas as pd

SHEETS_ROOT = "https://sheets.googleapis.com/v4"


@dataclass(frozen=True)
class GoogleSheetsLocation:
    spreadsheet_id: str
    range_name: str
    header_row: int = 1


@dataclass
class GoogleSheetsResult:
    available: bool
    dataframe: pd.DataFrame | None = None
    http_status: int | None = None
    response_ms: float | None = None
    response_etag: str | None = None
    error: str | None = None


class GoogleSheetsResponseError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"Google Sheets API returned HTTP {status_code}")
        self.status_code = status_code


def parse_google_sheets_location(location: str) -> GoogleSheetsLocation:
    """Parse an AnalystWatch Google Sheets range location.

    Format:
      gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]

    header_row is one-based and relative to the returned range, not the worksheet.
    """
    parsed = urlparse(location)
    if parsed.scheme != "gsheets":
        raise ValueError("Google Sheets location must start with gsheets://")
    spreadsheet_id = parsed.netloc.strip()
    query = parse_qs(parsed.query)
    range_name = (query.get("range") or [""])[0].strip()
    raw_header_row = (query.get("header_row") or ["1"])[0]
    try:
        header_row = int(raw_header_row)
    except ValueError as exc:
        raise ValueError("Google Sheets header_row must be an integer") from exc
    if not spreadsheet_id or not range_name:
        raise ValueError("Google Sheets location requires spreadsheet ID and A1 range")
    if header_row < 1 or header_row > 1000:
        raise ValueError("Google Sheets header_row must be between 1 and 1000")
    return GoogleSheetsLocation(
        spreadsheet_id=spreadsheet_id,
        range_name=range_name,
        header_row=header_row,
    )


def public_google_sheets_location(location: str) -> str:
    try:
        parsed = parse_google_sheets_location(location)
    except ValueError:
        return "Google Sheets"
    return f"Google Sheets · {parsed.range_name}"


def _authorization_present(headers: dict[str, str]) -> bool:
    return any(key.lower() == "authorization" for key in headers)


def _values_url(location: GoogleSheetsLocation) -> str:
    spreadsheet_id = quote(location.spreadsheet_id, safe="")
    range_name = quote(location.range_name, safe="")
    return f"{SHEETS_ROOT}/spreadsheets/{spreadsheet_id}/values/{range_name}"


def _normalize_values(values: object, header_row: int) -> pd.DataFrame:
    if not isinstance(values, list):
        raise ValueError("Google Sheets response did not contain a values array")
    if len(values) < header_row:
        raise ValueError("Google Sheets range did not contain the configured header row")

    header_values = values[header_row - 1]
    if not isinstance(header_values, list) or not header_values:
        raise ValueError("Google Sheets header row was empty")
    columns = [str(value) if value is not None else "" for value in header_values]
    if any(not column.strip() for column in columns):
        raise ValueError("Google Sheets header row contains an empty column name")
    if len(set(columns)) != len(columns):
        raise ValueError("Google Sheets header row contains duplicate column names")

    width = len(columns)
    rows: list[list[object]] = []
    for raw_row in values[header_row:]:
        if not isinstance(raw_row, list):
            raise ValueError("Google Sheets values array contained a non-row item")
        if len(raw_row) > width:
            raise ValueError(
                "Google Sheets data row contains more values than the configured header row"
            )
        normalized = list(raw_row) + [None] * (width - len(raw_row))
        if all(value is None or value == "" for value in normalized):
            continue
        rows.append(normalized)
    return pd.DataFrame(rows, columns=columns)


def read_google_sheets_range(
    location_text: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    client: httpx.Client | None = None,
) -> GoogleSheetsResult:
    if not _authorization_present(headers):
        return GoogleSheetsResult(
            available=False,
            error=(
                "Google Sheets sources require an Authorization request-header environment "
                "reference containing a Google OAuth bearer token."
            ),
        )

    try:
        location = parse_google_sheets_location(location_text)
    except ValueError as exc:
        return GoogleSheetsResult(available=False, error=str(exc))

    owns_client = client is None
    active_client = client or httpx.Client(timeout=timeout_seconds)
    started = time.perf_counter()
    try:
        response = active_client.get(
            _values_url(location),
            headers=headers,
            params={
                "majorDimension": "ROWS",
                "valueRenderOption": "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "FORMATTED_STRING",
            },
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code < 200 or response.status_code >= 300:
            raise GoogleSheetsResponseError(response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            return GoogleSheetsResult(
                available=False,
                http_status=response.status_code,
                response_ms=elapsed_ms,
                error=f"Google Sheets response was not usable JSON: {exc}",
            )
        frame = _normalize_values(payload.get("values"), location.header_row)
        return GoogleSheetsResult(
            available=True,
            dataframe=frame,
            http_status=response.status_code,
            response_ms=elapsed_ms,
            response_etag=response.headers.get("ETag"),
        )
    except GoogleSheetsResponseError as exc:
        return GoogleSheetsResult(
            available=False,
            http_status=exc.status_code,
            response_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    except (httpx.HTTPError, ValueError) as exc:
        return GoogleSheetsResult(
            available=False,
            response_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if owns_client:
            active_client.close()
