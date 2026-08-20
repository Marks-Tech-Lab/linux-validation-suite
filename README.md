# Linux Validation Suite (LVS)

Linux Validation Suite (LVS) is a profile-based hardware validation and
stress-test orchestrator for Linux systems. It runs repeatable CPU, RAM, GPU,
VRAM, and storage validation workflows, collects Linux telemetry, checks
dependencies and readiness, and exports structured result folders for later
review.

## Current Platform Support

Linux Validation Suite supports x86_64 and AArch64 Linux. Support is
architecture-specific: x86 vector execution covers the verified SSE/AVX
families available across the complete targeted CPU set, while AArch64 native
vector execution currently uses NEON. Explicit architecture-specific ISA
requests fail closed when unavailable rather than silently substituting
another ISA or backend.

This is not a generic guarantee for every ARM architecture or platform. SVE,
SVE2, and SME are not implemented, and unrelated architectures such as RISC-V
are outside the current support guarantee. Hardware and telemetry coverage
still depends on the CPU, GPU, driver, kernel, firmware, and system tools
available on each host.

## Public Alpha

The public repository is
[`Marks-Tech-Lab/linux-validation-suite`](https://github.com/Marks-Tech-Lab/linux-validation-suite),
with `main` as the published branch. Alpha releases are published as
pre-releases. The current release is `v0.3.1-alpha`, a corrective alpha for the
Heatsoak startup regression in `v0.3.0-alpha`. It preserves that release's
first-class AArch64 support and cross-architecture CPU, power, memory, GPU,
profile, and evidence validation.

The `v0.2.0-alpha` tag contains the Storage Health and Storage Benchmark
baseline. The `v0.3.0-alpha` release builds on that historical boundary. See
[ROADMAP.md](ROADMAP.md) for completed, deferred, and undecided project status.

Linux Validation Suite (LVS) is licensed under the MIT License. This alpha is
intended for early validation and feedback; hardware-sensitive and experimental
areas are identified below.

## Fresh Clone And First Run

### Core and Python requirements

Python 3.14 is the currently tested version. The code requires Python 3.10 or
newer because it uses modern typing syntax. Newer Python versions are allowed,
but run the smoke tests before relying on an untested interpreter version. The
baseline Python requirements include the established Textual dependency used by
the TUI.

From the repository root, create the ignored local virtual environment and
install baseline dependencies:

```bash
./scripts/setup_venv.sh
```

The script prefers `python3.14`, falls back to `python3`, and stops with a clear
error if the selected interpreter is older than Python 3.10. Override
interpreter selection when needed:

```bash
PYTHON=/path/to/python ./scripts/setup_venv.sh
```

Activate the environment, or call its Python directly:

```bash
source .venv/bin/activate
.venv/bin/python linux_validation_suite.py
.venv/bin/python linux_validation_suite_tui.py
.venv/bin/python smoke_tests/run_smoke_tests.py
```

### Native helper build requirements

A fresh clone needs `gcc` or a compatible `cc` when LVS must build its native
CPU and memory helpers. Helpers are built for the architecture on which LVS is
running. An AArch64 host therefore needs an AArch64-capable native compiler; it
does not need an x86 cross-compiler merely because LVS also supports x86_64.

### Capability-dependent system backends

System backends are installed and configured separately from the Python virtual
environment. They are capability dependent rather than universal requirements:

- `stress-ng` enables applicable CPU/RAM workloads and participates as a Power
  Auto candidate.
- A Vulkan loader and usable hardware GPU driver enable Vulkan compute,
  transfer/readback, and stateful-memory workloads.
- An OpenCL ICD loader and applicable GPU runtime enable OpenCL workloads.
- EGL/GLES libraries and a hardware renderer enable EGL/GLES workloads.
- `fio` with the `libaio` engine enables Storage Benchmark.
- `nvme-cli` and `smartmontools` provide applicable storage-health coverage.
- Vendor utilities such as `nvidia-smi` and `intel_gpu_top` add telemetry where
  the matching hardware and driver expose it.

LVS does not silently install system packages. Use Dependency Check and
Readiness/Dry Run to determine which capabilities are available on a particular
host and which are required by the selected profile.

On first launch, the suite uses `settings/global_settings.example.json` as the
initial settings payload and writes the ignored local file
`settings/global_settings.json`. The committed example uses end-user mode and
leaves Google Drive credentials and destination settings empty, with upload
prompts and move-after-upload disabled.

Google Drive integration is optional. Without credentials and a configured
destination it remains unavailable, while local execution and result review
continue normally. Install its optional Python dependencies only when needed:

```bash
.venv/bin/python -m pip install -r requirements-google.txt
```

Storage tooling is also optional for the base suite. `fio` with the `libaio`
engine is required to run Storage Benchmark. `nvme-cli` enables NVMe SMART
health, while `smartmontools` provides the preferred optional `smartctl`
provider for ATA/SATA/SAS and fallback SMART coverage. If all detected NVMe
drives are covered by `nvme-cli`, missing `smartctl` is reported as a missing
preferred provider rather than a failure.

The repository scaffolds these local runtime locations with `.gitkeep` files:

- `results/`
- `results/Archived/`
- `results/Uploaded/`
- `sensor_probe_logs/`

Their runtime contents are ignored. Result, upload, archive, and sensor-probe
workflows create their required output directories as needed.

Old retained results are not required for normal use or public smoke tests.
Maintainers may optionally keep ignored local retained-result mappings in
`hardware_result_validation_state.json` and refresh them from current results
with:

```bash
.venv/bin/python -m Modules.lvs_hardware_matrix_state rebuild
```

## Current Focus

- CPU and memory stress validation with Linux telemetry
- suite-native Vulkan/OpenCL/EGL GPU workloads
- VRAM allocation and verification workloads
- internal-drive inventory and normalized SMART/NVMe health enrichment
- fio-backed, file-based Storage Benchmark workflows
- result folder summaries and legacy-compatible JSON
- diagnostics and dependency checks for field troubleshooting
- optional Google Drive upload support
- public-safe support summaries and guarded local migration/restore tooling
- QA review payloads for result readiness, import readiness, comparison
  context, and escalation decisions

## Supported Operator Entrypoints

Use the QA wrapper for non-interactive JSON review payloads:

```bash
.venv/bin/python linux_validation_suite_qa.py review "results/<result-folder>"
.venv/bin/python linux_validation_suite_qa.py batch "results/<result-a>" "results/<result-b>"
```

`linux_validation_suite.py` remains the CLI compatibility entrypoint.
`linux_validation_suite_tui.py` is the operator TUI.
`linux_validation_suite_qa.py` is for external QA tooling and should not be
used as an import-policy automation layer or hardware-specification judge.

The CLI provides both profile-based validation runs and a standalone Storage
Benchmark utility at **Run Tests > Run Storage Benchmark**. The TUI supports
profile selection, editing, readiness review, run execution, and result review;
Storage Benchmark is available there as a completion-based profile module.

## Result Folders And Artifacts

Runs write timestamped folders under `results/` by default. A complete result
commonly includes:

- `run_summary.txt`
- `parsed_results_custom.json`
- `parsed_results_extended.json`
- `run_manifest.json`
- `telemetry_source_map.json`
- `raw_telemetry.csv`
- `system_info.json`
- `profile_used.json`
- `worker_results/`

For QA review, prefer the QA wrapper payload over parsing report text or dense
raw telemetry directly. The wrapper summarizes suite evidence and existing
validation outcomes; it does not look up or infer external hardware standards.

Storage Benchmark writes normalized JSON and TXT summaries, before/after
storage-health snapshots, a manifest, separate raw fio JSON, and optional
storage telemetry. Profile-stage artifacts are placed under
`storage_benchmark/` in the normal validation result. Raw fio and raw SMART
provider payloads are not embedded in normal `system_info.json` or parsed
results; system inventory contains only normalized storage-health fields and
source/status notes.

## Storage Health / SMART

LVS enriches local whole-drive inventory with internal/removable/USB
classification and read-only health evidence where the operating system and
optional providers expose it:

- `nvme-cli` supplies NVMe SMART/health data.
- `smartctl` from `smartmontools` is the preferred optional provider for
  ATA/SATA/SAS devices and fallback SMART coverage.
- Normalized fields may include overall SMART health, temperature, power-on
  hours, wear or percentage used, available spare, media errors, unsafe
  shutdowns, host reads, host writes, and lifetime write totals/TBW where available.
- Unsupported devices, permission limits, sleeping drives, and absent optional
  providers are reported as coverage/status notes rather than invented values.

Missing `smartctl` is not a failure when detected NVMe drives have health
coverage through `nvme-cli`. Installing both optional providers gives the
broadest coverage.

## Storage Benchmark

Storage Benchmark is a KDiskMark/CDM-style workload implemented with `fio`. It
is available as a standalone CLI utility and as a completion-based profile
module. It supports a selected eligible internal-drive workspace or a
sequential all-internal-drive run.

The benchmark is file-backed: it creates real, bounded LVS-owned temporary
files in the selected filesystem, performs direct I/O through `fio`, and removes
only its validated session files afterward. Raw block-device paths are never
accepted. Test size is limited to 1–8 GiB, and the CLI previews estimated
maximum writes before confirmation.

Root/system-drive benchmarking is excluded by default. Including it requires
explicit opt-in (`BENCHMARK ROOT` in the standalone CLI, or the corresponding
profile setting), and a completed root/system-drive result is forced to at
least `WARN`. Single-device CoW/Btrfs workspaces are supported with warnings;
their results may differ from raw-device or simpler non-CoW filesystem
behavior. Unresolved multi-device, virtual, removable, USB, and network-backed
mappings are ineligible.

Profiles may also opt into
`target_mode: all_internal_non_root_low_occupancy`. This mode selects only
eligible internal non-root drives whose deterministically selected writable
filesystem/workspace is at or below `max_used_percent`, which defaults to
`3.0`. Occupancy is measured from that selected filesystem/workspace, not
inferred from raw disk contents, and does not account for unmounted filesystems
on the same physical drive. Root/system drives are always excluded. Occupancy
and free space are rechecked immediately before each drive starts; if usage has
risen above the threshold, that drive is skipped before `fio` runs. Existing
USB, removable, network, virtual, ambiguous multi-device, and CoW/Btrfs safety
policies remain in effect.

Committed storage profiles are:

- `Storage Benchmark Quick`: one-run completion-based sequential benchmark of
  eligible internal drives; root/system drives are excluded by default.
- `Storage Benchmark Sequential`: five-run completion-based sequential
  benchmark of eligible internal drives; root/system drives are excluded by
  default.
- `Quick Test`: now ends with a one-run Storage Benchmark stage. Its committed
  profile explicitly opts into the root/system drive, so that stage is reported
  with at least `WARN` when the system drive is benchmarked.

`Storage Benchmark Quick` and `Storage Benchmark Sequential` remain unchanged
`all_internal` profiles. The low-occupancy mode is available for explicitly
configured profiles but is not their default.

## Enhanced Telemetry

Enhanced telemetry is session-scoped. At CLI or TUI launch, the suite may ask
whether to enable it for that session. Enabling it prepares sudo-backed
telemetry probes where available; the suite does not store the sudo password.

Enhanced telemetry can produce
`telemetry_privilege.source_mode: sudo_telemetry` when sudo-backed sources are
actually used. Skipping it produces normal-user telemetry and should be
expected to omit some privileged CPU package power or DIMM identity evidence
on some systems.

Advanced debug logging is separate from enhanced telemetry. Debug logging
affects additional logs/artifacts; it is not the control for sudo telemetry.

## Safety

Stress testing can expose unstable hardware, cooling, driver, firmware, or
power-delivery issues. Run with appropriate cooling, supervision, and data
backups. The suite reports telemetry where Linux exposes it, but missing or
limited telemetry is common across vendors and distributions.

## Current Status

Available workflows include:

- CLI profile selection, dry run/dependency checks, run setup, execution,
  result review, standalone Storage Benchmark, upload prompts, and pre-import
  sanity.
- TUI operator workflow for profile review, setup recall, dry run, run launch
  and cancellation, live status, post-run review, result review, validation,
  pre-import sanity, comparison, artifacts, upload workflow, and core settings.
- QA wrapper JSON contracts for single-result and batch review.
- A public hardware/result coverage matrix with optional local result mappings.
- Storage Health inventory enrichment plus standalone and profile-based Storage
  Benchmark workflows, including sequential all-internal mode.
- CLI and TUI Migration / Support workflows for public-safe support export,
  explicitly acknowledged private migration bundles, restore preview, and
  confirmed restore apply. Restore never overwrites existing local files;
  conflicts are staged for manual comparison, and bundle manifests, checksums,
  paths, and symlinks are validated before use.

The runtime version is `0.3.1-alpha`, corresponding to the `v0.3.1-alpha`
pre-release tag. Passing smoke runs capture expected interactive output instead
of dumping CLI/TUI setup screens; failures still retain their assertion
diagnostics.

Migration bundles exclude secrets, Google credentials, result contents,
sensor-log contents, vendor/test data, `.venv`, caches, and private identifiers
by default. The public-safe support export is shareable; a private migration
bundle is not.

Still experimental or hardware-sensitive:

- GUI support is not currently implemented; future scope is TBD.
- Some GPU backend variants and lab profiles.
- Sensor coverage that depends on vendor/kernel exposure.
- Automated packaging and dependency installation.

Future hardware validation modules are TBD. Future work may include additional
workload modules and hardware-specific validation flows, but they are not
committed release scope.

Phase 1 contract clarification and Phase 2A artifact identity work are complete.
The coordinated canonical `parsed_results.json` migration remains deferred;
`parsed_results_custom.json` and its compatibility aliases remain unchanged.
New feature fields must continue to follow the forward-only snake_case and
semantic-unit policy in `OUTPUT_CONTRACT_INDEX.md`.

## Release Notes — v0.3.1-alpha

Linux Validation Suite v0.3.1-alpha is a corrective alpha release for the
Heatsoak startup regression in v0.3.0-alpha. It preserves the architecture,
Power Auto, profile, and result behavior introduced in that release.

### Fixes

- Fixed Heatsoak exiting before worker launch because its unlogged runtime path
  referenced Python's `tempfile` module without importing it.
- Improved CLI launch-error containment so launch failures are reported to the
  operator without escaping the CLI session.
- Added regression coverage through the real shared Heatsoak manager, runner,
  Power Auto materialization, CLI, and TUI execution paths.

### Validation

- Confirmed a real AArch64 Heatsoak launch using the shared service path.
- Power Auto selected the expected `thermal_validated_fallback` path when
  package-power telemetry was unavailable.
- Real Python CPU and Qualcomm Adreno Vulkan workers launched, ran briefly, and
  were cleanly reaped through normal cancellation.
- The complete non-hardware smoke suite passed: 241/241.
- All 65 profiles validated successfully.

### Compatibility

No profile, configuration, result-schema, workload-policy, or operator migration
is required. Ordinary CPU Auto and existing v0.3.0-alpha compatibility behavior
remain unchanged.

This remains an alpha release.

## Release Notes — v0.3.0-alpha

Linux Validation Suite v0.3.0-alpha adds first-class AArch64 execution alongside
x86_64 and substantially improves CPU, power, memory, GPU, profile, and result
evidence behavior. It remains an alpha release intended for early hardware
validation and operator feedback.

### Highlights

- Added supported AArch64 execution, validated on Qualcomm Oryon and a Qualcomm
  Adreno integrated GPU.
- Added architecture-aware CPU instruction intent and heterogeneous-core-safe
  targeting.
- Added measured cross-backend Power Auto selection with truthful fallbacks
  when package-power telemetry is unavailable.
- Unified RAM and shared-GPU memory planning to prevent double counting and
  unsafe overcommit.
- Improved Vulkan compute, transfer/readback, stateful-memory, APU, and
  multi-GPU execution.
- Expanded verification, affinity, utilization, allocation, and worker evidence
  while preserving legacy result compatibility.
- Converted the standard PL, QA, and Quick profiles to architecture-portable
  CPU intent.
- Added an optional low-occupancy, non-root internal-drive Storage Benchmark
  target mode.

### Supported architectures

- x86_64 Linux
- AArch64 Linux

Support is architecture-specific rather than generic support for every ARM
version or unrelated architecture. AArch64 native vector execution currently
uses NEON; SVE, SVE2, and SME are not implemented. Explicit ISA requests remain
architecture constrained and fail closed when unavailable.

### AArch64 support

- Added AArch64 architecture detection, helper readiness, topology, targeting,
  affinity, telemetry, and result-evidence policy.
- Added native AArch64 scalar and NEON CPU paths, verified stress-ng and Python
  CPU paths, and native, stress-ng, and Python RAM paths.
- Added platform plus PCI/DRM GPU discovery and verified Vulkan operation on
  Qualcomm Adreno.
- Preserved truthful behavior when CPU clocks, package watts, or other platform
  telemetry are unavailable.

### CPU and Power validation

- CPU targets now use the intersection of online CPUs and the process-allowed
  affinity set, including sparse and nonzero allowed CPU sets.
- Improved physical/logical topology, SMT grouping, Intel P/E hybrid-core
  detection, and CPUID-based P/E classification.
- Native ISA selection uses the common safe capability set across every
  targeted CPU, supporting heterogeneous-core-safe execution across verified
  SSE, AVX, AVX2, and AVX-512 tiers.
- Added `baseline_vector`, `high_throughput_vector`, and
  `highest_verified_vector`. On AArch64, the current baseline and
  high-throughput tiers both resolve to NEON and disclose that tier collapse.
- Exact ISA requests keep their explicit meaning and fail closed when the
  architecture or complete target CPU set cannot provide them.
- Power Auto is separate from ordinary CPU Auto. It compares viable native
  kernels, stress-ng matrixprod, and Python PBKDF2 candidates using measured
  CPU/package power when trustworthy telemetry exists.
- When trustworthy package-power telemetry is unavailable, Power Auto uses an
  explicitly reported architecture-appropriate fallback. The validated
  AArch64 fallback is based on thermal testing, while x86_64 uses a
  compatibility/capability fallback.

### Memory and GPU improvements

- Unified RAM and shared-GPU memory budgeting with one system reserve, exact
  worker assignments, launch-time planning, and a runtime allocation guard.
- Prevented shared system memory from being counted independently as both RAM
  and integrated-GPU memory, while keeping dedicated VRAM outside the shared
  system-memory pool.
- Fixed Python RAM continuous verification across the zero-pattern transition,
  retained stress-ng final verification and metrics, and improved native RAM
  final verification evidence.
- Added platform plus PCI/DRM GPU discovery, including Qualcomm Adreno, and
  improved integrated/discrete classification, AMD APU selection, and
  small-dGPU selection.
- Improved Vulkan compute/readback, transfer/readback, stateful-memory,
  shared-heap selection, allocation-count splitting, buffer planning, and
  integrated-GPU memory handling.
- Stabilized GPU telemetry association by physical platform/card/slot identity
  and improved multi-GPU execution across exercised Intel, AMD, NVIDIA, and
  platform paths.

### Profiles and workflow

- The PL Validation family, QA System Test Short v2, and Quick Test use
  architecture-aware CPU intent without requiring duplicated x86 and AArch64
  profile variants.
- Power Test explicitly uses Power Auto.
- Completed hardware campaign and confirmation profiles were archived outside
  normal discovery, but retained for historical reproduction rather than
  deleted. Normal discovery now presents the active operator set instead of
  campaign-only profiles.
- Added `all_internal_non_root_low_occupancy` for explicitly configured Storage
  Benchmark profiles, with unconditional root/system-drive exclusion and
  execution-time occupancy and free-space rechecks.
- TUI Results-view `G Upload` now targets the selected result path rather than
  relying only on the latest run directory. Successful moves refresh result
  inventory/selection while preserving the shared uploader and readiness flow.

### Reliability and evidence

- Added meaningful stress-ng `--verify` and metrics behavior, independent
  Python CPU/RAM verification, and native canary evidence.
- Expanded CPU utilization, target-set, affinity, worker-count, memory,
  allocation, and verification evidence.
- Improved Readiness, Dry Run, materialized launch-plan, and Advanced Debug
  evidence.
- Added memory-plan, telemetry, and worker evidence to
  `parsed_results_extended.json` while preserving the existing
  `parsed_results_custom.json` compatibility contract and aliases.
- Added contract identities to run manifests, dependency reports, and telemetry
  source maps.
- Added unit-correct `_gib` telemetry aliases while retaining existing `_gb`
  compatibility fields.

### Compatibility

Existing user profiles remain loadable. New profile fields are additive:
`cpu.power_auto` and `cpu.instruction_intent` are opt-in and use safe defaults
when absent. Explicit historical `instruction_set` values retain their original
meanings, and architecture-specific requests continue to fail closed rather
than silently downgrade.

`parsed_results_custom.json` and existing compatibility aliases remain intact.
`parsed_results_extended.json`, manifests, worker artifacts, and telemetry
outputs gain additive evidence.

Completed campaign profiles were moved, not deleted. Scripts or external tools
that hard-code their former paths may need adjustment because those historical
profiles now reside below `profiles/Archived/2026 Hardware Validation/`.

### Known limitations

- AArch64 native vector support currently covers NEON, not SVE, SVE2, or SME.
- ARM GPU OpenCL was not hardware validated during this campaign. The OpenCL
  loader uses normal system discovery, but its hard-coded fallback list does
  not yet include common AArch64 multiarch paths.
- TUI selected-result Google Drive upload is software/regression validated.
  Physical end-to-end Google Drive integration was not exercised on the current
  host because the optional dependency and integration setup was incomplete.
- CPU/package-power telemetry availability varies by platform. Power Auto
  reports the selection mechanism it used and falls back truthfully where watts
  are unavailable.

These are capability boundaries and future expansion areas, not unresolved
release failures.

### Validation

AArch64 and x86_64 were exercised across five materially different final
Power Auto/instruction-intent confirmation systems. All 20 confirmation stages
were accepted: 17 `VALIDATED`, 3 `VALIDATED WITH EXPLAINED WARNING`, and no
current unresolved acceptance failures.

Real hardware acceptance included Qualcomm Oryon/NEON, Qualcomm Adreno Vulkan,
Intel hybrid P/E common-safe ISA behavior, x86 AVX-512 selection where common
and supported, measured Power Auto on multiple Intel and AMD systems, and the
AArch64 no-package-power fallback. This coverage does not imply validation of
every hardware combination.

The v0.3.0-alpha release audit passed all 240 non-hardware smoke tests.

## Default Configuration

The committed settings example uses `environment_mode: "end_user"`, so the CLI
starts with the public-facing operator workflow on a fresh clone. Local settings
can be adjusted after their initial creation.
