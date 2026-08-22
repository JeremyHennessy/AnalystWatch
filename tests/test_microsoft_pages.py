from __future__ import annotations

import json
from pathlib import Path

from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.pages import build_pages_site
from analystwatch.storage import Storage


def test_microsoft_excel_pages_redact_internal_drive_and_item_identifiers(tmp_path: Path):
    storage = Storage(tmp_path / "state.db")
    storage.initialize()
    source = SourceDefinition(
        id="finance-workbook",
        name="Finance Workbook",
        source_type=SourceType.MICROSOFT_EXCEL,
        location="m365://private-drive/private-item?table=FinanceTable&worksheet=Data",
        config=MonitoringConfig(
            request_header_env={"Authorization": "PRIVATE_MICROSOFT_TOKEN_ENV"}
        ),
    )
    storage.upsert_source(source)

    output = build_pages_site(storage, tmp_path / "site")
    index = (output / "index.html").read_text(encoding="utf-8")
    detail = (output / "sources" / source.id / "index.html").read_text(encoding="utf-8")
    raw_state = (output / "state.json").read_text(encoding="utf-8")
    state = json.loads(raw_state)["sources"][0]

    for rendered in (index, detail, raw_state):
        assert "private-drive" not in rendered
        assert "private-item" not in rendered
        assert "PRIVATE_MICROSOFT_TOKEN_ENV" not in rendered

    assert "Microsoft 365 Excel · FinanceTable" in index
    assert "Microsoft 365 Excel · FinanceTable" in detail
    assert state["location"] == "Microsoft 365 Excel · FinanceTable"
