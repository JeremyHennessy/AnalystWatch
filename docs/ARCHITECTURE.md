# AnalystWatch Product v0.32 Architecture

## Decision

Product v0.32 adds **explicit same-account OAuth reconnect** on top of the encrypted credential, source-binding and refresh lifecycle proven in v0.28-v0.31.

The architectural rule is:

> **Reconnect may renew credentials for the already-bound provider account, but it may not silently change account identity or reactivate a revoked credential.**

```text
Admin reconnect start
        ↓
existing workspace credential required
        ↓
provider match + active credential required
        ↓
one-time OAuth transaction
        ↓
authenticated operation = reconnect
        ↓
provider code exchange
        ↓
provider identity inspection
        ↓
same subject/account required
        ↓
encrypted token replacement
        ↓
existing credential_id remains stable
```

No monitoring, detector, Health, incident or source state machine is introduced.

## Foundation retained

- v0.28: encrypted provider credential records and workspace/provider/account binding;
- v0.29: persistent OAuth authorization/callback flow and provider identity verification;
- v0.30: stored credentials bound to Microsoft Excel and Google Sheets monitoring;
- v0.31: atomic automatic refresh-token rotation with SQLite/PostgreSQL concurrency safety.

v0.32 changes only the explicit operator-driven reconnect lifecycle.

## Authorization operation versioning

`OAuthAuthorizationTransaction` now carries:

```text
operation: connect | reconnect
aad_version: 1 | 2
```

New transactions use **AAD v2**. The `operation` value is included in the AES-GCM associated data protecting the PKCE verifier.

That makes the transaction intent cryptographic evidence rather than mutable routing metadata:

```text
v2 reconnect changed to connect
    → associated data changes
    → PKCE verifier authentication fails
```

The reverse direction fails for the same reason.

### Legacy transaction compatibility

Already-persisted v1 OAuth transactions can remain alive for only their existing short authorization TTL. v0.32 preserves their original associated-data byte shape so valid in-flight transactions remain consumable.

AAD v1 is defined as **connect-only**. A legacy transaction cannot be reinterpreted as reconnect.

## Reconnect start

New routes:

```text
POST /api/oauth/microsoft/reconnect/start
POST /api/oauth/google/reconnect/start
```

Before creating provider authorization state, the web boundary verifies:

1. the credential exists in the bound workspace;
2. the stored provider matches the requested reconnect provider;
3. the credential has not been locally revoked.

Failures return before provider authorization is started.

Reconnect authorization adds:

```text
prompt=consent
```

Existing provider-specific behavior is retained:

- Microsoft `response_mode=query` and fixed scopes including `offline_access`;
- Google `access_type=offline` and incremental granted scopes.

## Authorization role boundary

The existing signed-bearer authorization classifier permits ordinary Microsoft/Google OAuth **connect** starts to Operator users.

Reconnect routes are intentionally outside that Operator mutation allowlist. They therefore require the default mutating API capability: **Admin**.

This is deliberate because one stored credential may be referenced by multiple monitored sources and reconnect mutates that shared credential.

Provider callbacks remain bearer-exempt because an external provider cannot carry the AnalystWatch bearer session through the callback. Their security boundary remains:

- one-time state;
- PKCE;
- workspace binding;
- provider binding;
- credential ID binding;
- authenticated connect/reconnect operation intent.

## Callback preconditions

After the one-time transaction is consumed, the callback reads the current stored credential before token exchange.

### Connect

If the transaction is `connect`, an existing credential with that ID causes rejection:

```text
credential exists
→ reject
→ use explicit reconnect
```

This avoids silently turning the historical connect path into a replacement operation.

### Reconnect

Reconnect requires the current credential to:

- exist;
- match the callback provider;
- remain active/not locally revoked.

Missing, provider-mismatched or revoked reconnect attempts fail before any provider token exchange.

## Same-account identity proof

A successful provider token response does not authorize replacement by itself.

AnalystWatch uses the new access token to inspect provider identity through the existing Microsoft/Google identity path.

For reconnect:

```text
stored subject == callback subject
    → credential replacement may proceed

stored subject != callback subject
    → reject
    → preserve old credential
    → explicit account-switch milestone required
```

This prevents a reconnect attempt from silently redirecting every source that references a stable `credential_id` to another Microsoft/Google account.

## Encrypted replacement

On verified same-account reconnect, the new credential record preserves:

```text
workspace_id
provider
credential_id
subject_id
created_at
```

and updates encrypted token/expiry and provider display metadata.

If the provider callback omits a replacement refresh token while the stored credential already has one, v0.32 preserves the existing encrypted refresh-token envelope.

Credential replacement continues through the established `CredentialStore.upsert` validation contract.

## Revoked credential boundary

A locally revoked credential cannot be reactivated through reconnect.

Reactivation/account-switch/revoke semantics are intentionally separate operations because each has different audit and failure requirements.

## Interaction with v0.31 automatic refresh

Automatic refresh remains unchanged.

v0.31 handles normal expired-token recovery without operator interaction. v0.32 provides an explicit same-account recovery path for cases where automatic refresh cannot proceed, such as missing/invalid provider refresh authorization.

Both paths preserve the same provider subject/account identity boundary.

## Backward compatibility

- existing connect endpoint URLs remain unchanged;
- existing callback URLs remain unchanged;
- valid in-flight AAD-v1 connect transactions remain consumable;
- v1 cannot represent reconnect;
- existing source `credential_id` references remain stable;
- Microsoft/Google environment-backed sources remain unchanged;
- generic REST API sources remain unchanged;
- CSV/XLSX/JSON sources remain unchanged;
- FDA/openFDA examples remain disabled example sources;
- detector, Data Rule, row-diff, baseline, incident, notification, reliability scorecard, dependency graph and monitoring storage behavior remain unchanged.

## Verification

Frozen v0.32 functional checkpoint:

```text
26b2007b78df3eb15f5049c94d07b97292298183
```

Verified on PostgreSQL 16-backed CI:

- Ruff: success;
- compile/import: success;
- **467 passed, 1 warning**;
- AAD-v2 operation tampering fails verifier authentication;
- legacy AAD-v1 connect remains consumable;
- reconnect authorization explicitly requests provider consent;
- same-account reconnect succeeds through Memory, SQLite and PostgreSQL credential stores;
- different-account reconnect leaves the existing credential unchanged;
- missing/provider-mismatched/revoked reconnect fails before provider exchange;
- signed-bearer Operator receives 403 for reconnect start;
- signed-bearer Admin can start reconnect for an existing matching-provider credential.

The first functional run had six failures caused by one incorrect keyword at the pre-existing OAuth exchange seam (`pkce_verifier` instead of the established `code_verifier`). The correction changed that keyword only; the following clean functional run passed all 467 tests.

The warning remains the existing Starlette TestClient/httpx deprecation warning.

Microsoft/Google provider interactions in repository verification are bounded HTTP mocks. No real reconnect side effect is claimed.

Release-only metadata/documentation changes are re-gated on their exact head before merge.

## Explicit non-goals

Product v0.32 does not implement:

- account switching;
- revoked-credential reactivation;
- provider-side revoke;
- proactive near-expiry refresh;
- Add Source connection/binding UI;
- generic API stored-OAuth binding;
- production KMS/HSM integration;
- new credential or source Health classification.

## Next milestone

The next controlled lifecycle milestone should implement **explicit account switching** as a separate operation.

It should require old-account/new-account identity confirmation, make the identity transition auditable, and prevent a source from switching provider accounts through the ordinary connect/reconnect paths.

Provider-side revoke should follow as another independently verified milestone. Only after account-switch and revoke semantics are frozen should the Add Source UI directly bind provider connections to monitored sources.

AI investigation remains downstream of deterministic evidence and must never redefine Health classification.
