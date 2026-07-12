# PPI Consensus Observation Contract

An observation is an immutable pre-release record at
`data/consensus/ppi/{event_id}/provider_observations/{retrieved_at_compact}.json`.
It is not `consensus_snapshot.json`, does not apply expected values to
`events.json`, and is never actual release data.

The record preserves a single normalized Trading Economics response: its event
metadata, normalized metrics and status, missing metrics, provider metadata,
`Forecast` or `ForecastValue` source field, raw payload SHA-256, normalized
SHA-256, and an observation SHA-256. Its provenance states
`live_consensus_capture`, `pre_release_market_consensus`, and immutable status.
`Actual`, `Previous`, `TEForecast`, `TEForecastValue`, API keys, authenticated
URLs, raw payloads, secrets, and stack traces are excluded.

Complete observations are eligible for apply; partial and unavailable
observations are retained but are not eligible. Provider errors, missing keys,
post-release collection, unsafe paths, and invalid integrity never create an
observation. Equal replays report already-exists, differing content reports a
conflict, and damaged existing files report an integrity error.
