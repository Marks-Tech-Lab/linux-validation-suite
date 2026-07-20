# Linux Validation Suite (LVS)

Linux Validation Suite (LVS) is a profile-based hardware validation and
stress-test orchestrator for Linux systems. It runs repeatable CPU, RAM, GPU,
VRAM, and storage validation workflows, collects Linux telemetry, checks
dependencies and readiness, and exports structured result folders for later
review.

## Current Platform Support

This project is currently developed and validated primarily on x86_64 Linux systems.

ARM64/Linux support is a goal, but it is not fully validated yet. Some telemetry,
sensor, GPU, stress-test, or dependency behavior may be incomplete or inconsistent
on ARM systems until dedicated ARM validation is completed.

## Public Alpha

The public repository is
[`Marks-Tech-Lab/linux-validation-suite`](https://github.com/Marks-Tech-Lab/linux-validation-suite),
with `main` as the published branch. Alpha releases are published as
pre-releases. The current release is `v0.2.0-alpha`, focused on Storage Health
and Storage Benchmark.

Linux Validation Suite (LVS) is licensed under the MIT License. This alpha is
intended for early validation and feedback; hardware-sensitive and experimental
areas are identified below.

## Fresh Clone And First Run

Python 3.14 is the currently tested version. The code requires Python 3.10 or
newer because it uses modern typing syntax. Newer Python versions are allowed,
but run the smoke tests before relying on an untested interpreter version.

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

Committed storage profiles are:

- `Storage Benchmark Quick`: one-run completion-based sequential benchmark of
  eligible internal drives; root/system drives are excluded by default.
- `Storage Benchmark Sequential`: five-run completion-based sequential
  benchmark of eligible internal drives; root/system drives are excluded by
  default.
- `Quick Test`: now ends with a one-run Storage Benchmark stage. Its committed
  profile explicitly opts into the root/system drive, so that stage is reported
  with at least `WARN` when the system drive is benchmarked.

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

The runtime version is `0.2.0-alpha`, corresponding to the `v0.2.0-alpha`
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

A breaking output-schema stabilization milestone is deferred, not abandoned.
Its future canonical parsed-result target is `parsed_results.json`, while the
existing `parsed_results_custom.json` behavior remains unchanged until that
coordinated migration. New feature fields must already follow the forward-only
snake_case and semantic-unit policy in `OUTPUT_CONTRACT_INDEX.md`.

## Release Notes — v0.2.0-alpha

**Storage health and benchmark alpha**

- Added normalized internal-drive inventory enrichment and SMART health through
  `nvme-cli` and optional `smartctl` providers.
- Added the fio-backed KDiskMark/CDM-style Storage Benchmark as a standalone
  CLI workflow and a completion-based profile module.
- Added sequential all-internal-drive benchmarking, explicit system-drive
  safeguards, CoW/Btrfs warnings, and JSON/TXT benchmark artifacts.
- Added `Storage Benchmark Quick` and `Storage Benchmark Sequential`; `Quick
  Test` now finishes with a one-run Storage Benchmark stage.
- Retained normalized output boundaries: raw SMART and raw fio provider payloads
  are not embedded in normal system information or parsed results.

## Default Configuration

The committed settings example uses `environment_mode: "end_user"`, so the CLI
starts with the public-facing operator workflow on a fresh clone. Local settings
can be adjusted after their initial creation.
