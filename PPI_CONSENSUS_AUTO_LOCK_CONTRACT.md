# PPI Consensus Auto Lock Contract

Auto lock reuses `scripts/automation/lock_ppi_consensus.py` and its existing
`consensus_snapshot.json` schema, SHA calculation, immutable writer, and status
semantics. The wrapper adds validated observation provenance without replacing
the administrator fallback lock path.

All four applied calendar expected values must match the newest valid complete
observation after Decimal normalization. The snapshot stores that observation's
path, SHA, raw payload SHA, normalized SHA, retrieval time, and pre-release
provenance. Mismatch, missing expected values, invalid observations, or a
post-release request never create a snapshot.
