from __future__ import annotations

from fastapi.testclient import TestClient

from analystwatch.web import create_app


def test_onboarding_exposes_role_mapped_source_pack_flow(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "pack-ui.db"))

    response = client.get("/sources/new")

    assert response.status_code == 200
    assert "Start with a source pack" in response.text
    assert "Workflow preset" in response.text
    assert "Preview generated contract" in response.text
    assert "Apply pack contract" in response.text
    assert "Packs never bypass preflight" in response.text
    assert "'/api/source-packs'" in response.text
    assert "'/api/source-packs/materialize'" in response.text


def test_onboarding_requires_explicit_pack_application_before_preflight(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "pack-apply.db"))

    response = client.get("/sources/new")

    assert response.status_code == 200
    assert "pendingPackMaterialization" in response.text
    assert "activePackId" in response.text
    assert "Preview and apply the selected source pack before preflight." in response.text
    assert "Applying does not save or onboard the source." in response.text


def test_applied_pack_reuses_existing_contract_controls(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "pack-contract.db"))

    response = client.get("/sources/new")

    assert response.status_code == 200
    assert "replaceDataRules(config.data_rules || [])" in response.text
    assert "row_diff_fields: packRowDiffFields" in response.text
    assert "document.getElementById('monitor-interval').value" in response.text
    assert "document.getElementById('refresh-interval').value" in response.text
    assert "document.getElementById('latest-date').value" in response.text
    assert "document.getElementById('numeric-fields').value" in response.text
    assert "document.getElementById('unique-keys').value" in response.text
    assert "You can edit the generated cadence, fields and Data Rules below before running preflight." in response.text
