# PPI Consensus Observation Runbook

The observation pipeline accepts `--event-id`, `--events`, `--output-root`,
`--now-utc`, and `--result-json`. It records a provider observation only before
the event release time and only below the PPI consensus output root. The final
lock remains a separate `consensus_snapshot.json` workflow.

Complete observations may proceed to 5.3G-2B automatic apply and lock. Partial
and unavailable observations are immutable diagnostic records and require a
new collection attempt. Existing equal records are left unchanged; different
records at the same timestamp are conflicts.

No user enters expected values directly. API keys and raw provider payloads are
not written. This stage uses fixture and key-missing paths only: real provider
API/secret connection remains a later operation.
