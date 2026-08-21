# Milestones

## Core v0.1 — complete

Established the deterministic monitoring foundation:

- CSV, XLSX, JSON and unauthenticated REST JSON ingestion
- profiling and retained source history
- availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness detectors
- Healthy / Warning / Critical classification
- explicit baseline retention/promotion
- CLI, JSON API and minimal dashboard
- deliberately broken fixtures and false-positive controls
- CI gate

## Core v0.2 — Scheduling & Signal Quality — complete

Made the core continuously checkable without weakening detector trust:

- independent monitoring cadence
- due/not-due scheduling
- repository source configuration sync
- recent Healthy-history references alongside explicit baselines
- conservative freshness inference
- API HTTP evidence
- read-only static dashboard export
- scheduled GitHub Actions monitoring and Pages deployment

## Core v0.2.1 — Initial real-source validation — complete

Validated Bank of Canada USD/CAD and U.S. Treasury Debt to the Penny from GitHub Actions and added explicit `numeric_fields` contracts for APIs that publish numeric amounts as strings. No detector thresholds were changed.

## Core v0.3 — Source onboarding & contract preflight — complete

Added non-persistent candidate preflight, contract validation, local onboarding, server-side preflight before acceptance, duplicate-ID protection, and read-only Pages contract visibility. The clean gate reached 32 passing tests.

## Core v0.4 — Operational review & secure source configuration — complete

Added:

- environment-backed request-header references without storing secret values
- preflight-protected source edits that preserve history/baselines
- Acknowledged / Reviewed analyst state separate from observation Health
- guarded Healthy-only baseline review and promotion
- redacted Pages operational views

The clean v0.4 functional gate reached 41 passing tests and live-source smoke remained green.

## Core v0.5 — Incident transitions & notification readiness — current

Goal: prove meaningful incident transitions and notification-candidate semantics before introducing any outbound side effects.

Implemented and verified on the functional candidate:

- incident lifecycle is derived deterministically from immutable observation history
- `Opened`: Healthy/no prior state → Warning/Critical
- `Escalated`: Warning → Critical inside an open incident
- `Recovered`: Warning/Critical → Healthy
- repeated Warning or repeated Critical observations do not create duplicate transition candidates
- recovered incidents remain reconstructable through later Healthy checks
- `IncidentSnapshot` exposes opening/recovery timing, current/peak Health, and incident observation count
- each meaningful transition can create one `Pending` notification candidate
- transition observation and candidate persist atomically in the same SQLite transaction
- review state remains independent and cannot resolve an incident
- API/CLI inspect incidents/candidates without write/delivery operations
- Pages exposes incident summary and candidate count while remaining read-only
- no email, Slack, webhook, SMS, retry worker, destination configuration, or delivery adapter exists
- live source smoke remains green after the storage/service changes
- clean functional gate reached **50 passing tests** before documentation/version closeout

No detector, scheduler, hosted source configuration, secret handling, review semantics, or baseline semantics were changed in v0.5.

## Candidate v0.6 — delivery policy sandbox & persistence readiness

Before any real delivery:

- accumulate real transition history and inspect candidate noise/coverage
- define per-source transition policy (which Opened/Escalated/Recovered events should be deliverable)
- add explicit candidate lifecycle such as Pending / Suppressed / Delivered / Failed without sending by default
- define idempotency and retry semantics independently of monitoring transactions
- replace branch-backed SQLite test persistence with deployment-appropriate storage
- define authentication/workspace ownership before remote write/delivery actions
- introduce one sandbox delivery adapter only after candidate semantics are proven

## Later

- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
