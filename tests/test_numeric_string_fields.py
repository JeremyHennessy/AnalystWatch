from __future__ import annotations

from datetime import timedelta

import httpx
import pandas as pd

from analystwatch.models import HealthStatus, MonitoringConfig, SourceDefinition, SourceType
from analystwatch.profile import profile_dataframe


def test_explicit_numeric_fields_coerce_numeric_strings_for_profiling():
    frame = pd.DataFrame(
        {
            "amount": ["8000.0", "8100.5", "bad", None],
            "id": ["001", "002", "003", "004"],
        }
    )
    profile = profile_dataframe(frame, numeric_fields=["amount"])
    amount = profile.columns["amount"]
    identifier = profile.columns["id"]

    assert amount.dtype == "numeric"
    assert amount.null_count == 2
    assert amount.numeric is not None
    assert amount.numeric.median == 8050.25
    assert identifier.dtype == "text"
    assert identifier.numeric is None


def test_numeric_string_api_can_detect_scaling_change(service, now):
    source = SourceDefinition(
        id="string-numeric-api",
        name="String numeric API",
        source_type=SourceType.API,
        location="https://example.test/data",
        config=MonitoringConfig(
            json_record_path="data",
            latest_date_field="record_date",
            numeric_fields=["amount"],
        ),
    )
    service.add_source(source)

    baseline_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {"record_date": "2026-08-20", "amount": "8000"},
                    {"record_date": "2026-08-21", "amount": "8200"},
                ]
            },
        )
    )
    with httpx.Client(transport=baseline_transport) as client:
        baseline = service.check_source("string-numeric-api", client=client, now=now)
    assert baseline.health == HealthStatus.HEALTHY
    assert baseline.profile.columns["amount"].dtype == "numeric"

    scaled_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {"record_date": "2026-08-20", "amount": "80"},
                    {"record_date": "2026-08-21", "amount": "82"},
                ]
            },
        )
    )
    with httpx.Client(transport=scaled_transport) as client:
        current = service.check_source(
            "string-numeric-api", client=client, now=now + timedelta(minutes=1)
        )

    finding = next(item for item in current.findings if item.detector == "numeric_drift")
    assert current.health == HealthStatus.CRITICAL
    assert finding.current_value == 81.0
    assert finding.baseline_value == 8100.0
    assert "factor of 100.00" in finding.why_flagged
