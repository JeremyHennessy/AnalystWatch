# AnalystWatch Product v0.27 Architecture

## Decision

Product v0.27 adds a **non-persistent credential identity and lifecycle layer** on top of the v0.26 Microsoft/Google connection-discovery foundation.

The architectural rule is: **credential diagnostics may explain whether a configured provider credential is usable and which account it represents, but they cannot redefine connector reachability, source Health, or persist secret material.**

```text
fixed server credential reference
        ↓
provider reachability check ───────────────┐
        ↓                                 │
account identity check                    │
        ↓                                 │
deterministic credential lifecycle        │
        ↓                                 │
configure / reconnect / retry /           │
review scopes / no action                 │
                                          │
resource browse/select ────────────────────┘
        ↓
existing m365:// or gsheets:// fields
        ↓
ordinary SourceDefinition + MonitoringConfig
        ↓
existing preflight / guarded onboarding
        ↓
existing monitoring / Health / incidents
```

## Provider account identity

`ConnectionAccountIdentity` is bounded evidence about the account represented by the currently configured delegated credential:

- `provider`;
- stable provider `subject_id`;
- optional display name;
- optional email address.

Strings are bounded to 512 characters. Blank/untrimmed/oversized required provider identity fields fail closed.

### Microsoft identity

Microsoft uses Graph v1.0 `/me` with a narrow field selection:

```text
id, displayName, mail, userPrincipalName
```

`mail` is preferred for analyst-facing email evidence; `userPrincipalName` is a fallback. The Graph `id` is retained as the stable subject ID.

### Google identity

Google uses Drive API v3 `about` with:

```text
user(displayName,emailAddress,permissionId)
```

`permissionId` is retained as the stable subject ID.

### Identity claim boundary

A successful identity request proves only that the configured credential returned bounded account identity at that moment. It does not prove:

- future credential validity;
- refresh-token ownership;
- persistent authorization;
- access to every provider resource;
- source data correctness.

Identity responses never contain credential environment-variable names or token values. Raw provider rejection bodies are never surfaced.

## Reachability remains independent

The v0.26 connection check remains authoritative for the narrow question: **can the configured provider credential reach the connector's existing discovery surface?**

Microsoft reachability continues to use `/me/drives`; Google reachability continues to use Drive spreadsheet discovery.

Identity is intentionally a separate provider request. This prevents a missing identity-specific permission from turning a usable file credential into a false connector failure.

Example:

```text
/me/drives → 200
/me        → 403
```

The credential is still `reachable=True` for connector purposes. Identity is `unverified`; the lifecycle layer recommends reviewing scopes rather than declaring the connector unavailable.

## Deterministic credential lifecycle

`CredentialLifecycle` contains:

- provider;
- lifecycle state;
- explicit next action;
- configured/reachable/identity-verified booleans;
- bounded HTTP status when available;
- optional bounded account identity;
- deterministic guidance text.

Lifecycle states:

```text
needs_credential
rejected
unavailable
identity_unverified
verified
```

Next actions:

```text
configure
reconnect
retry
review_scopes
none
```

### Derivation

1. Missing runtime credential → `needs_credential` / `configure`.
2. Connector reachability rejected with 401/403 → `rejected` / `reconnect`.
3. Other connector reachability failure → `unavailable` / `retry`.
4. Connector reachable but identity request rejected with 401/403 → `identity_unverified` / `review_scopes`.
5. Connector reachable but other identity failure → `identity_unverified` / `retry`.
6. Connector reachable and identity verified → `verified` / `none`.

The lifecycle model is derived on demand and is not persisted.

## API boundary

v0.27 retains the v0.26 discovery routes and adds Operator-only fixed-credential routes:

```text
POST /api/connections/microsoft/identity
POST /api/connections/microsoft/lifecycle
POST /api/connections/google/identity
POST /api/connections/google/lifecycle
```

All connection POST routes remain under the established Operator authorization prefix.

Provider operations use only:

```text
Microsoft → ANALYSTWATCH_MICROSOFT_AUTHORIZATION
Google    → ANALYSTWATCH_GOOGLE_AUTHORIZATION
```

The caller cannot select an arbitrary process environment-variable name.

These endpoints do not:

- create/update a source;
- establish a baseline;
- persist provider state;
- store or rotate a token;
- change source Health;
- write observation history.

## Add Source UI boundary

The approved v0.25/v0.26 onboarding flow remains authoritative.

Inside each provider section, the connection browser now exposes three distinct diagnostic actions:

1. **Test connection** — connector reachability.
2. **Credential status** — derived lifecycle state and next-step guidance.
3. **Verify connected account** — direct identity evidence.

Resource browsing remains unchanged:

- Microsoft drive → `.xlsx` workbook → Excel table;
- Google spreadsheet → GRID sheet/tab → bounded or explicit A1 range.

Manual connector fields remain visible/editable. Source Packs, Data Rules, row-comparison fields, preflight and guarded onboarding are unchanged.

All external text is rendered using text content rather than HTML insertion. Credential environment-variable names and bearer-token examples are absent from the browser JavaScript.

## Existing connector and Health boundary

Product v0.27 does not modify Microsoft Excel or Google Sheets ingestion.

The resulting source still uses the existing location contracts:

```text
m365://<drive-id>/<item-id>?table=<table-name>[&worksheet=<sheet>]

gsheets://<spreadsheet-id>?range=<A1-range>[&header_row=1]
```

Credential lifecycle cannot emit Healthy / Warning / Critical and cannot influence:

- findings or Data Rules;
- baselines/reviews;
- incidents;
- reliability scorecards;
- notification policy;
- delivery attempts/reconciliation;
- dependency/blast-radius state.

There is no monitoring persistence migration in v0.27.

## OAuth / secret persistence boundary

v0.27 intentionally does **not** add an authorization-code callback or refresh-token database.

A production OAuth implementation must be treated as a new security/persistence boundary, not a UI convenience. The minimum architecture for the next phase is:

### Authorization transaction

- provider-specific authorization-code flow;
- cryptographically random state/CSRF token bound to the initiating authenticated workspace/user;
- PKCE where supported/appropriate;
- exact allowlisted redirect URI;
- short-lived transaction record with one-time consumption;
- callback rejects missing, mismatched, replayed or expired state.

### Credential storage

Introduce a credential-store abstraction separate from `MonitoringConfig` and source records. Stored metadata should be sufficient to bind credentials to:

- workspace;
- provider;
- stable provider subject/account identity;
- granted scopes where provider evidence is available;
- access-token expiry;
- refresh capability/status;
- created/updated/revoked timestamps.

Access/refresh tokens must be encrypted at rest. The encryption/KMS key must be deployment-held and not stored beside ciphertext in the same persistence record.

Token material must never enter:

- source definitions;
- observation/finding evidence;
- audit notes;
- logs;
- static Pages;
- API response bodies.

### Refresh and replacement

Refresh must be atomic from AnalystWatch's perspective:

- read current encrypted credential;
- request refresh;
- validate returned provider/account identity where appropriate;
- atomically replace token/expiry metadata;
- retain no plaintext token in persistence or logs;
- classify provider rejection separately from temporary transport failure.

### Reconnect / account switch

Reconnect is not equivalent to retry.

A reconnect flow must explicitly surface when the new provider subject differs from the previously bound account. Account switching should require an intentional operator/admin decision before existing source definitions silently begin using a different identity.

### Revoke

Revocation should:

- invoke the provider revocation endpoint when supported and configured;
- mark/remove the local credential atomically;
- leave source monitoring configuration intact but clearly credential-unavailable;
- avoid deleting monitoring history.

### Recovery and migration

Any persistent credential store requires:

- SQLite/PostgreSQL contract or an intentionally external secret-store implementation;
- schema/version migration tests;
- encryption/decryption failure behavior;
- key-rotation/recovery strategy;
- backup/restore rules that do not accidentally make ciphertext unusable or expose keys.

Until this contract is implemented and verified, environment-backed delegated Authorization remains the supported provider credential mechanism.

## Dynamic app vs static Pages

Connection reachability, identity, lifecycle and resource discovery are dynamic-app-only.

Static GitHub Pages remains a read-only monitoring artifact. It receives no provider credentials, account identity, lifecycle state or connection controls.

## Verification

Verified v0.27 feature checkpoints:

- identity foundation `0fbda27b9e82a62db1da66c16c2f8324ec10be37`: CI #653, **335 passed / 1 warning**;
- identity API/UI `1ed0edc6f0c5dc330c9d674cf02c7485e3ca9928`: CI #661, **340 passed / 1 warning**;
- pure lifecycle model `7f66752937e1c11e07c1d9704c766753fd1e086f`: CI #665, **345 passed / 1 warning**;
- lifecycle API/UI `582fc1d276e13684e893ece4d7d33ce6202b0c2c`: CI #673, **350 passed / 1 warning**.

Every exact feature checkpoint passed Ruff, compile/import checks and the PostgreSQL 16-backed suite.

No real Microsoft/Google tenant credential was supplied, so live provider identity/lifecycle evidence is not claimed.

## Release boundary

Product v0.27 is complete when package/FastAPI/module versions are aligned to `0.27.0`, release docs are aligned to this architecture, and the exact release head passes the full repository gate.

OAuth token persistence, refresh, revoke and provider callback handling remain the next dedicated security milestone rather than being partially simulated inside v0.27.
