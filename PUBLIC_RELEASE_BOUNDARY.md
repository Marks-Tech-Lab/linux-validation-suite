# Linux Validation Suite (LVS) Public Release Boundary

The public repository is
[`Marks-Tech-Lab/linux-validation-suite`](https://github.com/Marks-Tech-Lab/linux-validation-suite).
The published branch is `main`, mirrored at `origin/main`. The MIT License is
included. The `v0.1.x` alpha line is published as pre-releases; the current
`v0.1.2-alpha` release includes the guarded local Migration / Support workflow
and was validated with all 189 smoke tests passing.

Use this checklist when updating the public repository. Publish only generic
Linux Validation Suite (LVS) code, examples, documentation, and empty runtime
scaffolds.

## Keep Public

- `README.md`
- `linux_validation_suite.py`
- `linux_validation_suite_tui.py`
- `linux_validation_suite_qa.py`
- `Modules/`
- `native/` helper source files
- `requirements.txt`, optional requirements files, and `scripts/setup_venv.sh`
- generic probe scripts
- generic example profiles
- `settings/global_settings.example.json`
- `.gitkeep` scaffolds for result and sensor-probe directories
- operator notes and public setup documentation
- schema notes for result folders and parsed JSON

## Exclude From Public Release

- Runtime contents below `results/`, including uploaded/archived result data
- Runtime contents below `sensor_probe_logs/`
- `settings/global_settings.json`
- `settings/run_setup_history.json`
- `settings/secrets/`
- `.venv/`
- `hardware_result_validation_state.json`
- Python, test, editor, and build caches
- Google Drive credentials, shared-drive IDs, upload manifests, or tokens
- Private migration bundles and restore-conflict staging contents
- Organization-specific inventory options or profile lists
- Identifying unit or operator metadata, notes, or photos
- OCCT/vendor/test data, proprietary reference binaries, completed reference
  data, and non-public workflow files

## Public Branch Defaults

- Set `environment_mode` to `end_user`.
- Use generic profiles only.
- Keep Google Drive upload disabled or documented as user-configured.
- Avoid organization-specific profile group labels.
- Keep the MIT License and public release metadata current.
- Keep runtime version display aligned with the `v0.1.x-alpha` release policy.
- Document `./scripts/setup_venv.sh` and the repo-local `.venv/bin/python` entrypoints.
- Keep `.venv/` ignored; never publish or copy a maintainer virtual environment.
- Document enhanced telemetry as a session-scoped sudo-backed option, not a saved setting.

## Pre-Publish Checklist

- Run a search for credentials and IDs: `google`, `credential`, `shared_drive`, `serial`, `order`, `department`, `sku`.
- Confirm `.gitignore` excludes generated data and secrets.
- Confirm no retained results, probe logs, or non-public reference projects are staged.
- Confirm sample profiles are generic and do not encode organization-specific workflows.
- Confirm the README clearly describes hardware stress risk and telemetry caveats.
- Confirm QA wrapper examples use generic result folder names and do not expose local filesystem paths.
- Confirm x86_64 Linux remains identified as the primary validated target and
  ARM64/Linux remains marked TBD/not fully validated until dedicated validation
  is complete.
- Confirm passing smoke tests capture expected interactive screens while still
  exposing assertion diagnostics on failures.
- Confirm public-safe support exports remain redacted. Private migration bundles
  must require explicit acknowledgement, exclude secrets, Google credentials,
  results, sensor logs, vendor/test data, `.venv`, caches, and private
  identifiers, and retain no-overwrite restore, conflict staging, manifest,
  checksum, traversal, and symlink protections.
