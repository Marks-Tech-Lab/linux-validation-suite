# Linux Validation Suite (LVS) Architecture Map

## Purpose

This map documents the current production boundaries for the Linux Validation Suite. It is meant to guide future work toward contract clarity, QA readiness, troubleshooting, and shared CLI/TUI/GUI backend reuse.

This is not a line-count roadmap. The project is already highly modular, and small facades or compatibility shims should be treated as stable unless they are actively causing confusion, duplicated behavior, or contract risk.

## Modularity Rule

Before splitting more code, classify the task:

- True contract or QA improvement: improves tests, fixtures, QA integration, shared backend reuse, troubleshooting clarity, report/export/telemetry contract safety, or removes meaningful duplicated logic.
- Over-modularization: splits an already-thin facade, compatibility shim, CLI/TUI adapter, or small helper only because it can be split.

Do the first. Avoid the second.

## Entrypoints

- `linux_validation_suite.py`: CLI compatibility entrypoint. It re-exports legacy symbols and starts `Launcher().start()` when run directly.
- `linux_validation_suite_tui.py`: optional TUI entrypoint. It checks optional TUI dependencies, prompts for enhanced telemetry when needed, and launches `LinuxValidationSuiteTui`.
- `linux_validation_suite_qa.py`: non-interactive QA JSON wrapper. It calls the shared service layer and emits versioned QA review payloads for external tooling.
- `Modules/linux_validation_suite_service.py`: shared service facade for non-CLI callers. This is the preferred integration surface for TUI, GUI, and QA automation.

The entrypoints should stay thin. They are not good targets for more extraction.

## Service Graph

- `Modules/lvs_runtime_services.py` builds the shared runtime graph with `build_runtime_services()` and returns `RuntimeServices`.
- `Modules/linux_validation_suite_service.py` composes shared service behavior with service mixins from `lvs_service_*`.
- CLI adapters live in `Modules/lvs_cli_launcher.py` and related `lvs_cli_*` modules.
- TUI adapters live in `Modules/lvs_tui_*` modules and should call shared services instead of duplicating backend behavior.

High-level ownership:

- Runtime graph construction: `lvs_runtime_services.py`
- CLI compatibility and menu orchestration: `lvs_cli_launcher.py`, `lvs_cli_*`
- Shared application API: `linux_validation_suite_service.py`, `lvs_service_*`
- TUI presentation and interaction: `linux_validation_suite_tui.py`, `lvs_tui_*`

## Run Flow

Run flow starts with profile selection and setup, then moves through preflight, launch, stage execution, completion, and artifact finalization.

- Profile and run setup: `lvs_run_setup.py`, `lvs_run_setup_actions.py`, `lvs_run_setup_history_service.py`, `lvs_run_setup_stages.py`, `lvs_run_setup_text.py`, `lvs_run_setup_controller.py`
- Preflight and readiness: `lvs_run_preflight.py`, profile readiness services, dependency report services
- Launch and process execution: `lvs_run_launch.py`, `lvs_run_executor.py`, `lvs_run_flow.py`
- Stage orchestration: `lvs_validation_orchestrator.py`, `lvs_run_orchestration.py`, `lvs_run_stage_loop.py`, `lvs_stage_*`
- Completion and verdicts: `lvs_run_completion.py`, `lvs_run_finalization.py`, `lvs_run_verdict.py`, `lvs_run_artifacts.py`, `lvs_post_run.py`

The current run setup split is a stable boundary. Future work here should focus on fixture coverage and contract tests, not further small-file extraction.

## Report, Export, and Result Flow

This is one of the remaining high-value areas because it defines what downstream tools, legacy importer compatibility, and QA automation consume.

- Segment parsing: `lvs_segment_parser.py`, `lvs_segment_parser_services.py`, `lvs_segment_*`
- Compatibility export: `lvs_compat_exporter.py`, `lvs_compat_export_*`, `lvs_export_contract.py`
- Summary/report helpers: `lvs_report_helpers.py`, `lvs_summary_text.py`
- Result report rendering and workflows: `lvs_result_reports.py`, `lvs_result_report_rendering.py`, `lvs_result_report_text.py`, `lvs_result_report_workflows.py`
- Result validation payloads and checks: `lvs_result_validation.py`, `lvs_result_validation_checks.py`, `lvs_result_validation_payload.py`
- Result artifacts: `lvs_result_artifacts.py`, `lvs_result_artifact_*`
- Dependency reports: `lvs_dependency_reports.py`, `lvs_dependency_payload.py`, `lvs_dependency_report_text.py`, `lvs_dependency_report_artifacts.py`

Primary risk here is not file size by itself. The risk is unclear output contracts: which fields are stable, which are compatibility-only, and which downstream consumers should use.

## Telemetry and Inventory Flow

Telemetry collection and system inventory feed raw evidence, parsed output, report summaries, and validation context.

- Collection orchestration: `lvs_telemetry_collector.py`
- CPU telemetry and package metrics: `lvs_telemetry_cpu.py`
- GPU telemetry: `lvs_telemetry_gpu.py`, `lvs_telemetry_nvidia.py`, `lvs_telemetry_intel.py`
- Memory and sensor telemetry: `lvs_telemetry_memory.py`, `lvs_telemetry_sensor_io.py`, `lvs_telemetry_sources.py`, `lvs_telemetry_samples.py`
- Storage telemetry: `lvs_telemetry_storage_sources.py`
- System inventory: `lvs_system_info.py`, `lvs_inventory_helpers.py`, `lvs_cpu_topology.py`, `lvs_cpu_power_limits.py`, `lvs_gpu_identity.py`, `lvs_storage_inventory.py`, `lvs_system_identity.py`

Dense raw CSV is debug evidence and a fallback. Normal downstream consumers should use parsed report/export contracts where package-level CPU, GPU, storage, memory, and sensor summaries are promoted.

## Worker and Backend Flow

Worker modules are practical execution boundaries. They should not be split unless there is duplicated contract logic, schema confusion, or testing friction.

- Backend discovery and selection: `lvs_gpu_backend_catalog.py`, `lvs_gpu_backend_resolver.py`, `lvs_gpu_backend_support.py`, `lvs_gpu_backend_resolution.py`, `lvs_gpu_backend_runner.py`
- Worker planning and parameters: `lvs_gpu_worker_planner.py`, `lvs_gpu_worker_params.py`, `lvs_gpu_worker_materializer.py`, `lvs_gpu_worker_plan.py`, `lvs_gpu_worker_state.py`, `lvs_gpu_worker_retune.py`
- Workload execution: `lvs_workload_runner.py`, `lvs_workload_gpu_runtime.py`, `lvs_workload_gpu_workers.py`, `lvs_workload_cpu_memory.py`, `lvs_cpu_execution.py`, `lvs_memory_execution.py`
- Worker implementations: `lvs_opencl_compute_worker.py`, `lvs_opencl_vram_worker.py`, `lvs_egl_gles_worker.py`, `lvs_vulkan_workers.py`, native Vulkan helpers

Good future worker work would clarify worker result schemas, failure reasons, backend selection evidence, and fixture coverage. Splitting worker scripts just because they are large is not a priority.

## QA Integration Hook Points

QA should avoid driving interactive CLI prompts whenever possible.

Preferred hook points:

- Shared API: `SuiteAppService` from `Modules/linux_validation_suite_service.py`
- External wrapper: `.venv/bin/python linux_validation_suite_qa.py review RESULT_DIR` or `.venv/bin/python linux_validation_suite_qa.py batch ...`
- Runtime graph injection: `build_runtime_services()` in `Modules/lvs_runtime_services.py`
- Profile and readiness workflows: `lvs_service_profiles.py`, `lvs_service_profile_readiness.py`
- Run setup and execution: `RunSetupManager`, `RunExecutor`, `RunLaunchCoordinator`
- Result/report validation: `lvs_service_results.py`, `ResultReportManager`, `ResultValidationFacade`, `PreImportSanityFacade`, `ResultArtifactFacade`
- Dependency readiness: `DependencyReportManager` and dependency report modules

QA-facing work should define stable inputs, outputs, and fixtures for these hooks before introducing more adapters. The current QA review payload contract is versioned in `QA_REVIEW_PAYLOAD_CONTRACT.md`.

## Stable Boundaries To Stop Splitting For Now

- `linux_validation_suite.py`
- `linux_validation_suite_tui.py`
- `Modules/lvs_cli_launcher.py`
- Small `lvs_cli_*` compatibility shims
- Small TUI presentation or event adapter modules
- Current run setup split modules
- Current dependency report facade modules

These are already readable enough. Further splitting would likely increase navigation cost.

## High-Value Remaining Areas

Focus here only when the change improves contracts, tests, troubleshooting, or shared reuse:

- `lvs_report_helpers.py`: document and test report helper contracts before extracting anything else.
- `lvs_result_report_text.py`: consider output-family boundaries only if tests make the current responsibilities clear.
- `lvs_telemetry_cpu.py`: protect CPU topology, package metrics, power, clock, and memory-speed contracts with fixture tests.
- `lvs_system_info.py`: clarify inventory output contracts and platform fallback behavior.
- Stage diagnostics and stability modules: improve failure evidence clarity and test coverage.
- GPU worker/runtime modules: touch only for duplicated schema logic, backend selection clarity, or worker result contract safety.

## Verification Expectations

For runtime behavior changes, run:

```text
.venv/bin/python -m py_compile linux_validation_suite.py linux_validation_suite_tui.py Modules/*.py smoke_tests/run_smoke_tests.py
.venv/bin/python smoke_tests/run_smoke_tests.py
```

For report/export/telemetry contract changes, add focused fixture assertions. Smoke tests are necessary but not sufficient for contract safety.

## Next Recommended Step

The next major project phase is CPU Cooler Testing v2. Start with planning:
define the operator workflow, hardware and telemetry evidence, safety boundaries,
result/report contracts, platform assumptions, and fixture/acceptance coverage
before implementing runtime behavior or profiles.

Continue to avoid unrelated module splitting. Existing CLI, TUI, QA, result,
telemetry, and hardware-matrix boundaries should remain stable unless CPU cooler
v2 planning identifies a concrete contract or reuse requirement.
