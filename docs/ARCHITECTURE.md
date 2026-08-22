# AnalystWatch Core v0.15 Architecture

## Decision

Core v0.15 establishes authenticated workspace authorization as an independent security boundary. It does not change detector behavior, monitoring persistence semantics, incident derivation, notification policy or delivery-attempt state-machine behavior.

The milestone deliberately separates three concerns:

1. authentication establishes a principal;
2. membership storage establishes workspace authority;
3. authorization policy decides whether that role may perform the requested operation.

A remote caller never gains authority merely by supplying a `workspace_id`.

## Authentication modes

FastAPI supports two explicit modes:

```text
local | signed-bearer
```

`local` remains the default. It preserves the existing local CLI/dashboard and hosted GitHub monitor/Pages behavior and must not be described as authenticated multi-user operation.

`signed-bearer` activates the v0.15 remote authorization boundary.

## Provider-neutral authenticated principal

`auth.py` defines:

- `AuthenticatedPrincipal`;
- `AuthenticationContext`;
- `WorkspaceMembership`;
- `WorkspaceRole`;
- the structural `Authenticator` contract;
- `SignedSessionAuthenticator` as the first concrete authentication seam.

The signed session token contains a principal subject and optional expiry. It does not contain trusted workspace membership or role claims.

`SignedSessionAuthenticator` uses HMAC-SHA256 and requires a secret of at least 32 bytes. This provides a deterministic authentication mechanism for the boundary proof; it is not an OAuth/OIDC/SSO provider and is not presented as a complete production login system.

## Workspace membership persistence

Authorization persistence is intentionally **not** added to `MonitoringStore`.

`MonitoringStore` remains the persistence contract for monitored sources, observations, reviews, candidates and delivery attempts. Core v0.15 introduces a separate `MembershipStore` contract so RBAC changes cannot silently alter monitoring persistence semantics.

Implementations:

### SQLiteMembershipStore

A separate SQLite sidecar database contains:

```text
(workspace_id, user_id) -> role
```

This is useful for local development and deterministic tests without modifying legacy or namespaced monitoring SQLite schemas.

### PostgresMembershipStore

The PostgreSQL implementation persists memberships in:

```text
analystwatch.workspace_memberships
```

with primary key `(workspace_id, user_id)`. A principal can therefore hold distinct roles across different workspaces.

## Role model

Core v0.15 intentionally keeps RBAC small.

### Viewer

Read-only access to workspace reliability information.

### Operator

Viewer capabilities plus explicitly enumerated operational mutations, including checks, observation review, candidate evaluation and existing dry-run/reconciliation operations.

### Admin

Operator capabilities plus administrative mutations such as source configuration, baseline promotion and membership administration.

The role order is explicit:

```text
Viewer < Operator < Admin
```

## Fail-closed request authorization

`web_auth.py` is the centralized FastAPI security seam.

In signed-bearer mode, each protected request follows:

1. verify the bearer token;
2. obtain `AuthenticatedPrincipal`;
3. look up that user in the app-bound workspace membership store;
4. reject if membership is absent;
5. classify the request's required role;
6. reject if the role is insufficient;
7. place an `AuthenticationContext` on `request.state`;
8. only then execute the existing endpoint/domain behavior.

Read methods require Viewer. Known operational mutations require Operator. Membership administration and known administrative mutations require Admin. Any mutation not explicitly classified fails closed as Admin-only.

Only `/healthz` and static asset paths are intentionally outside this authenticated application boundary.

## Workspace binding rule

The app remains constructed for a validated workspace. Signed-bearer authorization always looks up membership for that **bound workspace**.

A request body such as:

```json
{"workspace_id": "another-workspace"}
```

cannot change the authorization target. Existing source-workspace validation also rejects source definitions whose workspace does not match the bound application workspace.

This yields the required authority chain:

```text
authenticated principal
→ membership in bound workspace
→ role
→ capability
→ operation
```

rather than:

```text
caller-supplied workspace_id
→ operation
```

## Membership administration

Signed-bearer mode adds Admin-protected membership routes:

```text
GET /api/workspace/memberships
PUT /api/workspace/memberships/{user_id}
```

The PUT operation writes a Viewer, Operator or Admin membership for the currently bound workspace only.

### First-Admin bootstrap boundary

There is deliberately no unauthenticated bootstrap endpoint. A fresh signed-bearer deployment therefore requires the first Admin membership to be provisioned by a trusted deployment/provisioning step.

Core v0.15 does not invent a bypass merely to make bootstrap convenient. Formal deployment bootstrap and secret-management tooling belongs with Core v0.16 managed deployment.

## Local and hosted compatibility

`local` auth mode remains default. No existing CLI command is made to pretend it has authenticated remote identity.

The GitHub-hosted monitoring/Pages workflow does not set `ANALYSTWATCH_AUTH_MODE=signed-bearer`; it therefore continues to operate through the existing local boundary. Likewise, hosted monitoring persistence remains default legacy SQLite until a separately verified managed deployment cutover.

## Security regression coverage

The v0.15 suite proves both positive and negative behavior:

- signed token verification and tamper rejection;
- token expiry enforcement when expiry is present;
- SQLite membership persistence and workspace isolation;
- PostgreSQL membership persistence and workspace isolation;
- missing remote authentication returns 401;
- authenticated non-members return 403;
- Viewer cannot mutate state;
- Operator can reach operational actions but cannot perform Admin-only actions;
- Admin can manage membership and source configuration;
- a workspace-A member cannot read or operate workspace B;
- cross-workspace denial occurs before source/candidate/attempt resource lookup;
- payload workspace spoofing does not override the bound workspace;
- local mode preserves existing unauthenticated local reads.

The verified functional checkpoint passed Ruff, compile and **156 deterministic tests** using the real PostgreSQL 16 CI service.

## Explicit limitations

Core v0.15 proves an authorization architecture, not a complete identity/deployment product.

Not implemented here:

- OAuth/OIDC login flow;
- SSO or enterprise identity providers;
- password/account lifecycle;
- automatic first-Admin bootstrap;
- managed PostgreSQL provisioning/cutover;
- production secret manager integration;
- billing;
- real email/Teams notification delivery.

## Next architecture step

Core v0.16 should prove managed runtime deployment and the first real email adapter without bypassing either the v0.14 persistence contract or v0.15 authorization boundary. Deployment work should include trusted initial Admin provisioning, secrets, schema migration/startup validation, backups/PITR/restore rehearsal, connection/runtime health and observability. Email must extend the existing delivery-attempt abstraction and preserve Eligible-candidate, idempotency, claim, Prepared, success/failure, retry and reconciliation semantics.
