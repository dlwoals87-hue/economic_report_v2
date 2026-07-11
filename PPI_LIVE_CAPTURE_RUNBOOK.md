# PPI Live Capture Runbook

After a human registers a PPI event, run the due-capture tool. Before release it
returns `WAITING_FOR_RELEASE`; before BLS publishes the target month it returns
`DATA_NOT_AVAILABLE_YET`; after 24 hours it returns `CAPTURE_WINDOW_EXPIRED`.
Successful capture is immutable and a matching rerun returns `ALREADY_CAPTURED`.
The BLS call is explicit, AI API calls are always false, and cost is free.
