# PPI Collector Runbook

## Purpose

The PPI collector performs a historical lookup of the four BLS PPI series in
`PPI_DATA_CONTRACT.md`. It produces only preview files outside the repository;
it does not capture a live release, create events, call an AI provider, or
generate reports.

## Commands

Use a project-external output directory. A real BLS request is made only when
`--use-live-bls` is present:

```powershell
python scripts/collectors/bls_ppi.py `
  --reference-period 2026-05 `
  --output-root D:\project\economic_report_v2_ppi_preview\2026-05 `
  --use-live-bls
```

For an offline test, provide a fixture instead of `--use-live-bls`:

```powershell
python scripts/collectors/bls_ppi.py `
  --reference-period 2026-05 `
  --output-root D:\project\economic_report_v2_ppi_preview\fixture `
  --bls-response D:\fixtures\bls_ppi.json `
  --now-utc 2026-07-11T12:00:00Z
```

The output directory contains `raw_bls_ppi.json`, `processed_ppi.json`, and
`result.json`. Repository-internal paths, paths containing `..`, and symlink
output roots are blocked.

## BLS authentication and cost

`BLS_API_KEY` is optional. When it is absent, the collector uses the public
unregistered BLS API. If a registered-key request is rejected, it retries once
without the key. Keys and tokens are not written to logs or preview JSON.
`data_api_called` is true only for `--use-live-bls`; `ai_api_called` is always
false. The collector's cost is `free` and it never calls an AI API.

## Result statuses

`PPI_COLLECTION_COMPLETED` means all four metrics passed validation and the
three files were exclusively created. `PPI_COLLECTION_ALREADY_COMPLETE` means
the same normalized source data and calculations already exist; files and
timestamps are left unchanged. `PPI_COLLECTION_CONFLICT` means an incomplete,
modified, or different existing collection was found and it is never
overwritten.

Data errors are explicit: `PPI_REFERENCE_PERIOD_NOT_FOUND`,
`PPI_PREVIOUS_MONTH_NOT_FOUND`, `PPI_PREVIOUS_YEAR_MONTH_NOT_FOUND`,
`PPI_PARTIAL_SERIES`, `PPI_DUPLICATE_PERIOD`, `PPI_INVALID_INDEX_VALUE`, and
`PPI_CALCULATION_MISMATCH`. Resolve the data issue and use a new preview path;
there is no force option.
