# AnalystWatch Product v0.28 Architecture

## Decision

Product v0.28 introduces a **dedicated encrypted provider-credential security boundary** before AnalystWatch is allowed to implement a Microsoft or Google OAuth callback.

The architectural rule is: **provider token ownership is separate from source configuration and monitoring evidence. Secret material must be authenticated, encrypted, workspace/account bound, persistable without plaintext, and recoverable through an explicit key-rotation contract before any provider callback can store it.**

```text
deployment-held credential keyring
        ↓
AES-256-GCM authenticated envelopes
        ↓
ProviderCredentialRecord
        ↓
Memory / SQLite / PostgreSQL CredentialStore
        ↓
future OAuth callback / refresh / revoke
        ↓
existing Microsoft / Google connector authorization
        ↓
existing source preflight / monitoring / Health
```

A second independent path establishes safe authorization-start state:

```text
authenticated workspace/user initiates future connect
        ↓
random state + random PKCE verifier
        ↓
state digest stored, verifier AES-GCM encrypted
        ↓
short-lived bound authorization transaction
        ↓
future callback must consume once
        ↓
state / expiry / metadata / ciphertext authentication
        ↓
only then may code exchange occur
```

v0.28 implements the two security foundations above. It does **not** implement the network callback or provider code exchange.

## Cryptographic envelope

`EncryptedCredentialSecret` contains only:

- version `1`;
- algorithm `AES-256-GCM`;
- bounded `key_id`;
- base64url nonce;
- base64url ciphertext.

The implementation uses `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with:

- 256-bit keys;
- a fresh random 96-bit nonce per encryption;
- authenticated associated data;
- fail-closed `InvalidTag` handling.

Plaintext secret bytes and encryption keys are not serializable model fields.

Malformed base64, invalid nonce length, unknown key IDs and authentication failure map to bounded `CredentialCryptoError` messages that do not include ciphertext or plaintext.

## Provider credential associated data

Provider credential ciphertext is cryptographically bound to:

```text
workspace_id
provider
credential_id
subject_id
secret_kind
version
```

`secret_kind` is constrained to:

```text
access_token
refresh_token
```

This prevents:

- copying encrypted tokens across workspaces;
- copying encrypted tokens across Microsoft/Google providers;
- moving a token to another credential ID;
- changing the stable provider subject/account ID;
- swapping encrypted access and refresh token fields.

All of those mutations alter associated data and therefore fail AES-GCM authentication.

## Credential keyring

`CredentialKeyring` receives deployment-supplied key bytes and one `active_key_id`.

Rules:

- at least one key is required;
- every key must be exactly 32 bytes;
- key IDs are bounded, non-empty and trimmed;
- the active key must exist in the keyring;
- new encryption always uses the active key;
- decryption may use any retained key ID;
- re-encryption decrypts an old envelope and encrypts a new envelope using the active key.

This gives AnalystWatch an explicit rolling-key contract: retain old keys only for the intended migration/recovery window, re-encrypt records, then retire the old key after verification.

v0.28 does not claim external KMS/HSM integration. The application-level keyring is designed so a deployment can later source key bytes from a stronger secret/KMS layer without changing credential record format.

## Deployment key loading

`load_credential_keyring(...)` reads only:

```text
ANALYSTWATCH_CREDENTIAL_KEYS_JSON
ANALYSTWATCH_CREDENTIAL_ACTIVE_KEY_ID
```

The JSON value is a bounded object mapping key IDs to base64url-encoded 32-byte key material.

Runtime configuration fails closed for:

- missing active key ID;
- untrimmed active key ID;
- missing/blank keyring JSON;
- malformed JSON;
- non-object/empty JSON;
- too many keys;
- non-string key IDs/values;
- malformed base64url;
- non-256-bit decoded keys;
- active key absent from the decoded keyring.

Configuration errors never echo supplied key material.

## ProviderCredentialRecord

The encrypted credential domain record contains:

- `credential_id`;
- `workspace_id`;
- provider;
- stable provider `subject_id`;
- optional display name/email;
- normalized unique scopes;
- encrypted access token;
- optional encrypted refresh token;
- optional access-token expiry;
- created/updated/revoked timestamps.

All timestamps are timezone-aware. Identity/scopes are bounded and trimmed.

The record is deliberately independent from `MonitoringConfig`. A source should eventually reference a credential identity; it must never embed plaintext provider token material.

## Replacement and revocation invariants

All credential-store implementations share the same replacement validation:

1. Provider/account (`provider`, `subject_id`) cannot change under ordinary upsert.
2. `created_at` is immutable.
3. An update older than the stored `updated_at` is rejected.
4. A revoked credential cannot be silently reactivated by writing `revoked_at=None`.
5. Revocation timestamps must be timezone-aware and cannot precede the latest credential update.
6. Unsealing any secret from a revoked record fails closed.

Provider/account switching therefore requires a future explicit account-switch workflow rather than an accidental refresh/reconnect overwrite.

## CredentialStore protocol

The protocol exposes:

```text
initialize
upsert
get(workspace, credential)
list(workspace)
revoke(workspace, credential, revoked_at)
```

Implementations in v0.28:

- `MemoryCredentialStore`;
- `SQLiteCredentialStore`;
- `PostgresCredentialStore`.

All reads are workspace scoped.

## SQLite persistence

SQLite credential persistence is intentionally separate from monitoring state semantics.

Table:

```text
provider_credentials
  workspace_id
  credential_id
  record_json
  PRIMARY KEY(workspace_id, credential_id)
```

`record_json` is the serialized `ProviderCredentialRecord`; token fields inside it are encrypted envelopes.

Existing-record update/revoke flows start `BEGIN IMMEDIATE`, read the current row, apply the shared replacement/revocation invariant, then update the encrypted record.

Tests close and reopen the database to prove persistence and inspect raw `record_json` to verify known test access/refresh plaintext values are absent.

## PostgreSQL persistence

PostgreSQL creates `provider_credentials` inside the existing AnalystWatch PostgreSQL schema and stores `record_json` as JSONB.

For upsert:

- the implementation first attempts create-only insertion;
- if a row already exists, it reads that row with `FOR UPDATE`;
- the shared replacement invariant is applied against the locked row;
- only then is JSONB replaced.

Revocation likewise locks the existing row before deriving/writing the revoked record.

This prevents concurrent updates from bypassing the account/provider/stale-update rules.

Tests run against PostgreSQL 16 in CI, reopen the store, exercise update/revoke/workspace isolation, and inspect raw JSONB to prove test token plaintext is absent.

## OAuth authorization transaction

`OAuthAuthorizationTransaction` is a provider-neutral precursor to an actual authorization-code callback.

Bound metadata:

- transaction ID;
- workspace;
- initiating user ID;
- provider;
- target credential ID;
- state SHA-256 digest;
- encrypted PKCE verifier;
- created timestamp;
- expiry timestamp;
- optional consumed timestamp.

The transaction is deliberately not a provider credential and does not contain an authorization code or provider token.

## Authorization start

`begin_authorization_transaction(...)`:

1. validates workspace/user/provider/credential and timezone-aware time;
2. enforces a bounded TTL (default 10 minutes, maximum 15);
3. generates a random transaction ID;
4. generates a random 32-byte state value;
5. stores only a SHA-256 base64url digest of state;
6. generates a random 32-byte PKCE verifier;
7. derives the S256 PKCE code challenge;
8. encrypts the PKCE verifier with the credential keyring.

PKCE verifier associated data binds:

```text
workspace_id
user_id
provider
credential_id
transaction_id
purpose = oauth_pkce_verifier
version
```

The plaintext state and plaintext verifier are returned only in the start result needed by the future initiating request. Neither is a persisted model field.

## Authorization consume

`consume_authorization_transaction(...)` performs a strict order:

1. require timezone-aware current time;
2. revalidate the entire transaction model from raw attributes;
3. reject consumed transactions;
4. reject expiry;
5. reject invalid state shape;
6. SHA-256 the presented state and compare with `hmac.compare_digest`;
7. reconstruct bound PKCE associated data;
8. authenticate/decrypt the verifier;
9. return a consumed transaction plus non-repr plaintext verifier.

Revalidation is important because defensive tests deliberately use Pydantic `model_copy(update=...)`, which can bypass normal field validation. Valid-but-modified metadata is normalized and reaches AES-GCM authentication, where it fails because associated data changed. Structurally invalid copied metadata becomes one bounded `Authorization transaction metadata is invalid` error.

State, verifier and attacker-controlled invalid metadata are not echoed in error text.

## Replay and persistence boundary

The pure transaction primitive proves one-time consumption semantics on a transaction object, but v0.28 does not yet provide a persistent authorization-transaction repository or an atomic database claim operation.

Therefore the future HTTP callback milestone must add persistence/atomic consumption before a real redirect/callback is exposed. A callback must never rely on only a browser-held transaction object.

This is an explicit release boundary, not an omitted claim.

## Existing v0.27 credential lifecycle

v0.27 fixed-environment credential diagnostics remain unchanged:

- provider reachability;
- provider account identity;
- deterministic `needs_credential` / `rejected` / `unavailable` / `identity_unverified` / `verified` lifecycle;
- `configure` / `reconnect` / `retry` / `review_scopes` / `none` guidance;
- Operator-only Microsoft/Google connection endpoints;
- Add Source test/status/identity and resource browsing.

v0.28 does not yet route those connection operations through `CredentialStore`.

## Monitoring and Health boundary

Credential encryption/persistence/authorization transaction state cannot emit or alter source Healthy / Warning / Critical classification.

v0.28 does not change:

- source ingestion;
- detectors or Data Rules;
- baselines/reviews;
- incidents;
- scorecards;
- notifications/delivery/reconciliation;
- dependencies/blast radius;
- monitoring observation persistence.

Provider credentials are operational security state, not monitoring evidence.

## Static Pages boundary

GitHub Pages remains read-only monitoring output.

Static output receives no:

- provider token ciphertext;
- provider credential metadata;
- provider account identity from credential records;
- credential key IDs;
- OAuth transaction state digest;
- PKCE ciphertext/verifier;
- connect/reconnect/revoke controls.

## Verification

Verified v0.28 checkpoints:

- AES-GCM/key-rotation foundation `eeda29a039a5a9e7bf4047154aba50a759dc91f5`: CI #691, **358 passed / 1 warning**;
- account/secret-bound encrypted credential model + MemoryStore `61ed8d8dd3c4ec08c38722ff8dc54f8e438a7aa4`: CI #701, **367 passed / 1 warning**;
- SQLite/PostgreSQL encrypted persistence `fc8acb4bec299c5083aee466528bd8502645128d`: CI #707, **372 passed / 1 warning**;
- deployment key loading + hardened state/PKCE transaction foundation `1ee8b3cec44a5b845024fdff396b6c8ee094fe2e`: CI #725, **383 passed / 1 warning**.

All exact green checkpoints passed Ruff, compile/import checks and the PostgreSQL 16-backed suite.

## Release boundary

Product v0.28 is complete when package/FastAPI/module versions are aligned to `0.28.0`, README/milestones/architecture are aligned, and the exact release head passes the full repository gate.

The next milestone owns the first real provider OAuth flow. It must add persistent/atomic authorization transaction consumption, provider configuration, authorization redirects, callback/code exchange, account verification, encrypted credential write, refresh/reconnect/revoke and integration with existing connector authorization.
