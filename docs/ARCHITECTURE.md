# AnalystWatch Core v0.5 Architecture

## Decision

Core v0.5 remains a Python modular monolith. FastAPI is the interactive local/API surface; GitHub Pages is a generated read-only test surface. The deterministic monitoring engine remains authoritative. Review state and incident/notification metadata are downstream operational interpretations of immutable observation evidence; they do not rewrite Health or detector findings.

SQLite persists accepted source definitions, observations, review state, transition notification candidates, profiles, and the selected baseline. The temporary GitHub-hosted test environment retains this database on `monitor-state`; because the repository is public, that branch must contain only non-secret test state.

## Data flow

```text
Candidate/new or edited SourceDefinition
  -> ingest + profile preflight
  -> validate source contracts
  -> accept definition only when Ready

Accepted SourceDefinition
  -> schedule decision
  -> ingest (runtime environment-backed API headers when configured)
  -> profile
  -> deterministic detectors
  -> immutable Observation: Healthy / Warning / Critical
       |
       +-> observation review state (Acknowledged / Reviewed)
       +-> derive incident lifecycle from observation history
       +-> meaningful transition? Opened / Escalated / Recovered
              |
              +-> persist Pending NotificationCandidate atomically
                  with the transition Observation
       +-> guarded baseline review/promotion
  -> FastAPI/API read surfaces
  -> read-only static Pages export
```

There is no outbound notification delivery in v0.5.

## Components

- `models.py` — source, observation, review, incident and notification-candidate models.
- `config.py` — validated JSON source-definition loading.
- `preflight.py` — non-persistent candidate ingestion/profiling and contract validation.
- `scheduler.py` — monitoring cadence decisions.
- `ingest.py` — file/API acquisition and runtime environment-backed headers.
- `profile.py` — structural/completeness/cardinality/numeric/categorical profiles and explicit contracts.
- `detectors.py` — deterministic baseline/history comparisons and freshness checks.
- `incidents.py` — pure transition and latest-incident derivation from observation history.
- `storage.py` — SQLite definitions, observations, review state, notification candidates and baseline pointer.
- `service.py` — monitoring transactions plus onboarding/edit/review/incident/baseline operations.
- `web.py` — local FastAPI UI/API; incident and candidate endpoints are read-only.
- `pages.py` — static redacted incident summary and candidate-count export.
- `cli.py` — operational inspection commands; no notification delivery command exists.

## Incident lifecycle

Incident state is **derived**, not maintained as a mutable authoritative row. Given observations ordered newest-first, AnalystWatch identifies the latest contiguous unhealthy block and its immediately following Healthy recovery when present.

Transitions are intentionally small and deterministic:

- `Opened`: the current observation is Warning/Critical and the previous observation is absent or Healthy;
- `Escalated`: previous is Warning and current is Critical;
- `Recovered`: previous is Warning/Critical and current is Healthy;
- all other adjacent health pairs produce no transition.

This means repeated Warning or repeated Critical observations do not generate repeated event noise. Critical→Warning remains the same open incident and does not create a separate de-escalation candidate in v0.5.

A derived `IncidentSnapshot` records the opening observation/time, latest unhealthy observation, current status, current/peak Health, number of unhealthy observations, and recovery observation/time when recovered. A recovered incident remains reconstructable after later Healthy observations.

## Notification candidates

A `NotificationCandidate` represents a meaningful incident transition that a future delivery policy might send. Its state is `Pending` in v0.5.

Candidate creation is coupled to monitoring persistence:

1. `MonitorService.check_source` captures the prior observation before checking;
2. detector output determines the new observation Health;
3. the pure transition function compares prior/new Health;
4. if Opened/Escalated/Recovered, a deterministic candidate is created;
5. `Storage.save_observation` writes the observation and candidate inside the same SQLite transaction.

The candidate cannot be committed without its transition observation, and repeated unchanged incident observations do not produce candidates.

Candidate storage is separate from review state. Acknowledging or reviewing an unhealthy observation does not close the incident, remove a candidate, or change Health.

## Delivery boundary

Core v0.5 intentionally stops before delivery. There is no:

- email transport;
- Slack/Teams transport;
- webhook sender;
- SMS provider;
- retry/backoff worker;
- delivery acknowledgement state;
- destination configuration.

API/CLI only list candidates. Pages only shows incident summary and candidate count. This preserves a clean boundary for evaluating transition quality before introducing external side effects.

## Credential-safe source configuration

`request_header_env` continues to store header → environment-variable-name references only. Secret values are resolved immediately before a request and are not inserted into source definitions, SQLite definition JSON, Git history, or Pages state. Missing variables become availability evidence.

## Source creation/edit and preflight

Interactive/API source creation and edits perform a fresh server-side preflight. A failed edit leaves the prior source definition, observations and baseline unchanged. `sync-sources` remains the explicit code-reviewed hosted configuration path.

## Review and baseline semantics

Warning/Critical observations may be independently marked `Acknowledged` or `Reviewed`; these workflow states never modify technical Health or incident status.

Baseline promotion remains Healthy-only and guarded by the expected current baseline ID so stale reviews cannot overwrite a newer baseline.

## Scheduling and detector behavior

`monitor_interval_minutes` controls check cadence; `expected_refresh_minutes` controls freshness expectation. Detector behavior and thresholds are unchanged in v0.5.

The explicit baseline remains retained. Once sufficient recent Healthy observations exist, selected detectors can use the median of Healthy history as an operational comparison reference while preserving baseline evidence.

## GitHub Pages test deployment

Pages remains read-only. The Actions workflow restores branch-backed SQLite state, syncs repository source definitions, runs monitoring, renders static output, persists updated test state and deploys the generated artifact.

Public output includes incident summary and candidate counts but not candidate delivery actions. Existing redaction rules remain: API query strings are removed from display and request-header environment-variable names are not rendered into Pages output.

## Verification boundary

The v0.5 functional candidate passed Ruff, compile, **50 deterministic tests**, and the existing live-source smoke against the demo, Bank of Canada and U.S. Treasury sources. No detector, scheduler, hosted source configuration, secret handling, review semantics or baseline semantics were changed by the incident implementation.

## Tradeoffs / current limitations

- `monitor-state` is test-only branch-backed persistence, not a production database.
- Incident state is derived from recent history read into memory; production scale may require indexed/materialized incident state with equivalent semantics.
- Pending notification candidates have no delivery lifecycle yet.
- Authentication/workspace ownership is not implemented.
- Environment-backed headers are a reference mechanism, not a multi-user secret vault.
- GitHub scheduling is not real-time.
- Pages is read-only.
- Schema rename inference is not implemented.
- Historical detector context remains deterministic rolling medians rather than forecasting/ML.
- More real-source history is required before enabling delivery or tuning thresholds.
