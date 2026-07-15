# CPI Consensus Provider Evaluation

Checked at: `2026-07-15T09:06:39Z`. This is a documentation-only qualification. No
account, API key, API request, scraping, or browser automation was used.

An `APPROVED` provider must pass every hard gate: permanently free API access without
card or trial, all four US CPI consensus metrics before release, deterministic documented
response fields, raw/snapshot storage, and explicit permission for public GitHub Pages
display plus derived surprise results. Unclear evidence is never treated as approval.

| provider | free | 4 metrics | pre-release | API | storage | public display | derived results | status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Financial Modeling Prep | yes | no evidence | yes | yes | no evidence | no | no | REJECTED_NO_PUBLIC_DISPLAY |
| Trading Economics | no | no evidence | yes | yes | no | no | no | REJECTED_PAID |
| Finnhub | no | no evidence | yes | yes | no | no | no | REJECTED_PAID |
| Twelve Data | no evidence | no evidence | no evidence | no economic-consensus API evidence | no | no | no | REJECTED_NO_PUBLIC_DISPLAY |
| EODHD | no | no evidence | yes | yes | no | no | no | REJECTED_PAID |
| Nasdaq Data Link | no evidence | no evidence | no evidence | no qualifying endpoint evidence | no | no | no | REVIEW_REQUIRED |
| Alpha Vantage | no evidence | no | no | documented indicators, not consensus | no | no | no | REJECTED_INCOMPLETE_METRICS |

## Financial Modeling Prep

- Official endpoint: `https://financialmodelingprep.com/stable/economic-calendar`.
- Authentication: official quickstart requires an API key.
- Pricing: Basic is listed as free, but the pricing page says displaying or redistributing
  FMP data requires a specific Data Display and Licensing Agreement.
- Metric mapping: the official economic-calendar page documents releases, not an explicit
  four-field CPI survey-consensus contract.
- Storage/public display/derived results: no free-tier permission was found; display and
  redistribution require the separate agreement.
- Decision: `REJECTED_NO_PUBLIC_DISPLAY`.
- Evidence: <https://site.financialmodelingprep.com/developer/docs>,
  <https://site.financialmodelingprep.com/developer/docs/pricing>,
  <https://site.financialmodelingprep.com/developer/docs/terms-of-service>,
  <https://site.financialmodelingprep.com/developer/docs/changelog>.

## Trading Economics

- Official Calendar API documents survey consensus separately from its proprietary
  analyst/model forecast and documents Point-In-Time calendar data.
- API identity/response fields: Calendar API and OpenAPI documentation are public.
- Pricing/distribution: official API material says subscription pricing depends on features,
  request volume, and distribution; full REST API and redistribution are described as
  full/enterprise access. A permanently free, public-display, snapshot-retention grant was
  not found.
- Decision: `REJECTED_PAID`.
- Evidence: <https://tradingeconomics.com/api/calendar.aspx>,
  <https://tradingeconomics.com/api/>,
  <https://tradingeconomics.com/analytics/api.aspx>,
  <https://api.tradingeconomics.com/swagger/index.html>,
  <https://docs.tradingeconomics.com/get_started/rate-limits/>.

## Finnhub

- Official economic calendar endpoint is marked Premium Access Required. Its official
  economic-data pricing page lists the calendar product at $50/month and Personal Use.
- Response documents `estimate`, `actual`, and `prev`, but paid personal-use access cannot
  satisfy the free/public-display hard gate.
- Decision: `REJECTED_PAID`.
- Evidence: <https://finnhub.io/docs/api/economic-code>,
  <https://finnhub.io/pricing-economic-data-api>.

## Twelve Data

- No official economic-calendar consensus endpoint meeting four CPI metrics was identified.
- Terms limit use to Internal Use unless a tier, add-on, or separate agreement permits more;
  external display/redistribution requires explicit authorization, and retention is limited
  by subscription/documentation.
- Decision: `REJECTED_NO_PUBLIC_DISPLAY`.
- Evidence: <https://twelvedata.com/terms>.

## EODHD

- Official economic-events endpoint has documented JSON with `estimate`, `actual`,
  `previous`, comparison, period, and country. It requires an API token and is listed in
  All-In-One/Fundamentals Data Feed plans; the documented free plan is limited to EOD stock
  data.
- The documented contract does not prove all four CPI consensus metrics or free public
  display/retention rights.
- Decision: `REJECTED_PAID`.
- Evidence: <https://eodhd.com/financial-apis/economic-events-data-api>,
  <https://eodhd.com/financial-apis/quick-start-with-our-financial-data-apis>,
  <https://eodhd.com/financial-apis/api-limits>.

## Nasdaq Data Link

- No official, qualifying economic-calendar consensus endpoint and licensing evidence was
  identified during this pass.
- Decision: `REVIEW_REQUIRED`; no adapter or scraping fallback is permitted.
- Evidence: <https://docs.data.nasdaq.com/>.

## Alpha Vantage

- Official terms identify its economic indicator APIs as FRED-based. No documented CPI
  survey-consensus API was found, so it cannot provide the required four pre-release market
  estimates.
- Decision: `REJECTED_INCOMPLETE_METRICS`.
- Evidence: <https://www.alphavantage.co/terms_of_service/>.

## Result

`NO_APPROVED_PROVIDER`. The registry intentionally has no approved entry, production
expected values remain null, and no adapter exists. Re-evaluate only with official written
evidence that explicitly covers every hard gate.
