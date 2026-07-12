# PPI Consensus Lock Runbook

Preview/apply records editable expected values; locking creates a separate immutable PPI snapshot only when all four values are complete and before release. It does not modify the calendar. Identical input is idempotent, while differing or invalid existing snapshots are never overwritten.

Locking is deferred for the actual `US_PPI_2026_06` event until expected values are entered. This stage does not call external APIs or AI and costs `free`. Readiness work follows in 5.3F-2B.
