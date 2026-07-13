# NFP BLS Collector Runbook

This 6.1A-1 collector consumes only a local, free official-BLS-shaped fixture.
It makes no real BLS, paid-provider, or AI request. Run it with an explicit
reference period, fixture path, and result path; do not use it to create a
production release record at this stage.

For ordinary BLS-shaped responses without catalog metadata, the collector uses
the local official series contract. It accepts only the three exact allowlisted
series and records that API metadata was absent. It never infers a replacement
series from a title, sector, production grouping, or labour-force population.
If catalog metadata is present, a title, seasonality, frequency, unit, or
measure-data-type mismatch stops processing with
`NFP_SERIES_CONTRACT_UNVERIFIED`.

Only `M01` to `M12` are valid. Duplicate series, duplicate periods, missing
required periods, period gaps, stale data, and reference mismatches are
blocking statuses. AHE's prior value at zero or below returns
`NFP_BLS_DIVIDE_BY_ZERO`; malformed, boolean, NaN, and infinite values return
`NFP_BLS_INVALID_VALUE`.

When one official series or a required period is absent but other official
series or periods remain valid, the collector returns `NFP_BLS_PARTIAL` with
an `incomplete_reason` of `NFP_BLS_SERIES_MISSING` or
`NFP_BLS_PERIOD_MISSING`. Duplicate, gap, stale, metadata, numeric, provider,
and malformed-response conditions remain explicit blocking states, not partial.

Fixture and historical-query results always record `historical_backfill`,
`current_api_snapshot`, and `not_as_released: true`. They are not an
`actual_as_released` or live capture. Only a future first immutable capture in
the actual release window may make that claim; later API responses may be
revised. Metrics retain source values and periods, and the response and
normalized result have reproducible SHA-256 provenance. AHE uses Decimal
precision 28 with no additional rounding.

Malformed JSON and malformed response structures return
`NFP_BLS_INVALID_RESPONSE`. A failed provider status or a provider message
returns `NFP_BLS_PROVIDER_ERROR`, never complete or partial. The fixture CLI
must write only its explicitly supplied temporary result path. It does not
create events, releases, consensus, generated, analysis, or workflow files.

No real BLS, paid-provider, or AI call occurs in this stage. Consensus and
surprise are intentionally unimplemented. This final 6.1A verification runs
the NFP unit module and the existing full regression suite; later work should
prioritize actual release-window E2E validation over broader feature work.
