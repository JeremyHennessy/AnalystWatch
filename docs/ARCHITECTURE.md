# AnalystWatch Core v0.3 Architecture

## Decision

Core v0.3 remains a Python modular monolith. FastAPI is the interactive local/API surface, while GitHub Pages is a generated read-only test surface. The monitoring engine remains authoritative; no detector logic is duplicated in browser JavaScript.

SQLite persists accepted source definitions, observations, findings, profiles, and the selected baseline. For the temporary GitHub-hosted test environment, a dedicated `monitor-state` branch retains the small SQLite database between scheduled GitHub Actions runs. This is intentionally a testing mechanism, not the production storage design.

The repository is currently public, so `monitor-state` is public as well. It must contain only non-secret test state. Secret-bearing sources remain out of scope until storage and credential handling are designed explicitly.

## Data flow

New-source onboarding and monitoring are deliberately separate transactions:

```text
Candidate SourceDefinition
  -> ingest + profile (preflight only)
  -> validate declared source contracts
  -> Ready / Needs attention
  -> accept definition only when Ready
  -> first monitoring check later establishes baseline

Accepted SourceDefinition
  -> schedule decision
  -> ingest (CSV / XLSX / JSON / REST JSON)
  -> pandas DataFrame
  -> source-contract profiling
  -> freshness + baseline/history comparison detectors
  -> findings
  -> Healthy / Warning / Critical
  -> SQLite observation history
  -> FastAPI dashboard/API
  -> static Pages export
```

Preflight never writes a source, observation, or baseline. Onboarding re-runs preflight server-side before persistence rather than trusting a previous browser result.

## Components

- `models.py` — source configuration, profiles, findings, observations, and schedule decisions.
- `config.py` — validated JSON source-definition loading.
- `preflight.py` — non-persistent candidate ingestion/profiling plus source-contract validation.
- `scheduler.py` — monitor cadence decisions independent from source freshness expectations.
- `ingest.py` — file/API acquisition; API responses retain HTTP status, timing, `Last-Modified`, and ETag evidence where available.
- `profile.py` — structural, completeness, cardinality, numeric, categorical, explicit numeric-field coercion, and opt-in date-field inference.
- `detectors.py` — deterministic comparisons against the selected baseline and, when enough trusted history exists, recent healthy-history reference windows.
- `storage.py` — SQLite source definitions, observations, history, and baseline pointer.
- `service.py` — preflight/onboarding plus monitoring transactions, due-source execution, and all-source execution.
- `web.py` — interactive local FastAPI dashboard/API and onboarding endpoints.
- `templates/onboard.html` / `static/onboard.css` — local new-source workflow isolated from the shared dashboard stylesheet.
- `pages.py` — read-only static dashboard exporter for GitHub Pages.
- `scripts/live_source_smoke.py` — real-upstream contract validation used by CI.
- `cli.py` — source sync, scheduling, checking, baseline promotion, Pages build, and local serving.

## Onboarding contract preflight

A source definition can be syntactically valid while still being analytically unsafe. Preflight therefore tests the candidate against actual source data before it enters monitoring.

Blocking checks currently include:

- source unavailable or unusable;
- zero returned records;
- configured numeric field missing or entirely empty;
- fewer than 95% of non-null values in a configured numeric field parse numerically;
- configured unique key missing, null, or duplicated;
- configured freshness field missing or containing no parseable dates;
- expected refresh configured with no usable freshness evidence.

A numeric parse rate from 95% to below 100% is a warning rather than a blocker so imperfect but intentional feeds can be reviewed instead of silently rejected. Existing freshness-detector output is also surfaced during preflight as evidence. A currently stale source can therefore be structurally Ready while warning that its current data is old.

`MonitorService.onboard_source` refuses an existing source ID. Editing existing definitions is intentionally separate so a new-source flow cannot silently rewrite an established monitoring contract.

Successful onboarding saves only the definition. It does not reuse the preflight profile as a baseline because that would silently convert an inspection into a persisted monitoring event. The source is immediately due, and its first explicit/scheduled check establishes the baseline through the normal monitor transaction.

## Source contracts and numeric strings

Real-source validation exposed a concrete ingestion/profiling boundary: some APIs publish analytically numeric fields as JSON strings. U.S. Treasury Fiscal Data is one such source. Successful JSON ingestion alone therefore does not prove numeric drift protection is active.

`MonitoringConfig.numeric_fields` is an explicit source contract. Only fields named there are coerced with numeric parsing during profiling. Values that cannot be parsed become null evidence. Unconfigured text fields remain text even when they look numeric, preventing identifiers and codes from being silently reinterpreted.

This keeps type interpretation source-specific, deterministic, reviewable, and testable instead of relying on broad automatic inference.

## Scheduling

`monitor_interval_minutes` controls how often AnalystWatch should inspect a source. It is distinct from `expected_refresh_minutes`, which describes how fresh the upstream data is expected to be.

A never-checked enabled source is due immediately. After a check, the next due time is the last observation time plus the monitoring interval. Disabled sources are never due.

The GitHub Actions test deployment runs hourly. Scheduled runs execute only due sources. Push/manual runs execute all enabled sources so configuration or fixture changes are visible immediately.

## Signal-quality reference windows

The explicit approved baseline remains retained and visible. Once at least `min_history_observations` recent **Healthy** observations exist, row-count, null-rate, numeric-median, and uniqueness checks use the median of that healthy history as their operational comparison reference while still exposing the explicit baseline in the finding evidence.

This prevents an old baseline from over-escalating normal gradual growth. Unhealthy observations are excluded from reference history so detected anomalies do not teach the monitor that the anomaly is normal.

Schema and categorical-presence checks continue to compare against the explicit baseline because those semantics should not silently drift with recent history.

## Freshness evidence

Freshness evidence is deliberately explicit:

- files can use filesystem modification time;
- APIs can use HTTP `Last-Modified` when supplied;
- a configured `latest_date_field` can use content dates;
- `infer_latest_date_field` is opt-in and only considers conservative, date-like field names with high parseability.

ETag is retained as observation evidence but does not by itself prove freshness.

## Real-source validation gate

The live-source smoke workflow complements deterministic tests with actual upstream access from GitHub Actions. For every enabled repository-configured source, it verifies:

- the source is available and produces a profile;
- the first observation is not Critical;
- every configured numeric field exists and is profiled numerically;
- every configured content freshness field yields a parseable latest date.

The first run on August 21, 2026 verified Bank of Canada USD/CAD and U.S. Treasury Debt to the Penny with 30 rows each and no contract failures. The v0.3 service changes were also run through the same smoke gate. This establishes integration behavior at those checkpoints; it does not establish long-run false-positive/false-negative performance.

## GitHub Pages test deployment

GitHub Pages cannot run FastAPI. The Pages workflow therefore:

1. restores the small SQLite monitoring database from `monitor-state`;
2. syncs repository source definitions from `config/sources.json`;
3. runs due/all checks;
4. renders a static site from the resulting stored observations;
5. persists the updated database back to `monitor-state`;
6. deploys only the generated static `site/` artifact to Pages.

The Pages site does not expose onboarding/write controls. Source details do expose the configured monitoring contract so the hosted test surface remains inspectable.

API query strings are removed from public static output to reduce accidental exposure. Authenticated/secret-bearing APIs are still out of scope.

## Tradeoffs / current limitations

- The public `monitor-state` branch is acceptable only for small, non-secret test state; it creates Git history growth and is not a production database strategy.
- GitHub scheduled workflows are not a real-time scheduler and can run later than the requested cron time.
- Pages is read-only; onboarding, interactive check, and baseline actions require the local FastAPI app/API.
- New-source preflight does not yet extend to edits of existing source contracts.
- Authentication and source secrets are intentionally out of scope.
- Explicit numeric-field contracts require source-aware configuration; broad automatic numeric-string inference is intentionally avoided.
- Schema rename inference is not implemented; removed/added fields are reported without claiming a rename.
- Historical reference windows are deterministic rolling medians, not statistical forecasting or machine learning.
- Initial real-source validation is complete, but longer observation history is still required before threshold tuning or notification delivery.
