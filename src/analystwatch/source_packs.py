from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from .models import DataRule, DataRuleKind, HealthStatus, MonitoringConfig


class SourcePackId(str, Enum):
    FP_AND_A_FORECAST = "fp_and_a_forecast"
    SALES_PIPELINE = "sales_pipeline"
    CLAIMS_REGISTER = "claims_register"
    OPERATIONS_ORDERS = "operations_orders"
    FINANCE_CLOSE = "finance_close"
    CUSTOMER_EXPORT = "customer_export"


class SourcePackRole(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True


class SourcePackRuleTemplate(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1)
    kind: DataRuleKind
    severity: HealthStatus = HealthStatus.CRITICAL
    field_role: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    likely_impact: str | None = None
    suggested_investigation: str | None = None

    @model_validator(mode="after")
    def validate_template(self) -> "SourcePackRuleTemplate":
        if self.kind == DataRuleKind.NOT_NULL:
            if self.field_role is None:
                raise ValueError("Source-pack not_null rules require field_role")
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("Source-pack not_null rules do not accept bounds")
            return self
        if self.kind == DataRuleKind.ROW_COUNT_RANGE:
            if self.field_role is not None:
                raise ValueError("Source-pack row_count_range rules do not accept field_role")
            if self.minimum is None and self.maximum is None:
                raise ValueError("Source-pack row_count_range rules require a bound")
            return self
        raise ValueError(
            "Source-pack templates currently support only not_null and row_count_range rules"
        )


class SourcePack(BaseModel):
    id: SourcePackId
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    roles: list[SourcePackRole]
    monitor_interval_minutes: int = Field(gt=0)
    expected_refresh_minutes: int | None = Field(default=None, gt=0)
    latest_date_role: str | None = None
    unique_key_roles: list[str] = Field(default_factory=list)
    numeric_roles: list[str] = Field(default_factory=list)
    row_diff_roles: list[str] = Field(default_factory=list)
    rule_templates: list[SourcePackRuleTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_role_references(self) -> "SourcePack":
        role_ids = [role.id for role in self.roles]
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("Source-pack role IDs must be unique")
        known = set(role_ids)
        references = [
            *self.unique_key_roles,
            *self.numeric_roles,
            *self.row_diff_roles,
        ]
        if self.latest_date_role is not None:
            references.append(self.latest_date_role)
        references.extend(
            template.field_role
            for template in self.rule_templates
            if template.field_role is not None
        )
        unknown = sorted(set(references) - known)
        if unknown:
            raise ValueError(f"Source-pack references unknown roles: {', '.join(unknown)}")
        if len(set(self.unique_key_roles)) != len(self.unique_key_roles):
            raise ValueError("Source-pack unique_key_roles must not contain duplicates")
        if len(set(self.numeric_roles)) != len(self.numeric_roles):
            raise ValueError("Source-pack numeric_roles must not contain duplicates")
        if len(set(self.row_diff_roles)) != len(self.row_diff_roles):
            raise ValueError("Source-pack row_diff_roles must not contain duplicates")
        template_ids = [template.id for template in self.rule_templates]
        if len(set(template_ids)) != len(template_ids):
            raise ValueError("Source-pack rule template IDs must be unique")
        return self


class SourcePackOverrides(BaseModel):
    monitor_interval_minutes: int | None = Field(default=None, gt=0)
    expected_refresh_minutes: int | None = Field(default=None, gt=0)


class SourcePackMaterialization(BaseModel):
    pack_id: SourcePackId
    pack_name: str
    role_mapping: dict[str, str]
    config: MonitoringConfig


def _role(
    role_id: str,
    label: str,
    description: str,
    *,
    required: bool = True,
) -> SourcePackRole:
    return SourcePackRole(
        id=role_id,
        label=label,
        description=description,
        required=required,
    )


def _not_null(
    rule_id: str,
    name: str,
    field_role: str,
    *,
    severity: HealthStatus = HealthStatus.CRITICAL,
    impact: str,
) -> SourcePackRuleTemplate:
    return SourcePackRuleTemplate(
        id=rule_id,
        name=name,
        kind=DataRuleKind.NOT_NULL,
        severity=severity,
        field_role=field_role,
        likely_impact=impact,
        suggested_investigation="Check the upstream export or transformation that populates this field.",
    )


def _non_empty_rows() -> SourcePackRuleTemplate:
    return SourcePackRuleTemplate(
        id="non_empty",
        name="Dataset must not be empty",
        kind=DataRuleKind.ROW_COUNT_RANGE,
        severity=HealthStatus.CRITICAL,
        minimum=1,
        likely_impact="An empty business dataset can make a downstream report look complete while carrying no usable records.",
        suggested_investigation="Check whether the upstream extract, query, filter, or scheduled refresh returned zero rows.",
    )


_PACKS: dict[SourcePackId, SourcePack] = {
    SourcePackId.FP_AND_A_FORECAST: SourcePack(
        id=SourcePackId.FP_AND_A_FORECAST,
        name="FP&A Forecast",
        description="Forecast or planning extracts where row identity, as-of date and modeled amounts must remain trustworthy.",
        roles=[
            _role("record_key", "Forecast row key", "Field that uniquely identifies one forecast row."),
            _role("as_of_date", "As-of / update date", "Field that proves how current the forecast extract is."),
            _role("amount", "Forecast amount", "Primary numeric amount used in forecast analysis."),
            _role("period", "Forecast period", "Business period being forecast.", required=False),
            _role("scenario", "Scenario", "Scenario such as budget, base, upside or downside.", required=False),
        ],
        monitor_interval_minutes=240,
        expected_refresh_minutes=1440,
        latest_date_role="as_of_date",
        unique_key_roles=["record_key"],
        numeric_roles=["amount"],
        row_diff_roles=["amount", "period", "scenario"],
        rule_templates=[
            _non_empty_rows(),
            _not_null(
                "record_key_required",
                "Forecast row key is required",
                "record_key",
                impact="Missing row identity can make additions, removals and changed forecast lines ambiguous.",
            ),
            _not_null(
                "as_of_date_required",
                "Forecast as-of date is required",
                "as_of_date",
                severity=HealthStatus.WARNING,
                impact="Missing update dates weaken freshness evidence for forecast reporting.",
            ),
            _not_null(
                "amount_required",
                "Forecast amount is required",
                "amount",
                impact="Missing modeled amounts can silently understate or distort forecast totals.",
            ),
        ],
    ),
    SourcePackId.SALES_PIPELINE: SourcePack(
        id=SourcePackId.SALES_PIPELINE,
        name="Sales Pipeline",
        description="Opportunity exports where row identity, update recency, stage and optional deal value drive pipeline reporting.",
        roles=[
            _role("opportunity_id", "Opportunity ID", "Unique opportunity or deal identifier."),
            _role("updated_at", "Last updated date", "Timestamp or date showing when the opportunity was last refreshed."),
            _role("stage", "Pipeline stage", "Current opportunity stage used in funnel reporting."),
            _role("amount", "Opportunity amount", "Optional deal value or expected revenue field.", required=False),
        ],
        monitor_interval_minutes=60,
        expected_refresh_minutes=1440,
        latest_date_role="updated_at",
        unique_key_roles=["opportunity_id"],
        numeric_roles=["amount"],
        row_diff_roles=["stage", "amount"],
        rule_templates=[
            _non_empty_rows(),
            _not_null(
                "opportunity_id_required",
                "Opportunity ID is required",
                "opportunity_id",
                impact="Missing deal identity can double-count or obscure pipeline movement.",
            ),
            _not_null(
                "updated_at_required",
                "Opportunity update date is required",
                "updated_at",
                severity=HealthStatus.WARNING,
                impact="Missing update dates weaken evidence that the pipeline export is current.",
            ),
            _not_null(
                "stage_required",
                "Pipeline stage is required",
                "stage",
                impact="Missing stage values can distort funnel, conversion and forecast reporting.",
            ),
        ],
    ),
    SourcePackId.CLAIMS_REGISTER: SourcePack(
        id=SourcePackId.CLAIMS_REGISTER,
        name="Claims Register",
        description="Claims or case registers where record identity, recency, status and optional incurred value feed risk reporting.",
        roles=[
            _role("claim_id", "Claim ID", "Unique claim or case identifier."),
            _role("updated_at", "Last updated date", "Timestamp or date showing when the claim record was refreshed."),
            _role("status", "Claim status", "Current claim or case status."),
            _role("incurred_amount", "Incurred amount", "Optional incurred, reserve or loss amount.", required=False),
        ],
        monitor_interval_minutes=60,
        expected_refresh_minutes=1440,
        latest_date_role="updated_at",
        unique_key_roles=["claim_id"],
        numeric_roles=["incurred_amount"],
        row_diff_roles=["status", "incurred_amount"],
        rule_templates=[
            _non_empty_rows(),
            _not_null(
                "claim_id_required",
                "Claim ID is required",
                "claim_id",
                impact="Missing claim identity can create duplicate or untraceable loss records.",
            ),
            _not_null(
                "updated_at_required",
                "Claim update date is required",
                "updated_at",
                severity=HealthStatus.WARNING,
                impact="Missing update dates weaken evidence that claim reporting reflects current handling activity.",
            ),
            _not_null(
                "status_required",
                "Claim status is required",
                "status",
                impact="Missing status can distort open/closed inventory and operational workload reporting.",
            ),
        ],
    ),
    SourcePackId.OPERATIONS_ORDERS: SourcePack(
        id=SourcePackId.OPERATIONS_ORDERS,
        name="Operations Orders",
        description="Order or work-item feeds where identity, update recency and operational status should remain stable between checks.",
        roles=[
            _role("order_id", "Order ID", "Unique order, job or work-item identifier."),
            _role("updated_at", "Last updated date", "Timestamp or date showing when the operational record changed."),
            _role("status", "Order status", "Current workflow or fulfillment status."),
            _role("quantity", "Quantity", "Optional units, items or workload quantity.", required=False),
        ],
        monitor_interval_minutes=30,
        expected_refresh_minutes=120,
        latest_date_role="updated_at",
        unique_key_roles=["order_id"],
        numeric_roles=["quantity"],
        row_diff_roles=["status", "quantity"],
        rule_templates=[
            _non_empty_rows(),
            _not_null(
                "order_id_required",
                "Order ID is required",
                "order_id",
                impact="Missing order identity can make operational changes impossible to reconcile reliably.",
            ),
            _not_null(
                "updated_at_required",
                "Order update date is required",
                "updated_at",
                severity=HealthStatus.WARNING,
                impact="Missing update dates weaken evidence that operational reporting is current.",
            ),
            _not_null(
                "status_required",
                "Order status is required",
                "status",
                impact="Missing workflow status can distort backlog and fulfillment reporting.",
            ),
        ],
    ),
    SourcePackId.FINANCE_CLOSE: SourcePack(
        id=SourcePackId.FINANCE_CLOSE,
        name="Finance Close",
        description="Close or ledger extracts where entry identity, recency and amounts support period-end reporting and reconciliation.",
        roles=[
            _role("entry_id", "Entry ID", "Unique journal, ledger or close-workflow record identifier."),
            _role("updated_at", "Last updated date", "Timestamp or date proving the close extract is current."),
            _role("amount", "Amount", "Primary financial amount used in reconciliation or close reporting."),
            _role("posting_date", "Posting date", "Optional accounting posting or effective date.", required=False),
            _role("close_status", "Close status", "Optional workflow or reconciliation status.", required=False),
        ],
        monitor_interval_minutes=60,
        expected_refresh_minutes=1440,
        latest_date_role="updated_at",
        unique_key_roles=["entry_id"],
        numeric_roles=["amount"],
        row_diff_roles=["amount", "posting_date", "close_status"],
        rule_templates=[
            _non_empty_rows(),
            _not_null(
                "entry_id_required",
                "Finance entry ID is required",
                "entry_id",
                impact="Missing entry identity weakens reconciliation and can hide duplicate or changed close records.",
            ),
            _not_null(
                "updated_at_required",
                "Finance update date is required",
                "updated_at",
                severity=HealthStatus.WARNING,
                impact="Missing update dates weaken evidence that close reporting uses the current extract.",
            ),
            _not_null(
                "amount_required",
                "Finance amount is required",
                "amount",
                impact="Missing financial amounts can silently distort close totals and reconciliations.",
            ),
        ],
    ),
    SourcePackId.CUSTOMER_EXPORT: SourcePack(
        id=SourcePackId.CUSTOMER_EXPORT,
        name="Customer Export",
        description="Customer or account exports where stable identity and update recency support reporting, segmentation and downstream models.",
        roles=[
            _role("customer_id", "Customer ID", "Unique customer or account identifier."),
            _role("updated_at", "Last updated date", "Timestamp or date proving the customer extract is current."),
            _role("status", "Customer status", "Optional lifecycle or account status.", required=False),
            _role("customer_value", "Customer value", "Optional numeric value such as ARR, balance or lifetime value.", required=False),
        ],
        monitor_interval_minutes=240,
        expected_refresh_minutes=1440,
        latest_date_role="updated_at",
        unique_key_roles=["customer_id"],
        numeric_roles=["customer_value"],
        row_diff_roles=["status", "customer_value"],
        rule_templates=[
            _non_empty_rows(),
            _not_null(
                "customer_id_required",
                "Customer ID is required",
                "customer_id",
                impact="Missing customer identity can duplicate or orphan records in downstream reporting.",
            ),
            _not_null(
                "updated_at_required",
                "Customer update date is required",
                "updated_at",
                severity=HealthStatus.WARNING,
                impact="Missing update dates weaken evidence that customer reporting is current.",
            ),
        ],
    ),
}


def list_source_packs() -> list[SourcePack]:
    return [_PACKS[pack_id].model_copy(deep=True) for pack_id in SourcePackId]


def get_source_pack(pack_id: SourcePackId | str) -> SourcePack:
    try:
        normalized = SourcePackId(pack_id)
    except ValueError as exc:
        raise KeyError(f"Unknown source pack: {pack_id}") from exc
    return _PACKS[normalized].model_copy(deep=True)


def materialize_source_pack(
    pack_id: SourcePackId | str,
    role_mapping: dict[str, str],
    *,
    overrides: SourcePackOverrides | None = None,
) -> SourcePackMaterialization:
    pack = get_source_pack(pack_id)
    known_roles = {role.id: role for role in pack.roles}
    unknown = sorted(set(role_mapping) - set(known_roles))
    if unknown:
        raise ValueError(f"Unknown role mappings for {pack.name}: {', '.join(unknown)}")

    normalized_mapping: dict[str, str] = {}
    for role_id, field_name in role_mapping.items():
        if not field_name or field_name != field_name.strip():
            raise ValueError(f"Role mapping {role_id!r} must use a non-empty trimmed field name")
        normalized_mapping[role_id] = field_name

    missing = [
        role.id for role in pack.roles if role.required and role.id not in normalized_mapping
    ]
    if missing:
        raise ValueError(f"Missing required role mappings for {pack.name}: {', '.join(missing)}")

    fields = list(normalized_mapping.values())
    if len(set(fields)) != len(fields):
        raise ValueError("Source-pack role mappings must use distinct source fields")

    resolved_overrides = overrides or SourcePackOverrides()
    data_rules: list[DataRule] = []
    for template in pack.rule_templates:
        field = None
        if template.field_role is not None:
            field = normalized_mapping.get(template.field_role)
            if field is None:
                continue
        data_rules.append(
            DataRule(
                id=f"pack.{pack.id.value}.{template.id}",
                name=template.name,
                kind=template.kind,
                severity=template.severity,
                field=field,
                minimum=template.minimum,
                maximum=template.maximum,
                likely_impact=template.likely_impact,
                suggested_investigation=template.suggested_investigation,
            )
        )

    def mapped(role_ids: list[str]) -> list[str]:
        return [normalized_mapping[role_id] for role_id in role_ids if role_id in normalized_mapping]

    config = MonitoringConfig(
        monitor_interval_minutes=(
            resolved_overrides.monitor_interval_minutes or pack.monitor_interval_minutes
        ),
        expected_refresh_minutes=(
            resolved_overrides.expected_refresh_minutes or pack.expected_refresh_minutes
        ),
        latest_date_field=(
            normalized_mapping.get(pack.latest_date_role) if pack.latest_date_role else None
        ),
        unique_keys=mapped(pack.unique_key_roles),
        numeric_fields=mapped(pack.numeric_roles),
        row_diff_fields=mapped(pack.row_diff_roles),
        data_rules=data_rules,
    )
    return SourcePackMaterialization(
        pack_id=pack.id,
        pack_name=pack.name,
        role_mapping=dict(normalized_mapping),
        config=config,
    )
