# Modules Index

## Purpose

`Modules/` is currently a flat compatibility package. This index groups the
existing files by ownership without moving or renaming them. The groups are a
navigation aid and a possible long-term package shape, not authorization to
change import paths.

All unlisted names matching a family below inherit that family's ownership.
When a file spans two areas, the listed owner is the area responsible for its
public contract and tests.

## Supported Surfaces

The surface labels used in this index are:

- **Public**: a documented command or integration path that callers may rely on.
- **Compatibility**: a legacy facade, adapter, or output contract retained for
  existing callers. It must remain importable while its compatibility promise
  applies.
- **Internal**: implementation code. Internal does not mean safe to move today;
  direct imports in tests or user scripts may still exist.

The supported root entrypoints are:

| Entrypoint | Surface | Responsibility |
| --- | --- | --- |
| `linux_validation_suite.py` | Public compatibility entrypoint | Interactive CLI startup and legacy symbol exports. |
| `linux_validation_suite_tui.py` | Public optional entrypoint | Textual dependency check and TUI startup. |
| `linux_validation_suite_qa.py` | Public entrypoint | Non-interactive, versioned QA review JSON. |
| `Modules/linux_validation_suite_service.py` | Public integration API | Shared application service for TUI, QA, and future frontends. |
| `python -m Modules.lvs_local_migration` | Public operator command | Public support export plus guarded private migration and restore workflows. |
| `python -m Modules.lvs_hardware_matrix_state` | Public maintainer command | Local retained-result hardware matrix state maintenance. |

`lvs_local_migration.py` and `lvs_hardware_matrix_state.py` are documented
`python -m` entrypoints. They must not be moved without executable legacy
wrappers that forward arguments, exit status, stdout, and stderr.

`Modules.lvs_tui_app` is the sole module allowed to import Textual directly.
Every other TUI helper must remain importable without Textual installed.

## Module Clusters

| Current ownership cluster | Possible later package | Included modules | Responsibility |
| --- | --- | --- | --- |
| Core | `Modules/core/` | `lvs_core.py` | Low-level constants, time helpers, and JSON persistence primitives. |
| CLI | `Modules/cli/` | `lvs_cli_*`, `lvs_diagnostics_cli.py`, `lvs_profile_cli_editor.py`, `lvs_qa_review_cli.py` | CLI compatibility, prompts, presentation, and command adapters. |
| TUI | `Modules/tui/` | `lvs_tui_*` | Optional Textual app plus Textual-free state, flows, adapters, and presentation. |
| Services | `Modules/services/` | `linux_validation_suite_service.py`, `lvs_service_*`, `lvs_runtime_services.py` | Shared frontend API and backend service composition. |
| Profiles | `Modules/profiles/` | `lvs_profile_*` except `lvs_profile_cli_editor.py` | Profile models, persistence, editing, validation, audit, and reports. |
| Settings | `Modules/settings/` | `lvs_settings.py`, `lvs_settings_facade.py`, `lvs_option_defaults.py` | Global settings contracts, persistence, and option defaults. |
| Run lifecycle | `Modules/run/` | `lvs_run_*`, `lvs_stage_*`, `lvs_orchestrator_*`, and the run exceptions listed below | Setup, preflight, launch, stage execution, evidence, verdicts, and completion. |
| Telemetry | `Modules/telemetry/` | `lvs_telemetry_*`, `lvs_intel_gpu_sidecar.py` | Source discovery, sampling, parsing, and device telemetry. |
| GPU/backends | `Modules/gpu/` | `lvs_gpu_*`, `lvs_opencl_*`, `lvs_vulkan_*`, `lvs_egl_*`, `lvs_external_gpu_*`, `lvs_vram_policy.py` | GPU identity, targeting, backend selection, workers, safety, and retuning. |
| Workloads | `Modules/workloads/` | `lvs_workload_*`, `lvs_cpu_execution.py`, `lvs_memory_execution.py`, `lvs_native_helpers.py` | CPU, memory, and GPU workload construction and execution. |
| Results/reports | `Modules/results/` | `lvs_result_*`, `lvs_report_*`, `lvs_summary_text.py`, `lvs_segment_*`, compatibility export modules | Result discovery, parsing, validation, rendering, artifacts, and exports. |
| Dependency diagnostics | `Modules/diagnostics/` | `lvs_dependency_*`, `lvs_backend_readiness.py`, `lvs_advanced_debug.py` | Dependency readiness payloads, reports, and opt-in debug evidence. |
| Hardware inventory | `Modules/inventory/` | `lvs_system_*`, inventory exceptions listed below | Hardware identity, topology, limits, PCIe evidence, and storage inventory. |
| Migration/support | `Modules/support/` | `lvs_local_*`, `lvs_hardware_matrix_state.py`, `lvs_privileged.py`, `lvs_google_drive_uploader.py` | Operator support, local migration, privileged telemetry, matrix state, and upload integration. |

## Ownership Index

### CLI

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_cli_launcher.py` | Compatibility | Composes the legacy `Launcher` from focused CLI mixins. |
| `lvs_cli_compat.py` | Compatibility | Preserves legacy top-level CLI classes and dependency injection behavior. |
| `lvs_cli_*_compat.py` | Compatibility | Retains legacy launcher method surfaces for the named CLI area. |
| `lvs_cli_input.py`, `lvs_cli_screen.py`, `lvs_cli_shell.py`, `lvs_cli_state.py` | Internal compatibility plumbing | Own terminal input, refresh, shell, and launcher state behavior. |
| `lvs_cli_runtime.py`, `lvs_cli_privileged.py`, `lvs_cli_upload.py` | Internal | Own launcher runtime wiring, privileged-session prompts, and upload actions. |
| `lvs_cli_live_run.py`, `lvs_cli_preflight_summary.py` | Internal | Render compact live-run and preflight status for terminals. |
| `lvs_cli_profile.py` | Internal adapter | Coordinates profile CLI actions. |
| `lvs_cli_profile_commands.py` | Internal | Dispatches profile commands. |
| `lvs_cli_profile_prompts.py`, `lvs_cli_profile_gpu_prompts.py`, `lvs_cli_profile_stage_prompts.py` | Internal | Own general, GPU, and stage profile prompts. |
| `lvs_cli_profile_view.py` | Internal | Renders profile detail for the CLI. |
| `lvs_profile_cli_editor.py` | Internal adapter | Bridges interactive CLI editing to shared profile mutation services. |
| `lvs_cli_results.py` | Compatibility adapter | Coordinates result actions exposed through the launcher. |
| `lvs_cli_result_inventory.py`, `lvs_cli_result_selected.py`, `lvs_cli_result_batch.py` | Internal | Handle inventory, selected-result, and batch-result command flows. |
| `lvs_cli_result_prompts.py` | Internal | Owns result workflow prompts. |
| `lvs_cli_run.py` | Compatibility adapter | Bridges CLI run actions to shared run services. |
| `lvs_cli_run_setup.py` | Internal adapter | Coordinates interactive run setup. |
| `lvs_cli_run_setup_builder.py`, `lvs_cli_run_setup_review.py` | Internal | Build and review run-setup state. |
| `lvs_cli_run_setup_prompts.py`, `lvs_cli_run_setup_hardware_prompts.py` | Internal | Own general and hardware run-setup prompts. |
| `lvs_cli_run_setup_history.py` | Internal | Presents and selects stored run-setup history. |
| `lvs_cli_run_setup_bridges.py`, `lvs_cli_heatsoak_bridge.py` | Internal | Translate CLI callbacks into shared setup and heatsoak services. |
| `lvs_cli_settings.py` | Compatibility adapter | Coordinates settings actions exposed through the launcher. |
| `lvs_cli_settings_menu.py`, `lvs_cli_settings_lists.py`, `lvs_cli_settings_advanced.py` | Internal | Own settings menus, list editing, and advanced settings flows. |
| `lvs_diagnostics_cli.py` | Internal adapter | Presents dry-run and dependency diagnostic actions. |
| `lvs_qa_review_cli.py` | Internal backing public entrypoint | Implements argument parsing and payload output for `linux_validation_suite_qa.py`. |

### TUI and shared services

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_tui_app.py` | Internal optional boundary | Owns the concrete Textual application and is the only direct Textual importer. |
| `lvs_tui_*_adapter.py` | Internal | Connect named TUI screens/events to shared service operations. |
| `lvs_tui_*_flow.py` | Internal | Define deterministic, Textual-free transitions and action specifications. |
| `lvs_tui_*_presentation.py` | Internal | Build Textual-free labels, rows, summaries, and view data. |
| `lvs_tui_input_state.py`, `lvs_tui_navigation_state.py` | Internal | Own reusable input and navigation state transitions. |
| `lvs_tui_list_adapter.py`, `lvs_tui_view_models.py` | Internal | Adapt generic lists and shared service data into TUI view models. |
| `linux_validation_suite_service.py` | Public | Composes the supported shared application service facade. |
| `lvs_service_models.py` | Internal contract | Defines data models exchanged between services and frontends. |
| `lvs_service_profiles.py`, `lvs_service_profile_readiness.py` | Internal | Implement profile operations and readiness payloads. |
| `lvs_service_results.py`, `lvs_service_run.py`, `lvs_service_settings.py` | Internal | Implement result, run, and settings service methods. |
| `lvs_runtime_services.py` | Internal composition root | Constructs and normalizes the backend service graph. |

### Profiles and settings

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_profile_models.py` | Internal foundational contract | Defines profile, module, and stage configuration models. |
| `lvs_profile_loader.py` | Internal | Loads, saves, sorts, and labels profile files. |
| `lvs_profile_editor.py`, `lvs_profile_edit_controller.py` | Internal | Perform prompt-free mutations and dispatch edit actions. |
| `lvs_profile_edit_view.py` | Internal | Builds frontend-neutral profile edit presentation data. |
| `lvs_profile_creation.py`, `lvs_profile_save.py` | Internal | Create profiles and perform guarded validation/persistence. |
| `lvs_profile_validation.py` | Internal policy | Defines shared validation rules for profile contracts. |
| `lvs_profile_audit.py` | Internal | Builds profile audit payloads. |
| `lvs_profile_reports.py`, `lvs_profile_report_text.py`, `lvs_profile_report_artifacts.py` | Internal | Build profile reports, render text, and write report artifacts. |
| `lvs_settings.py` | Internal foundational contract | Defines and persists global settings. |
| `lvs_settings_facade.py` | Internal facade | Exposes frontend-neutral settings operations. |
| `lvs_option_defaults.py` | Internal policy | Defines shared default option lists. |

### Run lifecycle

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_run_models.py`, `lvs_run_metadata.py` | Internal foundational contract | Define run state, stage windows, and persisted run metadata. |
| `lvs_run_setup.py`, `lvs_run_setup_controller.py` | Internal | Coordinate run setup and frontend-neutral action dispatch. |
| `lvs_run_setup_actions.py`, `lvs_run_setup_stages.py`, `lvs_run_setup_text.py` | Internal | Define setup actions, stage overrides, and presentation text. |
| `lvs_run_setup_history_service.py` | Internal | Persists and converts run setup history. |
| `lvs_run_preflight.py`, `lvs_dry_run.py` | Internal | Build readiness decisions and non-executing diagnostic plans. |
| `lvs_run_launch.py`, `lvs_run_executor.py`, `lvs_run_flow.py` | Internal | Delegate launch, capture execution, and coordinate frontend run decisions. |
| `lvs_run_execution_context.py` | Internal | Builds callback and output-capture context for run execution. |
| `lvs_run_orchestration.py`, `lvs_validation_orchestrator.py` | Internal composition | Own top-level validation orchestration. |
| `lvs_orchestrator_*` | Internal | Provide stage-analysis, retune, and shared orchestration callbacks. |
| `lvs_run_stage_loop.py`, `lvs_stage_adapter.py`, `lvs_stage_execution.py` | Internal | Drive stage iteration and the stage runtime shell. |
| `lvs_stage_run_context.py`, `lvs_stage_launch_plan.py`, `lvs_stage_process_control.py` | Internal | Define stage context, launch commands, and process lifecycle. |
| `lvs_stage_lifecycle.py`, `lvs_stage_live_loop.py` | Internal | Start/stop stage adjuncts and apply live-loop policy. |
| `lvs_stage_completion.py`, `lvs_stage_evaluation.py`, `lvs_stage_postprocess.py` | Internal | Assemble completed stages, evaluate evidence, and apply bookkeeping. |
| `lvs_stage_event_state.py`, `lvs_stage_stability.py` | Internal | Convert events and stability evidence into stage state. |
| `lvs_stage_diagnostics.py`, `lvs_stage_gpu_diagnostics.py` | Internal | Build general and GPU-specific diagnostic payloads. |
| `lvs_stage_worker_evidence.py`, `lvs_worker_evidence.py`, `lvs_worker_integrity.py` | Internal | Collect, normalize, and validate worker evidence. |
| `lvs_run_completion.py`, `lvs_run_finalization.py`, `lvs_run_verdict.py` | Internal | Complete runs and consolidate final verdicts. |
| `lvs_run_artifacts.py`, `lvs_run_bootstrap.py` | Internal | Write initial and final run artifacts. |
| `lvs_run_lifecycle.py`, `lvs_run_progress.py`, `lvs_run_event_presenter.py` | Internal | Format lifecycle events and progress for frontends. |
| `lvs_faults.py`, `lvs_sensor_events.py`, `lvs_stability_events.py` | Internal evidence | Build system-fault, sensor, and stability events. |
| `lvs_heatsoak.py` | Internal | Coordinates frontend-neutral heatsoak preparation. |
| `lvs_strict_threshold_policy.py` | Internal policy | Produces strict-threshold recommendation warnings. |

### Telemetry, inventory, and workloads

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_telemetry_collector.py` | Internal composition | Discovers sources and coordinates sampling. |
| `lvs_telemetry_sampling.py`, `lvs_telemetry_samples.py` | Internal | Parse raw samples and serialize sample records. |
| `lvs_telemetry_sources.py`, `lvs_telemetry_sensor_io.py`, `lvs_telemetry_device.py` | Internal | Select sources, perform sensor I/O, and discover optional devices. |
| `lvs_telemetry_cpu.py`, `lvs_telemetry_memory.py` | Internal | Own CPU/package and memory telemetry rules. |
| `lvs_telemetry_gpu.py`, `lvs_telemetry_intel.py`, `lvs_telemetry_nvidia.py` | Internal | Discover and sample generic, Intel, and NVIDIA GPU telemetry. |
| `lvs_telemetry_storage_sources.py` | Internal | Discovers and reads storage temperature sources. |
| `lvs_intel_gpu_sidecar.py` | Internal | Manages Intel GPU sidecar sampling and summaries. |
| `lvs_system_info.py` | Internal composition | Collects the complete system hardware inventory. |
| `lvs_system_identity.py`, `lvs_inventory_helpers.py` | Internal | Normalize system identity and raw inventory values. |
| `lvs_cpu_topology.py`, `lvs_cpu_power_limits.py` | Internal | Summarize CPU topology and power-limit evidence. |
| `lvs_storage_inventory.py`, `lvs_pcie_link.py` | Internal | Build storage inventory and trusted PCIe link evidence. |
| `lvs_workload_runner.py` | Internal facade | Composes workload resolution and execution adapters. |
| `lvs_workload_cpu_memory.py` | Internal adapter | Connects CPU and memory execution helpers to the workload runner. |
| `lvs_workload_gpu_runtime.py`, `lvs_workload_gpu_workers.py` | Internal adapter | Connect GPU runtime resolution and worker policy to the runner. |
| `lvs_cpu_execution.py`, `lvs_memory_execution.py` | Internal | Build and evaluate CPU and memory workload commands. |
| `lvs_native_helpers.py` | Internal | Resolves native helper build and runtime availability. |

### GPU and backend implementation

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_gpu_identity.py`, `lvs_gpu_targets.py`, `lvs_gpu_capability.py` | Internal contract | Normalize GPU identity, selectable targets, and capability policy. |
| `lvs_gpu_backend_catalog.py`, `lvs_gpu_backend_support.py` | Internal policy | Define available backends and per-target support. |
| `lvs_gpu_backend_resolver.py`, `lvs_gpu_backend_resolution.py`, `lvs_gpu_backend_runner.py` | Internal | Resolve backend choices, messages, and runner integration. |
| `lvs_gpu_target_resolution.py` | Internal | Resolves runtime OpenCL and Vulkan targets. |
| `lvs_gpu_worker_plan.py`, `lvs_gpu_worker_planner.py` | Internal contract | Define serializable worker specs and build stage worker plans. |
| `lvs_gpu_worker_params.py`, `lvs_gpu_worker_materializer.py`, `lvs_gpu_worker_state.py` | Internal | Size, materialize, and describe GPU workers. |
| `lvs_gpu_retune.py`, `lvs_gpu_retune_policy.py`, `lvs_gpu_retune_process.py`, `lvs_gpu_worker_retune.py` | Internal policy | Decide and apply safe worker retuning. |
| `lvs_gpu_progress.py`, `lvs_gpu_stage_events.py`, `lvs_gpu_stage_targets.py` | Internal evidence | Build progress, stage events, and target evidence. |
| `lvs_gpu_safety_marker.py`, `lvs_gpu_telemetry_warnings.py` | Internal safety | Persist interruption markers and report telemetry coverage. |
| `lvs_gpu_export_helpers.py` | Internal | Normalizes GPU naming and ordering for exports. |
| `lvs_opencl_runtime.py`, `lvs_opencl_targeting.py`, `lvs_opencl_probe_script.py` | Internal | Discover, target, and probe OpenCL runtimes. |
| `lvs_opencl_workers.py`, `lvs_opencl_compute_worker.py`, `lvs_opencl_vram_worker.py` | Internal worker | Build OpenCL worker specs and scripts. |
| `lvs_vulkan_runtime.py`, `lvs_vulkan_targeting.py`, `lvs_vulkan_workers.py` | Internal worker | Discover and target Vulkan runtimes and build workers. |
| `lvs_egl_target_probe.py`, `lvs_egl_probe_script.py` | Internal | Probe EGL/GLES renderer identity and targeting. |
| `lvs_egl_gles_workers.py`, `lvs_egl_gles_worker.py` | Internal worker | Build EGL/GLES worker specs and scripts. |
| `lvs_external_gpu_workers.py`, `lvs_external_gpu_supervisor.py` | Internal worker | Construct and supervise external GPU workloads. |
| `lvs_vram_policy.py` | Internal policy | Defines VRAM allocation and mixed-worker routing. |

### Results, reports, and exports

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_segment_parser.py`, `lvs_segment_parser_services.py` | Internal composition | Parse telemetry segments using injected metric services. |
| `lvs_segment_metric_context.py`, `lvs_segment_metric_helpers.py` | Internal | Hold shared parsing context and metric helper logic. |
| `lvs_segment_cpu_clocks.py`, `lvs_segment_cpu_metrics.py` | Internal | Build CPU clock and package metric sections. |
| `lvs_segment_gpu_metrics.py`, `lvs_segment_gpu_targeting.py`, `lvs_segment_gpu_worker_summary.py` | Internal | Build GPU metric, targeting, and worker summary sections. |
| `lvs_segment_temperature_metrics.py`, `lvs_segment_formatting.py` | Internal | Build temperature metrics and format segment values. |
| `lvs_segment_document_builder.py` | Internal | Assembles the parsed segment document. |
| `lvs_result_reports.py`, `lvs_result_report_workflows.py` | Internal facade | Coordinate result discovery, report payloads, and report operations. |
| `lvs_result_report_adapters.py`, `lvs_result_report_rendering.py`, `lvs_result_report_text.py` | Internal | Read report files and render structured/text output. |
| `lvs_result_validation.py`, `lvs_result_validation_checks.py`, `lvs_result_validation_payload.py` | Internal contract | Validate result folders, checks, and parsed payloads. |
| `lvs_result_artifacts.py`, `lvs_result_artifact_inventory.py`, `lvs_result_artifact_details.py`, `lvs_result_artifact_view.py` | Internal | Discover, classify, describe, and present result artifacts. |
| `lvs_result_comparison.py`, `lvs_result_overview_reports.py` | Internal | Compare completed results and build overview text. |
| `lvs_pre_import_sanity.py` | Internal facade | Performs frontend-neutral importer-readiness checks. |
| `lvs_report_helpers.py`, `lvs_summary_text.py` | Internal contract | Build compatibility report summaries and human-readable run summaries. |
| `lvs_compat_exporter.py`, `lvs_compat_export_builder.py` | Compatibility contract | Coordinate legacy-compatible export construction. |
| `lvs_compat_export_context.py`, `lvs_compat_export_envelope.py`, `lvs_compat_export_metadata.py` | Compatibility contract | Build export context, identity envelope, and metadata. |
| `lvs_compat_export_gpu.py`, `lvs_compat_export_hardware.py` | Compatibility contract | Build GPU and hardware compatibility sections. |
| `lvs_compat_export_helpers.py`, `lvs_compat_export_finalizer.py` | Compatibility contract | Supply shared classification helpers and final composition. |
| `lvs_export_contract.py` | Compatibility contract | Defines compatibility export contract identifiers and versions. |
| `lvs_post_run.py` | Internal | Coordinates post-run metadata, wall wattage, and optional upload. |

### Diagnostics and support

| Module or family | Surface | One-line ownership |
| --- | --- | --- |
| `lvs_dependency_reports.py` | Internal facade | Coordinates dependency and readiness reports. |
| `lvs_dependency_payload.py`, `lvs_dependency_report_text.py`, `lvs_dependency_report_artifacts.py` | Internal contract | Build dependency payloads, text, and artifacts. |
| `lvs_storage_benchmark_profile.py`, `lvs_storage_benchmark_target.py`, `lvs_fio_backend.py`, `lvs_storage_benchmark.py`, `lvs_storage_benchmark_batch.py` | Internal/public workflow contract | Define, safely resolve, execute, and serialize standalone single-target and sequential all-internal Storage Benchmark v1 workflows. |
| `lvs_backend_readiness.py` | Internal | Summarizes executable backend readiness. |
| `lvs_advanced_debug.py` | Internal | Captures optional per-run hardware debug evidence. |
| `lvs_local_environment_export.py` | Internal support contract | Builds redacted public support exports. |
| `lvs_local_migration.py` | Public command | Builds private migration bundles and performs guarded restore. |
| `lvs_hardware_matrix_state.py` | Public command | Maintains ignored local hardware/result validation state. |
| `lvs_privileged.py` | Internal | Manages session-scoped privileged telemetry helpers. |
| `lvs_google_drive_uploader.py` | Internal integration | Handles optional Google Drive readiness and upload operations. |

## Dependency-Layer Rules

Use this default dependency direction:

```text
core/contracts
    -> settings, profiles, inventory, telemetry
    -> GPU backends and workloads
    -> run lifecycle and results
    -> shared services
    -> CLI and TUI entrypoints
```

- Lower layers must not import CLI or TUI modules.
- Core, settings models, profile models, service models, and run models must not
  import orchestrators or frontend adapters.
- CLI and TUI may depend on shared services; shared services must not depend on
  concrete CLI or TUI applications.
- `Modules.lvs_tui_app` may import Textual. Textual-free TUI helpers must not.
- Package `__init__.py` files must stay minimal. Do not add eager convenience
  re-exports that load optional dependencies or reverse the layer direction.
- Orchestrators may compose lower layers. Lower layers must communicate upward
  through return values, events, or injected callbacks rather than importing an
  orchestrator.
- Result/export contract modules may consume normalized evidence, but telemetry
  and workload modules must not depend on report rendering.
- New imports should use one consistent style within a package. Any future move
  must update both absolute `Modules.*` and relative imports and pass the static
  cycle test.

## Future Move Compatibility Rule

No module should move directly from its current path. A future move requires:

1. a new implementation location with a minimal package initializer;
2. a legacy module at the old `Modules.lvs_*` path;
3. explicit symbol and exception compatibility tests;
4. forwarding of `python -m` behavior when the old path is executable;
5. tests for module-global monkeypatch behavior where callers replace imported
   collaborators; and
6. recursive compile, cold-import, optional-dependency, cycle, entrypoint, and
   full smoke-test coverage.

A simple `from new_module import *` wrapper is not automatically sufficient: it
can omit private-but-used names, change class `__module__` values, and break
callers that monkeypatch globals on the legacy module. Keep the implementation
at the legacy path when those behaviors cannot be preserved safely.

The authoritative organization safety checks live in
`smoke_tests/module_organization_checks.py` and run as part of
`smoke_tests/run_smoke_tests.py`.
