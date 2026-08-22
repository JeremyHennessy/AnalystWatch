# AnalystWatch Product v0.23 Architecture

## Decision

Product v0.23 adds deterministic analyst-defined Data Rules to the existing source evidence pipeline.

The architectural rule is: **a Data Rule is another deterministic source finding, not a second Health system.**

```text
SourceDefinition + MonitoringConfig.data_rules
        ↓
existing connector ingestion
        ↓
pandas DataFrame
        ↓
existing profiling / source evidence
        ↓
Data Rule evaluation
        ↓
ordinary Finding[]
        ↓
existing health_from_findings(...)
        ↓
existing observations / incidents / notifications / reviews
```

No rule-specific observation, incident, notification, baseline or persistence state machine is introduced.

## Rule model

`MonitoringConfig.data_rules` contains typed `DataRule` objects.

Supported kinds are:

- `not_null` — requires `field` and accepts no range/allowed-value parameters;
- `allowed_values` — requires `field` plus a non-empty unique allowed-value list;
- `numeric_range` — requires `field` and at least one numeric minimum/maximum;
- `row_count_range` — accepts integer row-count minimum/maximum and no field.

Every rule has:

- stable explicit `id`;
- analyst-facing `name`;
- failure `severity` of Warning or Critical;
- optional `likely_impact`;
- optional `suggested_investigation`.

Pydantic validation fails closed for incompatible/missing parameters, invalid bounds, empty/duplicate allowed values, invalid severity and duplicate rule IDs within one monitoring configuration.

## Deterministic evaluation boundary

`data_rules.evaluate_data_rules(...)` receives the already-ingested DataFrame and configured rules.

It does not execute SQL, user code or an expression language. It evaluates only the four typed operations above.

Field-based failures produce aggregate evidence:

```text
{
  violations: <count>,
  rows: <row count>,
  violation_pct: <bounded ratio>
}
```

The finding also retains the declared rule condition for authenticated/local investigation. Failing row values are never copied into the Data Rule finding.

A missing configured rule field is itself deterministic rule-failure evidence.

## Preflight boundary

Preflight uses the same ingested DataFrame that would be monitored and evaluates configured Data Rules before source acceptance.

A configured rule failure makes preflight not ready, even when the rule's runtime failure severity is Warning. This is intentional: onboarding must not establish a newly declared contract around data that already violates that contract.

Preflight therefore remains the single source-acceptance boundary for connector availability, declared field/key/date contracts and Data Rules.

There is no Data-Rule-specific onboarding endpoint.

## Runtime Health boundary

During `MonitorService.check_source(...)`, deterministic Data Rule findings are appended to the existing finding collection before the existing `health_from_findings(...)` call.

This preserves one Health derivation:

- no findings → Healthy;
- one or more Warning findings and no Critical → Warning;
- any Critical finding → Critical.

Data Rules therefore reuse existing incident transition, notification candidate, delivery, review and baseline behavior without directly mutating those systems.

A rule cannot separately mark an incident Open/Recovered or override another detector's severity.

## Analyst-facing UI boundary

The existing Add Source screen contains a typed Data Rule builder. It collects the same typed contract represented by `DataRule` and sends it through the normal preflight/onboarding API flow.

The existing generic source-detail Finding renderer is deliberately reused for runtime rule evidence. No separate rule finding-card architecture is introduced.

Authenticated/local source detail can show the private declared rule condition and custom guidance because it is an operator surface. The evaluator still omits failing row values.

## Public/static privacy boundary

The public GitHub Pages snapshot is less privileged than the authenticated/local application.

For each source, fields referenced by configured Data Rules are treated as private public-export metadata. The static exporter therefore:

1. Genericizes Data Rule findings:
   - detector ID becomes generic `data_rule`;
   - rule ID/name are removed;
   - declared field, allowed set and numeric bounds are removed;
   - custom impact/investigation text is replaced by generic guidance;
   - aggregate current evidence such as violation count/rows/percentage remains.
2. Removes Data-Rule-referenced fields from the exported `DatasetProfile.columns` map and recalculates the public profile column count.
3. Clears public latest-date evidence if the latest-date field is itself a Data Rule field.
4. Removes those fields from static-visible numeric-field, unique-key and row-diff configuration metadata.
5. Removes those field names from row-diff key/changed-column metadata and genericizes a row-diff reason that would expose one.
6. Genericizes ordinary detector findings when their serialized evidence would reveal a private Data Rule field.

This policy is deliberately **selective**. Unrelated public profile evidence remains visible so the public monitoring demo retains useful non-private context.

Existing row-diff raw samples/row snapshots remain excluded from public output by the earlier Product v0.18 privacy boundary.

## Single evidence pipeline

Product v0.23 preserves the distinction between:

- ingestion/provider evidence;
- deterministic profile/detector evidence;
- deterministic Data Rule evidence;
- derived Health;
- derived incident/delivery operations.

Data Rules do not reinterpret connector availability or source timestamps and do not alter existing detector thresholds.

## Persistence

No database migration is required for Product v0.23.

`DataRule` is part of `MonitoringConfig`, which already persists inside `SourceDefinition` through the existing legacy/namespaced/PostgreSQL source-definition contract.

No separate Data Rule result table is introduced; runtime results are ordinary `Finding` objects inside normal observations.

## Preserved connector architecture

Product v0.23 does not change the connector semantics established through v0.22:

- CSV, XLSX, JSON and REST API ingestion;
- Microsoft 365 Excel-table ingestion through Microsoft Graph delegated access;
- Google Sheets range ingestion through Google Sheets API v4;
- environment-backed request-header credential references;
- provider availability evidence;
- Google Sheets freshness limitation: values reads do not fabricate `source_modified_at` and expected refresh requires content-date evidence;
- public Google Sheets location redaction to `Google Sheets · <A1 range>`.

No real Google Workspace credential was exercised in this repository work, so live Google tenant access is not claimed.

## Preserved product architecture

Product v0.23 does not change:

- detector thresholds or Healthy/Warning/Critical semantics;
- baseline promotion/review;
- Healthy-history reference behavior;
- incident lifecycle;
- notification policy;
- Prepared/Succeeded/Failed delivery semantics;
- idempotency, retry or explicit reconciliation safety;
- Viewer / Operator / Admin authorization;
- workspace persistence boundaries;
- key-level row comparison semantics/retention;
- Power BI Guard trust logic;
- dependency graph traversal/storage;
- Teams delivery state handling;
- Delivery Ops reconciliation model;
- approved source-detail UI layout.

## Verification

The functional/UI/privacy checkpoint `ba779642aeaa971ceda38fa1799ea4f2387904a2` passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed suite;
- **253 passed, 1 warning**;
- live-source smoke #100.

Coverage proves:

- typed validation and duplicate-ID rejection;
- all four deterministic rule kinds;
- bounded field-level rule evidence;
- preflight failure before onboarding acceptance;
- runtime Warning and Critical Health integration;
- reuse of existing incident/notification lifecycle;
- no failing row values in Data Rule findings;
- typed onboarding builder;
- full authenticated/local rule evidence;
- static rule-contract redaction;
- selective profile/config/row-diff redaction for Data-Rule-referenced fields;
- preservation of unrelated public profile evidence.

Release-only version/documentation changes are gated again on their exact head before merge.

## Next architecture step

Product v0.24 should derive deterministic reliability scorecards/trust badges from existing observation history, incident history and rule/detector outcomes. Any score must remain explainable back to the underlying evidence and must not become a second opaque Health classifier.

Product v0.25 should then add preconfigured source packs over existing configuration primitives. AI investigation, if added later, remains an explanation/summarization layer downstream of deterministic evidence.
