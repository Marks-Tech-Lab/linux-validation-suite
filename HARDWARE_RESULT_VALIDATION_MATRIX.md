# Hardware And Result Validation Matrix

This is the minimum real-world coverage target before calling the Linux
Validation Suite production-ready. It defines the hardware/result categories
that should be captured and reviewed through CLI/TUI/QA payloads.

The committed machine-readable definition is
`hardware_result_validation_matrix.json`. It is a public, self-contained
category matrix. It does not require old retained result folders and should not
contain private workstation result paths.

Optional maintainer state may live in the ignored local file
`hardware_result_validation_state.json`. That file can map categories to real
retained `results/...` folders on a maintainer workstation for deeper QA
regression checks. Fresh clones do not need it.

## Public Matrix Versus Local State

- Public matrix: committed category/evidence definition.
- Local state: ignored retained-result mapping for maintainer QA regression.
- Fresh clone: starts with empty result/probe folders and still passes public
  smoke tests without retained private results.
- Stale local state: missing or moved result folders should be reported or
  skipped cleanly unless a maintainer intentionally enables a strict local
  check.

## Local State Lifecycle

`hardware_result_validation_state.json` is generated/local state, not public
truth. It is ignored by Git.

- Missing state file: treated as an empty local state with all public
  categories marked missing. Public smoke tests still pass.
- Confirmed state entry: maps one public category to a retained result folder
  that still contains `parsed_results_custom.json`.
- Missing state entry: records that no local retained result currently covers
  the category.
- Stale state entry: a previously confirmed path no longer exists or no longer
  has the expected parsed artifact. Default smoke tests report/skip it.
- Candidate state entry: optional unconfirmed discovery evidence. Candidate
  entries are not treated as confirmed QA coverage.

Maintainer helpers can discover/rebuild local state by scanning current
`results/` folders and looking for retained result folders with
`parsed_results_custom.json`. Discovery only fills obvious matches from local
artifacts, such as clean pass results, heatsoak evidence, telemetry privilege
evidence, GPU vendor evidence, or dual-package topology evidence. Uncertain
coverage remains missing or candidate/unconfirmed.

Prune behavior removes stale path mappings from local state by converting them
back to missing entries while preserving the previous path for troubleshooting.

### Rebuild Or Prune Local State

From the repository root, run this explicit maintainer action:

```bash
python3.14 -m Modules.lvs_hardware_matrix_state rebuild
```

The command loads `hardware_result_validation_matrix.json` and the existing
ignored state file when present, prunes stale mappings, scans `results/`, and
writes `hardware_result_validation_state.json`. It prints the confirmed,
missing, stale/pruned, and candidate counts plus the output path.

This is the only automatic write path for the local state. Normal CLI/TUI use,
module imports, and the default public smoke-test run do not invoke it. A fresh
clone does not need the state file or retained results.

Discovery preserves valid existing confirmed mappings. Structured evidence
such as explicit result/outcome fields, package topology, GPU identity,
heatsoak enablement, or telemetry privilege fields can produce a `confirmed`
mapping. Broad document-wide keywords or fallback phrases produce only a
`candidate`, and candidate coverage is never treated as confirmed. A stronger
confirmed match may upgrade a candidate; weaker discovery never replaces a
valid confirmed mapping.

Default/public smoke behavior validates the committed matrix shape and checks
any currently valid local retained mappings if present. Missing or stale local
state does not fail public smoke tests. Set `LVS_STRICT_HARDWARE_MATRIX=1` only
for maintainer QA when stale local mappings should fail the run.

## Required Hardware Coverage

| Area | Minimum coverage | Why it matters |
| --- | --- | --- |
| Single CPU | One clean single-socket run | Protects the common compatibility path and legacy aggregate CPU fields. |
| Dual CPU | One dual-socket/package run | Verifies package topology, package CPU telemetry, and aggregate CPU compatibility. |
| NVIDIA dGPU | One clean run and one warning/failure run | Covers NVML, external GPU workers, VRAM policy, and worker evidence. |
| AMD GPU or iGPU | One run if available | Protects non-NVIDIA GPU detection, backend selection, and telemetry fallback behavior. |
| Privileged telemetry | One run with privileged telemetry enabled | Verifies richer CPU/package/power/source evidence. |
| No privileged telemetry | One run without privileged telemetry | Verifies fallback behavior and worker-verified/no-telemetry interpretation. |
| Heatsoak | One run with heatsoak enabled | Protects the pre-run lifecycle and heatsoak reporting path. |
| GPU/VRAM failure or warning | One known warning/failure case | Protects troubleshooting, QA escalation, action items, and worker failure evidence. |
| Clean passing run | One complete passing result | Protects happy-path reports, import readiness, and comparison baseline behavior. |

## Telemetry Privilege Evidence

Telemetry privilege coverage should be identified from additive evidence in
future artifacts:

- `run_manifest.json` -> `telemetry_capabilities.telemetry_privilege`
- `telemetry_source_map.json` -> `telemetry_privilege`
- individual `telemetry_source_map.json.fields.*.access_mode`

Move local retained-result state for `privileged_telemetry_run` to available
when a retained result shows `source_mode` of `sudo_telemetry`, `root_process`,
or a clearly effective privileged helper path. Move local retained-result state
for `no_privileged_telemetry_run` to available when a retained result shows
`source_mode` of `unprivileged`.

## Required Result Review Paths

For each retained local matrix result, verify:

- CLI result review and report generation load without errors.
- TUI result review can show readiness and artifacts without duplicating backend logic.
- `linux_validation_suite_qa.py review RESULT_DIR` returns contract JSON with `contract_id` and `contract_version`.
- `python3.14 smoke_tests/run_smoke_tests.py` remains green after fixture updates.

## Stop Condition

The production-readiness phase can stop when every required row has at least
one retained local result folder, each folder can be reviewed through the QA
wrapper, and any known gaps are documented as hardware unavailable rather than
silently untested. This retained-result state is local QA evidence, not a
public repository requirement.
