# AnalystWatch Product v0.30 Architecture

## Decision

Product v0.30 binds monitored Microsoft 365 Excel and Google Sheets sources to the encrypted OAuth credentials established by the v0.28/v0.29 security runtime.

The architectural rule is:

> **source credential ownership must be explicit, workspace-bound and identical between preflight and monitoring. A configured stored credential may never silently fall back to another account.**

```text
SourceDefinition
        ↓
optional explicit credential_id
        ↓
MonitorService source credential resolver
        ↓
workspace-bound CredentialStore
        ↓
provider / revocation / expiry validation
        ↓
AES-256-GCM access-token decrypt in memory
        ↓
existing Microsoft / Google reader
        ↓
existing profile + detector + Data Rule pipeline
        ↓
Observation / Health / incident
```

No alternate detector, Health or monitoring-state path is introduced.

## v0.29 foundation retained

Product v0.29 already provides:

- fixed provider OAuth configuration;
- one-time state + PKCE authorization transactions;
- Memory/SQLite/PostgreSQL authorization stores;
- bounded callback consumption and code exchange;
- provider identity verification before credential persistence;
- AES-256-GCM `ProviderCredentialRecord` storage;
- Memory/SQLite/PostgreSQL credential stores;
- stored-credential preference for connection check, identity, lifecycle and resource browsing;
- fail-closed behavior when an existing stored connection credential is unusable.

v0.30 does not replace that runtime. It reuses its credential stores and encrypted record contract for monitored-source ingestion.

## Source contract

`MonitoringConfig` gains:

```text
credential_id: str | None
```

The binding is deliberately optional to preserve existing environment-backed sources.

A `SourceDefinition` with `credential_id` is valid only for:

```text
microsoft_excel
google_sheets
```

A source cannot configure both:

```text
credential_id
request_header_env
```

This is a fail-closed ownership rule rather than a convenience restriction. Allowing both would make it ambiguous which provider account is authoritative for preflight and scheduled monitoring.

Generic `api` sources remain on the established request-header contract in v0.30.

## Resolver contract

`SourceCredentialResolver` is intentionally narrow:

```text
resolve(SourceDefinition) -> Authorization headers | None
```

`StoredSourceCredentialResolver` validates the bound credential before returning an in-memory bearer header.

Validation includes:

1. source workspace equals resolver workspace;
2. source type maps to the expected provider;
3. credential record exists;
4. stored provider matches source provider;
5. credential is not revoked;
6. access-token expiry is known and remains in the future;
7. deployment credential keyring loads successfully;
8. authenticated decryption succeeds.

Failure returns bounded operational evidence through the existing ingestion/preflight path. Token/key plaintext is never copied into source or observation persistence.

## Runtime store binding

The resolver is derived from the monitoring store already selected by runtime configuration.

### SQLite / legacy runtime

For a workspace-bound SQLite monitoring store at:

```text
instance/analystwatch.db
```

the existing OAuth credential sidecar remains:

```text
instance/analystwatch.db.credentials.db
```

v0.30 resolves that same sidecar rather than creating a second credential database.

### PostgreSQL runtime

A workspace-bound `PostgresStorage` exposes the managed DSN already used by AnalystWatch. v0.30 constructs the existing `PostgresCredentialStore` on that DSN and resolves credentials only inside the monitoring workspace.

No monitoring schema migration is required for `credential_id` because source configuration is already serialized through the existing source-definition contract.

## Ingestion integration

The lower-level Microsoft/Google readers already accept concrete request headers. v0.30 therefore adds credential resolution immediately above that existing boundary rather than modifying provider readers or detector logic.

`ingest_source(...)` now accepts an optional resolver.

Selection is deterministic:

```text
credential_id absent
    → existing request_header_env behavior

credential_id present
    → stored credential resolver only
    → no environment fallback
```

For Microsoft/Google readers the resulting bearer authorization is passed through their existing `headers=` argument.

## One resolver for preflight and monitoring

`MonitorService` owns the resolver. The service passes it to both:

```text
preflight_source(...)
check_source(...)
```

Inherited service workflows therefore use the same credential path for:

- preflight;
- onboarding;
- source update preflight;
- manual check;
- check-all;
- check-due / scheduled execution.

This prevents the unsafe state where onboarding succeeds with one account while scheduled monitoring silently reads from another.

## Failure semantics

A stored-binding failure is source availability evidence, not OAuth Health state.

Examples:

- credential missing;
- wrong provider;
- revoked credential;
- unknown expiry;
- expired access token;
- unavailable deployment key;
- authenticated-decryption failure.

During normal monitoring those failures flow through the existing source availability detector and can result in Critical source Health for the same reason any unreadable required source can. v0.30 does not add a special credential Health classification.

During preflight the same failures reject readiness before source onboarding/update acceptance.

## No secret leakage

Credential plaintext exists only long enough to construct the provider request header in memory.

Regression coverage proves known token values are absent from:

- serialized preflight results;
- serialized observations;
- source definitions;
- public/static monitoring output.

The persisted credential remains the encrypted v0.28/v0.29 record.

## Backward compatibility

Existing Microsoft/Google source definitions without `credential_id` continue to use `request_header_env` unchanged.

Existing CSV/XLSX/JSON/API source behavior is unchanged.

Existing detector thresholds, Data Rules, row-diff behavior, baseline/review semantics, incidents, notifications, scorecards, dependency graph and monitoring storage remain unchanged.

## Live-source gate correction

During v0.30 verification the existing `Live source smoke` workflow failed because later-added static local demo fixtures had fixed August 21 sample dates with short freshness expectations. The real Bank of Canada and U.S. Treasury API sources were Healthy.

Repository history confirmed the smoke gate was introduced specifically to validate real public sources before those static demos existed.

The repair was isolated in its own PR and changed only `scripts/live_source_smoke.py` so the workflow checks enabled generic API sources. Demo configuration, sample data, freshness contracts and detector behavior were not changed.

That repair was independently green before merge:

- CI #817: success;
- Live source smoke #104: success.

## Verification

Frozen v0.30 functional checkpoint:

```text
f02e4cd34028f744f448bc37f8361d6bc29d28e6
```

Verified:

- Ruff: success;
- compile/import: success;
- PostgreSQL 16-backed suite: **451 passed, 1 warning**;
- CI #828: success;
- Live source smoke #106: success;
- Microsoft stored credential reaches preflight provider reads;
- Google stored credential reaches monitored provider reads;
- missing/expired stored credentials fail before network access and do not fall back to environment authorization;
- SQLite legacy runtime uses the existing `.credentials.db` sidecar;
- PostgreSQL runtime uses the existing workspace-bound `PostgresCredentialStore`;
- token values are absent from serialized monitoring evidence.

The warning remains the existing Starlette TestClient/httpx deprecation warning.

No real Microsoft/Google OAuth application credentials or tenant authorization were supplied, so external provider side effects are not claimed.

## Explicit non-goals

Product v0.30 does not implement:

- refresh-token network rotation;
- reconnect/account-switch workflow;
- provider-side revoke;
- visible Add Source connect-control binding;
- generic REST API stored-OAuth binding;
- production KMS/HSM infrastructure;
- new source Health/detector semantics.

## Next milestone

The next controlled milestone should implement credential lifecycle operations:

1. refresh expired/near-expiry access tokens through fixed provider endpoints;
2. atomically replace encrypted token/expiry metadata under the existing provider/account identity;
3. preserve refresh concurrency/idempotency safety;
4. make reconnect/account switch explicit rather than overwrite-oriented;
5. implement provider revoke where supported;
6. only then wire the visible Add Source connection control directly into stored source binding;
7. perform a managed-PostgreSQL pilot with real provider credentials and failure drills.

AI investigation remains downstream of deterministic evidence and must never redefine Health.
