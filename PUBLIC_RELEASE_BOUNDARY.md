# Public Release Boundary

Use this checklist when preparing the public repository. Publish only generic
Linux Validation Suite code, examples, documentation, and empty runtime
scaffolds.

## Keep Public

- `README.md`
- `linux_validation_suite.py`
- `linux_validation_suite_tui.py`
- `linux_validation_suite_qa.py`
- `Modules/`
- `native/` helper source files
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
- Google Drive credentials, shared-drive IDs, upload manifests, or tokens
- Organization-specific inventory options or profile lists
- Identifying unit or operator metadata, notes, or photos
- Proprietary reference binaries, completed reference data, and non-public workflow files

## Public Branch Defaults

- Set `environment_mode` to `end_user`.
- Use generic profiles only.
- Keep Google Drive upload disabled or documented as user-configured.
- Avoid organization-specific profile group labels.
- Include a license only after the ownership/release decision is settled.
- Document `python3.14 linux_validation_suite.py` and `python3.14 linux_validation_suite_tui.py` as the basic launch commands.
- Document enhanced telemetry as a session-scoped sudo-backed option, not a saved setting.

## Pre-Publish Checklist

- Run a search for credentials and IDs: `google`, `credential`, `shared_drive`, `serial`, `order`, `department`, `sku`.
- Confirm `.gitignore` excludes generated data and secrets.
- Confirm no retained results, probe logs, or non-public reference projects are staged.
- Confirm sample profiles are generic and do not encode organization-specific workflows.
- Confirm the README clearly describes hardware stress risk and telemetry caveats.
- Confirm QA wrapper examples use generic result folder names and do not expose local filesystem paths.
