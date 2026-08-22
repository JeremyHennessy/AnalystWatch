from __future__ import annotations

import json
from pathlib import Path

from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.pages import build_pages_site
from analystwatch.storage import Storage


def test_google_sheets_pages_redact_spreadsheet_id_and_token_reference(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "state.db")
    storage.initialize()
    source = SourceDefinition(
        id="google-finance",
        name="Google Finance Sheet",
        source_type=SourceType.GOOGLE_SHEETS,
        location=(
            "gsheets://private-spreadsheet-id?"
            "range=Finance%20Data%21A1%3AF500&header_row=1"
        ),
        config=MonitoringConfig(
            request_header_env={"Authorization": "PRIVATE_GOOGLE_TOKEN_ENV"}
        ),
    )
    storage.upsert_source(source)

    output = build_pages_site(storage, tmp_path / "site")
    index = (output / "index.html").read_text(encoding="utf-8")
    detail = (output / "sources" / source.id / "index.html").read_text(encoding="utf-8")
    raw_state = (output / "state.json").read_text(encoding="utf-8")
    state = json.loads(raw_state)["sources"][0]

    for rendered in (index, detail, raw_state):
        assert "private-spreadsheet-id" not in rendered
        assert "PRIVATE_GOOGLE_TOKEN_ENV" not in rendered
        assert "gsheets://" not in rendered

    assert "Google Sheets · Finance Data!A1:F500" in index
    assert "Google Sheets · Finance Data!A1:F500" in detail
    assert state["location"] == "Google Sheets · Finance Data!A1:F500"
