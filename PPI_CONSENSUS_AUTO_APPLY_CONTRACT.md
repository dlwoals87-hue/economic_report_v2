# PPI Consensus Auto Apply Contract

Only the newest valid immutable complete Trading Economics observation is eligible.
The selector verifies event, provider, provenance, four expected metrics, release
time, filename timestamp, raw and normalized SHA formats, and observation SHA.
Partial and unavailable records are never applied.

Preview changes no files. Apply updates the four expected values and required
existing consensus metadata only after calendar validation, then atomically
replaces `events.json`. Existing equal values are idempotent; partial or different
existing expected values are conflicts. `--force` is intentionally unavailable.
