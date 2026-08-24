from __future__ import annotations

import pytest

from analystwatch.connection_discovery import ConnectionProvider
from analystwatch.connections import ConnectionReadinessStatus, connection_readiness
from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType


def _microsoft_source(*, location: str | None = None, headers: dict[str, str] | None = None):
    return SourceDefinition(
        id="microsoft-workbook",
        name="Microsoft workbook",
        source_type=SourceType.MICROSOFT_EXCEL,
        location=location or "m365://drive-1/item-1?table=SalesTable",
        config=MonitoringConfig(request_header_env=headers or {}),
    )


def _google_source(*, location: str | None = None, headers: dict[str, str] | None = None):
    return SourceDefinition(
        id="google-sheet",
        name="Google sheet",
        source_type=SourceType.GOOGLE_SHEETS,
        location=location or "gsheets://sheet-1?range=Data%21A1%3AZ100",
        config=MonitoringConfig(request_header_env=headers or {}),
    )


def test_microsoft_connection_readiness_requires_credential_reference() -> None:
    readiness = connection_readiness(_microsoft_source(), environ={})

    assert readiness.provider == ConnectionProvider.MICROSOFT
    assert readiness.status == ConnectionReadinessStatus.NEEDS_CREDENTIAL_REFERENCE
    assert readiness.location_valid is True
    assert readiness.credential_reference_configured is False
    assert readiness.credential_available is False
    assert readiness.can_test is False


def test_google_connection_readiness_reports_missing_runtime_credential() -> None:
    readiness = connection_readiness(
        _google_source(headers={"Authorization": "ANALYSTWATCH_GOOGLE_AUTHORIZATION"}),
        environ={},
    )

    assert readiness.provider == ConnectionProvider.GOOGLE
    assert readiness.status == ConnectionReadinessStatus.NEEDS_CREDENTIAL_VALUE
    assert readiness.credential_reference_configured is True
    assert readiness.credential_available is False
    assert readiness.can_test is False


def test_ready_to_test_never_serializes_secret_or_environment_reference() -> None:
    token = "Bearer private-provider-token"
    source = _microsoft_source(
        headers={"authorization": "ANALYSTWATCH_MICROSOFT_AUTHORIZATION"}
    )

    readiness = connection_readiness(
        source,
        environ={"ANALYSTWATCH_MICROSOFT_AUTHORIZATION": token},
    )

    assert readiness.status == ConnectionReadinessStatus.READY_TO_TEST
    assert readiness.location_valid is True
    assert readiness.credential_reference_configured is True
    assert readiness.credential_available is True
    assert readiness.can_test is True
    assert readiness.issues == []
    rendered = readiness.model_dump_json()
    assert token not in rendered
    assert "ANALYSTWATCH_MICROSOFT_AUTHORIZATION" not in rendered


def test_blank_runtime_credential_is_not_ready() -> None:
    readiness = connection_readiness(
        _google_source(headers={"Authorization": "GOOGLE_TOKEN"}),
        environ={"GOOGLE_TOKEN": "   "},
    )

    assert readiness.status == ConnectionReadinessStatus.NEEDS_CREDENTIAL_VALUE
    assert readiness.can_test is False


@pytest.mark.parametrize(
    ("source", "expected_provider"),
    [
        (
            _microsoft_source(
                location="m365://drive-only",
                headers={"Authorization": "MS_TOKEN"},
            ),
            ConnectionProvider.MICROSOFT,
        ),
        (
            _google_source(
                location="gsheets://sheet-1",
                headers={"Authorization": "GOOGLE_TOKEN"},
            ),
            ConnectionProvider.GOOGLE,
        ),
    ],
)
def test_invalid_provider_location_blocks_connection_test(source, expected_provider) -> None:
    readiness = connection_readiness(
        source,
        environ={"MS_TOKEN": "Bearer x", "GOOGLE_TOKEN": "Bearer y"},
    )

    assert readiness.provider == expected_provider
    assert readiness.status == ConnectionReadinessStatus.INVALID_LOCATION
    assert readiness.location_valid is False
    assert readiness.can_test is False


def test_non_cloud_source_fails_closed() -> None:
    source = SourceDefinition(
        id="local-csv",
        name="Local CSV",
        source_type=SourceType.CSV,
        location="data.csv",
    )

    with pytest.raises(ValueError, match="only available for Microsoft 365 and Google"):
        connection_readiness(source, environ={})
