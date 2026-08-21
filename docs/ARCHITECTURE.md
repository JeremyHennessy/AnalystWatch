# AnalystWatch Core v0.2 Architecture

## Decision

Core v0.2 remains a Python modular monolith. FastAPI is the interactive local/API surface, while GitHub Pages is a generated read-only test surface. The monitoring engine remains authoritative; no detector logic is duplicated in browser JavaScript.

SQLite persists source definitions, observations, findings, profiles, and the selected baseline. For the temporary GitHub-hosted test environment, a dedicated private `monitor-state` branch retains the small SQLite database between scheduled GitHub Actions runs. This is intentionally a testing mechanism, not the production storage design.

## Data flow

```text
SourceDefinition
  -> schedule decision
  -> ingest (CSV / XLSX / JSON / REST JSON)
  -> pandas DataFrame
  -> profile
  -> freshness + baseline/history comparison detectors
  -> findings
  -> Healthy / Warning / Critical
  -> SQLite observation history
  -> FastAPI dashboard/API
  -> static Pages export
```

## Components

- `models.py` — source configuration, profiles, findings, observations, and schedule decisions.
- `config.py` — validated JSON source-definition loading.
- `scheduler.py` — monitor cadence decisions independent from source freshness expectations.
- `ingest.py` — file/API acquisition; API responses retain HTTP status, timing, `Last-Modified`, and ETag evidence where available.
- `profile.py` — structural, completeness, cardinality, numeric, categorical, and opt-in date-field inference.
- `detectors.py` — deterministic comparisons against the selected baseline and, when enough trusted history exists, recent healthy-history reference windows.
- `storage.py` — SQLite source definitions, observations, history, and baseline pointer.
- `service.py` — monitoring transactions, due-source execution, and all-source execution.
- `web.py` — interactive local FastAPI dashboard/API.
- `pages.py` — read-only static dashboard exporter for GitHub Pages.
- `cli.py` — source sync, scheduling, checking, baseline promotion, Pages build, and local serving.

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

## GitHub Pages test deployment

GitHub Pages cannot run FastAPI. The Pages workflow therefore:

1. restores the small SQLite monitoring database from `monitor-state`;
2. syncs repository source definitions from `config/sources.json`;
3. runs due/all checks;
4. renders a static site from the resulting stored observations;
5. persists the updated database back to `monitor-state`;
6. deploys only the generated static `site/` artifact to Pages.

API query strings are removed from public static output to reduce accidental secret exposure. Secret-bearing authenticated APIs are still out of scope for this milestone.

## Tradeoffs / current limitations

- The `monitor-state` branch is acceptable for small private test state but will create Git history growth and is not a production database strategy.
- GitHub scheduled workflows are not a real-time scheduler and can run later than the requested cron time.
- Pages is read-only; interactive check/baseline actions require the local FastAPI app/API.
- Authentication and source secrets are intentionally out of scope.
- Schema rename inference is not implemented; removed/added fields are reported without claiming a rename.
- Historical reference windows are deterministic rolling medians, not statistical forecasting or machine learning.
- Notification delivery remains deferred until signal quality is validated with real sources.
