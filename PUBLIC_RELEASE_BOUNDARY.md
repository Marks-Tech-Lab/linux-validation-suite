# Linux Validation Suite (LVS) Public Release Boundary

The public repository is
[`Marks-Tech-Lab/linux-validation-suite`](https://github.com/Marks-Tech-Lab/linux-validation-suite).
The published branch is `main`, mirrored at `origin/main`. The MIT License is
included. The prepared version is `v0.5.2`, a corrective reliability
milestone following the published `v0.5.2-alpha` checkpoint. It preserves the
hardware-scalability contract, first-class AArch64 and x86_64 support, safety,
and established output-compatibility boundaries. Validation includes the full
smoke suite and scoped x86-64/AArch64 physical campaigns, including Spark SVE at
128-bit VL, mixed/identical GPU targeting, protected shared/dedicated GPU memory
paths and final MSI Vulkan shutdown confirmation. Hardware coverage remains
specific to tested configurations. See [release scope and limitations](docs/release_notes_v0.5.2.md)
and [the proposed file inventory](docs/release_inventory_v0.5.2.md).

Release preparation commits and annotated Git tags are pushed to the public
repository only after approval. The maintainer creates and publishes GitHub releases manually;
preparing a version or pushing its tag does not itself publish a GitHub Release.

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
- Optional legacy `lvs_source_build.json` stamps (not required for copying or
  validation; do not publish operator-labelled local metadata)
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
- Keep runtime version display aligned with the approved release identity.
- Document `./scripts/setup_venv.sh` and the repo-local `.venv/bin/python` entrypoints.
- Keep `.venv/` ignored; never publish or copy a maintainer virtual environment.
- Document enhanced telemetry as a session-scoped sudo-backed option, not a saved setting.

## Supported Architecture Boundary

- Supported Linux architectures are x86_64 and AArch64.
- Accepted AArch64 native CPU implementations include scalar, integer NEON, and
  verified NEON FP32/FMA. SVE FP32/FMA is implemented and remains experimental;
  explicit SVE requests and operator-selected `highest_verified_vector` may use
  it when common native capability and compilation requirements are satisfied.
- Explicit architecture-specific ISA requests remain constrained to their
  architecture and fail closed when unavailable.
- Spark SVE functional execution and preserved-binary instruction inspection
  passed after the v0.5.2-alpha checkpoint; exact historical launch hashes were
  not recorded. Spark's 600-second sustained campaign passed at 128-bit VL with
  matching native executable observations. Highest-vector integration passed on
  Spark and non-SVE Snapdragon. Wider VLs and other SVE implementations remain
  physically unaccepted. Baseline/high-throughput vector policy is unchanged;
  ordinary Auto and Power Auto exclude SVE. SVE2, specialized ARM kernels and
  SME remain unimplemented and outside the ISA guarantee.
- Do not generalize AArch64 support into a promise for every ARM architecture,
  version, device, or platform.
- Unrelated architectures are not supported unless separately implemented and
  validated.
- ARM GPU OpenCL compute and VRAM execution are physically confirmed on NVIDIA
  GB10 within the recorded campaign. This does not accept every ARM driver:
  Snapdragon's captured OpenCL stack exposed no usable GPU and was correctly
  blocked. Adreno Vulkan compute/transfer acceptance remains independent.
- Future CPU/package-power telemetry providers are optional expansion work;
  current Power Auto behavior must report measured and fallback mechanisms
  truthfully.

## Output Compatibility Boundary

- Preserve `parsed_results_custom.json` and its existing compatibility aliases.
- Keep additions to `parsed_results_extended.json`, manifests, worker evidence,
  and telemetry contracts additive unless a separately approved migration says
  otherwise.
- Preserve established contract IDs, raw vendor/backend boundaries, and native
  stage display labels. Retain legacy sidecar reading only where compatibility
  requires it; active profiles do not depend on sidecars.
- Do not rename or reinterpret historical explicit ISA requests or backend
  identifiers.

## Pre-Publish Checklist

- Run a search for credentials and IDs: `google`, `credential`, `shared_drive`, `serial`, `order`, `department`, `sku`.
- Confirm `.gitignore` excludes generated data and secrets.
- Confirm no retained results, probe logs, or non-public reference projects are staged.
- Confirm sample profiles are generic and do not encode organization-specific workflows.
- Confirm the README clearly describes hardware stress risk and telemetry caveats.
- Confirm QA wrapper examples use generic result folder names and do not expose local filesystem paths.
- Confirm the README identifies x86_64 and AArch64 as supported architectures
  and scopes SVE/ARM OpenCL acceptance to actual tested configurations, without
  implying generic ARM, wider-VL, SVE2/SME or unrelated-architecture support.
- Confirm passing smoke tests capture expected interactive screens while still
  exposing assertion diagnostics on failures.
- Confirm public-safe support exports remain redacted. Private migration bundles
  must require explicit acknowledgement and clearly mark secret-bearing bundles;
  Google credentials may be included only after a separate deliberate choice.
  Bundles must exclude results, sensor logs, vendor/test data, `.venv`, caches,
  and unsupported private identifiers, and retain no-overwrite restore, conflict
  staging, manifest, checksum, traversal, and symlink protections.
