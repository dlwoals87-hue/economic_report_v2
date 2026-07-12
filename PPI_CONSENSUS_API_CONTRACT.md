# PPI Consensus API Contract

The Trading Economics adapter accepts market consensus only from `ForecastValue`
or, when that field is absent, `Forecast`. Both values are parsed as finite
`Decimal` values. When both are present they must agree after normalization;
otherwise the adapter returns `PPI_CONSENSUS_FORECAST_CONFLICT`.

`TEForecast`, `TEForecastValue`, `Actual`, and `Previous` are prohibited as
expected-value sources. A row with only either TE forecast field returns
`PPI_CONSENSUS_PROHIBITED_TEFORECAST`; actual and previous values are never
substituted.

The transport has one fixed origin, `https://api.tradingeconomics.com`. It uses
HTTPS, validates the final redirect host, has an explicit timeout and response
size limit, requires JSON content, and decodes JSON as UTF-8. The adapter does
not accept caller-provided full URLs. Provider errors use stable status codes
without including response bodies, authenticated URLs, or API keys.

The collector accepts `--event-id`, `--events`, `--now-utc`, and `--result-json`.
It validates a single `US_PPI_YYYY_MM` event, its PPI/US identity, reference
period, and timezone-aware release time. Collection is allowed only before the
release time; after release it returns `PPI_CONSENSUS_CAPTURE_WINDOW_EXPIRED`
without calling the provider.

The API key is read only from `TRADING_ECONOMICS_API_KEY`. A missing key stops
before transport and returns `CONSENSUS_PROVIDER_KEY_MISSING`. Its result JSON
includes the event id, provider, `external_api_called: false`,
`external_ai_api_called: false`, and `cost: "free"`; it contains neither a key,
authenticated URL, nor raw payload.

Result JSON is UTF-8, stable JSON and atomically replaces only a safe result
path. Project, system temporary, and the explicit PPI operations result folder
are allowed; traversal, symlinks, `events.json`, and consensus/release data
paths are rejected. Collector results map normalized `complete`, `partial`, and
`unavailable` states to `PPI_CONSENSUS_COLLECTED`,
`PPI_CONSENSUS_PARTIAL`, and `PPI_CONSENSUS_UNAVAILABLE`. The collector never
changes `events.json`, expected values, or snapshots.
