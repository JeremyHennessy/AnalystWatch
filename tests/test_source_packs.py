from __future__ import annotations

import pytest

from analystwatch.models import DataRuleKind, HealthStatus, MonitoringConfig
from analystwatch.source_packs import (
    SourcePackId,
    SourcePackOverrides,
    get_source_pack,
    list_source_packs,
    materialize_source_pack,
)


def _required_mapping(pack_id: SourcePackId) -> dict[str, str]:
    pack = get_source_pack(pack_id)
    return {role.id: f"field_{role.id}" for role in pack.roles if role.required}


def test_catalog_contains_initial_analyst_workflow_packs_in_stable_order() -> None:
    packs = list_source_packs()

    assert [pack.id for pack in packs] == [
        SourcePackId.FP_AND_A_FORECAST,
        SourcePackId.SALES_PIPELINE,
        SourcePackId.CLAIMS_REGISTER,
        SourcePackId.OPERATIONS_ORDERS,
        SourcePackId.FINANCE_CLOSE,
        SourcePackId.CUSTOMER_EXPORT,
    ]
    assert [pack.name for pack in packs] == [
        "FP&A Forecast",
        "Sales Pipeline",
        "Claims Register",
        "Operations Orders",
        "Finance Close",
        "Customer Export",
    ]


def test_sales_pipeline_pack_materializes_existing_monitoring_config_primitives() -> None:
    mapping = {
        "opportunity_id": "OpportunityKey",
        "updated_at": "LastModifiedUtc",
        "stage": "PipelineStage",
        "amount": "ExpectedRevenue",
    }

    result = materialize_source_pack(SourcePackId.SALES_PIPELINE, mapping)
    config = result.config

    assert result.pack_name == "Sales Pipeline"
    assert result.role_mapping == mapping
    assert config.monitor_interval_minutes == 60
    assert config.expected_refresh_minutes == 1440
    assert config.latest_date_field == "LastModifiedUtc"
    assert config.unique_keys == ["OpportunityKey"]
    assert config.numeric_fields == ["ExpectedRevenue"]
    assert config.row_diff_fields == ["PipelineStage", "ExpectedRevenue"]
    assert [rule.id for rule in config.data_rules] == [
        "pack.sales_pipeline.non_empty",
        "pack.sales_pipeline.opportunity_id_required",
        "pack.sales_pipeline.updated_at_required",
        "pack.sales_pipeline.stage_required",
    ]
    assert config.data_rules[0].kind == DataRuleKind.ROW_COUNT_RANGE
    assert config.data_rules[0].minimum == 1
    assert config.data_rules[1].field == "OpportunityKey"
    assert config.data_rules[2].field == "LastModifiedUtc"
    assert config.data_rules[2].severity == HealthStatus.WARNING
    assert config.data_rules[3].field == "PipelineStage"


def test_optional_roles_do_not_fall_back_to_all_column_row_diff() -> None:
    result = materialize_source_pack(
        SourcePackId.CUSTOMER_EXPORT,
        {
            "customer_id": "AccountNumber",
            "updated_at": "ExtractedAt",
        },
    )

    assert result.config.unique_keys == ["AccountNumber"]
    assert result.config.latest_date_field == "ExtractedAt"
    assert result.config.numeric_fields == []
    assert result.config.row_diff_fields == ["AccountNumber"]
    assert all(rule.field not in {"status", "customer_value"} for rule in result.config.data_rules)


def test_pack_overrides_change_only_declared_schedule_values() -> None:
    mapping = _required_mapping(SourcePackId.FP_AND_A_FORECAST)
    defaults = MonitoringConfig()

    result = materialize_source_pack(
        SourcePackId.FP_AND_A_FORECAST,
        mapping,
        overrides=SourcePackOverrides(
            monitor_interval_minutes=30,
            expected_refresh_minutes=720,
        ),
    )
    config = result.config

    assert config.monitor_interval_minutes == 30
    assert config.expected_refresh_minutes == 720
    assert config.warning_row_change_pct == defaults.warning_row_change_pct
    assert config.critical_row_change_pct == defaults.critical_row_change_pct
    assert config.warning_null_increase_pct == defaults.warning_null_increase_pct
    assert config.critical_null_increase_pct == defaults.critical_null_increase_pct
    assert config.warning_numeric_factor == defaults.warning_numeric_factor
    assert config.critical_numeric_factor == defaults.critical_numeric_factor
    assert config.warning_category_tvd == defaults.warning_category_tvd
    assert config.critical_category_tvd == defaults.critical_category_tvd
    assert config.notification_transitions == defaults.notification_transitions
    assert config.request_header_env == defaults.request_header_env


@pytest.mark.parametrize("pack_id", list(SourcePackId))
def test_every_pack_materializes_to_a_valid_monitoring_config(pack_id: SourcePackId) -> None:
    mapping = _required_mapping(pack_id)

    result = materialize_source_pack(pack_id, mapping)

    assert result.pack_id == pack_id
    assert result.config.unique_keys
    assert result.config.latest_date_field is not None
    assert result.config.row_diff_fields
    assert any(rule.kind == DataRuleKind.ROW_COUNT_RANGE for rule in result.config.data_rules)
    assert result.config == MonitoringConfig.model_validate(result.config.model_dump())


def test_materialization_is_transparent_and_does_not_mutate_input_mapping() -> None:
    mapping = {
        "claim_id": "ClaimNumber",
        "updated_at": "UpdatedAt",
        "status": "ClaimStatus",
        "incurred_amount": "Incurred",
    }
    original = dict(mapping)

    result = materialize_source_pack(SourcePackId.CLAIMS_REGISTER, mapping)

    assert mapping == original
    assert result.role_mapping == original
    result.role_mapping["status"] = "ChangedAfterReturn"
    assert mapping == original


def test_materialization_rejects_missing_required_roles() -> None:
    with pytest.raises(ValueError, match="Missing required role mappings"):
        materialize_source_pack(
            SourcePackId.OPERATIONS_ORDERS,
            {"order_id": "OrderId"},
        )


def test_materialization_rejects_unknown_roles() -> None:
    mapping = _required_mapping(SourcePackId.SALES_PIPELINE)
    mapping["made_up_role"] = "MysteryField"

    with pytest.raises(ValueError, match="Unknown role mappings"):
        materialize_source_pack(SourcePackId.SALES_PIPELINE, mapping)


@pytest.mark.parametrize("field_name", ["", " Amount", "Amount "])
def test_materialization_rejects_blank_or_untrimmed_field_names(field_name: str) -> None:
    mapping = _required_mapping(SourcePackId.FP_AND_A_FORECAST)
    mapping["amount"] = field_name

    with pytest.raises(ValueError, match="non-empty trimmed field name"):
        materialize_source_pack(SourcePackId.FP_AND_A_FORECAST, mapping)


def test_materialization_rejects_one_source_field_mapped_to_multiple_roles() -> None:
    mapping = _required_mapping(SourcePackId.FINANCE_CLOSE)
    mapping["updated_at"] = mapping["entry_id"]

    with pytest.raises(ValueError, match="distinct source fields"):
        materialize_source_pack(SourcePackId.FINANCE_CLOSE, mapping)


def test_unknown_pack_id_fails_closed() -> None:
    with pytest.raises(KeyError, match="Unknown source pack"):
        get_source_pack("not-a-pack")
    with pytest.raises(KeyError, match="Unknown source pack"):
        materialize_source_pack("not-a-pack", {})


def test_catalog_returns_defensive_copies() -> None:
    first = get_source_pack(SourcePackId.SALES_PIPELINE)
    first.roles[0].label = "Mutated label"

    second = get_source_pack(SourcePackId.SALES_PIPELINE)

    assert second.roles[0].label == "Opportunity ID"
