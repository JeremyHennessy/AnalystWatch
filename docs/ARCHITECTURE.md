# AnalystWatch Product v0.21 Architecture

## Decision

Product v0.21 adds an **operational reconciliation monitor** over the verified Product v0.20 delivery-attempt architecture.

The key architectural choice is deliberately conservative: **the monitor derives its queue from existing `Prepared` delivery attempts. It does not create another notification/delivery state machine or persistence schema.**

```text
eligible notification candidate
        ↓
existing atomic delivery claim + idempotency
        ↓
provider adapter
        ↓
Succeeded / Failed / Prepared
                    ↓
              Prepared only
                    ↓
bounded reconciliation queue
                    ↓
external evidence + Operator decision
                    ↓
existing reconcile_delivery_attempt(...)
                    ↓
Succeeded or Failed
```

A `Prepared` attempt continues to mean that AnalystWatch cannot safely assert whether the external side effect happened. Product v0.21 makes that ambiguity visible; it does not guess it away.

## Preserved v0.20 boundaries

The verified Product v0.20 architecture remains intact:

- Microsoft Teams Workflows / Power Automate delivery reuses the existing candidate and delivery-attempt state machine;
- explicit provider rejection records `Failed`;
- successful provider acceptance records `Succeeded`;
- ambiguous transport outcome remains `Prepared` for explicit reconciliation;
- same-key idempotency prevents duplicate external POSTs;
- dependency mapping remains a separate workspace-scoped graph;
- Power BI Guard remains a separate deterministic dashboard-trust result;
- source Health, detector thresholds, baselines and incident semantics are unchanged.

Product v0.20 was merged from its verified release head into `main` at `5ec4744826dafa737931bde89733ee277bbf08ef`.

## Reconciliation queue model

`reconciliation.py` defines a derived operational view:

- `DeliveryReconciliationQueueItem`;
- `DeliveryReconciliationQueue`;
- `build_delivery_reconciliation_queue(...)`.

The queue scans existing `MonitoringStore` delivery-attempt history and selects only attempts whose current state is `Prepared`.

No queue record is persisted. Re-running the builder reflects the current authoritative delivery-attempt state.

### Deterministic age/staleness

Defaults:

- stale after 30 minutes;
- scan at most 5,000 delivery attempts;
- return/display at most 100 Prepared attempts;
- oldest unresolved attempts first.

Age is computed against an explicit/current UTC time. Future-dated attempts are conservatively clamped to zero minutes of age rather than producing a negative operational duration.

### Bounded completeness evidence

The queue makes two limits independently visible:

- `scan_limit_reached` — the storage scan reached its configured cap;
- `item_limit_reached` — more Prepared attempts were found in that scan than the output can display/return.

These fields have different meanings.

If `scan_limit_reached` is true, AnalystWatch does **not** claim the Prepared count is exhaustive across all delivery history. The count describes the bounded scan only.

If `item_limit_reached` is true, the total Prepared count within the scan remains available while the queue returns the oldest limited subset.

This avoids turning bounded storage APIs into an unsupported completeness claim.

## Queue privacy / evidence boundary

The operational queue intentionally exposes only what an analyst needs to identify and prioritize an unresolved attempt:

- attempt ID;
- candidate ID;
- source ID and source name;
- adapter and delivery mode;
- creation time;
- unresolved age;
- stale flag;
- candidate transition/current Health when available.

The queue model deliberately excludes:

- caller idempotency key;
- claim owner;
- provider result summary;
- provider error detail;
- reconciliation note;
- provider secret/configuration values.

Those fields remain in their existing authoritative storage/audit boundaries and are not copied into the queue API/view.

## Reconciliation web/API boundary

`reconciliation_web.py` registers:

- `GET /reconciliation`;
- `GET /api/delivery-reconciliation`;
- `POST /reconciliation/{attempt_id}/resolve`.

The page and read API call the same queue builder.

Read parameters are bounded:

- stale threshold: 1 to 10,080 minutes;
- API item limit: 1 to 500.

The underlying scan cap remains the conservative product default unless the internal contract is deliberately changed later.

### UI resolution form

The UI resolution action is intentionally narrow:

- accepts `application/x-www-form-urlencoded` only;
- maximum body size is 4,096 bytes;
- requires exactly one `outcome` field;
- requires exactly one `note` field;
- evidence note maximum length is 2,000 characters;
- outcome must be the existing `DeliveryReconciliationOutcome` enum.

This uses standard-library URL-encoded parsing instead of introducing another form/multipart dependency solely for this action.

After validation the route delegates to the existing `MonitorService.reconcile_delivery_attempt(...)` domain operation. The web layer does not implement a second reconciliation transition.

Unknown attempt → 404. Invalid state transition → 409. Invalid form → 400/415/413 depending on the failure boundary.

## Authenticated reviewer attribution

Product v0.21 tightens the audit boundary for both reconciliation entry points:

- UI `/reconciliation/{attempt_id}/resolve`;
- existing API `/api/delivery-attempts/{attempt_id}/reconcile`.

When signed-bearer authentication is active, the authenticated principal's user ID is passed as `reviewer` and stored in the existing `reconciled_by` field.

In local/no-auth mode the service retains the established execution-owner fallback behavior.

Authorization remains centralized in `web_auth.py`:

- Viewer → reconciliation page/API reads;
- Operator → UI/API reconciliation actions;
- unclassified mutations → Admin by fail-closed default.

## Retry safety

Reconciliation is not retry execution.

When an operator resolves a `Prepared` attempt to `Failed`:

1. the existing attempt is updated to `Failed`;
2. it disappears from the derived Prepared queue;
3. no new delivery attempt is created;
4. existing retry policy controls whether and when a subsequent claim is permitted.

When an operator resolves to `Succeeded`, the attempt becomes terminally successful and leaves the queue.

Product v0.21 does not poll a provider and infer the outcome automatically. Provider-specific reconciliation automation can be considered later only if it can produce durable, trustworthy evidence without weakening the current ambiguity model.

## Analyst-facing Delivery Ops surface

`reconciliation.html` reuses the existing AnalystWatch visual system and the existing form styles. No UI/CSS redesign was introduced.

The view shows:

- total Prepared attempts found in the bounded scan;
- stale count;
- stale threshold;
- scan cap and whether it was reached;
- explicit display-limit warning when applicable;
- oldest unresolved items first;
- source, adapter/mode, attempt ID, age, transition and current Health context;
- required evidence note;
- explicit Confirm failed / Confirm succeeded actions;
- safety copy explaining that Prepared is not success/failure and retry remains blocked.

Dynamic navigation adds **Delivery Ops** to the workspace overview, Power BI Guard and Dependency Map surfaces.

## Public/static boundary

The public GitHub Pages build remains a read-only source-monitoring snapshot.

It does not fabricate:

- Teams delivery configuration or outcomes;
- Power BI tenant evidence;
- dynamic dependency graph state;
- reconciliation queue state.

The workspace overview therefore includes the Delivery Ops navigation link only in dynamic mode. Static Pages retain the existing public navigation boundary.

## Existing Product v0.20 architecture retained

### Microsoft Teams delivery

`teams_delivery.py` remains the provider adapter boundary. Notification eligibility, atomic claim, idempotency, retry timing and reconciliation state remain owned by the existing monitoring storage/service contract.

Runtime configuration remains environment-backed:

- `ANALYSTWATCH_TEAMS_WORKFLOW_WEBHOOK_URL`;
- `ANALYSTWATCH_PUBLIC_BASE_URL`.

The implementation targets Microsoft Teams Workflows / Power Automate rather than the retired Office 365 Connector model.

### Dependency graph

`dependencies.py`, `dependency_service.py`, `dependency_storage.py` and `dependency_web.py` remain the lightweight impact-intelligence boundary for Source / Workbook / Semantic Model / Report / Custom assets.

Blast-radius traversal remains deterministic, cycle safe and deduplicated by asset key. Discovered Power BI edges remain namespaced per Guard and never remove explicit edges.

### Power BI Guard

Power BI Guard continues to correlate semantic-model refresh evidence with existing AnalystWatch source Health without mutating that upstream Health.

Important cases remain:

```text
refresh Completed + upstream all Healthy
→ Healthy

refresh Completed + any upstream Critical
→ Critical

refresh Completed + any upstream Warning/unobserved
→ Warning

refresh Failed / Cancelled / Disabled
→ Critical

refresh InProgress / NotStarted / unknown / no history
→ trust unconfirmed (Warning)
```

No real Power BI tenant access is claimed without a real credential.

## Preserved behavior

Product v0.21 does not change:

- CSV/XLSX/JSON/API/Microsoft Excel ingestion;
- source detector thresholds;
- source Healthy / Warning / Critical classification;
- source baseline promotion or review;
- row-level comparison semantics/retention;
- source incident lifecycle;
- notification candidate policy;
- delivery attempt Prepared/Succeeded/Failed semantics;
- atomic claim/idempotency semantics;
- delivery retry timing;
- live-email or Teams adapter behavior;
- dependency storage/traversal semantics;
- Power BI Guard trust correlation;
- source scheduler;
- existing public Pages source-state policy.

## Verification

The verified Product v0.21 functional checkpoint passed **225 tests**, Ruff and compile/import checks against PostgreSQL 16 CI.

Coverage includes:

- Prepared-only queue derivation;
- stale threshold and oldest-first ordering;
- safe queue serialization;
- bounded scan/output evidence;
- reconciliation removal from the queue without automatic retry creation;
- reconciliation page/API output;
- required evidence-note and form-boundary validation;
- Viewer/Operator authorization classification;
- authenticated `reconciled_by` attribution on UI and existing API reconciliation paths;
- all existing Product v0.20 Teams/dependency/Power BI/source-monitoring regressions.

A real Teams Workflows webhook was not supplied in this repository session, so a real Teams side effect remains unverified.

A real Power BI tenant credential was not supplied, so live Microsoft tenant access remains unverified.

## Next architecture step

Product v0.22 should add a Google Sheets connector through the existing ingestion/preflight/onboarding contracts rather than creating a parallel monitoring architecture.
