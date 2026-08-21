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

## Core v0.2 — Scheduling & Signal Quality

Goal: make the core useful as a continuously checked test product without weakening detector trust.

Implemented:

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
- v0.2 scheduling/signal/static-site regression tests

## Candidate v0.3 — real-source hardening

- test with several real public/government/vendor-style sources over time
- tune thresholds from observed false positives/false negatives
- source onboarding/configuration UI
- secure API headers/secrets
- incident acknowledgement and baseline-review workflow
- notification delivery only after signal quality proves trustworthy
- replace test-state persistence with deployment-appropriate storage before production SaaS work

## Later

- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
