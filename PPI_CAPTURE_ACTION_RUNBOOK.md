# PPI Capture Action Runbook

The PPI capture workflow runs every 15 minutes but the calendar and
`run_due_ppi_capture.py` decide whether capture is due. No due event succeeds
without an API call, file creation, or commit. Only `CAPTURED` may commit the
single immutable `data/releases/ppi/{event_id}/as_released.json` path. Result
JSON is uploaded for every outcome; no secrets or raw API responses are stored.
