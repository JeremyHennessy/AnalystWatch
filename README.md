# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.29 status

Product v0.29 turns the encrypted credential foundation from v0.28 into the first real Microsoft/Google OAuth connection runtime.

The release now provides:

- persistent, atomic OAuth authorization transactions in Memory, SQLite and PostgreSQL;
- fixed Microsoft/Google OAuth endpoints, redirect paths and bounded scope sets;
- authenticated authorization start with state + PKCE persisted before redirect;
- bounded authorization-code exchange against the fixed provider token endpoint;
- provider account-identity verification before any credential is accepted;
- encrypted access/refresh-token persistence behind `CredentialStore`;
- public callback routes authenticated by one-time state/PKCE rather than the AnalystWatch bearer header;
- replay, expiry, route-provider and workspace binding at callback consumption;
- existing Microsoft/Google connection check, identity, lifecycle and resource-browse endpoints that prefer the encrypted OAuth credential when present;
- legacy environment-backed connection credentials retained only as fallback when no stored OAuth credential exists.

v0.29 deliberately does **not** redefine source Health and does not yet switch source preflight/check ingestion from `request_header_env` to stored credential IDs.

## OAuth authorization transaction store

Provider redirects return `state`, not AnalystWatch's internal transaction ID. v0.29 therefore persists authorization transactions with a unique SHA-256 state digest index while never storing the raw state value.

The store contract is intentionally narrow:

```text
initialize
create
get
consume
```

There is no generic transaction update operation. A transaction is created once and may only transition to consumed through the atomic consume path.

Implementations:

- Memory: in-process lock plus transaction/state-digest indexes;
- SQLite: `BEGIN IMMEDIATE` around state lookup, validation and consumed write;
- PostgreSQL: state row selected `FOR UPDATE` before validation and consumed write.

Concurrency tests require exactly one successful consumer for the same valid callback state. The competing consumer must receive an `already consumed` failure.

Raw SQLite/PostgreSQL tests verify that neither the callback state nor the recovered PKCE verifier plaintext is persisted.

## Provider OAuth configuration

Provider protocol configuration is deployment-controlled rather than caller-controlled.

Runtime configuration uses:

```text
ANALYSTWATCH_PUBLIC_BASE_URL
ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_ID
ANALYSTWATCH_MICROSOFT_OAUTH_CLIENT_SECRET
ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_ID
ANALYSTWATCH_GOOGLE_OAUTH_CLIENT_SECRET
```

The credential encryption keyring remains:

```text
ANALYSTWATCH_CREDENTIAL_KEYS_JSON
ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID
```

Microsoft uses the fixed `organizations` v2 authorization/token endpoints and a bounded delegated scope set for identity and file access. Google uses fixed authorization/token endpoints and bounded identity, Drive-metadata-readonly and Sheets-readonly scopes.

Redirect URIs are derived only from the validated public base URL and the fixed provider callback paths. Production URLs require HTTPS; loopback HTTP is allowed only for local development. Callers cannot override provider endpoints, redirect paths, scopes or secret environment-variable names.

## Authorization start and callback

Start routes:

```text
POST /api/oauth/microsoft/start
POST /api/oauth/google/start
```

They remain Operator-level mutations under the existing workspace authorization model.

A start request:

1. validates the target credential ID;
2. refuses to overwrite an existing credential ID;
3. loads fixed provider configuration and the deployment keyring lazily;
4. creates state + PKCE material;
5. persists the encrypted authorization transaction;
6. only after persistence succeeds, issues a `303` redirect to the fixed provider authorization endpoint.

Callback routes:

```text
GET /api/oauth/microsoft/callback
GET /api/oauth/google/callback
```

A browser returning from Microsoft/Google cannot carry the AnalystWatch signed-bearer header. Those two GET routes are therefore exempt from normal request authentication and are instead authenticated by the persisted one-time state/PKCE transaction, including workspace and provider binding.

Callbacks reject missing/malformed state, code/error ambiguity, expiry, replay and route-provider mismatch. Provider denial consumes the state so the same transaction cannot later be replayed as a successful callback.

Callback HTML is intentionally generic and does not render the authorization code, state value, provider error description, token material or provider account identifiers.

## Token exchange and account binding

The callback exchange path:

1. atomically consumes state and recovers the PKCE verifier;
2. posts the authorization code only to the fixed provider token endpoint;
3. validates bounded token response fields;
4. uses the returned access token in memory to resolve provider account identity;
5. seals access/refresh tokens with AES-256-GCM associated-data binding;
6. writes the encrypted `ProviderCredentialRecord` only after identity verification succeeds.

Provider response bodies, access tokens, refresh tokens, authorization codes and client secrets are excluded from bounded public errors.

Ordinary credential replacement still cannot silently switch provider/account identity. Reconnect/account-switch remains an explicit future workflow.

## Existing connection browser now prefers stored OAuth credentials

The existing v0.26/v0.27 connection endpoints are unchanged from the browser's perspective:

- Test connection;
- Credential status;
- Verify connected account;
- Microsoft drive/workbook/table browsing;
- Google spreadsheet/sheet browsing.

For the default OAuth credential IDs:

```text
microsoft-primary
google-primary
```

those endpoints now prefer the workspace-scoped encrypted credential when it exists. Access-token plaintext is decrypted only in memory for the provider request.

If no stored OAuth credential exists, the existing environment-backed authorization path remains available for compatibility.

If a stored OAuth credential exists but is revoked, expired, provider-mismatched, undecryptable or missing its deployment key, AnalystWatch fails closed. It does **not** silently fall back to a different environment-backed account.

## Explicit v0.29 limits

Product v0.29 does not yet claim:

- a visible Add Source **Connect Microsoft / Connect Google** button; authorization start is currently exposed through the authenticated start routes;
- source `MonitoringConfig` binding to a stored credential ID;
- Microsoft/Google source preflight or scheduled checks using stored OAuth credentials;
- access-token refresh when an encrypted access token expires;
- provider-side revoke;
- explicit reconnect/account-switch UI/workflow;
- a real Microsoft or Google OAuth side effect in repository verification;
- production KMS/HSM deployment.

Existing monitored Microsoft/Google sources therefore continue to use the established `request_header_env` ingestion contract until the next dedicated cutover milestone.

## Health and static-output boundary

OAuth/credential state is operational security state and cannot emit or modify Healthy / Warning / Critical source classification.

v0.29 does not change:

- source detector thresholds or Data Rules;
- baselines/reviews;
- incidents;
- reliability scorecards;
- notifications/delivery/reconciliation;
- dependency/blast-radius semantics;
- monitoring observation persistence.

GitHub Pages remains read-only monitoring output. It receives no OAuth transaction, credential record, ciphertext, key ID, provider account identity, state/PKCE material or callback controls.

## Verification

Verified v0.29 checkpoints include:

- atomic authorization-transaction stores `5a61a8a850c852b7f8151b92da5d05d888432aec`: CI #747 — **393 passed, 1 warning**;
- fixed provider OAuth configuration `37aa50634e064a8540b5dd85bae64eaafdb0789c`: CI #753 — **408 passed, 1 warning**;
- provider start/exchange/callback/identity-binding feature head `0f39cc0b39d5a4c49ab663e523527aea02d6994f`: CI #799 — **433 passed, 1 warning**;
- HTTP callback + encrypted credential persistence `0932ea92fa5b5e763eb23e8d5b1f75cf48d8e07d`: CI #803 — **439 passed, 1 warning**;
- frozen v0.29 feature checkpoint `6dcbe1b56a4d4375f56056d941226b959716aec6`: CI #805 — **445 passed, 1 warning**.

Each exact checkpoint passed Ruff, compile/import and the PostgreSQL 16-backed suite. The single warning remains the existing Starlette TestClient/httpx deprecation warning.

No real Microsoft/Google OAuth application credentials or tenant authorization were supplied, so no real provider token/account side effect is claimed.

## What comes next

The next engineering milestone should complete the runtime cutover rather than add another connector:

1. add an explicit optional stored-credential binding to Microsoft/Google source configuration;
2. resolve that credential through the workspace-bound encrypted store in preflight and scheduled checks;
3. preserve existing environment-header sources as a backward-compatible path;
4. add refresh-token rotation with atomic encrypted replacement;
5. add explicit reconnect/account-switch/revoke semantics;
6. add the small Add Source connect-control bridge once the credential-binding contract is frozen;
7. run a managed-PostgreSQL pilot with real Microsoft/Google credentials and end-to-end failure drills.

AI investigation remains downstream of deterministic evidence and must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
