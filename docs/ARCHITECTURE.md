# AnalystWatch Core v0.4 Architecture

## Decision

Core v0.4 remains a Python modular monolith. FastAPI is the interactive local/API surface, while GitHub Pages is a generated read-only test surface. The deterministic monitoring engine remains authoritative; operational review state does not rewrite observations or detector outcomes.

SQLite persists accepted source definitions, observations, review state, profiles, and the selected baseline. For the temporary GitHub-hosted test environment, a dedicated `monitor-state` branch retains the small SQLite database between scheduled GitHub Actions runs. The repository is currently public, so that branch must contain only non-secret test state.

## Data flow

```text
Candidate/new or edited SourceDefinition
  -> ingest + profile preflight
  -> validate source contracts
  -> accept definition only when Ready

Accepted SourceDefinition
  -> schedule decision
  -> ingest
       -> API header values resolved from environment variables at runtime
  -> profile
  -> freshness + baseline/history comparison detectors
  -> immutable observation evidence + Healthy / Warning / Critical
  -> SQLite observation history
       -> separate Acknowledged / Reviewed operational state
       -> guarded baseline-review/promotion
  -> FastAPI dashboard/API
  -> read-only static Pages export
```

Source preflight never creates an observation or baseline. A successful edit replaces only the source definition; prior observations and the current baseline remain intact. A failed edit leaves the stored definition untouched.

## Components

- `models.py` — source configuration, profiles, findings, observations, review-state and baseline-review models.
- `config.py` — validated JSON source-definition loading.
- `preflight.py` — non-persistent candidate ingestion/profiling plus source-contract validation.
- `scheduler.py` — monitor cadence decisions independent from source freshness expectations.
- `ingest.py` — file/API acquisition and runtime resolution of environment-backed request headers.
- `profile.py` — structural, completeness, cardinality, numeric, categorical, explicit numeric-field coercion, and opt-in date-field inference.
- `detectors.py` — deterministic comparisons against the selected baseline and recent Healthy-history reference windows.
- `storage.py` — SQLite source definitions, observations, review state, history, and baseline pointer.
- `service.py` — onboarding/edit preflight, operational review, guarded baseline promotion, and monitoring transactions.
- `web.py` — interactive local FastAPI dashboard/API and operational write endpoints.
- `pages.py` — read-only static dashboard exporter; public output is intentionally redacted.
- `scripts/live_source_smoke.py` — real-upstream contract validation used by CI.
- `cli.py` — source configuration, scheduling, checking, baseline review/promotion, Pages build, and local serving.

## Credential-safe API configuration

`MonitoringConfig.request_header_env` stores a mapping from HTTP header names to environment-variable names, for example:

```json
{
  "Authorization": "ANALYSTWATCH_API_TOKEN"
}
```

The secret value is resolved immediately before the HTTP request. It is not inserted into `SourceDefinition`, SQLite source JSON, Git history, or Pages state. A missing environment variable becomes availability evidence through the normal ingestion error boundary rather than an uncaught monitor failure.

This is intentionally a reference mechanism, not a complete multi-user secret-management service. For the current GitHub Actions test deployment, secret values must come from the runner environment/GitHub Actions secrets and must never be committed to the public repository or `monitor-state`.

## Safe creation and editing

Interactive/API creation uses `MonitorService.onboard_source`; replacement uses `MonitorService.update_source`. Both perform a fresh server-side preflight before persistence.

A replacement:

- must keep the same source ID;
- must pass current source-contract validation;
- updates only the stored definition;
- preserves existing observations and baseline;
- is not written at all when preflight blocks it.

`sync-sources` remains the explicit code-reviewed path used by the hosted GitHub Actions configuration. It is intentionally separate from interactive onboarding.

## Operational review state

Observation evidence remains immutable. Warning/Critical observations can receive a separate `ObservationReview` state:

- `Acknowledged` — an analyst has seen the signal;
- `Reviewed` — an analyst has completed review of the signal.

Neither state changes `Observation.health`, finding evidence, or the source baseline. This avoids conflating workflow attention with technical resolution.

Review state is stored in its own SQLite table keyed by observation ID. Pages may display the state but exposes no review write controls.

## Guarded baseline review

A baseline promotion is consequential because it changes the comparison reference. Core v0.4 therefore separates candidate review from promotion.

A candidate is blocked when:

- no current baseline exists;
- the candidate is missing or belongs to another source;
- the candidate is unavailable or has no profile;
- the candidate is not Healthy;
- the candidate is already the current baseline.

Promotion additionally requires the caller to provide the baseline ID that was current during review. If the baseline changed after review, promotion fails and a fresh review is required. This optimistic guard prevents a stale review from overwriting a newer approved reference.

## Onboarding contract preflight

Preflight continues to validate source availability, non-empty data, configured numeric fields, declared unique keys, and freshness evidence. It remains a non-persistent inspection transaction. Successful onboarding does not reuse the preflight profile as a baseline; the first normal monitoring check establishes the baseline.

## Source contracts and numeric strings

`MonitoringConfig.numeric_fields` remains explicit. Only fields declared there are coerced numerically, preventing IDs/codes from being silently reinterpreted. This behavior was introduced after real Treasury data demonstrated that analytically numeric API values can arrive as strings.

## Scheduling and signal-quality reference windows

`monitor_interval_minutes` controls how often AnalystWatch checks; `expected_refresh_minutes` describes upstream freshness. Detector behavior and thresholds are unchanged in v0.4.

The explicit baseline remains retained. Once enough recent Healthy observations exist, row-count, null-rate, numeric-median, and uniqueness checks can use the median of recent Healthy history as their operational reference while still exposing the approved baseline. Unhealthy observations are excluded from reference history.

## GitHub Pages test deployment

Pages cannot run FastAPI. The workflow therefore restores the branch-backed test database, syncs repository source definitions, runs monitoring, renders static output, persists updated test state, and deploys only the generated `site/` artifact.

Public-output rules include:

- API query strings are removed from displayed locations;
- request-header secret values are never part of stored source definitions;
- request-header environment-variable names are not rendered into Pages details or `state.json`;
- review state may be displayed, but all operational actions remain local/API-only.

## Verification boundary

The v0.4 functional candidate passed Ruff, compile, 41 deterministic tests, and the existing live-source smoke against the demo, Bank of Canada and U.S. Treasury sources. No detector or scheduler thresholds changed.

## Tradeoffs / current limitations

- The public `monitor-state` branch is test-only persistence and is not a production database strategy.
- Environment-backed request headers are a safe reference mechanism, not a hosted multi-user secret vault.
- GitHub scheduled workflows are not a real-time scheduler and can run later than requested.
- Pages is read-only; source edits, review actions and baseline promotion require the local FastAPI app/API or CLI.
- Authentication/workspace ownership is not implemented.
- Schema rename inference is not implemented.
- Historical reference windows are deterministic rolling medians, not statistical forecasting or machine learning.
- Longer real-source history is still required before threshold tuning or notification delivery.
