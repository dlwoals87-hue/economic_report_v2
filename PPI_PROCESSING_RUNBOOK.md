# PPI Live Processing Runbook

Live processing validates immutable `as_released.json`, creates a PPI live
canonical, rule-based analysis, report, and explicit commit paths. Historical
backfill wording must not appear in live reports. Expected and surprise remain
null without an immutable consensus snapshot; previous remains unavailable when
no prior release rate exists. Processing is idempotent, uses no external API or
AI API, costs free, and future workflow wiring must use only the allowed four
output paths.
