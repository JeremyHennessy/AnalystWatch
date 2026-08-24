from __future__ import annotations

from fastapi.testclient import TestClient

from analystwatch.web import create_app


def test_connection_browser_exposes_credential_lifecycle_actions(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "lifecycle-ui.db"))
    script = client.get("/static/connection_onboard.js").text

    for fragment in [
        "microsoft-lifecycle-test",
        "google-lifecycle-test",
        "Credential status",
        "${MICROSOFT_PREFIX}/lifecycle",
        "${GOOGLE_PREFIX}/lifecycle",
        "Credential status:",
        "lifecycle.guidance",
    ]:
        assert fragment in script


def test_lifecycle_ui_distinguishes_verified_warning_and_action_states(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "lifecycle-kind-ui.db"))
    script = client.get("/static/connection_onboard.js").text

    assert "lifecycle.state === 'verified'" in script
    assert "lifecycle.state === 'unavailable'" in script
    assert "lifecycle.state === 'identity_unverified'" in script
    assert "element.textContent = message" in script
    assert "ANALYSTWATCH_MICROSOFT_AUTHORIZATION" not in script
    assert "ANALYSTWATCH_GOOGLE_AUTHORIZATION" not in script
