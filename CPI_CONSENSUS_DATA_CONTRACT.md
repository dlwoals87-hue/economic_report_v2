# CPI Consensus Data Contract

The normal CPI consensus path is provider-neutral and fully pre-release:

`provider transport -> deterministic parser -> immutable observation -> immutable snapshot -> calendar projection -> canonical surprise`

No user-entered number and no AI output is market consensus. A future provider adapter must keep HTTP transport separate from parsing, retain the raw response at a safe repository-relative path, record its SHA-256, and replay fixtures without network access.

## Observation

`cpi-consensus-observation-v1` records provider identity, source URL/reference, response version, retrieval and observation times, event identity, raw-response provenance, four normalized metrics, and an immutable SHA-256. The only metrics are `headline_mom`, `headline_yoy`, `core_mom`, and `core_yoy`.

Each metric has an exact Decimal `expected_raw`, `expected_display`, `%` unit, provider label, and mapping version. Locale values, NaN, infinity, unknown fields, actual values, previous values, and credentials are rejected. Safe ranges are -10 to 10 for MoM and -20 to 30 for YoY.

Observation statuses are `COMPLETE`, `INCOMPLETE`, `UNAVAILABLE`, `INVALID`, `STALE`, and derived `AFTER_RELEASE`. Only a complete pre-release observation may produce a snapshot; partial evidence is retained but never projected into the calendar.

## Snapshot And Projection

`cpi-consensus-snapshot-v1` is immutable and contains the event identity, pre-release capture cutoff, provider/source provenance, observation SHA, all four metrics, validation result, and snapshot SHA-256. It never contains an API key, authorization URL, or raw credential.

Apply writes only the event's four `expected` values plus `consensus_source`, `consensus_status`, `entered_at_utc`, `consensus_snapshot_path`, and `consensus_snapshot_sha256`. Apply is preview by default, idempotent for the identical snapshot, and conflicts rather than overwriting a different projection. There is no force mode.

Canonical data retains actual and previous values from the BLS release; it obtains expected only from a validated immutable snapshot. Surprise is `actual - expected`, contains exact actual/expected inputs, `percentage_point` unit, an `above`/`inline`/`below` direction, and remains null when expected is null.
