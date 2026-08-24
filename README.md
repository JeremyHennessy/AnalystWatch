# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.27 status

Product v0.27 adds **provider account identity and deterministic credential-lifecycle evidence** to the Microsoft 365 / Google connection experience introduced in v0.26.

The release deliberately does not pretend that a full OAuth credential store exists. Microsoft and Google credentials remain server-provisioned environment-backed Authorization values. v0.27 makes that existing credential state easier and safer to diagnose before AnalystWatch moves to a real authorization-code/refresh-token lifecycle.

The dynamic Add Source flow can now answer three separate questions:

1. **Is the configured provider connection reachable?**
2. **Which provider account does the configured credential represent?**
3. **What should the operator do next if the credential is not usable?**

These are connection/setup signals only. They do not alter source Health.

## Account identity evidence

Account identity is intentionally separate from the v0.26 connection-reachability check.

### Microsoft

AnalystWatch can request bounded identity evidence from Microsoft Graph `/me`:

- provider subject/user ID;
- display name when available;
- mail address, falling back to user principal name when needed.

### Google

AnalystWatch can request bounded identity evidence from Google Drive `about.user`:

- stable permission ID;
- display name when available;
- email address when available.

Identity strings are bounded and malformed provider identity fails closed. Credential environment-variable names, bearer-token values, and raw provider error bodies are not returned in identity responses.

A successful identity lookup means the currently configured delegated credential identified an account at that moment. It does not imply that AnalystWatch stores or can refresh that credential.

## Deterministic credential lifecycle

`CredentialLifecycle` derives a small, explainable setup state from provider reachability plus identity evidence:

- `needs_credential` → **configure** the server credential;
- `rejected` → **reconnect** because the provider rejected the connector credential;
- `unavailable` → **retry** before changing credentials because the provider/network could not be reached reliably;
- `identity_unverified` → **review scopes** when connector access works but account identity is rejected, or retry for other identity-only failures;
- `verified` → **no action** because provider access is reachable and account identity is verified.

A key claim-safety rule is that **identity failure cannot silently redefine connector reachability**. For example, a credential may be able to enumerate Microsoft drives while lacking the Graph permission required to read `/me`; that is reported as reachable + identity-unverified rather than falsely declaring the connector broken.

The lifecycle model is non-persistent. It does not create a second source state machine and does not participate in Healthy / Warning / Critical classification.

## Add Source connection UX

The existing Microsoft and Google sections now keep three distinct actions:

- **Test connection** — provider/resource reachability;
- **Credential status** — deterministic lifecycle state and next-step guidance;
- **Verify connected account** — direct account identity evidence.

The existing v0.26 resource browser remains available:

### Microsoft

- browse current-user drives;
- search `.xlsx` workbooks;
- select workbook tables;
- populate the ordinary Drive ID / workbook item ID / table fields.

### Google

- browse spreadsheets;
- load GRID sheets/tabs;
- populate the ordinary Spreadsheet ID;
- suggest an A1 range only for known grids no larger than 5,000 rows × 100 columns;
- require explicit range entry for larger/unknown grids rather than silently truncating data.

Manual connector fields remain available. Source Packs, Data Rules, visible row-comparison fields, stale-preflight invalidation, normal preflight and guarded onboarding remain authoritative.

## API and authorization boundary

Connection operations remain dynamic-app-only and Operator-only under signed-bearer authorization.

Existing v0.26 discovery routes are retained, and v0.27 adds fixed-credential identity/lifecycle routes:

```text
POST /api/connections/microsoft/identity
POST /api/connections/microsoft/lifecycle
POST /api/connections/google/identity
POST /api/connections/google/lifecycle
```

All provider operations use the fixed server references:

```text
ANALYSTWATCH_MICROSOFT_AUTHORIZATION
ANALYSTWATCH_GOOGLE_AUTHORIZATION
```

Callers cannot choose arbitrary process environment-variable names. Public API payloads do not serialize those reference names or bearer-token values.

## OAuth boundary

Product v0.27 **does not** persist OAuth access or refresh tokens and does not add a fake Connect/Callback flow.

A production OAuth implementation must be designed as a separate security boundary and should include at minimum:

- authorization-code flow with state/CSRF validation and PKCE where supported;
- exact redirect-URI/provider configuration;
- encrypted-at-rest access/refresh-token storage behind a credential-store interface;
- a deployment-held encryption/KMS key that is not stored beside ciphertext;
- provider/account/workspace binding and stable account identity evidence;
- expiry/refresh handling with atomic replacement;
- explicit reconnect and revoke semantics;
- audit evidence that never records token material;
- failure behavior that distinguishes expired/rejected credentials from temporary provider outages;
- migration/recovery tests for encrypted credential records.

Until that contract exists and is verified, the environment-backed delegated authorization path remains the only supported provider credential mechanism.

## Health and monitoring boundary

v0.27 does not change:

- source ingestion;
- detector thresholds;
- Data Rule semantics;
- Healthy / Warning / Critical classification;
- baselines or reviews;
- incidents;
- notification/delivery/reconciliation state;
- reliability scorecards;
- dependency/blast-radius logic;
- monitoring persistence schema.

Credential lifecycle is setup/operational evidence, not source reliability evidence.

## Dynamic app vs GitHub Pages

Provider connection checks, identity, lifecycle guidance and resource browsing are available only in the dynamic FastAPI app.

GitHub Pages remains a **read-only monitoring snapshot**. No provider credentials, account identity, lifecycle state, or dynamic connection controls are published into Pages output.

## Verification

Verified Product v0.27 feature checkpoints:

- provider account identity foundation `0fbda27b9e82a62db1da66c16c2f8324ec10be37`: CI #653 — **335 passed, 1 warning**;
- fixed identity API + Add Source identity UX `1ed0edc6f0c5dc330c9d674cf02c7485e3ca9928`: CI #661 — **340 passed, 1 warning**;
- pure credential lifecycle model `7f66752937e1c11e07c1d9704c766753fd1e086f`: CI #665 — **345 passed, 1 warning**;
- full lifecycle API/UI checkpoint `582fc1d276e13684e893ece4d7d33ce6202b0c2c`: CI #673 — **350 passed, 1 warning**.

Each exact checkpoint passed Ruff, compile/import checks and the PostgreSQL 16-backed test suite.

Package, FastAPI and module versions are aligned to `0.27.0` during release closeout and are re-gated on the final exact head before merge.

No real Microsoft or Google tenant credential was supplied for this repository work, so live account identity or lifecycle verification against a real tenant is **not claimed**. Live-source smoke is not claimed unless an actual final-head run is observed.

## Hosted state

Product v0.26 merged to `main` at `5f7e4501dcc536d51507e90d54333ba210dc6e92`. Post-merge `monitor-state` advanced to `b271ef3dbf906709c45443ed03b2d752c79584b8`, confirming hosted monitoring-state persistence.

v0.27 changes connection/setup evidence rather than source monitoring data, so no hosted monitoring-database rewrite is required.

## What comes next

The next major engineering step should be **real OAuth credential ownership**, followed by a hosted pilot:

1. encrypted credential-store contract and key-management design;
2. Microsoft/Google authorization-code connect + callback + refresh;
3. explicit reconnect/revoke and account-switch handling;
4. authenticated managed-PostgreSQL deployment;
5. real Microsoft/Google/Power BI/email/Teams end-to-end failure drills;
6. five-minute first-value onboarding and safe simulation tools;
7. customer/pilot validation before broad connector accumulation.

AI investigation remains an explanation layer over deterministic evidence and must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
