from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
from conftest import write_csv_source

from analystwatch.models import HealthStatus, MonitoringConfig, SourceDefinition, SourceType
from analystwatch.service import MonitorService


def _baseline(service: MonitorService, path: Path, frame: pd.DataFrame, now, config=None):
    write_csv_source(service, path, frame, config=config)
    observation = service.check_source("market", now=now)
    assert observation.health == HealthStatus.HEALTHY
    assert observation.is_baseline is True
    return observation


def test_healthy_normal_variation_does_not_trigger(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    baseline = _baseline(service, path, base_frame, now)
    current = base_frame.copy()
    current["amount"] = current["amount"] * 1.03
    current.to_csv(path, index=False)
    observation = service.check_source("market", now=now + timedelta(minutes=5))
    assert observation.health == HealthStatus.HEALTHY
    assert observation.findings == []
    assert service.storage.get_baseline("market").id == baseline.id
    assert len(service.storage.list_observations("market")) == 2


def test_removed_column_generates_schema_critical(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    _baseline(service, path, base_frame, now)
    base_frame.drop(columns=["jurisdiction"]).to_csv(path, index=False)
    observation = service.check_source("market", now=now + timedelta(minutes=5))
    assert observation.health == HealthStatus.CRITICAL
    assert any(
        f.detector == "schema" and f.severity == HealthStatus.CRITICAL
        for f in observation.findings
    )


def test_row_truncation_generates_volume_critical(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    _baseline(service, path, base_frame, now)
    base_frame.iloc[:100].to_csv(path, index=False)
    observation = service.check_source("market", now=now + timedelta(minutes=5))
    row_finding = next(f for f in observation.findings if f.detector == "row_count")
    assert row_finding.severity == HealthStatus.CRITICAL
    assert row_finding.baseline_value == 1000
    assert row_finding.current_value == 100


def test_null_explosion_generates_completeness_critical(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    _baseline(service, path, base_frame, now)
    current = base_frame.copy()
    current.loc[:399, "jurisdiction"] = None
    current.to_csv(path, index=False)
    observation = service.check_source("market", now=now + timedelta(minutes=5))
    finding = next(f for f in observation.findings if f.detector == "null_rate")
    assert finding.severity == HealthStatus.CRITICAL
    assert finding.current_value >= 0.40
    assert finding.baseline_value == 0.02


def test_numeric_scaling_detects_possible_unit_change(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    _baseline(service, path, base_frame, now)
    current = base_frame.copy()
    current["amount"] = current["amount"] / 100
    current.to_csv(path, index=False)
    observation = service.check_source("market", now=now + timedelta(minutes=5))
    finding = next(
        f
        for f in observation.findings
        if f.detector == "numeric_drift" and "amount" in f.description
    )
    assert finding.severity == HealthStatus.CRITICAL
    assert "Possible scaling/unit change" in (finding.likely_impact or "")
    assert 80 < finding.current_value < 82
    assert finding.baseline_value > 8000


def test_category_disappearance_generates_warning(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    _baseline(service, path, base_frame, now)
    current = base_frame.copy()
    current.loc[current["segment"] == "C", "segment"] = "B"
    current.to_csv(path, index=False)
    observation = service.check_source("market", now=now + timedelta(minutes=5))
    finding = next(
        f
        for f in observation.findings
        if f.detector == "categorical_drift" and "segment" in f.description
    )
    assert finding.severity == HealthStatus.WARNING
    assert "disappeared: C" in finding.description


def test_duplicate_key_deterioration_generates_critical(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    _baseline(service, path, base_frame, now)
    current = base_frame.copy()
    current.loc[:149, "id"] = 1
    current.to_csv(path, index=False)
    observation = service.check_source("market", now=now + timedelta(minutes=5))
    finding = next(f for f in observation.findings if f.detector == "uniqueness")
    assert finding.severity == HealthStatus.CRITICAL
    assert finding.current_value >= 0.10


def test_stale_file_generates_freshness_alert(base_frame, service, tmp_path, now):
    path = tmp_path / "market.csv"
    config = MonitoringConfig(expected_refresh_minutes=60, unique_keys=["id"])
    write_csv_source(service, path, base_frame, config=config)
    fresh_timestamp = (now - timedelta(minutes=5)).timestamp()
    os.utime(path, (fresh_timestamp, fresh_timestamp))
    baseline = service.check_source("market", now=now)
    assert baseline.health == HealthStatus.HEALTHY

    stale_timestamp = (now - timedelta(hours=3)).timestamp()
    os.utime(path, (stale_timestamp, stale_timestamp))
    observation = service.check_source("market", now=now + timedelta(minutes=1))
    finding = next(f for f in observation.findings if f.detector == "freshness")
    assert finding.severity == HealthStatus.CRITICAL


def test_api_unavailable_after_baseline_is_critical(service, now):
    source = SourceDefinition(
        id="api",
        name="Government API",
        source_type=SourceType.API,
        location="https://example.test/data",
    )
    service.add_source(source)
    healthy_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{"id": 1, "value": 10}])
        )
    )
    failed_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="unavailable"))
    )
    first = service.check_source("api", client=healthy_client, now=now)
    second = service.check_source("api", client=failed_client, now=now + timedelta(minutes=5))
    healthy_client.close()
    failed_client.close()
    assert first.health == HealthStatus.HEALTHY
    assert second.health == HealthStatus.CRITICAL
    finding = next(f for f in second.findings if f.detector == "availability")
    assert "HTTP 503" in finding.why_flagged
