# AnalystWatch

**Reliability monitoring for analyst-owned data and reporting workflows.**

AnalystWatch monitors analyst-owned data inputs for silent reliability failures, explains the evidence behind trust changes, shows downstream reporting exposure, and keeps ambiguous delivery outcomes visible until an operator resolves them.

The product question is: **can I trust the data feeding this analysis or report today, what has been happening recently, what is affected if I cannot, and are any delivery outcomes still operationally unresolved?**

## Product v0.24 status

Product v0.24 adds **deterministic reliability scorecards + trust badges** over the observation evidence AnalystWatch already stores.

The release deliberately does **not** create a new reliability classifier or opaque numeric score. The badge is a presentation of the current source Health only:

- no eligible observation → `Not monitored`;
- `Healthy` → `Trusted`;
- `Warning` → `Attention`;
- `Critical` → `Critical`.

Historical metrics explain recent reliability but cannot override or recalculate Healthy / Warning / Critical.

## Explainable 7-day and 30-day scorecards

Each source scorecard exposes explicit 7-day and 30-day windows with:

- check count;
- successful-check count and percentage, using the existing AnalystWatch definition of a usable observation (`available` plus a profile);
- Healthy-check count and percentage;
- Warning and Critical counts;
- incident openings and recoveries derived through the existing incident-transition logic;
- stale-occurrence count, measured once per observation;
- Data Rule failure-occurrence count, measured once per observation;
- mean time to recovery (MTTR) when the incident start is actually known.

There is no `94/100`-style composite reliability score. Every displayed metric can be traced directly to stored observations, deterministic findings or existing incident transitions.

## Bounded history and claim safety

Scorecard history is loaded adaptively from the source's configured monitoring cadence instead of assuming a fixed observation count represents 30 days.

The scorecard service expands the history window until it has enough pre-window Healthy context to establish incident boundaries, or until a safety cap is reached. The default cap is 50,000 observations per scorecard evaluation.

If the cap is reached before enough earlier context is available:

- `history_complete` is false;
- the UI explicitly labels the history partial;
- the first visible unhealthy observation is not fabricated into a known incident opening;
- recovery can still be counted when observed;
- MTTR remains unavailable when the actual opening time is unknown.

## API and downstream context

`GET /api/sources/{source_id}/scorecard` returns:

- the deterministic `ReliabilityScorecard`;
- a bounded downstream-impact summary containing only total count and counts by asset kind.

Downstream asset names, identifiers, report names and URLs are not returned by this scorecard endpoint. Blast radius is contextual evidence only and cannot influence the trust badge or source Health.

## Analyst UI and public Pages parity

The existing source-detail layout now includes a compact **Reliability Scorecard** between the source summary and the established detail layout.

The panel shows the trust badge plus 7-day / 30-day evidence for Healthy %, successful %, incidents, stale occurrences, Data Rule failure occurrences and MTTR. Existing finding, row-change, history, incident, review, dependency and monitoring-contract layouts remain unchanged.

The same aggregate scorecard is rendered into read-only GitHub Pages and serialized in public `state.json`.

Product v0.23's selective Data Rule privacy boundary remains in force. Public scorecards may report that a Data Rule failure occurred, but they do not publish the private rule ID/name, referenced field, allowed values/bounds, custom guidance or failing row values.

## Product v0.23 foundation retained

Product v0.24 preserves deterministic Data Rules from v0.23:

- `not_null`;
- `allowed_values`;
- `numeric_range`;
- `row_count_range`.

Data Rules still enter the existing source `Finding` pipeline before the single `health_from_findings(...)` boundary. They do not have their own Health, incident or persistence state machine.

## Source connectors

Existing source connectors remain unchanged by Product v0.24:

- CSV;
- XLSX;
- JSON;
- REST API;
- Microsoft 365 SharePoint / OneDrive Excel tables through Microsoft Graph delegated access;
- Google Sheets ranges through Google Sheets API v4.

Credentials remain environment-backed where configured and provider-specific public identifiers continue to follow the existing Pages-redaction rules.

No new live-tenant claim is implied by Product v0.24. A provider path is only considered externally verified when corresponding credentials and side effects were actually exercised.

## Existing product foundation

Product v0.24 preserves the previously verified architecture, including:

- deterministic ingestion, profiling, source detectors and Data Rules;
- mandatory source preflight and guarded onboarding;
- Healthy-history references, freshness evidence and guarded baseline promotion/review;
- incident lifecycle and notification policy;
- dry-run/live delivery attempt state, idempotency, retry and explicit reconciliation;
- workspace-aware SQLite/namespaced/PostgreSQL persistence;
- Viewer / Operator / Admin authorization;
- bounded key-level row change analysis;
- Power BI Guard trust correlation;
- dependency mapping and deterministic blast radius;
- Microsoft Teams Workflows delivery architecture;
- Delivery Ops reconciliation monitoring;
- Google Sheets and Microsoft 365 Excel connector boundaries;
- read-only GitHub Pages monitoring snapshots.

## Verification

The Product v0.24 functional/UI/static checkpoint `4fc6e6126391da630a635b2ea9c04cfc7890d6fe` passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed test suite;
- **275 passed, 1 warning**.

Coverage includes badge/Health mapping, 7-day and 30-day metrics, inclusive time boundaries, incident/recovery/MTTR derivation, stale/Data Rule occurrence counting, future-observation exclusion, adaptive history loading, incomplete-history claim safety, bounded downstream API context, authenticated source-detail rendering, static Pages/state parity, and Data Rule privacy regression coverage.

Release-only metadata and documentation changes are gated again on their exact head before merge.

## Next milestone

Product v0.25 is **preconfigured source packs**: reusable analyst-facing presets that populate existing keys, freshness contracts, row-comparison settings and deterministic Data Rules for common reporting workflows.

After v0.25, priority shifts toward self-service Microsoft/Google connection UX, credential lifecycle and real hosted pilot validation rather than connector accumulation.

AI investigation remains downstream of deterministic evidence and must not redefine Health classification.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/MILESTONES.md`](docs/MILESTONES.md).
