# LVS Output Contract Index

## Purpose

This document classifies files written by the Linux Validation Suite and sets
the key-naming policy for future JSON artifacts. It does not change existing
schemas. Saved output is consumed by LVS report workflows, retained-result QA,
legacy importers, and external scripts, so an undocumented rename can be a
breaking change even when the producing module is internal.

## Contract Classes

The parent-owned `linux_validation_suite.vulkan_compute_shutdown` v1 snake_case
contract is attached as `shutdown_evidence` in normalized WorkerResults and
preserved intact as additive `ShutdownEvidence` in compatibility GPU details
and worker summaries. It records PID/role/physical target, timing source and
freshness decision, selected compute/cleanup/total allowances, fallback/cap
reason, SIGTERM request and absolute monotonic deadline, wait budget, observed
exit/kill/reaping outcome, and normalized `final_worker_result`. It does not
attest success, rewrite raw child JSON, or infer cleanup from accounting balances.
Native compute JSON adds `worker_pid` and
`last_result_write_started_monotonic_seconds` for current-process association.
See [policy, limits and the focused physical capture](docs/vulkan_shutdown_phase_diagnostic.md).

The opt-in Vulkan compute `linux_validation_suite.vulkan_shutdown_phases` v1
contract uses snake_case keys in `*.json.shutdown-phases.json` sidecars and the
embedded `shutdown_phase_evidence`. It retains 64 phase observations plus
cumulative/overwritten counts, active phase, stop-request timestamps, identity,
phase errors and diagnostic publication errors/elapsed time. Entered phases
are not completed operations; `observed_cleanup_complete` merely mirrors the
worker's recorded cleanup state. These diagnostic artifacts never establish a
workload PASS or replace terminal worker/lifecycle evidence. See
[the opt-in procedure and limits](docs/vulkan_shutdown_phase_diagnostic.md).

The opt-in `native/vulkan_bounds_diagnostic.py` emits
`linux_validation_suite.vulkan_bounds_startup_diagnostic` version 1 artifacts under a
new results subdirectory. These are bounded startup observations, not ordinary
profile results or stress acceptance. The manifest records source endpoints,
target, exit/deadline state; the diagnostic result keeps host expectations,
independent shader observations, guards, descriptor ranges and cleanup evidence.
An `observed` result may reveal a query/push discrepancy and must not be rendered
as a verified workload PASS. See [operator and interpretation details](docs/vulkan_startup_bounds_diagnostic.md).

Vulkan native workers accept an optional exact `--target-device-uuid` binding.
`target_device_uuid` and `selected_device_uuid` are additive native/WorkerResults
evidence (canonical UUID display/byte order, not pipeline-cache or driver UUIDs).
Compatibility GPU validation details expose `TargetDeviceUuid` and
`SelectedDeviceUuid` only when the new selected identity evidence is present;
historical records are not backfilled. Physical PCI IDs and telemetry/provider
indices retain their existing meanings. Planning, command construction, and both
native workers require positive UUID, authoritative PCI, or DRM render-node proof; model names,
candidate uniqueness, ordinals, and Mesa UUID bus heuristics are not proof.
Known target identifiers are retained independently of optional candidate data.
Available UUID/PCI/DRM contradictions override any other matching evidence. Missing
runtime UUIDs permit execution only with independently matching runtime PCI or
DRM render-node identity, not inferred PCI addresses. The optional core 1.1 UUID query does
not impose UUID availability on a positively identified PCI-only device.
The additive `physical_identity_evidence` contract
(`linux_validation_suite.vulkan_physical_identity`, version 1) preserves requested
and selected identifiers, proof source, and `verified`, `unknown_identity`,
`missing_evidence`, `ambiguous_identity`, or `conflicting_identity` status.
Compatibility validation details retain it as `PhysicalIdentityEvidence`,
including failed selections. Historical records are not reassessed. Auto backend
selection remains whole-stage/target-set selection, not per-device fallback.

The optional `VK_EXT_physical_device_drm` query adds `drm_render` (major/minor)
to discovery. Only an advertised extension with populated `hasRender` properties
can supply this proof. Linux character-device `st_rdev` must match; a node name,
model name or platform-label similarity is insufficient. This supports non-PCI
GPUs without inventing a PCI address. Platform inventory labels remain distinct
from DRM proof, including DRM masters whose sysfs ancestry is a display controller.
Workers retain `--target-render-node` and the observed `--target-drm-render`
device number, independently rechecking them and the runtime device on launch.
Bound node disappearance/reassignment fails closed. Additive `target_drm_render` and
`selected_drm_render` fields in physical identity evidence preserve the proof;
`source=drm_render_node` denotes direct DRM matching. A runtime UUID may be bound
after this independent proof, then reverified by both native workers. Neither
binding nor software fixtures imply physical workload acceptance.

| Class | Meaning | Naming rule |
| --- | --- | --- |
| LVS-owned snake_case contract | A structured LVS document intended for programmatic use. | Schema property names use `snake_case`. New external contracts include `contract_id`, `contract_version`, and `kind`. |
| OCCT/legacy compatibility contract | A document shaped for the existing custom OCCT-compatible exporter/importer path. | Preserve the established spelling and casing exactly. |
| Embedded external/vendor/raw payload | Evidence copied from an operating-system, driver, backend, or vendor tool. | Preserve source properties verbatim inside an explicit, documented boundary. |
| Mixed compatibility artifact | An LVS envelope that embeds a compatibility or raw document. | LVS envelope properties use `snake_case`; embedded boundaries retain their source schema. |
| Text/CSV companion | Human-readable output, logs, or tabular evidence accompanying JSON. | JSON casing rules do not apply. Stable CSV column names still require compatibility review. |

## Generated Artifact Index

### Optional Vulkan slow-operation evidence

Native compute worker `slow_operation_evidence` is an additive versioned
`linux_validation_suite.gpu_worker_slow_operations` v1 snake_case boundary.
Raw WorkerResults retain it; parsed/compatibility worker details expose the same
boundary as `SlowOperationEvidence`. Historical absence is null, not a claim of
no stalls. The one terminal `gpu_worker_slow_operation_diagnostics` JSON record
in the existing worker stderr log captures final-write timing too. Records and
per-operation maxima are bounded and are host observations, not GPU instruction
timings or pass/fail criteria. See `docs/gpu_worker_stall_diagnostics.md`.

### Source/build provenance

`linux_validation_suite.source_provenance` v1 uses snake_case properties and
`kind: source_provenance` for observed source evidence; the optional ignored
`lvs_source_build.json` uses the same contract with `kind: source_build_stamp`.
Its checksum detects accidental stamp edits, not authenticity. The deterministic
`lvs_execution_source_v1` fingerprint is scoped source identity, not native-binary
or dependency attestation. A capture commit/label never replaces measured bytes.
Collection is automatic: no stamp, Git, packaging or operator command is needed.
See [Automatic source provenance](docs/source_build_provenance.md).

Run manifests and extended output add `source_provenance`, final
`source_provenance_end`, and `source_changed_during_run` (nullable when unknown).
Diagnostics/preflight add `source_provenance`. Initial evidence is also retained
as `system_info.json` / compatibility `SystemInfo.SourceProvenance`, without
renaming legacy fields. Report data exposes it under `run.source_provenance`;
historical absence is `not_recorded`, never reconstructed from the renderer.
Report/QA `source_identity` summaries validate recorded fingerprints and expose
Git uncertainty and source changes as separate observations. Ordinary comparison
payloads add `source_comparison` (`matching`, `different`, `insufficient_evidence`,
or `unavailable`). Local Git correlation is separately labelled, bounded to HEAD
and at most one recorded HEAD, offline, and based on identical v1 scoped bytes;
multiple commits can match. Legacy results remain `not_recorded`, not relabelled
with the reviewing checkout. Legacy stamps remain optional, untrusted claims.
None of these observations changes worker integrity, safety, or verdict rules.

### Completed run artifacts

Native CPU/RAM workers add `native_executable_provenance`, contract
`linux_validation_suite.native_executable_provenance` v1. Prelaunch, Linux
process-executable and post-execution observations remain separate; SHA-256,
size, ELF-header architecture and bounded timing/file-object metadata are not
source/binary/instruction attestation. No paths or executable payloads are added.
Compatibility retains this versioned evidence unchanged. Reports and QA expose
`native_executable_review` / `native_executable_text`; missing historical evidence
is not reconstructed. See [automatic executable provenance](docs/native_executable_provenance.md).
Compatibility output also retains recorded `source_provenance_end` and nullable
`source_changed_during_run` so normal summaries use actual endpoints. Conflicting
endpoint evidence is explicit; this does not alter the v1 source fingerprint.

| Artifact | Classification | Ownership and compatibility notes |
| --- | --- | --- |
| `parsed_results_custom.json` | OCCT/legacy compatibility contract | Frozen compatibility export. Its lowercase, PascalCase, snake_case, and human-readable test keys are intentional. |
| `parsed_results_extended.json` | Mixed compatibility artifact | Snake_case LVS wrapper containing `system_info` and `compatibility_export`, both of which retain their existing schemas. It is extended, not normalized. |
| `system_info.json` | Mixed compatibility artifact | Hardware inventory uses established PascalCase sections with some snake_case detail records and is mirrored into `parsed_results_custom.json` as `SystemInfo`. GPU inventory may include additive canonical physical identity, identity provenance, and platform-device path fields; their absence in historical results remains valid. `VulkanIdentitySource` records the authoritative UUID/PCI association used for PCI Vulkan inventory properties, or is empty when unavailable. It does not turn API-addressable heaps into physical VRAM capacity. |
| `run_manifest.json` | Mixed compatibility artifact | Versioned `linux_validation_suite.run_manifest` v1 envelope with `kind: run_manifest`. LVS lifecycle fields are snake_case. Per-stage `analysis_evidence` and additive `gpu_evaluation_evidence` keep execution outcome separate from telemetry-performance sufficiency. Raw backend details, including Vulkan properties such as `deviceName`, remain verbatim within backend/detail sections. |
| `run_metadata.json` | LVS-owned snake_case contract | Serialized run identity and operator metadata. Existing names are compatibility-sensitive. |
| `profile_used.json` | LVS-owned snake_case contract | Effective profile and stage configuration used by the run. |
| `telemetry_source_map.json` | Mixed compatibility artifact | Versioned `linux_validation_suite.telemetry_source_map` v1 envelope with `kind: telemetry_source_map`. The established top-level `version: 1` remains the source-map content version. LVS source-map fields are snake_case; source-specific PCI or backend evidence may retain established casing. |
| `raw_telemetry.csv` | Text/CSV companion | Dense timestamped telemetry. Metric column names are a compatibility surface even though they currently use snake_case. |
| `run_summary.txt` | Text/CSV companion | Human-readable rendering of the compatibility result. |

Effective profiles in `profile_used.json` (execution and diagnostics) and the
extended result's `profile` use `ProfileLoader.profile_payload`, sharing normal
profile serialization rules. Absent stage `analysis`/`gpu_evaluation` objects
are omitted, not emitted as null; configured objects and effective disabled/skipped
stages remain intact. Capture serialization does not mutate the run configuration.
Diagnostic captures retain additive `segment_labels` and all-stage runnable policy.
`load_profile` stays strict, including for a file named `profile_used.json`.
The explicit `load_captured_profile` compatibility reader treats only the two
legacy optional-object null sentinels as absence, in memory. It does not repair
malformed non-null objects or rewrite evidence. Existing raw report/QA readers
remain compatible; legacy results are not rewritten or reinterpreted as new runs.

`Hardware.Storage` retains every established compatibility key. Eligible
internal-drive entries may additionally contain snake_case classification
fields and a normalized `storage_health` object. This object contains only
read-only, normalized health values and source/status notes; raw `smartctl` or
`nvme-cli` payloads are not embedded in `system_info.json`.

### Worker, sidecar, and debug artifacts

Native CPU `sve_fp32_fma` adds separate `sve_fp32_fma_v1` verification and
`sve_fp32_fma_progress_v1` sidecar contracts (LVS-owned snake_case). Raw capabilities,
exact ISA/kernel, per-thread current vector length/flags/errno, active FP32 lanes,
arithmetic geometry, verification phases, affinity, and failures are retained as
an indivisible compatibility WorkerResults record. Progress uses actual monotonic
counter deltas; per-thread derived lane-FMA counts use validated VL-dependent
geometry, not NEON's fixed block size. Missing/failed evidence remains blocking;
derived work is not measured instructions or a saturation verdict. See
`docs/sve_fp32_fma_contract.md`. Existing NEON v1 contracts remain unchanged.

ARM64 `highest_verified_vector` may select experimental SVE as a common-capable
software-verified implementation, not an assertion of prior physical acceptance.
Additive `cpu_selection_evidence` records `selection_basis`, `selection_reason`,
`software_verification_status` (required at execution, not a preflight PASS),
`physical_acceptance_status` (`not_inferred_from_selection`),
`experimental_kernel_selected` and `vector_length_policy`. Existing executed
kernel, all-thread verification and per-thread VL/progress fields remain authoritative.
Standalone report stages may add `cpu_instruction_selection`, retaining recorded
selection evidence and separate actual worker kernel/verification observations.
Report worker `software_verification_satisfied` is affirmative only for successful
execution with a recognized, complete FP32 v1 contract and consistent selected/
executed identity. Additive `software_verification_status` distinguishes `verified`,
`failed_or_incomplete`, `not_required` (explicitly recorded), and
`insufficient_evidence`. Legacy/non-required checks are not affirmative proof of
FP32 verification; their runtime acceptance semantics remain unchanged.
No such evidence is invented for historical records. Ordinary Auto, Power Auto,
baseline/high-throughput and x86 policies do not change.

VRAM reporting distinguishes worker-requested, assigned and active/ramped targets.
Assigned targets, not active targets, drive attainment and normalized target
percentages; existing 60/85% bands are unchanged. GPU validation details add
`ReadbackVerificationStatus`, `ReadbackVerificationPasses`, `RequestedTargetBytes`, `AssignedTargetBytes`,
`ActiveTargetBytes`, `NominalAllocatedBytes`, `ActualAllocatedBytes`,
`VerificationCoverage`, `VerifiedCoverageBytes`, `PhysicalCommitmentKnown` and
`PhysicalCommittedBytes`. `VerificationSatisfied` requires applicable error-free
readback evidence, not merely positive counters. Missing evidence remains
`insufficient_evidence`; exhaustive verified bytes and physical commitment remain
unavailable unless actually established. EGL requires texture-specific readback
passes, not render/marker counts. Report stages expose the same facts as additive
`gpu_vram_allocation_evidence` in snake_case. Shared-memory usage is not treated
as dedicated-VRAM telemetry. Allocation and verification failures remain separate
events; lifecycle failures retain their existing precedence. These are reporting
corrections, not new allocation strategies or hardware-residency attestation.

Native CPU `neon_fp32_fma` additionally writes `<result-file>.progress.jsonl`
(`neon_fp32_fma_progress_v1`, LVS-owned snake_case). Newline-terminated snapshots
carry process/thread/CPU identities, paired Linux monotonic/realtime timestamps,
and fully verified per-thread block counts. Unterminated records are incomplete,
not usable evidence. Progress is supplementary, never a substitute for worker
verification, clean exit, or safety outcomes. `WorkerResults` retain additive
`verified_progress` metadata and `verified_progress_analysis` (same versioned
progress contract), including trimmed per-thread rates, coverage, gaps, and
insufficiency reasons. Report/chart stages expose `cpu_verified_progress`.
Historical results without the contract are not retrospectively assessed.

Native CPU `neon_fp32_fma` adds the `neon_fp32_fma_v1` verification contract:
`operation_family`, `verification_method`, `verification_version`,
`rounding_environment`, `execution_implementation`, `arithmetic_verified_blocks`,
`lanes_per_block`, `fma_rounds_per_block`, and initial/periodic/final completion.
`isa_capability_source` and `isa_hwcap` retain the common HWCAP provenance;
test-only emulation declares an override and null HWCAP, not ARM capability.
Each `threads_detail` entry preserves affinity, FPCR, verified/interrupted block
counts, and first-mismatch lane/bit-pattern evidence. Every requested thread must
verify; aggregate counters cannot establish this contract. Existing integer
`neon`, scalar, and historical workers retain their established contracts.
These fields travel unchanged in segment `worker_results` / compatibility
`WorkerResults`; missing historical fields do not imply FP32/FMA execution.
The compatibility filter preserves the complete CPU record when it declares
`verification_contract: neon_fp32_fma_v1`, including failed/incomplete evidence.
It does not synthesize missing fields or waive integrity checks. Older worker
records keep their established legacy projection.

| Artifact | Classification | Ownership and compatibility notes |
| --- | --- | --- |
| `worker_results/*_cpu.json`, `*_memory.json`, `*_gpu_3d_*.json`, `*_vram_*.json` | LVS-owned snake_case contract | Worker evidence consumed by stage postprocessing. Treat existing keys as semi-public implementation contracts. Vulkan compute workers add bounded startup checkpoints/fault-diagnostic state, timing, dispatch/submission, verification-cadence, device-limit, and optional GPU-timestamp evidence; absence of those additive fields preserves the historical contract. Padded dispatches in stateful-memory v21 and hash/stress-hash v9 use a logical-word push constant and descriptor-length guard before buffer access. `dispatch_group_count` is the scheduled grid; `active_work_items`, active bytes and derived work exclude padded invocations. Allocation and sampled verification retain their separate meanings. |
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
| `lvs_report_data.json` | Mixed compatibility artifact | Versioned `linux_validation_suite.report_data` v1 envelope compiled manually from an existing result directory. LVS-owned fields use snake_case; embedded recorded hardware inventory and portable run metadata may retain their established source keys. It contains run, component, stage-summary, reference, provenance, and normalized analysis-window data without embedded raw samples. |
| `lvs_chart_data.json` | LVS-owned snake_case contract | Versioned `linux_validation_suite.chart_data` v1 derived visualization companion compiled from normalized-window raw telemetry and the report chart catalog. It is non-authoritative, contains compact graph-ready samples, and never determines outcomes or metric summaries. |
| `result_report.html` | Text/CSV companion | Self-contained offline HTML rendered from `lvs_report_data.json` and the identical embedded `lvs_chart_data.json` payload; it is a derived manual report and does not replace canonical run evidence. |
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
| `migration_manifest.json` | LVS-owned snake_case contract | Private, explicitly not-public-safe migration-bundle manifest. The compatibility v1 writer remains available. Contract v2 combines the A1 logical inventory, integrity/privacy metadata, safe transaction engine, and frontend-neutral plan with semantic portable-settings, active custom/modified-stock profile, menu-group, setup-history, and optional Google service-account credential migration. `contains_secrets` and `SECRET_CONTENT` inventory entries distinguish credential-bearing bundles without exposing secret values. Old v2 bundles without those additive fields remain readable. Results, archived profiles, sensor logs, and active hardware-validation state remain excluded. Historical v1 bundles are conservatively adapted into the same settings/history semantics but never imply credential coverage. |
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

### Additive Temperature Provenance Fields

New runs may add `platform_thermal_zone_<zone-index>_temp_c` columns to
`raw_telemetry.csv`. Their `telemetry_source_map.json` entries preserve the
zone ID/type, source path, semantic classification, confidence, trip points,
threshold source, and any proven aliases. `cpu_temp_c` remains the established
numeric CPU-temperature field, but new collection populates it only from a
CPU-attributable source. Parsed temperature sections may add
`PlatformThermalZones`, and compatibility exports may add a `Platform`
hardware section. Existing fields, casing, and numeric types are unchanged;
historical results without provenance remain readable as legacy unknown
temperature evidence.

### Additive CPU Topology Identity Fields

New `system_info.json` CPU topology records may preserve per-logical-CPU ARM
architectural identity as `CoreModel`, `CoreIdentity`, identity status/source/
confidence, raw MIDR implementer/part/variant/revision evidence, and neutral
`PerformanceClass` evidence. Topology summaries may add `CoreIdentitySummary`
and `PerformanceClassSummary`; telemetry source-map and parsed core-clock rows
carry the equivalent snake_case or established PascalCase fields appropriate
to their enclosing contract. These additions do not redefine legacy
`CoreType`: `P` and `E` remain architecture-specific core-type evidence and
are not inferred from ARM capacity, CPPC, frequency, cluster, or CPU ordering.
Historical results without the additive evidence remain readable and are not
retroactively assigned an architectural model or performance class.

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

The optional `all_internal_non_root_low_occupancy` target mode adds selection
metadata without changing required Storage Benchmark v1 fields, list shapes,
or count meanings. When that mode is used, relevant manifest, result, batch,
and target records may include `target_mode`, `max_used_percent`,
`target_used_percent_at_selection`, `target_total_bytes_at_selection`,
`target_used_bytes_at_selection`, `target_free_bytes_at_selection`, and
`target_selection_phase`; the batch aggregate also includes
`selection_policy`. Occupancy-related skips retain their reason and available
selection evidence. These properties are optional; Storage Benchmark result,
manifest, and batch records for the existing `all_internal` and
`selected_target` modes do not require the low-occupancy selection evidence.
Normal profile serialization, including `profile_used.json`, may retain the
additive `max_used_percent` default, but it has no effect outside the
low-occupancy target mode.

When selected through `stages[].modules.storage_benchmark`, the benchmark is a
completion-based stage. Its artifacts are rooted at `storage_benchmark/` inside
the normal validation run directory. All-internal mode writes its aggregate JSON
and text at that root and keeps each drive's normalized, health, manifest, and
`raw_fio/` artifacts in a device-named child directory. Compact status and
verdict information is retained in the normal run manifest stage window and
executed plan; raw fio payloads are never embedded there.

## GPU Allocation Feasibility and OpenCL Timing v1

`GpuWorkerSpec.allocation_feasibility` and worker
`allocation_feasibility` use `contract: gpu_allocation_feasibility_v1`.
The orchestrator retains the separate `planned_allocation_feasibility` so that
runtime discovery/backoff cannot overwrite planning evidence. Assigned targets
are not reduced to fit these plans. `planned_allocation_chunks` remain advisory
geometry, not executable worker commands. Incomplete plans do not establish
successful allocation or readback.

EGL geometry is shared between planning and execution: start with the worker
hint, grow texture dimensions only as needed to fit the assignment within the
existing 512-object **software** bookkeeping budget, and respect actual
`GL_MAX_TEXTURE_SIZE`. Unknown discovery is provisional, requiring a successful
runtime GL query. Whole objects never exceed the assignment. Allocation failure
retains existing smaller-texture backoff and reserve claims; the resulting
nominal limit/shortfall remains explicit. Nominal texture bytes do not prove
physical residency. OpenCL feasibility exposes its unchanged chunk/count policy
(safe non-discrete: up to 1024 objects of at most 64 MiB), separately from API
single-allocation limits, runtime reserve caps and actual allocation progress.

OpenCL worker `allocation_timing_evidence` uses
`contract: opencl_allocation_timing_v1`. Fixed operation summaries retain count,
host monotonic elapsed/process CPU seconds, maximum and time correlation for
buffer creation, initial touch enqueue/finish, recurring fill enqueue/finish,
blocking readback, existing atomic result persistence, and existing sleep/yield.
Counts of raised exceptions are not counts of nonzero API return codes; the
worker's existing API failure counters remain authoritative. Loop accounting
separates `attempted_loop_count`, `completed_loop_count`,
`interrupted_loop_count` and `loop_in_progress`; attempts equal completed plus
interrupted plus any active iteration. Exceptions, cancellation and caught
persistence/verification errors cannot mark that iteration completed. Completed
and interrupted elapsed seconds are separate; `observed_loop_seconds` includes
both. `allocation_progress_evidence.loop_iterations` counts completed iterations;
`authored_frames` preserves the worker's frame counter separately. Accounting
also reports elapsed time and unaccounted time (Python work,
guard calls, verification comparison and scheduling; not a causal attribution).
Only the latest 32 operations lasting at least 0.25 seconds are retained, with
an overwrite count and all-operation maxima. No event triggers an extra write.
Each JSON write contains prior completed persistence observations; terminal
`LVS_OPENCL_ALLOCATION_TIMING` stderr includes the final completed write. An
unclean exit may omit that final evidence. Timing neither proves GPU execution
time nor isolates driver latency from host descheduling.

`allocation_progress_evidence` (`opencl_allocation_progress_v1`) separates
iteration/object counts, API allocation failures, runtime-guard intervention,
object-limit attainment and target attainment. A target miss without failures
is not capacity exhaustion. Compatibility WorkerResults preserve these
versioned dictionaries unchanged; GPU validation details expose
`AllocationFeasibility`, `PlannedAllocationFeasibility`,
`AllocationTimingEvidence` and `AllocationProgressEvidence`. Extended/report
evidence uses snake_case. Missing historical evidence remains unavailable.
Existing 60%/85% attainment bands, sampled-readback requirements, and memory
reserves are unchanged.

### Authoritative GPU Allocation Safety v1

`allocation_safety` (`contract: gpu_allocation_safety_v1`) is resolved once from
memory classification evidence and bound through worker specs, materialization,
launch environment and native Vulkan arguments. `device_class` remains topology
and tuning evidence, never authorization to bypass memory guards. Only high-
confidence dedicated memory with a positive independently reported capacity and
nonconflicting classification source may set
`device_memory_requires_system_guard=false`. Shared, unknown, missing,
low-confidence or conflicting evidence remains guarded, including discrete GPUs.
Runtime revalidates the propagated evidence; a bare exemption boolean is not
sufficient. `host_memory_requires_system_guard` is always true. Vulkan compute
fixed host staging and transfer host staging are budgeted separately even on
dedicated GPUs; shared transfer accounts for both device and staging allocations.
Actual Vulkan alignment requirements are checked against the assignment and
additional protected bytes require claims. Dedicated exemptions require a
device-local Vulkan memory type, not a fallback to unguarded host memory.

Guarded growth requires a configured, permitting runtime guard. Dedicated device
bytes do not consume RAM allowance but still honor emergency termination.
Successful protected claims are tracked per worker, failed attempts release
their claims, and confirmed cleanup releases outstanding claims once. Incomplete
cleanup retains claims conservatively; outstanding bytes/cleanup errors remain
diagnostic evidence. Workers also poll emergency state without adding GPU waits.
This is allocation safety evidence, not proof of physical residency.

Final safe assignments are never raised by materialization or retuning. Current
minimum executable assignments are 64 MiB for EGL/OpenCL VRAM, 8 MiB for Vulkan
compute and 16 MiB for Vulkan transfer. Smaller assignments produce explicit
`infeasible_gpu_assignments` and block launch, not hardware-failure verdicts or
silent floors. Original requests, assigned/planned targets,
`materialized_target_bytes` and runtime targets remain distinct. Existing
percentage policy, reserve and 60%/85% attainment thresholds are unchanged.
Compatibility exports retain `allocation_safety` and expose `AllocationSafety`;
missing historical safety evidence remains unrecorded.

## GPU correction follow-up: scheduling and observed evidence

EGL VRAM initialization now clears each newly allocated texture using the same
index/phase color contract as readback and immediately samples it. Recurring
texture samples are due by monotonic elapsed time (one second), not frame 180;
a safe normal shutdown samples 0/middle/final at the last written phase again.
These are sampled texel checks, not exhaustive byte coverage. Deadlines are also
checked inside clear sweeps at texture-write boundaries, so a slow frame does
not gate recurring samples. A driver call can exceed the interval; it is not a
hard wall-time guarantee.
Emergency memory stops and recorded errors skip additional final GPU work.
`vram_verification_satisfied` requires a positive texture-readback count and zero
recorded errors; render/marker checks alone cannot establish VRAM verification.
`egl_selected_device` and `egl_device_exact_match` persist the existing runtime
binding observation (also `EglSelectedDevice`/`EglDeviceExactMatch` in normalized
GPU details). They do not strengthen the underlying targeting decision.

OpenCL's bounded object budget is unchanged. When a positive API maximum permits,
`opencl_buffer_geometry()` raises chunk size only enough to fit the assignment
within that budget, aligned to 4096 bytes and bounded by the API maximum and
assignment. Unknown API limits do not authorize this growth. API limits,
runtime backoff and runtime safety caps remain distinct feasibility evidence;
successful allocation and physical residency are never inferred from a plan.
During successful growth, full-buffer initialization plus its completion wait
replaces the same iteration's recurring refill. Existing recurring work resumes
when no allocation completes. Periodic sampled readback and queue synchronization
remain enabled, with unchanged verification intervals. Worker evidence records
`allocation_initialization_replaced_refill` and the bounded integer aggregate
`allocation_refill_replaced_iteration_count`; existing operation timings capture
initialization versus recurring work and interruptions. This policy does not
guarantee a target can be attained in a particular elapsed duration.

Parsed `VramAllocationPercent` and per-GPU `MaxAllocationPercent` use assigned
targets, not ramped active targets. `AssignedTargetVramBytes`,
`ActiveNominalAllocationPercent` and `MaxActiveNominalTargetBytes` retain that
distinction. `TextureVerificationPasses` and `RenderVerificationPasses` are
separate observed counts; the historical aggregate remains generic checks,
not successful texture verification. Missing historical counts remain absent.
Advanced Debug filters only command stdout: return codes, stderr and collection
exceptions are retained, with explicit bounded-output truncation markers.

## OpenCL bounded readback batches and coalesced persistence

The OpenCL VRAM queue remains in-order (creation properties zero). Each due
verification retains the existing selected buffers (0/middle/last on shared
devices, latest initialized on the established discrete safe path), sample
word counts, independent expected values and verification intervals. Up to
three reads enqueue into disjoint fixed host slots, then one `clFinish` and
per-event `CL_COMPLETE` checks precede all CPU inspection. No writes or growth
overlap that batch. Asynchronous failure or incomplete events cannot establish
verification. A failed enqueue/completion drains pending work; if completion
cannot be confirmed, host storage/events remain retained and claims stay charged.
Cancellation completes ownership cleanup rather than abandoning DMA pointers.

`readback_batch_policy`, `readback_batch_count`,
`readback_enqueued_sample_count`, `readback_pending`,
`readback_retained_event_count` and `readback_staging_bytes` are additive worker
evidence. Enqueued/completed counts alone do not prove error-free verification.
The at-most-12-KiB host sample pool is separately included in stage budgeting and
runtime growth claims, even for dedicated GPUs; it is not device VRAM coverage.
Dedicated device bytes remain outside the RAM pool. Missing host resources block
allocation rather than disabling that protection.

Existing `opencl_allocation_timing_v1` observations remain readable.
`blocking_readback` retains its historical meaning; new batches separately time
`readback_enqueue`, `readback_batch_finish`, `readback_event_status`, and
`readback_recovery_finish`. Compare their combined host costs, sample counts and
worker duration against historical per-sample blocking reads, not wait-call counts
alone. Initial-touch and recurring-fill completion timing remains unchanged.
No driver-latency or physical-throughput improvement is inferred from batching.

Ordinary progress persistence is coalesced to two monotonic seconds after the
previous write attempt completes, independent of object/frame count. Initial,
new arithmetic-error, allocation-backoff/failure, and final writes remain forced.
Atomic replacement, flushing, fsync and terminal stderr timing are retained.
`result_publication_interval_seconds`, `result_publication_deferred_count` and
`result_write_count` document this cadence; write/fsync errors remain explicit.
Blocking API/filesystem calls can delay publication beyond the nominal interval.
This does not change workload geometry, allocation concurrency, assigned targets,
safety reserves, or the 60%/85% attainment rules. It does not claim exhaustive
verification or physical residency.

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

## GPU cleanup completion evidence

Explicit `allocation_claim_cleanup_error` (compatibility detail:
`AllocationClaimCleanupError`) blocks overall worker success even if earlier
computation/readback verification passed. OpenCL compute publishes
`cleanup_complete` / `CleanupComplete` after resource and claim cleanup and
retains verification counts separately; a cleanup error is not an arithmetic
mismatch. Compatibility GPU details also preserve
`OutstandingSystemMemoryClaimBytes`. A positive outstanding claim count alone
does not establish a cleanup failure. Historical records without these fields
retain their existing interpretation; no cleanup evidence is synthesized.

### Vulkan compute descriptor bounds

The compute worker uses two uint32 push constants: `logical_words` at byte 0
and `descriptor_words` at byte 4. The host validates positive logical work
within the exact descriptor byte range (not aligned allocation size), with
4-byte alignment and uint32 capacity limits. Both unsigned bounds guard every
shader data access, including multidimensional padding. No `OpArrayLength` is
used in production: the October 26 RTX 5090 diagnostic returned zero for a
3 GiB view while its 1 GiB view returned the correct length. This changes no
allocation target or integrity requirement. The bounds ABI was introduced in stateful v22 and hash/stress-hash v10;
stateful v23 retains it. Historical observations remain unchanged.

### Execution completion and unfinished captures

New run manifests start with `verdict=running`, `execution_state=running`;
finalization records the terminal verdict and `execution_completion` evidence.
An offline/copy reader does not infer that a process is alive from a recorded
running state. Missing run endpoints or finalized stages yield INCOMPLETE,
not PASS; recorded aborts/interruption and explicit failures remain distinct.
PASS requires the recorded run endpoint, terminal stage endpoints/outcomes and
completion of enabled runnable stages. Worker errors, forced kills and explicit
cleanup failures cannot be overridden by stale positive snapshots. Unknown
cleanup remains unknown; retained claims do not prove physical memory leakage.

The shared completion assessment is exported as `ExecutionCompletion` in
compatibility output and `run.execution_completion` in compiled report data.
Results listing, summaries, overview and pre-import/QA validation use the same
assessment. Legacy results retain their own recorded terminal evidence; no
historical artifacts are rewritten. Missing kernel captures do not establish
absence of kernel faults, and successful arithmetic does not establish an
error-free driver lifecycle.

### Opt-in AMD Vulkan per-dispatch timestamps

`dispatch_timing_evidence` (`linux_validation_suite.vulkan_dispatch_timing`, v1)
is enabled only by `LVS_AMD_VULKAN_DISPATCH_TIMING=1` with an exact
`LVS_AMD_VULKAN_DIAGNOSTIC_SLOT`. It records bounded per-dispatch compute-stage
brackets, submission/fence timing and geometry separately from verification.
Unsupported timing/journal evidence blocks observation. A selected-device kernel
fault stops the diagnostic; a stop sidecar does not assert cleanup. The diagnostic itself does not alter production allocation, arithmetic or
verification. Stateful submission grouping is described below.
See [operator procedure](docs/amd_vulkan_dispatch_timing_diagnostic.md).

### Stateful Vulkan submission partitions

Stateful-memory worker v23 uses one buffer per sequential submission, independently
of vendor. Allocation targets, descriptor ranges, recurrence rounds and sampled
verification are unchanged. `submission_partition_policy`, `submissions_per_cycle`,
`cycle_completed_submissions`, `incomplete_cycle` and `buffer_dispatch_counts`
distinguish completed work from an interrupted cycle. `cycle_count`/frames and
final verification advance only after all partitions complete. GPU batch timing
counts individual submissions; cycle latency covers the full cycle. Hash and
stress-hash batching retain their existing policy. Missing terminal cleanup
continues to mean unknown, not successful cleanup or proven physical leakage.

## Explicit VNNI integer dot-product development contracts

Native CPU kernels `avx_vnni` (256-bit VEX) and `avx512_vnni` (512-bit EVEX)
add `avx_vnni_v1` / `avx512_vnni_v1` verification and corresponding
`*_progress_v1` contracts. Their `operation_family` is
`u8_s8_dot_product_accumulate`, never FP32 FMA. `verification_method` is
`wide_integer_dot_reference_modulo_2_32`; `actual_isa`,
`execution_implementation`, `isa_capability_source`, per-thread
`vnni_capability` CPUID/XCR0 fields, `active_int32_lanes`, `products_per_lane`,
`accumulator_chains`, `dot_rounds_per_block`, all-thread phases, error details
and verified/interrupted counts establish the versioned evidence boundary.
The existing progress time base, targeted CPU IDs and publication semantics
are reused without changing either FP32 v1 contract. Derived byte products/s
are arithmetic work counts, not measured instruction rate, performance targets
or a saturation verdict. Emulation identifies `test_integer_emulation` and
`test_override`; it cannot establish physical ISA acceptance.

The legacy export preserves each recognized VNNI worker record intact, including
failed records, and retains supplementary progress analysis. No historical
records are synthesized or reclassified. Explicit VNNI stages do not become a
new ordinary SIMD tier or an invented legacy AVX bucket. Reports keep selected
kernel, actual kernel and successful versioned verification separate from prior
physical acceptance. Missing, contradictory or incomplete verification blocks
worker success. See [the implementation contract](docs/vnni_dot_product_contract.md).

## Explicit SVE2 signed widening integer arithmetic

`sve2_smlal_v1` verification and `sve2_smlal_progress_v1` progress identify the
explicit-only `sve2_smlal` native CPU workload. Operation family
`s16_widening_multiply_accumulate_bottom_top` and independent method
`wide_integer_smlal_reference_modulo_2_32` are distinct from FP32/FMA and VNNI.
Eight accumulator chains, 256 rounds, `even_odd_halfwords` mapping and per-thread
HWCAP/HWCAP2, inherited VL, int32 lane count, affinity and verification phases
are authoritative contract evidence. Missing or contradictory evidence blocks
success; software emulation remains labelled `test_integer_emulation` with
`test_override` sources. This is not physical acceptance.

The existing bounded progress time base is reused with per-thread
`vector_length_bytes` and `active_int32_lanes`. Derived signed products/s are
arithmetic work counts, not measured instructions or saturation. Reports preserve
selection, execution and successful verification separately; legacy exports
retain whole recognized records, including failed/incomplete evidence. Optional
helper readiness additionally records `sve2_build_status` where collected.
No historical result is synthesized or reclassified. See the
[SVE2 implementation and acceptance contract](docs/sve2_smlal_contract.md).

## Explicit NEON signed/unsigned byte dot products

`neon_dotprod_v1` and `neon_dotprod_progress_v1` identify the explicit-only
`neon_dotprod` native CPU workload. Operation family
`s8_s8_and_u8_u8_dot_product_accumulate` uses the independent
`wide_integer_dot_reference_modulo_2_32` method: eight chains (four signed and
four unsigned), four int32 lanes, four byte products/lane and 256 rounds/block.
Actual production execution is `aarch64_neon_dotprod_intrinsics` / `asimddp`, with
per-thread Linux common HWCAP, affinity, phase and reconciled verified-block
counts. Software fixtures remain explicitly labelled `test_integer_emulation`.
Missing or conflicting evidence prevents success. Existing bounded timestamped
progress reports derived byte products/s, not measured instructions, saturation
or physical acceptance. Compatibility exports retain whole recognized records,
including failures. Native readiness records `dotprod_build_status` where
collected, separately from runtime availability and executable identity.
See the [DotProd workload and acceptance contract](docs/neon_dotprod_contract.md).

## Explicit NEON I8MM matrix arithmetic

`neon_i8mm_v1` and `neon_i8mm_progress_v1` identify the explicit-only native
I8MM workload. Operation family
`s8_s8_u8_u8_u8_s8_matrix_multiply_accumulate_2x8_8x2` uses
`wide_integer_matrix_reference_modulo_2_32`, distinct from DotProd groupings.
Matrix layout is `a_row_major_b_column_major_c_row_major`; eight chains split
3 signed / 3 unsigned / 2 mixed, four int32 lanes, eight products per lane and
256 matrix rounds per block are authoritative metadata. Runtime implementation
is `aarch64_neon_i8mm_intrinsics`, actual ISA `i8mm`, with per-thread common
HWCAP/HWCAP2_I8MM and pinned affinity. All phases and counts must reconcile.
Missing or conflicting matrix/capability/lifecycle evidence cannot establish
success. Labelled test emulation is not physical instruction evidence.

The bounded timestamped progress contract records verified work and errors;
derived products/s are not measured retired instructions, saturation or physical
acceptance. Reports preserve selected versus actual execution and software
verification; compatibility exports retain whole recognized worker records,
including failed/incomplete ones. Captured native readiness adds
`i8mm_build_status` where available, separately from runtime availability and
executable identity. See the [I8MM workload contract](docs/neon_i8mm_contract.md).


## Explicit NEON FP16 and FHM

`neon_fp16_v1` / `neon_fhm_v1` and corresponding `_progress_v1` sidecars record
experimental explicit-only finite fused arithmetic. The method is
`integer_significand_rne_fused_reference`, comparison `bit_exact`, with eight
chains, 256 stress rounds, one witness round, 16-bit inputs, and 8/4 active lanes
with 16/32-bit accumulation. Operation families are `fp16_fused_multiply_add` /
`fp16_product_fp32_fused_accumulate_low_high`; FHM mapping is
`paired_low_high_halfwords`, FP16 mapping `all_eight_halfwords`.

Native implementations are `aarch64_neon_fp16_asm` / `aarch64_neon_fhm_asm` with
actual ISA `asimdhp` / `asimdfhm`. Labelled `test_half_emulation` is software-only.
Each thread records FPCR, independently required HWCAP, exact pinned CPU identity,
all verification phases, verified/interrupted work and errors. Missing,
incompatible or failed evidence prevents successful worker classification.
Reports distinguish derived lane-FMAs from measured instruction retirement or
saturation; complete failure records survive compatibility exports. Helper
readiness adds `fp16_build_status` and `fhm_build_status` independently of runtime
availability and executable identity. See the
[FP16/FHM workload contract](docs/neon_fp16_fhm_contract.md).
