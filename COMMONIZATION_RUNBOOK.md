# Commonization Runbook

`scripts.common.preview` contains only verified preview mechanics: stable SHA,
immutable writes, external preview-root protection, safe local references,
asset copy, and common historical-provenance fields.

Callers translate shared errors into their existing public status codes. Do not
place series mappings, calculations, canonical semantics, analysis policy, or
live capture rules in this module. Run the full unittest suite, calendar
validator, and CPI readiness check after shared-helper changes.
