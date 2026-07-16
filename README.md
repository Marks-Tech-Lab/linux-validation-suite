# Linux Validation Suite (LVS)

Linux Validation Suite is a hardware validation and stress-test orchestrator
for Linux systems. It runs repeatable CPU, memory, GPU, and VRAM workloads,
collects Linux telemetry, and exports structured result folders for later
review.

## Current Platform Support

This project is currently developed and validated primarily on x86_64 Linux systems.

ARM64/Linux support is a goal, but it is not fully validated yet. Some telemetry,
sensor, GPU, stress-test, or dependency behavior may be incomplete or inconsistent
on ARM systems until dedicated ARM validation is completed.

## Public Alpha

The public repository is
[`Marks-Tech-Lab/linux-validation-suite`](https://github.com/Marks-Tech-Lab/linux-validation-suite),
with `main` as the published branch. The `v0.1.x` alpha releases are published
as pre-releases. The current `v0.1.2-alpha` release includes the guarded local
Migration / Support workflow described below.

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
- result folder summaries and legacy-compatible JSON
- diagnostics and dependency checks for field troubleshooting
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
  result review, upload prompts, and pre-import sanity.
- TUI operator workflow for profile review, setup recall, dry run, run launch
  and cancellation, live status, post-run review, result review, validation,
  pre-import sanity, comparison, artifacts, upload workflow, and core settings.
- QA wrapper JSON contracts for single-result and batch review.
- A public hardware/result coverage matrix with optional local result mappings.
- CLI and TUI Migration / Support workflows for public-safe support export,
  explicitly acknowledged private migration bundles, restore preview, and
  confirmed restore apply. Restore never overwrites existing local files;
  conflicts are staged for manual comparison, and bundle manifests, checksums,
  paths, and symlinks are validated before use.

The runtime version follows the `v0.1.x-alpha` release policy. The current
`v0.1.2-alpha` release passed all 189 smoke tests. Passing smoke runs capture
expected interactive output instead of dumping CLI/TUI setup screens; failures
still retain their assertion diagnostics.

Migration bundles exclude secrets, Google credentials, result contents,
sensor-log contents, vendor/test data, `.venv`, caches, and private identifiers
by default. The public-safe support export is shareable; a private migration
bundle is not.

Still experimental or hardware-sensitive:

- Future GUI support.
- Some GPU backend variants and lab profiles.
- Sensor coverage that depends on vendor/kernel exposure.
- Automated packaging and dependency installation.

The next planned major phase is CPU Cooler Testing v2, beginning with design
and test-planning work before implementation.

A breaking output-schema stabilization milestone is deferred, not abandoned.
Its future canonical parsed-result target is `parsed_results.json`, while the
existing `parsed_results_custom.json` behavior remains unchanged until that
coordinated migration. New feature fields must already follow the forward-only
snake_case and semantic-unit policy in `OUTPUT_CONTRACT_INDEX.md`, including
future NIC, storage, and CPU cooler fields.

## Default Configuration

The committed settings example uses `environment_mode: "end_user"`, so the CLI
starts with the public-facing operator workflow on a fresh clone. Local settings
can be adjusted after their initial creation.
