from __future__ import annotations

import pytest

from analystwatch.managed_runtime import ManagedRuntimeConfig


def _env() -> dict[str, str]:
    return {
        "ANALYSTWATCH_POSTGRES_DSN": "postgresql://user:secret@db.example/analystwatch",
        "ANALYSTWATCH_WORKSPACE_ID": "team-a",
        "ANALYSTWATCH_AUTH_SECRET": "signed-session-secret-value",
        "ANALYSTWATCH_BOOTSTRAP_ADMIN_USER_ID": "owner@example.com",
        "ANALYSTWATCH_RESEND_API_KEY": "re_provider_secret",
        "ANALYSTWATCH_EMAIL_FROM": "AnalystWatch <alerts@example.com>",
        "ANALYSTWATCH_EMAIL_TO": "one@example.com,two@example.com",
        "ANALYSTWATCH_PUBLIC_BASE_URL": "https://app.example.com",
    }


def test_managed_runtime_requires_complete_environment() -> None:
    values = _env()
    values.pop("ANALYSTWATCH_AUTH_SECRET")

    with pytest.raises(ValueError, match="ANALYSTWATCH_AUTH_SECRET"):
        ManagedRuntimeConfig.from_env(values)


def test_managed_runtime_parses_email_recipients_and_adapter_without_exposing_secrets() -> None:
    config = ManagedRuntimeConfig.from_env(_env())

    assert config.workspace_id == "team-a"
    assert config.email_to == ("one@example.com", "two@example.com")
    adapter = config.email_adapter()
    assert adapter.destination.to_addresses == config.email_to
    assert adapter.destination.base_url == "https://app.example.com"
    assert "re_provider_secret" not in repr(adapter.destination)


def test_managed_runtime_rejects_invalid_workspace() -> None:
    values = _env()
    values["ANALYSTWATCH_WORKSPACE_ID"] = "team/a"

    with pytest.raises(ValueError):
        ManagedRuntimeConfig.from_env(values)


def test_managed_runtime_rejects_blank_recipient_list() -> None:
    values = _env()
    values["ANALYSTWATCH_EMAIL_TO"] = ", ,"

    with pytest.raises(ValueError, match="at least one recipient"):
        ManagedRuntimeConfig.from_env(values)
