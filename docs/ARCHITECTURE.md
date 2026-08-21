# AnalystWatch Core v0.1 Architecture

## Decision

Core v0.1 is a Python modular monolith. The same process hosts a small FastAPI web/API layer and calls a deterministic monitoring engine. SQLite persists source definitions, observations, findings, profiles, and the selected baseline.

This is deliberate: the data work is Python-native, SQLite is inspectable and sufficient for a proof of concept, and a single deployable avoids premature service boundaries. The monitoring domain modules are kept separate so storage, scheduling, or the web shell can be replaced later without rewriting detectors.

## Data flow

```text
SourceDefinition
  -> ingest (CSV / XLSX / JSON / REST JSON)
  -> pandas DataFrame
  -> profile
  -> freshness + baseline comparison detectors
  -> findings
  -> Healthy / Warning / Critical
  -> SQLite observation history
  -> FastAPI dashboard/API
```

## Components

- `models.py` — source configuration and evidence models.
- `ingest.py` — file/API acquisition; failures become evidence rather than uncaught monitor crashes.
- `profile.py` — structural, completeness, cardinality, numeric and categorical summaries.
- `detectors.py` — deterministic comparisons against the selected baseline plus freshness checks.
- `storage.py` — SQLite source definitions, observation history and baseline pointer.
- `service.py` — one monitoring transaction.
- `web.py` — minimal server-rendered dashboard and JSON API.
- `cli.py` — local source registration, checking, baseline promotion and serving.

## Baselines and history

The first successful observation is retained as the source baseline. Every run stores a compact observation/profile rather than a full dataset copy. A later successful observation can be explicitly promoted to baseline. The dashboard exposes recent history so current, previous, and baseline states remain distinguishable.

## Detector philosophy

Detectors use explicit thresholds and emit the actual current/baseline evidence. Numeric drift reports symptoms such as "possible scaling/unit change" rather than asserting an unproven root cause. Category changes use material frequency plus total-variation distance to reduce noise. Key uniqueness drift only runs for configured key columns.

## Freshness

For files, freshness can use filesystem modification time. If `latest_date_field` is configured, its maximum parseable value is used instead. APIs therefore need a configured date field to support content freshness in v0.1; HTTP success alone is not treated as freshness evidence.

## Tradeoffs / current limitations

- SQLite is single-node and intended for the proof-of-concept, not large multi-tenant SaaS concurrency.
- Authentication and source secrets are intentionally out of scope.
- JSON support is arrays of objects, flat objects, `records`/`data` arrays, or a configured dotted record path.
- Schema rename inference is not implemented yet; removed/added fields are reported without claiming a rename.
- Detection compares primarily to the selected baseline. Rich multi-window historical models are later work.
- Scheduling is not yet embedded; an external scheduler can invoke the CLI/API.
