# PPI Event Approval Runbook

## Purpose

Approve a previously generated PPI candidate only after human review. Approval revalidates the candidate SHA-256 and schedule contract, and requires an exact `--confirm-event-id`. It does not discover dates, call external services, modify the candidate, or use a force option.

## Approve

Use an explicit candidate, calendar, human approver identity, timezone-aware approval time, and exact event-ID confirmation.

```powershell
python scripts/automation/approve_ppi_event_candidate.py `
  --candidate <PPI_CANDIDATE_JSON> `
  --events <EVENTS_JSON> `
  --approved-by <HUMAN_REVIEWER> `
  --approved-at-utc <UTC_ISO_8601> `
  --confirm-event-id US_PPI_YYYY_MM `
  --result-json <RESULT_JSON>
```

`--confirm-event-id` must match the candidate exactly. `approved_at_utc` must be timezone-aware, after the candidate source-check timestamp, and not in the future. It may be after the PPI release timestamp, consistent with the existing calendar approval policy.

## Safety And Idempotency

The tool validates the candidate identity, UTC/KST release timestamps, official source URL, candidate status, null PPI expected metrics, provenance, and SHA-256 before reading the calendar. It preserves the schedule-source metadata, approval metadata, and source candidate SHA in the approved PPI event.

Calendar changes are formatted UTF-8 JSON, validated before and after writing a temporary file, then committed with an atomic replace. The candidate remains unchanged. The same candidate is idempotent (`PPI_EVENT_ALREADY_APPROVED`); conflicting contents or an occupied PPI reference period/release timestamp do not modify the calendar.

## No Input Is Safe

Running without the required approval inputs returns `PPI_EVENT_APPROVAL_INPUT_REQUIRED`. In this stage, do not approve a real candidate or point the command at the production calendar. The workflow remains offline and free.
