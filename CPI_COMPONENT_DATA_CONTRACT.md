# CPI Component Data Contract

This C1 contract is fixture-only. It does not call BLS, create an operational raw
snapshot, modify canonical data, or update a report.

## Official Mapping

The registry at `config/bls_cpi_component_series.json` records BLS U.S. city-average
series for a six-component core set: shelter, food, energy, commodities less food and
energy, services less energy services, and medical care. Extended entries cover food
subcomponents, rent, owners' equivalent rent, energy subcomponents, apparel, recreation,
and education/communication.

Every approved component uses a seasonally adjusted `CUSR...` series for MoM and a
not-seasonally-adjusted `CUUR...` series for YoY. MoM is `(current SA / prior-month SA
- 1) * 100`; YoY is `(current NSA / same-month-prior-year NSA - 1) * 100`. A missing SA
series makes MoM unavailable rather than substituting NSA data.

Official references: <https://www.bls.gov/developers/api_signature_v2.htm>,
<https://www.bls.gov/cpi/seasonal-adjustment/home.htm>,
<https://www.bls.gov/cpi/tables/relative-importance/weight-update-comparison-2026.htm>,
and <https://download.bls.gov/pub/time.series/cu/>. Checked `2026-07-15T09:06:39Z`.

## Hierarchy And Contribution

Food contains food-at-home and food-away-from-home; shelter contains rent and owners'
equivalent rent; energy contains gasoline, electricity, and piped gas. Parents and children
are display relationships only: aggregation is forbidden and `double_count_risk` is explicit.

Index percent changes alone never establish contribution to headline CPI. Until an official
relative-importance vintage, matching reference period, official formula, de-duplication, and
headline reconciliation are supplied, each contribution is null with
`UNAVAILABLE_WEIGHT_OR_FORMULA`.

## C2 Contract

The future canonical location is `canonical.component_breakdown` with snapshot path/SHA,
mapping version, reference period, component MoM/YoY values, and contribution status. C1
does not write this field. Renderer values without component evidence must display
`미입력` or `산출 불가`, never sample weights or invented component values.
