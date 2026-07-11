# CPI GitHub Issue Notification Runbook

## When Notifications Are Created

Success notifications are created only for `PROCESSED_AND_INDEXED` and `INDEX_ONLY_RESUMED` after the report is committed and pushed. The report must exist and be registered in `docs/index.html`.

Failure notifications are created for `failure`, `cancelled`, and `timed_out` Process workflow runs. `cancelled` remains labelled as cancelled. States such as `NO_PENDING_EVENT`, release waiting, unavailable BLS data, or missing reports do not create Issues.

## Security And Deduplication

The notify workflow uses the default `GITHUB_TOKEN` with `contents: read`, `actions: read`, and `issues: write`. PATs and external Secrets are not required. It searches both open and closed Issues for a notification marker before creating anything.

Issue notifications are free. Configure GitHub mobile or email notifications in GitHub account notification settings to receive repository Issue alerts.

## Operations

Pages deployment can take a few minutes after a successful notification. A notification failure never rolls back the report commit. For failure Issues, inspect the linked GitHub Actions run before making any operational change; do not manually modify production artifacts.
