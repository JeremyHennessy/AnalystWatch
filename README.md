# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.31 status

Product v0.31 adds **atomic OAuth refresh-token rotation** to the encrypted Microsoft/Google credential path introduced in v0.28-v0.30.

A monitored Microsoft 365 Excel or Google Sheets source that explicitly binds a stored OAuth credential can now recover from an expired access token without silently switching accounts or falling back to environment authorization.

The release preserves the existing monitoring engine. It does **not** change detector thresholds, Data Rules, Health classification, baselines, incidents, notification semantics, scorecards, dependencies, FDA examples or monitoring persistence.

## Stored source credential path

Microsoft Excel and Google Sheets sources may bind an explicit workspace-scoped credential:

```text
credential_id=<stored OAuth credential>
```

The same resolver is used for:

- source preflight;
- onboarding preflight;
- source update preflight;
- manual checks;
- `check-all`;
- scheduled `check-due` execution.

A configured stored credential never silently falls back to an environment-backed account.

Existing Microsoft/Google sources without `credential_id` retain the established `request_header_env` path. Generic REST API sources remain unchanged.

## Expired-token refresh

When a bound stored access token is expired, or has no verified expiry, the resolver attempts refresh only when the fixed provider OAuth runtime is configured and the encrypted credential contains a refresh token.

The refresh contract is:

```text
bound source
→ workspace credential
→ expired / unknown access-token expiry
→ atomic credential lock
→ fixed Microsoft / Google token endpoint
→ refreshed access token
→ provider account identity re-check
→ same subject required
→ encrypted token replacement
→ existing source reader
```

If any trust check fails, monitoring fails closed through the normal source-availability evidence path.

## Rotation rules

AnalystWatch preserves provider-specific refresh behavior without weakening account ownership:

- **Microsoft:** when the refresh response returns a replacement refresh token, the new token replaces the old encrypted refresh token.
- **Google:** when the refresh response omits a replacement refresh token, AnalystWatch preserves the existing encrypted refresh token.
- returned scope evidence, when present, must remain within the fixed configured provider scope set;
- the refreshed access token must resolve to the same provider subject/account ID already bound to the credential;
- a different provider account is rejected and requires an explicit future reconnect/account-switch workflow;
- revoked credentials are never refreshed;
- missing refresh-token state requires reconnect rather than guessing another credential path.

The existing Google authorization-start flow already requests offline access, and the Microsoft scope set already includes `offline_access`.

## Concurrency safety

Refresh-token rotation is serialized around the individual credential update so two workers cannot independently refresh the same credential and overwrite a newly rotated refresh token with stale state.

Verified locking paths:

- process lock for `MemoryCredentialStore`;
- SQLite `BEGIN IMMEDIATE` for the credential sidecar;
- PostgreSQL row-level `SELECT ... FOR UPDATE` for `PostgresCredentialStore`.

The provider token request and refreshed account-identity check intentionally occur while that credential update is claimed.

Regression coverage proves two concurrent SQLite refresh attempts make **one** token-endpoint call, and two concurrent PostgreSQL refresh attempts also make **one** token-endpoint call.

## Encryption and identity preservation

Token plaintext is decrypted only in memory and encrypted again before persistence.

Refresh preserves the credential identity boundary:

- workspace ID;
- provider;
- credential ID;
- provider subject/account ID;
- original `created_at`.

The update advances `updated_at` and replaces access-token/expiry metadata only after the refreshed provider identity has been verified.

Known access/refresh token values are not serialized into source definitions, preflight results or observations.

## Failure behavior

Examples of bounded refresh failures include:

- provider runtime credentials are not configured;
- stored refresh token is missing;
- credential is revoked;
- provider token endpoint rejects the refresh;
- provider returns unusable token evidence;
- refreshed scope evidence exceeds the configured scope set;
- refreshed access token resolves to another provider account;
- encrypted refresh/access token cannot be decrypted safely.

Provider response bodies and token material are not copied into AnalystWatch error messages.

## Verification

Frozen functional checkpoint:

```text
957a4fbaa94bf77be4eb757ed39906a9bc430ea2
```

Verified on that functional head:

- Ruff: success;
- compile/import: success;
- PostgreSQL 16-backed suite: **460 passed, 1 warning**;
- Microsoft access/refresh-token rotation;
- Google refresh-token preservation when no replacement is returned;
- provider-account mismatch leaves the existing credential unchanged;
- rejected provider responses do not leak response-body secrets;
- missing refresh token performs no provider call;
- concurrent SQLite refresh is serialized to one token request;
- concurrent PostgreSQL refresh is serialized to one token request;
- source resolver refreshes an expired Google credential once and reuses the refreshed record.

The single warning remains the existing Starlette TestClient/httpx deprecation warning.

Repository CI uses bounded HTTP mocks for Microsoft/Google refresh and identity calls. No real Microsoft/Google OAuth application credentials or tenant authorization were supplied, so no real provider refresh side effect is claimed.

Release-only version/documentation changes are re-gated on their exact head before merge.

## FDA / openFDA examples

AnalystWatch also includes conservative, **disabled** openFDA examples for:

- FAERS drug adverse-event reports;
- MAUDE device adverse-event reports.

They live in `config/fda.sources.example.json` and are not enabled in hosted monitoring.

The examples demonstrate ordinary API availability, response/profile changes and latest-report-date evidence. They deliberately do not invent a freshness SLA, unique key, numeric contract, event incidence estimate or causal medical conclusion.

See [`docs/FDA_EXAMPLES.md`](docs/FDA_EXAMPLES.md).

## Explicit v0.31 limits

Product v0.31 does not yet implement:

- proactive near-expiry refresh;
- explicit reconnect/account-switch workflow;
- provider-side revoke;
- visible Add Source **Connect Microsoft / Connect Google** binding to a source;
- generic REST API stored-OAuth binding;
- production KMS/HSM infrastructure;
- a real Microsoft/Google refresh side effect in repository CI.

## What comes next

Continue credential lifecycle in isolated milestones rather than combining several account mutations at once:

1. explicit reconnect/account-switch semantics with operator-visible identity confirmation;
2. provider revoke where supported, preserving local revocation evidence even when remote revoke is ambiguous;
3. the small Add Source connection-control bridge once account-switch/revoke behavior is frozen;
4. managed-PostgreSQL pilot validation using real Microsoft/Google credentials and end-to-end failure drills;
5. only then expand connector breadth based on customer demand.

AI investigation remains downstream of deterministic evidence and must never redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
