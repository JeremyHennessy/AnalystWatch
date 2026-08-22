# AnalystWatch Product v0.18 Architecture

## Decision

Product v0.18 adds bounded row/key comparison evidence to the existing observation pipeline. It does not introduce a second Health classifier, incident engine or raw-data warehouse.

The feature is enabled only when a source has configured `unique_keys`.

```text
ingestion
→ DataFrame
→ existing deterministic profile/detectors
→ bounded row snapshot
→ compare with previous successful observation
→ compare with active baseline
→ row-diff evidence
→ existing observation persistence
```

Row-diff evidence is informational and does not independently change Healthy / Warning / Critical state.

## Snapshot contract

`RowSnapshot` stores only the bounded comparison material required for configured-key diffs:

- configured key fields;
- selected comparison value fields;
- normalized row values;
- row count;
- serialized-size evidence.

`row_diff_fields` may explicitly allowlist comparison fields. If omitted, the source columns are used subject to safety limits.

Snapshot creation refuses comparison when:

- configured keys are missing;
- key values are null;
- configured keys are not unique;
- configured comparison fields are missing;
- row count exceeds the configured limit;
- retained column count exceeds the configured limit;
- serialized snapshot size exceeds the configured limit.

The refusal is explicit `RowDiffEvidence`; it does not turn a Healthy source into Warning or Critical.

## Comparison contract

A successful keyed comparison produces deterministic counts for:

- added keys;
- removed keys;
- changed keys;
- unchanged keys;
- changed-value count by column.

Bounded examples may contain:

- added key/value examples;
- removed key/value examples;
- changed keys with previous/current values by changed column.

Comparison is performed independently against the previous successful observation and the active baseline when those reference snapshots are available.

## Retention boundary

Raw comparison material is deliberately short-lived.

After a successful check, AnalystWatch retains:

1. the active baseline row snapshot; and
2. the configured number of most recent successful row snapshots.

Older observations retain aggregate row-diff evidence but lose their raw `row_snapshot` and bounded sample lists.

The pruning contract is part of `MonitoringStore` and is verified across legacy SQLite, namespaced SQLite, `MemoryStore` and PostgreSQL. Product v0.18 therefore does not depend on one storage backend behaving more permissively than another.

## Public-output boundary

Static GitHub Pages use `strip_row_diff_raw_payloads(...)` before rendering/public JSON serialization.

Public output retains useful aggregate evidence while removing the new raw row payload:

```text
row_snapshot = null
added_samples = []
removed_samples = []
changed_samples = []
```

Aggregate counts and changed-column counts may remain visible.

The authenticated/local source detail can display bounded examples because it receives the full workspace-authorized observation.

This boundary is intentionally specific to v0.18 row-diff material. Existing detector findings, including category/numeric evidence already exposed by the approved product, retain their pre-v0.18 public-output behavior. Hiding that evidence would be a separate product/security decision and is not smuggled into this milestone.

## Analyst-facing UI

The approved Product v0.16.1 shell is preserved. v0.18 adds one source-detail section, **Key-level changes**, before the existing reliability findings.

For each available reference it answers:

```text
Compare with previous successful / active baseline
Added
Removed
Changed
Unchanged
Most affected columns
```

In the dynamic authenticated/local application, bounded changed-key examples can be expanded. In static Pages, those examples are not rendered and the UI explains that only aggregate row-change evidence is public.

## Preserved behavior

Product v0.18 does not change:

- ingestion semantics for CSV/XLSX/JSON/API/Microsoft Excel;
- detector thresholds or deterministic Health classification;
- source scheduling;
- baseline-promotion rules;
- review semantics;
- incident lifecycle;
- notification candidate policy;
- delivery idempotency/retry/reconciliation;
- workspace authorization;
- hosted legacy SQLite/local-auth defaults.

## Verification

The frozen v0.18 functional checkpoint passed **183 tests**, Ruff and compile checks against PostgreSQL 16 CI, plus the existing live-source smoke gate.

Coverage includes exact row comparison, composite keys, field allowlists, size/key refusal, retention/pruning across all persistence implementations, public row-diff redaction and analyst-facing source-detail rendering.

## Next architecture step

Product v0.19 should introduce Power BI Guard as a new external asset/refresh evidence boundary. It should correlate Power BI refresh health with existing AnalystWatch source reliability rather than interpreting a successful dashboard refresh as proof that the upstream data was trustworthy.
