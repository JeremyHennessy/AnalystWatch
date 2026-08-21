from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from analystwatch.cli import main
from analystwatch.models import SourceDefinition, SourceType
from analystwatch.pages import build_pages_site
from analystwatch.storage import Storage
from analystwatch.web import create_app
from analystwatch.workspace import create_workspace_service


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"id": [1, 2, 3], "amount": [10, 11, 12]})


def _source(path: Path, source_id: str, workspace_id: str) -> SourceDefinition:
    return SourceDefinition(
        id=source_id,
        workspace_id=workspace_id,
        name=f"{workspace_id} source",
        source_type=SourceType.CSV,
        location=str(path),
    )


def test_fastapi_reads_only_bound_workspace(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    alpha_path = tmp_path / "alpha.csv"
    beta_path = tmp_path / "beta.csv"
    _frame().to_csv(alpha_path, index=False)
    _frame().to_csv(beta_path, index=False)

    raw = Storage(db_path)
    raw.initialize()
    raw.upsert_source(_source(alpha_path, "alpha-source", "alpha"))
    raw.upsert_source(_source(beta_path, "beta-source", "beta"))

    client = TestClient(create_app(db_path, workspace_id="alpha"))
    sources = client.get("/api/sources")

    assert sources.status_code == 200
    assert [item["source"]["id"] for item in sources.json()] == ["alpha-source"]
    assert client.get("/api/sources/beta-source").status_code == 404


def test_fastapi_blocks_foreign_workspace_write_before_preflight(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    client = TestClient(create_app(db_path, workspace_id="alpha"))
    payload = {
        "id": "foreign",
        "workspace_id": "beta",
        "name": "Foreign",
        "source_type": "csv",
        "location": str(tmp_path / "does-not-exist.csv"),
    }

    response = client.post("/api/sources", json=payload)

    assert response.status_code == 409
    assert "does not match bound workspace" in response.json()["detail"]
    assert Storage(db_path).get_source("foreign") is None


def test_cli_add_source_persists_selected_workspace(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    csv_path = tmp_path / "alpha.csv"
    _frame().to_csv(csv_path, index=False)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "--workspace-id",
            "alpha",
            "add-source",
            "--id",
            "alpha-source",
            "--name",
            "Alpha source",
            "--type",
            "csv",
            "--location",
            str(csv_path),
        ]
    )

    stored = Storage(db_path).get_source("alpha-source")
    assert exit_code == 0
    assert stored is not None
    assert stored.workspace_id == "alpha"


def test_cli_list_is_workspace_filtered(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "state.db"
    alpha_path = tmp_path / "alpha.csv"
    beta_path = tmp_path / "beta.csv"
    _frame().to_csv(alpha_path, index=False)
    _frame().to_csv(beta_path, index=False)
    raw = Storage(db_path)
    raw.initialize()
    raw.upsert_source(_source(alpha_path, "alpha-source", "alpha"))
    raw.upsert_source(_source(beta_path, "beta-source", "beta"))

    assert main(["--db", str(db_path), "--workspace-id", "alpha", "list"]) == 0
    output = capsys.readouterr().out

    assert "alpha-source" in output
    assert "beta-source" not in output


def test_pages_render_only_bound_workspace(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    alpha_path = tmp_path / "alpha.csv"
    beta_path = tmp_path / "beta.csv"
    _frame().to_csv(alpha_path, index=False)
    _frame().to_csv(beta_path, index=False)
    raw = Storage(db_path)
    raw.initialize()
    raw.upsert_source(_source(alpha_path, "alpha-source", "alpha"))
    raw.upsert_source(_source(beta_path, "beta-source", "beta"))

    service = create_workspace_service(Storage(db_path), "alpha")
    output = build_pages_site(service.storage, tmp_path / "site")
    state = json.loads((output / "state.json").read_text(encoding="utf-8"))

    assert [item["id"] for item in state["sources"]] == ["alpha-source"]
    assert (output / "sources" / "alpha-source" / "index.html").exists()
    assert not (output / "sources" / "beta-source").exists()
