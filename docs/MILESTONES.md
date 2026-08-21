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

- independent monitoring cadence via `monitor_interval_minutes`
- due/not-due schedule decisions and `check-due` / `check-all`
- repository source configuration sync
- recent Healthy-history reference windows for row, null, numeric and uniqueness signals
- explicit baseline retained alongside historical context
- opt-in conservative latest-date inference
- API `Last-Modified` and ETag evidence capture
- read-only static dashboard export
- GitHub Actions hourly monitoring workflow
- persistent test monitoring state on dedicated `monitor-state` branch
- GitHub Pages deployment workflow
- scheduling/signal/static-site regression tests

## Core v0.2.1 — Initial real-source validation — complete

Established that the v0.2 monitoring path works against real analyst-style public APIs:

- Bank of Canada USD/CAD daily Valet observations validated from GitHub Actions
- U.S. Treasury Debt to the Penny validated from GitHub Actions
- explicit `numeric_fields` contracts for APIs that publish numeric amounts as strings
- configured content-date freshness fields validated for both real APIs
- live-source smoke gate for availability and numeric/date contracts
- numeric-string `/100` scaling remains detectable as Critical numeric drift

No detector thresholds were tuned because the initial live observations did not provide evidence that tuning was necessary.

## Core v0.3 — Source onboarding & contract preflight — complete

Prevented invalid or misunderstood source contracts from entering monitoring silently:

- read-only source preflight before persistence
- availability, empty-data, numeric, unique-key and freshness contract validation
- local FastAPI onboarding plus `/api/preflight` and `/api/onboard`
- server-side preflight repeated before acceptance
- duplicate source IDs rejected instead of overwritten
- accepted definitions do not create an observation/baseline until normal monitoring runs
- Pages remains read-only while exposing monitoring-contract configuration
- isolated onboarding styling and regression coverage

The clean v0.3 GitHub gate reached 32 passing tests and the live-source smoke remained green.

## Core v0.4 — Operational review & secure source configuration — current

Goal: add operational controls and credential-safe configuration around the verified monitoring engine without weakening its evidence semantics.

Implemented and verified on the functional candidate:

- `request_header_env` maps API headers to runtime environment-variable names; secret values are never stored in source definitions
- missing required environment variables become explicit availability evidence
- safe source edits use the same preflight discipline as onboarding and preserve existing observations/baseline
- interactive/API source creation is preflight-protected; `sync-sources` remains the code-reviewed hosted configuration path
- Warning/Critical observations can be marked `Acknowledged` or `Reviewed` without changing health or claiming resolution
- review state persists separately from observation evidence
- baseline review only allows Healthy available candidates with profiles
- baseline promotion is guarded by the expected current baseline ID to prevent stale-review promotion
- Pages remains read-only and hides API query strings and request-header environment-variable names
- CLI supports environment-backed headers, baseline review, and guarded promotion
- live Bank of Canada/Treasury smoke remains green after the ingestion/service changes
- clean functional gate reached 41 passing tests before documentation/version closeout

No detector or scheduler thresholds were changed in this milestone.

## Candidate v0.5 — persistence & notification readiness

- accumulate more real-source history and quantify false positives/false negatives before changing thresholds
- replace branch-backed SQLite test persistence with deployment-appropriate storage
- define authentication/workspace ownership before exposing write actions remotely
- add a dedicated secret-management boundary for multi-user/hosted authenticated sources
- design incident notification rules around unreviewed Warning/Critical transitions
- notification delivery only after signal quality and persistence semantics are trustworthy

## Later

- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
