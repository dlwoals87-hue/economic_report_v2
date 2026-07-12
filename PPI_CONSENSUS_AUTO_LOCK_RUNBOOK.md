# PPI Consensus Auto Lock Runbook

The normal sequence is API collector, immutable observation, latest complete
auto apply, then observation-backed auto lock. Preview validates only; `--lock`
uses the existing immutable PPI lock implementation. Equal reruns are already
locked and conflicting snapshots are never overwritten. There is no `--force`.

Manual consensus entry and the existing lock CLI remain administrator fallback
paths. This stage does not call the provider, expose secrets, or create workflow
automation. Final locking is allowed only before release and only when applied
expected values exactly match the selected observation.
