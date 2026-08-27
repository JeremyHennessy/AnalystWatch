# AnalystWatch Product v0.31 Architecture

## Decision

Product v0.31 extends the v0.28-v0.30 encrypted OAuth credential path with **atomic refresh-token rotation** for stored Microsoft 365 and Google credentials.

The architectural rule is:

> **An expired stored credential may refresh only under its existing workspace/provider/account identity, and concurrent workers may not independently rotate the same refresh token.**

```text
SourceDefinition.credential_id
        ↓
StoredSourceCredentialResolver
        ↓
workspace-bound CredentialStore
        ↓
access token expired / expiry unknown
        ↓
atomic credential update claim
        ↓
fixed provider token endpoint
        ↓
refreshed access token
        ↓
provider identity inspection
        ↓
same subject/account required
        ↓
AES-256-GCM token replacement
        ↓
existing Microsoft / Google source reader
        ↓
existing profile / detector / Data Rule path
```

No alternate source Health, incident or monitoring state machine is introduced.

## Foundation retained

Product v0.28 established encrypted credential records and workspace/provider/account binding.

Product v0.29 established persistent provider OAuth authorization/callback handling and provider identity verification before initial credential persistence.

Product v0.30 bound those stored credentials to Microsoft Excel and Google Sheets preflight/monitoring without silent environment-account fallback.

v0.31 changes only the expired-token lifecycle inside that already verified stored-credential path.

## Refresh trigger

`StoredSourceCredentialResolver` continues to load one explicitly bound credential inside the monitoring workspace.

If the stored access token has a verified expiry in the future, the existing decryption/read path is used and no refresh network call occurs.

If the access-token expiry is missing or is at/before the current timezone-aware resolution time, the resolver attempts refresh.

Refresh requires:

- the fixed provider OAuth runtime configuration;
- a persisted encrypted refresh token;
- a non-revoked credential;
- a provider matching the source type;
- the existing deployment credential keyring.

If any prerequisite is missing, the resolver fails closed. It never tries a different stored account or environment-backed Authorization value.

## Provider refresh request

The refresh request uses the provider token endpoint already defined by the fixed OAuth provider configuration.

The request is bounded to:

```text
client_id
client_secret
grant_type=refresh_token
refresh_token=<decrypted only in memory>
```

Provider response bodies are not propagated into AnalystWatch exceptions.

Token response parsing reuses the established OAuth token evidence validation used by the authorization-code exchange.

A usable refreshed access token must include a verified expiry. If the provider returns scope evidence, those scopes must be a subset of the fixed configured provider scope set.

## Provider account identity must remain stable

A successful token endpoint response is not sufficient to overwrite the stored credential.

Before persistence, AnalystWatch uses the refreshed access token to inspect the provider account identity through the existing Microsoft/Google identity path.

The returned provider subject ID must equal the credential's already persisted subject ID.

```text
existing subject == refreshed-token subject
    → replacement may proceed

existing subject != refreshed-token subject
    → reject
    → preserve old stored credential
    → explicit future reconnect/account-switch required
```

Display name/email metadata may update only after the subject identity is proven stable.

## Refresh-token rotation rules

Provider responses do not have identical refresh-token behavior.

### Microsoft

When Microsoft returns a replacement refresh token, AnalystWatch encrypts and persists the replacement token with the refreshed access token.

### Google

Google refresh responses can omit a replacement refresh token. When no replacement is returned, AnalystWatch preserves the existing encrypted refresh-token value by decrypting the original token in memory and re-sealing it as part of the new credential record.

At no point is the old or new token copied into source configuration or monitoring evidence.

## Atomic refresh claim

Refresh-token rotation creates a race that a normal read → network call → `upsert` sequence cannot safely handle.

Two workers could otherwise:

1. read the same old refresh token;
2. both refresh it;
3. receive different rotation results;
4. persist in the opposite order;
5. overwrite the newest refresh token with stale state.

v0.31 therefore keeps the individual credential update claimed across the provider refresh and identity check.

### MemoryCredentialStore

A per-store process `RLock` serializes the refresh operation.

### SQLiteCredentialStore

The refresh path opens the existing credential sidecar and starts:

```sql
BEGIN IMMEDIATE
```

The stored credential is read, provider refresh/identity verification occurs, and the replacement row is written before the transaction is released.

This intentionally locks the small credential sidecar during the rare refresh operation rather than allowing an unsafe token-rotation race.

### PostgresCredentialStore

The refresh path reads the workspace/credential row using:

```sql
SELECT ... FOR UPDATE
```

The row remains locked across provider refresh, identity verification and encrypted replacement.

Other credential rows remain independently claimable.

## Atomic no-op after another worker refreshes

The refresh decision is repeated **inside** the credential claim.

If worker A refreshes first, worker B blocks. When worker B acquires the credential, it sees the new unexpired expiry and returns the already refreshed record without another token-endpoint call.

Regression coverage proves exactly one provider token request for two concurrent SQLite callers and exactly one provider token request for two concurrent PostgreSQL callers.

## Encrypted replacement

The refreshed credential is sealed using the existing AES-256-GCM credential keyring.

Identity fields remain unchanged:

```text
workspace_id
provider
credential_id
subject_id
```

The original `created_at` is preserved. `updated_at` advances to the refresh time. Access-token expiry and encrypted token envelopes are replaced only after provider/account validation succeeds.

The credential encryption associated data binds workspace/provider/credential/account/secret-role identity. Timestamp metadata is not part of the token associated data, so preserving `created_at` after resealing does not invalidate ciphertext authentication.

Existing credential replacement validation is still applied before persistence.

## Failure atomicity

The existing credential remains unchanged when refresh fails before replacement.

Examples:

- missing refresh token;
- revoked credential;
- provider HTTP rejection;
- unusable token JSON/evidence;
- returned scopes outside the configured provider set;
- identity endpoint failure;
- refreshed token resolving another provider account;
- cryptographic failure.

The transaction/row claim is released without writing a partial credential.

## Source monitoring integration

`StoredSourceCredentialResolver` owns refresh invocation.

The source execution path remains:

```text
preflight / onboarding / update preflight / check / check-all / check-due
        ↓
MonitorService
        ↓
StoredSourceCredentialResolver
        ↓
refresh if required
        ↓
Authorization bearer
        ↓
existing provider reader
```

No ingestion, detector, Data Rule, row-diff, baseline, incident, notification, reliability-scorecard or dependency-graph behavior was rewritten for v0.31.

## Backward compatibility

Unexpired stored credentials behave exactly as in v0.30.

Microsoft/Google sources without `credential_id` continue to use the existing environment-backed request-header path.

Generic REST API sources are unchanged.

CSV/XLSX/JSON sources are unchanged.

The optional FDA/openFDA examples remain disabled example sources and are not part of the OAuth refresh runtime.

## OAuth authorization prerequisite

The existing authorization-start implementation already requests refresh-token-capable access:

- Microsoft fixed scopes include `offline_access`;
- Google authorization requests `access_type=offline` and incremental granted-scope inclusion.

v0.31 therefore does not silently assume refresh-token issuance from an authorization flow that never asked for offline access.

## Verification

Frozen functional checkpoint:

```text
957a4fbaa94bf77be4eb757ed39906a9bc430ea2
```

Verified on PostgreSQL 16-backed CI:

- Ruff: success;
- compile/import: success;
- **460 passed, 1 warning**;
- Microsoft access-token + replacement refresh-token rotation;
- Google access-token rotation while preserving the old refresh token when the response omits one;
- provider account mismatch leaves the stored credential unchanged;
- provider HTTP failure does not expose response-body secret material;
- missing refresh token performs no provider request;
- concurrent SQLite refreshes make one provider token call;
- concurrent PostgreSQL refreshes make one provider token call;
- source resolver refreshes one expired Google credential and reuses the now-unexpired stored record on the next resolution.

The warning remains the existing Starlette TestClient/httpx deprecation warning.

All Microsoft/Google token and identity HTTP calls in repository verification are bounded mocks. No real provider refresh side effect is claimed.

Release-only version/documentation changes are re-gated on their exact head before merge.

## Explicit non-goals

Product v0.31 does not implement:

- proactive near-expiry refresh;
- explicit reconnect/account-switch semantics;
- provider-side revoke;
- a visible Add Source connect-control bridge;
- generic API stored-OAuth binding;
- production KMS/HSM integration;
- a new credential-health or source-health classifier.

## Next milestone

The next controlled lifecycle milestone should be **explicit reconnect/account switching**.

It should establish a user-visible old-account → new-account boundary, require provider identity confirmation, preserve audit/revocation evidence, and refuse silent overwrite of an existing credential identity.

Provider-side revoke should follow as a separate failure-aware milestone. Only after reconnect/revoke behavior is independently green should the Add Source UI bind a provider connection directly to a monitored source.

AI investigation remains downstream of deterministic evidence and must never redefine Health classification.
