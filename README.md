# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.16 status

Core v0.16 adds managed-runtime readiness and the first live email delivery implementation while preserving the deterministic monitoring, authorization and delivery-attempt state machines verified through v0.15.

The release has two deliberately separate boundaries:

- **managed runtime readiness** — environment-backed PostgreSQL/auth/email configuration, PostgreSQL startup verification, persistent workspace membership initialization and trusted first-Admin bootstrap;
- **live email delivery** — Resend email requests behind the existing Eligible-candidate, idempotency, claim ownership, Prepared/retry/reconciliation contract.

Core v0.16 does not silently switch the existing GitHub Pages monitor to PostgreSQL and does not claim a successful real email side effect without provider credentials and an externally accepted message.

## Managed runtime configuration

`ManagedRuntimeConfig` reads deployment values from environment variables only:

```text
ANALYSTWATCH_POSTGRES_DSN=<managed PostgreSQL DSN>
ANALYSTWATCH_WORKSPACE_ID=<workspace>
ANALYSTWATCH_AUTH_SECRET=<signed-bearer secret>
ANALYSTWATCH_BOOTSTRAP_ADMIN_USER_ID=<trusted first Admin principal>
ANALYSTWATCH_RESEND_API_KEY=<Resend API key>
ANALYSTWATCH_EMAIL_FROM=<verified sender>
ANALYSTWATCH_EMAIL_TO=<comma-separated recipients>
ANALYSTWATCH_PUBLIC_BASE_URL=<public application base URL>
```

No DSN, API key, authorization header or auth secret belongs in repository configuration or Pages output.

`prepare_managed_runtime(...)` initializes and verifies the PostgreSQL monitoring schema, initializes PostgreSQL workspace memberships, creates the configured first Admin only when absent, rejects an existing non-Admin bootstrap principal, and returns non-secret readiness counts plus the storage identity.

### Managed PostgreSQL validation

A dedicated external managed PostgreSQL validation project was provisioned for v0.16 testing without changing the hosted application backend. The AnalystWatch schema-v1 metadata, persistent storage identity, workspace membership table and validation source were created and verified there.

Recovery was rehearsed on an isolated managed-database branch: validation state was cloned, deliberately removed on the child branch, then the child was reset from its parent and the original storage identity, source and Admin membership were verified again. The temporary recovery branches were deleted afterward.

This proves managed PostgreSQL provisioning/recovery mechanics for the validation environment. It is not a production cutover of the GitHub-hosted AnalystWatch demo.

## Authenticated workspace boundary

Core v0.15 authorization remains unchanged:

```text
authenticated principal
→ persisted workspace membership
→ workspace role
→ permitted capability
→ operation
```

The default hosted/local mode remains `local`. Signed-bearer mode remains opt-in. The managed-runtime bootstrap step is the trusted provisioning path for the first Admin; there is still no unauthenticated Admin bootstrap endpoint.

## Live email delivery

Core v0.16 introduces `DeliveryMode.LIVE` and a Resend adapter without replacing the existing dry-run path.

A live email can be attempted only for an existing **Eligible** notification candidate. The adapter uses the existing delivery-attempt claim contract and sends the AnalystWatch idempotency key to the provider.

Before external I/O, the claimed attempt is persisted as live. Outcomes are handled conservatively:

- provider acceptance → `Succeeded` with provider message ID summary;
- definitive provider rejection → `Failed`;
- transport uncertainty → remains `Prepared`, requiring explicit reconciliation before retry;
- replay of the same idempotency key returns the stored attempt and does not send a second request.

Alert content includes:

- source name;
- workspace;
- incident transition;
- severity;
- observation time;
- concise incident reason;
- important deterministic findings;
- likely impact when available;
- suggested investigation when available;
- source-detail link.

Secrets, DSNs, authorization headers and idempotency keys are not included in email bodies or stored result/error summaries.

The provider integration is verified deterministically through mocked HTTP transport. A successful real provider side effect is **not claimed** until a real Resend credential and verified sender are configured and the provider accepts a message.

## Verification

The v0.16 functional checkpoint passed:

- Ruff;
- compile/import gate;
- **164 deterministic tests** against PostgreSQL 16 CI;
- live-source smoke against the existing public-source set;
- managed PostgreSQL provisioning and isolated recovery rehearsal.

The existing hosted workflow remains legacy SQLite/local auth until a controlled deployment cutover is explicitly performed.

## Next milestone

Product v0.17 is the SharePoint / OneDrive Excel connector. It should normalize Microsoft 365 workbook/table/range data into the existing ingestion/profile/detector pipeline rather than duplicating monitoring logic.

Before a production SaaS launch, the managed runtime still needs an actual application deployment target, secret injection there, operational monitoring, and a verified real email send. Those deployment operations should remain explicit and evidence-backed rather than inferred from the v0.16 code or validation project.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
