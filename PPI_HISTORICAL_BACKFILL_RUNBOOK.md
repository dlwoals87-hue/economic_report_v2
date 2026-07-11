# PPI Historical Backfill Rehearsal

This rehearsal creates an isolated PPI historical preview only. It does not
write `data/calendar/events.json`, production releases, `docs/index.html`, or
`docs/reports`.

```powershell
python scripts/automation/run_ppi_historical_backfill.py `
  --event-id US_PPI_2026_05 `
  --reference-period 2026-05 `
  --original-release-datetime-utc 2026-06-11T12:30:00Z `
  --output-root D:\project\economic_report_v2_ppi_backfill_preview `
  --use-live-bls
```

The preview contains the immutable historical observation, PPI canonical,
rule-based analysis, report, copied index, and result. The historical lookup
is a current BLS API snapshot (`not_as_released: true`), not a release-time
capture. It uses no AI API and has free cost.

The same source data returns `PPI_BACKFILL_ALREADY_COMPLETE`; changed source
data returns `PPI_BACKFILL_CONFLICT` and never overwrites files. Output roots
must be absolute, outside the repository, free of `..`, and free of symlinks.
The report has no consensus comparison, no market or rate reaction claim, and
is not investment advice.

## Compact report rendering

The PPI renderer always keeps the release metadata, four PPI values, expected
and previous status, rule-based interpretation, core definition, provenance,
and data-availability summary. Market reaction, asset prices, yield curve,
positioning, liquidity, analogs, scenarios, track record, and checkpoints are
omitted entirely unless their input group contains real connected data. This
does not infer missing values. To preserve the prior immutable rehearsal, use
`D:\project\economic_report_v2_ppi_backfill_preview_compact` for a compact
preview run.

## Korean compact display

The compact PPI report presents user-facing titles, metric labels, timestamps,
backfill warnings, and the data-availability summary in Korean. Canonical and
analysis JSON retain their existing schemas, values, provenance, and internal
status values. A Korean preview can reuse a verified local PPI snapshot without
calling BLS again at `D:\project\economic_report_v2_ppi_backfill_preview_ko`.
