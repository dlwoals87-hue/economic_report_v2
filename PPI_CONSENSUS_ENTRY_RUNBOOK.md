# PPI Consensus Entry Runbook

Enter the four PPI expected values only after confirming they came from one source at one observed time. This stage provides preview and apply only; it does not create a consensus snapshot or lock values.

```powershell
python scripts/automation/set_ppi_consensus.py --event-id US_PPI_YYYY_MM --headline-mom <DECIMAL> --headline-yoy <DECIMAL> --core-mom <DECIMAL> --core-yoy <DECIMAL> --source "Reuters" --source-observed-at-utc <UTC_ISO_8601> --preview
```

Review the returned values, source, observed timestamp, UTC/KST release timestamps, warnings, and calendar SHA. Preview never modifies the calendar.

Use the same values with `--apply` only before release. Apply updates the four `expected` fields, `consensus_status`, `consensus_source`, and `entered_at_utc` in `data/calendar/events.json` through an atomic write. It does not modify actual values, previous values, release timestamps, approval metadata, other events, or create a snapshot. Locking is deferred to 5.3F-2.

Values are finite Decimal strings without `%` or commas. The source is a name, not a URL or credential. Existing identical input is idempotent; differing input, an existing PPI snapshot, or a release-time expiry does not change the calendar. The tool has no external API or AI calls and costs `free`.
