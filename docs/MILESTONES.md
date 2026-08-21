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

Initial live smoke on August 21, 2026:

- Bank of Canada: Healthy, 30 rows, latest date 2026-08-20, no contract failures
- U.S. Treasury: Healthy, 30 rows, latest date 2026-08-19, no contract failures

No detector thresholds were tuned because the first live observations did not provide evidence that tuning was necessary.

## Core v0.3 — Source onboarding & contract preflight — current

Goal: prevent invalid or misunderstood source contracts from entering monitoring silently.

Implemented:

- read-only source preflight before persistence
- validation for availability and empty datasets
- numeric-field presence and parseability contracts
- declared unique-key presence/null/duplicate validation
- freshness-field presence/date-parseability validation
- configured refresh expectations require usable freshness evidence
- stale-but-valid sources can warn without automatically invalidating the contract
- local FastAPI onboarding page plus `/api/preflight` and `/api/onboard`
- onboarding re-runs preflight before accepting a source
- duplicate source IDs are rejected rather than overwriting existing definitions
- successful onboarding saves only the source definition; the first monitoring check establishes its baseline
- GitHub Pages remains read-only while source details expose monitoring-contract configuration
- onboarding-specific CSS isolated from the established dashboard stylesheet
- focused onboarding regression coverage

The clean GitHub functional gate reached 32 passing tests before the documentation/version closeout, and the live-source smoke remained green.

## Candidate v0.4 — Operational review & secure source configuration

- accumulate real-source history and evaluate false positives/false negatives before changing detector thresholds
- editing existing source contracts through the same preflight discipline
- incident acknowledgement / review state
- baseline-review and approval workflow
- secure API headers/secrets and credential-safe source definitions
- notification delivery only after signal quality proves trustworthy
- replace branch-backed test-state persistence with deployment-appropriate storage before production SaaS work

## Later

- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
