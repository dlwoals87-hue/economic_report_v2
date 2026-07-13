# NFP Data Contract

## Official Series Contract

The fixture collector accepts only these exact BLS Public Data API v2 series.
It never substitutes a related sector, population group, or a non-seasonally
adjusted series.

| Series | Role | Exact title | Seasonal adjustment | Frequency | Source level unit | Measure data type | Derived metric / unit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CES0000000001` | payroll level | All employees, thousands, total nonfarm, seasonally adjusted | Seasonally Adjusted | monthly | thousand persons | ALL EMPLOYEES, THOUSANDS | `nonfarm_payroll_change_k` / thousand persons |
| `LNS14000000` | unemployment rate | (Seas) Unemployment Rate | Seasonally Adjusted | monthly | percent | Percent or rate | `unemployment_rate` / percent |
| `CES0500000003` | average hourly earnings level | Average hourly earnings of all employees, total private, seasonally adjusted | Seasonally Adjusted | monthly | USD per hour | AVERAGE HOURLY EARNINGS OF ALL EMPLOYEES | `average_hourly_earnings_mom` / percent |

The source identifier is `BLS Public Data API v2`. Source level units describe
the BLS observation; derived units describe the calculated metric and are not
interchangeable.

## Metadata Modes

The ordinary BLS response fixture may contain no catalog metadata. In that
case the collector verifies exact allowlisted series IDs and records
`metadata_validation.mode: local_official_contract` and
`metadata_from_api_response: false`. It does not claim that missing response
titles or units were verified by BLS.

When a fixture includes catalog metadata, every official field above must
match exactly. A mismatch stops all calculation with
`NFP_SERIES_CONTRACT_UNVERIFIED`.

## Periods, Values, and Result States

Allowed source periods are only `M01` through `M12`. Duplicate periods,
missing current or previous periods, non-contiguous required periods, stale
responses, and reference mismatches have separate result states. All numeric
calculation uses `Decimal`; bool, malformed, NaN, and infinite values are
blocked. AHE previous values less than or equal to zero return
`NFP_BLS_DIVIDE_BY_ZERO`.

`NFP_BLS_COLLECTED` requires all three official series and every required
period. `NFP_BLS_PARTIAL` means that one or more official series or required
periods are absent while another official series or period remains valid. Its
`incomplete_reason` is either `NFP_BLS_SERIES_MISSING` or
`NFP_BLS_PERIOD_MISSING`. A response with no official series remains the
explicit `NFP_BLS_SERIES_MISSING` error. Contract failures are never
downgraded to partial.

Known blocking states are `NFP_BLS_SERIES_MISSING`,
`NFP_BLS_DUPLICATE_SERIES`, `NFP_SERIES_CONTRACT_UNVERIFIED`,
`NFP_BLS_INVALID_RESPONSE`, `NFP_BLS_DUPLICATE_PERIOD`,
`NFP_BLS_PERIOD_MISSING`, `NFP_BLS_PERIOD_GAP`,
`NFP_BLS_REFERENCE_MISMATCH`, `NFP_BLS_STALE`,
`NFP_BLS_INVALID_VALUE`, and `NFP_BLS_DIVIDE_BY_ZERO`.

Historical API fixture results remain `historical_backfill`,
`current_api_snapshot`, and `not_as_released: true`. They must never be
labelled `actual_as_released` or `live_release_capture`. Those labels are
reserved for a future first immutable capture inside the real release window.
Later API responses can be revised, so this fixture collector preserves raw
response and normalized-result SHA provenance but does not create a live
capture file.

Each metric retains its source series, current source period, required prior
source period, raw source values, calculation method, and unit. Payroll is
`current - previous`; unemployment is the official current series value; AHE
is `((current / previous) - 1) * 100` with a local Decimal precision of 28 and
no additional rounding.

The raw-response digest uses deterministic, sorted-key JSON serialization with
NaN and Infinity forbidden. Request credentials and endpoint fields are not
digest input. The normalized integrity digest excludes only its own
`integrity.sha256` field and is reproducible; a changed result cannot pass
`integrity_matches`.

NFP consensus, surprise calculation, paid providers, and AI generation are
not implemented in this stage and have no generated values or required manual
inputs.
