# Milestones

## Core v0.1 — complete

Deterministic monitoring foundation: ingestion, profiling, Health classification, baseline retention, CLI/API/dashboard, deliberately broken fixtures and CI.

## Core v0.2 — Scheduling & Signal Quality — complete

Added independent monitoring cadence, due-source scheduling, repository source sync, Healthy-history references, freshness evidence, Pages export and scheduled GitHub Actions monitoring.

## Core v0.2.1 — Initial real-source validation — complete

Validated Bank of Canada USD/CAD and U.S. Treasury Debt to the Penny through GitHub Actions and added explicit numeric-string contracts. No detector thresholds changed.

## Core v0.3 — Source onboarding & contract preflight — complete

Added non-persistent source preflight, contract validation, safe onboarding/API creation and duplicate-ID protection. Clean gate: 32 tests.

## Core v0.4 — Operational review & secure source configuration — complete

Added environment-backed request headers, preflight-protected edits, Acknowledged/Reviewed state, guarded Healthy baseline promotion, and public-output redaction. Clean gate: 41 tests.

## Core v0.5 — Incident transitions & notification readiness — complete

Added derived Opened/Escalated/Recovered incidents and transition candidates with duplicate-noise suppression. Clean gate: 50 tests. No outbound delivery.

## Core v0.6 — Delivery policy sandbox — complete

Added opt-in notification-transition policy, safe-default suppression, Eligible/Suppressed decisions, and immutable policy snapshots. Clean gate: 58 tests. No outbound delivery.

## Core v0.7 — Dry-run delivery attempts — complete

Added explicit Prepared/Succeeded/Failed dry-run attempts, caller idempotency, sequential retry semantics, SQLite uniqueness constraints, and read-only attempt summaries. Clean gate: 66 tests. No real provider.

## Core v0.8 — Attempt reconciliation & claim safety — current

Goal: harden the dry-run execution model before introducing any real delivery side effect.

Implemented and verified on the functional checkpoint:

- atomic attempt claim under SQLite `BEGIN IMMEDIATE`
- candidate eligibility, idempotency replay, latest-state validation, retry timing, attempt-number allocation and Prepared insert share one transaction
- concurrent same-key claims resolve to one claim plus one replay
- concurrent different-key claims allow only one Prepared attempt
- `delivery_retry_minutes` is separate from monitoring cadence
- retry-delay default is `0` to preserve v0.7 immediate-retry behavior
- optional nonzero retry delays are enforced by both status reporting and the claim transaction
- `DeliveryRetryDecision` exposes due state and next retry time
- abandoned Prepared attempts require explicit reconciliation
- reconciliation supports only Succeeded or Failed and requires a review note
- reconciliation records timestamp + note
- Failed reconciliation follows retry-delay rules
- Succeeded reconciliation blocks future attempts
- Pages exposes retry policy and aggregate counts only; notes/keys/actions are redacted
- approved prior UI labels/copy remain preserved
- clean functional checkpoint reached **75 passing tests**
- live-source smoke remained green

No detector, scheduler, hosted source configuration, notification-transition semantics, secret handling, review semantics, baseline semantics, Pages workflow, or shared CSS changed.

## Candidate v0.9 — deployment persistence & execution ownership

Before any provider integration:

- replace branch-backed test SQLite persistence with deployment-appropriate storage
- define authentication/workspace ownership for remote operational actions
- define execution ownership/lease semantics for multiple worker processes or nodes
- define retention/audit rules for notification candidates and delivery attempts
- accumulate real transition history and inspect candidate/policy noise
- prove migration/back-up/restore behavior independently from provider delivery

## Later

- first opt-in provider integration behind the proven delivery-attempt abstraction
- production notification delivery
- SourceGuard productization
- ModelGuard
- DashboardGuard
- team workspaces, authentication, billing and integrations
