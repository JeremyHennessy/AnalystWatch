# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch monitors CSV, Excel, JSON, REST API and Microsoft 365 Excel inputs for silent reliability failures and answers a practical analyst question: **can I trust the data feeding my analysis today?**

## Product v0.18 status

Product v0.18 adds **row-level / key-level change analysis** for sources with configured unique keys. It extends deterministic monitoring evidence without changing Health classification, detector thresholds, incident semantics or notification-state behavior.

AnalystWatch can now answer not only that a dataset changed, but how the keyed records changed relative to:

- the previous successful observation; and
- the active baseline.

For each available comparison it reports:

- Added rows;
- Removed rows;
- Changed rows;
- Unchanged rows;
- per-column changed-value counts;
- bounded examples of added, removed and changed keys in the authenticated/local application view.

The source detail page exposes this as **Key-level changes** under the existing analyst-facing Product v0.16.1 UI hierarchy.

## Enabling row comparison

Row comparison requires configured `unique_keys`. Composite keys are supported.

Optional `row_diff_fields` can restrict which non-key columns are retained for comparison. When no field allowlist is supplied, AnalystWatch compares columns within the configured safety limits.

The default safety configuration is intentionally bounded:

```text
row_diff_max_rows = 5000
row_diff_max_columns = 50
row_diff_max_snapshot_bytes = 1000000
row_diff_sample_limit = 20
row_diff_snapshot_retention = 2
```

The configurable hard ceilings remain bounded as well. A source with missing, null or duplicate configured keys, or a dataset that exceeds its configured snapshot limits, receives explicit row-diff-unavailable evidence instead of an unbounded raw-data capture.

Row-diff availability does **not** alter Healthy / Warning / Critical classification.

## Retention and privacy

AnalystWatch is not becoming a raw-data archive.

The active baseline snapshot plus only the configured recent successful comparison snapshots are retained. Older observations keep aggregate row-diff counts but their raw snapshots and bounded sample values are removed.

This retention behavior is verified across:

- legacy SQLite;
- namespaced SQLite;
- `MemoryStore`;
- PostgreSQL.

Generated public GitHub Pages and `state.json` do not publish the new row snapshots or row-diff key/value samples. They may show aggregate Added / Removed / Changed / Unchanged counts and changed-column counts.

This v0.18 privacy boundary applies specifically to the new row-diff payload. Existing deterministic detector findings retain their established public-output policy; v0.18 does not silently redact or rewrite previously approved detector evidence.

## Existing product foundation

Product v0.17 Microsoft 365 Excel support remains intact and feeds the same row-comparison path when keys are configured. The broader foundation also remains unchanged:

- deterministic ingestion/profiling/detectors;
- baseline/history/review and incident lifecycle;
- workspace-aware SQLite/namespaced SQLite/PostgreSQL persistence;
- authenticated workspace authorization;
- managed-runtime readiness;
- existing delivery-attempt/idempotency/reconciliation semantics;
- GitHub Pages monitoring on the existing legacy/local hosted path.

No production PostgreSQL cutover, real Microsoft tenant connection or successful real Resend side effect is implied by v0.18.

## Verification

The v0.18 functional checkpoint passed:

- Ruff;
- compile/import checks;
- **183 deterministic tests** against PostgreSQL 16 CI;
- exact row add/remove/change comparison tests;
- composite-key and field-allowlist tests;
- duplicate/null/oversized-key refusal tests;
- four-backend snapshot-retention conformance;
- public row-diff payload redaction tests;
- analyst-facing source-detail row-change rendering;
- live-source smoke against the unchanged Bank of Canada / U.S. Treasury sources.

## Next milestone

Product v0.19 is **Power BI Guard**: monitor semantic-model refresh state and correlate it with AnalystWatch source health so a technically successful Power BI refresh is not mistaken for trustworthy data when its upstream source is stale or unhealthy.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
