# CPI Event Preparation Runbook

## Why Candidate And Approval Are Separate

The schedule is not auto-registered. A candidate preserves the human-entered official schedule details for review before it can affect the calendar. Reference period and release date are different: the event ID uses the CPI reference month, while the release timestamp is the later publication time.

## Prepare

Confirm the official schedule manually, then create a candidate with an event ID such as `US_CPI_YYYY_MM`. The candidate must be the month immediately after the latest CPI reference period.

```powershell
python scripts/automation/prepare_next_cpi_event.py --event-id US_CPI_YYYY_MM --reference-period YYYY-MM --release-datetime-utc <UTC_ISO_8601> --source "<official schedule source>" --source-checked-at-utc <UTC_ISO_8601> --output data/calendar/candidates/US_CPI_YYYY_MM.candidate.json
```

Review the event ID/reference period match, UTC and KST timestamps, source name, source check time, and SHA-256. Candidates cannot be overwritten automatically.

## Approve

Preview the merge before applying it, then validate the calendar. Consensus entry and immutable consensus locking happen later as separate steps.

```powershell
python scripts/automation/approve_cpi_event_candidate.py --candidate data/calendar/candidates/US_CPI_YYYY_MM.candidate.json --preview
python scripts/automation/approve_cpi_event_candidate.py --candidate data/calendar/candidates/US_CPI_YYYY_MM.candidate.json --apply
python scripts/validators/validate_calendar_events.py
```

The tools use no external API and have no cost. They do not infer dates, auto-approve candidates, or provide a force option.
