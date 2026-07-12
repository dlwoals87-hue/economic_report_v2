# PPI Notification Runbook

No-pending and already-processed results are skipped. Successful processing and
index-only resume produce deduplicated PPI success payloads; conflict, integrity,
artifact, and upstream failures produce failure payloads. Local tests never call
GitHub Issues or external APIs.
