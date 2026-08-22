# AnalystWatch Core v0.16 Architecture

## Decision

Core v0.16 extends the verified v0.15 security boundary in two controlled directions: managed-runtime readiness and the first live email delivery adapter. It does not change deterministic detector logic, incident derivation, notification-candidate eligibility or the established delivery-attempt lifecycle.

The architecture keeps infrastructure readiness and external side effects separable so neither can be inferred from the other.

## Managed runtime boundary

`managed_runtime.py` defines an environment-backed deployment contract for:

- managed PostgreSQL DSN;
- bound workspace;
- signed-bearer authentication secret;
- trusted bootstrap Admin principal;
- Resend API key;
- sender and recipients;
- public application base URL.

Secrets are consumed at runtime and are not written to repository configuration, monitoring state or public Pages output.

`prepare_managed_runtime(...)` performs the startup sequence:

1. construct workspace-bound `PostgresStorage`;
2. initialize the AnalystWatch PostgreSQL schema;
3. initialize `PostgresMembershipStore`;
4. look up the configured bootstrap principal;
5. create that principal as Admin only when absent;
6. refuse startup if that existing principal is not Admin;
7. verify AnalystWatch PostgreSQL schema/storage identity;
8. return non-secret readiness counts.

This is the trusted first-Admin provisioning path promised by v0.15. No unauthenticated web bootstrap endpoint is introduced.

## Managed PostgreSQL validation

A dedicated external managed PostgreSQL validation project was provisioned for v0.16 without changing the hosted GitHub runtime.

The validation environment contains the same AnalystWatch PostgreSQL schema-v1 contract used in CI, including monitoring state, delivery attempts and workspace memberships. Schema version and persistent storage identity were verified after initialization.

### Recovery rehearsal

Recovery was tested on an isolated managed-database branch:

1. clone the validation database state;
2. verify storage identity, validation source and Admin membership on the clone;
3. deliberately remove validation state from the clone;
4. confirm the clone is degraded;
5. reset the clone from its parent state;
6. verify the original storage identity, source and Admin membership are restored;
7. delete the temporary recovery branches.

The primary validation branch was not damaged during this test. This proves provider recovery mechanics for the validation environment; it is not evidence that the GitHub-hosted application has been cut over to managed PostgreSQL.

## Delivery mode extension

`DeliveryMode` now contains:

```text
dry-run | live
```

The existing dry-run path is preserved unchanged. Live email delivery reuses the existing persistence contract rather than introducing a second notification state machine.

## Resend email adapter

`email_delivery.py` adds `ResendEmailAdapter` and `EmailDestination`.

A live email operation resolves the existing candidate, source and observation and then calls the existing atomic `claim_delivery_attempt(...)` storage operation. Only an Eligible candidate can therefore be attempted.

The provider request carries the same AnalystWatch idempotency key in the Resend `Idempotency-Key` header.

### State ordering

The existing storage claim creates a Prepared attempt. Before network I/O, the attempt is updated to `DeliveryMode.LIVE`. This means persisted state records that an external side effect was about to occur before the provider is contacted.

### Outcome handling

Provider acceptance:

```text
Prepared/live → Succeeded/live
```

with a non-secret provider message-ID summary.

Definitive HTTP/provider rejection:

```text
Prepared/live → Failed/live
```

Transport uncertainty:

```text
Prepared/live → Prepared/live
```

The last case is intentional. A timeout or connection failure can happen after a provider accepted the request, so AnalystWatch does not blindly mark the attempt Failed and allow a duplicate retry. Existing explicit reconciliation remains required.

Same-key replay returns the stored attempt without a second provider request.

## Email content

The first email template remains intentionally simple and analyst-oriented. It includes source/workspace, transition, severity, observed time, candidate reason, deterministic findings, likely impact, suggested investigation and a source-detail link.

It does not include API credentials, PostgreSQL DSNs, authorization headers or idempotency keys.

## Verification boundary

Core v0.16 has three distinct evidence levels:

1. **deterministic provider integration tests** — mocked HTTP verifies request shape, idempotency, success/rejection/uncertainty behavior and secret redaction;
2. **managed PostgreSQL validation** — an external managed database and isolated recovery rehearsal prove infrastructure/storage mechanics;
3. **real email side effect** — requires a real Resend credential, verified sender and provider acceptance. This is not claimed merely from mocked tests.

The v0.16 functional checkpoint passed Ruff, compile, **164 tests** against PostgreSQL 16 CI, and live-source smoke.

## Hosted compatibility

The existing GitHub Pages monitor remains legacy SQLite and local auth. No production PostgreSQL DSN, signed-bearer deployment secret or email provider secret is added to that workflow by v0.16.

A future production deployment must explicitly configure managed runtime values and should retain a rollback path until the managed application deployment itself has been verified.

## Next architecture step

Product v0.17 should add the SharePoint / OneDrive Excel connector through the existing ingestion/profile/detector pipeline. Microsoft authentication and workbook/table selection should remain connector concerns; they must not fork the deterministic health/incident architecture.
