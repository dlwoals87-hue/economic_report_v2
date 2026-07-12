# PPI Event Preparation Runbook

## Purpose

Create an immutable PPI event candidate only after a person has manually checked the official publication schedule. This tool does not discover dates, register an event, approve a candidate, modify `data/calendar/events.json`, call an API, or incur a cost.

## Prepare A Candidate

Enter the PPI reference period and the later official release timestamp. The event ID is generated as `US_PPI_YYYY_MM` when omitted.

```powershell
python scripts/automation/prepare_next_ppi_event.py `
  --reference-period YYYY-MM `
  --release-datetime-utc <UTC_ISO_8601> `
  --source-url <OFFICIAL_HTTP_OR_HTTPS_URL> `
  --source-checked-at-utc <UTC_ISO_8601> `
  --output-root <CANDIDATE_OUTPUT_DIRECTORY> `
  --result-json <RESULT_JSON_PATH>
```

The candidate records UTC and KST release times, the manually checked official source URL, `not_entered` consensus, null expected PPI metrics, candidate approval status, and a SHA-256 integrity value. No actual, previous, or surprise values belong in a schedule candidate.

## Review

Review the candidate before any later human approval step. A candidate has `approval.status: candidate`; it is not an approved calendar event. The tool uses exclusive creation: identical inputs return `PPI_EVENT_CANDIDATE_ALREADY_EXISTS`, while differing contents return `PPI_EVENT_CANDIDATE_CONFLICT` without overwriting the existing file.

The tool also blocks a candidate if `events.json` already contains the same PPI event ID, PPI reference period, or PPI release timestamp. It intentionally does not modify that calendar in this stage.

## No Input Is Safe

Running the command without the required manually verified schedule inputs returns `PPI_EVENT_INPUT_REQUIRED` and creates no production candidate. The workflow remains offline: no external API, AI API, or GitHub workflow is used, and the cost is always `free`.
