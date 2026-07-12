# PPI Consensus Provider Probe

This workflow is manual `workflow_dispatch` only. It probes provider coverage
without creating observations, applying expected values, locking snapshots,
committing, opening Issues, or deploying Pages. The Secret is scoped to the
single probe step; artifacts contain normalized diagnostics only, never keys or
raw payloads. Complete is the only result safe to enable later automation.
