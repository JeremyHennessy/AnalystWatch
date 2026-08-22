# AnalystWatch

**Reliability monitoring for analyst-owned data sources.**

AnalystWatch detects silent changes in CSV, Excel, JSON and REST API inputs: stale data, schema changes, row loss, null explosions, scaling shifts, category changes and key duplication. The product question is simple: **can I trust the data feeding my analysis today?**

## Core v0.15 status

Core v0.15 adds the first authenticated workspace authorization boundary required for a multi-user AnalystWatch service while preserving the verified monitoring engine and persistence behavior from earlier milestones.

Two web authentication modes now exist:

- `local` — safe default; preserves existing local development and hosted GitHub Pages/monitoring behavior and does **not** claim remote user authentication;
- `signed-bearer` — opt-in authenticated remote mode using a provider-neutral signed principal token plus persistent workspace membership authorization.

Core v0.15 does **not** add OAuth, SSO, an enterprise identity provider, managed deployment, billing or real notification delivery.

## Authorization model

Remote authority is derived in one direction only:

```text
authenticated principal
→ persisted workspace membership
→ workspace role
→ permitted capability
→ operation
```

A bearer token authenticates the principal identity and optional expiry only. It does not contain trusted workspace authority. A workspace ID supplied in a URL, query, payload or source definition cannot grant access.

Initial roles are intentionally small:

- **Viewer** — read sources, observations, incidents and reliability state;
- **Operator** — Viewer access plus operational actions such as checks, observation review, candidate evaluation and existing dry-run delivery operations;
- **Admin** — Operator access plus source configuration, baseline promotion and workspace membership administration.

Unclassified remote mutations fail closed as Admin-only.

## Signed bearer mode

Signed-bearer mode is explicitly enabled rather than inferred:

```text
ANALYSTWATCH_AUTH_MODE=signed-bearer
ANALYSTWATCH_AUTH_SECRET=<secret at least 32 bytes>
```

`create_app(...)` also accepts `auth_mode=` and `auth_secret=` for controlled embedding/tests.

The current `SignedSessionAuthenticator` is provider-neutral and uses HMAC-SHA256 to verify bearer tokens. It is an authentication seam, not a production identity provider. OAuth/OIDC/SSO integration remains separate work.

`/healthz` and static assets remain outside the authenticated application boundary; other application/API routes require authentication and membership when signed-bearer mode is enabled.

## Membership persistence

Membership persistence is deliberately separate from `MonitoringStore`; adding RBAC does not alter source/observation/incident/delivery persistence semantics.

Available membership stores:

- `SQLiteMembershipStore` — separate sidecar SQLite state for local/testing use;
- `PostgresMembershipStore` — persists `(workspace_id, user_id, role)` in the existing PostgreSQL `analystwatch` schema.

The same user can hold different roles in different workspaces.

### Initial Admin provisioning

Signed-bearer mode does **not** provide an unauthenticated first-Admin bootstrap endpoint. An initial membership must be provisioned through a trusted deployment/provisioning step before remote membership administration can be used. Formal deployment/bootstrap tooling belongs to the managed-deployment milestone.

## Security behavior proven by tests

Core v0.15 negative tests explicitly prove:

- missing authentication is rejected;
- a valid principal without membership is rejected;
- a member of workspace A cannot read workspace B;
- a member of workspace A cannot mutate workspace B;
- cross-workspace checks, candidate operations and delivery operations are denied before resource lookup;
- Viewer cannot perform Operator/Admin mutations;
- Operator cannot perform Admin-only mutations;
- an arbitrary payload `workspace_id` cannot override the app's authenticated/bound workspace;
- Admin can manage workspace memberships and source configuration;
- local mode preserves the existing unauthenticated local workflow.

The verified v0.15 functional checkpoint passed Ruff, compile and **156 tests** against the real PostgreSQL 16 CI service.

## Persistence and hosted boundary

Core v0.14's PostgreSQL persistence implementation remains available as an explicit backend, but PostgreSQL is still **not production-deployed** by this milestone.

The existing hosted monitor/Pages workflow remains on:

- `legacy` SQLite monitoring persistence;
- `local` auth mode;
- no production PostgreSQL DSN;
- no real outbound notification provider.

Core v0.15 therefore proves an authorization boundary without silently converting the existing GitHub-hosted demo into an authenticated SaaS deployment.

## Next milestone

Core v0.16 is managed deployment plus the first real email delivery. Infrastructure proof and external side-effect delivery should remain separable where practical. Required work includes managed PostgreSQL configuration, secret injection, explicit migrations/startup checks, backup/retention/PITR/restore rehearsal, runtime health/observability, trusted initial Admin provisioning, and the first email provider behind the already-proven delivery attempt abstraction.

Real notification delivery remains disabled until that milestone is independently verified.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
