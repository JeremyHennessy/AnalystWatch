# AnalystWatch Product v0.29 Architecture

## Decision

Product v0.29 implements the first real provider OAuth connection runtime on top of v0.28's encrypted credential foundation.

The architectural rule is: **a provider callback may persist a credential only after one-time state/PKCE consumption, fixed-endpoint code exchange, workspace/provider binding and provider account-identity verification. Stored credential use is separate from source Health and must never silently fall back to another account when a stored credential is present but unusable.**

```text
authenticated Operator start
        ↓
fixed provider config + deployment keyring
        ↓
random state + PKCE
        ↓
atomic authorization transaction store
        ↓
303 provider redirect
        ↓
public callback route
        ↓
atomic state consume + provider/workspace binding
        ↓
fixed token endpoint exchange
        ↓
provider account identity verification
        ↓
AES-256-GCM ProviderCredentialRecord
        ↓
SQLite/PostgreSQL credential store
        ↓
connection check / identity / lifecycle / resource browse
```

Source preflight/check ingestion remains on the existing `request_header_env` contract in v0.29. That cutover is a separate runtime milestone.

## Atomic authorization transaction persistence

The callback only possesses the returned OAuth `state`, so persisted authorization transactions are indexed by a unique SHA-256/base64url digest of that state. Raw state is never a persistence field.

`OAuthAuthorizationStore` exposes only:

```text
initialize
create
get
consume
```

The transition model is intentionally create → consume once. There is no general update method.

### Memory

`MemoryOAuthAuthorizationStore` protects transaction/state indexes with an in-process lock. Atomic consumption validates and writes the consumed record while holding that lock.

### SQLite

`SQLiteOAuthAuthorizationStore` stores transaction ID, state digest and serialized transaction JSON. Consumption begins `BEGIN IMMEDIATE`, looks up the state digest, validates/decrypts the PKCE verifier, then writes `consumed_at` before commit.

### PostgreSQL

`PostgresOAuthAuthorizationStore` stores transaction ID, unique state digest and transaction JSONB in the AnalystWatch schema. Consumption selects the state row `FOR UPDATE` before validating and writing the consumed record.

Concurrency coverage requires one winner and one deterministic replay failure for two simultaneous consumers of the same state in all three backends.

A failed state/expiry/provider/workspace/PKCE validation does not mark the transaction consumed. A valid provider denial intentionally does consume it.

## Fixed provider configuration

OAuth endpoints and scope sets are code-controlled per provider. Callers cannot choose arbitrary authorization/token endpoints, redirect URIs, scope sets or client-secret locations.

Deployment configuration supplies only the public application origin and provider client credentials:

```text
ANALYSTWATCH_PUBLIC_BASE_URL
ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID
ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET
ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID
ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET
```

The public base URL:

- must be trimmed/bounded;
- cannot contain user info, query, fragment or an application path;
- requires HTTPS except loopback local-development HTTP;
- is combined with fixed callback paths.

Microsoft uses fixed `organizations` OAuth 2.0 v2 endpoints. Google uses fixed OAuth 2.0 web-server endpoints. Scope sets are bounded to the identity/file access needed by the existing AnalystWatch connection experience.

## Authorization start

The two start routes are POST mutations and remain Operator-level under the existing authorization layer.

A start request loads provider configuration and the credential keyring lazily. Missing OAuth configuration therefore does not prevent AnalystWatch from booting or from operating existing environment-backed sources.

Start refuses to reuse an existing credential ID. This prevents an ordinary connect operation from becoming an implicit reconnect/account-switch operation.

Critically, the transaction is persisted before the redirect response is returned. If persistence fails, no provider redirect is issued.

## Callback authentication boundary

Provider callbacks are special HTTP-authentication endpoints:

```text
GET /api/oauth/microsoft/callback
GET /api/oauth/google/callback
```

The provider-controlled browser redirect cannot carry an AnalystWatch signed-bearer header. These exact GET paths bypass the normal bearer middleware.

That exemption is narrow: callback authorization is established through the stored one-time state transaction, which binds:

- workspace;
- initiating AnalystWatch user;
- provider;
- target credential ID;
- transaction ID;
- expiry;
- encrypted PKCE verifier.

The callback route's provider must match the provider in the consumed transaction and the transaction workspace must match the app runtime workspace.

Provider denial uses the same bound atomic consume path and then returns a generic failure page. This prevents a denied authorization transaction from later being replayed with a code.

Callback rendering never includes authorization code, state, provider error description, token material or account identity.

## Code exchange

The code-exchange helper posts only to the fixed token endpoint from `OAuthProviderRuntimeConfig` and does not follow arbitrary redirects.

Inputs are bounded before network use. Token responses are validated for bounded access token, optional refresh token, token type, expiry and returned scopes.

Raw provider response bodies are not surfaced through `OAuthTokenExchangeError`.

The PKCE verifier exists in plaintext only for the in-memory exchange request after authenticated transaction consumption.

## Account verification before write

A successful token response is not sufficient for credential persistence.

The returned access token is first used in memory to resolve provider account identity through the existing bounded Microsoft `/me` or Google Drive `about.user` evidence path.

Only after stable provider subject identity is established does AnalystWatch call `seal_provider_credential(...)`, which binds ciphertext to:

```text
workspace
provider
credential_id
subject_id
secret_kind
```

The resulting encrypted record is then stored using the v0.28 credential store.

This means an OAuth code cannot create an AnalystWatch credential record whose provider account identity was never verified.

## Credential store initialization

Dynamic app setup now creates both dedicated security stores:

```text
OAuthAuthorizationStore
CredentialStore
```

For SQLite they use separate sidecar databases derived from the runtime monitoring database path.

For PostgreSQL they share the managed AnalystWatch DSN but use dedicated tables in the AnalystWatch schema.

Neither store is part of source observation history.

## Stored OAuth credential preference for connection operations

The existing connection endpoints remain stable. v0.29 adds an internal access-token path that uses the same bounded provider request/response models without copying token plaintext into environment variables.

Default OAuth credential identities are:

```text
Microsoft → microsoft-primary
Google    → google-primary
```

For check, account identity, lifecycle and resource browsing:

1. look up the default credential in the bound workspace;
2. if no record exists, retain the legacy fixed environment-backed path;
3. if a record exists, validate provider/revocation/expiry;
4. load the deployment keyring;
5. decrypt the access token in memory;
6. use the access token for the existing bounded provider operation.

If an existing stored record is unusable, the operation fails closed. It does not fall back to an environment token because that could silently operate as a different provider account.

The connection API response models never expose the internal `stored_oauth` marker or the access token.

## Lifecycle semantics retained

Credential lifecycle remains deterministic operational evidence:

```text
needs_credential
rejected
unavailable
identity_unverified
verified
```

The derivation is now shared between environment-backed and in-memory OAuth access-token paths. Reachability and identity remain separate evidence so identity-scope failure does not falsely redefine connector reachability.

Lifecycle state remains independent from source Healthy / Warning / Critical.

## Source ingestion boundary

v0.29 intentionally does not change `MonitoringConfig.request_header_env` or `ingest_source(...)` credential resolution.

The existing lower-level Microsoft/Google readers already accept concrete headers, so the next cutover can be implemented without a new connector. However, silently choosing a default stored credential inside ingestion would create ambiguous account ownership.

The next milestone should therefore add an **explicit optional stored credential ID** to the source contract and resolve it through the workspace-bound encrypted store. Existing environment-header sources must continue to work unchanged.

Preflight and scheduled checks must share the same resolver so a source cannot pass onboarding with one credential path and later monitor through another.

## Refresh/reconnect/revoke boundary

v0.29 stores refresh tokens when supplied but does not use them for network refresh.

Until refresh exists:

- expired stored access tokens fail closed;
- existing environment credentials are not used as a hidden substitute;
- ordinary start cannot overwrite an existing credential ID;
- account switching is not implicit.

A future refresh operation must lock/read the existing credential, refresh against the fixed provider endpoint, re-verify identity when appropriate and atomically replace encrypted token/expiry metadata without changing `created_at` or provider subject.

Reconnect/account-switch/revoke must remain explicit actions.

## Monitoring and static-output boundary

Provider OAuth state is operational security state. It cannot emit or change source Health.

v0.29 does not alter:

- detector/Data Rule semantics;
- baselines/reviews;
- incidents;
- reliability scorecards;
- notifications/delivery/reconciliation;
- dependency/blast-radius logic;
- monitoring observation persistence.

Static GitHub Pages receives no OAuth state, transaction, credential record, ciphertext, key ID, account identity or dynamic callback controls.

## Verification

Verified feature checkpoints:

- `5a61a8a850c852b7f8151b92da5d05d888432aec` / CI #747 — **393 passed / 1 warning**;
- `37aa50634e064a8540b5dd85bae64eaafdb0789c` / CI #753 — **408 passed / 1 warning**;
- `0f39cc0b39d5a4c49ab663e523527aea02d6994f` / CI #799 — **433 passed / 1 warning**;
- `0932ea92fa5b5e763eb23e8d5b1f75cf48d8e07d` / CI #803 — **439 passed / 1 warning**;
- frozen feature checkpoint `6dcbe1b56a4d4375f56056d941226b959716aec6` / CI #805 — **445 passed / 1 warning**.

All checkpoints passed Ruff, compile/import and the PostgreSQL 16-backed suite.

No real Microsoft/Google OAuth client/tenant authorization was supplied, so external token/account side effects are not claimed.

## Release boundary

Product v0.29 is ready for release closeout when package/FastAPI/module versions are aligned to `0.29.0`, release documentation is aligned to this architecture and the exact release head passes the full repository gate.

A visible Add Source Connect control, source ingestion credential binding, refresh, reconnect/account-switch and provider revoke remain explicit follow-on work rather than unverified v0.29 claims.
