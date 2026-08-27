# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous operational outcomes visible until reviewed.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.32 status

Product v0.32 adds **explicit same-account OAuth reconnect** for stored Microsoft 365 and Google credentials.

Reconnect is deliberately narrower than account switching. A credential may be renewed only when the provider callback resolves the **same provider subject/account ID already bound to that credential**. A different account is rejected and the existing credential remains unchanged.

The release preserves the monitoring engine. It does not change detector thresholds, Data Rules, Health classification, baselines, incidents, notifications, reliability scorecards, dependencies, FDA examples, source configuration or monitoring persistence.

## Reconnect contract

Microsoft and Google now expose explicit reconnect start endpoints:

```text
POST /api/oauth/microsoft/reconnect/start
POST /api/oauth/google/reconnect/start
```

Reconnect requires:

- an existing stored credential;
- the reconnect provider to match the stored provider;
- the credential to be active rather than locally revoked;
- one-time OAuth state + PKCE validation;
- successful provider code exchange;
- provider identity verification;
- the returned provider subject ID to exactly match the stored subject ID.

Only after those checks pass may AnalystWatch replace encrypted access/refresh-token material. The credential keeps the same workspace, provider, credential ID, subject ID and original `created_at`.

If a reconnect token response omits a replacement refresh token, the existing encrypted refresh token is preserved.

## Account switching is not reconnect

Reconnect will not silently change Microsoft or Google accounts.

```text
existing subject == callback subject
    → reconnect may replace encrypted tokens

existing subject != callback subject
    → reject
    → preserve existing credential
    → explicit account-switch workflow required
```

This protects monitored sources that reference a stable `credential_id` from unexpectedly reading a different account after a reconnect attempt.

Revoked credentials are also not silently reactivated by reconnect.

## Authenticated operation intent

OAuth authorization transactions now distinguish:

```text
connect
reconnect
```

New transactions use authorization associated-data version 2. The operation is included in the AES-GCM associated data protecting the PKCE verifier. Changing a v2 transaction from connect to reconnect or vice versa therefore invalidates verifier authentication.

Already-persisted v1 transactions remain compatible for their short existing TTL, but v1 can represent **connect only**. It cannot be reinterpreted as reconnect.

Reconnect authorization explicitly requests provider consent. Existing Google offline-access and Microsoft `offline_access` behavior remains unchanged.

## Authorization boundary

In signed-bearer mode:

- existing OAuth connect remains an Operator mutation;
- reconnect start is intentionally **Admin-only**;
- provider callbacks remain bearer-exempt but are protected by one-time state, PKCE, workspace/provider binding and authenticated operation intent.

Reconnect is treated as an administrative credential mutation because one credential can be referenced by multiple monitored sources.

## Product v0.31 refresh retained

The v0.31 automatic refresh path remains unchanged:

- expired stored credentials can refresh through fixed Microsoft/Google token endpoints;
- refreshed tokens must resolve the same provider subject;
- Microsoft refresh-token rotation is persisted;
- Google can preserve its existing refresh token when the provider omits a replacement;
- concurrent SQLite/PostgreSQL refreshes serialize so only one worker rotates a given refresh token.

v0.32 adds the explicit operator-driven same-account recovery path around that existing identity boundary; it does not replace automatic refresh.

## Verification

Frozen v0.32 functional checkpoint:

```text
26b2007b78df3eb15f5049c94d07b97292298183
```

Verified on that functional head:

- Ruff: success;
- compile/import: success;
- PostgreSQL 16-backed suite: **467 passed, 1 warning**;
- AAD-v2 reconnect/connect operation tampering fails verifier authentication;
- legacy AAD-v1 connect transactions remain consumable;
- same-account reconnect succeeds with Memory, SQLite and PostgreSQL credential stores;
- different-account reconnect leaves the old credential unchanged;
- missing/provider-mismatched/revoked reconnect fails before provider exchange;
- signed-bearer Operator receives 403 for reconnect start;
- signed-bearer Admin can initiate reconnect for an existing matching-provider credential.

One initial functional run failed six tests because the reconnect callback called the established token-exchange function with the wrong keyword (`pkce_verifier` instead of the verified `code_verifier` contract). That was corrected as a one-keyword API-seam fix. The clean functional run above passed all 467 tests.

The single warning remains the existing Starlette TestClient/httpx deprecation warning.

Microsoft/Google provider calls in repository tests are bounded mocks. No real provider reconnect side effect is claimed.

Release-only version/documentation changes are re-gated on their exact head before merge.

## FDA / openFDA examples

The repository also includes conservative, **disabled** examples for openFDA FAERS drug adverse events and MAUDE device adverse events in `config/fda.sources.example.json`.

They are examples only and are not enabled in hosted monitoring. They demonstrate API availability/profile/date evidence and deliberately do not infer causation, incidence, a freshness SLA, unique key or medical-safety conclusion.

See [`docs/FDA_EXAMPLES.md`](docs/FDA_EXAMPLES.md).

## Explicit v0.32 limits

Product v0.32 does not implement:

- account switching;
- reactivation of a revoked credential;
- provider-side revoke;
- proactive near-expiry refresh;
- visible Add Source **Connect Microsoft / Connect Google** binding;
- generic REST API stored-OAuth binding;
- production KMS/HSM infrastructure;
- a real Microsoft/Google reconnect side effect in repository CI.

## What comes next

Continue credential lifecycle in isolated milestones:

1. **explicit account switching** with old-account/new-account identity confirmation and audit evidence;
2. **provider revoke** as a separate failure-aware operation;
3. the Add Source connection/binding UI only after account-switch and revoke semantics are independently green;
4. managed-PostgreSQL pilot validation with real Microsoft/Google credentials and end-to-end failure drills;
5. then additional connector breadth based on customer demand.

AI investigation remains downstream of deterministic evidence and must never redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
