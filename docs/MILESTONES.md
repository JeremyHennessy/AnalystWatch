# Milestones

## Core v0.1 — current

Goal: prove that AnalystWatch can establish a known-good source baseline, detect meaningful silent changes, explain the evidence, and expose a simple health state.

Implemented in this milestone branch:

- CSV, XLSX, JSON and unauthenticated REST JSON ingestion
- deterministic profiling and source history
- availability, freshness, schema, row-count, null-rate, numeric, categorical and configured-key uniqueness detectors
- Healthy / Warning / Critical classification
- explicit baseline retention and baseline promotion
- CLI, JSON API and minimal health dashboard
- deliberately broken detector fixtures plus false-positive control tests
- GitHub Actions CI gate

## Candidate v0.2 — after v0.1 verification

- scheduled checks and run policies
- richer baseline windows / trend context
- better date-field inference and API freshness metadata
- source onboarding UI
- secure API headers/secrets
- notification delivery after signal quality is validated

## Later — not v0.1

- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
