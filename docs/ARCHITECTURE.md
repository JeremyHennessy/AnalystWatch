# AnalystWatch Core v0.6 Architecture

## Decision

Core v0.6 remains a Python modular monolith. FastAPI is the interactive local/API surface; GitHub Pages is a generated read-only test surface. The deterministic monitoring engine remains authoritative. Review state, incident state, and delivery-policy decisions are downstream interpretations of immutable observation evidence and do not rewrite detector Health/findings.

SQLite persists accepted source definitions, observations, review state, notification candidates, profiles, and the selected baseline. The temporary GitHub-hosted environment retains this database on the public `monitor-state` branch, which must contain only non-secret test state.

## Data flow

```text
SourceDefinition
  -> preflight for interactive create/edit
  -> schedule
  -> ingest
  -> profile
  -> deterministic detectors
  -> immutable Observation: Healthy / Warning / Critical
       |
       +-> review state: Acknowledged / Reviewed
       +-> derive Incident: Opened / Escalated / Recovered
              |
              +-> NotificationCandidate
                    |
                    +-> evaluate source notification_transitions policy
                           -> Eligible OR Suppressed
                           -> snapshot policy + time + reason
       +-> guarded baseline review/promotion
  -> FastAPI/API read surfaces
  -> read-only Pages export
```

There is no outbound delivery in v0.6.

## Incident transitions

Incident state is derived from observation history rather than maintained as an independent mutable truth.

Transitions:

- `Opened`: current is Warning/Critical and previous is absent or Healthy
- `Escalated`: previous Warning → current Critical
- `Recovered`: previous Warning/Critical → current Healthy
- all other adjacent pairs create no transition

Repeated unchanged-severity incident observations therefore create no candidate noise. The transition observation and its candidate are persisted in one SQLite transaction.

## Delivery policy sandbox

`MonitoringConfig.notification_transitions` is an opt-in list of `Opened`, `Escalated`, and/or `Recovered`.

Safe default:

```json
{
  "notification_transitions": []
}
```

A new transition candidate is immediately policy-evaluated:

- transition in enabled list → `Eligible`
- transition not enabled / empty list → `Suppressed`

The candidate stores:

- the transition
- previous/current Health
- state
- evaluation timestamp
- snapshot of enabled transitions
- human-readable policy reason

This makes the decision auditable and non-retroactive. Editing the source policy later does not rewrite existing candidates.

## Legacy Pending candidates

v0.5 candidates may exist with state `Pending`. They are not silently migrated at application startup. `evaluate_pending_notification_candidates` is an explicit operation that evaluates only Pending candidates against the current policy and persists the result.

Already Eligible/Suppressed candidates are skipped, making repeat evaluation idempotent.

This legacy evaluation is intentionally separate from the monitoring transaction because historical policy did not exist when those candidates were created.

## Delivery boundary

Core v0.6 deliberately stops at policy eligibility. It has no:

- email/Slack/Teams/webhook/SMS provider
- send endpoint or UI control
- destination configuration
- delivery attempt table
- retry/backoff worker
- Delivered/Failed lifecycle

`Eligible` means only “this transition matched the source policy.” It does not mean a message was or can be sent.

## Source contracts and secrets

Interactive/API source creation and editing remain preflight-protected. `sync-sources` remains the code-reviewed hosted configuration path.

`request_header_env` stores header → environment-variable-name references only; secret values are resolved at request time and never stored in source definitions, SQLite definition JSON, Git history, or Pages output.

## Review and baseline semantics

Acknowledged/Reviewed is analyst workflow state only and does not resolve an incident or alter Health.

Baseline promotion remains Healthy-only and guarded by the expected current baseline ID to prevent stale review from overwriting a newer approved baseline.

## Scheduling and detector behavior

`monitor_interval_minutes` controls check cadence; `expected_refresh_minutes` controls upstream freshness expectation. Detector algorithms and thresholds are unchanged in v0.6.

## Pages and public state

Pages remains read-only. It can display:

- notification policy enabled transitions
- incident summary
- candidate totals
- Pending / Eligible / Suppressed counts

It exposes no delivery control. Existing redaction rules remain: displayed API locations omit query strings and Pages does not render request-header environment-variable names.

## Verification boundary

The verified v0.6 functional head passed Ruff, compile, **58 deterministic tests**, and live-source smoke against the demo, Bank of Canada and U.S. Treasury sources.

CI caught one UI regression during development: the v0.5 metric label **“Notification candidates”** had been shortened. The change was reverted and the exact approved label restored before the functional head was accepted.

No detector, scheduler, hosted source configuration, secret handling, review semantics, baseline semantics, Pages workflow, or shared CSS changed in v0.6.

## Tradeoffs / current limitations

- policy eligibility is not delivery
- legacy Pending migration is explicit/manual
- there is no production delivery attempt/retry/idempotency model yet
- `monitor-state` is test-only branch-backed persistence
- authentication/workspace ownership is not implemented
- environment-backed headers are not a multi-user secret vault
- GitHub scheduling is not real-time
- Pages is read-only
- incident derivation currently reads recent history into memory
- more real transition history is required before any real provider integration
