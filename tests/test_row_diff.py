from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from analystwatch.models import MonitoringConfig, SourceDefinition, SourceType
from analystwatch.pages import build_pages_site
from analystwatch.row_diff import build_row_snapshot, compare_row_snapshots
from analystwatch.service import MonitorService
from analystwatch.storage import Storage


def _frame_one() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3],
            "status": ["Active", "Active", "Closed"],
            "amount": [100, 200, 300],
            "region": ["East", "West", "West"],
        }
    )


def _frame_two() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 3, 4],
            "status": ["Cancelled", "Closed", "Active"],
            "amount": [110, 300, 400],
            "region": ["East", "West", "North"],
        }
    )


def _source(path: Path, *, retention: int = 2) -> SourceDefinition:
    return SourceDefinition(
        id="customers",
        name="Customers",
        source_type=SourceType.CSV,
        location=str(path),
        config=MonitoringConfig(
            unique_keys=["id"],
            row_diff_snapshot_retention=retention,
            row_diff_sample_limit=10,
        ),
    )


def test_row_snapshot_comparison_reports_exact_key_and_column_changes() -> None:
    config = MonitoringConfig(unique_keys=["id"], row_diff_sample_limit=10)
    baseline, baseline_reason = build_row_snapshot(_frame_one(), config)
    current, current_reason = build_row_snapshot(_frame_two(), config)

    assert baseline_reason is None
    assert current_reason is None
    assert baseline is not None
    assert current is not None

    diff = compare_row_snapshots(
        current,
        baseline,
        reference_observation_id="baseline-1",
        reference_label="active baseline",
        sample_limit=10,
    )

    assert diff.added_count == 1
    assert diff.removed_count == 1
    assert diff.changed_count == 1
    assert diff.unchanged_count == 1
    assert diff.changed_columns == {"amount": 1, "status": 1}
    assert diff.added_samples[0].key == {"id": 4}
    assert diff.removed_samples[0].key == {"id": 2}
    assert diff.changed_samples[0].key == {"id": 1}
    assert diff.changed_samples[0].changes["status"].previous == "Active"
    assert diff.changed_samples[0].changes["status"].current == "Cancelled"
    assert diff.changed_samples[0].changes["amount"].previous == 100
    assert diff.changed_samples[0].changes["amount"].current == 110


def test_row_snapshot_supports_composite_keys_and_field_allowlist() -> None:
    frame = pd.DataFrame(
        {
            "account": ["A", "A", "B"],
            "month": [1, 2, 1],
            "amount": [10, 20, 30],
            "private_note": ["one", "two", "three"],
        }
    )
    config = MonitoringConfig(
        unique_keys=["account", "month"],
        row_diff_fields=["amount"],
    )

    snapshot, reason = build_row_snapshot(frame, config)

    assert reason is None
    assert snapshot is not None
    assert snapshot.key_fields == ["account", "month"]
    assert snapshot.value_fields == ["account", "month", "amount"]
    assert snapshot.rows[0].key == {"account": "A", "month": 1}
    assert snapshot.rows[0].values == {"amount": 10}
    assert "private_note" not in snapshot.model_dump_json()


def test_row_snapshot_refuses_duplicate_null_and_oversized_keys() -> None:
    duplicate = pd.DataFrame({"id": [1, 1], "value": [10, 20]})
    snapshot, reason = build_row_snapshot(duplicate, MonitoringConfig(unique_keys=["id"]))
    assert snapshot is None
    assert "unique" in reason.lower()

    null_key = pd.DataFrame({"id": [1, None], "value": [10, 20]})
    snapshot, reason = build_row_snapshot(null_key, MonitoringConfig(unique_keys=["id"]))
    assert snapshot is None
    assert "non-null" in reason.lower()

    oversized = pd.DataFrame({"id": [1, 2, 3], "value": [10, 20, 30]})
    snapshot, reason = build_row_snapshot(
        oversized,
        MonitoringConfig(unique_keys=["id"], row_diff_max_rows=2),
    )
    assert snapshot is None
    assert "3 rows" in reason
    assert "limit is 2" in reason


def test_monitor_service_compares_previous_and_baseline_then_prunes_raw_payloads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "customers.csv"
    _frame_one().to_csv(path, index=False)
    service = MonitorService(Storage(tmp_path / "state.db"))
    service.add_source(_source(path, retention=1))
    started = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)

    baseline = service.check_source("customers", now=started)
    assert baseline.row_snapshot is not None
    assert baseline.row_diff is not None
    assert baseline.row_diff.previous is None
    assert baseline.row_diff.baseline is None

    _frame_two().to_csv(path, index=False)
    second = service.check_source("customers", now=started + timedelta(minutes=1))
    assert second.row_snapshot is not None
    assert second.row_diff is not None
    assert second.row_diff.previous is not None
    assert second.row_diff.baseline is not None
    assert second.row_diff.previous.added_count == 1
    assert second.row_diff.previous.removed_count == 1
    assert second.row_diff.previous.changed_count == 1
    assert second.row_diff.baseline.changed_columns == {"amount": 1, "status": 1}

    third_frame = _frame_two().copy()
    third_frame.loc[third_frame["id"] == 1, "amount"] = 111
    third_frame.to_csv(path, index=False)
    third = service.check_source("customers", now=started + timedelta(minutes=2))
    assert third.row_diff is not None
    assert third.row_diff.previous is not None
    assert third.row_diff.previous.added_count == 0
    assert third.row_diff.previous.removed_count == 0
    assert third.row_diff.previous.changed_count == 1
    assert third.row_diff.previous.changed_columns == {"amount": 1}

    persisted_baseline = service.storage.get_observation(baseline.id)
    persisted_second = service.storage.get_observation(second.id)
    persisted_third = service.storage.get_observation(third.id)
    assert persisted_baseline is not None and persisted_baseline.row_snapshot is not None
    assert persisted_third is not None and persisted_third.row_snapshot is not None
    assert persisted_second is not None and persisted_second.row_snapshot is None
    assert persisted_second.row_diff is not None
    assert persisted_second.row_diff.previous is not None
    assert persisted_second.row_diff.previous.changed_count == 1
    assert persisted_second.row_diff.previous.changed_samples == []


def test_row_diff_is_not_enabled_without_configured_keys(tmp_path: Path) -> None:
    path = tmp_path / "plain.csv"
    _frame_one().to_csv(path, index=False)
    service = MonitorService(Storage(tmp_path / "plain.db"))
    service.add_source(
        SourceDefinition(
            id="plain",
            name="Plain",
            source_type=SourceType.CSV,
            location=str(path),
        )
    )

    observation = service.check_source("plain")

    assert observation.row_snapshot is None
    assert observation.row_diff is None


def test_oversized_row_diff_is_explicit_and_does_not_change_health(tmp_path: Path) -> None:
    path = tmp_path / "limited.csv"
    _frame_one().to_csv(path, index=False)
    service = MonitorService(Storage(tmp_path / "limited.db"))
    source = _source(path)
    source.config.row_diff_max_rows = 2
    service.add_source(source)

    observation = service.check_source("customers")

    assert observation.health.value == "Healthy"
    assert observation.row_snapshot is None
    assert observation.row_diff is not None
    assert observation.row_diff.snapshot_available is False
    assert "limit is 2" in observation.row_diff.snapshot_reason


def test_static_pages_strip_row_diff_raw_payloads_but_keep_aggregate_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "customers.csv"
    _frame_one().to_csv(path, index=False)
    service = MonitorService(Storage(tmp_path / "public.db"))
    service.add_source(_source(path))
    service.check_source("customers")

    current = _frame_two().copy()
    current.loc[current["id"] == 1, "status"] = "SECRET-CANCELLED-VALUE"
    current.to_csv(path, index=False)
    latest = service.check_source("customers")
    assert latest.row_diff is not None and latest.row_diff.previous is not None
    assert latest.row_diff.previous.changed_samples

    output = build_pages_site(service.storage, tmp_path / "site")
    raw_state = (output / "state.json").read_text(encoding="utf-8")
    state = json.loads(raw_state)["sources"][0]["latest"]

    assert state["row_snapshot"] is None
    assert state["row_diff"]["previous"]["changed_count"] == 1
    assert state["row_diff"]["previous"]["added_count"] == 1
    assert state["row_diff"]["previous"]["removed_count"] == 1
    assert state["row_diff"]["previous"]["changed_samples"] == []
    assert state["row_diff"]["previous"]["added_samples"] == []
    assert state["row_diff"]["previous"]["removed_samples"] == []
    # Existing deterministic findings retain their established public evidence policy;
    # v0.18 specifically prevents its new raw row snapshots/samples from being published.
