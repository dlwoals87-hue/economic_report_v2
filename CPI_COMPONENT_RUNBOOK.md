# CPI Component Runbook

1. Validate `config/bls_cpi_component_series.json`; only `APPROVED` mappings are requested.
2. Replay a saved test fixture through `parse_component_response`; do not invoke a transport
   function in C1.
3. Confirm BLS response status, exact requested/returned series, monthly `M01`-`M12` periods,
   Decimal index values, and common reference period. `M13` annual averages are ignored.
4. Build fixture observation and immutable fixture snapshot only after a complete parse.
5. Keep contribution unavailable unless validated BLS relative importance and formula evidence
   are added in a later phase.

The parser rejects duplicate, missing, unexpected, malformed, non-numeric, and period-mismatched
series. It makes no network request and does not touch `data/`, `docs/`, canonical release,
analysis, report, Pages, or workflows. C2 may connect a separately captured BLS component snapshot
to canonical data after live-capture safety work is approved.
