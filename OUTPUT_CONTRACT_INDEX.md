# LVS Output Contract Index

## Purpose

This document classifies files written by the Linux Validation Suite and sets
the key-naming policy for future JSON artifacts. It does not change existing
schemas. Saved output is consumed by LVS report workflows, retained-result QA,
legacy importers, and external scripts, so an undocumented rename can be a
breaking change even when the producing module is internal.

## Contract Classes

| Class | Meaning | Naming rule |
| --- | --- | --- |
| LVS-owned snake_case contract | A structured LVS document intended for programmatic use. | Schema property names use `snake_case`. New external contracts include `contract_id`, `contract_version`, and `kind`. |
| OCCT/legacy compatibility contract | A document shaped for the existing custom OCCT-compatible exporter/importer path. | Preserve the established spelling and casing exactly. |
| Embedded external/vendor/raw payload | Evidence copied from an operating-system, driver, backend, or vendor tool. | Preserve source properties verbatim inside an explicit, documented boundary. |
| Mixed compatibility artifact | An LVS envelope that embeds a compatibility or raw document. | LVS envelope properties use `snake_case`; embedded boundaries retain their source schema. |
| Text/CSV companion | Human-readable output, logs, or tabular evidence accompanying JSON. | JSON casing rules do not apply. Stable CSV column names still require compatibility review. |

## Generated Artifact Index

### Completed run artifacts

| Artifact | Classification | Ownership and compatibility notes |
| --- | --- | --- |
| `parsed_results_custom.json` | OCCT/legacy compatibility contract | Frozen compatibility export. Its lowercase, PascalCase, snake_case, and human-readable test keys are intentional. |
| `parsed_results_extended.json` | Mixed compatibility artifact | Snake_case LVS wrapper containing `system_info` and `compatibility_export`, both of which retain their existing schemas. It is extended, not normalized. |
| `system_info.json` | Mixed compatibility artifact | Hardware inventory uses established PascalCase sections with some snake_case detail records and is mirrored into `parsed_results_custom.json` as `SystemInfo`. |
| `run_manifest.json` | Mixed compatibility artifact | LVS lifecycle fields are snake_case. Raw backend details, including Vulkan properties such as `deviceName`, remain verbatim within backend/detail sections. |
| `run_metadata.json` | LVS-owned snake_case contract | Serialized run identity and operator metadata. Existing names are compatibility-sensitive. |
| `profile_used.json` | LVS-owned snake_case contract | Effective profile and stage configuration used by the run. |
| `telemetry_source_map.json` | Mixed compatibility artifact | LVS source-map fields are snake_case; source-specific PCI or backend evidence may retain established casing. |
| `raw_telemetry.csv` | Text/CSV companion | Dense timestamped telemetry. Metric column names are a compatibility surface even though they currently use snake_case. |
| `run_summary.txt` | Text/CSV companion | Human-readable rendering of the compatibility result. |

### Worker, sidecar, and debug artifacts

| Artifact | Classification | Ownership and compatibility notes |
| --- | --- | --- |
| `worker_results/*_cpu.json`, `*_memory.json`, `*_gpu_3d_*.json`, `*_vram_*.json` | LVS-owned snake_case contract | Worker evidence consumed by stage postprocessing. Treat existing keys as semi-public implementation contracts. |
| Intel GPU sidecar `*.json` | Embedded external/vendor/raw payload | Raw `intel_gpu_top` output; preserve it verbatim. |
| Intel GPU sidecar `*.summary.json` | LVS-owned snake_case contract | LVS summary of raw Intel GPU sidecar evidence. |
| `gpu_safety_marker.json` | LVS-owned snake_case contract | Local operational state used for interrupted-run safety. |
| `advanced_debug_manifest.json`, `*_debug_manifest.json` | LVS-owned snake_case contract | Indexes optional debug captures. |
| DRM/PCI debug snapshot JSON | Embedded external/vendor/raw payload | LVS wrapper fields may be snake_case; kernel keys such as `DRIVER`, `PCI_ID`, and `MODALIAS` remain verbatim. |
| Worker stdout/stderr, sidecar stderr, and debug logs | Text/CSV companion | Raw diagnostic text. |

### Diagnostics, readiness, and report artifacts

| Artifact | Classification | Ownership and compatibility notes |
| --- | --- | --- |
| `dependency_check.json` | Mixed compatibility artifact | Snake_case report envelope with source/backend capability dictionaries that can retain external casing. |
| `profile_audit.json` | LVS-owned snake_case contract | Profile audit findings and metadata. |
| `dry_run_diagnostics.json`, `diagnostics.json`, `preflight_report.json` | Mixed compatibility artifact | Snake_case envelopes; embedded runtime/backend detail dictionaries may preserve external properties. |
| `result_validation.json`, `result_validation_batch.json` | Mixed compatibility artifact | Snake_case validation envelopes; checks can include values derived from the legacy result schema. |
| `pre_import_sanity.json`, `pre_import_sanity_batch.json` | Mixed compatibility artifact | Snake_case workflow envelopes embedding validation or comparison payloads. |
| `results_inventory.json`, `artifact_details.json` | Mixed compatibility artifact | Snake_case inventory envelopes that may summarize fields from mixed source artifacts. |
| `result_comparison_vs_*.json` | Mixed compatibility artifact | Snake_case comparison envelope containing normalized summaries derived from legacy results and dynamic stage/device labels. |
| `dependency_check.txt`, `dependency_check_summary.txt`, profile/diagnostic/preflight summaries, validation/pre-import reports, inventories, artifact details, and comparisons | Text/CSV companion | Human-readable companions to the corresponding JSON artifacts. |

`telemetry_capabilities.json` and `extended_results.json` are recognized by
some presentation or validation paths but are not emitted by the current main
run artifact writer. They must not be treated as new schemas without first
defining their ownership and contract.

### QA, support, migration, matrix, and upload artifacts

| Artifact | Classification | Ownership and compatibility notes |
| --- | --- | --- |
| QA single/batch review JSON written to stdout | LVS-owned snake_case contract | Versioned `linux_validation_suite.qa_review` envelope. Embedded `validation`, `pre_import_sanity`, `comparison`, `review_verdict`, `worker_failure_evidence.raw_summary`, and `action_item_summary.details` sections retain legacy or separately owned field names. The QA CLI does not independently save a JSON file. |
| `public_support_summary.json` | LVS-owned snake_case contract | Versioned, public-safe local environment summary. |
| Retained `local_environment_summary.json` | LVS-owned snake_case contract | Older support-export filename; preserve for compatibility where present. |
| `migration_manifest.json` | LVS-owned snake_case contract | Versioned private migration-bundle manifest. Bundled settings/history/state retain their own contracts. |
| `hardware_result_validation_matrix.json` | LVS-owned snake_case contract | Versioned committed public coverage definition. |
| `hardware_result_validation_state.json` | LVS-owned snake_case contract | Versioned ignored local retained-result state. |
| `upload_manifest.json`, `google_drive_upload.json` | LVS-owned snake_case contract | Upload status and inventory. Dynamic Python module identifiers are data keys, not schema casing. |
| `public_support_summary.txt` and migration summaries | Text/CSV companion | Human-readable safety and restore guidance. |

### Persistent configuration and local state

`global_settings.json`, `run_setup_history.json`, and generated profile JSON
use LVS-owned snake_case fields. They are not completed-result artifacts, but
they are persistent user-facing contracts and must receive the same rename
review as output files.

## Casing And Evolution Policy

1. New LVS-owned JSON schema properties use `snake_case`.
2. New external LVS contracts include `contract_id`, `contract_version`, and
   `kind`. Removing or renaming required properties requires a contract-version
   change and a consumer migration plan.
3. `parsed_results_custom.json` is frozen as the OCCT/legacy compatibility
   export and may remain mixed. Its parser-facing sections include `Segments`,
   `SegmentDetails`, `Metadata`, `SystemInfo`, `Motherboard`, `Memory`,
   `Storage`, `Gpu`, `Cpu`, and `CpuCores`.
4. Compatibility-sensitive PascalCase fields inside legacy envelopes must not
   be renamed. This includes additive LVS fields already consumed under names
   such as `ExportContract`, `ReportSummary`, `GpuWorkerSummary`, and
   `StabilityInterpretation`. Existing aliases such as `ReportSummary` and
   `report_summary` must also be preserved.
5. Raw backend, operating-system, kernel, and vendor properties are preserved
   verbatim inside explicit boundaries. New schemas should name those
   boundaries clearly, for example `vendor_payload`, `raw_properties`, or
   `legacy_compatibility`, and identify the source schema where practical.
6. Dynamic display labels are data, not schema. Prefer records with explicit
   `name` and `value` fields for new contracts instead of turning labels into
   property names.
7. Do not use blind recursive case conversion. It can change vendor contracts,
   break importers, and create collisions such as `serial` versus `Serial`.
8. A future normalized result must be a separate, versioned additive artifact.
   It must not replace or rewrite `parsed_results_custom.json`.

## Required Change Process

Before changing an output contract:

1. Identify its writer, readers, CLI/TUI/QA presentation, tests, retained
   fixtures, and known external consumers.
2. Update contract documentation and fixture assertions first.
3. Preserve compatibility fields or introduce a new versioned artifact and a
   dual-read/dual-write migration period.
4. Run the full smoke suite, recursive `compileall`, and `git diff --check`.
