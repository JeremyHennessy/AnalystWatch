from __future__ import annotations

from fastapi.testclient import TestClient

from analystwatch.web import create_app


def test_connection_browser_exposes_separate_account_identity_actions(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "identity-ui.db"))
    script = client.get("/static/connection_onboard.js").text

    for fragment in [
        "microsoft-identity-test",
        "google-identity-test",
        "Verify connected account",
        "${MICROSOFT_PREFIX}/identity",
        "${GOOGLE_PREFIX}/identity",
        "Connected Microsoft account:",
        "Connected Google account:",
    ]:
        assert fragment in script


def test_identity_ui_uses_text_status_and_never_embeds_credentials(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "identity-private-ui.db"))
    script = client.get("/static/connection_onboard.js").text

    assert "element.textContent = message" in script
    assert "ANALYSTWATCH_MICROSOFT_AUTHORIZATION" not in script
    assert "ANALYSTWATCH_GOOGLE_AUTHORIZATION" not in script
    assert "Bearer " not in script
