# CPI Component Capture Runbook

## Purpose

The component pipeline is separate from headline CPI capture. It only starts after
`data/releases/cpi/{event_id}/as_released.json` already exists. A component failure
must never change, roll back, or block the headline release, canonical headline,
or headline report.

## Data Contract

- Registry: `config/bls_cpi_component_series.json`
- Source: BLS public API v2 over HTTPS
- Request series: only approved registry series, deduplicated and sorted
- Batch size: 25 or fewer series, so unregistered fallback requests remain within
  the public request limit
- Raw evidence: `data/raw/bls/cpi_components/{reference_period}/retrieved_{timestamp}.json`
- Immutable release: `data/releases/cpi/{event_id}/components_as_released.json`

The raw artifact records provider, API version, request count, request mode, batch
membership, and registry SHA. It never stores the registration key. The release
artifact is created once: identical retries yield `COMPONENT_ALREADY_CAPTURED`; a
different proposed artifact yields `COMPONENT_IMMUTABLE_CONFLICT`.

## Operations

The normal command requires explicit live opt-in:

```powershell
python scripts/automation/run_due_cpi_component_capture.py --event-id US_CPI_YYYY_MM --enable-live-bls --result-json <outside-project-result.json>
```

Without `--enable-live-bls`, the runner is dry and returns
`COMPONENT_DATA_NOT_AVAILABLE_YET`. `BLS_API_KEY` is optional. The existing BLS
registered request is attempted when present; an explicitly rejected key retries
unregistered mode. Never put the key in a command line, JSON artifact, log, or
workflow file.

## Report Behavior

Canonical generation includes `component_breakdown.status: unavailable` when the
component release is absent or invalid. The headline canonical and report continue.
When an immutable COMPLETE component release exists, the report adds section 04 and
shows only its stored MoM, YoY, and unavailable contribution values. No weights,
contributions, market reaction, or inferred values are fabricated.

## Workflow Commit Guard

`capture-cpi-components.yml` may commit exactly two new regular files: one raw
component snapshot and one `components_as_released.json`. It explicitly adds only
the result paths, then checks staged names and name-status again. Both must exactly
match the two expected paths and have status `A`; traversal, backslashes, symlinks,
unexpected files, force push, and bulk adds are rejected.
