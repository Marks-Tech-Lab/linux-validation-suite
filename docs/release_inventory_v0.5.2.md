# Proposed LVS v0.5.2 release inventory

Prepared October 30, 2026. Profile archival is approved and complete; final
staging remains subject to review. The index remains empty. No results,
diagnostics, settings or runtime locks are relocated or deleted.

## Final inventory decisions

Stage exactly the **116 Include** paths below after final approval. The single
**Exclude** row is the unrelated runtime lock. There are no Pending paths.
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

## Every pending file

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
| `docs/release_inventory_v0.5.2.md` | new | Include |
| `docs/release_notes_v0.5.2.md` | new | Include |
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

This enumerates **117 pending paths**: 84 tracked modifications
and 33 untracked files. The staging proposal has
**116 Include**, **0 Pending**, **1 Exclude**.

## New production dependencies

All eight untracked Modules files are required distribution contents:

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

Prepared runtime: **0.5.2**. Accepted physical source:
`d14b5bb1450385929fdb08d6dcc6f3253356293b06055b503a05c44e7620be21`.
Prepared source before archival:
`ff48a7e08a9d6d5053dd13fa33ad250dfdf73814967d660280c4d9f3ea154b46`.
Final prepared source after archival (363 files, complete):
`7c42ed499e77a034d30771e224883c0145777e669cc0625265bc001d3b91b9a4`.
The v1 algorithm/scope is unchanged. Versioning changes APP_VERSION bytes in
`Modules/lvs_core.py`; moving the five root JSON paths outside discovery removes
those five records from v1 scope. Markdown and smoke tests are outside scope.
No workload code or test configuration bytes changed. Reintroducing the five
archived root records reconstructs the pre-archive digest; also restoring the
old version bytes reconstructs the accepted physical digest. No new fingerprint
is claimed as an exact match to an earlier physical execution.
See [release notes](release_notes_v0.5.2.md) for campaign provenance and limits.

## Final validation

- The unchanged executable/test implementation retains the prepared-tree
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
- The exact 117-row inventory matches working-tree status: **116 Include** and
  only the unrelated runtime lock excluded. Live upstream main matches HEAD;
  the alpha tag is unchanged and v0.5.2 remains absent locally/remotely.
- No physical test is requested or performed. Runtime, historical results and
  alpha release notes/tags remain preserved.

### Byte-preserved archived profile contents

| Profile | Bytes | SHA-256 (before and after identical) |
|---|---:|---|
| `GPU Correction EGL AMD Short.json` | 920 | `4c89cb7d090f8a5d4d5cfd3a13c014c93e82d87d96656a2288ec64204d8819e4` |
| `GPU Correction EGL Intel Baseline.json` | 911 | `6c8e96691905c636b8eb6176bf15f9a0272ff61e8f94941c413065e224b20b55` |
| `GPU Correction EGL Intel Bounded Geometry.json` | 938 | `9dccee0a308667d4f2028bb546eac78810a712f53c138b28334f01b75dae072f` |
| `GPU Correction EGL NVIDIA Short.json` | 926 | `a32ae7c520e5f23641ee7b1047eb00b6e68d5fa0f25f9eee5d5d87cc283e8891` |
| `GPU Correction EGL OpenCL Intel Timing.json` | 1116 | `07eacd48bbd1d4a62681057829f5aee41c3081b94e38b009c8c623bfd558bec7` |

## Git release plan after approval

- Current branch: `main`; HEAD and verified remote main:
  `ba7a529ef4bd89f91d9014c6225ac696618b055e`. Upstream is `origin/main`;
  no outgoing commit or divergence was present at inspection.
- Published annotated `v0.5.2-alpha` resolves to
  `500a17e22a6d384b779ca785f1a9a45cda092e7d`; preserve it unchanged.
- `v0.5.2` is absent locally and on the inspected remote. Recheck before tagging.
- Profile archival is approved and complete. Review the 116 Include rows and
  the resulting staged diff before committing; preserve the excluded runtime
  lock and all historical evidence.
- Stage the approved explicit paths from this table, including every new source
  and test dependency and the final approved profile paths. Exclude the lock and
  all runtime groups. Verify `git diff --cached --name-only` against the approved
  list and review the complete staged diff before committing.
- Proposed subject: `Prepare Linux Validation Suite v0.5.2 release`.
- Recheck upstream divergence and push the reviewed commit normally to
  `origin/main`, without force. Verify local HEAD, tracking main and remote main.
- Only then create a new annotated `v0.5.2` at that verified commit; proposed
  annotation: `Linux Validation Suite v0.5.2 corrective reliability and cross-hardware validation release`.
- Push that new tag normally; verify its peeled remote target equals the release
  commit. Never overwrite a pre-existing tag. GitHub publication remains a
  separate maintainer action after commit/tag approval.
