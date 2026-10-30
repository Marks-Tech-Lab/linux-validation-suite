# LVS v0.5.3-alpha release inventory

Updated October 30, 2026. The approved development inventory was committed and
pushed as `00772b2c9a233680827bc765cd368e23677d6d2b`, with an incorrect prepared
v0.5.2 identity. No release tag or GitHub Release was created. The separate,
uncommitted v0.5.3-alpha correction below changes only version metadata and
current-release documentation. The index remains empty. No results, diagnostics,
settings or runtime locks are relocated or deleted.

## Final inventory decisions

The approved development inventory contains **116 Include** paths. Its two
release-document paths below reflect their final v0.5.3-alpha names. The single
**Exclude** row remains the unrelated runtime lock. These rows describe the
release contents, not the current correction's Git status or a request to stage
all 116 paths again. The separate correction inventory follows the table.
All five original GPU Correction JSON files were moved byte-for-byte to
`profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/`.
There are no active duplicates. This follows the existing numbered historical
campaign archive and is linked from the retained
[operator handoff](../physical-validation/gpu-corrections-20261022/OPERATOR-HANDOFF.md).

Final inventory: **25 active + 56 archived = 81 profiles**. The unchanged loader
reads root JSON non-recursively and can still load archive JSON by exact path.
For deliberate historical reproduction, restore only the selected archive JSON
to root for normal menu discovery. No new menu, loader logic or deployment
workflow is introduced. Existing ordinary profiles, including PL Validation,
remain untouched.

The historical operator handoff is included with archive-aware paths and explicit
historical status. Its safety, stopping, integrity and evidence requirements are
preserved. Current acceptance remains authoritative in README, ROADMAP and release
notes; no renewed physical campaign is requested.

Opt-in diagnostics and their tests are intentional. In particular,
`Modules/lvs_vulkan_dispatch_timing.py` is imported by the native compute worker
even when diagnostics are off; it must ship. Do not discard diagnostic source as
abandoned scaffolding or omit newly added production dependencies.

## Approved development inventory (final release paths)

### Required release source (79)

| Path | Git state | Proposed staging |
|---|---|---|
| `Modules/lvs_advanced_debug.py` | modified | Include |
| `Modules/lvs_cli_profile_commands.py` | modified | Include |
| `Modules/lvs_cli_profile_gpu_prompts.py` | modified | Include |
| `Modules/lvs_cli_profile_stage_prompts.py` | modified | Include |
| `Modules/lvs_cli_run_setup_builder.py` | modified | Include |
| `Modules/lvs_cli_run_setup_prompts.py` | modified | Include |
| `Modules/lvs_compat_export_builder.py` | modified | Include |
| `Modules/lvs_compat_export_gpu.py` | modified | Include |
| `Modules/lvs_compat_export_helpers.py` | modified | Include |
| `Modules/lvs_core.py` | modified | Include |
| `Modules/lvs_cpu_architecture.py` | modified | Include |
| `Modules/lvs_cpu_power_selection.py` | modified | Include |
| `Modules/lvs_egl_gles_worker.py` | modified | Include |
| `Modules/lvs_egl_gles_workers.py` | modified | Include |
| `Modules/lvs_gpu_allocation_geometry.py` | new | Include |
| `Modules/lvs_gpu_allocation_safety.py` | new | Include |
| `Modules/lvs_gpu_capability.py` | modified | Include |
| `Modules/lvs_gpu_retune_process.py` | modified | Include |
| `Modules/lvs_gpu_stage_events.py` | modified | Include |
| `Modules/lvs_gpu_targets.py` | modified | Include |
| `Modules/lvs_gpu_vram_evidence.py` | new | Include |
| `Modules/lvs_gpu_worker_materializer.py` | modified | Include |
| `Modules/lvs_gpu_worker_plan.py` | modified | Include |
| `Modules/lvs_gpu_worker_planner.py` | modified | Include |
| `Modules/lvs_gpu_worker_retune.py` | modified | Include |
| `Modules/lvs_opencl_allocation_timing.py` | new | Include |
| `Modules/lvs_opencl_compute_worker.py` | modified | Include |
| `Modules/lvs_opencl_vram_worker.py` | modified | Include |
| `Modules/lvs_opencl_workers.py` | modified | Include |
| `Modules/lvs_profile_cli_editor.py` | modified | Include |
| `Modules/lvs_profile_edit_controller.py` | modified | Include |
| `Modules/lvs_profile_edit_view.py` | modified | Include |
| `Modules/lvs_profile_editor.py` | modified | Include |
| `Modules/lvs_profile_loader.py` | modified | Include |
| `Modules/lvs_profile_report_text.py` | modified | Include |
| `Modules/lvs_profile_save.py` | modified | Include |
| `Modules/lvs_report_data.py` | modified | Include |
| `Modules/lvs_report_helpers.py` | modified | Include |
| `Modules/lvs_report_html.py` | modified | Include |
| `Modules/lvs_result_overview_reports.py` | modified | Include |
| `Modules/lvs_result_report_adapters.py` | modified | Include |
| `Modules/lvs_result_validation_checks.py` | modified | Include |
| `Modules/lvs_run_artifacts.py` | modified | Include |
| `Modules/lvs_run_bootstrap.py` | modified | Include |
| `Modules/lvs_run_completion_evidence.py` | new | Include |
| `Modules/lvs_run_setup.py` | modified | Include |
| `Modules/lvs_run_setup_actions.py` | modified | Include |
| `Modules/lvs_run_setup_stages.py` | modified | Include |
| `Modules/lvs_run_setup_text.py` | modified | Include |
| `Modules/lvs_runtime_memory_guard.py` | modified | Include |
| `Modules/lvs_segment_gpu_targeting.py` | modified | Include |
| `Modules/lvs_segment_gpu_worker_summary.py` | modified | Include |
| `Modules/lvs_service_models.py` | modified | Include |
| `Modules/lvs_service_profiles.py` | modified | Include |
| `Modules/lvs_stage_configuration.py` | new | Include |
| `Modules/lvs_stage_diagnostics.py` | modified | Include |
| `Modules/lvs_stage_process_control.py` | modified | Include |
| `Modules/lvs_summary_text.py` | modified | Include |
| `Modules/lvs_system_memory_budget.py` | modified | Include |
| `Modules/lvs_tui_app.py` | modified | Include |
| `Modules/lvs_tui_app_actions_adapter.py` | modified | Include |
| `Modules/lvs_tui_event_adapter.py` | modified | Include |
| `Modules/lvs_tui_event_flow.py` | modified | Include |
| `Modules/lvs_tui_profile_edit_adapter.py` | modified | Include |
| `Modules/lvs_tui_profile_edit_presentation.py` | modified | Include |
| `Modules/lvs_tui_run_execution_adapter.py` | modified | Include |
| `Modules/lvs_tui_run_setup_adapter.py` | modified | Include |
| `Modules/lvs_tui_stage_configuration.py` | new | Include |
| `Modules/lvs_tui_view_models.py` | modified | Include |
| `Modules/lvs_vram_policy.py` | modified | Include |
| `Modules/lvs_vulkan_identity.py` | modified | Include |
| `Modules/lvs_vulkan_runtime.py` | modified | Include |
| `Modules/lvs_vulkan_targeting.py` | modified | Include |
| `Modules/lvs_vulkan_workers.py` | modified | Include |
| `Modules/lvs_worker_evidence.py` | modified | Include |
| `Modules/lvs_worker_integrity.py` | modified | Include |
| `Modules/lvs_workload_cpu_memory.py` | modified | Include |
| `native/vulkan_compute_worker.py` | modified | Include |
| `native/vulkan_transfer_worker.py` | modified | Include |

### Required regression/test support (18)

| Path | Git state | Proposed staging |
|---|---|---|
| `smoke_tests/cli_configuration_checks.py` | new | Include |
| `smoke_tests/configuration_workflow_checks.py` | new | Include |
| `smoke_tests/egl_vram_correctness_checks.py` | new | Include |
| `smoke_tests/gpu_allocation_safety_checks.py` | new | Include |
| `smoke_tests/gpu_allocation_scaling_checks.py` | new | Include |
| `smoke_tests/gpu_slow_operation_checks.py` | modified | Include |
| `smoke_tests/neon_fp32_fma_checks.py` | modified | Include |
| `smoke_tests/opencl_scheduling_checks.py` | new | Include |
| `smoke_tests/physical_gpu_selection_checks.py` | new | Include |
| `smoke_tests/run_completion_evidence_checks.py` | new | Include |
| `smoke_tests/run_smoke_tests.py` | modified | Include |
| `smoke_tests/sve_fp32_fma_checks.py` | modified | Include |
| `smoke_tests/vulkan_bounds_diagnostic_checks.py` | new | Include |
| `smoke_tests/vulkan_dispatch_timing_checks.py` | new | Include |
| `smoke_tests/vulkan_physical_identity_checks.py` | modified | Include |
| `smoke_tests/vulkan_shutdown_policy_checks.py` | new | Include |
| `smoke_tests/vulkan_submission_partition_checks.py` | new | Include |
| `smoke_tests/vulkan_workload_effectiveness_checks.py` | modified | Include |

### Required user-facing documentation (11)

| Path | Git state | Proposed staging |
|---|---|---|
| `OUTPUT_CONTRACT_INDEX.md` | modified | Include |
| `PUBLIC_RELEASE_BOUNDARY.md` | modified | Include |
| `README.md` | modified | Include |
| `ROADMAP.md` | modified | Include |
| `docs/amd_vulkan_dispatch_timing_diagnostic.md` | new | Include |
| `docs/release_inventory_v0.5.3-alpha.md` | new | Include |
| `docs/release_notes_v0.5.3-alpha.md` | new | Include |
| `docs/source_build_provenance.md` | modified | Include |
| `docs/sve_fp32_fma_contract.md` | modified | Include |
| `docs/vulkan_shutdown_phase_diagnostic.md` | new | Include |
| `docs/vulkan_startup_bounds_diagnostic.md` | new | Include |

### Intentional diagnostic/developer utility (2)

| Path | Git state | Proposed staging |
|---|---|---|
| `Modules/lvs_vulkan_dispatch_timing.py` | new | Include |
| `native/vulkan_bounds_diagnostic.py` | new | Include |

### Historical physical-validation support (6)

| Path | Git state | Proposed staging |
|---|---|---|
| `physical-validation/gpu-corrections-20261022/OPERATOR-HANDOFF.md` | new | Include |
| `profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/GPU Correction EGL AMD Short.json` | new | Include |
| `profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/GPU Correction EGL Intel Baseline.json` | new | Include |
| `profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/GPU Correction EGL Intel Bounded Geometry.json` | new | Include |
| `profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/GPU Correction EGL NVIDIA Short.json` | new | Include |
| `profiles/Archived/2026 Hardware Validation/08 GPU Corrections October 22/GPU Correction EGL OpenCL Intel Timing.json` | new | Include |

### Runtime/generated artifact to exclude (1)

| Path | Git state | Proposed staging |
|---|---|---|
| `settings/.lvs_state.lock` | new | Exclude |

### Unrelated or unresolved (0)

None.

At development approval this enumerated **117 pending paths**: 84 tracked
modifications and 33 untracked files, with **116 Include**, **0 Pending** and
**1 Exclude**. The Git-state column records that approval-time state; those
116 files are now committed. The two renamed release documents retain their
classifications and the release-content count remains 116.

## Separate release-identity correction inventory

Only the following nine logical files change relative to `00772b2`:

| Final path | Correction |
|---|---|
| `Modules/lvs_core.py` | Runtime APP_VERSION only: 0.5.3-alpha |
| `README.md` | Current identity, links and alpha publication wording |
| `PUBLIC_RELEASE_BOUNDARY.md` | Current identity, links and alpha boundary |
| `ROADMAP.md` | Current release identity and already-committed inventory status |
| `docs/source_build_provenance.md` | Current runtime version reference |
| `docs/sve_fp32_fma_contract.md` | Current release heading and provenance link |
| `docs/release_notes_v0.5.3-alpha.md` | Renamed from release_notes_v0.5.2.md; identity, draft and provenance |
| `docs/release_inventory_v0.5.3-alpha.md` | Renamed from release_inventory_v0.5.2.md; final paths and correction inventory |
| `physical-validation/gpu-corrections-20261022/OPERATOR-HANDOFF.md` | Current-release link only; historical instructions preserved |

The two old documentation paths must be recorded as renames/deletions when the
correction is later staged. No other source, test or profile changes belong in
that commit. The excluded runtime lock stays untracked and untouched.

## New production dependencies

All eight formerly untracked Modules files are committed, required distribution contents:

| Module | Production reference examples |
|---|---|
| `lvs_gpu_allocation_geometry.py` | GPU planning; generated EGL/OpenCL workers |
| `lvs_gpu_allocation_safety.py` | Capability/planning/budgeting and all native GPU worker families |
| `lvs_gpu_vram_evidence.py` | GPU events, worker evidence, reports and compatibility |
| `lvs_opencl_allocation_timing.py` | Generated OpenCL VRAM execution |
| `lvs_run_completion_evidence.py` | Run finalization, compatibility, reports and result review |
| `lvs_stage_configuration.py` | Shared CLI/TUI profile/run configuration |
| `lvs_tui_stage_configuration.py` | TUI application mixin |
| `lvs_vulkan_dispatch_timing.py` | Native Vulkan compute diagnostic import |

## Exclusions that remain untouched

Never stage `settings/.lvs_state.lock`, `.venv/`, generated `build/`/native binaries,
`results/` (including accepted/archived physical evidence and recovered helpers),
`results_*` test outputs, sensor logs, temporary `*.log` validation output, caches,
settings/history files, credentials/secrets, migration bundles, deployment/compressed archives or other
machine-specific state. Existing ignore rules cover these runtime groups; the
runtime lock is visibly untracked and requires explicit exclusion. No broad
`git add .`, `git clean`, reset, package export or deletion is appropriate.
The table contains no unexplained source/scaffolding or unrelated pending file
apart from the explicitly excluded runtime lock.

## Version and provenance

Prepared runtime: **0.5.3-alpha**. Accepted physical source:
`d14b5bb1450385929fdb08d6dcc6f3253356293b06055b503a05c44e7620be21`.
Prepared source before archival:
`ff48a7e08a9d6d5053dd13fa33ad250dfdf73814967d660280c4d9f3ea154b46`.
Earlier v0.5.2 prepared source after archival (363 files, complete):
`7c42ed499e77a034d30771e224883c0145777e669cc0625265bc001d3b91b9a4`.
Current v0.5.3-alpha prepared source (363 files, complete):
`6683c863794c7f389265aa51541784cc880fd67a0baa9b865fb06d657c539140`.
Only APP_VERSION differs within source scope from committed `00772b2`;
restoring `0.5.2` reconstructs `7c42...` exactly. The documentation renames and
Markdown edits are outside scope. The v1 algorithm/scope is unchanged.
Versioning changes APP_VERSION bytes in
`Modules/lvs_core.py`; moving the five root JSON paths outside discovery removes
those five records from v1 scope. Markdown and smoke tests are outside scope.
No workload code or test configuration bytes changed. Starting from the earlier
`7c42...` preparation, reintroducing the five archived root records reconstructs
the pre-archive digest; also restoring `0.5.2-alpha` version bytes reconstructs
the accepted physical digest. No new fingerprint
is claimed as an exact match to an earlier physical execution.
See [release notes](release_notes_v0.5.3-alpha.md) for campaign provenance and limits.

## Retained development validation

- The unchanged workload/test implementation retains the prepared-tree
  **314/314 full smoke PASS** baseline. This archival changes discovery contents,
  not discovery logic, test expectations, backend selection rules or workload
  behavior; a complete-suite repeat is unnecessary.
- Final archive/discovery: **25 active**, PL Validation present, no correction
  profiles in normal discovery and no duplicate correction JSON files.
- All-profile validation: **25 active + 56 archived = 81/81 valid**, zero errors,
  five unchanged advisories. Original profile SHA-256 values are retained below.
- Focused configuration/operator-workflow, loader, captured-profile, archived-pack,
  output-contract and compatibility regressions: **17/17 PASS**.
- Compilation: **371 Python files PASS**; **six affected imports PASS**.
- Documentation links/profile references and `git diff --check`: PASS.
- The approved 117-row development inventory had **116 Include** and only
  the unrelated runtime lock excluded. All release contents are committed;
  the separate identity correction is listed above. The historical alpha tag
  remains unchanged. The new v0.5.3-alpha tag must be absent before tagging.
- No physical test is requested or performed. Historical results and alpha
  release notes/tags remain preserved. Only the prepared runtime identity changes.
- Identity correction validation: **8/8** focused provenance/output-contract
  regressions PASS; version-only source comparison and compilation PASS;
  **five integration imports** and **26 local documentation links** PASS;
  final inventory paths and `git diff --check` PASS. The 314/314 full smoke
  baseline remains applicable to unchanged workload code; no new smoke test
  or complete-suite repeat is needed for a version literal and Markdown.

### Byte-preserved archived profile contents

| Profile | Bytes | SHA-256 (before and after identical) |
|---|---:|---|
| `GPU Correction EGL AMD Short.json` | 920 | `4c89cb7d090f8a5d4d5cfd3a13c014c93e82d87d96656a2288ec64204d8819e4` |
| `GPU Correction EGL Intel Baseline.json` | 911 | `6c8e96691905c636b8eb6176bf15f9a0272ff61e8f94941c413065e224b20b55` |
| `GPU Correction EGL Intel Bounded Geometry.json` | 938 | `9dccee0a308667d4f2028bb546eac78810a712f53c138b28334f01b75dae072f` |
| `GPU Correction EGL NVIDIA Short.json` | 926 | `a32ae7c520e5f23641ee7b1047eb00b6e68d5fa0f25f9eee5d5d87cc283e8891` |
| `GPU Correction EGL OpenCL Intel Timing.json` | 1116 | `07eacd48bbd1d4a62681057829f5aee41c3081b94e38b009c8c623bfd558bec7` |

## Git release plan after approval

- Branch: `main`; current pushed HEAD: `00772b2c9a233680827bc765cd368e23677d6d2b`.
  That development commit is retained unchanged; the correction is a separate
  commit. Recheck upstream alignment before committing/pushing.
- Published annotated `v0.5.2-alpha` resolves to
  `500a17e22a6d384b779ca785f1a9a45cda092e7d`; preserve it and its historical
  notes unchanged. The mistaken v0.5.2 preparation never became a release.
- Confirm `v0.5.3-alpha` is absent locally and remotely before tagging.
- After approval, stage only the nine logical correction files listed above,
  including the two old document deletions and their renamed destinations.
  Review the exact staged diff; exclude the runtime lock and generated files.
- Proposed subject: `Correct prepared release identity to v0.5.3-alpha`.
- Push that separate commit normally after checking divergence; never amend,
  reset, rebase or force-push the already published preparation commit.
- Only after further approval, create annotated `v0.5.3-alpha` at the verified
  correction commit. Proposed annotation: `Linux Validation Suite v0.5.3-alpha corrective reliability and cross-hardware validation prerelease`.
- Push only the new tag after approval, verifying its peeled target. Manual
  GitHub publication must retain alpha/prerelease status. No tag, publication
  or package is authorized by this preparation.
