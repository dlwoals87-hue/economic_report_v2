# CPI GitHub Issue Notification Runbook

## When Notifications Are Created

Success notifications are created for `PROCESSED_AND_INDEXED`, `REPORT_ONLY_RESUMED_AND_INDEXED`, `REPORT_ONLY_RESUMED`, `INDEX_ONLY_RESUMED`, and `ALREADY_PROCESSED` after the report and index have passed integrity checks. This permits a manual Process workflow rerun to repair a notification after a completed report was already committed.

The repository artifact remains `docs/reports/{event_id}.html`. Its managed index entry must be an `article.auto-real-report` with the exact `data-event-id` and `data-report-href="reports/{event_id}.html"`; the public Pages URL is `https://{owner}.github.io/{repository}/reports/{event_id}.html`. Repository paths are never used as Pages URLs.

Failure notifications are created for `failure`, `cancelled`, and `timed_out` Process workflow runs. `cancelled` remains labelled as cancelled. States such as `NO_PENDING_EVENT`, release waiting, unavailable BLS data, or missing reports do not create Issues.

## Security And Deduplication

The notify workflow uses the default `GITHUB_TOKEN` with `contents: read`, `actions: read`, and `issues: write`. PATs and external Secrets are not required. It searches both open and closed Issues for a notification marker before creating anything.

Issue notifications are free. Configure GitHub mobile or email notifications in GitHub account notification settings to receive repository Issue alerts.

## Operations

Pages deployment can take a few minutes after a successful notification. A notification failure never rolls back the report commit. For failure Issues, inspect the linked GitHub Actions run before making any operational change; do not manually modify production artifacts.
