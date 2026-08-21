from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd

from analystwatch.ingest import ingest_source
from analystwatch.models import HealthStatus, MonitoringConfig, SourceDefinition, SourceType
from analystwatch.pages import build_pages_site
from analystwatch.profile import profile_dataframe


def _frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": range(1, rows + 1),
            "amount": [100 + (index % 10) for index in range(rows)],
            "segment": ["A" if index % 2 else "B" for index in range(rows)],
        }
    )


def test_monitor_schedule_distinguishes_check_cadence_from_freshness(service, tmp_path, now):
    path = tmp_path / "scheduled.csv"
    _frame(100).to_csv(path, index=False)
    service.add_source(
        SourceDefinition(
            id="scheduled",
            name="Scheduled",
            source_type=SourceType.CSV,
            location=str(path),
            config=MonitoringConfig(monitor_interval_minutes=60),
        )
    )

    before = service.get_run_decision("scheduled", now=now)
    assert before.due is True
    assert before.reason == "Source has never been checked."

    service.check_source("scheduled", now=now)
    early = service.get_run_decision("scheduled", now=now + timedelta(minutes=59))
    due = service.get_run_decision("scheduled", now=now + timedelta(minutes=60))
    assert early.due is False
    assert due.due is True
    assert due.next_check_at == now + timedelta(minutes=60)


def test_check_due_sources_runs_only_due_sources(service, tmp_path, now):
    path = tmp_path / "market.csv"
    _frame(100).to_csv(path, index=False)
    service.add_source(
        SourceDefinition(
            id="market",
            name="Market",
            source_type=SourceType.CSV,
            location=str(path),
            config=MonitoringConfig(monitor_interval_minutes=30),
        )
    )
    first = service.check_due_sources(now=now)
    assert [item.source_id for item in first] == ["market"]

    assert service.check_due_sources(now=now + timedelta(minutes=29)) == []
    second = service.check_due_sources(now=now + timedelta(minutes=30))
    assert [item.source_id for item in second] == ["market"]
    assert len(service.storage.list_observations("market")) == 2


def test_disabled_source_is_not_due(service, tmp_path, now):
    path = tmp_path / "disabled.csv"
    _frame(10).to_csv(path, index=False)
    service.add_source(
        SourceDefinition(
            id="disabled",
            name="Disabled",
            source_type=SourceType.CSV,
            location=str(path),
            enabled=False,
        )
    )
    decision = service.get_run_decision("disabled", now=now)
    assert decision.due is False
    assert "disabled" in decision.reason.lower()


def test_recent_healthy_history_reduces_stale_baseline_over_escalation(service, tmp_path, now):
    path = tmp_path / "growth.csv"
    config = MonitoringConfig(
        monitor_interval_minutes=1,
        history_window_size=5,
        min_history_observations=3,
    )
    _frame(1000).to_csv(path, index=False)
    service.add_source(
        SourceDefinition(
            id="growth",
            name="Growth",
            source_type=SourceType.CSV,
            location=str(path),
            config=config,
        )
    )
    baseline = service.check_source("growth", now=now)
    assert baseline.health == HealthStatus.HEALTHY

    for offset in (1, 2, 3):
        _frame(1200).to_csv(path, index=False)
        observation = service.check_source("growth", now=now + timedelta(minutes=offset))
        assert observation.health == HealthStatus.HEALTHY

    _frame(1500).to_csv(path, index=False)
    current = service.check_source("growth", now=now + timedelta(minutes=4))
    finding = next(item for item in current.findings if item.detector == "row_count")
    assert finding.severity == HealthStatus.WARNING
    assert finding.baseline_value["baseline"] == 1000
    assert finding.baseline_value["historical_median"] == 1200
    assert finding.baseline_value["observations"] >= 3
    assert "recent healthy-history median" in finding.why_flagged


def test_date_field_inference_is_opt_in():
    frame = pd.DataFrame(
        {"id": [1, 2], "updated_at": ["2026-08-20T10:00:00Z", "2026-08-21T12:00:00Z"]}
    )
    normal = profile_dataframe(frame)
    inferred = profile_dataframe(frame, infer_latest_date_field=True)
    assert normal.latest_date is None
    assert normal.latest_date_field is None
    assert inferred.latest_date_field == "updated_at"
    assert inferred.latest_date.isoformat().startswith("2026-08-21T12:00:00")


def test_api_records_last_modified_and_etag():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[{"id": 1}],
            headers={
                "Last-Modified": "Fri, 21 Aug 2026 12:00:00 GMT",
                "ETag": '"abc123"',
            },
        )
    )
    client = httpx.Client(transport=transport)
    source = SourceDefinition(
        id="api-metadata",
        name="API metadata",
        source_type=SourceType.API,
        location="https://example.test/data?token=secret",
    )
    result = ingest_source(source, client=client)
    client.close()
    assert result.available is True
    assert result.source_modified_at is not None
    assert result.source_modified_at.isoformat().startswith("2026-08-21T12:00:00")
    assert result.response_etag == '"abc123"'


def test_static_pages_export_is_read_only_and_navigable(service, tmp_path: Path, now):
    path = tmp_path / "market.csv"
    _frame(25).to_csv(path, index=False)
    service.add_source(
        SourceDefinition(
            id="market",
            name="Market Data",
            source_type=SourceType.CSV,
            location="samples/demo_market.csv",
            config=MonitoringConfig(monitor_interval_minutes=60),
        )
    )
    # The stored relative path is deliberate for the repository-hosted test source.
    source = service.storage.get_source("market")
    source.location = str(path)
    service.add_source(source)
    service.check_source("market", now=now)
    source.location = "samples/demo_market.csv"
    service.add_source(source)

    output = build_pages_site(service.storage, tmp_path / "site", generated_at=now)
    index = (output / "index.html").read_text(encoding="utf-8")
    detail = (output / "sources" / "market" / "index.html").read_text(encoding="utf-8")
    state = (output / "state.json").read_text(encoding="utf-8")

    assert (output / ".nojekyll").exists()
    assert (output / "static" / "app.css").exists()
    assert 'href="sources/market/"' in index
    assert "Static test deployment" in index
    assert "Read-only Pages view" in detail
    assert "Run check" not in detail
    assert "samples/demo_market.csv" in state
