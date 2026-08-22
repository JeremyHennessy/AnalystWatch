# AnalystWatch Product v0.24 Architecture

## Decision

Product v0.24 derives an explainable reliability scorecard from existing source observations without introducing a second Health classifier.

The architectural rule is: **current Health remains authoritative; the trust badge mirrors it and historical scorecard metrics only explain recent reliability.**

```text
existing Observation history
        ↓
existing Health + Finding evidence
        ↓
existing incident_transition(...)
        ↓
ReliabilityScorecardService
        ↓
ReliabilityScorecard
        ├── current trust badge
        ├── 7-day evidence
        └── 30-day evidence
```

No scorecard-specific persistence, incident state machine, detector threshold or Health derivation is introduced.

## Trust badge boundary

`TrustBadge` is intentionally deterministic and non-numeric:

- no eligible observation → `Not monitored`;
- current `Healthy` → `Trusted`;
- current `Warning` → `Attention`;
- current `Critical` → `Critical`.

Historical reliability cannot upgrade or downgrade the badge. Downstream blast radius cannot upgrade or downgrade the badge. There is no weighted or opaque reliability score.

## Reliability windows

`ReliabilityScorecard` contains explicit 7-day and 30-day `ReliabilityWindow` objects.

Each window contains:

- `check_count`;
- `successful_check_count` and `successful_check_pct`;
- `healthy_count` and `healthy_check_pct`;
- `warning_count`;
- `critical_count`;
- `incident_count`;
- `recovered_incident_count`;
- `stale_occurrence_count`;
- `data_rule_failure_occurrence_count`;
- `mttr_minutes` when recovery duration is actually known.

A successful check reuses the established AnalystWatch usability condition: the observation is available and has a profile.

Stale and Data Rule failures are counted once per observation, not once per individual finding. This keeps the metric interpretable as occurrence frequency rather than detector volume.

## Incident and MTTR boundary

Scorecards reuse the existing `incident_transition(previous, current)` function. They do not implement a second incident model.

For ordered observations:

- a transition into Warning/Critical can produce `Opened`;
- Warning → Critical can produce `Escalated`;
- unhealthy → Healthy can produce `Recovered`;
- MTTR is calculated from a known opening timestamp to a known recovery timestamp.

Incident counts are attributed to the window containing the opening transition. Recoveries are attributed to the window containing the recovery transition.

A recovery can therefore appear in a 7-day window for an incident opened before that window, while the opening still belongs to the 30-day window or earlier.

## Time semantics

Scorecard timestamps must be timezone-aware and are normalized to UTC.

Window boundaries are inclusive:

`as_of - N days <= observed_at <= as_of`

Future observations are excluded from the scorecard at the requested `as_of` time.

Mixed-source observation lists fail closed.

## Adaptive bounded history

A fixed observation limit is not sufficient for a 30-day scorecard because source cadences vary from minutes to days and an incident can begin before the window.

`ReliabilityScorecardService` therefore computes an initial history request from the source's configured `monitor_interval_minutes` and expands the newest-first history when more context is needed.

The service considers incident context complete when:

- the store returns fewer observations than requested, proving no older retained history exists; or
- the oldest eligible visible observation is older than the 30-day cutoff and Healthy, establishing a pre-window non-incident state.

Otherwise the requested history limit doubles until the configured safety cap is reached. The default cap is 50,000 observations.

If the cap is reached before enough earlier context exists, `ReliabilityScorecard.history_complete` is false.

For incomplete history, the first visible unhealthy observation is not fabricated into an `Opened` transition. A later recovery may still be observed, but MTTR stays `None` when the actual opening timestamp is unknown.

This is a claim-safety boundary: the product exposes partial history rather than manufacturing precision.

## Persistence

Product v0.24 adds **no database migration**.

Scorecards are derived on read from existing observations and existing source configuration. The adaptive service requires only:

- `get_source(source_id)`;
- newest-first `list_observations(source_id, limit=...)`.

SQLite, namespaced storage and PostgreSQL therefore reuse their existing observation persistence unchanged.

## API boundary

`GET /api/sources/{source_id}/scorecard` returns:

```text
ReliabilityScorecardResponse
  scorecard: ReliabilityScorecard
  downstream_impact:
    total: int
    counts: dict[asset_kind, int]
```

The downstream summary deliberately contains counts only. The scorecard route does not publish dependency asset names, report names, IDs or URLs.

Dependency context is computed through the existing `DependencyService.blast_radius(...)` path after scorecard derivation and cannot affect the scorecard badge or metrics.

The route is registered directly with `app.add_api_route(...)` to preserve the repository's existing `app.routes` regression contract; an intermediate FastAPI included-router object is not added.

## Analyst-facing UI boundary

The existing source-detail template includes one compact Reliability Scorecard panel after the established four-card source summary and before the existing detail layout.

The panel reuses existing UI primitives (`panel`, `status`, `finding`, `profile-grid`) rather than introducing a new styling system or redesigning source detail.

It displays:

- current trust badge;
- 7-day and 30-day check counts;
- Healthy percentage;
- successful-check percentage;
- incident openings;
- stale occurrences;
- Data Rule failure occurrences;
- MTTR in hours when known.

The panel states explicitly that the badge mirrors current Health and historical metrics do not reclassify the source.

When `history_complete` is false, the UI displays a partial-history safety note.

## Dynamic rendering boundary

The application creates one workspace-bound `ReliabilityScorecardService` during web configuration and stores it on `app.state.scorecard_service`.

The scorecard API uses that same service. The Jinja environment receives a narrow `reliability_scorecard_for(source_id)` global for authenticated source-detail rendering, avoiding a broad rewrite of the established `web.py` source-view composition.

## Static Pages boundary

`build_pages_site(...)` creates a scorecard service over the existing static-storage boundary and uses the same deterministic derivation for source-detail HTML and public `state.json`.

The exported scorecard contains aggregate reliability metrics only.

Product v0.23's public Data Rule privacy boundary remains authoritative:

- private rule IDs/names are not exposed;
- referenced private fields are not exposed;
- allowed sets/bounds are not exposed;
- custom impact/investigation guidance is not exposed;
- failing row values are not exposed.

The scorecard may expose only the aggregate count that one or more Data Rule failures occurred in a given observation window.

## Preserved v0.23 Data Rule architecture

Product v0.24 does not modify the deterministic Data Rule engine:

- `not_null`;
- `allowed_values`;
- `numeric_range`;
- `row_count_range`.

Data Rule findings still join ordinary source findings before the single existing `health_from_findings(...)` derivation. Scorecards consume the resulting observation evidence downstream.

## Preserved product architecture

Product v0.24 does not change:

- connector ingestion semantics;
- detector thresholds;
- Healthy / Warning / Critical classification;
- Data Rule evaluation semantics;
- source preflight/onboarding acceptance;
- baseline promotion/review;
- incident transition semantics;
- notification policy;
- delivery attempt state/idempotency/retry/reconciliation;
- Viewer / Operator / Admin authorization;
- workspace persistence boundaries;
- row-diff retention/privacy;
- Power BI Guard trust logic;
- dependency graph traversal/storage;
- Teams delivery state handling;
- Delivery Ops reconciliation;
- approved finding/history/sidebar source-detail layout.

## Verification

The functional/UI/static checkpoint `4fc6e6126391da630a635b2ea9c04cfc7890d6fe` passed:

- Ruff;
- compile/import checks;
- PostgreSQL 16-backed suite;
- **275 passed, 1 warning**.

Coverage proves:

- current Health → trust badge mapping;
- 7-day / 30-day deterministic metrics;
- inclusive time windows and future-observation exclusion;
- incident/recovery/MTTR reuse of existing transition logic;
- per-observation stale/Data Rule occurrence counting;
- adaptive cadence-aware history loading;
- bounded incomplete-history claim safety;
- scorecard API 404 behavior;
- count-only downstream impact privacy;
- downstream impact cannot change the badge;
- authenticated source-detail scorecard rendering;
- static Pages/state scorecard parity;
- public Data Rule contract remains private while aggregate failure occurrence is retained.

Release-only version/documentation changes are gated again on their exact head before merge.

## Next architecture step

Product v0.25 should implement preconfigured source packs as thin, typed presets over existing `MonitoringConfig` primitives. Packs should reduce onboarding configuration burden without creating a second source model or hiding assumptions.

After v0.25, architecture priority shifts to real connection/credential lifecycle and hosted pilot validation. AI investigation, if added later, remains an explanation layer downstream of deterministic evidence and must not redefine Health.
