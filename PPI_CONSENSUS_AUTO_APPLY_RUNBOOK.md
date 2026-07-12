# PPI Consensus Auto Apply Runbook

Auto apply selects the latest complete pre-release observation, not a manually
entered number. Partial and unavailable observations remain diagnostic only.
Use preview first; `--apply` performs the validated atomic calendar update.

The pipeline blocks conflicts, unsafe paths, damaged observations, and post-release
execution. It does not create the final consensus snapshot; 5.3G-2B-2 handles
that separate lock. API keys, raw payloads, real provider calls, and workflow
connection remain outside this stage.
