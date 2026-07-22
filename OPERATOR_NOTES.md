# Linux Validation Suite (LVS) Operator Notes

These notes are for technicians running local Linux validation workflows. They
describe the generic public-alpha operator path; local deployments can keep
private profiles, upload settings, and inventory options in ignored settings
files.

## Standard Workflow

1. Launch the CLI with `.venv/bin/python linux_validation_suite.py` or the TUI with `.venv/bin/python linux_validation_suite_tui.py`.
2. At launch, choose whether to enable enhanced telemetry for this session. Enable it when you need sudo-backed sensor evidence. Skip it when intentionally capturing normal-user telemetry.
3. Use Dependency Check on a new machine or after driver/runtime changes.
4. Use Dry Run / Diagnostics for the profile you plan to run.
5. Start a New Run or use the TUI Run Setup flow.
6. When prompted, recall a previous setup if the system should reuse prior case/PSU/cooling metadata.
7. After the run, open the created result folder from the TUI Results view or inspect `run_summary.txt`.
8. Before importing, comparing, or escalating a result, use Pre-Import Sanity and QA Review.

Advanced debug logging is not the same as enhanced telemetry. Use advanced
debug only when troubleshooting a run; use enhanced telemetry at launch when
you need sudo-backed source evidence.

## Launch Commands

```bash
.venv/bin/python linux_validation_suite.py
.venv/bin/python linux_validation_suite_tui.py
.venv/bin/python linux_validation_suite_qa.py review "results/<result-folder>"
.venv/bin/python linux_validation_suite_qa.py batch "results/<result-a>" "results/<result-b>"
```

The repo-local `.venv` commands are the expected operator and smoke-test path.
The setup script selects the preferred available interpreter and records the
actual virtual-environment Python in its output.

## Which Profile To Use

- `Quick Test.json`: short machine validation that finishes with a one-run
  Storage Benchmark stage. The committed profile explicitly allows the system
  drive, which forces the storage result to at least `WARN`.
- `Storage Benchmark Quick.json`: one-run completion-based sequential benchmark
  of eligible internal drives; system drives are excluded by default.
- `Storage Benchmark Sequential.json`: five-run completion-based sequential
  benchmark of eligible internal drives; system drives are excluded by default.
- `QA System Test Short v2.json`: short multi-stage system validation example.
- `GPU Troubleshooting.json`: GPU backend and VRAM troubleshooting example.

Private deployments can keep additional local profiles in ignored profile
folders or local-only settings.

## Storage Operator Notes

Storage Benchmark requires `fio` with the `libaio` engine. `nvme-cli` supplies
the `nvme` SMART provider, while `smartctl` is the executable supplied by the
`smartmontools` package.

`Storage Benchmark Quick.json` runs the benchmark once per eligible internal
drive; `Storage Benchmark Sequential.json` runs it five times. Both process
eligible drives sequentially and exclude root/system drives by default. `Quick
Test.json` ends with a one-run Storage Benchmark stage and explicitly opts into
root/system drives. In the standalone workflow, benchmarking a root/system
drive requires typed confirmation.

Single-device CoW/Btrfs benchmark workspaces are supported with warnings. Their
results may differ from raw-device or simpler non-CoW filesystem behavior.

The optional profile mode
`target_mode: all_internal_non_root_low_occupancy` dynamically selects eligible
internal non-root drives. Its `max_used_percent` setting defaults to `3.0` and
is applied to the deterministically selected writable filesystem/workspace,
not to guessed raw disk contents; unmounted filesystems on the same physical
drive are not measured. Root/system drives are always excluded in this mode,
and the existing USB, removable, network-backed, virtual, unresolved, and
ambiguous multi-device exclusions still apply.

The suite rechecks the selected filesystem's occupancy and free space
immediately before each sequential target starts. If usage has risen above the
configured threshold, the target is skipped before `fio` starts. Single-device
CoW/Btrfs remains supported with the existing warning behavior.

The ready-made `Storage Benchmark Quick.json` and `Storage Benchmark
Sequential.json` profiles remain unchanged `all_internal` profiles. Use the
low-occupancy mode only in a profile that explicitly selects it; existing
`all_internal` and `selected_target` behavior is unchanged.

CPU cooler, entered power-limit, PPT, and TDP values are descriptive run
metadata. They do not configure firmware or enforce cooling or power policy,
and they do not represent a committed future CPU cooler test module.

## What Result States Mean

- `Ready`: usable as a passing validation result for the configured profile.
- `Ready with documented warnings`: usable if the warnings make sense for the system and environment.
- `Not ready`: do not treat as passing until the blocking issue is reviewed.
- `Warning`: not automatically failed. Read action items and stage warnings.
- `Aborted` or `Fail`: review logs and preserve the result folder for analysis.

## Common Non-Blocking Warnings

- `OS VRAM telemetry under-report`: worker allocation and verification passed, but driver/OS telemetry reported less VRAM than the worker actually allocated. This can happen on shared-memory or driver-managed paths.
- `GPU temperature warning`: the system reached a configured thermal warning threshold. Review airflow, cooling, and ambient conditions.
- `Report-only performance recommendation`: workload verification passed, but sustained telemetry was below a preferred target.

## What To Preserve If Something Fails

Preserve the entire timestamped folder from `results/`, not just one file. The
important files are commonly:

- `run_summary.txt`
- `parsed_results_custom.json`
- `parsed_results_extended.json`
- `run_manifest.json`
- `raw_telemetry.csv`
- `system_info.json`
- `profile_used.json`
- `worker_results/`
- `telemetry_source_map.json`
- any terminal notes you captured

For pre-run issues, preserve the timestamped diagnostics or dependency folder:

- `*_Diagnostics_*`
- `*_Dependency_Check`
- `*_Preflight`

## Import/Upload Check

Before importing or uploading active result folders:

1. Go to `Results`.
2. Run Pre-Import Sanity.
3. Run QA Review.
4. Review any warning/fail folders before upload or import.

Google Drive upload is optional and private/local. Missing credentials or shared
drive IDs should appear as not configured, not as a suite failure.

## Migration And Public-Safe Support

Use **Diagnostics / Dependencies > Migration / Support** in the CLI or the TUI
**K Migration** action. The TUI can run all three workflows directly: it uses
text input for bundle paths, requires `PRIVATE` before private export, and shows
a fresh restore preview before requiring `APPLY`. The public-safe support
export is redacted, reports
missing optional files as informational, and writes below
`results/Support_Exports/Public_Support_Export_<timestamp>/`:

```bash
.venv/bin/python -m Modules.lvs_local_migration support-export
```

This support summary is safe to share by default. It is not a configuration or
secret backup.

Private migration bundles require explicit acknowledgement:

```bash
.venv/bin/python -m Modules.lvs_local_migration migration-export --acknowledge-private-data
```

They are written below
`results/Migration_Bundles/Private_Migration_Bundle_<timestamp>/` with
restrictive permissions, a versioned manifest, and SHA-256 checksums. They may
contain private settings, setup history, and hardware-state mappings and are
**not public-safe**. Google credentials and identifiers, runtime environment
overrides, actual results, sensor-log contents, vendor/test data, `.venv`, and
caches are excluded.

Restore is preview-only unless explicitly applied:

```bash
.venv/bin/python -m Modules.lvs_local_migration restore /path/to/bundle
.venv/bin/python -m Modules.lvs_local_migration restore /path/to/bundle --apply --yes
```

Restore validates the manifest, checksums, paths, and symlink safety first. It
recreates safe folder scaffolding and missing local files but never overwrites
existing files. Conflicts are staged below
`results/Migration_Restore_Staging/` for manual comparison. Google Drive
credentials and identifiers always require manual restoration in v1.

## Production-Ready Versus Experimental

Use these as normal operator workflows:

- CLI run/setup/result review.
- TUI profile/setup/run/result review flow.
- QA wrapper single/batch JSON review.
- Hardware validation matrix retained-result checks.

Treat these as experimental or hardware-sensitive unless directed:

- GUI support is not currently implemented; future scope is TBD.
- New GPU backend variants or profiles marked lab/diagnostic/experimental.
- Telemetry fields from newly discovered sensors before they have retained-result evidence.
- Any parser/export/schema changes not covered by fixture tests.

Do not change validation thresholds, parser/export schemas, QA payload fields,
or hardware matrix entries unless a real blocker or retained-result evidence
requires it.
