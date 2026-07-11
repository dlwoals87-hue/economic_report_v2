# CPI Historical Backfill Rehearsal

## Purpose

This rehearsal checks historical CPI data through the current BLS API in an isolated preview directory. It is not a live capture and does not claim release-time values. The output marks the data as `historical_backfill`, `current_api_snapshot`, and `not_as_released: true`.

The live capture 24-hour window is never bypassed. Do not use the rehearsal to create or replace live release artifacts.

## Run

After tests pass, run the isolated rehearsal with the bundled Python runtime.

```powershell
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/automation/run_cpi_historical_backfill.py --event-id US_CPI_2026_05 --output-root D:\project\economic_report_v2_backfill_preview --use-live-bls
```

The preview contains the observation, canonical, rule-based analysis, HTML report, and copied index only. A second identical command returns `BACKFILL_ALREADY_COMPLETE` without rewriting output.

## Preview Links

The copied index also copies only the local sample HTML files and safe static assets it actually references. To repair an older preview without calling BLS again, run:

```powershell
& 'C:\Users\dlwoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts/automation/run_cpi_historical_backfill.py --event-id US_CPI_2026_05 --output-root D:\project\economic_report_v2_backfill_preview --repair-preview-links
```

The repair reports `preview_links_valid: true` and an empty `missing_local_links` list. It does not modify the live index, source sample files, observation, canonical, analysis, or backfill report.

## Verification

Manually cross-check the four results with BLS official historical release material before considering any publication. Do not publish the preview to the site before that separate approval.

The rehearsal uses the free BLS data API only. It does not use an AI API or a paid API, and rule-based analysis has zero AI cost.
