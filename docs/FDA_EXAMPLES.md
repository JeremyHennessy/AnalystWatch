# FDA / openFDA monitoring examples

AnalystWatch includes two **optional, disabled** openFDA source examples in
`config/fda.sources.example.json`:

- FAERS drug adverse-event reports: `https://api.fda.gov/drug/event.json`
- MAUDE device adverse-event reports: `https://api.fda.gov/device/event.json`

These examples are deliberately separate from `config/sources.json`. They do not add FDA data to
the hosted monitor, do not run in the normal live-source smoke workflow, and do not create a source
until an analyst explicitly copies/configures one and passes normal preflight.

## What the examples demonstrate

Both examples use the existing generic REST API connector and the existing deterministic monitoring
pipeline. They can provide evidence about:

- endpoint availability;
- whether the response still exposes a usable `results` array;
- schema/profile changes in the returned records;
- the newest report date visible in the bounded response window;
- later detector findings if an analyst explicitly configures additional contracts after inspecting
  the real data.

The FAERS example orders the newest 100 records by `receivedate` and uses `receivedate` as its date
evidence. The MAUDE example orders the newest 100 records by `date_received` and uses
`date_received` as its date evidence.

The fixed 100-record window is a sample of current API results, **not** a completeness check. The
examples therefore do not add custom row-count drift thresholds or unique-key assumptions.

## Freshness is intentionally not guessed

The examples do not set `expected_refresh_minutes`.

FDA documents the openFDA FAERS endpoint as updating quarterly and warns that the API can lag the
underlying quarterly FAERS release by three months or more. FDA documents the MAUDE device-event
endpoint as updating weekly. Neither statement means that the newest report date in every bounded
query must advance on a fixed timer, so AnalystWatch does not convert those publication cadences
into an invented source freshness SLA.

An analyst who has a validated business expectation for a specific FDA workflow may configure an
explicit freshness contract after preflight and review.

## API-key handling

The example URLs intentionally contain no API key. openFDA documents separate request limits for
calls without a key and with a key. If recurring usage requires a key, keep it outside the
repository and configure authentication through an approved secret-backed mechanism; do not embed
an API key in committed source URLs.

Official documentation:

- https://open.fda.gov/apis/authentication/
- https://open.fda.gov/apis/drug/event/
- https://open.fda.gov/apis/device/event/

## Completeness and historical revisions

The openFDA API query examples are suitable for demonstrating AnalystWatch's source monitoring, but
they are not a substitute for acquiring the complete FDA datasets. openFDA states that endpoint
updates can change older records and that a complete current local copy requires downloading all
available files for the endpoint again after an update.

For workflows that require complete FAERS or MAUDE history, use the official download mechanism and
monitor the resulting controlled dataset separately rather than treating a 100-record API window as
the full database.

Official download documentation:

- https://open.fda.gov/apis/downloads/
- https://open.fda.gov/apis/drug/event/download/
- https://open.fda.gov/apis/device/event/download/

## Interpretation boundary

AnalystWatch can establish deterministic evidence about the data source it reads. It does **not**
establish that an adverse-event report proves causation, estimate event incidence from passive
reporting, or make a medical-safety determination. openFDA itself warns against relying on the API
for medical-care decisions, and the MAUDE documentation describes important limitations of passive
adverse-event reporting.

The correct product claim is therefore:

> AnalystWatch can tell you whether the configured FDA data input changed, became unavailable, or
> violated an explicitly configured data contract. It does not turn adverse-event reports into a
> causal or clinical conclusion.

## Trying the examples

Start with the examples disabled. Copy the desired source into a local/test configuration, leave
its endpoint unchanged initially, and run normal AnalystWatch preflight before persisting or
monitoring it. Review the returned columns and date evidence before adding keys, numeric fields,
Data Rules, freshness expectations, or downstream dependencies.
