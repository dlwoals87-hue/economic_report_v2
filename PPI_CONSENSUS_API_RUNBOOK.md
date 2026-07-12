# PPI Consensus API Runbook

Use `scripts/collectors/ppi_consensus.py` with `--event-id`, optional `--events`
and `--now-utc`, and an optional safe `--result-json` diagnostic path. The
collector reads calendar data but does not update it. It rejects a missing or
ambiguous PPI event, a naive `--now-utc`, and the post-release collection window.

Set `TRADING_ECONOMICS_API_KEY` only in the execution environment. Never place
the value in source, fixtures, result JSON, logs, or error reports. If it is
missing, the collector returns `CONSENSUS_PROVIDER_KEY_MISSING` without opening
transport and writes a secret-free diagnostic result when `--result-json` is
safe. Result paths use an atomic replace and reject traversal, symlinks,
`events.json`, and consensus/release data directories.

The provider contacts only its fixed HTTPS Trading Economics host. It rejects
unsafe redirects, non-JSON content, oversized responses, and malformed UTF-8
JSON. HTTP authorization errors, rate limits, server errors, and timeouts map
to separate stable statuses; response bodies and authenticated URLs are not
reported.

For consensus values, `ForecastValue` is preferred and `Forecast` is a fallback
only when `ForecastValue` is absent. `TEForecast` and `TEForecastValue` must
not be used. `Actual` and `Previous` are never expected values. This stage does
not make real API calls; the provider contract is verified with injected mock
transport. Normalized complete, partial, and unavailable responses are reported
without applying expected values or creating a snapshot. Real API/secret
connection and full-project regression verification remain later stages.
