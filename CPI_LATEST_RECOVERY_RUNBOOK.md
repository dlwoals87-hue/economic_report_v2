# CPI Latest Offline Recovery Runbook

Use this tool only when an immutable CPI release and its stored BLS raw snapshot exist but `data/processed/bls/cpi_latest.json` was not committed. It never calls BLS, uses no API key, and never changes the raw snapshot, immutable release, canonical release, analysis, report, or index.

Run a dry-run first with a project-relative result path:

```powershell
python -B scripts/recovery/recover_cpi_latest.py --event-id US_CPI_2026_06 --raw-snapshot data/raw/bls/cpi/2026-06/retrieved_20260714T140853Z.json --result-json tmp/cpi-latest-recovery-result.json
```

Only after reviewing `RECOVERY_READY`, rerun the same command with `--apply`. The only possible created operational path is `data/processed/bls/cpi_latest.json`. Existing output is never overwritten: matching bytes return `ALREADY_UP_TO_DATE`; differing bytes return `RECOVERY_CONFLICT`.

The recovery validates the exact raw path, BLS raw metadata and four-series response, calendar reference period, immutable release source metadata, and all four actual/previous raw and display values. A failed validation returns `INVALID_INPUT` or `RECOVERY_INTEGRITY_MISMATCH` and creates no output. The writer first uses an atomic hard-link publication; where hard links are unavailable it uses exclusive `xb` creation, still refusing overwrite.
