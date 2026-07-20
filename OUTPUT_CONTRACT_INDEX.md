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
| `run_manifest.json` | Mixed compatibility artifact | Versioned `linux_validation_suite.run_manifest` v1 envelope with `kind: run_manifest`. LVS lifecycle fields are snake_case. Raw backend details, including Vulkan properties such as `deviceName`, remain verbatim within backend/detail sections. |
| `run_metadata.json` | LVS-owned snake_case contract | Serialized run identity and operator metadata. Existing names are compatibility-sensitive. |
| `profile_used.json` | LVS-owned snake_case contract | Effective profile and stage configuration used by the run. |
| `telemetry_source_map.json` | Mixed compatibility artifact | Versioned `linux_validation_suite.telemetry_source_map` v1 envelope with `kind: telemetry_source_map`. The established top-level `version: 1` remains the source-map content version. LVS source-map fields are snake_case; source-specific PCI or backend evidence may retain established casing. |
| `raw_telemetry.csv` | Text/CSV companion | Dense timestamped telemetry. Metric column names are a compatibility surface even though they currently use snake_case. |
| `run_summary.txt` | Text/CSV companion | Human-readable rendering of the compatibility result. |

`Hardware.Storage` retains every established compatibility key. Eligible
internal-drive entries may additionally contain snake_case classification
fields and a normalized `storage_health` object. This object contains only
read-only, normalized health values and source/status notes; raw `smartctl` or
`nvme-cli` payloads are not embedded in `system_info.json`.

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
| `dependency_check.json` | Mixed compatibility artifact | Versioned `linux_validation_suite.dependency_check` v1 envelope with `kind: dependency_check`. Source/backend capability dictionaries can retain external casing. |
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
   `StabilityInterpretation`. Existing aliases remain unchanged until the
   breaking schema milestone, but no new duplicate case aliases may be added.
5. Raw backend, operating-system, kernel, and vendor properties are preserved
   verbatim inside explicit boundaries. New schemas should name those
   boundaries clearly, for example `vendor_payload`, `raw_properties`, or
   `legacy_compatibility`, and identify the source schema where practical.
6. Dynamic display labels are data, not schema. Prefer records with explicit
   `name` and `value` fields for new contracts instead of turning labels into
   property names.
7. Do not use blind recursive case conversion. It can change vendor contracts,
   break importers, and create collisions such as `serial` versus `Serial`.
8. The future breaking schema milestone will replace the canonical target with
   `parsed_results.json`. It will not add a redundant normalized alias beside
   every legacy field. Until that coordinated cutover, it must not replace or
   rewrite `parsed_results_custom.json`.

## Forward-Only Key And Unit Policy

Any new LVS-owned JSON or CSV field added before the breaking milestone must use
the eventual target conventions now:

- Fixed keys use `snake_case` and lowercase acronyms: `cpu`, `gpu`, `bios`,
  `pcie`, `nvme`, `vram`, and `wifi`.
- Do not add new PascalCase or camelCase LVS-owned keys, or duplicate aliases
  whose only difference is case.
- Raw vendor/backend properties may retain source spelling only within explicit
  boundaries such as `raw_properties`, `vendor_payload`, or
  `backend_raw_payload`.
- Binary capacities use `_gib` or `_mib`; `_gb` and `_mb` are reserved for true
  decimal gigabytes and megabytes.
- Network bit rates use `_gbps` (and `_mbps` at the corresponding scale).
- Binary byte throughput uses `_gib_per_s` (or `_mib_per_s`).
- Temperature, power, voltage, current, clock, memory transfer rate, and fan
  speed use `_temp_c`, `_power_w`, `_voltage_v`, `_current_a`, `_clock_mhz`,
  `_mt_s`, and `_fan_rpm`, respectively.

Human-facing labels may continue to use conventional acronym and unit spelling,
such as CPU, GPU, BIOS, PCIe, NVMe, VRAM, GiB, Gb/s, MHz, W, V, A, °C, and RPM.
This policy governs machine-facing fixed keys and does not turn display labels
into schema keys.

## Phase 1 Contract Clarifications (Completed Historical Record)

This completed Phase 1 section records the current contracts without changing
their payloads.
Phase 1 does not rename fields, remove aliases, add replacement fields, or
change the structure of `parsed_results_custom.json`.

### Legacy Binary-Unit Labels

The following established fields have names that say GB or MB but contain
binary GiB or MiB values. Their names remain compatibility-sensitive; consumers
must interpret the values using the actual-unit column until the future
`parsed_results.json` migration.

| Existing field or family | Actual unit | Compatibility note |
| --- | --- | --- |
| `memory_used_gb`, `gpu_vram_used_gb` | GiB | Telemetry values are derived from bytes or MiB using binary divisors. |
| `VramUsedGB`, `VramUsedAvgGB`, `VramUsedMaxGB` | GiB | Legacy compatibility and report-summary fields; text renderers label these values GiB. |
| `TotalPhysicalMemoryGB` | GiB | Compatibility system-memory capacity. |
| `CapacityGB`, `SizeGB`, `capacity_gb`, `size_gb` | GiB | Compatibility storage inventory capacities. These are distinct from Storage Benchmark's decimal throughput and lifetime-counter units. |
| `ActiveBufferMB`, `PerBufferCapMB`, and related buffer-size compatibility fields | MiB | Worker/export values use binary MiB. |
| `estimated_device_memory_gb` and `EstimatedDeviceMemoryGB` families | GiB | Compatibility GPU worker estimates. |
| `estimated_device_memory_gbps` and `EstimatedDeviceMemoryGBps` families | GiB/s | Historical names use `gbps`, but the calculation is binary bytes per second. |

No existing key in this table is redefined as a decimal unit. New fields must
follow the forward-only suffix policy instead of copying these names.

### Compatibility Aliases Preserved

`parsed_results_custom.json` is the frozen legacy compatibility output. Its
lowercase, PascalCase, snake_case, and human-readable aliases must remain until
the coordinated `parsed_results.json` migration. This includes root result,
time, metadata, report, and stability mirrors; `ReportSummary` and
`report_summary`; `Segments`, `SegmentDetails`, `Metadata`, `SystemInfo`,
`Motherboard`, `Memory`, `Storage`, `Gpu`, `Cpu`, and `CpuCores`; and the
`Temperatures.Ram` and `Temperatures.Memory` aliases. Dynamic test, device, and
stage labels are importer-facing data and are not renamed in Phase 1.

### Storage-Health Provider And Counter Semantics

`storage_health` is the normalized enclosing object. Names beginning with
`smart_` are historical umbrella names and may describe NVMe health obtained
from `nvme-cli`, not only a `smartctl` response. `nvme-cli` enables NVMe health
collection. `smartctl`, provided by smartmontools, is the preferred optional
provider for ATA/SATA/SAS and fallback SMART coverage. Missing `smartctl` is not
a failed health query when applicable NVMe drives are covered by `nvme-cli`.

`percentage_used` is a compatibility duplicate of `wear_percent_used`; both
currently carry the same normalized percentage-used value when available.
Neither field is removed in Phase 1. `host_writes_tb` and `host_reads_tb` are
decimal-TB lifetime host-write and host-read counters. The Storage Benchmark
fields `host_writes_delta_tb` and `host_reads_delta_tb` are decimal-TB deltas
between the benchmark's before and after health snapshots, not lifetime totals.

Raw `smartctl`, `nvme-cli`, and fio provider payloads are not embedded in normal
`system_info.json` or parsed-result artifacts. Raw fio JSON remains in the
separate `raw_fio/` boundary documented below.

### Contract-ID Namespace

The current ID namespace is inconsistent: established storage contracts use
`lvs.storage_benchmark*`, while QA, support, migration, and hardware-matrix
contracts use `linux_validation_suite.*`. Existing IDs are stable compatibility
identifiers and must not be renamed. For future public LVS-owned contracts, the
selected namespace is `linux_validation_suite.*`. This selection does not add a
new contract or migrate an existing ID in Phase 1.

### Enum Domains

The following are separate domains. Identical-looking terms are not declared
interchangeable, and casing is significant where shown.

| Domain | Current values and representation |
| --- | --- |
| Run/stage verdicts | Lowercase `pass`, `warning`, `fail`, `aborted`, and `manually_aborted` where manual-abort state is retained. |
| Storage Benchmark verdicts | Uppercase `PASS`, `WARN`, `FAIL`, and `CANCELLED`; all-internal target entries may also use `SKIPPED`. |
| Storage execution statuses | Lowercase `active`, `completed`, `failed`, `cancelled`, `unsupported`, `unavailable`, and `skipped`, according to manifest/result level. |
| SMART/storage-health states | `smart_health`: `passed`, `failed`, `unknown`; `query_status`: `available`, `partial`, `unavailable`, `permission_denied`, `unsupported`, `skipped_external`, `skipped_uncertain`. |
| Dependency statuses | Dependency entries primarily expose boolean `available`; storage-health capability status uses `available`, `partial`, `unavailable`, `not_applicable`. Human report labels such as `OK`, `missing`, and `missing preferred` are presentation text, not payload enums. |
| QA readiness states | Review: `ready`, `blocked`; import: `pass`, `warning`, `fail`; comparison: `ready_no_baseline_selected`, `blocked`, `error`, `compared`; escalation is the boolean `needed`. |
| Capability severity terms | Storage Benchmark fio capability uses lowercase `ok` and `warn`. General issue/event severity uses its separately owned values, including `warning`; Phase 1 does not merge these domains. |

### Compatibility And Raw Boundaries

- `parsed_results_custom.json` is legacy compatibility output, not the future
  normalized result contract.
- `system_info.json` currently combines compatibility hardware sections with
  normalized inventory additions. Its `memory_modules` data is compatibility
  inventory and is not a fully normalized memory-module schema.
- `backend_details` may contain backend- or source-specific evidence. Properties
  inside that boundary can retain their source spelling and semantics.
- Normal outputs contain normalized storage-health fields, but not raw SMART
  provider payloads. Normal parsed results and `system_info.json` do not embed
  raw fio JSON; Storage Benchmark retains it separately beneath `raw_fio/`.

### Deprecation Registry

This registry is a Phase 1 tracking aid, not a removal schedule. Any future
removal requires migration/version notes and the coordinated breaking milestone.

| Field or family | Artifact | Current status | Future replacement/removal |
| --- | --- | --- | --- |
| Legacy GB/MB fields listed above | Mixed telemetry, inventory, worker, and compatibility outputs | Preserve; actual binary units documented | Canonical names are deferred to the future `parsed_results.json` migration. |
| PascalCase/lowercase/snake_case compatibility aliases | `parsed_results_custom.json` | Preserve for existing importers | Remove only through the future atomic importer migration. |
| `ReportSummary` / `report_summary` and metadata/report mirrors | `parsed_results_custom.json` | Preserve compatibility duplicates | No Phase 1 replacement. |
| `Temperatures.Ram` / `Temperatures.Memory` | `parsed_results_custom.json` | Preserve compatibility duplicates | No Phase 1 replacement. |
| `percentage_used` | `storage_health` | Preserve as compatibility duplicate of `wear_percent_used` | Removal, if approved, requires a versioned migration note. |
| Existing `lvs.*` contract IDs | Storage Benchmark artifacts | Stable namespace exception; not deprecated | Do not rename; use `linux_validation_suite.*` for future public contracts. |

## Phase 2A Contract Identities (Completed)

Phase 2A added `contract_id`, `contract_version`, and `kind` to
`run_manifest.json`, `dependency_check.json`, and `telemetry_source_map.json`.
It did not rename existing fields, remove aliases, or change
`parsed_results_custom.json`.

## Phase 2B Telemetry Unit Aliases (Completed)

Phase 2B added unit-correct telemetry aliases without renaming or removing any
existing field. `memory_used_gib` mirrors `memory_used_gb`,
`gpu_vram_used_gib` mirrors `gpu_vram_used_gb`, and each dynamic
`gpu_<index>_vram_used_gib` field mirrors its corresponding
`gpu_<index>_vram_used_gb` field. The aliases are emitted in
`raw_telemetry.csv` and described in `telemetry_source_map.json`; the matching
capability names are included in dependency, preflight, dry-run, and run
manifest payloads.

The existing `_gb` telemetry fields are legacy compatibility names whose values
are binary GiB. They remain unchanged and remain authoritative for existing
internal processing. The additive `_gib` fields are the unit-correct names for
new consumers. Phase 2B does not remove or mark the `_gb` fields as deprecated
for operator-facing use, and it does not change `parsed_results_custom.json`,
`system_info.json`, storage benchmark contracts, or profile sidecar labels.

## Future Canonical Parsed-Result Milestone

Phase 1 clarification, Phase 2A identity, and Phase 2B telemetry alias work are
complete. The remaining coordinated canonical parsed-result migration is
deferred and is divided into two milestones.

### Phase 3 — Canonical-First Result Reader Compatibility

Phase 3 changes readers and adapters only. It introduces an identity-aware
artifact resolver and a normalized internal result view so readers can prefer
recognized canonical names when available and fall back to legacy names. It
does not emit `parsed_results.json`, remove aliases, or change
`parsed_results_custom.json`.

Artifact selection must not rely on the filename alone. Retained OCCT data may
already contain a different legacy artifact named `parsed_results.json`.
Readers may treat a file as the canonical LVS parsed result only when it carries
a recognized and supported identity:

```yaml
contract_id: linux_validation_suite.parsed_results
contract_version: 1
kind: parsed_results
```

An unrecognized `parsed_results.json` must not override
`parsed_results_custom.json` or existing specialized legacy handling.

### Phase 4 — Canonical Parsed Result v1 Dual-Output Migration

When Phase 4 is scheduled:

- The identified canonical parsed-result filename becomes
  `parsed_results.json`, using the contract identity above.
- `parsed_results_custom.json` remains the legacy OCCT/custom compatibility
  output and continues to be emitted during the migration.
- Fixed LVS-owned keys are normalized without redundant old/new alias fields.
- Semantic unit suffixes are corrected and internal readers, tests, fixtures,
  report adapters, validation, comparison, QA, and importer-facing adapters are
  migrated together.
- Raw/vendor/backend properties remain verbatim only inside documented
  boundaries. Dynamic test and stage labels also remain documented dynamic
  boundaries; there is no mechanical or recursive snake-case conversion.
- Apps Script, SQL, and other external importer changes require representative
  fixtures, identity-aware selection, compatibility planning, and a tested
  rollback path.
- Storage Benchmark v1 aggregate reshaping is outside this migration and
  requires its own separately approved, versioned contract milestone.

The cleanup must preserve the OCCT-style parsed-results layout rather than
redesigning it. The protected structural sequence is:

```text
root metadata
metadata
system_info
motherboard/devices/tests
memory/devices/tests
storage/devices/tests
gpu/devices/tests
cpu/devices/tests
cpu_cores/devices/tests
segments
segment_details
gpu_details
stability
stability_interpretation
report_summary
tests -> dynamic test label -> device/results -> dynamic stage label -> min/avg/max
```

Dynamic test and stage labels may remain labels. They are explicit dynamic
boundaries, not fixed LVS-owned keys that should be mechanically renamed.

The implementation milestone must deliver an importer migration package with:

- before/after sample parsed results;
- an `old_path -> new_path` mapping;
- an `old_unit -> new_unit` mapping and conversion notes;
- dynamic-label boundary documentation;
- raw/vendor boundary documentation; and
- Apps Script and SQL importer migration notes.

### Future Developer Deprecation Map

Before Phase 3 implementation, a developer-facing deprecation map should be
defined with these columns:

| Legacy artifact/path | Canonical path | Actual unit | Reader fallback owner | Intended migration phase | Permanent legacy |
| --- | --- | --- | --- | --- | --- |

The map is migration documentation, not an operator-facing warning system or a
removal schedule.

All new feature work must follow the forward-only key and unit policy for every
new LVS-owned field, even before the full cleanup is implemented.

## Storage Benchmark v1 Contract

Standalone and profile-stage file-backed storage benchmarks write `storage_benchmark.json` with
`contract_id: lvs.storage_benchmark`, `contract_version: 1`, and
`kind: storage_benchmark`. This remains separate from `system_info.json`.
Fixed keys are snake_case; throughput headlines
use decimal `average_mb_per_s`, `best_mb_per_s`, and `worst_mb_per_s`. Raw fio
JSON is retained only as separate files beneath `raw_fio/` and must not be
embedded in normalized results or system information. The associated manifest,
summary, before/after storage-health snapshots, and optional telemetry CSV are
siblings of the normalized result.

Workspace attribution is recorded with `target_workspace_path`,
`target_filesystem_type`, `target_filesystem_policy`, `target_is_cow`, `target_mapping_source`,
`target_physical_devices`, and `target_resolution_warning`. A single-device
copy-on-write workspace may be represented with a warning; unresolved,
multi-device, virtual, removable, USB, and network-backed mappings remain
ineligible.

Explicit sequential all-internal-drive runs additionally write an aggregate
`storage_benchmark_all_internal.json` with `contract_id:
lvs.storage_benchmark_batch`, `contract_version: 1`, and `kind:
storage_benchmark_batch`, plus `storage_benchmark_all_internal_summary.txt`.
Each selected drive retains its independent v1 result folder and raw fio
boundary; raw fio payloads are not copied into the batch contract.

When selected through `stages[].modules.storage_benchmark`, the benchmark is a
completion-based stage. Its artifacts are rooted at `storage_benchmark/` inside
the normal validation run directory. All-internal mode writes its aggregate JSON
and text at that root and keeps each drive's normalized, health, manifest, and
`raw_fio/` artifacts in a device-named child directory. Compact status and
verdict information is retained in the normal run manifest stage window and
executed plan; raw fio payloads are never embedded there.

## Required Change Process

Before changing an output contract:

1. Identify its writer, readers, CLI/TUI/QA presentation, tests, retained
   fixtures, and known external consumers.
2. Update contract documentation and fixture assertions first.
3. Preserve compatibility fields or introduce a new versioned artifact and a
   dual-read/dual-write migration period, except for an explicitly approved
   breaking milestone with an atomic reader migration and importer map. Do not
   introduce duplicate case aliases as a substitute for that migration.
4. Run the full smoke suite, recursive `compileall`, and `git diff --check`.
