# CPI/PPI Commonization Audit

| Area | CPI location | PPI location | Same behavior | Extraction | Risk |
| --- | --- | --- | --- | --- | --- |
| Stable JSON integrity SHA | `stable_sha256` | canonical/collector SHA helpers | UTF-8, sorted compact JSON, excludes integrity SHA | `stable_json_sha256` | Low; wrappers remain |
| Immutable write | `write_new` | `write_new` | No overwrite | `write_immutable_bytes` | Medium; callers keep status codes |
| Preview output root | `output_root_path` | `safe_output_root` | External absolute, no parent traversal or symlink | `external_preview_root` | Low |
| Local preview links | `local_reference` | `local_path` | Same safety core, CPI has blocked roots | `local_preview_reference` | Medium; caller policy stays local |
| Sample asset copy | `copy_preview_file` | `repair_local_links` copy branch | Immutable copy and SHA check | Shared writer/file SHA | Medium; traversal order remains local |
| Missing local links | `repair_preview_links` | `repair_local_links` | Traversal details differ | Not extracted | Avoid preview-output regressions |
| UTC/KST display | `iso_kst` | PPI report formatter | User output differs | Not extracted | Preserve Korean PPI wording |
| Historical provenance | observation builder | observation builder | Common required fields | `validate_historical_provenance` | Low; callers own values |
| Temporary index entry | `build_index` | `build_index` | Metadata differs | Not extracted | Preserve labels and report SHA |

Series IDs, calculations, canonical semantics, analysis rules, capture behavior,
and status-code selection remain indicator-specific. No generic indicator engine
is introduced.
