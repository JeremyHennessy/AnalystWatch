# AnalystWatch

**The trust layer for analyst-owned reporting.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the deterministic evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what changed, what has been happening recently, and what is affected if I cannot?**

## Product v0.28 status

Product v0.28 establishes the **encrypted provider-credential and OAuth authorization-transaction foundation** required before AnalystWatch can safely own Microsoft or Google delegated credentials.

This release deliberately stops before a provider callback or token-exchange network call. It proves the security and persistence contracts first:

- authenticated encryption for access tokens, refresh tokens and PKCE verifiers;
- workspace/provider/account/credential/secret-purpose binding;
- deployment-held key loading and key rotation;
- typed encrypted credential records;
- Memory, SQLite and PostgreSQL credential-store behavior;
- revocation/account-switch/stale-update guardrails;
- short-lived OAuth state + PKCE transaction primitives with replay/expiry/tamper protection.

The existing v0.27 environment-backed Microsoft/Google Authorization path remains the only credential path used by live connector/discovery code in v0.28.

## Authenticated credential encryption

`CredentialKeyring` uses AES-256-GCM through the vetted `cryptography` package.

Each encrypted secret has:

- envelope version;
- `AES-256-GCM` algorithm identifier;
- key ID;
- random 96-bit nonce;
- authenticated ciphertext.

Plaintext tokens and encryption-key bytes are not fields on the serialized envelope.

Associated data binds provider credentials to:

- workspace;
- provider;
- credential ID;
- stable provider subject/account ID;
- secret role (`access_token` or `refresh_token`).

As a result, moving ciphertext to another workspace/account/credential or swapping access-token and refresh-token envelopes fails authentication rather than decrypting under the wrong context.

## Key management and rotation

Encryption keys are deployment supplied. They are not stored in provider credential rows.

The runtime loader reads only the explicit key configuration contract:

```text
ANALYSTWATCH_CREDENTIAL_KEYS_JSON
ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID
```

The keyring supports multiple decryption keys and exactly one active encryption key. Existing ciphertext can remain decryptable during a rotation window while new or re-encrypted secrets use the active key.

Configuration fails closed for missing/invalid JSON, invalid key IDs, invalid base64url material, non-256-bit keys, missing active keys and oversized keyrings. Error messages do not echo key material.

This is an application-managed keyring contract; v0.28 does not claim a deployed cloud KMS/HSM integration.

## Encrypted provider credential record

`ProviderCredentialRecord` stores only encrypted token envelopes plus bounded metadata:

- credential ID;
- workspace;
- provider;
- stable provider subject/account ID;
- optional display name/email;
- normalized scopes;
- encrypted access token;
- optional encrypted refresh token;
- access-token expiry;
- created/updated/revoked timestamps.

Credential replacement is fail-closed:

- provider or account replacement requires an explicit future account-switch flow;
- `created_at` is immutable;
- stale updates are rejected;
- a revoked credential cannot be silently reactivated;
- revoked credentials cannot be unsealed.

This prevents a reconnect/refresh implementation from silently changing the provider identity behind existing monitored sources.

## Credential-store persistence

v0.28 adds one credential-store protocol with Memory, SQLite and PostgreSQL implementations.

SQLite uses a dedicated `provider_credentials` table with `(workspace_id, credential_id)` identity and serializes the encrypted record JSON only. Existing-row updates/revokes execute under `BEGIN IMMEDIATE` so replacement validation is performed against a stable row.

PostgreSQL stores encrypted record JSONB in the existing AnalystWatch PostgreSQL schema. Existing-row updates/revokes use row locking before applying the same replacement/revocation invariants.

Persistence tests reopen both backends, verify workspace isolation, exercise update/revoke behavior, and inspect the raw stored payload to prove the test access/refresh plaintext strings are absent.

The credential store is separate from `MonitoringConfig`, source definitions and observation history.

## OAuth authorization transaction foundation

v0.28 adds provider-neutral start/consume primitives for a future authorization-code flow.

A transaction binds:

- workspace;
- initiating user;
- provider;
- target credential ID;
- transaction ID;
- created/expiry/consumed timestamps.

Start generates:

- a cryptographically random state value returned only to the initiating flow;
- only a SHA-256 digest of that state in the transaction record;
- a cryptographically random PKCE verifier;
- an S256 code challenge;
- an AES-GCM-encrypted PKCE verifier bound to workspace/user/provider/credential/transaction metadata.

Consumption:

- revalidates the entire transaction before use;
- rejects already-consumed transactions;
- rejects expiry;
- compares state digests with constant-time comparison;
- rejects mismatched state without echoing it;
- authenticates the encrypted PKCE verifier against the bound metadata;
- fails with bounded errors for invalid/tampered transaction metadata.

The default authorization transaction TTL is 10 minutes and the configured maximum is 15 minutes.

## What v0.28 does not claim

Product v0.28 does **not** add:

- a Microsoft authorization endpoint redirect;
- a Google authorization endpoint redirect;
- an HTTP callback route;
- authorization-code exchange;
- provider token refresh network calls;
- provider revocation network calls;
- automatic migration from existing environment tokens into the credential store;
- source connector consumption of stored credentials;
- a production KMS/HSM deployment;
- any change to Healthy / Warning / Critical source classification.

Those behaviors are intentionally separated so the first callback implementation must build on an already-tested encryption, persistence and state/PKCE boundary.

## Existing connection and monitoring behavior retained

The v0.27 connection experience remains intact:

- Test Microsoft/Google connection;
- inspect deterministic credential lifecycle guidance;
- verify the connected account;
- browse Microsoft drives/workbooks/tables;
- browse Google spreadsheets/sheets and bounded A1 ranges;
- retain manual connector fields;
- run ordinary source preflight and guarded onboarding.

Source Packs, Data Rules, row-level comparison, incident transitions, notifications, delivery reconciliation, reliability scorecards and dependency/blast-radius logic are unchanged.

GitHub Pages remains a read-only monitoring artifact and receives no provider credential record, ciphertext, account identity, OAuth state, PKCE material, key IDs or credential-management controls.

## Verification

Verified Product v0.28 checkpoints:

- initial AES-GCM/key-rotation foundation `eeda29a039a5a9e7bf4047154aba50a759dc91f5`: CI #691 — **358 passed, 1 warning**;
- account/secret-bound encrypted record + MemoryStore `61ed8d8dd3c4ec08c38722ff8dc54f8e438a7aa4`: CI #701 — **367 passed, 1 warning**;
- SQLite/PostgreSQL encrypted persistence `fc8acb4bec299c5083aee466528bd8502645128d`: CI #707 — **372 passed, 1 warning**;
- deployment key loading + state/PKCE transaction foundation `1ee8b3cec44a5b845024fdff396b6c8ee094fe2e`: CI #725 — **383 passed, 1 warning**.

The exact feature head passed Ruff, compile/import checks and the PostgreSQL 16-backed suite. The final security regression also proves valid-but-tampered transaction metadata reaches authenticated decryption failure while structurally invalid copied metadata fails through a bounded validation error.

No real Microsoft or Google OAuth application/client credentials were supplied for this repository work, so a real authorization-code flow or token side effect is **not claimed**.

## Hosted state

Product v0.27 merged to `main` at `d127c926e5777a8901c8cfdcd9805085130d408e`. Post-merge `monitor-state` advanced to `41efdb60932d09df768eaa7d4354afd2d83aa0d1`, confirming hosted monitoring-state persistence after the release.

v0.28 adds credential-storage code but does not wire that store into the hosted monitoring workflow, so it does not require rewriting existing monitoring observations or source definitions.

## What comes next

After v0.28, implement the actual provider authorization flow in a new gated milestone:

1. provider OAuth configuration with exact allowlisted redirect URIs and bounded scopes;
2. authenticated Operator/Admin connect-start routes that persist short-lived authorization transactions;
3. Microsoft/Google callback + authorization-code exchange using the consumed PKCE verifier;
4. verify provider account identity before storing the encrypted credential;
5. atomic refresh-token replacement and expiry handling;
6. explicit reconnect, account-switch and revoke workflows;
7. connect stored credentials to existing Microsoft/Google discovery and ingestion without weakening preflight;
8. deploy an authenticated managed-PostgreSQL pilot and run real end-to-end failure drills.

AI investigation remains downstream of deterministic evidence and must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
