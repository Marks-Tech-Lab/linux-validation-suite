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

- `Quick Test.json`: short smoke run for quick machine checks.
- `QA System Test Short v2.json`: short multi-stage system validation example.
- `GPU Troubleshooting.json`: GPU backend and VRAM troubleshooting example.

Private deployments can keep additional local profiles in ignored profile
folders or local-only settings.

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

- Future GUI work.
- New GPU backend variants or profiles marked lab/diagnostic/experimental.
- Telemetry fields from newly discovered sensors before they have retained-result evidence.
- Any parser/export/schema changes not covered by fixture tests.

Do not change validation thresholds, parser/export schemas, QA payload fields,
or hardware matrix entries unless a real blocker or retained-result evidence
requires it.
