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

## Core v0.2.1 — Initial real-source validation — current

Goal: establish that the v0.2 monitoring path works against real analyst-style public APIs before adding onboarding or notifications.

Verified:

- Bank of Canada USD/CAD daily Valet observations can be ingested and profiled from GitHub Actions
- U.S. Treasury Debt to the Penny can be ingested and profiled from GitHub Actions
- explicit `numeric_fields` source contracts handle APIs that publish numeric amounts as strings without auto-coercing identifiers
- configured content-date freshness fields parse successfully for both real APIs
- live-source smoke gate fails on unavailable/Critical sources and broken numeric/date contracts
- numeric-string `/100` scaling remains detectable as Critical numeric drift in deterministic regression coverage

Initial live smoke on August 21, 2026:

- Bank of Canada: Healthy, 30 rows, latest date 2026-08-20, no contract failures
- U.S. Treasury: Healthy, 30 rows, latest date 2026-08-19, no contract failures

No detector thresholds were tuned during this milestone because the first live observations did not provide evidence that tuning was necessary.

## Candidate v0.3 — source onboarding & operational hardening

- accumulate real-source history and evaluate false positives/false negatives before changing thresholds
- source onboarding/configuration UI
- source-contract validation and preview before activation
- secure API headers/secrets
- incident acknowledgement and baseline-review workflow
- notification delivery only after signal quality proves trustworthy
- replace branch-backed test-state persistence with deployment-appropriate storage before production SaaS work

## Later

- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
