# PPI Data Contract

## Scope

This contract defines the U.S. Producer Price Index (PPI) data used by the
historical BLS collector. It is intentionally separate from the CPI contract.
The collector writes a current BLS API snapshot for a requested reference
period; it does not claim to reproduce the value available at the original
release time.

## Official BLS series

| Metric | BLS series | Meaning | Seasonal adjustment | Calculation |
| --- | --- | --- | --- | --- |
| `headline_mom` | `WPSFD4` | Final demand | Seasonally adjusted | Current month versus previous month |
| `headline_yoy` | `WPUFD4` | Final demand | Not seasonally adjusted | Current month versus same month one year earlier |
| `core_mom` | `WPSFD49116` | Final demand less foods, energy, and trade services | Seasonally adjusted | Current month versus previous month |
| `core_yoy` | `WPUFD49116` | Final demand less foods, energy, and trade services | Not seasonally adjusted | Current month versus same month one year earlier |

Core PPI in this contract excludes foods, energy, **and trade services**. It
must not be replaced with a foods-and-energy-only series. MoM uses the
seasonally adjusted series and YoY uses the not-seasonally-adjusted series, so
the collector must never mix the four series.

## Calculation and target-month protection

The caller supplies one `YYYY-MM` reference period. For each MoM metric the
collector requires the reference month and immediately preceding month. For
each YoY metric it requires the reference month and the same month in the
previous year. It calculates each result from BLS index levels using `Decimal`:

```
((current_index / comparison_index) - 1) * 100
```

The unrounded result and both raw index levels are preserved. The display value
rounds to one decimal place with `ROUND_HALF_UP`. A missing target month is not
substituted by the newest BLS observation. Missing comparison data, duplicate
periods, invalid or zero indexes, a missing series, and a supplied BLS
calculation that disagrees with the local calculation stop the collection.

## Provenance and revisions

`processed_ppi.json` records `data_origin: historical_lookup`,
`vintage_status: current_api_snapshot`, and `not_as_released: true`. Historical
lookups may reflect later BLS revisions. The raw response, retrieval time,
series mapping, reference period, and a deterministic SHA-256 integrity value
are retained so a later revision can be identified without pretending that the
snapshot is the original release vintage.
