# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.30 status

Product v0.30 completes the first monitored-source cutover onto the encrypted Microsoft/Google OAuth credential foundation introduced in v0.28 and made operational in v0.29.

The release adds an explicit optional stored credential binding to Microsoft 365 Excel and Google Sheets source configuration. The same workspace-bound credential resolver is used for source preflight and monitored checks, so onboarding cannot validate through one account path and later monitor through another.

v0.30 preserves all previously verified monitoring semantics. It does **not** change detector thresholds, Data Rules, Health classification, baselines, incidents, notifications, reliability scorecards, dependencies or monitoring persistence.

## Stored credential source binding

Microsoft Excel and Google Sheets sources may now set:

```text
credential_id=<workspace-scoped stored OAuth credential>
```

A stored credential binding is explicit. AnalystWatch does not silently choose a default OAuth account inside source ingestion.

For a bound source, AnalystWatch:

1. validates that stored OAuth binding is supported for the source type;
2. resolves the credential only inside the source's bound workspace;
3. verifies provider identity matches the connector;
4. rejects revoked credentials;
5. rejects missing or expired access-token state;
6. loads the deployment credential keyring;
7. decrypts the access token only in memory;
8. supplies the bearer authorization to the existing Microsoft/Google reader;
9. returns ordinary deterministic preflight or observation evidence.

Credential plaintext is not copied into the source definition, observation record or public output.

## Backward-compatible environment authorization

Existing Microsoft/Google sources that do not set `credential_id` retain the established `request_header_env` authorization path.

A source cannot configure both `credential_id` and `request_header_env`. This prevents ambiguous account ownership.

If a source explicitly binds a stored credential and that credential is missing, provider-mismatched, revoked, expired, undecryptable or unavailable because deployment key configuration is invalid, the source fails closed. AnalystWatch does **not** fall back to an environment-backed account.

Generic REST API sources remain on the existing request-header contract in v0.30; stored OAuth credential binding is intentionally limited to the Microsoft Excel and Google Sheets connectors whose provider/account semantics are already verified.

## Shared preflight and monitoring path

`MonitorService` owns the source credential resolver and passes it through the existing ingestion boundary.

The same resolver therefore covers:

- source preflight;
- onboarding preflight;
- source update preflight;
- manual source checks;
- `check-all`;
- scheduled `check-due` execution.

No second detector or monitoring state machine was introduced.

## OAuth foundation retained from v0.29

The v0.29 provider OAuth runtime remains the foundation for stored credentials:

- persistent one-time authorization transactions in Memory, SQLite and PostgreSQL;
- state + PKCE persisted before provider redirect;
- fixed Microsoft/Google OAuth endpoints, redirect paths and bounded scope sets;
- bounded authorization-code exchange;
- provider account-identity verification before credential persistence;
- AES-256-GCM encrypted access/refresh-token persistence;
- workspace/provider/credential/account binding;
- replay/expiry/provider/workspace callback protection;
- connection check, identity, lifecycle and resource browsing that prefer stored OAuth credentials when present;
- no silent environment-account fallback when an existing stored OAuth credential is unusable.

OAuth/credential state remains operational security state and cannot itself emit Healthy / Warning / Critical source classification.

## Runtime credential stores

The v0.30 source resolver reuses the existing v0.29 credential persistence:

- SQLite monitoring runtimes use the existing `.credentials.db` sidecar for the same monitoring database;
- PostgreSQL monitoring runtimes use the existing `PostgresCredentialStore` on the same managed AnalystWatch DSN;
- workspace identity remains mandatory in both cases.

Regression coverage proves source ingestion through both the legacy SQLite sidecar path and the PostgreSQL credential-store path.

## Explicit v0.30 limits

Product v0.30 does not yet claim:

- automatic refresh-token use when an access token expires;
- explicit reconnect/account-switch workflow;
- provider-side revoke;
- a visible Add Source **Connect Microsoft / Connect Google** control wired directly into stored source binding;
- generic REST API stored-OAuth binding;
- a real Microsoft or Google OAuth side effect in repository CI;
- production KMS/HSM deployment.

Until refresh support is implemented, an expired stored access token fails closed and requires reconnect outside the current automated source path.

## Verification

Functional checkpoint:

- `f02e4cd34028f744f448bc37f8361d6bc29d28e6`
- CI #828: **SUCCESS**
- Live source smoke #106: **SUCCESS**
- Ruff: success
- compile/import: success
- PostgreSQL 16-backed suite: **451 passed, 1 warning**

The single warning is the existing Starlette TestClient/httpx deprecation warning.

The PostgreSQL-specific regression proves that a `PostgresStorage` monitoring runtime resolves and uses the existing workspace-bound `PostgresCredentialStore`, while the legacy regression proves the existing SQLite `.credentials.db` sidecar path.

No real Microsoft/Google OAuth application credentials or tenant authorization were supplied, so no real provider token/account side effect is claimed by repository verification.

## Live-source smoke boundary

The live-source smoke workflow is the external/public upstream gate. It now checks enabled generic API sources only. Static local demonstration fixtures remain monitored by the application and covered by deterministic tests, but their intentionally fixed sample dates no longer masquerade as live external-source evidence in that workflow.

This correction was independently isolated and merged before v0.30 after CI and the live-source smoke both passed.

## What comes next

The next engineering milestone should finish credential lifecycle operations before adding more connector breadth:

1. atomic refresh-token rotation with encrypted replacement and preserved provider/account binding;
2. explicit reconnect and account-switch semantics;
3. explicit provider revoke where supported;
4. the small Add Source connect-control bridge once lifecycle behavior is frozen;
5. managed-PostgreSQL pilot validation with real Microsoft/Google credentials and end-to-end failure drills.

Optional FDA/openFDA examples are being handled separately as conservative disabled example sources rather than being mixed into the OAuth runtime milestone.

AI investigation remains downstream of deterministic evidence and must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
