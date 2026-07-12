# PPI Processing Action Runbook

Manual runs and successful Capture PPI Release completions process pending PPI
releases from `main`. The workflow commits at most canonical, analysis, report,
and index; index-only resume commits only `docs/index.html`. Result JSON is
uploaded for every status.
