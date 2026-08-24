from __future__ import annotations

import os
from enum import Enum
from typing import Mapping

from pydantic import BaseModel, Field

from .connection_discovery import ConnectionProvider
from .google_sheets import parse_google_sheets_location
from .microsoft_excel import parse_microsoft_excel_location
from .models import SourceDefinition, SourceType


class ConnectionReadinessStatus(str, Enum):
    INVALID_LOCATION = "invalid_location"
    NEEDS_CREDENTIAL_REFERENCE = "needs_credential_reference"
    NEEDS_CREDENTIAL_VALUE = "needs_credential_value"
    READY_TO_TEST = "ready_to_test"


class ConnectionReadiness(BaseModel):
    source_id: str
    provider: ConnectionProvider
    status: ConnectionReadinessStatus
    location_valid: bool
    credential_reference_configured: bool
    credential_available: bool
    can_test: bool
    issues: list[str] = Field(default_factory=list)


def _provider(source: SourceDefinition) -> ConnectionProvider:
    if source.source_type == SourceType.MICROSOFT_EXCEL:
        return ConnectionProvider.MICROSOFT
    if source.source_type == SourceType.GOOGLE_SHEETS:
        return ConnectionProvider.GOOGLE
    raise ValueError("Connection readiness is only available for Microsoft 365 and Google sources")


def _location_valid(source: SourceDefinition) -> bool:
    try:
        if source.source_type == SourceType.MICROSOFT_EXCEL:
            parse_microsoft_excel_location(source.location)
        elif source.source_type == SourceType.GOOGLE_SHEETS:
            parse_google_sheets_location(source.location)
        else:
            return False
    except ValueError:
        return False
    return True


def _authorization_env_reference(source: SourceDefinition) -> str | None:
    for header, env_name in source.config.request_header_env.items():
        if header.lower() == "authorization":
            return env_name
    return None


def connection_readiness(
    source: SourceDefinition,
    *,
    environ: Mapping[str, str] | None = None,
) -> ConnectionReadiness:
    """Return local credential/location readiness without returning secret metadata.

    READY_TO_TEST means AnalystWatch has enough local configuration to attempt a provider
    request. It does not claim that the credential is valid or that tenant/resource access works.
    """
    provider = _provider(source)
    environment = os.environ if environ is None else environ
    location_valid = _location_valid(source)
    credential_reference = _authorization_env_reference(source)
    credential_reference_configured = credential_reference is not None
    credential_available = bool(
        credential_reference
        and credential_reference in environment
        and environment[credential_reference].strip()
    )

    issues: list[str] = []
    if not location_valid:
        issues.append("The provider source location is not valid for this connector.")
    if not credential_reference_configured:
        issues.append("No environment-backed Authorization credential reference is configured.")
    elif not credential_available:
        issues.append("The configured Authorization credential is not available in this runtime.")

    if not location_valid:
        status = ConnectionReadinessStatus.INVALID_LOCATION
    elif not credential_reference_configured:
        status = ConnectionReadinessStatus.NEEDS_CREDENTIAL_REFERENCE
    elif not credential_available:
        status = ConnectionReadinessStatus.NEEDS_CREDENTIAL_VALUE
    else:
        status = ConnectionReadinessStatus.READY_TO_TEST

    return ConnectionReadiness(
        source_id=source.id,
        provider=provider,
        status=status,
        location_valid=location_valid,
        credential_reference_configured=credential_reference_configured,
        credential_available=credential_available,
        can_test=status == ConnectionReadinessStatus.READY_TO_TEST,
        issues=issues,
    )
