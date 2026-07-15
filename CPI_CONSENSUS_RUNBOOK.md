# CPI Consensus Runbook

This phase does not call a provider. It defines the offline boundary that a future free/public provider adapter must use.

1. The adapter fetches only through its own transport module, stores the raw response in a safe repository-relative location, and parses one response deterministically into the four CPI mappings.
2. The adapter emits an immutable `cpi-consensus-observation-v1`. Every timestamp must be timezone-aware and before the scheduled release.
3. Preview a snapshot with `scripts/consensus/build_cpi_consensus_snapshot.py --event-id ... --observation ...`. Add `--apply` only in an approved pre-release operation.
4. Preview calendar projection with `scripts/consensus/apply_cpi_consensus_snapshot.py --event-id ... --snapshot ...`. Add `--apply` only after verifying the immutable snapshot.
5. Re-run readiness. If consensus is unavailable, capture of the actual release continues; only surprise comparison remains unavailable.

The legacy `set_cpi_consensus.py` tool is not the normal operation path. It is retained solely for controlled administrator recovery. Never represent AI output as market consensus, never use actual/previous as expected, and never use `--force` because no such option exists.
