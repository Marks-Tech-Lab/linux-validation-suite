#!/usr/bin/env python3
"""Lightweight regression smoke tests for modularization work.

These tests intentionally avoid launching real stress workloads. They exercise
shared service/report helpers that CLI, TUI, and future GUI frontends depend on.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smoke_tests.module_organization_checks import (
    test_modules_cold_import_manifest,
    test_modules_compile_recursively,
    test_modules_have_no_static_internal_import_cycles,
    test_textual_is_confined_to_optional_tui_boundary,
)
from smoke_tests.output_contract_checks import (
    QA_BATCH_REQUIRED_FIELDS,
    QA_REVIEW_REQUIRED_FIELDS,
    assert_contract_identity,
    assert_legacy_custom_result_contract,
    assert_required_fields,
    assert_snake_case_keys,
)

from linux_validation_suite import (
    CompatibilityExporter,
    GoogleDriveUploader,
    JsonStore,
    Launcher,
    ProfileDefaults,
    ProfileValidator,
    RunMetadata,
    RunSummaryTextExporter,
    Sample,
    StageConfig,
    SegmentParser,
    StageWindow,
    TelemetryCollector,
    ValidationProfile,
    WorkloadRunner,
)
from Modules.lvs_dependency_reports import DependencyReportManager
from Modules.lvs_diagnostics_cli import DiagnosticsCliAdapter
from Modules.lvs_advanced_debug import AdvancedDebugLogger
from Modules import lvs_telemetry_intel
from Modules import lvs_telemetry_memory
from Modules import lvs_telemetry_nvidia
from Modules.lvs_faults import LinuxFaultCollector, faults_for_stage_window, summarize_fault_events
from Modules.lvs_gpu_safety_marker import GpuSafetyMarkerStore
from Modules.lvs_gpu_stage_targets import (
    gpu_index_from_metric_key,
    stage_target_gpu_details_from_processes,
    stage_target_gpu_details_from_worker_dicts,
)
from Modules.lvs_gpu_telemetry_warnings import gpu_telemetry_coverage_warnings
from Modules.lvs_gpu_progress import (
    latest_sample_value,
    other_gpu_progress_summary,
    stage_gpu_progress_summary,
    target_gpu_metric_progress_parts,
    target_gpu_progress_summary,
    target_gpu_state_progress_parts,
)
from Modules.lvs_gpu_retune import (
    effective_gpu_retune_cooldown_seconds,
    effective_gpu_retune_warmup_seconds,
    minimum_gpu_retune_remaining_seconds,
    recent_metric_values,
    worker_retune_count,
)
from Modules.lvs_gpu_retune_policy import gpu_worker_retune_decision
from Modules.lvs_gpu_retune_process import replace_gpu_process_for_retune
from Modules.lvs_gpu_stage_events import (
    gpu_backend_effectiveness_events,
    target_gpu_utilization_events,
    vram_target_attainment_events,
)
from Modules.lvs_gpu_worker_state import (
    current_internal_load_fraction,
    planned_internal_gpu_worker_state,
)
from Modules.lvs_gpu_worker_plan import GpuWorkerSpec, serialize_gpu_worker_spec
from Modules.lvs_gpu_worker_materializer import materialize_gpu_worker
from Modules.lvs_gpu_worker_planner import (
    build_gpu_3d_worker_specs,
    build_stage_gpu_worker_specs,
)
from Modules.lvs_gpu_worker_retune import retune_gpu_worker
from Modules.lvs_gpu_backend_resolution import (
    best_partial_gpu_backend_report,
    gpu_backend_resolution_messages,
    gpu_backend_usage_summary,
    gpu_excluded_targets_summary,
    partial_gpu_target_warning,
    unsupported_gpu_target_issue,
)
from Modules.lvs_gpu_backend_resolver import (
    gpu_backend_support_summary,
    resolve_gpu_backend_for_targets,
)
from Modules.lvs_stage_gpu_diagnostics import (
    build_stage_gpu_backend_diagnostics,
    gpu_3d_backend_identity_warnings,
    gpu_3d_intensity_warning,
    gpu_3d_preference_fallback_warning,
    gpu_safe_mode_worker_warnings,
    mixed_stage_gpu_safety_warnings,
    opencl_high_headroom_safety_warning,
    per_target_backend_selection_warning,
    suite_native_gpu_3d_backend_warnings,
    vram_backend_warnings,
    vram_preference_fallback_warning,
)
from Modules.lvs_gpu_backend_support import (
    base_gpu_backend_target_support,
    egl_backend_target_support,
    gpu_backend_target_support,
    opencl_backend_target_support,
    vulkan_backend_target_support,
    vulkan_nvidia_dropout_reason,
)
from Modules.lvs_gpu_backend_catalog import (
    GpuBackendAvailabilityContext,
    allow_per_target_auto_gpu_3d_backends,
    gpu_3d_backend_available,
    gpu_3d_backend_available_from_context,
    gpu_3d_backend_candidates,
    gpu_3d_backend_candidates_by_preference,
    gpu_3d_backend_catalog_entry,
    gpu_3d_backend_preference_catalog,
    normalize_gpu_3d_backend_preference,
    normalize_vram_backend_preference,
    prefer_graphics_backend_for_mixed_stage,
    vram_backend_available,
    vram_backend_available_from_context,
    vram_backend_candidates,
)
from Modules.lvs_vulkan_targeting import (
    slot_from_mesa_style_vulkan_uuid,
    vulkan_device_class_from_match,
    vulkan_device_for_target,
    vulkan_device_pci_slot,
    vulkan_device_score_for_target,
)
from Modules.lvs_vulkan_runtime import (
    build_vulkan_native_runtime_backend,
    collect_vulkan_native_physical_devices,
    collect_vulkan_runtime_details,
    parse_vulkaninfo_summary,
    resolve_vulkan_library,
)
from Modules.lvs_gpu_worker_params import (
    gpu_worker_baseline_params,
    gpu_worker_tuned_params,
    vulkan_compute_buffer_bytes,
    vulkan_compute_dispatch_repeats,
    vulkan_compute_rounds,
    vulkan_transfer_buffer_bytes,
)
from Modules.lvs_vram_policy import (
    amd_discrete_target_count,
    cap_gpu_vram_target_bytes,
    capacity_vram_request_cap_bytes,
    concurrent_vram_skip_target_labels,
    fallback_vram_total_for_target,
    opencl_device_looks_like_shared_memory,
    resolve_target_vram_allocation_bytes,
    route_vulkan_vram_worker_for_target,
    shared_memory_gpu_target_total_bytes,
    skip_concurrent_vram_worker_for_target,
    target_vram_allocation_bytes,
    use_vulkan_vram_worker_for_target,
)
from Modules.lvs_telemetry_nvidia import (
    NVIDIA_CLOCK_EVENT_REASON_FIELDS,
    discover_nvidia_smi_gpus,
    parse_nvidia_active_flag,
    read_nvidia_smi_gpu_metrics,
)
from Modules.lvs_telemetry_intel import (
    intel_gpu_top_metrics_from_text,
    read_intel_gpu_top_metrics,
)
from Modules.lvs_compat_export_helpers import (
    build_cpu_core_frequency_tests,
    build_gpu_metric_test,
    build_gpu_temp_test,
    build_memory_temperature_tests,
    build_storage_temperature_tests,
    compatibility_cpu_power_limit_value,
    compatibility_elapsed_string,
    compatibility_execution_detail,
    compatibility_overall_result,
    gpu_detail_export_sort_key,
    gpu_source_device_class,
    gpu_temp_export_name,
    gpu_worker_backend_name,
    has_core_clock_data,
    has_core_type_data,
    resolve_gpu_source_device_name,
    resolve_gpu_worker_device_name,
    run_manually_aborted,
    should_blank_gpu_power_source,
)
from Modules.lvs_compat_export_builder import build_compatibility_export_document
from Modules.lvs_compat_export_context import build_compatibility_run_context
from Modules.lvs_compat_export_envelope import build_compatibility_identity_envelope
from Modules.lvs_compat_export_finalizer import finalize_compatibility_export
from Modules.lvs_compat_export_gpu import (
    build_compatibility_gpu_section,
    build_gpu_power_details,
    build_gpu_worker_metric_test,
    build_gpu_worker_validation_detail,
)
from Modules.lvs_compat_export_hardware import build_compatibility_hardware_sections
from Modules.lvs_compat_export_metadata import build_compatibility_metadata_block
from Modules.lvs_export_contract import validate_export_contract_compatibility
from Modules.lvs_report_helpers import (
    build_overall_stability_interpretation,
    build_department_use_summary,
    build_report_action_item_details,
    build_report_intel_gpu_top_summary,
    build_report_summary,
    build_report_stage_summary,
    clean_review_verdict_from_payload,
    overall_report_outcome_summary,
    validate_gpu_worker_summary,
    validate_report_action_items,
    validate_report_stage_counts,
    validate_report_summary_mirror,
    validate_stability_alignment,
)
from Modules.lvs_result_report_text import (
    result_overview_text_from_payload,
    result_stage_details_text_from_payload,
)
from Modules.lvs_strict_threshold_policy import (
    optional_bool,
    profile_strict_threshold_recommendation_warnings,
    stage_strict_threshold_recommendation_warnings,
    strict_threshold_warning_scope,
)
from Modules.lvs_result_report_workflows import build_result_validation_payload
from Modules.lvs_stage_launch_plan import build_stage_launch_commands
from Modules.lvs_stage_completion import build_stage_check_window, complete_stage_record, serialize_final_gpu_workers, stage_issue_count
from Modules.lvs_stage_evaluation import evaluate_completed_stage
from Modules.lvs_stage_process_control import (
    StageProcess,
    launch_stage_processes_from_plan,
    stop_processes,
    stop_stage_processes,
)
from Modules.lvs_stage_adapter import run_stage_adapter
from Modules.lvs_stage_event_state import apply_stage_events
from Modules.lvs_stage_execution import execute_stage_runtime
from Modules.lvs_stage_postprocess import apply_completed_stage_bookkeeping
import Modules.lvs_run_stage_loop as run_stage_loop_module
import Modules.lvs_run_completion as run_completion_module
from Modules.lvs_run_event_presenter import CliRunEventPresenter
from Modules.lvs_run_bootstrap import bootstrap_run_artifacts
from Modules.lvs_run_artifacts import write_final_run_artifacts
from Modules.lvs_stage_run_context import (
    apply_cpu_tuning_execution,
    cpu_stage_start_suffix,
    cpu_tune_summary_suffix,
    gpu_stage_start_suffix,
    internal_gpu_backend_set,
    stage_run_context_from_plan,
)
from Modules.lvs_stage_lifecycle import start_stage_lifecycle, stop_stage_lifecycle, stage_targets_intel_gpu
from Modules.lvs_stage_live_loop import run_stage_live_loop
from Modules.lvs_stage_worker_evidence import (
    poll_stage_process_failures,
    read_worker_result,
    worker_result_events,
)
from Modules.lvs_cpu_power_limits import (
    build_cpu_power_limit_info,
    collect_rapl_constraints,
    format_seconds,
    format_watts,
    read_microseconds,
    read_microunit_watts,
    select_rapl_package_dir,
)
from Modules.lvs_cpu_execution import (
    benchmark_cpu_kernel_candidate,
    best_valid_cpu_tuning_candidate,
    build_cpu_benchmark_result,
    build_cpu_command,
    build_cpu_default_kernel_probe_command,
    build_cpu_execution_base,
    build_cpu_fallback_script,
    build_cpu_kernel_support_probe_command,
    build_cpu_resolved_mode_probe_command,
    cpu_kernel_support_probe_matches,
    cpu_candidate_kernel_flavors,
    cpu_fallback_params,
    cpu_mode_for_kernel_flavor,
    cpu_power_tuning_available,
    cpu_tuning_policy,
    normalize_cpu_helper_mode,
    normalize_cpu_probe_mode,
    parse_cpu_default_kernel_probe,
    parse_cpu_resolved_mode_probe,
    resolve_cpu_execution_policy,
)
from Modules.lvs_cpu_topology import (
    collect_cpu_topology_info,
    cpu_package_devices_from_topology,
    parse_proc_cpuinfo_models,
)
from Modules.lvs_heatsoak import HeatsoakManager
from Modules.lvs_gpu_identity import (
    clean_runtime_gpu_name,
    device_class_from_vulkan_type,
    friendly_pci_gpu_name,
    gpu_vendor_family_from_inventory,
    gpu_vendor_family_from_name,
    gpu_vendor_name,
    is_management_display_adapter,
    is_unhelpful_runtime_gpu_name,
    looks_like_cpu_package_gpu_name,
    normalize_pci_id,
    normalize_pci_slot,
    parse_vulkan_summary_devices,
    pci_slot_sort_key,
    runtime_gpu_name_score,
    select_runtime_gpu_name,
    slot_for_vulkan_device,
    slot_from_mesa_vulkan_uuid,
)
from Modules.lvs_gpu_capability import (
    build_gpu_capability_profile,
    gpu_capability_cache_key,
    likely_discrete_target_ids,
)
from Modules.lvs_gpu_targets import (
    dri_prime_selector,
    gpu_card_class,
    gpu_target_by_id,
    gpu_target_display_label,
    gpu_target_summary,
    gpu_targets,
    likely_discrete_gpu_cards,
    lookup_pci_device_name,
)
from Modules.lvs_inventory_helpers import (
    build_memory_speed_summary,
    clean_dmi_value,
    memory_module_display_part_number,
    normalize_memory_modules_for_export,
    parse_dmidecode_memory_modules,
    parse_inxi_memory_modules,
    parse_memory_capacity_gb,
    parse_memory_speed_mhz,
)
from Modules.lvs_memory_execution import (
    build_memory_command,
    build_memory_fallback_script,
    memory_target_bytes,
    memory_worker_count,
)
from Modules.lvs_native_helpers import (
    NativeHelperRuntimeService,
    find_c_compiler,
    native_helper_build_command,
    native_helper_status_base,
    resolve_native_helper_status,
)
from Modules.lvs_storage_inventory import (
    block_device_capacity_gb,
    clean_storage_value,
    collect_storage_info,
    storage_interface_type,
    storage_media_type,
)
from Modules.lvs_pcie_link import pcie_link_info_for_path, read_pcie_link_info, trusted_pcie_link_for_slot
from Modules.lvs_telemetry_storage_sources import discover_storage_temp_sources, read_storage_temps
from Modules.lvs_system_info import SystemInfoCollector
from Modules.lvs_stability_events import (
    create_stability_event,
    dedupe_events,
    event_signature,
    new_unique_events,
    threshold_run_seconds,
)
from Modules.lvs_system_identity import (
    build_bios_info,
    build_linux_os_name,
    build_motherboard_info,
    normalize_dmi_sysfs_value,
    parse_os_release_pretty_name,
)
from Modules.lvs_backend_readiness import (
    build_backend_availability,
    build_backend_availability_from_probe_results,
    build_backend_details_payload,
    build_backend_details_from_probe_results,
    build_egl_backend_payload,
    build_opencl_backend_payload,
    build_vulkan_native_backend_payload,
    build_vulkan_transfer_backend_payload,
    collect_backend_availability_from_runner,
    collect_backend_details_from_runner,
    enrich_cpu_helper_backend_details,
    probe_cpu_helper_modes,
)
from Modules.lvs_google_drive_uploader import GoogleDriveUploader as ModuleGoogleDriveUploader
from Modules.lvs_egl_gles_worker import build_egl_gles_workload_script
from Modules.lvs_egl_target_probe import is_software_renderer, probe_egl_runtime_backend
from Modules.lvs_external_gpu_supervisor import build_external_gpu_supervisor_script
from Modules.lvs_opencl_compute_worker import build_opencl_compute_workload_script
from Modules.lvs_opencl_probe_script import build_opencl_probe_script
from Modules.lvs_opencl_targeting import (
    append_opencl_probe_devices,
    gpu_vendor_aliases,
    gpu_vendor_matches_text,
    opencl_device_identity_key,
    opencl_discover_icds,
    opencl_env_candidates_for_target,
    opencl_find_icd,
    opencl_runtime_context_candidates,
)
from Modules.lvs_opencl_runtime import (
    discover_opencl_backend,
    opencl_compute_safety_profile,
    probe_opencl_runtime_context,
)
from Modules.lvs_opencl_vram_worker import build_opencl_vram_workload_script
import Modules.lvs_dry_run as dry_run_module
from Modules.lvs_intel_gpu_sidecar import (
    collect_intel_gpu_top_details,
    intel_gpu_top_failure_reason,
    intel_gpu_top_json_sample_attempt,
    load_intel_gpu_top_objects,
    start_intel_gpu_top_sidecar,
    stop_intel_gpu_top_sidecar,
    summarize_intel_gpu_top_sidecar,
    summarize_numeric_series,
)
from Modules.lvs_post_run import PostRunManager
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_reports import ProfileReportManager
from Modules.lvs_profile_reports import (
    dry_run_plan_line,
    profile_audit_item_line,
    profile_audit_item_status,
    profile_execution_cpu_line,
    profile_execution_gpu_3d_line,
    profile_execution_gpu_detail_lines,
    profile_execution_stage_header_line,
    profile_execution_stage_status,
    profile_execution_memory_line,
    profile_execution_trim_line,
    profile_execution_vram_line,
)
from Modules.lvs_result_reports import (
    ResultReportManager,
    artifact_detail_text,
    batch_result_validation_text,
    batch_pre_import_sanity_text,
    format_result_metric_number,
    format_result_metric_pair,
    format_result_metric_triplet,
    missing_result_overview_text,
    missing_result_stage_details_text,
    pre_import_batch_line,
    result_action_item_line,
    result_gpu_highlight_line,
    result_overview_stage_line,
    result_comparison_text,
    result_validation_batch_line,
    result_validation_issue_line,
    result_validation_text,
    selected_pre_import_sanity_text,
)
from Modules.lvs_result_validation import ResultValidationFacade
from Modules.lvs_result_comparison import ResultComparisonFacade
from Modules.lvs_result_report_adapters import list_result_entries, read_result_json, result_summary_text
from Modules.lvs_pre_import_sanity import PreImportSanityFacade
from Modules.lvs_result_artifacts import ResultArtifactFacade
from Modules.lvs_result_artifact_view import (
    result_artifact_choice_label,
    result_artifact_choice_text,
    result_artifact_inventory_text,
    result_artifact_item_extras,
)
from Modules.lvs_run_lifecycle import future_local_iso, phase_line
from Modules.lvs_run_progress import (
    is_phase_progress_line,
    latest_phase_line,
    normalize_progress_line,
    parse_progress_event,
    run_event_history_text,
    RunStatusTracker,
    run_status_detail_text,
    short_status_text,
)
from Modules.lvs_cli_live_run import CliLiveRunPresenter, cli_live_run_supported
from Modules.lvs_cli_preflight_summary import compact_cli_preflight_summary
from Modules.lvs_cli_screen import clear_cli_screen, cli_screen_refresh_supported
from Modules.lvs_cli_heatsoak_compat import HeatsoakCompatibilityMixin
from Modules.lvs_run_finalization import finalize_run_stage_windows
from Modules.lvs_run_verdict import combine_run_verdict
from Modules.lvs_sensor_events import stage_sensor_events
from Modules.lvs_run_execution_context import CallbackStringIO, build_heatsoak_debug, build_profile_run_context
from Modules.lvs_run_executor import RunExecutionError, RunExecutor
from Modules.lvs_run_flow import RunFlowCoordinator, build_run_preflight_action_summary
from Modules.lvs_run_launch import RunLaunchCoordinator, RunLaunchRequest
from Modules.lvs_run_preflight import RunPreflightManager
import Modules.lvs_cli_run as cli_run_module
from Modules.lvs_cli_run import RunCliAdapter
from Modules.lvs_cli_run_setup import RunSetupCliAdapter
from Modules.lvs_cli_results import ResultCliAdapter
from Modules.lvs_run_setup import RunSetupManager
from Modules.lvs_run_setup_controller import RunSetupActionController, RunSetupPromptCallbacks, RunSetupReviewController
from Modules.lvs_profile_editor import ProfileEditor
from Modules.lvs_profile_edit_controller import ProfileEditController
from Modules.lvs_profile_creation import (
    ProfileCreationController,
    ProfileCreationRequest,
    ProfileStageDraft,
)
from Modules.lvs_profile_save import ProfileSaveController
from Modules.lvs_profile_validation import ProfileValidator as SharedProfileValidator
from Modules.lvs_profile_models import ModuleCpu
from Modules.lvs_profile_edit_view import (
    ProfileEditPresenter,
    profile_detail_lines,
    profile_dry_run_preview_text,
    profile_stage_detail_lines,
    stage_enabled_module_names,
    strict_threshold_override_text,
    vram_backend_candidates_for_preference,
    vram_backend_description,
    vram_backend_display_name,
)
from Modules.lvs_service_models import FrontendActionSpec, ProfileEditState, RunResult, RunSetupHistoryEntry, RunSetupState
from Modules.lvs_service_results import QA_REVIEW_CONTRACT_ID, QA_REVIEW_CONTRACT_VERSION
from Modules.lvs_hardware_matrix_state import (
    discover_hardware_matrix_state,
    empty_hardware_matrix_state,
    load_hardware_matrix,
    load_hardware_matrix_state,
    matrix_categories,
    matrix_state_file,
    prune_stale_hardware_matrix_state,
    refresh_hardware_matrix_state,
    validate_hardware_matrix_state,
)
from Modules.lvs_local_environment_export import (
    EXPORT_CONTRACT_ID,
    EXPORT_CONTRACT_VERSION,
    PublicSupportExporter,
)
from Modules.lvs_local_migration import (
    HARDWARE_STATE_BUNDLE_PATH,
    HISTORY_BUNDLE_PATH,
    MANIFEST_NAME,
    MIGRATION_CONTRACT_ID,
    MIGRATION_CONTRACT_VERSION,
    SETTINGS_BUNDLE_PATH,
    LocalMigrationManager,
    main as local_migration_main,
)
from Modules.lvs_qa_review_cli import main as qa_review_cli_main
from Modules.lvs_settings import GlobalSettings, SettingsManager
from Modules.lvs_settings_facade import SettingsFacade
from Modules.lvs_runtime_services import build_runtime_services, normalize_runtime_settings
from Modules.lvs_segment_formatting import format_analysis_window, format_segment_duration
from Modules.lvs_segment_parser_services import build_segment_parser_services
from Modules.linux_validation_suite_service import SuiteAppService
from Modules.lvs_tui_view_models import (
    picker_row_labels,
    profile_edit_row_label,
    profile_row_label,
    result_row_label,
    setup_action_row_label,
    setup_history_row_label,
)
from Modules.lvs_tui_input_state import DEFAULT_SETUP_INPUT_PLACEHOLDER, tui_input_reset_state, tui_input_state
from Modules.lvs_tui_list_adapter import replace_list_labels
from Modules.lvs_tui_navigation_state import tui_navigation_reset
from Modules.lvs_tui_picker_presentation import (
    profile_edit_picker_open_presentation,
    profile_edit_picker_presentation,
    setup_picker_open_presentation,
    setup_picker_presentation,
)
from Modules.lvs_tui_profile_edit_presentation import (
    profile_edit_description_input_presentation,
    profile_edit_failed_detail,
    profile_edit_name_input_presentation,
    profile_edit_presentation,
    profile_edit_stage_input_presentation,
    profile_edit_updated_detail,
    selected_stage_detail_text,
)
from Modules.lvs_tui_profile_edit_flow import (
    normalized_profile_edit_input_value,
    profile_edit_trim_start_value,
    selected_profile_edit_stage_index,
)
from Modules.lvs_tui_app_actions_flow import (
    ACTION_BUTTONS,
    ACTION_BUTTON_ROWS,
    GLOBAL_ACTION_BUTTONS,
    GLOBAL_ACTION_BAR_ROWS,
    action_layout_width,
    compact_action_help_text,
    global_action_cell_rows,
    global_action_keypress,
    global_action_markup,
    global_action_bar_text,
    layout_action_button_rows,
    migration_support_sidebar_state,
    profiles_sidebar_state,
    results_sidebar_state,
    settings_sidebar_state,
)
from Modules.lvs_tui_profile_presentation import profile_summary_presentation
from Modules.lvs_tui_result_presentation import (
    qa_result_review_presentation,
    result_stage_details_presentation,
    result_summary_presentation,
)
from Modules.lvs_tui_run_setup_presentation import (
    RUN_SETUP_HISTORY_SIDEBAR_TITLE,
    RUN_SETUP_SIDEBAR_TITLE,
    RUN_SETUP_STAGE_INPUT_COMPLETE,
    RUN_SETUP_STAGE_INPUT_COMPLETE_TRIM,
    RUN_SETUP_STAGE_INPUT_NOOP,
    RUN_SETUP_STAGE_INPUT_TRIM_END,
    run_setup_detail_presentation,
    run_setup_history_confirm_presentation,
    run_setup_history_loaded_detail,
    run_setup_history_presentation,
    run_setup_history_prompt_presentation,
    run_setup_input_presentation,
    run_setup_no_history_detail,
    run_setup_sidebar_presentation,
    run_setup_stage_input_transition,
)
from Modules.lvs_tui_run_setup_flow import (
    power_limit_amd_type_transition,
    power_limit_input_transition,
    power_limit_vendor_transition,
    prepared_run_readiness_text,
)
from Modules.lvs_tui_settings_list_presentation import (
    settings_input_presentation,
    settings_list_input_presentation,
    settings_list_presentation,
)
from Modules.lvs_tui_post_run_flow import (
    POST_RUN_ACTION_COMPLETE,
    POST_RUN_ACTION_FAILED,
    POST_RUN_ACTION_UPLOAD_PROMPT,
    POST_RUN_ACTION_WALL_WATTAGE,
    UPLOAD_PROMPT_OPTIONS,
    post_run_completion_transition,
    post_run_prompt_presentation,
    post_run_skip_upload_base_text,
    post_run_upload_prompt_spec,
    post_run_wall_wattage_prompt_spec,
    should_prompt_for_post_run_upload,
)
from Modules.lvs_tui_run_presentation import (
    RUN_ACTIVE_SIDEBAR_ROWS,
    RUN_ACTIVE_SIDEBAR_TITLE,
    active_stage_line_text,
    initial_run_active_presentation,
    live_system_gpu_metrics,
    live_system_layout,
    live_system_text,
    locked_post_run_upload_text,
    locked_post_run_wall_wattage_text,
    locked_run_detail_text,
    output_tail_text,
    post_run_operator_presentation,
    run_confirmation_presentation,
    run_progress_detail_text,
    stage_progress_table_text,
)
from Modules.lvs_tui_run_execution_flow import (
    apply_run_output_line,
    upload_active_detail,
    upload_finish_result,
    upload_not_ready_detail,
    upload_workflow_detail,
    uploaded_result_dir,
)
from Modules.lvs_tui_event_flow import (
    button_action,
    event_key,
    index_in_range,
    is_escape_key,
    pending_input_route,
    selected_index,
    setup_input_value,
    view_uses_escape_cancel,
)
from Modules.lvs_tui_profile_edit_adapter import TuiProfileEditAdapterMixin
from Modules.lvs_tui_app_actions_adapter import TuiAppActionsAdapterMixin
from Modules.lvs_tui_event_adapter import TuiEventAdapterMixin
from Modules.lvs_tui_results_adapter import TuiResultsAdapterMixin
from Modules.lvs_tui_run_execution_adapter import TuiRunExecutionAdapterMixin
from Modules.lvs_tui_run_setup_adapter import TuiRunSetupAdapterMixin
from Modules.lvs_tui_settings_adapter import TuiSettingsAdapterMixin
from Modules.lvs_telemetry_sources import (
    build_gpu_telemetry_matrix,
    build_telemetry_capability_summary,
    build_telemetry_source_map,
    metric_gpu_count,
    preferred_metric_source,
    source_thresholds,
    telemetry_source_description,
    unreadable_source_description,
)
from Modules.lvs_telemetry_sampling import (
    json_objects_from_text,
    metric_number,
    parse_gpu_clock_text,
    parse_intel_gpu_top_snapshot,
    parse_mb_to_gb,
    parse_optional_float,
    parse_percent_text,
    parse_power_text_w,
    parse_temperature_text,
    parse_vram_used_gb_from_bytes_text,
    walk_json_numbers,
)
from Modules.lvs_telemetry_samples import (
    telemetry_csv_fieldnames,
    telemetry_sample_row,
    write_telemetry_csv,
)
from Modules.lvs_telemetry_sensor_io import (
    hwmon_temp_thresholds,
    read_hwmon_temp_limit,
    read_temp_limit_c,
    safe_read_text,
    sensor_label as telemetry_sensor_label,
    thermal_zone_thresholds,
)
from Modules.lvs_telemetry_gpu import (
    discover_gpu_cards as discover_gpu_cards_helper,
    discover_gpu_sources as discover_gpu_sources_helper,
    gpu_hwmon_dirs,
    gpu_temp_metric,
    gpu_voltage_metric,
    parse_voltage_text_v,
    read_gpu_clock,
    read_gpu_values,
)
from Modules.lvs_telemetry_memory import (
    cached_ipmi_sensor_temperatures,
    discover_memory_temp_sources,
    discover_memory_temp_sources_with_ipmi,
    ipmi_memory_sensor_sort_key,
    parse_ipmi_sensor_temperatures,
    read_ipmi_sensor_temperatures,
    read_memory_temps,
    run_ipmitool_sensor_text,
    looks_like_ipmi_memory_temperature,
)
from Modules.lvs_telemetry_cpu import (
    add_privileged_cpu_power_sources,
    aggregate_cpu_package_power_source,
    assign_cpu_package_temp_sources,
    cpu_core_classification_summary_from_topology,
    cpu_index_from_name,
    cpu_package_id_from_power_source,
    cpu_package_id_from_temp_source,
    cpu_package_ids_from_topology,
    discover_cpu_clock_source,
    discover_cpu_core_clock_sources,
    discover_cpu_core_topology,
    discover_cpu_power_candidates,
    discover_cpu_power_source,
    discover_cpu_temp_sources,
    parse_cpu_list,
    parse_explicit_core_type,
    performance_tiers,
    read_cpu_clock_mhz,
    read_cpu_core_clocks,
    read_cpu_package_temps,
    read_cpu_power,
    read_cpu_sysfs_int,
    read_cpu_temp,
    read_energy_power_source,
    read_hwmon_power_source,
    read_temperature_path,
    score_cpu_power_source,
    score_cpu_temp_source,
    score_energy_source,
    score_rapl_source,
    score_thermal_zone,
)
from Modules.lvs_telemetry_device import (
    discover_board_temp_sources,
    discover_nic_temp_sources,
    discover_wifi_temp_sources,
    read_device_temps,
)
from Modules.lvs_worker_evidence import (
    apply_worker_entry_context,
    fallback_worker_payload,
    read_log_tail,
    worker_result_events_from_payload,
)


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value, message: str) -> None:
    if not value:
        raise AssertionError(message)


def test_output_contract_index_and_casing_policy() -> None:
    document = (ROOT / "OUTPUT_CONTRACT_INDEX.md").read_text(encoding="utf-8")
    for classification in (
        "LVS-owned snake_case contract",
        "OCCT/legacy compatibility contract",
        "Embedded external/vendor/raw payload",
        "Mixed compatibility artifact",
        "Text/CSV companion",
    ):
        assert_true(classification in document, f"output contract classification documented: {classification}")
    for artifact in (
        "parsed_results_custom.json",
        "parsed_results_extended.json",
        "run_manifest.json",
        "dependency_check.json",
        "public_support_summary.json",
        "migration_manifest.json",
        "hardware_result_validation_matrix.json",
        "hardware_result_validation_state.json",
    ):
        assert_true(artifact in document, f"output contract artifact documented: {artifact}")
    for policy in (
        "New LVS-owned JSON schema properties use `snake_case`",
        "`contract_id`, `contract_version`, and",
        "`parsed_results_custom.json` is frozen",
        "Do not use blind recursive case conversion",
    ):
        assert_true(policy in document, f"output casing policy documented: {policy}")


def test_lvs_owned_versioned_contract_key_casing() -> None:
    matrix = json.loads((ROOT / "hardware_result_validation_matrix.json").read_text(encoding="utf-8"))
    assert_contract_identity(
        matrix,
        contract_id="linux_validation_suite.hardware_result_validation_matrix",
        contract_version=2,
        kind="public_coverage_definition",
        label="hardware validation matrix",
    )
    assert_snake_case_keys(matrix, label="hardware validation matrix")

    state = empty_hardware_matrix_state(matrix)
    assert_contract_identity(
        state,
        contract_id="linux_validation_suite.hardware_result_validation_state",
        contract_version=1,
        kind="local_retained_result_state",
        label="hardware validation state",
    )
    assert_snake_case_keys(state, label="hardware validation state")

    wrapper_fixture = json.loads(
        (ROOT / "smoke_tests" / "fixtures" / "qa_review_cli_wrapper_shape_fixture.json").read_text(
            encoding="utf-8"
        )
    )
    for name, kind in (("review", "qa_result_review"), ("batch", "qa_result_review_batch")):
        payload = wrapper_fixture[name]
        assert_contract_identity(
            payload,
            contract_id=QA_REVIEW_CONTRACT_ID,
            contract_version=QA_REVIEW_CONTRACT_VERSION,
            kind=kind,
            label=f"QA wrapper {name}",
        )
    assert_snake_case_keys(wrapper_fixture, label="QA wrapper fixture")


def test_legacy_result_fixture_contract_and_consumer_paths() -> None:
    fixture_path = ROOT / "smoke_tests" / "fixtures" / "report_export_contract_gpu_troubleshooting_extended_trimmed.json"
    parsed = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert_legacy_custom_result_contract(parsed)
    assert_equal(validate_export_contract_compatibility(parsed)["issues"], [], "legacy fixture importer contract")

    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        result_dir = root / "retained_fixture"
        baseline_dir = root / "retained_baseline"
        result_dir.mkdir()
        baseline_dir.mkdir()
        JsonStore.write(result_dir / "parsed_results_custom.json", parsed)
        JsonStore.write(baseline_dir / "parsed_results_custom.json", parsed)

        assert_equal(read_result_json(result_dir / "parsed_results_custom.json"), parsed, "result JSON adapter")
        entries = list_result_entries(root)
        selected = next(entry for entry in entries if entry.path == result_dir)
        assert_equal(selected.profile_name, "GPU Troubleshooting Extended", "result list adapter profile")
        assert_equal(selected.verdict, "Failed", "result list adapter verdict")

        summary_exporter = RunSummaryTextExporter()
        summary = result_summary_text(result_dir, summary_exporter)
        assert_true("Linux Validation Suite Run Summary" in summary, "legacy fixture summary adapter")
        assert_true("Result: Failed" in summary, "legacy fixture summary result")

        validation_facade = ResultValidationFacade(root)
        validation = validation_facade.validate_result_folder(result_dir, summary_exporter)
        assert_equal(validation["kind"], "result_validation", "legacy fixture validation path")
        assert_true(isinstance(validation.get("checks"), dict), "legacy fixture validation checks")

        comparison = ResultComparisonFacade().compare_result_folders(baseline_dir, result_dir)
        assert_equal(comparison["kind"], "result_comparison", "legacy fixture comparison path")
        assert_equal(comparison["baseline"]["result"], "Failed", "legacy fixture comparison result")

        service = SuiteAppService.__new__(SuiteAppService)
        service.summary_exporter = summary_exporter
        service.result_validation = validation_facade
        service.result_comparison = ResultComparisonFacade()
        service.pre_import_sanity = PreImportSanityFacade(root, validation_facade, summary_exporter)
        service.result_artifacts = ResultArtifactFacade(root)
        review = service.qa_result_review_payload(result_dir, refresh_summary=False)
        assert_required_fields(review, QA_REVIEW_REQUIRED_FIELDS, label="QA retained-fixture review")
        assert_contract_identity(
            review,
            contract_id=QA_REVIEW_CONTRACT_ID,
            contract_version=QA_REVIEW_CONTRACT_VERSION,
            kind="qa_result_review",
            label="QA retained-fixture review",
        )
        assert_snake_case_keys(
            review,
            excluded_subtrees={
                ("validation",),
                ("pre_import_sanity",),
                ("comparison",),
                ("review_verdict",),
                ("worker_failure_evidence", "raw_summary"),
                ("action_item_summary", "details"),
            },
            label="QA retained-fixture LVS envelope",
        )


def test_duplicate_gpu_temperature_names() -> None:
    services = build_segment_parser_services(lambda _window: False)
    samples = [
        Sample(0.0, {"gpu_0_temp_core_c": 70.0, "gpu_1_temp_core_c": 60.0}),
        Sample(1.0, {"gpu_0_temp_core_c": 72.0, "gpu_1_temp_core_c": 62.0}),
    ]
    group = services.temperature_metrics.gpu_temp_group(
        samples,
        "temp_core_c",
        "edge",
        {0: "NVIDIA GeForce RTX 5090", 1: "NVIDIA GeForce RTX 5090"},
        {1: 0, 0: 1},
    )
    names = [gpu["Name"] for gpu in group["Gpus"]]
    base_names = [gpu["BaseName"] for gpu in group["Gpus"]]
    assert_equal(names, ["NVIDIA GeForce RTX 5090 #1", "NVIDIA GeForce RTX 5090 #2"], "duplicate GPU temp names")
    assert_equal(base_names, ["NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 5090"], "base GPU temp names")


def test_storage_secondary_temperature_parsed_detail() -> None:
    services = build_segment_parser_services(lambda _window: False)
    telemetry = SimpleNamespace(
        _storage_temp_sources=[
            {
                "kind": "storage_temp",
                "key": "storage_drive_0_temp_c",
                "label": "Smoke NVMe Composite",
                "drive_index": 0,
                "block_name": "nvme0n1",
                "device_name": "Smoke NVMe",
            },
            {
                "kind": "storage_temp_secondary",
                "key": "storage_drive_0_sensor_1_temp_c",
                "label": "Smoke NVMe Sensor 1",
                "drive_index": 0,
                "sensor_index": 1,
                "block_name": "nvme0n1",
                "device_name": "Smoke NVMe",
            },
        ]
    )
    samples = [
        Sample(0.0, {"storage_drive_0_temp_c": 40.0, "storage_drive_0_sensor_1_temp_c": 41.0}),
        Sample(1.0, {"storage_drive_0_temp_c": 42.0, "storage_drive_0_sensor_1_temp_c": 43.0}),
    ]
    drives = services.temperature_metrics.storage_temp_entries(samples, telemetry)
    assert_equal(len(drives), 1, "storage parsed primary drive count ignores secondary sensors")
    assert_equal(drives[0]["Temperatures"]["Max"], 42.0, "storage parsed primary temp unchanged")
    assert_equal(len(drives[0]["Sensors"]), 1, "storage parsed secondary sensor count")
    assert_equal(drives[0]["Sensors"][0]["SensorIndex"], 1, "storage parsed secondary sensor index")
    assert_equal(drives[0]["Sensors"][0]["Temperatures"]["Max"], 43.0, "storage parsed secondary sensor stats")
    aggregate = services.temperature_metrics.aggregate_storage_temp_stats(drives)
    assert_equal(aggregate["DriveCount"], 1, "storage parsed aggregate drive count unchanged")
    assert_equal(aggregate["Max"], 42.0, "storage parsed aggregate ignores secondary sensors")


def test_segment_formatting_helpers() -> None:
    window = SimpleNamespace(
        started_monotonic=100.0,
        analysis_start=130.04,
        analysis_end=360.06,
    )
    assert_equal(format_segment_duration(3661.4), "01:01:01", "segment duration hms formatting")
    assert_equal(format_analysis_window(window), "30.0s - 260.1s", "segment analysis window formatting")


def test_tui_view_model_row_labels() -> None:
    profile = SimpleNamespace(name="PL Validation", menu_group_label="Production")
    result = SimpleNamespace(name="2026-06-30_Run", verdict="warning")
    history = SimpleNamespace(
        case_sku="CASE-1",
        description="Rack system",
        profile_name="PL Validation",
        profile_file="PL Validation.json",
        psu_wattage="1200W",
        saved="2026-06-30",
    )
    assert_equal(profile_row_label(profile), "PL Validation\n  Production", "TUI profile row label")
    assert_equal(result_row_label(result), "2026-06-30_Run\n  warning", "TUI result row label")
    assert_equal(
        setup_history_row_label(history),
        "CASE-1 | Rack system\n  PL Validation | 1200W | 2026-06-30",
        "TUI setup history row label",
    )
    assert_equal(profile_edit_row_label(SimpleNamespace(label="Stage 1")), "Stage 1", "TUI profile edit row label")
    assert_equal(
        setup_action_row_label(FrontendActionSpec("1", "input", "case_sku", "Case SKU", "required")),
        "Case SKU\n1 -- required",
        "TUI setup action row label",
    )
    labels, selected_index = picker_row_labels(["Auto", "Manual"], "manual")
    assert_equal(labels, ["Auto", "Manual <- current"], "TUI picker row labels")
    assert_equal(selected_index, 1, "TUI picker selected index")


def test_tui_list_adapter() -> None:
    class FakeListView:
        def __init__(self) -> None:
            self.rows = ["old"]
            self.index = None
            self.focused = False

        async def clear(self) -> None:
            self.rows.clear()

        async def append(self, item) -> None:
            self.rows.append(item)

        def focus(self) -> None:
            self.focused = True

    async def run_check() -> None:
        view = FakeListView()
        count = await replace_list_labels(
            view,
            ["one", "two"],
            lambda text: f"item:{text}",
            selected_index=9,
            focus=True,
        )
        assert_equal(count, 2, "TUI list adapter row count")
        assert_equal(view.rows, ["item:one", "item:two"], "TUI list adapter rows")
        assert_equal(view.index, 1, "TUI list adapter clamps selected index")
        assert_true(view.focused, "TUI list adapter focuses list")

    asyncio.run(run_check())


def test_tui_input_state_helpers() -> None:
    state = tui_input_state(
        "field",
        value=None,
        placeholder="Enter value",
        detail="Detail text",
        blank_default="Auto",
        enabled=False,
        focus=False,
    )
    assert_equal(state.pending_field, "field", "TUI input state field")
    assert_equal(state.value, "", "TUI input state normalizes None value")
    assert_equal(state.placeholder, "Enter value", "TUI input state placeholder")
    assert_equal(state.detail, "Detail text", "TUI input state detail")
    assert_equal(state.blank_default, "Auto", "TUI input state blank default")
    assert_equal(state.enabled, False, "TUI input state disabled flag")
    assert_equal(state.focus, False, "TUI input state focus flag")
    reset_state = tui_input_reset_state(value=None)
    assert_equal(reset_state.value, "", "TUI input reset normalizes None value")
    assert_equal(
        reset_state.placeholder,
        DEFAULT_SETUP_INPUT_PLACEHOLDER,
        "TUI input reset default placeholder",
    )
    assert_equal(reset_state.blank_default, "", "TUI input reset blank default")
    assert_equal(reset_state.enabled, False, "TUI input reset disabled by default")


def test_tui_navigation_reset_spec() -> None:
    default = tui_navigation_reset()
    assert_true(default.clear_confirm_run, "TUI navigation reset clears confirmation by default")
    assert_true(default.clear_pending_input, "TUI navigation reset clears input by default")
    assert_true(default.clear_setup_picker, "TUI navigation reset clears setup picker by default")
    assert_equal(
        default.clear_profile_edit_picker,
        False,
        "TUI navigation reset preserves profile edit picker by default",
    )
    assert_true(default.reset_input_widget, "TUI navigation reset resets input widget by default")
    scoped = tui_navigation_reset(
        clear_setup_picker=False,
        clear_profile_edit_picker=True,
        clear_setting_list=True,
        clear_selected_profile=True,
        clear_selected_result=True,
    )
    assert_equal(scoped.clear_setup_picker, False, "TUI navigation reset can preserve setup picker")
    assert_true(scoped.clear_profile_edit_picker, "TUI navigation reset can clear profile edit picker")
    assert_true(scoped.clear_setting_list, "TUI navigation reset can clear setting list")
    assert_true(scoped.clear_selected_profile, "TUI navigation reset can clear selected profile")
    assert_true(scoped.clear_selected_result, "TUI navigation reset can clear selected result")


def test_tui_picker_presentation_helpers() -> None:
    setup_spec = SimpleNamespace(
        key="case_sku",
        title="Case/SKU",
        options=["A", "B"],
        current="B",
    )
    setup = setup_picker_presentation(setup_spec, "Setup summary")
    assert_equal(setup.key, "case_sku", "TUI setup picker key")
    assert_equal(setup.view_mode, "setup_picker", "TUI setup picker view mode")
    assert_equal(setup.labels, ("A", "B <- current"), "TUI setup picker labels")
    assert_equal(setup.selected_index, 1, "TUI setup picker selected index")
    assert_true("Setup summary" in setup.detail, "TUI setup picker summary")
    assert_true("Choosing: Case/SKU" in setup.detail, "TUI setup picker title detail")
    setup_open = setup_picker_open_presentation(setup_spec, "Setup summary")
    assert_equal(setup_open.picker, setup, "TUI setup picker open wraps picker presentation")
    assert_equal(setup_open.key, "case_sku", "TUI setup picker open key")
    assert_equal(setup_open.options, ("A", "B"), "TUI setup picker open options")
    assert_equal(setup_open.confirm_run, False, "TUI setup picker open clears confirmation")

    profile_spec = SimpleNamespace(
        key="stage_runner",
        title="Stage runner",
        options=["CPU", "GPU"],
        current="CPU",
    )
    profile = profile_edit_picker_presentation(profile_spec, "Profile summary")
    assert_equal(profile.key, "stage_runner", "TUI profile picker key")
    assert_equal(profile.view_mode, "profile_edit_picker", "TUI profile picker view mode")
    assert_equal(profile.labels, ("CPU <- current", "GPU"), "TUI profile picker labels")
    assert_equal(profile.selected_index, 0, "TUI profile picker selected index")
    assert_true("Profile summary" in profile.detail, "TUI profile picker summary")
    assert_true("Choosing: Stage runner" in profile.detail, "TUI profile picker title detail")
    profile_open = profile_edit_picker_open_presentation(profile_spec, "Profile summary", stage_index=3)
    assert_equal(profile_open.picker, profile, "TUI profile picker open wraps picker presentation")
    assert_equal(profile_open.key, "stage_runner", "TUI profile picker open key")
    assert_equal(profile_open.options, ("CPU", "GPU"), "TUI profile picker open options")
    assert_equal(profile_open.stage_index, 3, "TUI profile picker open stage index")


def test_tui_profile_edit_presentation_helpers() -> None:
    items = [
        SimpleNamespace(label="Save profile"),
        SimpleNamespace(label="Stage 1"),
    ]
    presentation = profile_edit_presentation(items, 7, "Summary text", "Updated")
    assert_equal(presentation.labels, ("Save profile", "Stage 1"), "TUI profile edit labels")
    assert_equal(presentation.selected_index, 1, "TUI profile edit clamps selected index")
    assert_equal(presentation.detail, "Updated\n\nSummary text", "TUI profile edit detail prefix")
    empty = profile_edit_presentation([], 0, "Summary text")
    assert_equal(empty.selected_index, None, "TUI profile edit empty selected index")
    stage_detail = selected_stage_detail_text("Summary text")
    assert_true("Summary text" in stage_detail, "TUI profile edit selected stage summary")
    assert_true("Selected stage" in stage_detail, "TUI profile edit selected stage title")
    assert_true("GPU target" in stage_detail, "TUI profile edit selected stage actions")
    name_input = profile_edit_name_input_presentation(value="PL Validation", profile_summary="Summary text")
    assert_equal(name_input.pending_field, "__profile_name", "TUI profile edit name input field")
    assert_equal(name_input.value, "PL Validation", "TUI profile edit name input value")
    assert_equal(name_input.placeholder, "Enter profile name and press Enter", "TUI profile edit name placeholder")
    assert_true("Editing profile name" in name_input.detail, "TUI profile edit name detail")
    description_input = profile_edit_description_input_presentation(
        value="Menu description",
        profile_summary="Summary text",
    )
    assert_equal(
        description_input.pending_field,
        "__profile_description",
        "TUI profile edit description input field",
    )
    assert_equal(description_input.value, "Menu description", "TUI profile edit description value")
    assert_true(
        "Enter profile menu description" in description_input.placeholder,
        "TUI profile edit description placeholder",
    )
    stage_input = profile_edit_stage_input_presentation(
        spec=SimpleNamespace(field="__profile_stage_duration", label="Duration seconds", initial_value=600),
        profile_summary="Summary text",
    )
    assert_equal(stage_input.pending_field, "__profile_stage_duration", "TUI profile edit stage input field")
    assert_equal(stage_input.value, "600", "TUI profile edit stage input value")
    assert_equal(stage_input.placeholder, "Enter Duration seconds and press Enter", "TUI profile edit stage placeholder")
    assert_true("Editing: Duration seconds" in stage_input.detail, "TUI profile edit stage detail")
    assert_equal(profile_edit_updated_detail(), "Profile edit updated.", "TUI profile edit updated detail")
    assert_equal(
        profile_edit_failed_detail("bad value", "Summary text"),
        "Profile edit failed:\nbad value\n\nSummary text",
        "TUI profile edit failed detail",
    )


def test_tui_result_presentation_helpers() -> None:
    summary = result_summary_presentation("Overview", "Summary", "Help")
    assert_equal(
        summary,
        "Overview\nRun Summary\n===========\n\nSummary\n\nHelp\n",
        "TUI result summary presentation",
    )
    stage_details = result_stage_details_presentation("Stage details", "Help")
    assert_equal(stage_details, "Stage details\nHelp\n", "TUI result stage details presentation")
    qa_review = qa_result_review_presentation(
        {
            "result_folder": "/tmp/result",
            "identity": {
                "folder_name": "Result Folder",
                "result": "Failed",
                "outcome_class": "workload_or_integrity_failure",
            },
            "decisions": {
                "review": {"status": "ready"},
                "import": {"status": "fail", "blocking": True},
                "compare": {"status": "compared"},
                "escalate": {"needed": True, "reasons": ["worker_failures"]},
            },
            "validation_status": {
                "result": "fail",
                "errors": 2,
                "warnings": 3,
                "issue_category_counts": {"gpu_worker_summary": 1},
            },
            "worker_failure_evidence": {
                "worker_result_count": 9,
                "successful_worker_result_count": 8,
                "worker_failure_count": 1,
                "verification_passes": 20308,
            },
            "action_item_summary": {
                "total": 2,
                "severity_counts": {"error": 1, "info": 1},
                "category_counts": {"workload_or_system_error": 1},
            },
            "telemetry_stability_warning_summary": {
                "warning_categories": {"gpu_vram_verification_coverage": 1},
                "error_categories": {"worker_exit": 2},
                "backend_confidence_counts": {"worker_verified": 1},
                "worker_verified_no_telemetry_count": 1,
            },
            "artifact_availability": {
                "kind": "run_result",
                "has_parsed_results": True,
                "has_validation_report": False,
                "has_pre_import_sanity": False,
            },
        },
        "Help",
    )
    assert_true("QA Review" in qa_review, "TUI QA review heading")
    assert_true("Review: ready" in qa_review, "TUI QA review status")
    assert_true("Import: fail (blocking=True)" in qa_review, "TUI QA import status")
    assert_true("Escalation reasons: worker_failures" in qa_review, "TUI QA escalation reason")
    assert_true("Operator Next Steps" in qa_review, "TUI QA operator next steps heading")
    assert_true("Do not import yet" in qa_review, "TUI QA import blocker next step")
    assert_true("GPU workers: 8/9 successful, 1 failed" in qa_review, "TUI QA worker evidence")
    assert_true("Worker-verified no telemetry: 1" in qa_review, "TUI QA telemetry evidence")


def test_tui_profile_presentation_helpers() -> None:
    text = profile_summary_presentation(
        environment_mode="Production",
        enhanced_telemetry="enabled",
        profile_summary="Profile summary",
    )
    assert_equal(
        text,
        "Mode: Production\n"
        "Enhanced telemetry: enabled\n\n"
        "Profile summary\n\n"
        "Actions:\n"
        "- Enter opens Run Setup for this profile.\n"
        "- N creates a new profile in the Profile Edit screen.\n"
        "- M opens Profile Edit for persistent profile changes.\n"
        "- D runs Dry Run / Diagnostics.\n"
        "- U starts run confirmation.\n"
        "- A audits all profiles.\n"
        "- E ensures the example PL Validation profile exists.",
        "TUI profile summary presentation",
    )


def test_tui_settings_list_presentation_helpers() -> None:
    department = settings_input_presentation(
        field="department",
        label="Department",
        value="Production",
        summary="Settings summary",
    )
    assert_true(department is not None, "TUI settings department presentation exists")
    assert_equal(department.pending_field, "__settings_department", "TUI settings department pending field")
    assert_equal(department.value, "Production", "TUI settings department value")
    assert_true("Enter Department" in department.placeholder, "TUI settings department placeholder")
    assert_true("Editing: Department" in department.detail, "TUI settings department detail")
    numeric = settings_input_presentation(
        field="trim_start_seconds",
        label="Default trim start seconds",
        value=30,
        summary="Settings summary",
    )
    assert_true(numeric is not None, "TUI settings numeric presentation exists")
    assert_equal(numeric.pending_field, "__settings_numeric:trim_start_seconds", "TUI settings numeric pending field")
    assert_equal(numeric.value, "30", "TUI settings numeric value")
    assert_equal(
        settings_input_presentation(
            field="unsupported",
            label="Unsupported",
            value="x",
            summary="Settings summary",
        ),
        None,
        "TUI settings unsupported input returns none",
    )
    list_view = settings_list_presentation(
        title="Case/SKU",
        values=["A", "B"],
        selected_index=9,
        summary="Summary",
    )
    assert_equal(list_view.title, "Case/SKU", "TUI settings list title")
    assert_equal(list_view.values, ("A", "B"), "TUI settings list values")
    assert_equal(list_view.selected_index, 1, "TUI settings list clamps selected index")
    assert_equal(list_view.detail, "Summary", "TUI settings list summary detail")
    empty = settings_list_presentation(title="Case/SKU", values=[], selected_index=3, summary="Summary")
    assert_equal(empty.selected_index, None, "TUI settings empty list selected index")
    add = settings_list_input_presentation(
        mode="add",
        title="Case/SKU",
        values=["A"],
        selected_index=0,
        summary="Summary",
    )
    assert_true(add is not None, "TUI settings add presentation exists")
    assert_equal(add.pending_field, "__settings_list_add", "TUI settings add pending field")
    assert_equal(add.value, "", "TUI settings add empty value")
    assert_true("Add item to Case/SKU" in add.placeholder, "TUI settings add placeholder")
    assert_true("Adding:" in add.detail, "TUI settings add detail")
    rename = settings_list_input_presentation(
        mode="rename",
        title="Case/SKU",
        values=["A", "B"],
        selected_index=9,
        summary="Summary",
    )
    assert_true(rename is not None, "TUI settings rename presentation exists")
    assert_equal(rename.pending_field, "__settings_list_rename", "TUI settings rename pending field")
    assert_equal(rename.value, "B", "TUI settings rename clamps value")
    assert_equal(rename.selected_index, 1, "TUI settings rename selected index")
    assert_true("Renaming:" in rename.detail, "TUI settings rename detail")
    assert_equal(
        settings_list_input_presentation(
            mode="rename",
            title="Case/SKU",
            values=[],
            selected_index=0,
            summary="Summary",
        ),
        None,
        "TUI settings rename empty list returns none",
    )


def test_tui_post_run_prompt_specs() -> None:
    wall = post_run_wall_wattage_prompt_spec(
        SimpleNamespace(status="Waiting", text="Wall prompt"),
        placeholder="Enter watts",
    )
    assert_equal(wall.pending_field, "__post_wall_wattage", "TUI post-run wall field")
    assert_equal(wall.placeholder, "Enter watts", "TUI post-run wall placeholder")
    assert_equal(wall.status, "Waiting", "TUI post-run wall status")
    assert_equal(wall.detail, "Wall prompt", "TUI post-run wall detail")
    assert_true(wall.enabled, "TUI post-run wall input enabled")
    wall_presentation = post_run_prompt_presentation(wall)
    assert_equal(wall_presentation.pending_field, "__post_wall_wattage", "TUI post-run wall presentation field")
    assert_equal(wall_presentation.placeholder, "Enter watts", "TUI post-run wall presentation placeholder")
    assert_equal(wall_presentation.detail, "Wall prompt", "TUI post-run wall presentation detail")
    assert_equal(wall_presentation.enabled, True, "TUI post-run wall presentation enabled")
    assert_equal(wall_presentation.focus, True, "TUI post-run wall presentation focus")
    assert_equal(wall_presentation.sidebar_options, (), "TUI post-run wall presentation no sidebar")
    upload = post_run_upload_prompt_spec(SimpleNamespace(status="Choose upload", text="Upload prompt"))
    assert_equal(upload.pending_field, "__post_upload_prompt", "TUI post-run upload field")
    assert_equal(upload.view_mode, "post_run_upload_picker", "TUI post-run upload view mode")
    assert_equal(upload.sidebar_title, "Upload?", "TUI post-run upload title")
    assert_equal(upload.sidebar_options, UPLOAD_PROMPT_OPTIONS, "TUI post-run upload options")
    assert_equal(upload.selected_index, 1, "TUI post-run upload default selection")
    assert_equal(upload.enabled, False, "TUI post-run upload input disabled")
    assert_equal(upload.focus, False, "TUI post-run upload input focus")
    upload_presentation = post_run_prompt_presentation(upload)
    assert_equal(
        upload_presentation.sidebar_options,
        UPLOAD_PROMPT_OPTIONS,
        "TUI post-run upload presentation sidebar options",
    )
    assert_equal(upload_presentation.selected_index, 1, "TUI post-run upload presentation selected index")
    assert_equal(upload_presentation.status, "Choose upload", "TUI post-run upload presentation status")
    assert_true(should_prompt_for_post_run_upload(Path("result"), True), "TUI post-run upload prompt enabled")
    assert_equal(
        should_prompt_for_post_run_upload(None, True),
        False,
        "TUI post-run upload prompt requires result dir",
    )
    assert_equal(
        should_prompt_for_post_run_upload(Path("result"), False),
        False,
        "TUI post-run upload prompt respects setting",
    )
    assert_equal(
        post_run_skip_upload_base_text("", "fallback"),
        "fallback",
        "TUI post-run skip fallback text",
    )
    failed_transition = post_run_completion_transition(
        result_available=False,
        completed_text="Failure text",
        prompt_for_wall_wattage=True,
        prompt_for_upload=True,
    )
    assert_equal(failed_transition.action, POST_RUN_ACTION_FAILED, "TUI post-run failed transition action")
    assert_equal(failed_transition.status, "Run failed", "TUI post-run failed transition status")
    assert_equal(failed_transition.detail, "Failure text", "TUI post-run failed transition detail")
    wall_transition = post_run_completion_transition(
        result_available=True,
        completed_text="Complete text",
        prompt_for_wall_wattage=True,
        prompt_for_upload=True,
    )
    assert_equal(wall_transition.action, POST_RUN_ACTION_WALL_WATTAGE, "TUI post-run wall transition precedence")
    upload_transition = post_run_completion_transition(
        result_available=True,
        completed_text="Complete text",
        prompt_for_wall_wattage=False,
        prompt_for_upload=True,
    )
    assert_equal(upload_transition.action, POST_RUN_ACTION_UPLOAD_PROMPT, "TUI post-run upload transition action")
    complete_transition = post_run_completion_transition(
        result_available=True,
        completed_text="Complete text",
        prompt_for_wall_wattage=False,
        prompt_for_upload=False,
    )
    assert_equal(complete_transition.action, POST_RUN_ACTION_COMPLETE, "TUI post-run complete transition action")
    assert_equal(complete_transition.status, "Run complete", "TUI post-run complete transition status")


def test_tui_run_setup_presentation_helpers() -> None:
    actions = [
        FrontendActionSpec("1", "picker", "case_sku", "Case/SKU", "required"),
        FrontendActionSpec("2", "input", "description", "Description", "optional"),
    ]
    sidebar = run_setup_sidebar_presentation(actions=actions, overview="Setup overview", selected_index=9)
    assert_equal(sidebar.title, RUN_SETUP_SIDEBAR_TITLE, "TUI run setup sidebar title")
    assert_equal(
        sidebar.rows,
        (
            "Case/SKU\n1 -- required",
            "Description\n2 -- optional",
        ),
        "TUI run setup sidebar rows",
    )
    assert_equal(sidebar.selected_index, 1, "TUI run setup sidebar clamps selected index")
    assert_true("Setup overview" in sidebar.detail, "TUI run setup sidebar overview detail")
    assert_true("Recall previous setup" in sidebar.detail, "TUI run setup sidebar exposes setup history recall")
    empty = run_setup_sidebar_presentation(actions=[], overview="Setup overview")
    assert_equal(empty.selected_index, None, "TUI run setup empty sidebar selected index")
    assert_equal(
        run_setup_detail_presentation("Overview", "Action detail"),
        "Overview\n\nRecall previous setup: press H or select Load previous setup from the left list.\n\nAction detail",
        "TUI run setup action detail presentation",
    )
    assert_equal(
        run_setup_detail_presentation("Overview", ""),
        "Overview\n\nRecall previous setup: press H or select Load previous setup from the left list.",
        "TUI run setup detail omits empty action detail",
    )
    input_presentation = run_setup_input_presentation(
        field="stage_duration",
        spec=SimpleNamespace(label="Stage duration seconds", initial_value="600", blank_default="300"),
        setup_summary="Setup summary",
    )
    assert_equal(input_presentation.pending_field, "stage_duration", "TUI run setup input pending field")
    assert_equal(input_presentation.value, "600", "TUI run setup input value")
    assert_equal(input_presentation.blank_default, "300", "TUI run setup input blank default")
    assert_equal(
        input_presentation.placeholder,
        "Enter Stage duration seconds and press Enter, or Esc to cancel",
        "TUI run setup input placeholder",
    )
    assert_true("Setup summary" in input_presentation.detail, "TUI run setup input summary detail")
    assert_true("Editing: Stage duration seconds" in input_presentation.detail, "TUI run setup input label detail")
    history_entries = [
        SimpleNamespace(
            case_sku="CASE-1",
            description="Rack system",
            profile_name="PL Validation",
            profile_file="PL Validation.json",
            psu_wattage="1200W",
            saved="2026-06-30",
        ),
        SimpleNamespace(
            case_sku="CASE-2",
            description="Bench system",
            profile_name="GPU Troubleshooting",
            profile_file="GPU Troubleshooting.json",
            psu_wattage="1000W",
            saved="2026-06-29",
        ),
    ]
    history = run_setup_history_presentation(
        entries=history_entries,
        setup_summary="Setup summary",
        selected_index=5,
    )
    assert_equal(history.title, RUN_SETUP_HISTORY_SIDEBAR_TITLE, "TUI run setup history title")
    assert_equal(history.selected_index, 1, "TUI run setup history clamps selected index")
    assert_equal(
        history.rows[0],
        "CASE-1 | Rack system\n  PL Validation | 1200W | 2026-06-30",
        "TUI run setup history row",
    )
    assert_true("Load Previous Run Setup" in history.detail, "TUI run setup history detail title")
    assert_true("Wall wattage is not recalled" in history.detail, "TUI run setup history wattage note")
    history_prompt = run_setup_history_prompt_presentation(
        setup_summary="Setup summary",
        entry_count=2,
    )
    assert_equal(history_prompt.title, "Recall Setup?", "TUI run setup history prompt title")
    assert_equal(history_prompt.rows, ("Recall previous setup", "Skip recall"), "TUI run setup history prompt actions")
    assert_true("2 previous run setups available" in history_prompt.detail, "TUI run setup history prompt count")
    assert_true("mirrors the CLI recall prompt" in history_prompt.detail, "TUI run setup history prompt CLI parity note")
    confirm_history = run_setup_history_confirm_presentation(
        entry=history_entries[0],
        setup_summary="Setup summary",
    )
    assert_equal(confirm_history.title, "Recall Setup?", "TUI run setup history confirm title")
    assert_equal(confirm_history.rows, ("Apply selected setup", "Cancel"), "TUI run setup history confirm actions")
    assert_true("CASE-1 | Rack system" in confirm_history.detail, "TUI run setup history confirm selected entry")
    assert_true("Choose Apply selected setup" in confirm_history.detail, "TUI run setup history confirm guidance")
    assert_equal(
        run_setup_history_presentation(entries=[], setup_summary="Setup summary").selected_index,
        None,
        "TUI run setup empty history selected index",
    )
    assert_equal(
        run_setup_no_history_detail("Setup summary"),
        "Setup summary\n\nNo previous run setup history is available yet.",
        "TUI run setup no history detail",
    )
    assert_equal(
        run_setup_history_loaded_detail("Setup summary"),
        "Setup summary\n\nPrevious run setup loaded. Wall wattage will still be collected after this run.",
        "TUI run setup history loaded detail",
    )
    duration_transition = run_setup_stage_input_transition(
        field="stage_duration",
        value="600",
        pending_trim_start=None,
        default_trim_start=30,
        default_trim_end=45,
    )
    assert_equal(duration_transition.action, RUN_SETUP_STAGE_INPUT_COMPLETE, "TUI run setup duration transition")
    label_transition = run_setup_stage_input_transition(
        field="segment_label",
        value="GPU",
        pending_trim_start=None,
        default_trim_start=30,
        default_trim_end=45,
    )
    assert_equal(label_transition.action, RUN_SETUP_STAGE_INPUT_COMPLETE, "TUI run setup label transition")
    trim_start = run_setup_stage_input_transition(
        field="trim_start",
        value="12.9",
        pending_trim_start=None,
        default_trim_start=30,
        default_trim_end=45,
    )
    assert_equal(trim_start.action, RUN_SETUP_STAGE_INPUT_TRIM_END, "TUI run setup trim start transition")
    assert_equal(trim_start.start, 12, "TUI run setup trim start parsed")
    assert_equal(trim_start.next_field, "trim_end", "TUI run setup trim start next field")
    assert_equal(trim_start.next_value, "45", "TUI run setup trim end initial value")
    invalid_trim_start = run_setup_stage_input_transition(
        field="trim_start",
        value="bad",
        pending_trim_start=None,
        default_trim_start=30,
        default_trim_end=45,
    )
    assert_equal(invalid_trim_start.start, 30, "TUI run setup invalid trim start fallback")
    trim_end = run_setup_stage_input_transition(
        field="trim_end",
        value="20",
        pending_trim_start=12,
        default_trim_start=30,
        default_trim_end=45,
    )
    assert_equal(trim_end.action, RUN_SETUP_STAGE_INPUT_COMPLETE_TRIM, "TUI run setup trim end transition")
    assert_equal(trim_end.start, 12, "TUI run setup trim end pending start")
    assert_equal(trim_end.end, 20, "TUI run setup trim end parsed")
    invalid_trim_end = run_setup_stage_input_transition(
        field="trim_end",
        value="bad",
        pending_trim_start=None,
        default_trim_start=30,
        default_trim_end=45,
    )
    assert_equal(invalid_trim_end.start, 30, "TUI run setup trim end default start fallback")
    assert_equal(invalid_trim_end.end, 45, "TUI run setup invalid trim end fallback")
    noop = run_setup_stage_input_transition(
        field="unknown",
        value="",
        pending_trim_start=None,
        default_trim_start=30,
        default_trim_end=45,
    )
    assert_equal(noop.action, RUN_SETUP_STAGE_INPUT_NOOP, "TUI run setup unknown transition")
    blocked_prepared = SimpleNamespace(
        readiness=SimpleNamespace(validation={"errors": ["profile blocked"], "warnings": ["profile warning"]}),
        preflight_decision=SimpleNamespace(
            runnable=False,
            report={"runnable_stage_count": 1, "enabled_stage_count": 2},
        ),
        preflight_action=SimpleNamespace(
            errors=["backend unavailable"],
            warnings=["stage skipped"],
            blocked=True,
            skipped_stage_count=1,
            skip_notice="Proceeding with 1 runnable stage(s); 1 stage(s) will be skipped for this run.",
            report_dir=Path("/tmp/preflight"),
        ),
    )
    blocked_readiness = prepared_run_readiness_text(blocked_prepared)
    assert_true("Status: blocked" in blocked_readiness, "TUI run setup readiness blocked status")
    assert_true("Profile validation: 1 error(s)" in blocked_readiness, "TUI run setup readiness profile errors")
    assert_true("Preflight: not runnable, runnable stages 1/2" in blocked_readiness, "TUI run setup readiness preflight")
    assert_true("Run blocked: fix the preflight/profile issues" in blocked_readiness, "TUI run setup readiness blocked instruction")


def test_tui_run_setup_adapter_helpers() -> None:
    class FakeTui(TuiRunSetupAdapterMixin):
        def __init__(self) -> None:
            class TitleWidget:
                def __init__(widget_self) -> None:
                    widget_self.value = ""

                def update(widget_self, value) -> None:
                    widget_self.value = value

            self.title_widget = TitleWidget()
            self.list_widget = SimpleNamespace(value="")
            self.detail = ""
            self.rows = []
            self.selected_index = None
            self.focus = False
            self.setup_sidebar_shown = False
            self.restored = False
            self.view_mode = "setup"
            self.run_setup = SimpleNamespace()
            self.history_entries = []
            self.pending_history_entry = None
            self.applied_entry = None

            class Service:
                def __init__(service_self, owner) -> None:
                    service_self.owner = owner
                    service_self.entries = []

                def run_setup_history_entries(service_self):
                    return service_self.entries

                def run_setup_summary_text(service_self, _setup):
                    return "Setup summary"

                def apply_run_setup_history_entry(service_self, _setup, entry):
                    service_self.owner.applied_entry = entry

            self.service = Service(self)

        def query_one(self, selector):
            if selector == "#sidebar-title":
                return self.title_widget
            if selector == "#items":
                return self.list_widget
            raise AssertionError(f"unexpected selector {selector}")

        async def _replace_sidebar_labels(self, _list_view, rows, selected_index=None, focus=False):
            self.rows = list(rows)
            self.selected_index = selected_index
            self.focus = focus

        def _set_detail(self, detail):
            self.detail = detail

        async def _show_run_setup_sidebar(self):
            self.setup_sidebar_shown = True

        async def _restore_setup_sidebar(self):
            self.restored = True

    fake = FakeTui()
    assert_equal(fake._normalize_power_watts("280W"), "280", "TUI power watts suffix normalization")
    assert_equal(fake._normalize_power_watts(" 280 "), "280", "TUI power watts whitespace normalization")
    intel = power_limit_vendor_transition("Intel")
    assert_equal(intel.action, "input", "TUI power limit Intel starts input flow")
    assert_equal(intel.next_field, "power_limit_intel_pl1", "TUI power limit Intel PL1 field")
    intel_turbo = power_limit_input_transition("power_limit_intel_turbo", "56", {"pl1": "30", "pl2": "40"})
    assert_equal(intel_turbo.metadata_value, "PL1:30|PL2:40|Turbo:56", "TUI Intel power limit metadata")
    amd_picker = power_limit_input_transition("power_limit_amd_power", "280W", {})
    assert_equal(amd_picker.action, "picker", "TUI AMD power limit opens type picker")
    assert_equal(amd_picker.parts_update.get("amd_power"), "280", "TUI AMD power limit normalizes watts")
    amd_type = power_limit_amd_type_transition("PPT", {"amd_power": "280"})
    assert_equal(amd_type.metadata_value, "(MB) 280W-PPT", "TUI AMD power limit metadata")

    history_entry = SimpleNamespace(
        case_sku="CASE-1",
        description="Rack system",
        profile_name="PL Validation",
        profile_file="PL Validation.json",
        psu_wattage="1200W",
        saved="2026-06-30",
    )

    async def run_setup_history_adapter_check() -> None:
        recall_tui = FakeTui()
        recall_tui.service.entries = [history_entry]
        recall_tui.history_entries = [history_entry]
        await recall_tui._select_setup_history_prompt(0)
        assert_equal(recall_tui.view_mode, "setup_history", "TUI setup recall prompt opens history list")
        assert_equal(recall_tui.title_widget.value, RUN_SETUP_HISTORY_SIDEBAR_TITLE, "TUI setup history title")
        assert_true("CASE-1 | Rack system" in recall_tui.rows[0], "TUI setup history row rendered")
        assert_true("Load Previous Run Setup" in recall_tui.detail, "TUI setup history detail rendered")

        await recall_tui._select_setup_history_entry(history_entry)
        assert_equal(recall_tui.view_mode, "setup_history_confirm", "TUI setup history opens confirm")
        assert_equal(recall_tui.rows, ["Apply selected setup", "Cancel"], "TUI setup history confirm rows")
        assert_true("Choose Apply selected setup" in recall_tui.detail, "TUI setup history confirm guidance")

        await recall_tui._select_setup_history_confirm(0)
        assert_equal(recall_tui.applied_entry, history_entry, "TUI setup history applies selected entry")
        assert_true(recall_tui.restored, "TUI setup history restores setup sidebar after apply")
        assert_true("Previous run setup loaded" in recall_tui.detail, "TUI setup history loaded detail")

        skip_tui = FakeTui()
        await skip_tui._select_setup_history_prompt(1)
        assert_true(skip_tui.setup_sidebar_shown, "TUI setup recall skip returns to setup sidebar")

        empty_tui = FakeTui()
        await empty_tui._show_setup_history_entries()
        assert_true(empty_tui.setup_sidebar_shown, "TUI empty setup history returns to setup sidebar")
        assert_true("No previous run setup history" in empty_tui.detail, "TUI empty setup history detail")

    asyncio.run(run_setup_history_adapter_check())


def test_tui_profile_edit_adapter_helpers() -> None:
    class FakeTui(TuiProfileEditAdapterMixin):
        pass

    fake = FakeTui()
    fake.profile_edit = SimpleNamespace()
    fake.profile_edit_selected_index = 1
    fake.profile_edit_items = [
        SimpleNamespace(kind="name", index=None),
        SimpleNamespace(kind="stage", index=3),
    ]
    assert_equal(fake._selected_profile_edit_stage_index(), 3, "TUI profile edit selected stage index")
    fake.profile_edit_selected_index = 0
    assert_equal(fake._selected_profile_edit_stage_index(), None, "TUI profile edit ignores non-stage rows")
    assert_equal(
        selected_profile_edit_stage_index(fake.profile_edit_items, 1, edit_present=True),
        3,
        "TUI profile edit flow selected stage index",
    )
    assert_equal(
        selected_profile_edit_stage_index(fake.profile_edit_items, 1, edit_present=False),
        None,
        "TUI profile edit flow requires active edit state",
    )
    assert_equal(
        selected_profile_edit_stage_index(fake.profile_edit_items, 99, edit_present=True),
        None,
        "TUI profile edit flow ignores out-of-range selection",
    )
    assert_equal(
        normalized_profile_edit_input_value("  value  "),
        "value",
        "TUI profile edit input normalization",
    )
    assert_equal(
        profile_edit_trim_start_value("__profile_stage_trim_start", " 3.7 ", pending_stage_index=0),
        3,
        "TUI profile edit trim start parsing",
    )
    assert_equal(
        profile_edit_trim_start_value("__profile_stage_trim_start", "-12", pending_stage_index=0),
        0,
        "TUI profile edit trim start clamps negative values",
    )
    assert_equal(
        profile_edit_trim_start_value("duration", "30", pending_stage_index=0),
        None,
        "TUI profile edit trim start ignores non-trim fields",
    )


def test_tui_results_adapter_helpers() -> None:
    class FakeService:
        def __init__(self) -> None:
            self.qa_paths = []
            self.comparison_calls = []

        def qa_result_review_payload(self, path, refresh_summary=True):
            self.qa_paths.append((path, refresh_summary))
            return {
                "identity": {"folder_name": "QA Result", "result": "Failed", "outcome_class": "worker_failure"},
                "decisions": {
                    "review": {"status": "ready"},
                    "import": {"status": "fail", "blocking": True},
                    "compare": {"status": "ready_no_baseline_selected"},
                    "escalate": {"needed": True, "reasons": ["worker_failures"]},
                },
                "validation_status": {"result": "fail", "errors": 1, "warnings": 0, "issue_category_counts": {}},
                "worker_failure_evidence": {
                    "worker_result_count": 2,
                    "successful_worker_result_count": 1,
                    "worker_failure_count": 1,
                    "verification_passes": 5,
                },
                "action_item_summary": {"total": 1, "severity_counts": {"error": 1}, "category_counts": {}},
                "telemetry_stability_warning_summary": {},
                "artifact_availability": {"kind": "run_result", "has_parsed_results": True},
            }

        def result_action_help_text(self):
            return "Help"

        def compare_result_payload(self, baseline_path, comparison_path):
            self.comparison_calls.append((baseline_path, comparison_path))
            return {
                "baseline_folder": str(baseline_path),
                "comparison_folder": str(comparison_path),
            }

        def result_comparison_text(self, payload):
            return f"Compared {payload['baseline_folder']} -> {payload['comparison_folder']}"

        def result_artifact_detail_text(self, path):
            return f"Artifact detail for {path}"

        def result_artifact_inventory_item(self, path):
            return {
                "folder": str(path),
                "kind": "run_result",
                "result": "warning",
                "artifacts": [
                    "parsed_results_custom.json",
                    "run_summary.txt",
                    "raw_telemetry.csv",
                    "telemetry_source_map.json",
                    "result_validation.json",
                    "result_comparison_vs_baseline.txt",
                ],
            }

        def validate_result_text(self, path, save=True):
            return f"Validation for {path} save={save}"

        def validate_all_results_text(self, save=True):
            return f"Batch validation save={save}"

        def pre_import_sanity_text(self, path, save=True):
            return f"Pre-import for {path} save={save}"

        def pre_import_sanity_all_text(self, save=True):
            return f"Batch pre-import save={save}"

    class FakeTui(TuiResultsAdapterMixin):
        def __init__(self) -> None:
            self.selected_result = None
            self.comparison_target_result = None
            self.detail = ""
            self.service = FakeService()

        def _set_detail(self, text: str) -> None:
            self.detail = text

    fake = FakeTui()
    fake._show_result_stage_details()
    assert_true("Select a result folder first." in fake.detail, "TUI result adapter handles missing selection")
    assert_true("Use the result list" in fake.detail, "TUI result adapter explains missing selection recovery")
    fake._show_result_qa_review()
    assert_true("Select a result folder first." in fake.detail, "TUI result adapter handles missing QA selection")
    fake._show_result_artifact_details()
    assert_true("Select a result folder first." in fake.detail, "TUI result adapter handles missing artifact selection")
    fake.selected_result = SimpleNamespace(path=Path("/tmp/qa_result"))
    fake._show_result_qa_review()
    assert_equal(fake.service.qa_paths, [(Path("/tmp/qa_result"), False)], "TUI result adapter calls QA service")
    assert_true("QA Review" in fake.detail, "TUI result adapter QA review heading")
    assert_true("Escalation reasons: worker_failures" in fake.detail, "TUI result adapter QA escalation")
    assert_true("Operator Next Steps" in fake.detail, "TUI result adapter QA operator next steps")
    fake._show_result_artifact_details()
    assert_true(
        "Artifact detail for /tmp/qa_result" in fake.detail,
        "TUI result adapter renders artifact detail service text",
    )
    assert_true("Selected Result Artifacts" in fake.detail, "TUI artifact browser heading")
    assert_true("Core result:" in fake.detail, "TUI artifact browser core category")
    assert_true(
        "parsed_results_custom.json -> /tmp/qa_result/parsed_results_custom.json" in fake.detail,
        "TUI artifact browser parsed result path",
    )
    assert_true("Telemetry / source evidence:" in fake.detail, "TUI artifact browser telemetry category")
    assert_true(
        "telemetry_source_map.json -> /tmp/qa_result/telemetry_source_map.json" in fake.detail,
        "TUI artifact browser source map path",
    )
    assert_true("Comparisons:" in fake.detail, "TUI artifact browser comparison category")
    assert_true("Help" in fake.detail, "TUI result adapter includes result action help with artifact detail")
    assert_true("Use E to return to QA review" in fake.detail, "TUI artifact detail includes next step guidance")
    target = SimpleNamespace(name="Target", path=Path("/tmp/target"))
    baseline = SimpleNamespace(name="Baseline", path=Path("/tmp/baseline"))
    fake.selected_result = None
    fake._begin_result_comparison()
    assert_true("Select a result folder first." in fake.detail, "TUI result adapter handles missing comparison target")
    fake.selected_result = target
    fake._begin_result_comparison()
    assert_true("Comparison result: Target" in fake.detail, "TUI result adapter starts comparison flow")
    assert_true(fake.comparison_target_result is target, "TUI result adapter stores comparison target")
    fake._show_result_comparison_candidate(baseline)
    assert_true("Baseline candidate: Baseline" in fake.detail, "TUI result adapter previews baseline candidate")
    fake._complete_result_comparison(baseline)
    assert_equal(
        fake.service.comparison_calls,
        [(Path("/tmp/baseline"), Path("/tmp/target"))],
        "TUI result adapter calls comparison service with baseline then comparison",
    )
    assert_true("Compared /tmp/baseline -> /tmp/target" in fake.detail, "TUI result adapter renders comparison text")
    assert_true("Use E to review" in fake.detail, "TUI result adapter comparison includes next step guidance")
    assert_true("Help" in fake.detail, "TUI result adapter comparison includes action help")
    assert_true(fake.comparison_target_result is None, "TUI result adapter clears comparison target")
    assert_true(fake.selected_result is target, "TUI result adapter restores selected comparison result")
    fake._validate_selected_result()
    assert_true("Validation for /tmp/target save=True" in fake.detail, "TUI result adapter renders validation text")
    assert_true("Use E to refresh QA review" in fake.detail, "TUI validation includes next step guidance")
    fake._validate_all_results()
    assert_true("Batch validation save=True" in fake.detail, "TUI result adapter renders batch validation text")
    assert_true("Select a result folder" in fake.detail, "TUI batch validation includes next step guidance")
    fake._pre_import_selected_result()
    assert_true("Pre-import for /tmp/target save=True" in fake.detail, "TUI result adapter renders pre-import text")
    assert_true("Use E to return to QA review" in fake.detail, "TUI pre-import includes next step guidance")
    fake._pre_import_all_results()
    assert_true("Batch pre-import save=True" in fake.detail, "TUI result adapter renders batch pre-import text")
    assert_true("selected pre-import detail" in fake.detail, "TUI batch pre-import includes next step guidance")


def test_cli_result_qa_review_action() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        result_dir = root / "2026-07-13_12-00-00_QA_Result"
        result_dir.mkdir()
        JsonStore.write(
            result_dir / "parsed_results_custom.json",
            {
                "Result": "Finished",
                "Metadata": {"ProfileName": "QA Smoke"},
                "ReportSummary": {
                    "ProfileName": "QA Smoke",
                    "Result": "Finished",
                    "OutcomeClass": "verified_clean",
                    "StageCount": 1,
                    "ActionItems": 0,
                    "GpuWorkerSummary": {
                        "WorkerResultCount": 1,
                        "SuccessfulWorkerResultCount": 1,
                        "WorkerFailureCount": 0,
                    },
                },
            },
        )

        class FakeLauncher:
            def __init__(self) -> None:
                self.result_validation = ResultValidationFacade(root)
                self.result_comparison = ResultComparisonFacade()
                self.summary_exporter = RunSummaryTextExporter()
                self.pre_import_sanity = PreImportSanityFacade(root, self.result_validation, self.summary_exporter)
                self.result_artifacts = ResultArtifactFacade(root)
                self.inputs = ["1"]

            def _input(self, _prompt: str) -> str:
                return self.inputs.pop(0)

        adapter = ResultCliAdapter(FakeLauncher())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            adapter.result_qa_review()
        text = output.getvalue()
        assert_true("Available result folders" in text, "CLI QA review shows result choices")
        assert_true("QA Review" in text, "CLI QA review renders readable review output")
        assert_true("Review:" in text, "CLI QA review renders review status")
        assert_true("Import:" in text, "CLI QA review renders import status")
        assert_true(
            "CLI Results actions: run Validation, Pre-Import Sanity, Comparison, or Artifact Detail from this menu."
            in text,
            "CLI QA review includes operator next-step guidance",
        )
        assert_true(
            "From the Results / Reports menu, use Validate Result Folder" in text,
            "CLI QA review uses menu-name followup guidance",
        )
        assert_true(
            "Use F for artifacts" not in text,
            "CLI QA review does not leak TUI hotkey guidance",
        )

        class EmptyLauncher(FakeLauncher):
            def __init__(self) -> None:
                super().__init__()
                self.result_validation = ResultValidationFacade(root / "missing")
                self.result_artifacts = ResultArtifactFacade(root / "missing")
                self.pre_import_sanity = PreImportSanityFacade(
                    root / "missing",
                    self.result_validation,
                    self.summary_exporter,
                )

        empty_output = io.StringIO()
        with contextlib.redirect_stdout(empty_output):
            ResultCliAdapter(EmptyLauncher()).result_qa_review()
        assert_true(
            "No result folders with parsed_results_custom.json were found." in empty_output.getvalue(),
            "CLI QA review handles missing results clearly",
        )


def test_tui_settings_adapter_helpers() -> None:
    class FakeTui(TuiSettingsAdapterMixin):
        pass

    async def run_check() -> None:
        handled = await FakeTui()._commit_settings_input("__not_settings", "value")
        assert_equal(handled, False, "TUI settings adapter ignores unrelated input")

    asyncio.run(run_check())


def test_tui_run_execution_adapter_helpers() -> None:
    class FakeTui(TuiRunExecutionAdapterMixin):
        pass

    class FakeUploadService:
        def upload_result_outcome(self, payload: dict) -> SimpleNamespace:
            return SimpleNamespace(status=f"Google Drive upload {payload.get('result')}", text="Upload summary")

    fake = FakeTui()
    assert_equal(fake._tail_text("abcdef", 10), "abcdef", "TUI run execution keeps short output")
    assert_equal(
        fake._tail_text("abcdef", 3),
        "... output truncated ...\ndef",
        "TUI run execution truncates long output",
    )
    fake.run_in_progress = False
    fake.pending_input_field = None
    assert_equal(fake._interaction_locked(), False, "TUI run execution unlocked when idle")
    fake.pending_input_field = "field"
    assert_equal(fake._interaction_locked(), True, "TUI run execution locks during input")
    fake.pending_input_field = None
    fake.upload_in_progress = True
    assert_equal(fake._interaction_locked(), True, "TUI run execution locks during upload")
    fake.upload_in_progress = False
    not_ready = upload_not_ready_detail(Path("result"), {"missing": ["credentials"], "credential_path": "/tmp/creds.json"})
    assert_true("Missing: credentials" in not_ready, "TUI upload readiness missing detail")
    assert_true("Uploading: result" in upload_active_detail(Path("result")), "TUI upload active detail")
    workflow = upload_workflow_detail(
        title="Google Drive Upload Prompt",
        result_dir=Path("result"),
        status="waiting",
        body="Choose upload or skip.",
    )
    assert_true("Google Drive Upload Prompt" in workflow, "TUI upload workflow right-pane title")
    assert_true("Result folder: result" in workflow, "TUI upload workflow result folder")
    assert_true("Status: waiting" in workflow, "TUI upload workflow status")
    assert_true("Operator Next Steps" in workflow, "TUI upload workflow next steps")
    status, detail, _outcome = upload_finish_result({"result": "success"}, "fallback", FakeUploadService())
    assert_equal(status, "Google Drive upload success", "TUI upload finish status")
    assert_equal(detail, "Upload summary", "TUI upload finish detail")
    assert_equal(uploaded_result_dir({"moved_to": "/tmp/uploaded"}), Path("/tmp/uploaded"), "TUI upload moved dir")

    class FakePostRunArtifactService:
        def result_artifact_inventory_item(self, result_dir):
            return {
                "kind": "run_result",
                "result": "pass",
                "artifacts": ["parsed_results_custom.json", "run_summary.txt"],
            }

    class FakePostRunTui(TuiRunExecutionAdapterMixin):
        def __init__(self) -> None:
            self.service = FakePostRunArtifactService()

    post_run_tui = FakePostRunTui()
    post_run_text = post_run_tui._post_run_operator_text(Path("/tmp/result"), "Run Complete", upload_status="success")
    assert_true("Latest result folder: /tmp/result" in post_run_text, "TUI post-run adapter result context")
    assert_true("Upload status: success" in post_run_text, "TUI post-run adapter upload status")
    assert_true("Parsed results: available" in post_run_text, "TUI post-run adapter artifact availability")

    class FakeRunService:
        def __init__(self) -> None:
            self.settings = SimpleNamespace()

        def create_run_setup(self, profile_path):
            return SimpleNamespace(profile_path=profile_path, heatsoak_minutes=0.0)

        def setup_action_specs(self, setup):
            return [FrontendActionSpec("u", "run_selected", label="Review and run")]

        def run_setup_summary_text(self, setup):
            return "Setup summary"

    class FakeRunTui(TuiRunExecutionAdapterMixin):
        def __init__(self, blocked: bool, confirm: bool = False) -> None:
            self.view_mode = "setup"
            self.selected_profile = SimpleNamespace(name="Blocked Profile", path=Path("/tmp/profile.json"))
            self.run_in_progress = False
            self.confirm_run = confirm
            self.run_setup = SimpleNamespace(profile_path=Path("/tmp/profile.json"), heatsoak_minutes=0.0)
            self.service = FakeRunService()
            self.detail = ""
            self.prepare_calls = []
            self.handled_actions = []
            self.blocked = blocked

        def _set_detail(self, text: str) -> None:
            self.detail = text

        def _set_status(self, text: str) -> None:
            self.status = text

        def _handle_sync_run_setup_action(self, action) -> None:
            self.handled_actions.append(action.action)

        def _prepare_run_confirmation_flow(self, *, save_blocked_report: bool = False):
            self.prepare_calls.append(save_blocked_report)
            return SimpleNamespace(preflight_action=SimpleNamespace(blocked=self.blocked))

        def _prepared_run_readiness_text(self, prepared_flow) -> str:
            return "Status: blocked" if self.blocked else "Status: ready"

    blocked_tui = FakeRunTui(blocked=True)
    blocked_tui.action_run_selected()
    assert_equal(blocked_tui.confirm_run, False, "TUI run confirmation does not arm blocked run")
    assert_equal(blocked_tui.run_in_progress, False, "TUI blocked run confirmation does not start run")
    assert_equal(blocked_tui.prepare_calls, [False], "TUI blocked run confirmation previews preflight")
    assert_true("Run is blocked" in blocked_tui.detail, "TUI blocked run confirmation detail")
    runnable_tui = FakeRunTui(blocked=False)
    runnable_tui.action_run_selected()
    assert_equal(runnable_tui.confirm_run, True, "TUI runnable run confirmation arms second press")
    assert_true("Press Run again" in runnable_tui.detail, "TUI runnable run confirmation instruction")
    second_press_blocked_tui = FakeRunTui(blocked=True, confirm=True)
    second_press_blocked_tui.action_run_selected()
    assert_equal(second_press_blocked_tui.confirm_run, False, "TUI second press clears blocked confirmation")
    assert_equal(second_press_blocked_tui.run_in_progress, False, "TUI second press blocked preflight does not start run")
    assert_equal(second_press_blocked_tui.prepare_calls, [True], "TUI second press saves blocked preflight report")

    class CancelRunTui(TuiRunExecutionAdapterMixin):
        def __init__(self) -> None:
            self.run_in_progress = True
            self.run_cancel_requested = False
            self.run_cancel_event = threading.Event()
            self.run_live_profile_name = "PL Validation"
            self.run_live_phase_line = "[phase] stage-start"
            self.run_live_lines = []
            self.run_status_tracker = RunStatusTracker()
            self.status = ""
            self.detail = ""

        def _set_status(self, text: str) -> None:
            self.status = text

        def _set_detail(self, text: str) -> None:
            self.detail = text

    cancel_tui = CancelRunTui()
    cancel_tui._request_run_cancel()
    assert_true(cancel_tui.run_cancel_requested, "TUI run cancel records requested state")
    assert_true(cancel_tui.run_cancel_event.is_set(), "TUI run cancel sets backend cancellation event")
    assert_true("Run cancel requested" in cancel_tui.status, "TUI run cancel status")
    assert_true("Cancel requested: stopping active workers" in cancel_tui.detail, "TUI run cancel right-pane detail")
    cancel_tui._append_run_output_line(
        "2026-06-30T12:05:31-04:00 | stage=Power | elapsed=00:02:00 | remaining=00:03:00 | "
        "gpu_target=gpu0:busy=99.0%,pwr=110.0W,temp=68.0C,clk=2600.0MHz"
    )
    assert_equal(cancel_tui.run_status_tracker.snapshot.elapsed, "00:02:00", "TUI stdout progress updates tracker elapsed")
    assert_equal(cancel_tui.run_status_tracker.snapshot.remaining, "00:03:00", "TUI stdout progress updates tracker remaining")
    assert_equal(cancel_tui.run_live_lines, [], "TUI stdout progress does not append to visible output tail")
    assert_true("elapsed=00:02:00" in cancel_tui.detail, "TUI stdout progress refreshes right-pane elapsed")

    class FinishRunTui(TuiRunExecutionAdapterMixin):
        def __init__(self) -> None:
            self.run_in_progress = True
            self.run_cancel_requested = True
            self.run_cancel_event = threading.Event()
            self.run_cancel_event.set()
            self.confirm_run = True
            self.last_run_dir = None
            self.last_run_metadata = None
            self.run_setup = SimpleNamespace(profile_path=Path("profiles/TuiSetupSmoke.json"))
            self.status = ""
            self.detail = ""
            self.restored = False
            self.saved_setup = None
            self.service = SimpleNamespace(
                settings=SimpleNamespace(prompt_for_wall_wattage=False, google_drive_prompt_after_run=False),
                save_run_setup_history=lambda setup: setattr(self, "saved_setup", setup),
            )

        async def _restore_profiles_sidebar_after_post_run(self) -> None:
            self.restored = True
            self.view_mode = "profiles"

        def _set_status(self, text: str) -> None:
            self.status = text

        def _set_detail(self, text: str) -> None:
            self.detail = text

        def _post_run_operator_text(self, result_dir, text: str, *, upload_status: str = "") -> str:
            return f"post-run: {text}"

    async def run_finish_unlock_check() -> None:
        finish_tui = FinishRunTui()
        result = SimpleNamespace(run_dir=Path("/tmp/result"), metadata=SimpleNamespace())
        finish_tui._finish_run_from_thread("Run cancelled", result)
        await asyncio.sleep(0)
        assert_equal(finish_tui.run_in_progress, False, "TUI finish clears run-in-progress")
        assert_equal(finish_tui.run_cancel_requested, False, "TUI finish clears cancel requested")
        assert_true(not finish_tui.run_cancel_event.is_set(), "TUI finish clears cancel event")
        assert_true(finish_tui.restored, "TUI finish restores normal sidebar after run completion")
        assert_equal(finish_tui.view_mode, "profiles", "TUI finish exits run-active view")
        assert_equal(finish_tui.status, "Run complete", "TUI finish keeps post-run status")
        assert_true("post-run: Run cancelled" in finish_tui.detail, "TUI finish keeps post-run detail")
        assert_equal(finish_tui.saved_setup, finish_tui.run_setup, "TUI finish saves run setup history through shared service")

    asyncio.run(run_finish_unlock_check())


def test_tui_app_actions_adapter_helpers() -> None:
    class FakeService:
        def environment_mode_label(self) -> str:
            return "Production"

        def enhanced_telemetry_label(self) -> str:
            return "disabled"

        def profile_summary_text(self, path) -> str:
            return f"Summary for {path}"

    class FakeTui(TuiAppActionsAdapterMixin):
        def __init__(self) -> None:
            self.service = FakeService()
            self.detail = ""

        def _set_detail(self, text: str) -> None:
            self.detail = text

    fake = FakeTui()
    fake._show_profile_summary(SimpleNamespace(path="profile.json"))
    assert_true("Mode: Production" in fake.detail, "TUI app actions profile summary environment")
    assert_true("Summary for profile.json" in fake.detail, "TUI app actions profile summary text")
    profiles = [SimpleNamespace(name="PL Validation"), SimpleNamespace(name="GPU Troubleshooting")]
    profile_state = profiles_sidebar_state(
        profiles,
        environment_label="Production",
        row_label=lambda item: item.name,
    )
    assert_equal(profile_state.title, "Profiles | Production", "TUI app actions profile sidebar title")
    assert_equal(profile_state.rows, ("PL Validation", "GPU Troubleshooting"), "TUI app actions profile sidebar rows")
    assert_equal(profile_state.selected_index, 0, "TUI app actions profile sidebar selected index")
    assert_equal(profile_state.first_item, profiles[0], "TUI app actions profile sidebar first item")
    empty_profiles = profiles_sidebar_state([], environment_label="Production", row_label=lambda item: item.name)
    assert_equal(empty_profiles.selected_index, None, "TUI app actions empty profile sidebar has no selection")
    assert_equal(empty_profiles.empty_detail, "No profiles found.", "TUI app actions empty profile detail")
    results = [SimpleNamespace(name="Result 1")]
    result_state = results_sidebar_state(results, row_label=lambda item: item.name)
    assert_equal(result_state.title, "Results", "TUI app actions result sidebar title")
    assert_equal(result_state.rows, ("Result 1",), "TUI app actions result sidebar rows")
    assert_equal(result_state.first_item, results[0], "TUI app actions result sidebar first item")
    latest_results = [
        SimpleNamespace(name="Old", path=Path("/tmp/old")),
        SimpleNamespace(name="Latest", path=Path("/tmp/latest")),
    ]
    latest_state = results_sidebar_state(
        latest_results,
        row_label=lambda item: item.name,
        selected_path=Path("/tmp/latest"),
    )
    assert_equal(latest_state.selected_index, 1, "TUI result sidebar selects latest result path")
    assert_equal(latest_state.first_item, latest_results[1], "TUI result sidebar latest result item")
    settings_state = settings_sidebar_state()
    assert_equal(settings_state.rows, ("Settings summary",), "TUI app actions settings sidebar row")
    migration_state = migration_support_sidebar_state()
    assert_equal(migration_state.title, "Migration / Support", "TUI migration sidebar title")
    assert_equal(len(migration_state.rows), 4, "TUI migration sidebar action count")
    assert_true(("results", "Results") in ACTION_BUTTONS, "TUI right-pane buttons keep Results action")
    assert_true(("settings", "Settings") in ACTION_BUTTONS, "TUI right-pane buttons keep Settings action")
    assert_true(("migration-support", "Migration") in ACTION_BUTTONS, "TUI right-pane buttons expose migration support")
    assert_equal(len(ACTION_BUTTON_ROWS), 2, "TUI right-pane buttons use restored two-row layout")
    assert_equal(
        ACTION_BUTTON_ROWS[0],
        (
            ("profiles", "Profiles"),
            ("dry-run", "Dry"),
            ("deps", "Deps"),
            ("new-profile", "New"),
            ("setup", "Setup"),
            ("edit-profile", "Edit"),
        ),
        "TUI right-pane first button row matches restored layout",
    )
    assert_equal(
        ACTION_BUTTON_ROWS[1],
        (
            ("history", "History"),
            ("run", "Run"),
            ("results", "Results"),
            ("settings", "Settings"),
            ("migration-support", "Migration"),
            ("refresh", "Refresh"),
        ),
        "TUI right-pane second button row matches restored layout",
    )
    tui_app_source = (ROOT / "Modules" / "lvs_tui_app.py").read_text(encoding="utf-8")
    assert_true(".action-row {\n        height: 3;\n        width: 100%;" in tui_app_source, "TUI action rows span panel width")
    assert_true("#actions Button {\n        width: 1fr;" in tui_app_source, "TUI right-pane buttons share row width")
    assert_true("margin-right: 0;" in tui_app_source, "TUI right-pane buttons avoid standalone gaps")
    assert_true(("global-upload", "G Upload") in GLOBAL_ACTION_BUTTONS, "TUI global buttons keep upload action")
    assert_true(("global-wall-wattage", "W Watts") in GLOBAL_ACTION_BUTTONS, "TUI global buttons keep wall watts action")
    assert_true(("global-back", "Esc Back") in GLOBAL_ACTION_BUTTONS, "TUI global buttons keep back action")
    assert_true(("global-quit", "Q Quit") in GLOBAL_ACTION_BUTTONS, "TUI global buttons keep quit action")
    global_wide_rows = layout_action_button_rows(GLOBAL_ACTION_BUTTONS, available_width=180, preferred_rows=2)
    assert_equal(len(global_wide_rows), 1, "TUI global buttons use one row on wide terminals")
    assert_equal(
        sum(len(row) for row in global_wide_rows),
        len(GLOBAL_ACTION_BUTTONS),
        "TUI global wide row includes every footer action",
    )
    global_narrow_rows = layout_action_button_rows(GLOBAL_ACTION_BUTTONS, available_width=72, preferred_rows=2)
    assert_true(len(global_narrow_rows) > 2, "TUI global buttons dynamically wrap on narrow terminals")
    assert_equal(
        sum(len(row) for row in global_narrow_rows),
        len(GLOBAL_ACTION_BUTTONS),
        "TUI global narrow rows include every footer action",
    )
    assert_true(
        len(layout_action_button_rows(GLOBAL_ACTION_BUTTONS, available_width=260, preferred_rows=2)) == 1,
        "TUI global buttons remain one row on very wide terminals",
    )
    assert_true(
        len(layout_action_button_rows(GLOBAL_ACTION_BUTTONS, available_width=52, preferred_rows=2)) > len(global_narrow_rows),
        "TUI global buttons add rows as terminals get narrower",
    )
    assert_equal(
        action_layout_width(container_width=160, app_width=80, cached_width=72),
        160,
        "TUI global button layout prefers mounted container width",
    )
    assert_equal(
        action_layout_width(container_width=0, app_width=180, cached_width=72),
        180,
        "TUI global button layout falls back to app resize width",
    )
    assert_equal(
        action_layout_width(container_width=0, app_width=0, cached_width=120),
        120,
        "TUI global button layout keeps last known width instead of stale default rows",
    )
    global_cell_wide_rows = global_action_cell_rows(GLOBAL_ACTION_BUTTONS, available_width=180)
    assert_equal(len(global_cell_wide_rows), 1, "TUI global action cells use one row on wide terminals")
    assert_equal(
        sum(len(row) for row in global_cell_wide_rows),
        len(GLOBAL_ACTION_BUTTONS),
        "TUI global action cells include every footer action when wide",
    )
    global_cell_narrow_rows = global_action_cell_rows(GLOBAL_ACTION_BUTTONS, available_width=72)
    assert_true(len(global_cell_narrow_rows) > 1, "TUI global action cells wrap on narrow terminals")
    assert_true(
        all(cell.start < cell.end for row in global_cell_narrow_rows for cell in row),
        "TUI global action cells expose clickable spans",
    )
    assert_equal(global_action_keypress("Esc Back"), "escape", "TUI global action Esc maps to escape key")
    assert_equal(global_action_keypress("Q Quit"), "q", "TUI global action quit maps to keyboard binding")
    assert_true("#global-actions {\n        height: 4;" in tui_app_source, "TUI global footer reserves fixed visible height")
    assert_true("yield Vertical(id=\"global-actions\")" in tui_app_source, "TUI global footer uses fixed row container")
    assert_true("container.remove_children()" in tui_app_source, "TUI global footer rebuilds rows only on mount/resize")
    assert_true("Button(\n                    markup," in tui_app_source, "TUI global footer uses real clickable buttons")
    assert_true("compact=True" in tui_app_source, "TUI global footer buttons use compact mode")
    assert_true("flat=True" in tui_app_source, "TUI global footer buttons use flat mode")
    assert_true("action=action" not in tui_app_source, "TUI global quit button routes through shared Button.Pressed dispatcher")
    assert_true("set_interval(0.25, self._refresh_global_action_buttons)" in tui_app_source, "TUI global footer polls for terminal width changes")
    assert_true("_rendered_global_action_width" in tui_app_source, "TUI global footer avoids unnecessary rebuilds between width changes")
    assert_true("_current_global_action_width" in tui_app_source, "TUI global footer uses current width resolver")
    assert_true("container_width=None" in tui_app_source, "TUI global button rebuild ignores unstable mounted footer width")
    set_detail_source = tui_app_source.split("    def _set_detail", 1)[1].split("    def _set_action_help", 1)[0]
    assert_true(
        "_refresh_global_action_buttons" not in set_detail_source,
        "TUI global buttons do not rebuild from detail changes/click side effects",
    )
    assert_true("async def on_click" not in (ROOT / "Modules" / "lvs_tui_event_adapter.py").read_text(encoding="utf-8"), "TUI global footer uses button press routing, not generic click routing")
    assert_equal(
        global_action_markup("P Profiles"),
        "[bold $accent]P[/] [white]Profiles[/]",
        "TUI global button markup accents only hotkey",
    )
    assert_equal(
        global_action_markup("Esc Back"),
        "[bold $accent]Esc[/] [white]Back[/]",
        "TUI global button markup handles multi-character hotkey",
    )
    assert_equal(len(GLOBAL_ACTION_BAR_ROWS), 2, "TUI global action bar uses two rows")
    assert_true(("P", "Profiles") in GLOBAL_ACTION_BAR_ROWS[0], "TUI global action bar first row keeps profiles")
    assert_true(("Q", "Quit") in GLOBAL_ACTION_BAR_ROWS[1], "TUI global action bar second row keeps quit")
    assert_true(("Esc", "Back") in GLOBAL_ACTION_BAR_ROWS[1], "TUI global action bar keeps back action")
    narrow_global = global_action_bar_text(terminal_width=72)
    assert_equal(len(narrow_global.splitlines()), 2, "TUI global action bar stays two rows when narrow")
    assert_true("P Profiles" in narrow_global, "TUI narrow global action bar keeps first-row actions")
    assert_true("Esc Back" in narrow_global, "TUI narrow global action bar keeps back action")
    assert_true(" | " in narrow_global, "TUI global action bar keeps dividers")
    narrow_help = compact_action_help_text("results", terminal_width=80)
    assert_true("\n" in narrow_help, "TUI compact help wraps on narrow terminals")
    assert_true("E QA" in narrow_help, "TUI compact help keeps QA action discoverable")
    assert_true("F artifacts" in narrow_help, "TUI compact help keeps artifact action discoverable")
    assert_true(
        all(len(line) <= 74 for line in narrow_help.splitlines()),
        "TUI compact help lines fit narrow right panes",
    )
    setup_help = compact_action_help_text("setup", terminal_width=140)
    assert_true("Esc/B back" in setup_help, "TUI compact setup help exposes back navigation")

    class ResultService:
        def list_results(self):
            return [
                SimpleNamespace(name="Old", path=Path("/tmp/old"), verdict="pass"),
                SimpleNamespace(name="Latest", path=Path("/tmp/latest"), verdict="warning"),
            ]

    class SidebarTitle:
        def __init__(self) -> None:
            self.text = ""

        def update(self, text: str) -> None:
            self.text = text

    class ResultTui(TuiAppActionsAdapterMixin):
        def __init__(self) -> None:
            self.service = ResultService()
            self.last_run_dir = Path("/tmp/latest")
            self.results = []
            self.selected_result = None
            self.selected_profile = SimpleNamespace()
            self.title_widget = SidebarTitle()
            self.rows = []
            self.selected_index = None
            self.summary_seen = None
            self.status = ""
            self.reset_seen = False
            self.focus_seen = False

        def query_one(self, selector):
            return self.title_widget if selector == "#sidebar-title" else SimpleNamespace()

        async def _replace_sidebar_labels(self, list_view, rows, selected_index=None, focus=False):
            self.rows = list(rows)
            self.selected_index = selected_index

        def _apply_navigation_reset(self, reset) -> None:
            self.reset_seen = True
            if reset.clear_selected_profile:
                self.selected_profile = None

        def _set_status(self, text: str) -> None:
            self.status = text

        def _show_result_summary(self, result) -> None:
            self.summary_seen = result

        def _focus_items(self) -> None:
            self.focus_seen = True

    async def run_latest_result_handoff() -> None:
        result_tui = ResultTui()
        await result_tui.action_show_results()
        assert_equal(result_tui.selected_index, 1, "TUI action results selects last run row")
        assert_equal(result_tui.selected_result.path, Path("/tmp/latest"), "TUI action results selects last run result")
        assert_equal(result_tui.summary_seen.path, Path("/tmp/latest"), "TUI action results opens last run summary")
        assert_true(result_tui.focus_seen, "TUI action results focuses list")

    asyncio.run(run_latest_result_handoff())

    class DryRunService:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def dry_run_summary_text(self, profile_path, setup=None, save=True):
            self.started.set()
            self.release.wait(timeout=2.0)
            return f"Dry run complete for {profile_path}"

    class DryRunTui(TuiAppActionsAdapterMixin):
        def __init__(self) -> None:
            self.service = DryRunService()
            self.selected_profile = SimpleNamespace(name="Smoke Profile", path=Path("/tmp/profile.json"))
            self.run_setup = None
            self.dry_run_in_progress = False
            self.detail = ""
            self.status = ""
            self.reset_seen = False
            self.finished = threading.Event()

        def _set_detail(self, text: str) -> None:
            self.detail = text

        def _set_status(self, text: str) -> None:
            self.status = text

        def _apply_navigation_reset(self, reset) -> None:
            self.reset_seen = True

        def call_from_thread(self, callback, *args) -> None:
            callback(*args)
            self.finished.set()

    dry_tui = DryRunTui()
    dry_tui.action_dry_run()
    assert_true(dry_tui.service.started.wait(timeout=1.0), "TUI dry run background service starts")
    assert_true(dry_tui.dry_run_in_progress, "TUI dry run marks in progress")
    assert_true("Dry Run In Progress" in dry_tui.detail, "TUI dry run immediate right-pane feedback")
    dry_tui.service.release.set()
    assert_true(dry_tui.finished.wait(timeout=1.0), "TUI dry run background service finishes")
    assert_true("Dry run complete for /tmp/profile.json" in dry_tui.detail, "TUI dry run final result displayed")
    assert_equal(dry_tui.status, "Dry run complete | Smoke Profile", "TUI dry run final status")

    class MigrationSupportService:
        def __init__(self) -> None:
            self.private_calls = []
            self.preview_paths = []
            self.apply_calls = []

        def public_support_export_text(self):
            return "Public-safe Support Summary\nExport folder: results/Support_Exports/smoke"

        def create_private_migration_bundle(self, *, acknowledge_private_data):
            self.private_calls.append(acknowledge_private_data)
            return SimpleNamespace(summary_text="Private Migration Bundle\nBundle folder: results/Migration_Bundles/smoke")

        def preview_migration_restore(self, bundle_path):
            self.preview_paths.append(bundle_path)
            return SimpleNamespace(
                valid=True,
                summary_text=(
                    "Migration Restore Preview\nWrites performed: no\nAction counts: restore=1\n"
                    "Conflicts requiring staging: 0\nManual actions: 2"
                ),
            )

        def apply_migration_restore(self, bundle_path, *, confirmed):
            self.apply_calls.append((bundle_path, confirmed))
            return SimpleNamespace(
                valid=True,
                summary_text=(
                    "Migration Restore Apply Result\nWrites performed: yes\nAction counts: restore=1\n"
                    "Staging folder: none\nManual actions: 2"
                ),
            )

    class MigrationSupportTui(TuiAppActionsAdapterMixin):
        def __init__(self) -> None:
            self.service = MigrationSupportService()
            self.detail = ""
            self.status = ""
            self.reset_seen = False
            self.view_mode = "profiles"
            self.title = SimpleNamespace(update=lambda text: setattr(self, "title_text", text))
            self.rows = []
            self.pending_input_field = None
            self.pending_migration_bundle_path = None

        def query_one(self, selector):
            return self.title if selector == "#sidebar-title" else SimpleNamespace()

        async def _replace_sidebar_labels(self, list_view, rows, selected_index=None, focus=False):
            self.rows = list(rows)

        def _set_detail(self, text: str) -> None:
            self.detail = text

        def _set_status(self, text: str) -> None:
            self.status = text

        def _apply_navigation_reset(self, reset) -> None:
            self.reset_seen = True

        def _apply_input_state(self, state) -> None:
            self.pending_input_field = state.pending_field
            self.detail = state.detail

        def _clear_setup_input(self, *, focus_items=False) -> None:
            self.pending_input_field = None

    async def run_migration_support_actions() -> None:
        migration_tui = MigrationSupportTui()
        await migration_tui.action_show_migration_support()
        assert_equal(migration_tui.view_mode, "migration_support", "TUI migration support view mode")
        assert_equal(len(migration_tui.rows), 4, "TUI migration support renders choices")
        assert_true(migration_tui.reset_seen, "TUI migration support resets navigation")
        await migration_tui._select_migration_support_action(0)
        assert_true("Public-safe Support Summary" in migration_tui.detail, "TUI public support action renders summary")
        assert_equal(migration_tui.status, "Public-safe support summary complete", "TUI public support action status")

        await migration_tui._select_migration_support_action(1)
        assert_equal(migration_tui.pending_input_field, "__migration_private_ack", "TUI private export awaits acknowledgement")
        assert_equal(migration_tui.service.private_calls, [], "TUI private export does not run before acknowledgement")
        await migration_tui._commit_migration_input("__migration_private_ack", "cancel")
        assert_equal(migration_tui.service.private_calls, [], "TUI private export rejects incorrect acknowledgement")
        await migration_tui._select_migration_support_action(1)
        await migration_tui._commit_migration_input("__migration_private_ack", "PRIVATE")
        assert_equal(migration_tui.service.private_calls, [True], "TUI private export accepts explicit acknowledgement")
        assert_true("Bundle folder" in migration_tui.detail, "TUI private export renders output path")

        await migration_tui._select_migration_support_action(2)
        assert_equal(migration_tui.pending_input_field, "__migration_restore_preview_path", "TUI preview awaits bundle path")
        await migration_tui._commit_migration_input("__migration_restore_preview_path", "/tmp/migration-preview")
        assert_equal(migration_tui.service.preview_paths[-1], Path("/tmp/migration-preview"), "TUI preview passes bundle path")
        assert_true("Writes performed: no" in migration_tui.detail, "TUI preview renders no-write result")

        await migration_tui._select_migration_support_action(3)
        await migration_tui._commit_migration_input("__migration_restore_apply_path", "/tmp/migration-apply")
        assert_equal(migration_tui.pending_input_field, "__migration_restore_apply_confirm", "TUI apply awaits second confirmation")
        assert_equal(migration_tui.service.apply_calls, [], "TUI apply does not run after path alone")
        await migration_tui._commit_migration_input("__migration_restore_apply_confirm", "cancel")
        assert_equal(migration_tui.service.apply_calls, [], "TUI apply rejects incorrect confirmation")
        await migration_tui._select_migration_support_action(3)
        await migration_tui._commit_migration_input("__migration_restore_apply_path", "/tmp/migration-apply")
        await migration_tui._commit_migration_input("__migration_restore_apply_confirm", "APPLY")
        assert_equal(
            migration_tui.service.apply_calls,
            [(Path("/tmp/migration-apply"), True)],
            "TUI apply requires preview path and explicit APPLY",
        )
        assert_true("Writes performed: yes" in migration_tui.detail, "TUI apply renders write result")

    asyncio.run(run_migration_support_actions())


def test_tui_event_adapter_helpers() -> None:
    class FakeTui(TuiEventAdapterMixin):
        def __init__(self) -> None:
            self.pending_input_field = "field"
            self.confirm_run = True
            self.input_reset_seen = False
            self.focus_seen = False

        def _apply_input_reset_state(self, state) -> None:
            self.input_reset_seen = True
            self.pending_input_blank_default = state.blank_default

        def _focus_items(self) -> None:
            self.focus_seen = True

    fake = FakeTui()
    fake._clear_setup_input(focus_items=True)
    assert_equal(fake.pending_input_field, None, "TUI event adapter clears pending input field")
    assert_equal(fake.confirm_run, False, "TUI event adapter clears confirm run state")
    assert_true(fake.input_reset_seen, "TUI event adapter resets input widget state")
    assert_true(fake.focus_seen, "TUI event adapter restores list focus when requested")
    assert_equal(selected_index(SimpleNamespace(list_view=SimpleNamespace(index=2))), 2, "TUI event selected index")
    assert_equal(selected_index(SimpleNamespace(list_view=SimpleNamespace(index=None))), None, "TUI event missing index")
    assert_true(index_in_range(1, ["a", "b"]), "TUI event index in range")
    assert_true(not index_in_range(3, ["a", "b"]), "TUI event index out of range")
    assert_equal(event_key(SimpleNamespace(key="escape")), "escape", "TUI event key text")
    assert_true(is_escape_key(SimpleNamespace(key="escape")), "TUI event escape key")
    assert_equal(setup_input_value("", "Auto"), "Auto", "TUI event blank default")
    assert_equal(button_action("dry-run"), "dry_run", "TUI event button action routing")
    assert_equal(button_action("global-results"), "show_results", "TUI event global result button routing")
    assert_equal(button_action("global-upload"), "upload_last_result", "TUI event global upload button routing")
    assert_equal(button_action("global-wall-wattage"), "edit_wall_wattage", "TUI event global wall wattage button routing")
    assert_equal(button_action("migration-support"), "show_migration_support", "TUI event migration support routing")
    assert_equal(button_action("global-back"), "cancel_setup_input", "TUI event global back button routing")
    assert_equal(button_action("global-quit"), "quit", "TUI event global quit button routing")
    for button_id, label in GLOBAL_ACTION_BUTTONS:
        assert_true(button_action(button_id), f"TUI generated global action routes {label}")
    assert_equal(button_action("unknown"), "", "TUI event ignores unknown button action")
    assert_equal(button_action("global-esc-back"), "cancel_setup_input", "TUI global Esc Back button routes cancel")
    assert_true(view_uses_escape_cancel("setup_picker"), "TUI event setup picker escape cancel")
    assert_true(view_uses_escape_cancel("setup_history_prompt"), "TUI event setup history prompt escape cancel")
    assert_true(view_uses_escape_cancel("setup_history_confirm"), "TUI event setup history confirm escape cancel")
    assert_true(view_uses_escape_cancel("migration_support"), "TUI migration input supports escape cancel")
    assert_true(not view_uses_escape_cancel("settings"), "TUI event settings view does not use picker escape cancel")
    assert_equal(pending_input_route("__post_wall_wattage"), "post_wall_wattage", "TUI event wall wattage input route")
    assert_equal(pending_input_route("__migration_restore_preview_path"), "migration", "TUI event migration input route")
    assert_equal(pending_input_route("__settings_department"), "settings", "TUI event settings input route")
    assert_equal(pending_input_route("__profile_stage_duration"), "profile_edit", "TUI event profile input route")
    assert_equal(pending_input_route("power_limit_amd_power"), "power_limit", "TUI event power-limit input route")
    assert_equal(pending_input_route("stage_duration"), "stage_input", "TUI event stage input route")
    assert_equal(pending_input_route("fan_type"), "fan_type", "TUI event fan type input route")
    assert_equal(pending_input_route("description"), "run_setup", "TUI event run setup input route")

    class ResultRouteService:
        def result_action_for_key(self, key: str) -> FrontendActionSpec:
            if key == "f":
                return FrontendActionSpec("f", "artifact_detail")
            return FrontendActionSpec(key, "")

    class ResultRouteTui(TuiEventAdapterMixin):
        def __init__(self) -> None:
            self.run_in_progress = False
            self.view_mode = "results"
            self.service = ResultRouteService()
            self.artifact_detail_seen = False

        def _show_result_artifact_details(self) -> None:
            self.artifact_detail_seen = True

    class KeyEvent:
        key = "f"

        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    async def run_result_route_check() -> None:
        result_route = ResultRouteTui()
        event = KeyEvent()
        await result_route.on_key(event)
        assert_true(result_route.artifact_detail_seen, "TUI event routes result artifact detail action")
        assert_true(event.stopped, "TUI event stops result artifact detail action")

    asyncio.run(run_result_route_check())

    class ProfileRecallPromptTui(TuiEventAdapterMixin):
        def __init__(self, has_history: bool) -> None:
            self.run_in_progress = False
            self.upload_in_progress = False
            self.view_mode = "profiles"
            self.profiles = [SimpleNamespace(path=Path("/tmp/profile.json"), name="Profile")]
            self.selected_profile = None
            self.run_setup = None
            self.prompted = False
            self.setup_shown = False
            self.has_history = has_history
            self.service = SimpleNamespace(
                create_run_setup=lambda path: SimpleNamespace(profile_path=path),
            )

        def _apply_navigation_reset(self, reset) -> None:
            pass

        async def _maybe_prompt_setup_history_recall(self) -> bool:
            self.prompted = True
            return self.has_history

        async def _show_run_setup_sidebar(self) -> None:
            self.setup_shown = True

    class ListEvent:
        def __init__(self, index: int) -> None:
            self.list_view = SimpleNamespace(index=index)

    async def run_profile_recall_prompt_check() -> None:
        prompt_tui = ProfileRecallPromptTui(has_history=True)
        await prompt_tui.on_list_view_selected(ListEvent(0))
        assert_true(prompt_tui.prompted, "TUI profile selection checks previous setup recall")
        assert_true(not prompt_tui.setup_shown, "TUI profile selection waits at recall prompt when history exists")
        no_history_tui = ProfileRecallPromptTui(has_history=False)
        await no_history_tui.on_list_view_selected(ListEvent(0))
        assert_true(no_history_tui.prompted, "TUI profile selection checks recall even when no history")
        assert_true(no_history_tui.setup_shown, "TUI profile selection continues setup when no history exists")

    asyncio.run(run_profile_recall_prompt_check())

    class GlobalButtonTui(TuiEventAdapterMixin):
        def __init__(self) -> None:
            self.actions = []
            self.exited = False

        def _interaction_locked(self) -> bool:
            return False

        def _show_locked_interaction_message(self) -> None:
            self.actions.append("locked")

        async def action_show_results(self) -> None:
            self.actions.append("results")

        def action_upload_last_result(self) -> None:
            self.actions.append("upload")

        def action_edit_wall_wattage(self) -> None:
            self.actions.append("watts")

        async def action_cancel_setup_input(self) -> None:
            self.actions.append("back")

        def exit(self) -> None:
            self.actions.append("quit")
            self.exited = True

    class ButtonEvent:
        def __init__(self, widget_id: str) -> None:
            self.button = SimpleNamespace(id=widget_id)

    async def run_global_button_check() -> None:
        global_button = GlobalButtonTui()
        for widget_id in (
            "global-results",
            "global-upload",
            "global-wall-wattage",
            "global-back",
            "global-quit",
        ):
            await global_button.on_button_pressed(ButtonEvent(widget_id))
        assert_equal(
            global_button.actions,
            ["results", "upload", "watts", "back", "quit"],
            "TUI global bottom buttons dispatch existing actions",
        )
        assert_true(global_button.exited, "TUI global quit button exits the app")

    asyncio.run(run_global_button_check())

    class LockedBackTui(TuiEventAdapterMixin):
        def __init__(self) -> None:
            self.actions = []

        def _interaction_locked(self) -> bool:
            return True

        def _show_locked_interaction_message(self) -> None:
            self.actions.append("locked")

        async def action_cancel_setup_input(self) -> None:
            self.actions.append("back")

    async def run_locked_back_button_check() -> None:
        locked_back = LockedBackTui()
        await locked_back.on_button_pressed(ButtonEvent("global-back"))
        assert_equal(
            locked_back.actions,
            ["back"],
            "TUI global back button bypasses input lock and cancels like Escape",
        )

    asyncio.run(run_locked_back_button_check())

    class RunningBackTui(TuiEventAdapterMixin):
        def __init__(self) -> None:
            self.actions = []
            self.upload_in_progress = False

        def _interaction_locked(self) -> bool:
            return True

        def _show_locked_interaction_message(self, cancel_requested: bool = False) -> None:
            self.actions.append("cancel" if cancel_requested else "locked")

        async def action_cancel_setup_input(self) -> None:
            self._show_locked_interaction_message(cancel_requested=True)

    class UploadLockedTui(TuiEventAdapterMixin):
        def __init__(self) -> None:
            self.actions = []
            self.upload_in_progress = True

        def _interaction_locked(self) -> bool:
            return True

        def _show_locked_interaction_message(self, cancel_requested: bool = False) -> None:
            self.actions.append("upload-locked")

        async def action_cancel_setup_input(self) -> None:
            self.actions.append("back")

    async def run_cancel_and_upload_lock_checks() -> None:
        running_back = RunningBackTui()
        await running_back.on_button_pressed(ButtonEvent("global-back"))
        assert_equal(running_back.actions, ["cancel"], "TUI global back routes run cancel request")
        running_esc_back = RunningBackTui()
        await running_esc_back.on_button_pressed(ButtonEvent("global-esc-back"))
        assert_equal(running_esc_back.actions, ["cancel"], "TUI global Esc Back routes run cancel request")
        upload_locked = UploadLockedTui()
        await upload_locked.on_button_pressed(ButtonEvent("global-back"))
        assert_equal(upload_locked.actions, ["upload-locked"], "TUI upload lock blocks back button during active upload")

    asyncio.run(run_cancel_and_upload_lock_checks())

    class SetupEscapeTui(TuiEventAdapterMixin):
        def __init__(self) -> None:
            self.run_in_progress = False
            self.view_mode = "setup"
            self.run_setup = SimpleNamespace()
            self.pending_input_field = None
            self.profiles_seen = False

        async def action_show_profiles(self) -> None:
            self.profiles_seen = True
            self.view_mode = "profiles"

    class EscapeEvent:
        key = "escape"

        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    async def run_setup_escape_check() -> None:
        setup_tui = SetupEscapeTui()
        event = EscapeEvent()
        await setup_tui.on_key(event)
        assert_true(setup_tui.profiles_seen, "TUI setup escape returns to profiles")
        assert_true(event.stopped, "TUI setup escape stops event")

    asyncio.run(run_setup_escape_check())


def test_tui_run_presentation_helpers() -> None:
    confirmation = run_confirmation_presentation(
        profile_name="PL Validation",
        setup_summary="Setup summary",
        readiness_text="Ready",
    )
    assert_true("Run confirmation" in confirmation.detail, "TUI run confirmation title")
    assert_true("Profile: PL Validation" in confirmation.detail, "TUI run confirmation profile")
    assert_true("Setup summary" in confirmation.detail, "TUI run confirmation setup summary")
    assert_true("Ready" in confirmation.detail, "TUI run confirmation readiness")
    assert_true("Press Run again" in confirmation.detail, "TUI run confirmation start instruction")
    blocked_confirmation = run_confirmation_presentation(
        profile_name="PL Validation",
        setup_summary="Setup summary",
        readiness_text="Status: blocked",
        can_run=False,
    )
    assert_true(
        "Run is blocked. Fix the readiness issues above before starting." in blocked_confirmation.detail,
        "TUI run confirmation blocked instruction",
    )
    assert_true("Press Run again" not in blocked_confirmation.detail, "TUI blocked confirmation omits start instruction")

    initial = initial_run_active_presentation("PL Validation", 3.0)
    assert_equal(initial.status, "Run active | PL Validation", "TUI run active initial status")
    assert_true("Heatsoak: 3 min Power Test will run first." in initial.detail, "TUI run active heatsoak text")
    assert_true("request safe cancellation" in initial.detail, "TUI run active cancel guidance")
    assert_equal(initial.sidebar_title, RUN_ACTIVE_SIDEBAR_TITLE, "TUI run active sidebar title")
    with TemporaryDirectory(dir="/tmp") as tmp:
        result_dir = Path(tmp) / "Run"
        result_dir.mkdir()
        (result_dir / "parsed_results_custom.json").write_text("{}", encoding="utf-8")
        (result_dir / "raw_telemetry.csv").write_text("timestamp,cpu_temp_c\n", encoding="utf-8")
        (result_dir / "telemetry_source_map.json").write_text("{}", encoding="utf-8")
        post_run = post_run_operator_presentation(
            "Run Complete\n============\n\nResult: Warning",
            result_dir=result_dir,
            artifact_item={
                "kind": "run_result",
                "result": "warning",
                "artifacts": ["run_summary.txt", "result_validation.json"],
            },
            upload_status="skipped",
        )
        assert_true("TUI Post-Run Context" in post_run, "TUI post-run context heading")
        assert_true(f"Latest result folder: {result_dir}" in post_run, "TUI post-run result folder")
        assert_true("Upload status: skipped" in post_run, "TUI post-run upload status")
        assert_true(
            "- Parsed results: available (parsed_results_custom.json)" in post_run,
            "TUI post-run parsed availability",
        )
        assert_true("- Run summary: available (run_summary.txt)" in post_run, "TUI post-run summary availability")
        assert_true(
            "- Telemetry source map: available (telemetry_source_map.json)" in post_run,
            "TUI post-run source map availability",
        )
        assert_true("- Raw telemetry: available (raw_telemetry.csv)" in post_run, "TUI post-run raw telemetry")
        assert_true("Press W to add or update observed wall wattage" in post_run, "TUI post-run wall wattage step")
        assert_true("use E for QA review" in post_run, "TUI post-run QA review step")
    failed_post_run = post_run_operator_presentation("Run failed\n==========\n\nboom", result_dir=None)
    assert_true("Result folder: not available" in failed_post_run, "TUI failed post-run no result folder")
    assert_true("No result-folder actions are available" in failed_post_run, "TUI failed post-run guidance")
    assert_equal(initial.sidebar_rows, RUN_ACTIVE_SIDEBAR_ROWS, "TUI run active sidebar rows")

    tracker = RunStatusTracker()
    event = parse_progress_event("[phase] 2026-06-30T12:00:00 | stage-start | stage=1 | name=Power")
    assert_true(event is not None, "TUI run presentation progress event parsed")
    tracker.update_event(event)
    end_event = parse_progress_event("[phase] 2026-06-30T12:05:00 | stage-end | stage=1 | verdict=pass | elapsed=300s")
    assert_true(end_event is not None, "TUI run presentation stage end parsed")
    tracker.update_event(end_event)
    next_event = parse_progress_event("[phase] 2026-06-30T12:05:01 | stage-start | stage=2 | name=SSE")
    assert_true(next_event is not None, "TUI run presentation next stage parsed")
    tracker.update_event(next_event)
    live_progress = parse_progress_event(
        "2026-06-30T12:05:31-04:00 | stage=2 | elapsed=00:00:30 | remaining=00:04:30 | "
        "gpu_target=gpu0@0000:04:00.0/python_vulkan_compute:busy=98.0%,mem_busy=1.0%,"
        "pwr=116.0W,temp=68.0C,clk=2625.0MHz,mclk=1000.0MHz,vram=2.83GB,state=load=79.9%,"
        "comp_buf=1,buf=307.0MB,rounds=160"
    )
    assert_true(live_progress is not None, "TUI live stage progress line parsed")
    assert_equal(live_progress.event_type, "stage-progress", "TUI live stage progress event type")
    tracker.update_event(live_progress)
    wide_live_layout = live_system_layout(terminal_width=160, run_active=True)
    assert_true(wide_live_layout.visible, "TUI wide active-run layout shows Live System pane")
    assert_equal(wide_live_layout.pane_width, 32, "TUI Live System pane uses compact width")
    assert_true(
        not live_system_layout(terminal_width=100, run_active=True).visible,
        "TUI narrow active-run layout hides Live System pane",
    )
    assert_true(
        not live_system_layout(terminal_width=160, run_active=False).visible,
        "TUI inactive layout hides Live System pane",
    )
    live_gpu_rows, live_gpu_stale = live_system_gpu_metrics(tracker.events)
    assert_equal(len(live_gpu_rows), 1, "TUI Live System parses one GPU progress row")
    assert_equal(live_gpu_rows[0].gpu_index, 0, "TUI Live System GPU index")
    assert_equal(live_gpu_rows[0].load_percent, 98.0, "TUI Live System GPU load")
    assert_equal(live_gpu_rows[0].temp_c, 68.0, "TUI Live System GPU temperature")
    assert_equal(live_gpu_rows[0].power_w, 116.0, "TUI Live System GPU power")
    assert_equal(live_gpu_rows[0].clock_mhz, 2625.0, "TUI Live System GPU clock")
    assert_equal(live_gpu_rows[0].vram_used_gib, 2.83, "TUI Live System GPU VRAM")
    assert_true(not live_gpu_stale, "TUI latest GPU progress sample is current")
    live_text = live_system_text(tracker.events)
    for expected in ("Live System", "GPU 0", "Load   98%", "68 °C", "116 W", "2625 MHz", "2.8 GiB used"):
        assert_true(expected in live_text, f"TUI Live System renders {expected}")
    assert_true(
        "Waiting for available" in live_system_text([]),
        "TUI Live System handles missing telemetry",
    )
    later_event = parse_progress_event("[phase] 2026-06-30T12:06:00 | stage-end | stage=2 | verdict=pass")
    assert_true(later_event is not None, "TUI later event parsed for stale telemetry check")
    stale_text = live_system_text([*tracker.events, later_event])
    assert_true("(not current)" in stale_text, "TUI Live System marks retained telemetry stale")
    assert_equal(tracker.snapshot.elapsed, "00:00:30", "TUI live stage progress updates elapsed")
    assert_equal(tracker.snapshot.remaining, "00:04:30", "TUI live stage progress updates remaining")
    stage_progress = stage_progress_table_text(tracker.events)
    assert_true("- Stage 1: pass" in stage_progress, "TUI stage progress keeps completed stage line")
    assert_true("- Stage 2: running" in stage_progress, "TUI stage progress updates current stage line")
    assert_true("elapsed=00:00:30" in stage_progress, "TUI stage progress row refreshes current elapsed")
    assert_true("gpu_target=" not in stage_progress, "TUI stage progress suppresses long backend target details")
    active_stage = active_stage_line_text(tracker.snapshot, tracker.events, width=96)
    assert_true("Active: 2" in active_stage, "TUI active stage line uses current stage")
    assert_true("elapsed=00:00:30" in active_stage, "TUI active stage line shows current elapsed")
    assert_true(len(active_stage) <= 96, "TUI active stage line is width limited")
    progress = run_progress_detail_text(
        profile_name="PL Validation",
        status_snapshot=tracker.snapshot,
        phase_line=live_progress.raw_line,
        events=tracker.events,
        output_lines=[
            "non-progress line 1",
            "non-progress line 2",
            "very long backend output " + ("x" * 180),
        ],
    )
    assert_true("Run In Progress" in progress, "TUI run progress title")
    assert_true("Current Status" in progress, "TUI run progress current status section")
    assert_true("Latest: 2026-06-30T12:05:31-04:00" in progress, "TUI run progress compact latest event")
    assert_true("Stage Progress" in progress, "TUI run progress stage table")
    assert_true("Output Tail" in progress, "TUI run progress output tail heading")
    assert_true("non-progress line 2" in progress, "TUI run progress keeps non-progress output")
    assert_true("very long backend output" in progress, "TUI run progress keeps long output summary")
    assert_true("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in progress, "TUI run progress truncates long output")
    small_tail = output_tail_text(["one", "two", "three"], limit=2, width=12)
    assert_equal(small_tail, "two\nthree", "TUI small output tail keeps only requested lines")
    output_update = apply_run_output_line(
        line=live_progress.raw_line,
        output_lines=["existing non-progress"],
        phase_line="",
        status_snapshot=tracker.snapshot,
        tracker_status_text=tracker.status_text(),
    )
    assert_true(output_update is not None, "TUI run output update from progress line")
    assert_equal(
        output_update.output_lines,
        ["existing non-progress"],
        "TUI run output suppresses phase spam from output tail",
    )

    locked = locked_run_detail_text(
        profile_name="PL Validation",
        status_snapshot=tracker.snapshot,
        phase_line=event.raw_line,
        events=tracker.events,
        cancel_requested=True,
    )
    assert_true("Navigation and edits are locked" in locked, "TUI locked run detail")
    assert_true("Cancel requested: stopping active workers" in locked, "TUI locked cancel detail")
    assert_true("Enter wall wattage" in locked_post_run_wall_wattage_text(), "TUI locked wall prompt text")
    assert_true("Choose Upload to Google Drive" in locked_post_run_upload_text(), "TUI locked upload prompt text")


def test_segment_parser_cpu_package_metrics() -> None:
    parser = SegmentParser()
    window = StageWindow(
        stage_id="segment_1",
        stage_type="Combined",
        display_name="Power",
        started_iso="2026-06-25T10:00:00-04:00",
        ended_iso="2026-06-25T10:01:00-04:00",
        started_monotonic=0.0,
        ended_monotonic=60.0,
        duration_seconds=60.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="pass",
    )
    telemetry = SimpleNamespace(
        samples=[
            Sample(
                10.0,
                {
                    "cpu_temp_c": 62.0,
                    "cpu_power_w": 350.0,
                    "cpu_package_0_temp_c": 60.0,
                    "cpu_package_1_temp_c": 62.0,
                    "cpu_package_0_power_w": 150.0,
                    "cpu_package_1_power_w": 200.0,
                    "cpu_core_0_clock_mhz": 3000.0,
                    "cpu_core_1_clock_mhz": 3200.0,
                    "cpu_core_2_clock_mhz": 2800.0,
                    "cpu_core_3_clock_mhz": 2900.0,
                },
            ),
            Sample(
                20.0,
                {
                    "cpu_temp_c": 65.0,
                    "cpu_power_w": 370.0,
                    "cpu_package_0_temp_c": 61.0,
                    "cpu_package_1_temp_c": 65.0,
                    "cpu_package_0_power_w": 160.0,
                    "cpu_package_1_power_w": 210.0,
                    "cpu_core_0_clock_mhz": 3100.0,
                    "cpu_core_1_clock_mhz": 3300.0,
                    "cpu_core_2_clock_mhz": 2700.0,
                    "cpu_core_3_clock_mhz": 2950.0,
                },
            ),
        ],
        _cpu_core_clock_sources=[
            {"key": "cpu_core_0_clock_mhz", "physical_core_key": "package0:core0"},
            {"key": "cpu_core_1_clock_mhz", "physical_core_key": "package0:core1"},
            {"key": "cpu_core_2_clock_mhz", "physical_core_key": "package1:core0"},
            {"key": "cpu_core_3_clock_mhz", "physical_core_key": "package1:core1"},
        ],
    )
    cpu_info = {
        "Name": "2x AMD EPYC 9255 24-Core Processor",
        "Topology": {
            "PackageCount": 2,
            "Packages": [
                {"PackageId": 0, "Name": "AMD EPYC 9255 24-Core Processor"},
                {"PackageId": 1, "Name": "AMD EPYC 9255 24-Core Processor"},
            ],
        },
        "PackageDevices": [
            {"PackageId": 0, "DeviceId": "cpu_package_0", "Name": "AMD EPYC 9255 24-Core Processor"},
            {"PackageId": 1, "DeviceId": "cpu_package_1", "Name": "AMD EPYC 9255 24-Core Processor"},
        ],
    }

    output = parser.summarize([window], telemetry, [], cpu_info)
    segment = output["Segments"][0]
    assert_equal(segment["Temperatures"]["Cpu"]["Max"], 65.0, "combined CPU temperature remains")
    assert_equal(segment["Power"]["Cpu"]["Avg"], 360.0, "combined CPU power remains")
    assert_equal(segment["Clocks"]["AllCoreAverage"]["Avg"], 2993.75, "combined all-core clock remains")

    cpu_section = segment["Cpu"]
    assert_equal(cpu_section["Combined"]["Temp"], segment["Temperatures"]["Cpu"], "CPU combined temp mirrors legacy field")
    assert_equal(cpu_section["Combined"]["Power"], segment["Power"]["Cpu"], "CPU combined power mirrors legacy field")
    assert_equal(
        cpu_section["Combined"]["AllCoreAverageClock"],
        segment["Clocks"]["AllCoreAverage"],
        "CPU combined clock mirrors legacy field",
    )
    packages = cpu_section["Packages"]
    assert_equal([package["PackageId"] for package in packages], [0, 1], "package IDs preserved")
    assert_equal(packages[0]["MetricTarget"], "package_0", "package 0 metric target")
    assert_equal(packages[1]["MetricTarget"], "package_1", "package 1 metric target")
    assert_equal(packages[0]["Temp"]["Max"], 61.0, "package 0 temp max")
    assert_equal(packages[1]["Power"]["Avg"], 205.0, "package 1 power avg")
    assert_equal(packages[0]["Clock"]["Avg"], 3150.0, "package 0 clock avg")
    assert_equal(packages[1]["Clock"]["Avg"], 2837.5, "package 1 clock avg")
    assert_equal(output["SegmentDetails"]["segment_1"]["cpu"]["Packages"][0]["Power"]["Max"], 160.0, "details package power")


def test_segment_parser_single_cpu_keeps_legacy_shape() -> None:
    parser = SegmentParser()
    window = StageWindow(
        stage_id="segment_1",
        stage_type="CPU",
        display_name="CPU",
        started_iso="2026-06-25T10:00:00-04:00",
        ended_iso="2026-06-25T10:01:00-04:00",
        started_monotonic=0.0,
        ended_monotonic=60.0,
        duration_seconds=60.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="pass",
    )
    telemetry = SimpleNamespace(
        samples=[
            Sample(10.0, {"cpu_temp_c": 55.0, "cpu_power_w": 100.0, "cpu_package_0_temp_c": 55.0}),
            Sample(20.0, {"cpu_temp_c": 57.0, "cpu_power_w": 110.0, "cpu_package_0_temp_c": 57.0}),
        ],
        _cpu_core_clock_sources=[],
    )
    output = parser.summarize([window], telemetry, [], {"Topology": {"PackageCount": 1}})
    segment = output["Segments"][0]
    assert_equal(segment["Temperatures"]["Cpu"]["Max"], 57.0, "single CPU combined temp")
    assert_equal(segment["Power"]["Cpu"]["Avg"], 105.0, "single CPU combined power")
    assert_true("AllCoreAverage" in segment["Clocks"], "single CPU legacy all-core clock field remains")
    assert_true("Combined" in segment["Cpu"], "single CPU combined CPU section remains")
    assert_true("Packages" not in segment["Cpu"], "single CPU does not add package section")


def test_cpu_system_info_dual_cpu_fixture_contract() -> None:
    fixture_path = ROOT / "smoke_tests" / "fixtures" / "cpu_system_info_dual_cpu_pl_validation_24hr_trimmed.json"
    parsed = json.loads(fixture_path.read_text())

    metadata = parsed["Metadata"]
    system_cpu = parsed["SystemInfo"]["Hardware"]["Cpu"]
    system_memory = parsed["SystemInfo"]["Hardware"]["Memory"]
    cpu_devices = parsed["Cpu"]["devices"]
    cpu_tests = parsed["Cpu"]["tests"]
    memory_devices = parsed["Memory"]["devices"]
    segment = parsed["Segments"][0]

    assert_equal(parsed["_FixtureSource"], "trimmed retained QA parsed-results fixture", "dual CPU fixture source")
    assert_equal(metadata["ProfileName"], "PL Validation 24hr", "dual CPU profile")
    assert_equal(metadata["CpuName"], "2x AMD EPYC 9255 24-Core Processor", "dual CPU metadata name")
    assert_equal(metadata["CpuAggregateName"], metadata["CpuName"], "dual CPU aggregate name mirror")
    assert_equal(metadata["CpuPackageCount"], 2, "dual CPU metadata package count")
    assert_equal(metadata["CpuLogicalCount"], 96, "dual CPU metadata logical count")
    assert_equal(metadata["CpuPhysicalCoreCount"], 48, "dual CPU metadata physical core count")
    assert_equal(metadata["CpuPackageNames"], ["AMD EPYC 9255 24-Core Processor"] * 2, "dual CPU package names")

    package_devices = metadata["CpuPackageDevices"]
    assert_equal([device["PackageId"] for device in package_devices], [0, 1], "dual CPU package IDs")
    assert_equal([device["DeviceId"] for device in package_devices], ["cpu_package_0", "cpu_package_1"], "dual CPU device IDs")
    assert_equal([device["LogicalCpuCount"] for device in package_devices], [48, 48], "dual CPU per-package logical counts")
    assert_equal([device["PhysicalCoreCount"] for device in package_devices], [24, 24], "dual CPU per-package physical counts")
    assert_equal(
        [device["LogicalCpuRange"] for device in package_devices],
        ["0-23,48-71", "24-47,72-95"],
        "dual CPU logical CPU ranges",
    )

    assert_equal(system_cpu["Name"], metadata["CpuName"], "system info CPU name mirror")
    assert_equal(system_cpu["AggregateName"], metadata["CpuAggregateName"], "system info CPU aggregate mirror")
    assert_equal(system_cpu["Topology"]["PackageCount"], metadata["CpuPackageCount"], "system info topology package count")
    assert_equal(system_cpu["Topology"]["LogicalCpuCount"], metadata["CpuLogicalCount"], "system info topology logical count")
    assert_equal(system_cpu["Topology"]["PhysicalCoreCount"], metadata["CpuPhysicalCoreCount"], "system info topology physical count")
    assert_equal(system_cpu["PackageDevices"], package_devices, "system info package device mirror")

    assert_equal(cpu_devices["cpu_model"], metadata["CpuName"], "compat CPU model")
    assert_equal(cpu_devices["aggregate_cpu_model"], metadata["CpuAggregateName"], "compat aggregate CPU model")
    assert_equal(cpu_devices["cpu_package_count"], metadata["CpuPackageCount"], "compat package count")
    assert_equal(cpu_devices["logical_cpu_count"], metadata["CpuLogicalCount"], "compat logical count")
    assert_equal(cpu_devices["physical_core_count"], metadata["CpuPhysicalCoreCount"], "compat physical count")
    assert_equal(cpu_devices["cpu_package_devices"], package_devices, "compat package device mirror")
    assert_equal([package["PackageId"] for package in cpu_devices["cpu_packages"]], [0, 1], "compat package list IDs")

    assert_true("CPU Package (Temperature)" in cpu_tests, "compat CPU package temperature test")
    assert_true("CPU Package Power (Power)" in cpu_tests, "compat CPU package power test")
    assert_equal(
        cpu_tests["CPU Package (Temperature)"][0]["results"]["Power (CPU + 3D)"],
        {"avg": 59.77, "max": 60.75, "min": 57.12},
        "compat CPU package temperature stats",
    )
    assert_equal(
        cpu_tests["CPU Package Power (Power)"][0]["results"]["Power (CPU + 3D)"],
        {"avg": 353.62, "max": 356.83, "min": 350.09},
        "compat CPU package power stats",
    )

    assert_equal(system_memory["TotalPhysicalMemoryGB"], 377, "system memory total")
    assert_equal(len(system_memory["Modules"]), 2, "trimmed system memory module count")
    assert_equal(len(memory_devices), 2, "trimmed compat memory module count")
    first_module = system_memory["Modules"][0]
    assert_equal(first_module["Type"], "DDR5", "system memory module type")
    assert_equal(first_module["CapacityGB"], 32, "system memory module capacity")
    assert_equal(first_module["Speed"], 5600, "system memory module speed")
    assert_equal(first_module["Position"], "P0 CHANNEL A/CPU1_DIMM_A1", "system memory module position")
    assert_equal(memory_devices[0]["PartNumber"], first_module["PartNumber"], "compat memory part mirror")
    assert_true("System Memory Used (Usage)" in parsed["Memory"]["tests"], "compat memory usage test")

    assert_equal(segment["Cpu"]["Combined"]["Temp"], segment["Temperatures"]["Cpu"], "segment CPU combined temp mirror")
    assert_equal(segment["Cpu"]["Combined"]["Power"], segment["Power"]["Cpu"], "segment CPU combined power mirror")
    assert_equal(
        segment["Cpu"]["Combined"]["AllCoreAverageClock"],
        segment["Clocks"]["AllCoreAverage"],
        "segment CPU combined clock mirror",
    )
    segment_packages = segment["Cpu"]["Packages"]
    assert_equal([package["PackageId"] for package in segment_packages], [0, 1], "segment CPU package IDs")
    assert_equal([package["MetricTarget"] for package in segment_packages], ["package_0", "package_1"], "segment CPU metric targets")
    assert_equal(segment_packages[0]["Temp"]["Max"], 56.62, "segment package 0 temp max")
    assert_equal(segment_packages[1]["Power"]["Max"], 180.31, "segment package 1 power max")
    assert_equal(segment_packages[0]["Clock"]["Avg"], 4268.52, "segment package 0 clock avg")


def test_report_highlights_and_xid_language() -> None:
    stage = build_report_stage_summary(
        {
            "Label": "Power",
            "TestType": "Combined",
            "Verdict": "warning",
            "StabilityInterpretation": {},
            "GpuMetrics": [
                {
                    "Targeted": True,
                    "GpuIndex": 0,
                    "Name": "NVIDIA GeForce RTX 5090",
                    "DisplayName": "NVIDIA GeForce RTX 5090 #2",
                    "TargetIds": ["0000:f1:00.0"],
                    "Usage": {"Avg": 90.0, "Max": 99.0},
                    "WorkerEvidence": {"VerificationPasses": 10},
                }
            ],
        }
    )
    assert_equal(stage["GpuHighlights"][0]["Name"], "NVIDIA GeForce RTX 5090 #2", "GPU highlight display name")
    summary = build_department_use_summary(
        overall_result="Aborted",
        execution_detail="aborted",
        stability_interpretation={"ErrorCategoryCounts": {"nvidia_xid": 2}, "WarningCategoryCounts": {}},
        warning_events=[],
        error_events=[{"category": "nvidia_xid"}, {"category": "nvidia_xid"}],
        skipped_stages=[],
        worker_result_count=2,
        worker_success_count=1,
        worker_failure_count=1,
        verification_passes=10,
    )
    assert_true(any("NVIDIA Xid" in note for note in summary["OperatorNotes"]), "NVIDIA Xid operator note")
    assert_true(any("NVIDIA Xid driver/GPU fault" in caveat for caveat in summary["PrimaryCaveats"]), "NVIDIA Xid caveat")
    thermal_items = build_report_action_item_details(
        {"WarningCategoryCounts": {}, "ErrorCategoryCounts": {"gpu_temperature": 1}},
        [],
        [{"category": "gpu_temperature", "message": "gpu_0_temp_core_c exceeded fail threshold"}],
        [],
    )
    assert_true(any(item.get("Category") == "gpu_temperature" for item in thermal_items), "GPU thermal abort action item")
    assert_true(
        not any(item.get("Category") == "workload_or_system_error" for item in thermal_items),
        "GPU thermal abort should not be generic workload error",
    )
    outcome = overall_report_outcome_summary("aborted", {}, {"gpu_temperature": 1}, [])
    assert_equal(outcome["OutcomeClass"], "thermal_safety_abort", "thermal abort outcome class")
    intel_summary = build_report_intel_gpu_top_summary(
        {
            "available": True,
            "object_count": 3,
            "aggregate_engine_busy": {"max": 88.0},
            "engines": {
                "Render/3D": {"max": 88.0, "avg": 40.0},
                "Blitter": {"max": 0.5, "avg": 0.1},
            },
            "reason": "",
            "raw_path": "intel_gpu_top/stage.json",
            "summary_path": "intel_gpu_top/stage.summary.json",
        }
    )
    assert_true(intel_summary is not None, "Intel GPU sidecar report summary exists")
    assert_equal(intel_summary["ActiveEngines"], {"Render/3D": {"max": 88.0, "avg": 40.0}}, "Intel active engines")
    assert_equal(intel_summary["RawPath"], "intel_gpu_top/stage.json", "Intel sidecar raw path")


def test_clean_review_verdict_defaults_to_pass_for_evaluated_clean_payload() -> None:
    parsed = {
        "Result": "Finished",
        "ExecutionDetail": "completed",
        "ReportSummary": {
            "Result": "Finished",
            "ExecutionDetail": "completed",
            "OutcomeClass": "verified_clean",
            "OutcomeSummary": "No issues found -- all evaluated rules passed.",
            "StageOutcomes": [
                {"Label": "Power", "Verdict": "pass", "OutcomeClass": "verified_clean"},
                {"Label": "SSE", "Verdict": "pass", "OutcomeClass": "verified_clean"},
            ],
            "ReportOnlyThresholdUnobservedCount": 1,
        },
    }
    validation = {
        "result": "pass",
        "summary": {
            "errors": 0,
            "warnings": 0,
            "rule_checks": 10,
            "not_checked_rules": 1,
        },
        "issues": [],
    }
    verdict = clean_review_verdict_from_payload(parsed, validation)
    assert_equal(verdict["FinalVerdict"], "Pass", "clean review final verdict defaults to pass")
    assert_equal(verdict["RuleBasedVerdict"], "Pass", "clean review rule-based verdict defaults to pass")
    assert_equal(verdict["EffectiveFinalVerdict"], "Pass", "clean review effective verdict defaults to pass")
    assert_equal(verdict["EvaluatedStageCount"], 2, "clean review evaluated stage count")
    assert_equal(verdict["EvaluatedRuleCount"], 10, "clean review evaluated rule count")
    assert_equal(verdict["NotCheckedRuleCount"], 1, "clean review optional not-checked count preserved")
    overview = result_overview_text_from_payload("clean-result", parsed)
    assert_true("Final verdict: Pass" in overview, "clean overview final verdict display")
    assert_true("Rule-based verdict: Pass" in overview, "clean overview rule verdict display")
    assert_true("Effective final verdict: Pass" in overview, "clean overview effective verdict display")
    manual = clean_review_verdict_from_payload(
        {
            "Result": "manually_aborted",
            "ExecutionDetail": "manually_aborted",
            "ReportSummary": {
                "Result": "manually_aborted",
                "ExecutionDetail": "manually_aborted",
                "StageOutcomes": [{"Label": "Power", "Verdict": "pass"}],
            },
        },
        validation,
    )
    assert_equal(manual["Reason"], "manual_or_aborted_state", "manual review verdict preserves manual state")
    empty = clean_review_verdict_from_payload({"ReportSummary": {}}, {})
    assert_equal(empty["EffectiveFinalVerdict"], "None", "empty review verdict remains none")


def test_report_stage_summary_builder() -> None:
    stage = build_report_stage_summary(
        {
            "TestDescription": "GPU + VRAM",
            "TestType": "GPU + VRAM",
            "Verdict": "warning",
            "StabilityInterpretation": {
                "OutcomeClass": "worker_verified_non_blocking_warnings",
                "OutcomeSummary": "Review coverage.",
                "PrimaryPurpose": "gpu_stress",
                "BackendConfidence": "worker_verified",
                "TargetedGpuCount": 2,
                "TargetedLoadQualityCounts": {"high": 1, "medium": 1},
                "ThresholdRecommendations": {"WouldWarnCount": 1},
            },
            "GpuExecution": {
                "IntelGpuTopSidecar": {
                    "available": True,
                    "object_count": 2,
                    "aggregate_engine_busy": {"max": 80.0},
                    "engines": {"Render/3D": {"max": 80.0}},
                }
            },
            "GpuMetrics": [
                {
                    "Targeted": True,
                    "GpuIndex": 0,
                    "Name": "GPU A",
                    "DisplayName": "GPU A #1",
                    "Workloads": ["gpu_3d"],
                    "Backends": ["python_vulkan_compute"],
                    "Usage": {"Min": 70.0, "Avg": 90.0, "Max": 100.0},
                    "MemoryUsage": {"Avg": 60.0, "Max": 75.0},
                    "Power": {"Avg": 300.0, "Max": 400.0},
                    "VramUsedGB": {"Avg": 8.0, "Max": 10.0},
                    "WorkerEvidence": {"MaxAllocationPercent": 80.0, "VerificationPasses": 10},
                },
                {
                    "Targeted": True,
                    "GpuIndex": 1,
                    "Name": "GPU B",
                    "Workloads": ["gpu_3d", "vram"],
                },
                {
                    "Targeted": False,
                    "GpuIndex": 2,
                    "Name": "Observed Only",
                },
            ],
        }
    )
    assert_equal(stage["Label"], "GPU + VRAM", "stage summary label fallback")
    assert_equal(stage["TargetedGpuCount"], 2, "stage summary targeted GPU count")
    assert_equal(stage["ReportOnlyThresholdWouldWarnCount"], 1, "stage summary threshold count")
    assert_equal(len(stage["GpuHighlights"]), 2, "stage summary targeted highlights only")
    assert_equal(stage["GpuHighlights"][0]["Name"], "GPU A #1", "stage summary display name")
    assert_equal(stage["GpuHighlights"][0]["PowerMaxW"], 400.0, "stage summary GPU power")
    assert_true("GPU A" in stage["CoverageNotes"][0], "stage summary omitted VRAM coverage note")
    assert_true(stage["IntelGpuTopSidecar"]["Available"], "stage summary nested Intel sidecar")


def test_report_summary_builder() -> None:
    segments = [
        {
            "TestDescription": "GPU Stress",
            "TestType": "3D Adaptive",
            "Verdict": "warning",
            "StabilityInterpretation": {
                "OutcomeClass": "worker_verified_non_blocking_warnings",
                "OutcomeSummary": "Review thermal warning.",
                "PrimaryPurpose": "gpu_stress",
                "BackendConfidence": "worker_verified",
                "TargetedGpuCount": 1,
                "WarningCategoryCounts": {"gpu_thermal_throttle_zone": 1},
                "ErrorCategoryCounts": {},
            },
        }
    ]
    stability_interpretation = {
        "State": "warning",
        "OutcomeClass": "worker_verified_non_blocking_warnings",
        "OutcomeSummary": "Run completed with a thermal warning.",
        "WarningCategoryCounts": {"gpu_thermal_throttle_zone": 1},
        "ErrorCategoryCounts": {"workload_or_system_error": 1},
        "ReportOnlyThresholdWouldWarnCount": 2,
        "ReportOnlyThresholdUnobservedCount": 1,
    }
    report = build_report_summary(
        overall_result="Warning",
        execution_detail="Warning",
        elapsed="00:01:30",
        segments=segments,
        stability_interpretation=stability_interpretation,
        all_error_events=[
            {"severity": "warning", "category": "gpu_thermal_throttle_zone"},
            {"severity": "error", "category": "workload_or_system_error"},
        ],
        gpu_validation_details=[
            {"Status": "ok", "VerificationPasses": 4},
            {"Status": "failed", "ErrorCount": 1, "VerificationPasses": 2},
        ],
        skipped_stages=[{"label": "VRAM", "reason": "not runnable"}],
    )
    assert_equal(report["Schema"], "linux_validation_suite.report_summary.v1", "report summary schema")
    assert_equal(report["Elapsed"], "00:01:30", "report summary elapsed")
    assert_equal(report["WarningCount"], 1, "report summary warning count")
    assert_equal(report["ErrorCount"], 1, "report summary error count")
    assert_equal(report["StageCount"], 1, "report summary stage count")
    assert_equal(report["SkippedStageCount"], 1, "report summary skipped count")
    assert_equal(report["StageOutcomes"][0]["Label"], "GPU Stress", "report summary stage outcome")
    assert_equal(report["GpuWorkerSummary"]["WorkerResultCount"], 2, "report summary worker count")
    assert_equal(report["GpuWorkerSummary"]["SuccessfulWorkerResultCount"], 1, "report summary worker successes")
    assert_equal(report["GpuWorkerSummary"]["WorkerFailureCount"], 1, "report summary worker failures")
    assert_equal(report["GpuWorkerSummary"]["VerificationPasses"], 6, "report summary verification passes")
    assert_equal(report["DepartmentUseSummary"]["Status"], "not_ready", "report summary department status")
    assert_equal(report["ActionItemCategoryCounts"]["skipped_stage"], 1, "report summary skipped action count")
    assert_true(report["ActionItems"], "report summary action messages")


def test_report_export_result_contract_bundle() -> None:
    segments = [
        {
            "TestDescription": "GPU Contract",
            "TestType": "GPU + VRAM",
            "Verdict": "warning",
            "StabilityInterpretation": {
                "OutcomeClass": "worker_verified_telemetry_limited",
                "OutcomeSummary": "Worker verification passed with telemetry caveat.",
                "State": "warning",
                "PrimaryPurpose": "gpu_plus_vram_saturation",
                "BackendConfidence": "worker_verified",
                "TargetedGpuCount": 1,
                "TargetedLoadQualityCounts": {"high": 1},
                "WarningCategoryCounts": {"gpu_vram_telemetry_discrepancy": 1},
                "ErrorCategoryCounts": {},
                "ThresholdRecommendations": {
                    "WouldWarnCount": 1,
                    "Checks": [
                        {
                            "Name": "GPU busy",
                            "Metric": "gpu_busy_percent",
                            "GpuIndex": 0,
                            "ObservedAvgPercent": 88.0,
                            "RecommendedMinAvgPercent": 90.0,
                            "Result": "would_warn",
                        }
                    ],
                },
            },
            "GpuMetrics": [
                {
                    "Targeted": True,
                    "GpuIndex": 0,
                    "Name": "Contract GPU",
                    "DisplayName": "Contract GPU #1",
                    "TargetIds": ["0000:01:00.0"],
                    "Cards": ["card1"],
                    "Slots": ["0000:01:00.0"],
                    "Workloads": ["gpu_3d"],
                    "Backends": ["python_vulkan_compute"],
                    "LoadQuality": "high",
                    "Usage": {"Min": 80.0, "Avg": 94.0, "Max": 99.0},
                    "UsageSustain": {"StdDev": 2.0, "Range": 19.0, "SampleCount": 30},
                    "MemoryUsage": {"Avg": 78.0, "Max": 88.0},
                    "Power": {"Avg": 501.0, "Max": 575.0},
                    "VramUsedGB": {"Avg": 12.0, "Max": 16.0},
                    "WorkerEvidence": {"MaxAllocationPercent": 80.0, "VerificationPasses": 12},
                }
            ],
        }
    ]
    stability = build_overall_stability_interpretation("Warning", segments)
    report = build_report_summary(
        overall_result="Warning",
        execution_detail="FinishedWithWarnings",
        elapsed="00:10:00",
        segments=segments,
        stability_interpretation=stability,
        all_error_events=[
            {
                "severity": "warning",
                "category": "gpu_vram_telemetry_discrepancy",
                "message": "OS telemetry under-reported VRAM allocation.",
            }
        ],
        gpu_validation_details=[
            {
                "Status": "ok",
                "Backend": "python_vulkan_compute",
                "DeviceName": "Contract GPU #1",
                "VerificationPasses": 12,
            }
        ],
        skipped_stages=[{"label": "VRAM", "reason": "backend unavailable"}],
    )
    parsed = {
        "Result": "Warning",
        "Metadata": {
            "Result": "Warning",
            "ProfileName": "Contract Profile",
            "Description": "Report contract fixture",
            "ReportSummary": report,
            "Stability": {"InterpretationSummary": stability},
            "ExportContract": {
                "Schema": "linux_validation_suite.compat_export.v1",
                "CompatibilityMode": "legacy_additive",
                "RequiresLegacyImporterUpdate": False,
            },
        },
        "ExportContract": {
            "Schema": "linux_validation_suite.compat_export.v1",
            "CompatibilityMode": "legacy_additive",
            "RequiresLegacyImporterUpdate": False,
        },
        "StabilityInterpretation": stability,
        "ReportSummary": report,
        "Segments": segments,
        "SegmentDetails": {"segment_1": {"label": "GPU Contract"}},
        "GpuDetails": {"validation_details": []},
        "SystemInfo": {"Hardware": {"Cpu": {"Name": "Contract CPU"}}},
        "Motherboard": {"Product": "Contract Board"},
        "Cpu": {"tests": {}},
        "CpuCores": {"tests": {}},
        "Gpu": {"devices": [], "tests": {}},
        "Memory": {"tests": {}},
        "Storage": {"tests": {}},
    }

    assert_equal(report["Schema"], "linux_validation_suite.report_summary.v1", "contract report summary schema")
    assert_equal(report["ReferenceContract"], "Legacy custom JSON compatible extension", "contract report summary reference")
    for key in (
        "DepartmentUseSummary",
        "StageOutcomes",
        "GpuWorkerSummary",
        "ActionItems",
        "ActionItemDetails",
        "ActionItemCategoryCounts",
        "ActionItemSeverityCounts",
        "ImportNotes",
    ):
        assert_true(key in report, f"contract report summary key {key}")
    assert_equal(report["StageCount"], 1, "contract report stage count")
    assert_equal(report["SkippedStageCount"], 1, "contract report skipped stage count")
    assert_equal(report["StageOutcomes"][0]["Label"], "GPU Contract", "contract stage label")
    assert_equal(report["StageOutcomes"][0]["GpuHighlights"][0]["Name"], "Contract GPU #1", "contract GPU highlight name")
    assert_equal(report["StageOutcomes"][0]["GpuHighlights"][0]["PowerMaxW"], 575.0, "contract GPU highlight power max")
    assert_true(report["StageOutcomes"][0]["CoverageNotes"], "contract stage coverage notes preserved")
    assert_equal(report["GpuWorkerSummary"]["WorkerResultCount"], 1, "contract worker count")
    assert_equal(report["GpuWorkerSummary"]["SuccessfulWorkerResultCount"], 1, "contract worker success count")
    assert_equal(report["GpuWorkerSummary"]["VerificationPasses"], 12, "contract verification pass count")
    assert_equal(report["ActionItemCategoryCounts"]["gpu_vram_telemetry_discrepancy"], 1, "contract VRAM action category")
    assert_equal(report["ActionItemCategoryCounts"]["report_only_threshold_recommendation"], 1, "contract threshold action category")
    assert_equal(report["ActionItemCategoryCounts"]["skipped_stage"], 1, "contract skipped action category")
    assert_equal(parsed["Metadata"]["ReportSummary"], parsed["ReportSummary"], "contract report summary metadata mirror")
    assert_equal(parsed["Metadata"]["ExportContract"], parsed["ExportContract"], "contract export metadata mirror")
    assert_equal(validate_report_summary_mirror(parsed)["issues"], [], "contract report mirror validation")
    assert_equal(validate_report_stage_counts(parsed, report)["issues"], [], "contract stage count validation")
    assert_equal(validate_report_action_items(report)["issues"], [], "contract action item validation")
    assert_equal(validate_stability_alignment(parsed, report)["issues"], [], "contract stability validation")
    assert_equal(validate_export_contract_compatibility(parsed)["issues"], [], "contract export validation")


def test_result_report_text_contract_from_payload() -> None:
    parsed = {
        "Result": "Warning",
        "Metadata": {
            "ProfileName": "Contract Profile",
            "Description": "Result text fixture",
        },
        "ReportSummary": {
            "Result": "Warning",
            "DepartmentUseSummary": {
                "Status": "ready_with_warnings",
                "Decision": "Usable with documented warnings.",
            },
            "GpuWorkerSummary": {
                "WorkerResultCount": 2,
                "SuccessfulWorkerResultCount": 2,
                "WorkerFailureCount": 0,
                "Successful": 2,
                "Failed": 0,
            },
            "StageOutcomes": [
                {
                    "Label": "GPU Contract",
                    "Verdict": "warning",
                    "TestType": "GPU + VRAM",
                    "OutcomeClass": "worker_verified_telemetry_limited",
                    "OutcomeSummary": "Worker verified; telemetry caveat remains.",
                    "WarningCategoryCounts": {"gpu_vram_telemetry_discrepancy": 1},
                    "CoverageNotes": ["Standalone VRAM stage remains authoritative."],
                    "GpuHighlights": [
                        {
                            "Name": "Contract GPU #1",
                            "LoadQuality": "high",
                            "TargetIds": ["0000:01:00.0"],
                            "Workloads": ["gpu_3d"],
                            "Backends": ["python_vulkan_compute"],
                            "UsageMin": 80.0,
                            "UsageAvg": 94.0,
                            "UsageMax": 99.0,
                            "PowerAvgW": 501.0,
                            "PowerMaxW": 575.0,
                            "VramUsedAvgGB": 12.0,
                            "VramUsedMaxGB": 16.0,
                            "AllocationPercent": 80.0,
                            "VerificationPasses": 12,
                        }
                    ],
                }
            ],
            "ActionItemDetails": [
                {
                    "Severity": "info",
                    "Category": "gpu_vram_telemetry_discrepancy",
                    "Stage": "GPU Contract",
                    "Message": "Treat worker verification as authoritative.",
                }
            ],
        },
    }
    overview = result_overview_text_from_payload("ContractFolder", parsed)
    details = result_stage_details_text_from_payload("ContractFolder", parsed)
    assert_true("Result Overview" in overview, "contract overview heading")
    assert_true("Folder: ContractFolder" in overview, "contract overview folder")
    assert_true("Result: Warning" in overview, "contract overview result")
    assert_true("Profile: Contract Profile" in overview, "contract overview profile")
    assert_true("Department status: ready_with_warnings" in overview, "contract overview department status")
    assert_true("GPU workers: 2/2 successful, 0 failed" in overview, "contract overview worker line")
    assert_true("1. GPU Contract: warning (GPU + VRAM, GPUs=1)" in overview, "contract overview stage line")
    assert_true("[info] gpu_vram_telemetry_discrepancy: Treat worker verification as authoritative." in overview, "contract overview action item")
    assert_true("Result Stage Details" in details, "contract details heading")
    assert_true("1. GPU Contract" in details, "contract details stage heading")
    assert_true("Outcome: worker_verified_telemetry_limited" in details, "contract details outcome")
    assert_true("Warnings: {'gpu_vram_telemetry_discrepancy': 1}" in details, "contract details warning counts")
    assert_true("Coverage: Standalone VRAM stage remains authoritative." in details, "contract details coverage")
    assert_true(
        "Contract GPU #1: load=high; target=0000:01:00.0; workloads=gpu_3d; backends=python_vulkan_compute" in details,
        "contract details GPU identity",
    )
    assert_true("usage=80 / 94 / 99%" in details, "contract details usage triplet")
    assert_true("power=avg 501, max 575W" in details, "contract details power pair")
    assert_true("vram=avg 12, max 16GB" in details, "contract details VRAM pair")
    assert_true("alloc=80.0%; verify=12" in details, "contract details worker evidence")


def test_report_export_realistic_trimmed_fixture_contract() -> None:
    fixture_path = ROOT / "smoke_tests" / "fixtures" / "report_export_contract_gpu_troubleshooting_extended_trimmed.json"
    parsed = json.loads(fixture_path.read_text())
    report = parsed["ReportSummary"]
    metadata = parsed["Metadata"]

    assert_equal(parsed["_FixtureSource"], "trimmed retained QA parsed-results fixture", "realistic fixture source")
    assert_equal(parsed["Result"], "Failed", "realistic fixture result")
    assert_equal(parsed["ProfileName"], "GPU Troubleshooting Extended", "realistic fixture profile")
    assert_equal(parsed["ExportContract"]["Schema"], "linux_validation_suite.compat_export.v1", "realistic fixture export schema")
    assert_equal(parsed["ExportContract"]["CompatibilityMode"], "legacy_additive", "realistic fixture export compatibility mode")
    assert_equal(parsed["ExportContract"]["RequiresLegacyImporterUpdate"], False, "realistic fixture importer safety")
    assert_equal(metadata["ReportSummary"], report, "realistic fixture report summary metadata mirror")
    assert_equal(metadata["ExportContract"], parsed["ExportContract"], "realistic fixture export metadata mirror")
    assert_equal(metadata["Stability"]["InterpretationSummary"], parsed["StabilityInterpretation"], "realistic fixture stability metadata mirror")

    stable_fields = validate_export_contract_compatibility(parsed)["checks"]["stable_consumer_fields"]["required"]
    for field in stable_fields:
        assert_true(field in parsed, f"realistic fixture stable top-level field {field}")
    assert_equal(validate_export_contract_compatibility(parsed)["issues"], [], "realistic fixture export validation")
    assert_equal(validate_report_summary_mirror(parsed)["issues"], [], "realistic fixture report mirror validation")
    assert_equal(validate_stability_alignment(parsed, report)["issues"], [], "realistic fixture stability alignment")
    assert_equal(validate_report_stage_counts(parsed, report)["issues"], [], "realistic fixture stage count validation")
    assert_equal(validate_report_action_items(report)["issues"], [], "realistic fixture action item validation")

    assert_equal(report["Schema"], "linux_validation_suite.report_summary.v1", "realistic fixture report schema")
    assert_equal(report["ReferenceContract"], "Legacy custom JSON compatible extension", "realistic fixture reference contract")
    assert_equal(report["StageCount"], 4, "realistic fixture report stage count")
    assert_equal(len(parsed["Segments"]), 4, "realistic fixture segment count")
    assert_equal(len(report["StageOutcomes"]), 4, "realistic fixture stage outcome count")
    assert_equal(report["DepartmentUseSummary"]["Status"], "not_ready", "realistic fixture department status")
    assert_equal(report["GpuWorkerSummary"]["WorkerResultCount"], 9, "realistic fixture worker count")
    validation_payload = build_result_validation_payload(
        Path("realistic_fixture"),
        parsed,
        True,
        lambda _name: True,
    )
    assert_true(
        any(
            issue.get("category") == "worker_results"
            and issue.get("message") == "1 GPU worker(s) failed"
            for issue in validation_payload["issues"]
        ),
        "realistic fixture canonical worker failure validation",
    )
    assert_equal(report["ActionItemCategoryCounts"], {"report_only_threshold_recommendation": 1, "workload_or_system_error": 1}, "realistic fixture action categories")
    assert_equal(report["ActionItemSeverityCounts"], {"error": 1, "info": 1}, "realistic fixture action severities")

    first_stage = report["StageOutcomes"][0]
    assert_equal(first_stage["Label"], "GPU (3D Auto + VRAM)", "realistic fixture first stage label")
    assert_equal(first_stage["Verdict"], "fail", "realistic fixture first stage verdict")
    assert_equal(first_stage["OutcomeClass"], "workload_or_integrity_failure", "realistic fixture first stage outcome")
    assert_equal(first_stage["ErrorCategoryCounts"], {"worker_exit": 2}, "realistic fixture first stage errors")
    assert_equal(first_stage["WarningCategoryCounts"], {"gpu_vram_verification_coverage": 1}, "realistic fixture first stage warnings")
    assert_true("standalone VRAM stage remains" in first_stage["CoverageNotes"][0], "realistic fixture coverage note")
    assert_equal(len(first_stage["GpuHighlights"]), 2, "realistic fixture first stage GPU highlights")
    assert_equal(first_stage["GpuHighlights"][0]["Name"], "NVIDIA GeForce RTX 3080 #1", "realistic fixture first GPU highlight")
    assert_true("vram" in first_stage["GpuHighlights"][0]["Workloads"], "realistic fixture VRAM workload")
    assert_equal(first_stage["GpuHighlights"][0]["PowerMaxW"], 318.54, "realistic fixture GPU power max")
    assert_equal(first_stage["GpuHighlights"][0]["AllocationPercent"], 99.4693, "realistic fixture GPU allocation")

    assert_true("CPU Package (Temperature)" in parsed["Cpu"]["tests"], "realistic fixture CPU temp section")
    assert_true("CPU Package Power (Power)" in parsed["Cpu"]["tests"], "realistic fixture CPU power section")
    assert_true("GPU Temperature (Temperature)" in parsed["Gpu"]["tests"], "realistic fixture GPU temp section")
    assert_true("GPU Power (Power)" in parsed["Gpu"]["tests"], "realistic fixture GPU power section")
    assert_true("GPU VRAM Used (Usage)" in parsed["Gpu"]["tests"], "realistic fixture VRAM usage section")
    assert_true("GPU VRAM Verification Errors (Errors)" in parsed["Gpu"]["tests"], "realistic fixture VRAM error section")
    assert_true("System Memory Used (Usage)" in parsed["Memory"]["tests"], "realistic fixture RAM usage section")
    assert_true("SPD Hub Temperature (Temperature)" in parsed["Memory"]["tests"], "realistic fixture DIMM temp section")
    assert_true("Drive Temperature (Temperature)" in parsed["Storage"]["tests"], "realistic fixture storage temp section")
    assert_equal(
        parsed["Gpu"]["tests"]["GPU Power (Power)"][0]["results"]["GPU (3D Auto + VRAM)"]["max"],
        318.54,
        "realistic fixture GPU power metric",
    )
    assert_equal(
        parsed["Memory"]["tests"]["SPD Hub Temperature (Temperature)"][0]["results"]["VRAM (Vulkan Stateful Memory)"]["max"],
        45.25,
        "realistic fixture memory temp metric",
    )

    overview = result_overview_text_from_payload("realistic_fixture", parsed)
    details = result_stage_details_text_from_payload("realistic_fixture", parsed)
    assert_true("Result: Failed" in overview, "realistic fixture overview result")
    assert_true("Profile: GPU Troubleshooting Extended" in overview, "realistic fixture overview profile")
    assert_true("GPU workers: 8/9 successful, 1 failed" in overview, "realistic fixture overview worker summary")
    assert_true("1. GPU (3D Auto + VRAM): fail (GPU (3D Auto + VRAM), GPUs=2)" in overview, "realistic fixture overview stage")
    assert_true("[error] workload_or_system_error: Review error-level events before treating this run as passing." in overview, "realistic fixture overview action")
    assert_true("Outcome: workload_or_integrity_failure" in details, "realistic fixture details outcome")
    assert_true("Warnings: {'gpu_vram_verification_coverage': 1}" in details, "realistic fixture details warnings")
    assert_true("Errors: {'worker_exit': 2}" in details, "realistic fixture details errors")
    assert_true("NVIDIA GeForce RTX 3080 #1: load=variable_high" in details, "realistic fixture details GPU line")
    assert_true("vram=avg 1.1, max 7.04GB" in details, "realistic fixture details VRAM metric")


def test_stage_diagnostics_stability_fixture_contract() -> None:
    fixture_path = ROOT / "smoke_tests" / "fixtures" / "stage_diagnostics_stability_gpu_troubleshooting_extended_trimmed.json"
    parsed = json.loads(fixture_path.read_text())
    stability = parsed["StabilityInterpretation"]
    metadata_stability = parsed["Metadata"]["Stability"]["InterpretationSummary"]
    report = parsed["ReportSummary"]
    failed_segment = parsed["Segments"][0]
    vram_segment = parsed["Segments"][1]
    failed_interpretation = failed_segment["StabilityInterpretation"]
    vram_interpretation = vram_segment["StabilityInterpretation"]
    failed_outcome = report["StageOutcomes"][0]
    vram_outcome = report["StageOutcomes"][1]

    assert_equal(
        parsed["_FixtureSource"],
        "trimmed retained QA parsed-results fixture",
        "stage diagnostics fixture source",
    )
    assert_equal(metadata_stability, stability, "stage diagnostics metadata stability mirror")
    assert_equal(stability["State"], "unstable", "stage diagnostics top state")
    assert_equal(stability["Result"], "unstable", "stage diagnostics top result")
    assert_equal(stability["OutcomeClass"], "workload_or_integrity_failure", "stage diagnostics top outcome")
    assert_equal(stability["OverallResult"], "Failed", "stage diagnostics overall result")
    assert_equal(stability["SegmentCount"], 4, "stage diagnostics segment count")
    assert_equal(stability["InterpretedSegmentCount"], 4, "stage diagnostics interpreted count")
    assert_equal(stability["StateCounts"], {"stable": 3, "unstable": 1}, "stage diagnostics state counts")
    assert_equal(stability["BackendConfidenceCounts"], {"failed": 1, "high": 2, "validated_explicit": 1}, "stage diagnostics backend confidence counts")
    assert_equal(stability["WarningCategoryCounts"], {"gpu_vram_verification_coverage": 1}, "stage diagnostics warning categories")
    assert_equal(stability["ErrorCategoryCounts"], {"worker_exit": 2}, "stage diagnostics error categories")
    assert_equal(stability["ReportOnlyThresholdWouldWarnCount"], 1, "stage diagnostics would-warn count")
    assert_equal(stability["ReportOnlyThresholdUnobservedCount"], 0, "stage diagnostics unobserved count")
    assert_true(stability["StrictThresholdRecommendationWarningsEnabled"], "stage diagnostics strict recommendation flag")
    first_threshold = stability["ReportOnlyThresholdWouldWarnDetails"][0]
    assert_equal(first_threshold["Segment"], "GPU (3D Auto + VRAM)", "stage diagnostics threshold segment")
    assert_equal(first_threshold["Check"], "target_gpu_busy_saturation", "stage diagnostics threshold check")
    assert_equal(first_threshold["BackendConfidence"], "failed", "stage diagnostics threshold backend confidence")
    assert_equal(first_threshold["Result"], "would_warn", "stage diagnostics threshold result")

    assert_equal(report["Result"], "Failed", "stage diagnostics report result")
    assert_equal(report["State"], "unstable", "stage diagnostics report state")
    assert_equal(report["OutcomeClass"], stability["OutcomeClass"], "stage diagnostics report outcome mirror")
    assert_equal(report["WarningCategoryCounts"], stability["WarningCategoryCounts"], "stage diagnostics report warning mirror")
    assert_equal(report["ErrorCategoryCounts"], stability["ErrorCategoryCounts"], "stage diagnostics report error mirror")
    assert_equal(report["ReportOnlyThresholdWouldWarnCount"], stability["ReportOnlyThresholdWouldWarnCount"], "stage diagnostics report threshold mirror")
    assert_equal(report["ActionItemCategoryCounts"], {"report_only_threshold_recommendation": 1, "workload_or_system_error": 1}, "stage diagnostics action category counts")
    assert_equal(report["ActionItemSeverityCounts"], {"error": 1, "info": 1}, "stage diagnostics action severity counts")
    assert_equal(
        [(item["Severity"], item["Category"], item["Count"], item["Source"]) for item in report["ActionItemDetails"]],
        [
            ("error", "workload_or_system_error", 2, "report_summary"),
            ("info", "report_only_threshold_recommendation", 1, "report_summary"),
        ],
        "stage diagnostics action item details",
    )

    assert_equal(failed_segment["Label"], failed_outcome["Label"], "failed stage label mirror")
    assert_equal(failed_segment["Verdict"], failed_outcome["Verdict"], "failed stage verdict mirror")
    assert_equal(failed_interpretation["BackendConfidence"], "failed", "failed stage backend confidence")
    assert_equal(failed_interpretation["OutcomeClass"], "workload_or_integrity_failure", "failed stage outcome")
    assert_equal(failed_interpretation["State"], "unstable", "failed stage state")
    assert_equal(failed_interpretation["WarningCategoryCounts"], {"gpu_vram_verification_coverage": 1}, "failed stage warning categories")
    assert_equal(failed_interpretation["ErrorCategoryCounts"], {"worker_exit": 2}, "failed stage error categories")
    assert_equal(failed_interpretation["TargetedGpuCount"], 2, "failed stage targeted GPU count")
    assert_equal(failed_interpretation["TargetedLoadQualityCounts"], {"sustained_extreme": 1, "variable_high": 1}, "failed stage load quality")
    assert_equal(failed_interpretation["BackendLoadClasses"], ["high_load"], "failed stage backend load classes")
    assert_true(failed_interpretation["BackendRecommendedForSaturation"], "failed stage backend recommendation")
    assert_equal(failed_outcome["BackendConfidence"], failed_interpretation["BackendConfidence"], "failed outcome backend mirror")
    assert_equal(failed_outcome["OutcomeClass"], failed_interpretation["OutcomeClass"], "failed outcome class mirror")
    assert_equal(failed_outcome["WarningCategoryCounts"], failed_interpretation["WarningCategoryCounts"], "failed outcome warning mirror")
    assert_equal(failed_outcome["ErrorCategoryCounts"], failed_interpretation["ErrorCategoryCounts"], "failed outcome error mirror")
    assert_true(bool(failed_outcome["CoverageNotes"]), "failed outcome coverage note")
    failed_thresholds = failed_interpretation["ThresholdRecommendations"]
    assert_equal(failed_thresholds["Mode"], "report_only", "failed stage threshold mode")
    assert_equal(failed_thresholds["WouldWarnCount"], 1, "failed stage threshold would-warn")
    assert_equal(failed_thresholds["WorkerVerifiedNoTelemetryCount"], 0, "failed stage no-telemetry count")
    assert_equal(failed_thresholds["StrictModeEffect"], "none", "failed stage strict effect")
    failed_busy_check = failed_thresholds["Checks"][0]
    assert_equal(failed_busy_check["Result"], "would_warn", "failed busy check result")
    assert_equal(failed_busy_check["WorkerEvidence"]["WorkerErrorCount"], 2, "failed busy check worker errors")
    assert_equal(failed_busy_check["WorkerEvidence"]["SuccessfulWorkerResultCount"], 1, "failed busy check worker success count")
    assert_true("vram worker exited early with code 12" in failed_interpretation["Reasons"], "failed stage reason preserves worker exit")

    assert_equal(vram_segment["Label"], vram_outcome["Label"], "VRAM stage label mirror")
    assert_equal(vram_segment["Verdict"], "pass", "VRAM stage verdict")
    assert_equal(vram_interpretation["BackendConfidence"], "validated_explicit", "VRAM stage backend confidence")
    assert_equal(vram_interpretation["OutcomeClass"], "verified_clean", "VRAM stage outcome")
    assert_equal(vram_interpretation["PrimaryPurpose"], "vulkan_memory_path_validation", "VRAM stage purpose")
    assert_equal(vram_interpretation["State"], "stable", "VRAM stage state")
    assert_equal(vram_interpretation["WarningCategoryCounts"], {}, "VRAM stage warning categories")
    assert_equal(vram_interpretation["ErrorCategoryCounts"], {}, "VRAM stage error categories")
    assert_equal(vram_outcome["BackendConfidence"], vram_interpretation["BackendConfidence"], "VRAM outcome backend mirror")
    assert_equal(vram_outcome["OutcomeClass"], vram_interpretation["OutcomeClass"], "VRAM outcome class mirror")
    vram_thresholds = vram_interpretation["ThresholdRecommendations"]
    assert_equal(vram_thresholds["WouldWarnCount"], 0, "VRAM threshold would-warn")
    assert_equal(vram_thresholds["WorkerVerifiedNoTelemetryCount"], 1, "VRAM worker-verified no-telemetry count")
    no_telemetry_check = vram_thresholds["Checks"][1]
    assert_equal(no_telemetry_check["Result"], "telemetry_unobserved_worker_verified", "VRAM no-telemetry check result")
    assert_equal(no_telemetry_check["ObservedAvgPercent"], None, "VRAM no-telemetry observed average")
    assert_equal(no_telemetry_check["WorkerEvidence"]["WorkerErrorCount"], 0, "VRAM no-telemetry worker errors")
    assert_equal(no_telemetry_check["WorkerEvidence"]["SuccessfulWorkerResultCount"], 1, "VRAM no-telemetry worker success")
    assert_equal(no_telemetry_check["WorkerEvidence"]["Backends"], ["python_vulkan_compute"], "VRAM no-telemetry backend")


def test_overall_stability_interpretation_builder() -> None:
    segments = [
        {
            "TestDescription": "GPU Stress",
            "StabilityInterpretation": {
                "State": "warning",
                "PrimaryPurpose": "gpu_stress",
                "BackendConfidence": "worker_verified",
                "WarningCategoryCounts": {"gpu_thermal_throttle_zone": 1},
                "ErrorCategoryCounts": {},
                "SaturationCandidate": True,
                "ThresholdRecommendations": {
                    "StrictModeEnabled": True,
                    "WouldWarnCount": 1,
                    "UnobservedCount": 1,
                    "Checks": [
                        {
                            "Name": "GPU busy",
                            "Metric": "gpu_busy_percent",
                            "GpuIndex": 0,
                            "Target": "0000:01:00.0",
                            "Result": "would_warn",
                            "RecommendedMinAvgPercent": 90,
                            "ObservedAvgPercent": 85,
                        },
                        {
                            "Name": "GPU memory busy",
                            "Metric": "gpu_memory_busy_percent",
                            "GpuIndex": 0,
                            "Target": "0000:01:00.0",
                            "Result": "unobserved",
                        },
                    ],
                },
            },
        },
        {
            "TestType": "VRAM",
            "StabilityInterpretation": {
                "State": "stable",
                "PrimaryPurpose": "vram_integrity",
                "BackendConfidence": "worker_verified",
                "WarningCategoryCounts": {},
                "ErrorCategoryCounts": {},
                "MemoryPathCandidate": True,
            },
        },
    ]
    interpretation = build_overall_stability_interpretation("Warning", segments)
    assert_equal(interpretation["State"], "warning", "overall interpretation state")
    assert_equal(
        interpretation["OutcomeClass"],
        "worker_verified_non_blocking_warnings",
        "overall interpretation outcome class",
    )
    assert_equal(interpretation["SegmentCount"], 2, "overall interpretation segment count")
    assert_equal(interpretation["InterpretedSegmentCount"], 2, "overall interpreted segment count")
    assert_equal(interpretation["StateCounts"], {"stable": 1, "warning": 1}, "overall state counts")
    assert_equal(interpretation["SaturationCandidateCount"], 1, "overall saturation candidates")
    assert_equal(interpretation["MemoryPathCandidateCount"], 1, "overall memory candidates")
    assert_true(
        interpretation["StrictThresholdRecommendationWarningsEnabled"],
        "overall strict threshold enabled",
    )
    assert_equal(interpretation["ReportOnlyThresholdWouldWarnCount"], 1, "overall would-warn count")
    assert_equal(interpretation["ReportOnlyThresholdUnobservedCount"], 1, "overall unobserved count")
    assert_equal(
        interpretation["ReportOnlyThresholdWouldWarnDetails"][0]["Segment"],
        "GPU Stress",
        "overall threshold detail segment",
    )
    aborted = build_overall_stability_interpretation("manually_aborted", [])
    assert_equal(aborted["State"], "manually_aborted", "overall manual abort state")
    assert_equal(aborted["OutcomeClass"], "manually_aborted", "overall manual abort outcome")


def test_manual_abort_export_classification() -> None:
    exporter = CompatibilityExporter()
    event = {
        "timestamp": "2026-05-22T10:00:00-04:00",
        "category": "operator_stop",
        "severity": "warning",
        "stage": "Manual Memory",
        "source": "cli",
        "message": "operator stop requested; saving partial run results",
    }
    window = StageWindow(
        stage_id="segment_1",
        stage_type="Memory",
        display_name="Manual Memory",
        started_iso="2026-05-22T10:00:00-04:00",
        ended_iso="2026-05-22T10:00:05-04:00",
        started_monotonic=0.0,
        ended_monotonic=5.0,
        duration_seconds=5.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="aborted",
        failure_reasons=["operator stop requested; saving partial run results"],
        error_events=[event],
    )
    result = exporter.build(
        RunMetadata(dept="Smoke"),
        "2026-05-22T10:00:00-04:00",
        "2026-05-22T10:00:05-04:00",
        5.0,
        {
            "Hardware": {
                "Cpu": {"Name": "Smoke CPU"},
                "Motherboard": {},
                "Bios": {},
                "Memory": {"Modules": []},
                "Storage": [],
                "Gpu": [],
            },
            "TestInfo": {"TestName": "Manual Abort Smoke", "ProfileName": "Manual Abort Smoke"},
        },
        {
            "Segments": [
                {
                    "Label": "Manual Memory",
                    "TestType": "Manual Memory",
                    "TestTypeDetails": "Memory",
                    "Verdict": "aborted",
                    "StabilityInterpretation": {
                        "State": "manually_aborted",
                        "Result": "manually_aborted",
                        "OutcomeClass": "manually_aborted",
                        "OutcomeSummary": "Stage was stopped by the operator and partial results were saved.",
                    },
                    "GpuMetrics": [],
                }
            ],
            "SegmentDetails": {},
        },
        SimpleNamespace(samples=[], _gpu_sources=[]),
        [window],
    )
    assert_equal(result["Result"], "manually_aborted", "manual abort top-level result")
    assert_equal(result["ExecutionDetail"], "manually_aborted", "manual abort execution detail")
    assert_equal(result["Metadata"]["Result"], "manually_aborted", "manual abort metadata result")
    assert_equal(result["ReportSummary"]["Result"], "manually_aborted", "manual abort report result")
    assert_equal(result["ReportSummary"]["OutcomeClass"], "manually_aborted", "manual abort outcome class")
    assert_equal(result["ReportSummary"]["DepartmentUseSummary"]["Status"], "not_ready", "manual abort department status")
    assert_true(result["ManualAbort"], "manual abort flag")


def test_compatibility_export_helper_classification() -> None:
    pass_window = SimpleNamespace(verdict="pass", error_events=[], system_faults=[])
    warning_window = SimpleNamespace(verdict="warning", error_events=[], system_faults=[])
    fail_window = SimpleNamespace(verdict="fail", error_events=[], system_faults=[])
    aborted_window = SimpleNamespace(verdict="aborted", error_events=[], system_faults=[])
    manual_window = SimpleNamespace(
        verdict="aborted",
        error_events=[{"category": "operator_stop", "severity": "warning"}],
        system_faults=[],
    )
    assert_equal(compatibility_elapsed_string(3661.4), "01:01:01", "compat elapsed string")
    assert_equal(compatibility_overall_result([pass_window]), "Finished", "compat pass result")
    assert_equal(compatibility_overall_result([warning_window]), "Warning", "compat warning result")
    assert_equal(compatibility_overall_result([fail_window]), "Failed", "compat fail result")
    assert_equal(compatibility_overall_result([aborted_window]), "Aborted", "compat aborted result")
    assert_true(run_manually_aborted([manual_window]), "compat manual abort detection")
    assert_equal(compatibility_overall_result([manual_window]), "manually_aborted", "compat manual abort result")
    assert_equal(compatibility_execution_detail("Finished", 1), "FinishedWithSkips", "compat skipped detail")
    cpu_power_limits = {
        "Constraints": [
            {"Name": "long_term", "PowerLimitW": 125.0},
            {"Name": "short_term", "PowerLimitW": 253.75},
        ]
    }
    assert_equal(compatibility_cpu_power_limit_value(cpu_power_limits, "long_term"), "125W", "compat PL1")
    assert_equal(compatibility_cpu_power_limit_value(cpu_power_limits, "short_term"), "253.75W", "compat PL2")
    assert_equal(compatibility_cpu_power_limit_value(cpu_power_limits, "missing"), "", "compat missing PL")


def test_run_verdict_precedence() -> None:
    assert_equal(combine_run_verdict(["pass"]), "pass", "run verdict pass")
    assert_equal(combine_run_verdict(["warning", "fail"]), "fail", "run verdict fail overrides prior warning")
    assert_equal(combine_run_verdict(["fail", "warning"]), "fail", "run verdict fail independent of order")
    assert_equal(combine_run_verdict(["fail", "aborted"]), "aborted", "run verdict abort overrides fail")
    assert_equal(combine_run_verdict(["warning"], run_aborted=True), "aborted", "run verdict run_aborted flag")
    assert_equal(
        combine_run_verdict(["aborted"], manual_abort=True),
        "manually_aborted",
        "run verdict manual abort overrides abort",
    )


def test_run_finalization_helpers() -> None:
    warning_event = {
        "category": "thermal",
        "source": "gpu_0_temp_c",
        "message": "GPU temperature reached warning threshold",
        "severity": "warning",
    }
    error_event = {
        "category": "worker_exit",
        "source": "gpu_3d",
        "message": "gpu_3d worker exited early with code 12",
        "severity": "error",
    }
    operator_event = {
        "category": "operator_stop",
        "source": "cli",
        "message": "operator stop requested",
        "severity": "warning",
    }
    windows = [
        SimpleNamespace(
            verdict="pass",
            error_events=[warning_event],
            system_faults=[],
            failure_reasons=[],
        ),
        SimpleNamespace(
            verdict="pass",
            error_events=[],
            system_faults=[operator_event],
            failure_reasons=[],
        ),
    ]
    plan = [{}, {}]
    result = finalize_run_stage_windows(
        windows,
        plan,
        run_aborted=False,
        stage_sensor_events=lambda window: [warning_event] if window is windows[0] else [],
        stage_faults=lambda window: [error_event] if window is windows[0] else [],
    )
    assert_equal(windows[0].verdict, "fail", "finalizer promotes late error to fail")
    assert_equal(windows[0].failure_reasons, ["gpu_3d worker exited early with code 12"], "finalizer records late error reason")
    assert_equal(plan[0]["verdict"], "fail", "finalizer mirrors verdict into plan")
    assert_equal(len(plan[0]["error_events"]), 1, "finalizer keeps duplicate sensor event out")
    assert_equal(plan[0]["system_faults"], [error_event], "finalizer mirrors late faults")
    assert_true(result.manual_abort, "finalizer detects manual abort event")
    assert_equal(result.overall_verdict, "manually_aborted", "manual abort overrides final run verdict")
    assert_equal(result.warning_events, [warning_event, operator_event], "finalizer warning event list")
    assert_equal(result.error_events, [error_event], "finalizer error event list")


def test_cli_run_event_presenter_helpers() -> None:
    lines = []
    presenter = CliRunEventPresenter(started_iso="2026-06-12T00:00:00", emit=lines.append)
    run_dir = Path("/tmp/lvs-presenter-smoke")
    presenter.run_header("Smoke Profile", run_dir, True)
    presenter.stage_skip("GPU Stage", "blocked backend")
    presenter.run_start("Smoke Profile")
    presenter.cpu_tune_start("CPU Stage", "2026-06-12T00:00:01", "max_power")
    presenter.cpu_tune_end("CPU Stage", "2026-06-12T00:00:02", 1.4, "avx2", " | candidates=avx2:88W")
    presenter.stage_start(
        "GPU Stage",
        "2026-06-12T00:00:03",
        "3D Adaptive",
        "00:01:00",
        "2026-06-12T00:01:03",
        " | cpu=native",
        " | gpu=vulkan",
    )
    presenter.stage_abort("GPU Stage", "2026-06-12T00:00:04", "worker failed")
    presenter.stage_end("GPU Stage", "2026-06-12T00:00:05", 61.2, "fail", 2)
    presenter.operator_stop("GPU Stage", {"timestamp": "2026-06-12T00:00:06"})
    presenter.run_end("2026-06-12T00:01:05", 65.0, "fail", 1)
    presenter.run_complete(run_dir)

    assert_equal(lines[0], "\nRunning profile: Smoke Profile", "presenter run header")
    assert_equal(lines[2], f"Advanced debug logging: {run_dir / 'advanced_debug'}", "presenter debug path")
    assert_true("stage-skip | stage=GPU Stage | reason=blocked backend" in lines[3], "presenter skipped stage")
    assert_true(lines[4].endswith("| run-start | profile=Smoke Profile\n"), "presenter run start")
    assert_true("cpu-tune-start | stage=CPU Stage | policy=max_power" in lines[5], "presenter cpu tune start")
    assert_true("cpu-tune-end | stage=CPU Stage | duration=00:00:01 | selected=avx2" in lines[6], "presenter cpu tune end")
    assert_true("stage-start | stage=GPU Stage | type=3D Adaptive" in lines[7], "presenter stage start")
    assert_true(lines[7].endswith(" | cpu=native | gpu=vulkan"), "presenter stage suffixes")
    assert_true("stage-abort | stage=GPU Stage | reason=worker failed" in lines[8], "presenter stage abort")
    assert_true("stage-end | stage=GPU Stage | actual=00:01:01 | verdict=fail | issues=2" in lines[9], "presenter stage end")
    assert_true("operator-stop | stage=GPU Stage | action=stop-workers-and-save" in lines[10], "presenter operator stop")
    assert_true("run-end | elapsed=00:01:05 | verdict=fail | skipped=1" in lines[11], "presenter run end")
    assert_equal(lines[-3], "Run complete.", "presenter run complete")
    assert_true(lines[-2].endswith("parsed_results_custom.json"), "presenter compatibility path")
    assert_true(lines[-1].endswith("run_summary.txt"), "presenter summary path")


def test_run_bootstrap_artifact_helpers() -> None:
    metadata = RunMetadata(dept="Smoke", case_sku="Fixture", description="Bootstrap", advanced_debug_logging=True)
    profile = ValidationProfile(
        profile_name="Bootstrap Smoke",
        defaults=ProfileDefaults(),
        stages=[
            StageConfig(id="segment_1", name="CPU Stage", duration_seconds=60),
            StageConfig(id="segment_2", name="GPU Stage", duration_seconds=60),
        ],
    )
    preflight = {
        "plan": [
            {"runnable": True, "issues": []},
            {"runnable": False, "issues": ["blocked backend"]},
        ],
        "telemetry_capabilities": {"cpu": {"available": True}},
        "validation": {"errors": [], "warnings": []},
        "strict_threshold_recommendation_warnings": {"enabled": False},
    }
    printed_headers = []
    skipped = []
    run_starts = []

    def collect_system_info(profile_name, segment_labels, profile_file, run_metadata, privileged):
        assert_equal(profile_name, "Bootstrap Smoke", "bootstrap system profile name")
        assert_equal(segment_labels, ["CPU"], "bootstrap effective labels")
        assert_equal(profile_file, "Bootstrap Smoke.json", "bootstrap profile file")
        assert_true(run_metadata is metadata, "bootstrap metadata object")
        assert_equal(privileged, False, "bootstrap privileged flag")
        return {"Hardware": {"Cpu": {"Name": "Smoke CPU"}}, "TestInfo": {"ProfileName": profile_name}}

    with TemporaryDirectory(dir="/tmp") as tmp:
        run_dir = Path(tmp)
        result = bootstrap_run_artifacts(
            app_name="LVS",
            app_version="0.0",
            profile_path=Path("profiles/Bootstrap Smoke.json"),
            profile=profile,
            labels=["CPU", "GPU"],
            metadata=metadata,
            preflight=preflight,
            run_dir=run_dir,
            started_iso="2026-06-12T00:00:00",
            runtime_environment={"LVS_TEST": "1"},
            backends={"cpu_native_helper": True},
            backend_details={"cpu_native_helper": {"available": True}},
            abort_on_fail_threshold=False,
            abort_on_worker_error=True,
            abort_on_system_fault=True,
            abort_run_on_stage_abort=True,
            privileged_helper_enabled=False,
            recovery_report={"attempted": False},
            collect_system_info=collect_system_info,
            print_run_header=lambda profile_name, current_run_dir, debug_enabled: printed_headers.append(
                (profile_name, current_run_dir, debug_enabled)
            ),
            print_stage_skip=lambda label, reason: skipped.append((label, reason)),
            print_run_start=lambda profile_name: run_starts.append(profile_name),
        )
        manifest = JsonStore.read(run_dir / "run_manifest.json", {})
        profile_used = JsonStore.read(run_dir / "profile_used.json", {})
        system_info = JsonStore.read(run_dir / "system_info.json", {})
        debug_manifest = JsonStore.read(run_dir / "advanced_debug" / "advanced_debug_manifest.json", {})
        assert_equal(result.effective_labels, ["CPU"], "bootstrap result effective labels")
        assert_equal(result.effective_profile.stages[1].enabled, False, "bootstrap disables unrunnable stage")
        assert_equal(result.skipped_stages[0]["label"], "GPU", "bootstrap skipped label")
        assert_equal(manifest["segment_labels"], ["CPU"], "bootstrap manifest labels")
        assert_equal(manifest["skipped_stages"][0]["issues"], ["blocked backend"], "bootstrap manifest skipped issues")
        assert_equal(profile_used["stages"][1]["enabled"], False, "bootstrap profile copy disabled stage")
        assert_equal(system_info["Hardware"]["Cpu"]["Name"], "Smoke CPU", "bootstrap system info write")
        assert_equal(printed_headers, [("Bootstrap Smoke", run_dir, True)], "bootstrap run header callback")
        assert_equal(skipped, [("GPU", "blocked backend")], "bootstrap skip callback")
        assert_equal(run_starts, ["Bootstrap Smoke"], "bootstrap run start callback")
        assert_equal(debug_manifest["events"][0]["event"], "run_start", "bootstrap debug run-start event")


def test_run_completion_helpers() -> None:
    calls = []
    run_events = SimpleNamespace(
        run_end=lambda ended_iso, total_elapsed, overall_verdict, skipped_count: calls.append(
            ("run-end", ended_iso, total_elapsed, overall_verdict, skipped_count)
        ),
        run_complete=lambda run_dir: calls.append(("run-complete", run_dir)),
    )
    original_writer = run_completion_module.write_final_run_artifacts

    def fake_writer(**kwargs):
        calls.append(("writer", kwargs))
        fault_events = kwargs["stage_faults"](SimpleNamespace(name="window"))
        calls.append(("fault-events", fault_events))
        return SimpleNamespace(overall_verdict="warning")

    run_completion_module.write_final_run_artifacts = fake_writer
    try:
        result = run_completion_module.complete_validation_run(
            run_dir=Path("/tmp/lvs-completion-smoke"),
            manifest_payload={"profile_name": "Smoke"},
            app_name="LVS",
            app_version="0.0",
            profile=SimpleNamespace(profile_name="Smoke"),
            metadata=SimpleNamespace(description="Smoke"),
            started_iso="2026-06-12T00:00:00",
            started_monotonic=10.0,
            system_info={"Hardware": {"Gpu": []}},
            telemetry=SimpleNamespace(),
            stage_windows=[],
            executed_plan=[],
            recovery_report={},
            skipped_stages=[{"label": "Skipped"}],
            run_aborted=False,
            keep_raw_telemetry=True,
            export_compatibility_json=True,
            export_extended_json=False,
            segment_parser=SimpleNamespace(),
            exporter=SimpleNamespace(),
            summary_exporter=SimpleNamespace(),
            stage_sensor_events=lambda window: [{"category": "sensor"}],
            collect_kernel_faults=lambda started, ended: [{"started": started, "ended": ended}],
            faults_for_stage=lambda faults, window: [{"fault_count": len(faults), "window": getattr(window, "name", "")}],
            capture_run_end=lambda **kwargs: calls.append(("capture-run-end", kwargs)),
            run_events=run_events,
            now_local_iso=lambda: "2026-06-12T00:01:05",
            monotonic=lambda: 75.0,
        )
    finally:
        run_completion_module.write_final_run_artifacts = original_writer

    writer_call = next(call for call in calls if call[0] == "writer")[1]
    assert_equal(result.ended_iso, "2026-06-12T00:01:05", "completion ended timestamp")
    assert_equal(result.total_elapsed, 65.0, "completion elapsed")
    assert_equal(result.overall_verdict, "warning", "completion verdict")
    assert_equal(writer_call["ended_iso"], "2026-06-12T00:01:05", "completion writer ended")
    assert_equal(writer_call["total_elapsed"], 65.0, "completion writer elapsed")
    assert_true(writer_call["keep_raw_telemetry"], "completion writer raw telemetry flag")
    assert_equal(calls[1], ("fault-events", [{"fault_count": 1, "window": "window"}]), "completion faults adapter")
    assert_equal(calls[-2], ("run-end", "2026-06-12T00:01:05", 65.0, "warning", 1), "completion presenter run end")
    assert_equal(calls[-1], ("run-complete", Path("/tmp/lvs-completion-smoke")), "completion presenter run complete")


def test_final_run_artifact_writer_helpers() -> None:
    class FakeTelemetry:
        def __init__(self) -> None:
            self.csv_path = None
            self.samples = []
            self._gpu_sources = []

        def write_csv(self, path: Path) -> None:
            self.csv_path = path
            path.write_text("timestamp,cpu\n", encoding="utf-8")

        def source_map(self) -> dict:
            return {"cpu": {"source": "smoke"}}

    class FakeSegmentParser:
        def summarize(self, stage_windows, telemetry, gpus, cpu_info=None):
            return {"Segments": [{"Label": stage_windows[0].display_name}], "GpuCount": len(gpus), "CpuInfo": cpu_info}

    class FakeExporter:
        def build(self, metadata, started_iso, ended_iso, total_elapsed, system_info, parser_output, telemetry, stage_windows, recovery_report, skipped_stages):
            return {
                "Result": "Finished" if stage_windows[0].verdict == "pass" else "Warning",
                "Metadata": {"ProfileName": metadata.profile_name},
                "ParserOutput": parser_output,
            }

    class FakeSummaryExporter:
        def build(self, compat):
            return f"Result: {compat['Result']}\n"

    window = StageWindow(
        stage_id="segment_1",
        stage_type="CPU Load",
        display_name="CPU Stage",
        started_iso="2026-06-12T00:00:00",
        ended_iso="2026-06-12T00:01:00",
        started_monotonic=0.0,
        ended_monotonic=60.0,
        duration_seconds=60.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="pass",
    )
    plan = [{"stage": "segment_1"}]
    captured = []
    warning_event = {
        "category": "thermal",
        "source": "cpu",
        "message": "warm",
        "severity": "warning",
    }
    with TemporaryDirectory(dir="/tmp") as tmp:
        run_dir = Path(tmp)
        telemetry = FakeTelemetry()
        result = write_final_run_artifacts(
            run_dir=run_dir,
            manifest_payload={"profile_name": "Smoke"},
            app_name="LVS",
            app_version="0.0",
            profile=SimpleNamespace(profile_name="Smoke"),
            metadata=SimpleNamespace(profile_name="Smoke"),
            started_iso="2026-06-12T00:00:00",
            ended_iso="2026-06-12T00:01:00",
            total_elapsed=60.4,
            system_info={"Hardware": {"Gpu": [{"Name": "GPU"}]}},
            telemetry=telemetry,
            stage_windows=[window],
            executed_plan=plan,
            recovery_report={},
            skipped_stages=[],
            run_aborted=False,
            keep_raw_telemetry=True,
            export_compatibility_json=True,
            export_extended_json=False,
            segment_parser=FakeSegmentParser(),
            exporter=FakeExporter(),
            summary_exporter=FakeSummaryExporter(),
            stage_sensor_events=lambda stage_window: [warning_event],
            stage_faults=lambda stage_window: [],
            capture_run_end=lambda **kwargs: captured.append(dict(kwargs)),
        )
        manifest = JsonStore.read(run_dir / "run_manifest.json", {})
        parsed = JsonStore.read(run_dir / "parsed_results_custom.json", {})
        source_map = JsonStore.read(run_dir / "telemetry_source_map.json", {})
        assert_equal(result.overall_verdict, "warning", "artifact writer final verdict")
        assert_equal(manifest["verdict"], "warning", "artifact writer manifest verdict")
        assert_equal(plan[0]["verdict"], "warning", "artifact writer mirrors final plan verdict")
        assert_equal(parsed["ParserOutput"]["GpuCount"], 1, "artifact writer parsed export")
        assert_equal((run_dir / "run_summary.txt").read_text(encoding="utf-8"), "Result: Warning\n", "artifact writer summary")
        assert_true((run_dir / "raw_telemetry.csv").exists(), "artifact writer raw telemetry")
        assert_equal(source_map["cpu"]["source"], "smoke", "artifact writer telemetry source map")
        assert_equal(captured[0]["verdict"], "warning", "artifact writer captures run end before return")

    class ManualAbortSegmentParser:
        def summarize(self, stage_windows, telemetry, gpus, cpu_info=None):
            stage_window = stage_windows[0]
            return {
                "Segments": [
                    {
                        "Label": stage_window.display_name,
                        "TestType": stage_window.stage_type,
                        "TestTypeDetails": stage_window.stage_type,
                        "Verdict": stage_window.verdict,
                        "StabilityInterpretation": {
                            "State": "manually_aborted",
                            "Result": "manually_aborted",
                            "OutcomeClass": "manually_aborted",
                            "OutcomeSummary": "Stage was stopped by the operator and partial results were saved.",
                        },
                        "GpuMetrics": [],
                    }
                ],
                "SegmentDetails": {},
            }

    manual_stop_event = {
        "timestamp": "2026-06-12T00:00:05",
        "category": "operator_stop",
        "severity": "warning",
        "stage": "TUI Cancel Stage",
        "source": "tui",
        "message": "operator stop requested; saving partial run results",
    }
    manual_window = StageWindow(
        stage_id="segment_1",
        stage_type="GPU",
        display_name="TUI Cancel Stage",
        started_iso="2026-06-12T00:00:00",
        ended_iso="2026-06-12T00:00:05",
        started_monotonic=0.0,
        ended_monotonic=5.0,
        duration_seconds=5.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="aborted",
        failure_reasons=["operator stop requested; saving partial run results"],
        error_events=[manual_stop_event],
    )
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        run_dir = root / "tui-cancel-artifacts"
        run_dir.mkdir()
        telemetry = FakeTelemetry()
        manual_plan = [{"stage": "segment_1"}]
        manual_result = write_final_run_artifacts(
            run_dir=run_dir,
            manifest_payload={"profile_name": "TUI Cancel Smoke"},
            app_name="LVS",
            app_version="0.0",
            profile=SimpleNamespace(profile_name="TUI Cancel Smoke"),
            metadata=RunMetadata(dept="Smoke", case_sku="Cancel Case", description="TUI Cancel Smoke"),
            started_iso="2026-06-12T00:00:00",
            ended_iso="2026-06-12T00:00:05",
            total_elapsed=5.0,
            system_info={
                "Hardware": {
                    "Cpu": {"Name": "Smoke CPU"},
                    "Motherboard": {},
                    "Bios": {},
                    "Memory": {"Modules": []},
                    "Storage": [],
                    "Gpu": [],
                },
                "TestInfo": {"TestName": "TUI Cancel Smoke", "ProfileName": "TUI Cancel Smoke"},
            },
            telemetry=telemetry,
            stage_windows=[manual_window],
            executed_plan=manual_plan,
            recovery_report={},
            skipped_stages=[],
            run_aborted=True,
            keep_raw_telemetry=True,
            export_compatibility_json=True,
            export_extended_json=False,
            segment_parser=ManualAbortSegmentParser(),
            exporter=CompatibilityExporter(),
            summary_exporter=RunSummaryTextExporter(),
            stage_sensor_events=lambda stage_window: [],
            stage_faults=lambda stage_window: [],
            capture_run_end=lambda **kwargs: None,
        )
        manifest = JsonStore.read(run_dir / "run_manifest.json", {})
        parsed = JsonStore.read(run_dir / "parsed_results_custom.json", {})
        assert_equal(manual_result.overall_verdict, "manually_aborted", "TUI cancel artifact final verdict")
        assert_equal(manifest["verdict"], "manually_aborted", "TUI cancel manifest verdict")
        assert_equal(manifest["executed_plan"][0]["verdict"], "aborted", "TUI cancel plan stage verdict")
        assert_equal(
            manifest["stage_windows"][0]["error_events"][0]["category"],
            "operator_stop",
            "TUI cancel manifest keeps operator stop event",
        )
        assert_equal(parsed["Result"], "manually_aborted", "TUI cancel parsed result")
        assert_equal(parsed["ExecutionDetail"], "manually_aborted", "TUI cancel parsed execution detail")
        assert_true(parsed["ManualAbort"], "TUI cancel parsed manual abort flag")
        assert_equal(parsed["ReportSummary"]["OutcomeClass"], "manually_aborted", "TUI cancel report summary outcome")
        assert_true((run_dir / "run_summary.txt").exists(), "TUI cancel summary generated")
        assert_true((run_dir / "raw_telemetry.csv").exists(), "TUI cancel raw telemetry generated")
        assert_true((run_dir / "telemetry_source_map.json").exists(), "TUI cancel telemetry source map generated")

        service = SuiteAppService.__new__(SuiteAppService)
        service.summary_exporter = RunSummaryTextExporter()
        service.result_validation = ResultValidationFacade(root)
        service.result_comparison = ResultComparisonFacade()
        service.pre_import_sanity = PreImportSanityFacade(root, service.result_validation, service.summary_exporter)
        service.result_artifacts = ResultArtifactFacade(root)
        qa_payload = service.qa_result_review_payload(run_dir, refresh_summary=False)
        assert_equal(qa_payload["identity"]["result"], "manually_aborted", "TUI cancel QA identity result")
        assert_equal(qa_payload["identity"]["outcome_class"], "manually_aborted", "TUI cancel QA outcome class")
        assert_equal(qa_payload["artifact_availability"]["kind"], "run_result", "TUI cancel QA artifact kind")


def test_egl_gles_worker_script_builder() -> None:
    script = build_egl_gles_workload_script(
        "gpu_3d",
        target_vram_bytes=0,
        worker_params={"result_file": "/tmp/egl_worker_result.json"},
    )
    compile(script, "<egl_gles_worker>", "exec")
    assert_true("verify_dynamic_marker" in script, "EGL/GLES worker dynamic marker verification")
    assert_true("draw_checksum_stall_count" in script, "EGL/GLES worker checksum stall evidence")


def test_workload_runner_egl_probe_script_available() -> None:
    script = WorkloadRunner()._egl_probe_script()
    compile(script, "<egl_probe>", "exec")
    assert_true("egl_device_exact_match" in script, "WorkloadRunner exposes EGL target probe script")
    assert_true("eglGetPlatformDisplayEXT" in script, "EGL probe can select platform display")


def test_egl_runtime_discovery_helpers() -> None:
    assert_true(is_software_renderer("Mesa llvmpipe"), "EGL identifies llvmpipe")
    assert_true(not is_software_renderer("NVIDIA RTX 5090"), "EGL accepts hardware renderer")

    no_runtime = probe_egl_runtime_backend(
        python_runtime="",
        probe_script="probe",
        preferred_target=None,
        command_env=lambda env: dict(env or {}),
    )
    assert_equal(no_runtime["reason"], "python runtime unavailable", "EGL missing Python reason")

    target = {"card": "card1", "dri_prime": "pci-0000_01_00_0"}
    env_calls = []

    def command_env(extra_env):
        env_calls.append(dict(extra_env or {}))
        return dict(extra_env or {})

    def successful_run(command, **kwargs):
        assert_equal(command, ["python3", "-c", "probe"], "EGL runtime probe command")
        assert_equal(kwargs["timeout"], 8, "EGL runtime probe timeout")
        return SimpleNamespace(
            stdout=json.dumps({"available": True, "renderer": "NVIDIA RTX 5090", "vendor": "NVIDIA"}),
            stderr="",
            returncode=0,
        )

    successful = probe_egl_runtime_backend(
        python_runtime="python3",
        probe_script="probe",
        preferred_target=target,
        command_env=command_env,
        run_command=successful_run,
        environment={"BASE": "1"},
    )
    assert_equal(successful["available"], True, "EGL runtime successful probe")
    assert_equal(successful["renderer"], "NVIDIA RTX 5090", "EGL runtime renderer")
    assert_equal(successful["target_gpu"], "card1", "EGL runtime target card")
    assert_equal(successful["target_dri_prime"], "pci-0000_01_00_0", "EGL runtime target selector")
    assert_equal(env_calls[0]["DRI_PRIME"], "pci-0000_01_00_0", "EGL runtime target environment")

    software = probe_egl_runtime_backend(
        python_runtime="python3",
        probe_script="probe",
        preferred_target=None,
        command_env=command_env,
        run_command=lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps({"available": True, "renderer": "llvmpipe", "vendor": "Mesa"}),
            stderr="",
            returncode=0,
        ),
        environment={},
    )
    assert_equal(software["available"], False, "EGL software renderer unavailable")
    assert_equal(software["reason"], "software renderer detected: llvmpipe", "EGL software renderer reason")

    malformed = probe_egl_runtime_backend(
        python_runtime="python3",
        probe_script="probe",
        preferred_target=None,
        command_env=command_env,
        run_command=lambda *_args, **_kwargs: SimpleNamespace(stdout="not json", stderr="probe stderr", returncode=2),
        environment={},
    )
    assert_equal(malformed["available"], False, "EGL malformed probe unavailable")
    assert_equal(malformed["reason"], "probe stderr", "EGL malformed probe reason")

    failed = probe_egl_runtime_backend(
        python_runtime="python3",
        probe_script="probe",
        preferred_target=None,
        command_env=command_env,
        run_command=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        environment={},
    )
    assert_equal(failed["reason"], "probe failed: boom", "EGL probe exception reason")


def test_opencl_compute_worker_script_builder() -> None:
    script = build_opencl_compute_workload_script(
        target_vendor="nvidia",
        target_vendor_id="10de",
        target_name="RTX 5090",
        target_card="/dev/dri/card1",
        target_slot="0000:01:00.0",
        target_id="0000:01:00.0",
        target_gpu_index=0,
        target_vram_total=24 * 1024 * 1024 * 1024,
        compute_variant="baseline",
        worker_params={"result_file": "/tmp/opencl_compute_worker_result.json", "safe_mode_enabled": True},
    )
    compile(script, "<opencl_compute_worker>", "exec")
    assert_true("score_device" in script, "OpenCL compute worker target scoring")
    assert_true("safe_runtime_limits" in script, "OpenCL compute worker safe runtime limits")
    assert_true("verify_buffer" in script, "OpenCL compute worker buffer verification")


def test_opencl_vram_worker_script_builder() -> None:
    script = build_opencl_vram_workload_script(
        8 * 1024 * 1024 * 1024,
        "nvidia",
        "10de",
        "RTX 5090",
        "/dev/dri/card1",
        "0000:01:00.0",
        "0000:01:00.0",
        0,
        24 * 1024 * 1024 * 1024,
        worker_params={"result_file": "/tmp/opencl_vram_worker_result.json", "safe_mode_enabled": True},
        result_file="/tmp/opencl_vram_worker_result.json",
    )
    compile(script, "<opencl_vram_worker>", "exec")
    assert_true("device_score" in script, "OpenCL VRAM worker target scoring")
    assert_true("clCreateBuffer" in script, "OpenCL VRAM worker allocation path")
    assert_true("clEnqueueReadBuffer" in script, "OpenCL VRAM worker buffer readback")
    assert_true("vram_mismatch_count" in script, "OpenCL VRAM worker mismatch verification")


def test_opencl_probe_script_builder() -> None:
    script = build_opencl_probe_script()
    compile(script, "<opencl_probe_script>", "exec")
    assert_true("resolve_opencl_library" in script, "OpenCL probe library resolver")
    assert_true("CL_DEVICE_PCI_BUS_INFO_KHR" in script, "OpenCL probe PCI slot query")
    assert_true("duplicate_group_size" in script, "OpenCL probe duplicate device grouping")


def test_opencl_targeting_helpers() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        etc_vendor = root / "etc" / "OpenCL" / "vendors"
        usr_vendor = root / "usr" / "share" / "OpenCL" / "vendors"
        etc_vendor.mkdir(parents=True)
        usr_vendor.mkdir(parents=True)
        (etc_vendor / "nvidia.icd").write_text("libnvidia-opencl.so\n", encoding="utf-8")
        (usr_vendor / "intel.icd").write_text("libintelocl.so\n", encoding="utf-8")
        (usr_vendor / "rusticl.icd").write_text("libMesaOpenCL.so\n", encoding="utf-8")
        icds = opencl_discover_icds([etc_vendor, usr_vendor])
        assert_equal([icd["vendor_hint"] for icd in icds], ["nvidia", "intel", "rusticl"], "OpenCL ICD discovery")
        assert_equal(opencl_find_icd(icds, ["nvidia"])["vendor_hint"], "nvidia", "OpenCL find NVIDIA ICD")

        nvidia_envs = opencl_env_candidates_for_target({"vendor": "NVIDIA", "vendor_id": "10de"}, icds)
        assert_equal(nvidia_envs, [{"context": "icd_nvidia", "env": {"OCL_ICD_VENDORS": str(etc_vendor / "nvidia.icd")}}], "NVIDIA ICD env")
        intel_envs = opencl_env_candidates_for_target({"vendor": "Intel", "vendor_id": "8086"}, icds)
        assert_equal([env["context"] for env in intel_envs], ["icd_intel", "rusticl_iris"], "Intel OpenCL env order")
        amd_envs = opencl_env_candidates_for_target({"vendor": "AMD", "vendor_id": "1002"}, icds)
        assert_equal(amd_envs[0]["context"], "rusticl_radeonsi", "AMD Rusticl env fallback")

    no_rusticl_due_override = opencl_runtime_context_candidates(
        env_overrides={"RUSTICL_ENABLE": "radeonsi"},
        gpu_cards=[{"vendor": "AMD"}],
        native_probe={"reason": "no OpenCL GPU devices found", "platforms": []},
    )
    assert_equal(no_rusticl_due_override, [{"context": "native", "env": {}}], "OpenCL respects explicit Rusticl env")
    rusticl_fallback = opencl_runtime_context_candidates(
        env_overrides={},
        gpu_cards=[{"vendor": "AMD"}],
        native_probe={"reason": "no OpenCL GPU devices found", "platforms": []},
    )
    assert_equal(rusticl_fallback[-1]["context"], "rusticl_radeonsi", "OpenCL Rusticl fallback context")

    devices: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    probe = {
        "context": "icd_nvidia",
        "devices": [
            {"vendor_id": "10de", "pci_slot": "0000:01:00.0", "name": "RTX", "global_mem_bytes": 100, "platform_name": "NVIDIA"},
            {"vendor_id": "10de", "pci_slot": "0000:01:00.0", "name": "RTX", "global_mem_bytes": 100, "platform_name": "NVIDIA"},
        ],
    }
    append_opencl_probe_devices(devices, probe, {"OCL_ICD_VENDORS": "nvidia.icd"}, seen)
    assert_equal(len(devices), 1, "OpenCL append de-duplicates devices")
    assert_equal(devices[0]["probe_context"], "icd_nvidia", "OpenCL append tags probe context")
    assert_equal(
        opencl_device_identity_key(devices[0], devices[0]["required_env"])[0],
        "10de",
        "OpenCL identity normalizes vendor",
    )
    assert_true("nvidia corporation" in gpu_vendor_aliases("10de"), "OpenCL vendor aliases")
    assert_true(gpu_vendor_matches_text("1002", "Advanced Micro Devices, Inc.", "Radeon"), "OpenCL vendor text match")
    assert_true(not gpu_vendor_matches_text("nvidia", "Intel Arc"), "OpenCL vendor text mismatch")


def test_opencl_runtime_discovery_helpers() -> None:
    no_runtime = probe_opencl_runtime_context(
        context_name="native",
        extra_env={},
        python_runtime="",
        probe_script="probe",
        command_env=lambda *_args, **_kwargs: {},
    )
    assert_equal(no_runtime["reason"], "python runtime unavailable", "OpenCL runtime missing Python reason")
    assert_equal(no_runtime["selected_env"], {}, "OpenCL runtime missing Python env")

    env_calls: List[Dict[str, Any]] = []

    def command_env(extra_env: Dict[str, str], **kwargs: Any) -> Dict[str, str]:
        env_calls.append({"extra_env": dict(extra_env), **kwargs})
        return {"BASE": "1", **extra_env}

    payload = {
        "available": True,
        "library": "libOpenCL.so.1",
        "platform_count": 1,
        "platforms": [{"name": "Test OpenCL"}],
        "devices": [{"name": "GPU A", "vendor_id": "1002", "global_mem_bytes": 1024}],
    }

    def successful_run(command: List[str], **_kwargs: Any) -> SimpleNamespace:
        assert_equal(command, ["python3", "-c", "probe"], "OpenCL runtime probe command")
        return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    successful = probe_opencl_runtime_context(
        context_name="rusticl_radeonsi",
        extra_env={"RUSTICL_ENABLE": "radeonsi"},
        python_runtime="python3",
        probe_script="probe",
        command_env=command_env,
        run_command=successful_run,
    )
    assert_equal(successful["available"], True, "OpenCL runtime successful probe")
    assert_equal(successful["devices"][0]["name"], "GPU A", "OpenCL runtime probe device")
    assert_equal(successful["selected_env"], {"RUSTICL_ENABLE": "radeonsi"}, "OpenCL runtime selected env")
    assert_equal(
        env_calls[0]["unset_keys"],
        ["RUSTICL_ENABLE", "OCL_ICD_VENDORS"],
        "OpenCL runtime clears compatibility env",
    )

    failed = probe_opencl_runtime_context(
        context_name="native",
        extra_env={},
        python_runtime="python3",
        probe_script="probe",
        command_env=command_env,
        run_command=lambda *_args, **_kwargs: SimpleNamespace(stdout="not json", stderr="probe stderr", returncode=2),
    )
    assert_equal(failed["available"], False, "OpenCL runtime malformed probe unavailable")
    assert_equal(failed["reason"], "probe stderr", "OpenCL runtime malformed probe reason")

    fallback_probes = {
        "native": {
            "available": False,
            "reason": "no OpenCL GPU devices found",
            "devices": [],
            "context": "native",
            "selected_env": {},
            "platform_count": 1,
            "platforms": [],
        },
        "rusticl_radeonsi": {
            "available": True,
            "reason": "",
            "devices": [{"name": "GPU A", "vendor_id": "1002", "global_mem_bytes": 1024}],
            "context": "rusticl_radeonsi",
            "selected_env": {"RUSTICL_ENABLE": "radeonsi"},
            "platform_count": 1,
            "platforms": [],
        },
    }
    fallback = discover_opencl_backend(
        probe_attempt=lambda context, _env: dict(fallback_probes[context]),
        runtime_context_candidates=lambda _probe: [
            {"context": "native", "env": {}},
            {"context": "rusticl_radeonsi", "env": {"RUSTICL_ENABLE": "radeonsi"}},
        ],
        gpu_cards=[{"name": "GPU A"}],
        discover_icds=lambda: [],
        best_device_for_target=lambda devices, _target: devices[0] if devices else None,
        env_candidates_for_target=lambda _target, _icds: [],
        device_identity_key=opencl_device_identity_key,
        append_probe_devices=append_opencl_probe_devices,
    )
    assert_equal(fallback["selected_context"], "rusticl_radeonsi", "OpenCL runtime fallback context")
    assert_equal(fallback["devices"][0]["required_env"], {"RUSTICL_ENABLE": "radeonsi"}, "OpenCL runtime fallback device env")
    assert_equal(len(fallback["probe_attempts"]), 2, "OpenCL runtime fallback attempts")

    mixed_probes = {
        "native": {
            "available": True,
            "reason": "",
            "devices": [{"name": "GPU A", "vendor_id": "8086", "global_mem_bytes": 1024}],
            "context": "native",
            "selected_env": {},
            "platform_count": 1,
            "platforms": [],
        },
        "icd_nvidia": {
            "available": True,
            "reason": "",
            "devices": [{"name": "GPU B", "vendor_id": "10de", "global_mem_bytes": 2048}],
            "context": "icd_nvidia",
            "selected_env": {"OCL_ICD_VENDORS": "nvidia.icd"},
            "platform_count": 1,
            "platforms": [],
        },
    }

    def best_named_device(devices: List[Dict[str, Any]], target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return next((device for device in devices if device.get("name") == target.get("name")), None)

    mixed = discover_opencl_backend(
        probe_attempt=lambda context, _env: dict(mixed_probes[context]),
        runtime_context_candidates=lambda _probe: [{"context": "native", "env": {}}],
        gpu_cards=[{"name": "GPU A"}, {"name": "GPU B"}],
        discover_icds=lambda: [{"path": "nvidia.icd"}],
        best_device_for_target=best_named_device,
        env_candidates_for_target=lambda target, _icds: (
            [{"context": "icd_nvidia", "env": {"OCL_ICD_VENDORS": "nvidia.icd"}}]
            if target.get("name") == "GPU B"
            else []
        ),
        device_identity_key=opencl_device_identity_key,
        append_probe_devices=append_opencl_probe_devices,
    )
    assert_equal(mixed["selected_context"], "mixed_per_target", "OpenCL runtime mixed context")
    assert_equal([device["opencl_index"] for device in mixed["devices"]], [0, 1], "OpenCL runtime mixed indexes")
    assert_equal(len(mixed["probe_attempts"]), 2, "OpenCL runtime mixed attempts")

    safety = opencl_compute_safety_profile(True)
    assert_equal(safety["safe_mode_enabled"], True, "OpenCL runtime safety enabled")
    assert_equal(safety["high_headroom_discrete_cap"]["enabled"], True, "OpenCL runtime high-headroom cap")
    assert_equal(safety["integer_mix_high_headroom_discrete_cap"]["work_items_cap"], 1 << 20, "OpenCL runtime integer cap")


def test_external_gpu_supervisor_script_builder() -> None:
    script = build_external_gpu_supervisor_script(
        backend="glmark2",
        child_command=["glmark2", "--off-screen"],
        child_env={"LVS_TEST_ENV": "1"},
        target={"target_id": "0000:01:00.0", "slot": "0000:01:00.0", "card": "/dev/dri/card1", "gpu_index": 0},
        target_process_count=2,
        ramp_step_seconds=15.0,
        start_load_fraction=0.35,
        resolved_device_name="",
        selection_ambiguous=False,
        result_file="/tmp/external_gpu_supervisor_result.json",
    )
    compile(script, "<external_gpu_supervisor>", "exec")
    assert_true("desired_process_count" in script, "external GPU supervisor process ramp")
    assert_true("child_failure_count" in script, "external GPU supervisor child failure tracking")
    assert_true("compatibility_backend" in script, "external GPU supervisor compatibility flag")


def test_compatibility_export_metric_helpers() -> None:
    gpu_segment = {
        "TestType": "GPU Smoke",
        "Temperatures": {
            "Gpu": {
                "Core": {
                    "Gpus": [
                        {
                            "DisplayName": "RTX 5090 #1",
                            "SensorName": "core",
                            "Temperatures": {"Max": 75.0, "Avg": 70.0, "Min": 65.0},
                        }
                    ]
                }
            }
        },
        "GpuMetrics": [
            {
                "DisplayName": "RTX 5090 #1",
                "Power": {"Max": 575.0, "Avg": 525.0, "Min": 120.0},
            }
        ],
    }
    assert_equal(gpu_temp_export_name({"GpuIndex": 2, "SensorName": "edge"}), "GPU 2 [edge]", "compat GPU temp name")
    assert_equal(
        build_gpu_temp_test([gpu_segment], "Core")[0]["device"],
        "RTX 5090 #1 [core]",
        "compat GPU temp test device",
    )
    assert_equal(
        build_gpu_metric_test([gpu_segment], "Power")[0]["results"]["GPU Smoke"]["max"],
        575.0,
        "compat GPU metric test max",
    )
    environment_segment = {
        "TestType": "Memory/Storage Smoke",
        "Temperatures": {
            "Memory": {
                "Modules": [
                    {
                        "Name": "A-DATA AX5U5200C3816G-B",
                        "Temperatures": {"Max": 54.0, "Avg": 50.0, "Min": 45.0},
                    }
                ]
            },
            "Storage": {
                "Drives": [
                    {
                        "DeviceName": "Samsung SSD",
                        "Temperatures": {"Max": 60.0, "Avg": 52.0, "Min": 38.0},
                    }
                ]
            },
        },
    }
    assert_equal(
        build_memory_temperature_tests([environment_segment])[0]["results"]["Memory/Storage Smoke"]["avg"],
        50.0,
        "compat memory temperature test avg",
    )
    assert_equal(
        build_storage_temperature_tests([environment_segment])[0]["device"],
        "Samsung SSD",
        "compat storage temperature test device",
    )
    core_segment = {
        "TestType": "CPU Smoke",
        "Clocks": {
            "Cores": [
                {
                    "Name": "Core 0 Clock",
                    "CoreType": "P",
                    "Stats": {"Max": 5400.0, "Avg": 5100.0, "Min": 3600.0},
                }
            ]
        },
    }
    parser_output = {"Segments": [core_segment]}
    assert_true(has_core_clock_data(parser_output), "compat core clock data present")
    assert_true(has_core_type_data(parser_output, "P"), "compat P-core data present")
    assert_true(not has_core_type_data(parser_output, "E"), "compat E-core data absent")
    assert_equal(
        build_cpu_core_frequency_tests([core_segment])[0]["Core 0 Clock"]["CPU Smoke"]["avg"],
        5100.0,
        "compat CPU core frequency avg",
    )
    assert_equal(
        gpu_worker_backend_name({"mode": "gpu_3d", "renderer": "Mesa"}),
        "python_egl_gles2",
        "compat worker EGL backend inference",
    )
    assert_equal(
        gpu_worker_backend_name({"mode": "vram", "platform_name": "rusticl"}),
        "python_opencl",
        "compat worker OpenCL VRAM backend inference",
    )
    assert_equal(
        gpu_worker_backend_name({"mode": "gpu_3d", "selected_vulkan_index": 0}),
        "python_vulkan_transfer",
        "compat worker Vulkan legacy backend inference",
    )
    gpus = [
        {"DisplayName": "RTX 5090 #1", "Interface": "0000:01:00.0", "Card": "card1", "DeviceClass": "discrete"},
        {"DisplayName": "RTX 5090 #2", "Interface": "0000:02:00.0", "Card": "card2", "DeviceClass": "discrete"},
        {"DisplayName": "AMD Radeon Graphics", "Interface": "0000:13:00.0", "Card": "card0", "DeviceClass": "integrated"},
    ]
    assert_equal(
        resolve_gpu_worker_device_name({"slot": "0000:02:00.0", "gpu_index": 0}, gpus),
        "RTX 5090 #2",
        "compat worker device resolves by slot first",
    )
    assert_equal(
        resolve_gpu_worker_device_name({"gpu_index": 0}, gpus),
        "RTX 5090 #1",
        "compat worker device resolves by index",
    )
    assert_equal(
        gpu_source_device_class({"slot": "0000:13:00.0"}, gpus),
        "integrated",
        "compat GPU source device class",
    )
    assert_true(
        should_blank_gpu_power_source({"slot": "0000:13:00.0"}, gpus, [0.0, 0.2]),
        "compat blank low iGPU power source",
    )
    assert_equal(
        gpu_detail_export_sort_key({"ExpectedSlot": "0000:02:00.0", "name": "RTX 5090 #2"}, gpus)[0],
        1,
        "compat GPU detail sort by slot",
    )
    assert_equal(
        resolve_gpu_source_device_name({"label": "card2 PPT"}, gpus),
        "RTX 5090 #2",
        "compat GPU source name from label card",
    )


def test_compatibility_export_hardware_sections() -> None:
    window = StageWindow(
        stage_id="segment_1",
        stage_type="Combined",
        display_name="Hardware Fixture",
        started_iso="2026-06-04T10:00:00-04:00",
        ended_iso="2026-06-04T10:00:10-04:00",
        started_monotonic=0.0,
        ended_monotonic=10.0,
        duration_seconds=10.0,
        trim_start_seconds=2,
        trim_end_seconds=2,
    )
    samples = [
        Sample(1.0, {"cpu_temp_c": 10.0, "cpu_power_w": 10.0, "memory_used_gb": 10.0}),
        Sample(2.0, {"cpu_temp_c": 50.0, "cpu_power_w": 100.0, "memory_used_gb": 20.0}),
        Sample(5.0, {"cpu_temp_c": 60.0, "cpu_power_w": 120.0, "memory_used_gb": 22.0}),
        Sample(8.0, {"cpu_temp_c": 70.0, "cpu_power_w": 140.0, "memory_used_gb": 24.0}),
        Sample(9.0, {"cpu_temp_c": 90.0, "cpu_power_w": 200.0, "memory_used_gb": 30.0}),
    ]
    parser_output = {
        "Segments": [
            {
                "TestType": "Hardware Fixture",
                "Clocks": {
                    "Cores": [
                        {
                            "Name": "Core 0 Clock",
                            "Stats": {"Min": 4000.0, "Avg": 5000.0, "Max": 5500.0},
                        }
                    ]
                },
                "Temperatures": {
                    "Memory": {
                        "Modules": [
                            {
                                "Name": "DIMM 0",
                                "Temperatures": {"Min": 40.0, "Avg": 45.0, "Max": 50.0},
                            }
                        ]
                    },
                    "Storage": {
                        "Drives": [
                            {
                                "DeviceName": "nvme0n1",
                                "Temperatures": {"Min": 35.0, "Avg": 40.0, "Max": 45.0},
                            }
                        ]
                    },
                },
            }
        ]
    }
    gpu_section = {"devices": [{"gpu_name": "Fixture GPU"}], "tests": {}}
    sections = build_compatibility_hardware_sections(
        system_info={
            "Hardware": {
                "Memory": {
                    "Modules": [{"Name": "DIMM 0"}],
                    "SpeedSummary": {"OperatingSpeedMTs": 5600},
                },
                "Storage": [{"DeviceName": "nvme0n1"}],
            }
        },
        parser_output=parser_output,
        windows=[window],
        samples=samples,
        cpu_name="Fixture CPU",
        cpu_power_limits={
            "Constraints": [
                {"Name": "long_term", "PowerLimitW": 125.0},
                {"Name": "short_term", "PowerLimitW": 253.0},
            ]
        },
        gpu_section=gpu_section,
    )
    assert_equal(list(sections), ["Memory", "Storage", "Gpu", "Cpu", "CpuCores"], "hardware section order")
    assert_equal(sections["Memory"]["summary"]["OperatingSpeedMTs"], 5600, "hardware memory speed summary")
    assert_equal(sections["Gpu"], gpu_section, "hardware prebuilt GPU section")
    assert_equal(sections["Cpu"]["devices"]["aggregate_cpu_model"], "Fixture CPU", "hardware aggregate CPU model")
    assert_equal(sections["Cpu"]["devices"]["power_limit_1"], "125W", "hardware CPU PL1")
    assert_equal(sections["Cpu"]["devices"]["power_limit_2"], "253W", "hardware CPU PL2")
    assert_equal(
        sections["Cpu"]["tests"]["CPU Package (Temperature)"][0]["results"]["Hardware Fixture"],
        {"max": 70.0, "avg": 60.0, "min": 50.0},
        "hardware trimmed CPU temperature stats",
    )
    assert_equal(
        sections["Memory"]["tests"]["System Memory Used (Usage)"][0]["results"]["Hardware Fixture"]["avg"],
        22.0,
        "hardware trimmed memory usage stats",
    )
    assert_equal(
        sections["Memory"]["tests"]["SPD Hub Temperature (Temperature)"][0]["device"],
        "DIMM 0",
        "hardware memory temperature device",
    )
    assert_equal(
        sections["Storage"]["tests"]["Drive Temperature (Temperature)"][0]["device"],
        "nvme0n1",
        "hardware storage temperature device",
    )
    assert_equal(
        sections["CpuCores"]["tests"]["Frequency"][0]["Core 0 Clock"]["Hardware Fixture"]["avg"],
        5000.0,
        "hardware CPU core frequency",
    )


def test_compatibility_export_gpu_section() -> None:
    segment = {
        "TestType": "GPU Fixture",
        "Temperatures": {
            "Gpu": {
                "Core": {
                    "Gpus": [
                        {
                            "DisplayName": "RTX 5090 #1",
                            "SensorName": "edge",
                            "Temperatures": {"Min": 60.0, "Avg": 70.0, "Max": 80.0},
                        }
                    ]
                },
                "Hotspot": {
                    "Gpus": [
                        {
                            "DisplayName": "RTX 5090 #1",
                            "SensorName": "junction",
                            "Temperatures": {"Min": 70.0, "Avg": 80.0, "Max": 90.0},
                        }
                    ]
                },
                "Memory": {
                    "Gpus": [
                        {
                            "DisplayName": "RTX 5090 #1",
                            "SensorName": "mem",
                            "Temperatures": {"Min": 74.0, "Avg": 84.0, "Max": 94.0},
                        }
                    ]
                },
            }
        },
        "GpuMetrics": [
            {
                "DisplayName": "RTX 5090 #1",
                "Clock": {"Min": 1500.0, "Avg": 2500.0, "Max": 2800.0},
                "MemoryClock": {"Min": 8000.0, "Avg": 9000.0, "Max": 10000.0},
                "Power": {"Min": 250.0, "Avg": 500.0, "Max": 575.0},
                "Usage": {"Min": 85.0, "Avg": 95.0, "Max": 100.0},
                "MemoryUsage": {"Min": 60.0, "Avg": 75.0, "Max": 90.0},
                "VramUsedGB": {"Min": 8.0, "Avg": 12.0, "Max": 16.0},
            }
        ],
    }
    gpu_section = build_compatibility_gpu_section(
        gpu_devices=[
            {
                "Name": "NVIDIA GeForce RTX 5090",
                "DisplayName": "NVIDIA GeForce RTX 5090 #1",
                "Chipset": "GB202",
                "DriverVersion": "nvidia 575",
                "Memory": "32 GB",
            }
        ],
        segments=[segment],
        worker_metric_tests={
            "gpu_3d_errors": [{"device": "RTX 5090 #1", "results": {"GPU Fixture": {"min": 1.0, "avg": 1.0, "max": 1.0}}}],
            "gpu_3d_api_errors": [{"device": "RTX 5090 #1", "results": {"GPU Fixture": {"min": 2.0, "avg": 2.0, "max": 2.0}}}],
            "gpu_3d_draw_mismatches": [{"device": "RTX 5090 #1", "results": {"GPU Fixture": {"min": 3.0, "avg": 3.0, "max": 3.0}}}],
            "gpu_vram_errors": [{"device": "RTX 5090 #1", "results": {"GPU Fixture": {"min": 4.0, "avg": 4.0, "max": 4.0}}}],
            "gpu_vram_api_errors": [{"device": "RTX 5090 #1", "results": {"GPU Fixture": {"min": 5.0, "avg": 5.0, "max": 5.0}}}],
            "gpu_vram_mismatches": [{"device": "RTX 5090 #1", "results": {"GPU Fixture": {"min": 6.0, "avg": 6.0, "max": 6.0}}}],
            "gpu_vram_shortfall": [{"device": "RTX 5090 #1", "results": {"GPU Fixture": {"min": 7.0, "avg": 7.0, "max": 7.0}}}],
        },
    )
    assert_equal(
        gpu_section["devices"][0]["gpu_display_name"],
        "NVIDIA GeForce RTX 5090 #1",
        "GPU section display name",
    )
    expected_test_order = [
        "GPU Temperature (Temperature)",
        "GPU Hotspot Temperature (Temperature)",
        "GPU Memory Junction Temperature (Temperature)",
        "GPU Clock (Frequency)",
        "GPU Memory Clock (Frequency)",
        "GPU Power (Power)",
        "GPU Usage (Usage)",
        "GPU Memory Controller Usage (Usage)",
        "GPU VRAM Used (Usage)",
        "GPU 3D Verification Errors (Errors)",
        "GPU 3D API Errors (Errors)",
        "GPU 3D Draw Mismatches (Errors)",
        "GPU VRAM Verification Errors (Errors)",
        "GPU VRAM API Errors (Errors)",
        "GPU VRAM Data Mismatches (Errors)",
        "GPU VRAM Allocation Shortfall (Bytes)",
    ]
    assert_equal(list(gpu_section["tests"]), expected_test_order, "GPU section test order")
    assert_equal(
        gpu_section["tests"]["GPU Temperature (Temperature)"][0]["device"],
        "RTX 5090 #1 [edge]",
        "GPU section core temp device",
    )
    assert_equal(
        gpu_section["tests"]["GPU Power (Power)"][0]["results"]["GPU Fixture"]["avg"],
        500.0,
        "GPU section power avg",
    )
    assert_equal(
        gpu_section["tests"]["GPU VRAM Allocation Shortfall (Bytes)"][0]["results"]["GPU Fixture"]["max"],
        7.0,
        "GPU section worker metric",
    )


def test_gpu_power_details_builder() -> None:
    sources = [
        {"metric": "power_w", "key": "gpu_1_power_w", "label": "card2 PPT", "slot": "0000:02:00.0"},
        {"metric": "temperature_c", "key": "gpu_0_temp_c", "label": "card1 edge", "slot": "0000:01:00.0"},
        {"metric": "power_w", "key": "gpu_0_power_w", "label": "card1 PPT", "slot": "0000:01:00.0"},
        {"metric": "power_w", "key": "missing_power_w", "label": "missing"},
        {"metric": "power_w", "label": "no key"},
    ]
    samples = [
        Sample(1.0, {"gpu_0_power_w": 100.0, "gpu_1_power_w": 0.1}),
        Sample(2.0, {"gpu_0_power_w": 200.0, "gpu_1_power_w": 0.2}),
    ]
    blanked: list[tuple[str, list[object]]] = []

    def should_blank(source: dict[str, object], values: list[object]) -> bool:
        if source.get("slot") == "0000:02:00.0":
            blanked.append((str(source.get("slot") or ""), list(values)))
            return True
        return False

    detail = build_gpu_power_details(
        gpu_sources=sources,
        samples=samples,
        should_blank_source=should_blank,
        source_device_name=lambda source: {
            "0000:01:00.0": "RTX 5090 #1",
            "0000:02:00.0": "AMD Radeon Graphics",
        }.get(str(source.get("slot") or ""), "Unknown GPU"),
        sort_key=lambda item: (0, str(item.get("name") or "")),
    )
    assert_true(detail is not None, "GPU power detail generated")
    assert_equal(len(detail or []), 1, "GPU power detail blanks low iGPU")
    assert_equal(blanked, [("0000:02:00.0", [0.1, 0.2])], "GPU power detail blank callback values")
    assert_equal((detail or [])[0]["name"], "RTX 5090 #1", "GPU power detail resolved name")
    assert_equal((detail or [])[0]["sensor_name"], "card1 PPT", "GPU power detail sensor name")
    assert_equal((detail or [])[0]["category"], "board", "GPU power detail category")
    assert_true((detail or [])[0]["is_primary"], "GPU power detail primary marker")
    assert_equal((detail or [])[0]["min"], 100.0, "GPU power detail min")
    assert_equal((detail or [])[0]["avg"], 150.0, "GPU power detail avg")
    assert_equal((detail or [])[0]["max"], 200.0, "GPU power detail max")

    sorted_detail = build_gpu_power_details(
        gpu_sources=[
            {"metric": "power_w", "key": "gpu_1_power_w", "label": "card2 PPT", "slot": "0000:02:00.0"},
            {"metric": "power_w", "key": "gpu_0_power_w", "label": "card1 PPT", "slot": "0000:01:00.0"},
        ],
        samples=[Sample(1.0, {"gpu_0_power_w": 500.0, "gpu_1_power_w": 525.0})],
        should_blank_source=lambda source, values: False,
        source_device_name=lambda source: {
            "0000:01:00.0": "RTX 5090 #1",
            "0000:02:00.0": "RTX 5090 #2",
        }.get(str(source.get("slot") or ""), "Unknown GPU"),
        sort_key=lambda item: (0 if str(item.get("name") or "").endswith("#1") else 1, str(item.get("name") or "")),
    )
    assert_equal(
        [item["name"] for item in (sorted_detail or [])],
        ["RTX 5090 #1", "RTX 5090 #2"],
        "GPU power detail deterministic sort",
    )
    assert_true(
        build_gpu_power_details(
            gpu_sources=[{"metric": "power_w", "key": "missing"}],
            samples=[Sample(1.0, {})],
            should_blank_source=lambda source, values: False,
            source_device_name=lambda source: "Unknown GPU",
            sort_key=lambda item: (0, ""),
        )
        is None,
        "GPU power detail empty result",
    )


def test_gpu_worker_metric_test_builder() -> None:
    windows = [
        SimpleNamespace(
            display_name="GPU Stage 1",
            worker_results=[
                {"kind": "gpu", "mode": "gpu_3d", "target_id": "0000:01:00.0", "error_count": 1.234},
                {"kind": "gpu", "mode": "vram", "target_id": "0000:02:00.0", "error_count": 9},
                {"kind": "cpu", "mode": "gpu_3d", "target_id": "cpu", "error_count": 5},
                {"kind": "gpu", "mode": "gpu_3d", "target_id": "bad", "error_count": "not numeric"},
            ],
        ),
        SimpleNamespace(
            display_name="GPU Stage 2",
            worker_results=[
                {"kind": "gpu", "workload": "gpu_3d", "target_id": "0000:01:00.0", "error_count": 0},
                {"kind": "gpu", "mode": "gpu_3d", "target_id": "0000:03:00.0"},
            ],
        ),
    ]
    names = {
        "0000:01:00.0": "RTX 5090 #1",
        "0000:02:00.0": "RTX 5090 #2",
        "bad": "Bad GPU",
    }
    result = build_gpu_worker_metric_test(
        windows=windows,
        mode="gpu_3d",
        metric_key="error_count",
        device_name_resolver=lambda payload: names.get(str(payload.get("target_id") or ""), "Unknown GPU"),
    )
    assert_equal(len(result), 1, "worker metric nonzero devices")
    assert_equal(result[0]["device"], "RTX 5090 #1", "worker metric resolved device")
    assert_equal(
        result[0]["results"]["GPU Stage 1"],
        {"max": 1.23, "avg": 1.23, "min": 1.23},
        "worker metric rounded value",
    )
    assert_equal(
        result[0]["results"]["GPU Stage 2"],
        {"max": 0.0, "avg": 0.0, "min": 0.0},
        "worker metric includes zero once nonzero exists",
    )
    zero_only = build_gpu_worker_metric_test(
        windows=[
            SimpleNamespace(
                display_name="Zero Stage",
                worker_results=[{"kind": "gpu", "mode": "gpu_3d", "target_id": "0000:01:00.0", "error_count": 0}],
            )
        ],
        mode="gpu_3d",
        metric_key="error_count",
        device_name_resolver=lambda payload: "RTX 5090 #1",
    )
    assert_equal(zero_only, [], "worker metric omits zero-only results")


def test_gpu_worker_validation_detail_builder() -> None:
    payload = {
        "kind": "gpu",
        "workload": "vram",
        "backend": "python_vulkan_memory",
        "status": "ok",
        "target_gpu_index": "2",
        "target_id": "0000:03:00.0",
        "target_slot": "0000:03:00.0",
        "target_card": "card3",
        "worker_version": "1.2.3",
        "backend_api_family": "vulkan",
        "suite_scaling_mode": "adaptive",
        "suite_verification": "readback",
        "diagnostic_backend": True,
        "saturation_result": True,
        "power_saturation_expected": True,
        "profile_mode": "steady",
        "profile_intensity": "extreme",
        "selection_ambiguous": True,
        "kernel_variant": "stress_hash",
        "error_count": "1",
        "gl_error_count": 2,
        "draw_mismatch_count": 3,
        "vram_mismatch_count": 4,
        "transfer_mismatch_count": 5,
        "verification_passes": 6,
        "render_verification_passes": 7,
        "vram_verification_passes": 8,
        "frames": 9,
        "tuning_step": 10,
        "active_load_fraction": "0.87654",
        "target_process_count": 11,
        "active_process_count": 12,
        "active_target_vram_bytes": 400,
        "buffer_allocation_bytes": 100,
        "requested_buffer_bytes": 101,
        "target_buffer_bytes": 102,
        "worker_total_cap_bytes": 103,
        "buffer_count": 104,
        "buffer_count_limit": 105,
        "per_buffer_cap_bytes": 106,
        "buffer_size_min_bytes": 107,
        "buffer_size_max_bytes": 108,
        "buffer_size_avg_bytes": 109,
        "allocation_strategy": "multi_buffer",
        "requested_device_local_heap_percent": "90.5",
        "target_device_local_heap_percent": "88.25",
        "buffer_memory_type_index": 3,
        "buffer_memory_type_flags": 7,
        "buffer_memory_heap_index": 1,
        "buffer_device_local_heap_percent": "80.125",
        "staging_memory_type_index": 4,
        "device_local_heap_bytes": 32000000000,
        "device_local_heap_gb": 32.0,
        "estimated_device_memory_bytes": 31000000000,
        "estimated_device_memory_gb": 31.0,
        "estimated_device_memory_gbps": 900.5,
        "peak_estimated_device_memory_gbps": 950.75,
        "elapsed_seconds": 89.5,
        "verified_buffer_count": 13,
        "verified_buffer_coverage_percent": "99.5",
        "verified_buffer_indexes": [0, 2, 4],
        "buffer_dispatch_min": 14,
        "buffer_dispatch_max": 15,
        "buffer_dispatch_avg": 14.5,
        "phase": "steady",
        "runtime_target_cap_bytes": 201,
        "phase_limit_bytes": 202,
        "last_successful_bytes": 203,
        "runtime_work_item_cap": 204,
        "runtime_launch_cap": 205,
        "runtime_round_cap": 206,
        "runtime_buffer_count": 207,
        "allocation_attempts": 208,
        "allocation_touch_count": 209,
        "allocation_failures": 1,
        "allocation_exhausted": True,
        "allocation_shortfall_bytes": 210,
        "selected_device_name": "Selected GPU",
        "platform_name": "Mesa",
        "platform_vendor": "Mesa/X.org",
        "renderer": "RADV",
        "resolved_device_name": "Resolved GPU",
        "result_path": "/tmp/gpu.json",
    }
    detail = build_gpu_worker_validation_detail(
        stage_name="VRAM Stage",
        stage_type="Combined",
        stage_verdict="warning",
        payload=payload,
        backend_name="python_vulkan_memory",
        device_name="RTX 5090 #3",
    )
    assert_equal(detail["Stage"], "VRAM Stage", "worker detail stage")
    assert_equal(detail["StageType"], "Combined", "worker detail stage type")
    assert_equal(detail["StageVerdict"], "warning", "worker detail stage verdict")
    assert_equal(detail["Mode"], "vram", "worker detail mode from workload")
    assert_equal(detail["Workload"], "vram", "worker detail workload")
    assert_equal(detail["Backend"], "python_vulkan_memory", "worker detail backend")
    assert_equal(detail["DeviceName"], "RTX 5090 #3", "worker detail device")
    assert_equal(detail["ExpectedGpuIndex"], 2, "worker detail target GPU index fallback")
    assert_equal(detail["ExpectedSlot"], "0000:03:00.0", "worker detail target slot fallback")
    assert_equal(detail["ExpectedCard"], "card3", "worker detail target card fallback")
    assert_equal(
        detail["ExpectedTargetMapping"],
        {"GpuIndex": 2, "TargetId": "0000:03:00.0", "Slot": "0000:03:00.0", "Card": "card3"},
        "worker detail target mapping",
    )
    assert_equal(detail["ComputeVariant"], "stress_hash", "worker detail kernel variant fallback")
    assert_equal(detail["ActiveLoadFraction"], 0.877, "worker detail active load rounding")
    assert_equal(detail["AllocatedVramBytes"], 100, "worker detail allocated fallback")
    assert_equal(detail["TargetVramBytes"], 400, "worker detail target VRAM")
    assert_equal(detail["AllocationPercent"], 25.0, "worker detail allocation percent")
    assert_equal(detail["VerifiedBufferIndexes"], [0, 2, 4], "worker detail verified buffers")
    assert_equal(detail["BufferDispatchAvg"], 14.5, "worker detail buffer dispatch avg")
    assert_true(detail["AllocationExhausted"], "worker detail allocation exhausted")
    assert_equal(detail["AllocationShortfallBytes"], 210, "worker detail shortfall")
    assert_equal(detail["SelectedDeviceName"], "Selected GPU", "worker detail selected device")
    assert_equal(detail["Renderer"], "RADV", "worker detail renderer")

    missing_index_detail = build_gpu_worker_validation_detail(
        stage_name="3D Stage",
        stage_type="3D Adaptive",
        stage_verdict="pass",
        payload={"kind": "gpu", "mode": "gpu_3d", "gpu_index": "not numeric"},
        backend_name="python_egl_gles2",
        device_name="Unknown GPU",
    )
    assert_true(missing_index_detail["ExpectedGpuIndex"] is None, "worker detail invalid GPU index")
    assert_true(missing_index_detail["AllocationPercent"] is None, "worker detail missing allocation percent")


def test_compatibility_export_run_context() -> None:
    metadata = RunMetadata(power_limit_data="Operator PL override")
    system_info = {
        "Hardware": {
            "Cpu": {
                "Name": "Dual Socket Smoke CPU",
                "PowerLimits": {
                    "PowerLimitData": "Detected PL",
                    "AmdPpt": "280W",
                },
            },
            "Motherboard": {
                "Product": "Smoke Board",
                "Manufacturer": "Smoke Vendor",
                "Description": "Smoke Vendor Smoke Board",
                "Version": "1.0",
                "SystemVendor": "Smoke System Vendor",
                "BoardVendor": "Smoke Board Vendor",
                "BoardName": "Smoke Board Name",
            },
            "Bios": {
                "Name": "Smoke BIOS Full",
                "Version": "S1.2",
                "FullName": "Smoke BIOS Full S1.2",
            },
        },
        "TestInfo": {
            "TestName": "Smoke Test",
            "ProfileDisplayName": "Smoke Profile Linux Validation",
            "ConfigFile": "profiles/Smoke Profile.json",
        },
    }
    windows = [
        SimpleNamespace(
            verdict="pass",
            error_events=[{"category": "warning_event", "severity": "warning"}],
            system_faults=[],
        ),
        SimpleNamespace(
            verdict="aborted",
            error_events=[{"category": "operator_stop", "severity": "warning"}],
            system_faults=[{"category": "hardware_error", "severity": "error"}],
        ),
    ]
    skipped = [{"stage_id": "segment_3", "reason": "unsupported"}]
    context = build_compatibility_run_context(metadata, system_info, windows, skipped)
    assert_equal(context["cpu_name"], "Dual Socket Smoke CPU", "compat context CPU name")
    assert_equal(context["profile_name"], "Smoke Profile", "compat context profile fallback")
    assert_equal(context["motherboard_description"], "Smoke Vendor Smoke Board", "compat context motherboard")
    assert_equal(context["bios_version"], "S1.2", "compat context BIOS")
    assert_equal(context["effective_power_limit_data"], "Operator PL override", "compat context PL override")
    assert_equal(context["effective_amd_ppt"], "280W", "compat context AMD PPT")
    assert_equal(context["executed_stage_count"], 2, "compat context executed stage count")
    assert_equal(context["skipped_stage_count"], 1, "compat context skipped stage count")
    assert_equal(context["top_level_error_count"], 1, "compat context error count")
    assert_true(context["manual_abort"], "compat context manual abort")
    assert_equal(context["overall_result"], "manually_aborted", "compat context result")
    assert_equal(context["execution_detail"], "manually_aborted", "compat context execution detail")


def test_compatibility_export_metadata_block() -> None:
    metadata = RunMetadata(
        serial="META123",
        dept="RND",
        notes="Metadata smoke",
        wall_wattage="700W",
        case_sku="Smoke Case",
        description="Smoke Description",
        psu_wattage="1000W",
        psu_rating="Gold",
        cpu_cooler="Tower",
        fan_type="PWM",
        fan_details="3 intake",
        advanced_debug_logging=True,
    )
    system_info = {
        "Hardware": {
            "Cpu": {"Name": "Smoke CPU", "PowerLimits": {"PowerLimitData": "PL1 125W"}},
            "Motherboard": {
                "Product": "Smoke Board",
                "Manufacturer": "Smoke Vendor",
                "Description": "Smoke Vendor Smoke Board",
                "Version": "1.0",
                "SystemVendor": "Smoke System Vendor",
                "BoardVendor": "Smoke Board Vendor",
                "BoardName": "Smoke Board Name",
            },
            "Bios": {"Name": "Smoke BIOS", "Version": "S1", "FullName": "Smoke BIOS S1"},
            "Gpu": [{"Name": "Smoke GPU"}],
        },
        "TestInfo": {
            "TestName": "Smoke Test",
            "ProfileName": "Smoke Profile",
            "ProfileDisplayName": "Smoke Profile Linux Validation",
            "ConfigFile": "profiles/Smoke Profile.json",
        },
    }
    window = StageWindow(
        stage_id="segment_1",
        stage_type="Combined",
        display_name="Metadata Stage",
        started_iso="2026-06-04T12:00:00-04:00",
        ended_iso="2026-06-04T12:01:30-04:00",
        started_monotonic=0.0,
        ended_monotonic=90.0,
        duration_seconds=90.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        cpu_backend="cpu_native_helper",
        cpu_mode_requested="avx2",
        cpu_mode_resolved="avx2",
        cpu_kernel_flavor="avx2_fma",
        cpu_tuning_policy="family_locked",
        cpu_tuned_avg_power_w=120.0,
        gpu_target_mode="all",
        gpu_targets=["0000:01:00.0"],
        gpu_workers_initial=[{"backend": "python_vulkan_compute"}],
        gpu_workers_final=[{"backend": "python_vulkan_compute"}],
        gpu_retune_events=[{"step": 1}],
        verdict="warning",
        error_events=[{"category": "thermal", "severity": "warning"}],
    )
    parser_output = {
        "Segments": [
            {
                "Clocks": {
                    "Cores": [
                        {"Name": "Core 0 Clock", "CoreType": "P", "Stats": {}},
                        {"Name": "Core 8 Clock", "CoreType": "E", "Stats": {}},
                    ]
                }
            }
        ]
    }
    context = build_compatibility_run_context(
        metadata,
        system_info,
        [window],
        [{"stage_id": "segment_2", "reason": "unsupported"}],
    )
    contract = {"Schema": "smoke.contract"}
    recovery = {
        "unclean_marker_present": True,
        "previous_boot_fault_summary": {"fault_count": 1},
    }
    block = build_compatibility_metadata_block(
        metadata,
        window.started_iso,
        window.ended_iso,
        window.duration_seconds,
        system_info,
        parser_output,
        [window],
        context,
        [{"device": "Smoke GPU", "max": 500.0}],
        contract,
        recovery,
        date_text="2026-06-04",
        parsed_datetime="2026-06-04T12:02:00-04:00",
    )
    assert_equal(block["SerialNumber"], "META123", "compat metadata serial")
    assert_equal(block["CpuAggregateName"], "Smoke CPU", "compat metadata aggregate CPU name")
    assert_equal(block["Date"], "2026-06-04", "compat metadata date")
    assert_equal(block["ParsedDateTime"], "2026-06-04T12:02:00-04:00", "compat metadata parsed time")
    assert_equal(block["ProfileName"], "Smoke Profile", "compat metadata profile")
    assert_true(block["HasPCores"], "compat metadata P-core flag")
    assert_true(block["HasECores"], "compat metadata E-core flag")
    assert_equal(block["DgpuName"], "Smoke GPU", "compat metadata primary GPU")
    assert_equal(block["CpuInstructionModes"][0]["KernelFlavor"], "avx2_fma", "compat metadata CPU mode")
    assert_equal(block["GpuExecutionModes"][0]["Targets"], ["0000:01:00.0"], "compat metadata GPU targets")
    assert_equal(block["Stability"]["WarningCount"], 1, "compat metadata warning count")
    assert_equal(block["ExecutionSummary"]["RequestedStageCount"], 2, "compat metadata requested stages")
    assert_equal(block["ExportContract"], contract, "compat metadata export contract")
    assert_true(block["GpuRecovery"]["UncleanMarkerPresent"], "compat metadata recovery")


def test_compatibility_export_identity_envelope() -> None:
    metadata = RunMetadata(
        serial="ENV123",
        order="ORD123",
        dept="RND",
        case_sku="Envelope Case",
        description="Envelope Description",
        psu_wattage="1200W",
        psu_rating="Platinum",
        power_limit_data="Operator PL",
        cpu_cooler="Liquid",
        fan_type="PWM",
        fan_details="Envelope fans",
        advanced_debug_logging=True,
    )
    system_info = {
        "Hardware": {
            "Cpu": {"Name": "Envelope CPU", "PowerLimits": {"AmdPpt": "300W"}},
            "Motherboard": {
                "Product": "Envelope Board",
                "Manufacturer": "Envelope Vendor",
                "Description": "Envelope Vendor Envelope Board",
                "Version": "2.0",
                "SystemVendor": "Envelope System Vendor",
                "BoardVendor": "Envelope Board Vendor",
                "BoardName": "Envelope Board Name",
            },
            "Bios": {
                "Name": "Envelope BIOS",
                "Version": "E2",
                "FullName": "Envelope BIOS E2",
            },
        },
        "TestInfo": {
            "TestName": "Envelope Test",
            "ProfileName": "Envelope Profile",
            "ProfileDisplayName": "Envelope Profile Linux Validation",
            "ConfigFile": "profiles/Envelope Profile.json",
        },
    }
    window = SimpleNamespace(verdict="warning", error_events=[], system_faults=[])
    context = build_compatibility_run_context(metadata, system_info, [window])
    envelope = build_compatibility_identity_envelope(
        metadata,
        "2026-06-04T13:00:00-04:00",
        "2026-06-04T13:01:30-04:00",
        90.0,
        context,
        "9.9.9",
        lower_date_text="2026-06-04",
        upper_date_text="2026-06-05",
    )
    assert_equal(envelope["serial"], "ENV123", "compat envelope lower serial")
    assert_equal(envelope["Serial"], "ENV123", "compat envelope upper serial")
    assert_equal(envelope["date"], "2026-06-04", "compat envelope lower date")
    assert_equal(envelope["Date"], "2026-06-05", "compat envelope upper date")
    assert_equal(envelope["elapsed"], "00:01:30", "compat envelope elapsed")
    assert_equal(envelope["Result"], "Warning", "compat envelope result")
    assert_equal(envelope["CombinedDescription"], "Envelope Case=Envelope Description", "compat envelope description")
    assert_equal(envelope["PowerLimitData"], "Operator PL", "compat envelope power limits")
    assert_equal(envelope["AmdPpt"], "300W", "compat envelope AMD PPT")
    assert_equal(envelope["SourceVersion"], "9.9.9", "compat envelope version")
    devices = envelope["Motherboard"]["devices"]
    assert_equal(devices["motherboard_description"], "Envelope Vendor Envelope Board", "compat envelope board")
    assert_equal(devices["bios_version"], "E2", "compat envelope BIOS")


def test_compatibility_export_finalizer() -> None:
    base_output = {
        "serial": "FINAL123",
        "Motherboard": {"devices": {}, "tests": {}},
        "Cpu": {"devices": {}, "tests": {}},
    }
    metadata_block = {
        "Stability": {"Verdict": "Warning"},
        "ExecutionSummary": {"ExecutedStageCount": 1, "SkippedStageCount": 1},
    }
    contract = {"Schema": "smoke.contract"}
    report_summary = {"Result": "Warning", "StageCount": 1}
    interpretation = {"State": "warning", "OutcomeClass": "completed_with_warnings"}
    system_info = {"Hardware": {"Cpu": {"Name": "Smoke CPU"}}}
    parser_output = {
        "Segments": [{"TestType": "Smoke"}],
        "SegmentDetails": {"segment_1": {"label": "Smoke"}},
    }
    recovery = {"unclean_marker_present": True}
    power_details = [{"device": "Smoke GPU", "max": 500.0}]
    validation_details = [{"DeviceName": "Smoke GPU", "Status": "ok"}]
    output = finalize_compatibility_export(
        base_output,
        metadata_block,
        contract,
        report_summary,
        interpretation,
        system_info,
        parser_output,
        recovery,
        power_details,
        validation_details,
    )
    assert_equal(output["serial"], "FINAL123", "compat finalizer base output")
    assert_equal(output["Segments"], parser_output["Segments"], "compat finalizer parser segments")
    assert_equal(output["ExecutionSummary"], metadata_block["ExecutionSummary"], "compat finalizer execution summary")
    assert_equal(output["ExportContract"], contract, "compat finalizer contract")
    assert_equal(output["ReportSummary"], report_summary, "compat finalizer report summary")
    assert_equal(output["report_summary"], report_summary, "compat finalizer lower report summary")
    assert_equal(output["StabilityInterpretation"], interpretation, "compat finalizer interpretation")
    assert_equal(
        output["Metadata"]["Stability"]["InterpretationSummary"],
        interpretation,
        "compat finalizer metadata interpretation",
    )
    assert_equal(output["Metadata"]["ReportSummary"], report_summary, "compat finalizer metadata report")
    assert_equal(output["Recovery"], recovery, "compat finalizer recovery")
    assert_equal(output["GpuDetails"]["power_details"], power_details, "compat finalizer GPU power")
    assert_equal(
        output["GpuDetails"]["validation_details"],
        validation_details,
        "compat finalizer GPU validation",
    )
    minimal = finalize_compatibility_export(
        {},
        {"Stability": {}, "ExecutionSummary": {}},
        {},
        {},
        {},
        {},
        {},
    )
    assert_true("Recovery" not in minimal, "compat finalizer omits empty recovery")
    assert_true("GpuDetails" not in minimal, "compat finalizer omits empty GPU details")


def test_compatibility_export_document_builder() -> None:
    metadata = RunMetadata(
        serial="DOC123",
        order="ORD789",
        dept="RND",
        case_sku="Doc Case",
        description="Doc Description",
        psu_wattage="1200W",
        psu_rating="Platinum",
        cpu_cooler="Liquid",
        fan_type="PWM",
        fan_details="Document fans",
        wall_wattage="800W",
    )
    system_info = {
        "Hardware": {
            "Cpu": {
                "Name": "Document CPU",
                "PowerLimits": {"PowerLimitData": "PL1 125W", "AmdPpt": "280W"},
            },
            "Motherboard": {
                "Product": "Document Board",
                "Manufacturer": "Document Vendor",
                "Description": "Document Vendor Document Board",
                "Version": "1.0",
                "SystemVendor": "Document System",
                "BoardVendor": "Document Vendor",
                "BoardName": "Document Board",
            },
            "Bios": {"Name": "Document BIOS", "Version": "D1", "FullName": "Document BIOS D1"},
            "Memory": {"TotalPhysicalMemoryGB": 64, "Modules": [{"Name": "DIMM 0"}]},
            "Storage": [{"DeviceName": "nvme0n1", "Model": "Document NVMe", "CapacityGB": 1024}],
            "Gpu": [{"Name": "Document GPU", "DisplayName": "Document GPU #1"}],
        },
        "OperatingSystem": {"Name": "DocumentOS Linux"},
        "TestInfo": {
            "TestName": "Doc Case=Doc Description",
            "ProfileName": "Document Profile",
            "ProfileDisplayName": "Document Profile Linux Validation",
            "ConfigFile": "profiles/Document Profile.json",
        },
    }
    window = StageWindow(
        stage_id="segment_1",
        stage_type="Combined",
        display_name="Document Stage",
        started_iso="2026-06-05T09:00:00-04:00",
        ended_iso="2026-06-05T09:01:30-04:00",
        started_monotonic=0.0,
        ended_monotonic=90.0,
        duration_seconds=90.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="warning",
        error_events=[{"category": "thermal", "severity": "warning"}],
    )
    parser_output = {
        "Segments": [
            {
                "TestType": "Document Stage",
                "Verdict": "warning",
                "Temperatures": {"Cpu": {"Min": 55.0, "Avg": 60.0, "Max": 65.0}},
            }
        ],
        "SegmentDetails": {"segment_1": {"label": "Document Stage"}},
    }
    gpu_section = {
        "devices": [{"gpu_name": "Document GPU", "gpu_display_name": "Document GPU #1"}],
        "tests": {"GPU Power (Power)": [{"device": "Document GPU #1", "results": {"Document Stage": {"max": 500.0}}}]},
    }
    power_details = [{"name": "Document GPU #1", "max": 500.0}]
    validation_details = [{"DeviceName": "Document GPU #1", "Status": "ok", "VerificationPasses": 3}]
    recovery = {"unclean_marker_present": True, "previous_boot_fault_summary": {"error_count": 1}}
    output = build_compatibility_export_document(
        metadata=metadata,
        started_iso=window.started_iso,
        ended_iso=window.ended_iso,
        elapsed_seconds=window.duration_seconds,
        system_info=system_info,
        parser_output=parser_output,
        windows=[window],
        samples=[
            Sample(1.0, {"cpu_temp_c": 55.0, "cpu_power_w": 90.0, "memory_used_gb": 20.0}),
            Sample(45.0, {"cpu_temp_c": 60.0, "cpu_power_w": 100.0, "memory_used_gb": 22.0}),
            Sample(89.0, {"cpu_temp_c": 65.0, "cpu_power_w": 110.0, "memory_used_gb": 24.0}),
        ],
        app_version="9.9.9",
        export_contract={"Schema": "document.contract"},
        gpu_section=gpu_section,
        gpu_power_details=power_details,
        gpu_validation_details=validation_details,
        recovery_report=recovery,
        skipped_stages=[{"stage_id": "segment_2", "reason": "unsupported"}],
    )
    assert_equal(output["Serial"], "DOC123", "compat document envelope serial")
    assert_equal(output["Result"], "Warning", "compat document result")
    assert_equal(output["ExecutionDetail"], "Warning", "compat document execution detail")
    assert_equal(output["SourceVersion"], "9.9.9", "compat document source version")
    assert_equal(output["Metadata"]["ProfileName"], "Document Profile", "compat document metadata")
    assert_equal(output["Metadata"]["ExecutionSummary"]["SkippedStageCount"], 1, "compat document skipped count")
    assert_equal(output["Metadata"]["GpuPowerDetails"], power_details, "compat document metadata GPU power")
    assert_equal(output["Gpu"], gpu_section, "compat document GPU section")
    assert_equal(output["GpuDetails"]["power_details"], power_details, "compat document GPU power details")
    assert_equal(
        output["GpuDetails"]["validation_details"],
        validation_details,
        "compat document GPU validation details",
    )
    assert_equal(output["ReportSummary"]["Result"], "Warning", "compat document report result")
    assert_equal(output["ReportSummary"], output["Metadata"]["ReportSummary"], "compat document report mirror")
    assert_equal(output["Recovery"], recovery, "compat document recovery")
    assert_true("CPU Package Power (Power)" in output["Cpu"]["tests"], "compat document CPU power tests")


def test_linux_fault_collector_classification() -> None:
    collector = LinuxFaultCollector()
    lines = [
        "2026-05-29T10:00:00-04:00 host kernel: NVRM: Xid 79, GPU has fallen off the bus",
        "2026-05-29 10:00:01 host kernel: pcie bus error: severity=Corrected",
        "host kernel: mce: hardware error CPU 0",
        "host kernel: oom-killer invoked",
        "host kernel: ordinary message",
    ]
    events = collector._collect_from_lines(lines, source="kernel", boot_scope="current")
    assert_equal(
        [event["category"] for event in events],
        ["nvidia_xid", "pcie_aer", "hardware_error", "oom"],
        "fault collector categories",
    )
    assert_equal(events[0]["timestamp"], "2026-05-29T10:00:00-04:00", "fault collector ISO timestamp")
    assert_equal(events[1]["timestamp"], "2026-05-29T10:00:01", "fault collector space timestamp")
    assert_equal(events[3]["severity"], "warning", "fault collector OOM warning")
    summary = summarize_fault_events(events)
    assert_equal(summary["count"], 4, "fault summary count")
    assert_equal(summary["error_count"], 3, "fault summary error count")
    assert_equal(summary["warning_count"], 1, "fault summary warning count")
    assert_equal(summary["categories"]["nvidia_xid"], 1, "fault summary category count")
    window = SimpleNamespace(
        started_iso="2026-05-29T10:00:00-04:00",
        ended_iso="2026-05-29T10:05:00-04:00",
    )
    windowed = faults_for_stage_window(
        [
            {"timestamp": "2026-05-29T09:59:59-04:00", "category": "before"},
            {"timestamp": "2026-05-29T10:00:00-04:00", "category": "start"},
            {"timestamp": "2026-05-29T10:02:00-04:00", "category": "middle"},
            {"timestamp": "2026-05-29T10:05:00-04:00", "category": "end"},
            {"timestamp": "2026-05-29T10:05:01-04:00", "category": "after"},
            {"timestamp": "not-a-date", "category": "invalid"},
            {"category": "missing"},
        ],
        window,
    )
    assert_equal(
        [event["category"] for event in windowed],
        ["start", "middle", "end"],
        "fault stage-window inclusive filtering",
    )


def test_gpu_safety_marker_store() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        store = GpuSafetyMarkerStore(Path(tmp) / "settings")
        assert_true(store.read() is None, "missing GPU safety marker")
        store.write(
            profile_name="Smoke",
            stage_name="GPU Stage",
            gpu_backends=["python_vulkan_transfer"],
            gpu_targets=["0000:01:00.0"],
            run_dir=Path(tmp) / "results" / "run",
        )
        payload = store.read()
        assert_true(isinstance(payload, dict), "GPU safety marker read")
        assert_equal(payload.get("profile_name"), "Smoke", "GPU safety marker profile")
        assert_equal(payload.get("gpu_targets"), ["0000:01:00.0"], "GPU safety marker targets")
        assert_true(str(payload.get("path") or "").endswith("gpu_safety_marker.json"), "GPU safety marker path")
        store.clear()
        assert_true(store.read() is None, "GPU safety marker cleared")


def test_compatibility_export_fixture_shape() -> None:
    exporter = CompatibilityExporter()
    metadata = RunMetadata(
        serial="SMOKE123",
        order="ORD456",
        dept="Production",
        case_sku="Fixture Case",
        description="Fixture Description",
        psu_wattage="850W",
        psu_rating="Gold",
        cpu_cooler="Tower",
        fan_type="PWM",
        fan_details="2 intake, 1 exhaust",
        wall_wattage="640W",
    )
    system_info = {
        "Hardware": {
            "Cpu": {
                "Name": "Smoke CPU",
                "PowerLimits": {
                    "PowerLimitData": "PL1 125W / PL2 253W",
                    "Constraints": [
                        {"Name": "long_term", "PowerLimitW": 125.0},
                        {"Name": "short_term", "PowerLimitW": 253.0},
                    ],
                },
            },
            "Motherboard": {
                "Product": "PRIME X670-P WIFI",
                "Manufacturer": "ASUS",
                "Description": "ASUS PRIME X670-P WIFI",
                "Version": "Rev 1.xx",
                "SystemVendor": "ASUSTeK COMPUTER INC.",
                "BoardVendor": "ASUSTeK COMPUTER INC.",
                "BoardName": "PRIME X670-P WIFI",
            },
            "Bios": {"Name": "American Megatrends Inc. 3287", "Version": "3287", "FullName": "American Megatrends Inc. 3287"},
            "Memory": {
                "TotalPhysicalMemoryGB": 64,
                "Modules": [{"Name": "DIMM 0", "PartNumber": "F5-6000J3444F64G"}],
            },
            "Storage": [{"DeviceName": "nvme0n1", "Model": "Smoke NVMe", "CapacityGB": 1024}],
            "Gpu": [
                {
                    "Name": "NVIDIA GeForce RTX 5090",
                    "Interface": "0000:01:00.0",
                    "Card": "card1",
                    "Chipset": "GB202",
                    "DriverVersion": "nvidia 575",
                    "Memory": "32 GB",
                    "DeviceClass": "discrete",
                }
            ],
        },
        "OperatingSystem": {"Name": "SmokeOS Linux 6.19"},
        "TestInfo": {
            "TestName": "Fixture Case=Fixture Description",
            "ProfileName": "Fixture Profile",
            "ProfileDisplayName": "Fixture Profile Linux Validation",
            "ConfigFile": "profiles/Fixture Profile.json",
        },
    }
    segment = {
        "Label": "GPU Fixture",
        "TestType": "3D Adaptive",
        "TestDescription": "GPU Fixture",
        "Verdict": "pass",
        "Clocks": {
            "AllCoreAverage": {"Min": 5000.0, "Avg": 5100.0, "Max": 5200.0},
            "Cores": [{"Name": "Core 0 Clock", "CoreType": "P", "Stats": {"Min": 5000.0, "Avg": 5100.0, "Max": 5200.0}}],
        },
        "Temperatures": {
            "Cpu": {"Min": 55.0, "Avg": 60.0, "Max": 65.0},
            "Gpu": {
                "Core": {
                    "Gpus": [
                        {
                            "GpuIndex": 0,
                            "Name": "NVIDIA GeForce RTX 5090",
                            "DisplayName": "NVIDIA GeForce RTX 5090",
                            "SensorName": "edge",
                            "Temperatures": {"Min": 60.0, "Avg": 70.0, "Max": 80.0},
                        }
                    ]
                }
            },
            "Memory": {
                "Modules": [
                    {"Name": "DIMM 0", "Temperatures": {"Min": 40.0, "Avg": 45.0, "Max": 50.0}}
                ]
            },
            "Storage": {
                "Drives": [
                    {"DeviceName": "Smoke NVMe", "Temperatures": {"Min": 35.0, "Avg": 40.0, "Max": 45.0}}
                ]
            },
        },
        "Power": {"Cpu": {"Min": 90.0, "Avg": 100.0, "Max": 110.0}},
        "GpuMetrics": [
            {
                "GpuIndex": 0,
                "Name": "NVIDIA GeForce RTX 5090",
                "DisplayName": "NVIDIA GeForce RTX 5090",
                "Targeted": True,
                "TargetIds": ["0000:01:00.0"],
                "Cards": ["card1"],
                "Slots": ["0000:01:00.0"],
                "Workloads": ["gpu_3d"],
                "Backends": ["python_vulkan_compute"],
                "LoadQuality": "high",
                "Clock": {"Min": 1500.0, "Avg": 2500.0, "Max": 2800.0},
                "MemoryClock": {"Min": 8000.0, "Avg": 9000.0, "Max": 10000.0},
                "Power": {"Min": 250.0, "Avg": 500.0, "Max": 575.0},
                "Usage": {"Min": 85.0, "Avg": 95.0, "Max": 100.0},
                "MemoryUsage": {"Min": 60.0, "Avg": 75.0, "Max": 90.0},
                "VramUsedGB": {"Min": 8.0, "Avg": 12.0, "Max": 16.0},
                "UsageSustain": {"StdDev": 3.0, "Range": 15.0, "SampleCount": 12},
                "WorkerEvidence": {"VerificationPasses": 9, "MaxAllocationPercent": 80.0},
            }
        ],
        "StabilityInterpretation": {
            "State": "clean",
            "Result": "pass",
            "OutcomeClass": "verified_clean",
            "OutcomeSummary": "Synthetic fixture completed cleanly.",
            "PrimaryPurpose": "gpu_stress",
            "BackendConfidence": "worker_verified",
            "WarningCategoryCounts": {},
            "ErrorCategoryCounts": {},
            "TargetedGpuCount": 1,
            "TargetedLoadQualityCounts": {"high": 1},
        },
    }
    window = StageWindow(
        stage_id="segment_1",
        stage_type="3D Adaptive",
        display_name="GPU Fixture",
        started_iso="2026-05-22T12:00:00-04:00",
        ended_iso="2026-05-22T12:01:30-04:00",
        started_monotonic=0.0,
        ended_monotonic=90.0,
        duration_seconds=90.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        gpu_3d_backend_preference="vulkan_compute",
        gpu_3d_backend_resolved="python_vulkan_compute",
        gpu_target_mode="all",
        gpu_targets=["0000:01:00.0"],
        verdict="pass",
        worker_results=[
            {
                "kind": "gpu",
                "mode": "gpu_3d",
                "backend": "python_vulkan_compute",
                "status": "ok",
                "gpu_index": 0,
                "target_id": "0000:01:00.0",
                "slot": "0000:01:00.0",
                "card": "card1",
                "verification_passes": 9,
                "frames": 120,
            }
        ],
    )
    telemetry = SimpleNamespace(
        samples=[
            Sample(1.0, {"cpu_temp_c": 55.0, "cpu_power_w": 90.0, "memory_used_gb": 20.0, "gpu_0_power_w": 250.0}),
            Sample(45.0, {"cpu_temp_c": 60.0, "cpu_power_w": 100.0, "memory_used_gb": 22.0, "gpu_0_power_w": 500.0}),
            Sample(89.0, {"cpu_temp_c": 65.0, "cpu_power_w": 110.0, "memory_used_gb": 24.0, "gpu_0_power_w": 575.0}),
        ],
        _gpu_sources=[
            {"metric": "power_w", "key": "gpu_0_power_w", "label": "card1 PPT", "slot": "0000:01:00.0", "card": "card1", "gpu_index": 0}
        ],
    )
    result = exporter.build(
        metadata,
        "2026-05-22T12:00:00-04:00",
        "2026-05-22T12:01:30-04:00",
        90.0,
        system_info,
        {"Segments": [segment], "SegmentDetails": {"segment_1": {"label": "GPU Fixture"}}},
        telemetry,
        [window],
    )
    assert_equal(result["Result"], "Finished", "fixture top-level result")
    assert_equal(result["Metadata"]["BiosVersion"], "3287", "fixture BIOS version")
    assert_equal(result["Metadata"]["MotherboardDescription"], "ASUS PRIME X670-P WIFI", "fixture motherboard description")
    assert_equal(result["Metadata"]["ReportSummary"], result["ReportSummary"], "fixture report summary mirror")
    assert_equal(result["Metadata"]["ExportContract"], result["ExportContract"], "fixture export contract mirror")
    report_summary_validation = validate_report_summary_mirror(result)
    assert_equal(report_summary_validation["issues"], [], "fixture report summary validation no issues")
    assert_equal(report_summary_validation["checks"]["report_summary"]["mirror_mismatches"], [], "fixture report summary mirror ok")
    stability_validation = validate_stability_alignment(result, result["ReportSummary"])
    assert_equal(stability_validation["issues"], [], "fixture stability alignment no issues")
    assert_equal(stability_validation["checks"]["stability_alignment"]["metadata_mismatches"], [], "fixture stability metadata mirror ok")
    assert_equal(stability_validation["checks"]["stability_alignment"]["report_mismatches"], [], "fixture stability report alignment ok")
    stage_count_validation = validate_report_stage_counts(result, result["ReportSummary"])
    assert_equal(stage_count_validation["issues"], [], "fixture stage counts no issues")
    assert_equal(stage_count_validation["checks"]["stage_counts"]["segments"], 1, "fixture stage count segments")
    assert_equal(stage_count_validation["checks"]["stage_counts"]["stage_outcomes"], 1, "fixture stage count outcomes")
    action_item_validation = validate_report_action_items(result["ReportSummary"])
    assert_equal(action_item_validation["issues"], [], "fixture action item validation no issues")
    assert_equal(
        action_item_validation["checks"]["action_items"]["category_counts"],
        result["ReportSummary"]["ActionItemCategoryCounts"],
        "fixture action item category counts",
    )
    assert_equal(
        action_item_validation["checks"]["action_items"]["severity_counts"],
        result["ReportSummary"]["ActionItemSeverityCounts"],
        "fixture action item severity counts",
    )
    gpu_worker_validation = validate_gpu_worker_summary(result, result["ReportSummary"])
    assert_equal(gpu_worker_validation["issues"], [], "fixture GPU worker validation no issues")
    assert_equal(len(gpu_worker_validation["validation_details"]), 1, "fixture GPU worker validation detail count")
    export_validation = validate_export_contract_compatibility(result)
    assert_true(export_validation["checks"]["stable_consumer_fields"]["ok"], "fixture stable consumer fields ok")
    assert_true(export_validation["checks"]["export_contract"]["ok"], "fixture export contract ok")
    assert_equal(export_validation["issues"], [], "fixture export contract validation no issues")
    assert_equal(result["ReportSummary"]["DepartmentUseSummary"]["Status"], "ready", "fixture department status")
    assert_equal(result["ReportSummary"]["GpuWorkerSummary"]["WorkerResultCount"], 1, "fixture worker result count")
    assert_equal(result["GpuDetails"]["validation_details"][0]["DeviceName"], "NVIDIA GeForce RTX 5090", "fixture worker device name")
    assert_equal(result["GpuDetails"]["power_details"][0]["max"], 575.0, "fixture GPU power detail")
    assert_equal(
        result["Gpu"]["tests"]["GPU Temperature (Temperature)"][0]["device"],
        "NVIDIA GeForce RTX 5090 [edge]",
        "fixture GPU temp export device",
    )
    assert_equal(
        result["Gpu"]["tests"]["GPU Power (Power)"][0]["results"]["3D Adaptive"]["avg"],
        500.0,
        "fixture GPU power export avg",
    )
    assert_equal(
        result["Cpu"]["tests"]["CPU Package Power (Power)"][0]["results"]["GPU Fixture"]["max"],
        110.0,
        "fixture CPU package power export",
    )
    assert_equal(
        result["Memory"]["tests"]["SPD Hub Temperature (Temperature)"][0]["device"],
        "DIMM 0",
        "fixture memory temp export",
    )
    assert_equal(
        result["Storage"]["tests"]["Drive Temperature (Temperature)"][0]["device"],
        "Smoke NVMe",
        "fixture storage temp export",
    )
    assert_equal(
        result["CpuCores"]["tests"]["Frequency"][0]["Core 0 Clock"]["3D Adaptive"]["avg"],
        5100.0,
        "fixture CPU core frequency export",
    )
    assert_equal(
        result["ReportSummary"]["StageOutcomes"][0]["GpuHighlights"][0]["UsageAvg"],
        95.0,
        "fixture report GPU highlight",
    )
    missing_field_validation = validate_export_contract_compatibility({"Metadata": {}, "ExportContract": {}})
    assert_true(
        any(issue["category"] == "compatibility_shape" for issue in missing_field_validation["issues"]),
        "fixture export validation missing stable fields",
    )
    unsafe_contract = dict(result)
    unsafe_contract["ExportContract"] = dict(result["ExportContract"])
    unsafe_contract["ExportContract"]["RequiresLegacyImporterUpdate"] = True
    unsafe_contract["Metadata"] = dict(result["Metadata"])
    unsafe_contract["Metadata"]["ExportContract"] = dict(unsafe_contract["ExportContract"])
    unsafe_validation = validate_export_contract_compatibility(unsafe_contract)
    assert_true(
        any(issue["category"] == "export_contract" and issue["severity"] == "error" for issue in unsafe_validation["issues"]),
        "fixture export validation requires apps script update",
    )
    missing_report_validation = validate_report_summary_mirror({"Metadata": {}})
    assert_true(
        any(issue["message"] == "ReportSummary is missing" for issue in missing_report_validation["issues"]),
        "fixture report summary validation missing top level",
    )
    assert_true(
        any(issue["message"] == "Metadata.ReportSummary is missing" for issue in missing_report_validation["issues"]),
        "fixture report summary validation missing metadata",
    )
    mismatched_report = dict(result)
    mismatched_report["Metadata"] = dict(result["Metadata"])
    mismatched_report["Metadata"]["ReportSummary"] = dict(result["ReportSummary"])
    mismatched_report["Metadata"]["ReportSummary"]["Result"] = "Different"
    mismatch_validation = validate_report_summary_mirror(mismatched_report)
    assert_equal(
        mismatch_validation["checks"]["report_summary"]["mirror_mismatches"],
        ["Result"],
        "fixture report summary validation mismatch field",
    )
    missing_stability_validation = validate_stability_alignment({}, {})
    assert_true(
        any(issue["message"] == "StabilityInterpretation is missing" for issue in missing_stability_validation["issues"]),
        "fixture stability validation missing top level",
    )
    assert_true(
        any(issue["message"] == "Metadata.Stability.InterpretationSummary is missing" for issue in missing_stability_validation["issues"]),
        "fixture stability validation missing metadata",
    )
    mismatched_stability = dict(result)
    mismatched_stability["Metadata"] = dict(result["Metadata"])
    mismatched_stability["Metadata"]["Stability"] = dict(result["Metadata"]["Stability"])
    mismatched_stability["Metadata"]["Stability"]["InterpretationSummary"] = dict(result["StabilityInterpretation"])
    mismatched_stability["Metadata"]["Stability"]["InterpretationSummary"]["State"] = "different"
    mismatched_stability_validation = validate_stability_alignment(mismatched_stability, result["ReportSummary"])
    assert_equal(
        mismatched_stability_validation["checks"]["stability_alignment"]["metadata_mismatches"],
        ["Metadata.Stability.InterpretationSummary.State"],
        "fixture stability validation metadata mismatch field",
    )
    mismatched_report_stability = dict(result["ReportSummary"])
    mismatched_report_stability["Result"] = "Different"
    report_stability_validation = validate_stability_alignment(result, mismatched_report_stability)
    assert_equal(
        report_stability_validation["checks"]["stability_alignment"]["report_mismatches"],
        ["Result->OverallResult"],
        "fixture stability validation report mismatch field",
    )
    missing_segments_validation = validate_report_stage_counts({"Segments": []}, {})
    assert_true(
        any(issue["category"] == "segments" and issue["severity"] == "error" for issue in missing_segments_validation["issues"]),
        "fixture stage counts missing segments",
    )
    mismatched_stage_count = dict(result)
    mismatched_stage_count["ReportSummary"] = dict(result["ReportSummary"])
    mismatched_stage_count["ReportSummary"]["StageOutcomes"] = [dict(result["ReportSummary"]["StageOutcomes"][0]), {"Label": "Extra"}]
    mismatched_stage_count_validation = validate_report_stage_counts(mismatched_stage_count, mismatched_stage_count["ReportSummary"])
    assert_true(
        any(issue["message"] == "ReportSummary.StageOutcomes count does not match Segments count" for issue in mismatched_stage_count_validation["issues"]),
        "fixture stage counts mismatch",
    )
    bad_action_items = {
        "ActionItemDetails": [
            {"Severity": "warn", "Category": "thermal", "Message": "Check cooling", "Count": 1},
            {"Severity": "", "Category": "", "Message": "", "Count": -1},
        ],
        "ActionItems": ["Check cooling"],
        "ActionItemCategoryCounts": {"thermal": "not-a-number"},
        "ActionItemSeverityCounts": {"warning": 99},
    }
    bad_action_validation = validate_report_action_items(bad_action_items)
    assert_true(
        any(issue["message"] == "Action item detail 2 is missing Severity" for issue in bad_action_validation["issues"]),
        "fixture action item missing severity",
    )
    assert_true(
        any(issue["message"] == "Action item detail 2 is missing Category" for issue in bad_action_validation["issues"]),
        "fixture action item missing category",
    )
    assert_true(
        any(issue["message"] == "Action item detail 2 has negative Count" for issue in bad_action_validation["issues"]),
        "fixture action item negative count",
    )
    assert_true(
        any(issue["message"] == "ReportSummary.ActionItemCategoryCounts has a non-numeric value" for issue in bad_action_validation["issues"]),
        "fixture action item nonnumeric category count",
    )
    assert_true(
        any(issue["message"] == "ReportSummary.ActionItemSeverityCounts does not match ActionItemDetails" for issue in bad_action_validation["issues"]),
        "fixture action item severity count mismatch",
    )
    bad_gpu_worker_summary = dict(result)
    bad_gpu_worker_summary["GpuDetails"] = {
        "validation_details": [
            {
                "Stage": "GPU Fixture",
                "Status": "ok",
                "VerificationPasses": 1,
                "Backend": "python_vulkan_transfer",
                "VerifiedBufferCoveragePercent": 50.0,
                "VerifiedBufferCount": 0,
            }
        ]
    }
    bad_gpu_worker_summary["ReportSummary"] = dict(result["ReportSummary"])
    bad_gpu_worker_summary["ReportSummary"]["GpuWorkerSummary"] = {
        "WorkerResultCount": 2,
        "SuccessfulWorkerResultCount": 0,
        "VerificationPasses": 99,
    }
    bad_gpu_worker_validation = validate_gpu_worker_summary(
        bad_gpu_worker_summary,
        bad_gpu_worker_summary["ReportSummary"],
    )
    bad_gpu_worker_messages = {issue["message"] for issue in bad_gpu_worker_validation["issues"]}
    assert_true(
        "GpuWorkerSummary.WorkerResultCount does not match GpuDetails.validation_details" in bad_gpu_worker_messages,
        "fixture GPU worker count mismatch",
    )
    assert_true(
        "GpuWorkerSummary.SuccessfulWorkerResultCount does not match validation detail statuses" in bad_gpu_worker_messages,
        "fixture GPU worker success mismatch",
    )
    assert_true(
        "GpuWorkerSummary.VerificationPasses does not match validation details" in bad_gpu_worker_messages,
        "fixture GPU worker verification mismatch",
    )
    assert_true(
        "GPU Fixture GPU worker is missing Mode/Workload" in bad_gpu_worker_messages,
        "fixture GPU worker missing mode",
    )
    assert_true(
        "GPU Fixture GPU worker is missing TargetId" in bad_gpu_worker_messages,
        "fixture GPU worker missing target",
    )
    assert_true(
        "GPU Fixture Vulkan transfer worker did not verify its transfer buffer" in bad_gpu_worker_messages,
        "fixture GPU worker transfer coverage mismatch",
    )


def test_compatibility_export_skipped_stage_fixture() -> None:
    exporter = CompatibilityExporter()
    metadata = RunMetadata(dept="Production", case_sku="Smoke", description="Skipped stage fixture")
    system_info = {
        "Hardware": {
            "Cpu": {"Name": "Smoke CPU", "PowerLimits": {}},
            "Motherboard": {},
            "Bios": {},
            "Memory": {"Modules": []},
            "Storage": [],
            "Gpu": [
                {"Name": "AMD Radeon RX 6600 XT", "Interface": "0000:03:00.0", "Card": "card1", "DeviceClass": "discrete"}
            ],
        },
        "TestInfo": {"TestName": "Smoke=Skipped stage fixture", "ProfileName": "Skipped Fixture"},
    }
    segment = {
        "Label": "3D + VRAM Fixture",
        "TestType": "GPU + VRAM",
        "TestDescription": "3D + VRAM Fixture",
        "Verdict": "warning",
        "GpuMetrics": [
            {
                "GpuIndex": 0,
                "Name": "AMD Radeon RX 6600 XT",
                "DisplayName": "AMD Radeon RX 6600 XT",
                "Targeted": True,
                "TargetIds": ["0000:03:00.0"],
                "Workloads": ["gpu_3d"],
                "Usage": {"Min": 70.0, "Avg": 88.0, "Max": 96.0},
                "UsageSustain": {"StdDev": 4.0, "Range": 20.0, "SampleCount": 10},
                "WorkerEvidence": {"VerificationPasses": 4},
            }
        ],
        "StabilityInterpretation": {
            "State": "warning",
            "Result": "warning",
            "OutcomeClass": "worker_verified_telemetry_limited",
            "OutcomeSummary": "Worker verified but telemetry was limited.",
            "PrimaryPurpose": "gpu_vram_integrity",
            "BackendConfidence": "worker_verified",
            "WarningCategoryCounts": {"gpu_vram_telemetry_discrepancy": 1},
            "ErrorCategoryCounts": {},
            "TargetedGpuCount": 1,
            "TargetedLoadQualityCounts": {"high": 1},
        },
    }
    window = StageWindow(
        stage_id="segment_1",
        stage_type="Combined",
        display_name="3D + VRAM Fixture",
        started_iso="2026-05-22T13:00:00-04:00",
        ended_iso="2026-05-22T13:01:30-04:00",
        started_monotonic=0.0,
        ended_monotonic=90.0,
        duration_seconds=90.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="warning",
        worker_results=[
            {
                "kind": "gpu",
                "mode": "gpu_3d",
                "backend": "python_vulkan_compute",
                "status": "ok",
                "gpu_index": 0,
                "target_id": "0000:03:00.0",
                "verification_passes": 4,
            }
        ],
    )
    skipped = [
        {
            "stage_id": "segment_2",
            "label": "SSE + VRAM",
            "reason": "VRAM backend cannot support requested GPU target",
        }
    ]
    result = exporter.build(
        metadata,
        "2026-05-22T13:00:00-04:00",
        "2026-05-22T13:01:30-04:00",
        90.0,
        system_info,
        {"Segments": [segment], "SegmentDetails": {}},
        SimpleNamespace(samples=[], _gpu_sources=[]),
        [window],
        skipped_stages=skipped,
    )
    assert_equal(result["Result"], "Warning", "skipped fixture top-level result")
    assert_equal(result["ExecutionDetail"], "Warning", "skipped fixture execution detail")
    assert_equal(result["ExecutionSummary"]["SkippedStageCount"], 1, "skipped fixture execution summary")
    assert_equal(result["ReportSummary"]["SkippedStageCount"], 1, "skipped fixture report skipped count")
    assert_equal(result["ReportSummary"]["DepartmentUseSummary"]["Status"], "not_ready", "skipped fixture department status")
    assert_true(
        any(item["Category"] == "skipped_stage" for item in result["ReportSummary"]["ActionItemDetails"]),
        "skipped fixture action item",
    )
    assert_true(
        result["ReportSummary"]["StageOutcomes"][0]["CoverageNotes"],
        "skipped fixture GPU+VRAM coverage note",
    )
    assert_equal(
        result["ReportSummary"]["ActionItemCategoryCounts"]["skipped_stage"],
        1,
        "skipped fixture action category count",
    )


def test_compatibility_export_same_model_gpu_ordering_fixture() -> None:
    exporter = CompatibilityExporter()
    system_info = {
        "Hardware": {
            "Cpu": {"Name": "Smoke CPU", "PowerLimits": {}},
            "Motherboard": {},
            "Bios": {},
            "Memory": {"Modules": []},
            "Storage": [],
            "Gpu": [
                {
                    "Name": "NVIDIA GeForce RTX 5090",
                    "Interface": "0000:01:00.0",
                    "Card": "card1",
                    "DriverVersion": "nvidia 575",
                    "Memory": "32 GB",
                    "DeviceClass": "discrete",
                },
                {
                    "Name": "NVIDIA GeForce RTX 5090",
                    "Interface": "0000:02:00.0",
                    "Card": "card2",
                    "DriverVersion": "nvidia 575",
                    "Memory": "32 GB",
                    "DeviceClass": "discrete",
                },
            ],
        },
        "TestInfo": {"TestName": "Same Model GPU Fixture", "ProfileName": "Same Model GPU Fixture"},
    }
    segment = {
        "Label": "Same Model GPU Stage",
        "TestType": "3D Adaptive",
        "TestDescription": "Same Model GPU Stage",
        "Verdict": "pass",
        "Temperatures": {
            "Gpu": {
                "Core": {
                    "Gpus": [
                        {
                            "GpuIndex": 0,
                            "Name": "NVIDIA GeForce RTX 5090",
                            "DisplayName": "NVIDIA GeForce RTX 5090 #1",
                            "SensorName": "edge",
                            "Temperatures": {"Min": 60.0, "Avg": 70.0, "Max": 80.0},
                        },
                        {
                            "GpuIndex": 1,
                            "Name": "NVIDIA GeForce RTX 5090",
                            "DisplayName": "NVIDIA GeForce RTX 5090 #2",
                            "SensorName": "edge",
                            "Temperatures": {"Min": 61.0, "Avg": 71.0, "Max": 81.0},
                        },
                    ]
                }
            }
        },
        "GpuMetrics": [
            {
                "GpuIndex": 0,
                "Name": "NVIDIA GeForce RTX 5090",
                "DisplayName": "NVIDIA GeForce RTX 5090 #1",
                "Targeted": True,
                "TargetIds": ["0000:01:00.0"],
                "Cards": ["card1"],
                "Slots": ["0000:01:00.0"],
                "Workloads": ["gpu_3d"],
                "Backends": ["python_vulkan_compute"],
                "LoadQuality": "high",
                "Power": {"Min": 300.0, "Avg": 500.0, "Max": 600.0},
                "Usage": {"Min": 80.0, "Avg": 95.0, "Max": 100.0},
                "WorkerEvidence": {"VerificationPasses": 8},
            },
            {
                "GpuIndex": 1,
                "Name": "NVIDIA GeForce RTX 5090",
                "DisplayName": "NVIDIA GeForce RTX 5090 #2",
                "Targeted": True,
                "TargetIds": ["0000:02:00.0"],
                "Cards": ["card2"],
                "Slots": ["0000:02:00.0"],
                "Workloads": ["gpu_3d"],
                "Backends": ["python_vulkan_compute"],
                "LoadQuality": "high",
                "Power": {"Min": 290.0, "Avg": 490.0, "Max": 590.0},
                "Usage": {"Min": 78.0, "Avg": 94.0, "Max": 99.0},
                "WorkerEvidence": {"VerificationPasses": 7},
            },
        ],
        "StabilityInterpretation": {
            "State": "clean",
            "Result": "pass",
            "OutcomeClass": "verified_clean",
            "OutcomeSummary": "Synthetic same-model GPU fixture completed cleanly.",
            "PrimaryPurpose": "gpu_stress",
            "BackendConfidence": "worker_verified",
            "WarningCategoryCounts": {},
            "ErrorCategoryCounts": {},
            "TargetedGpuCount": 2,
            "TargetedLoadQualityCounts": {"high": 2},
        },
    }
    window = StageWindow(
        stage_id="segment_1",
        stage_type="3D Adaptive",
        display_name="Same Model GPU Stage",
        started_iso="2026-05-22T14:00:00-04:00",
        ended_iso="2026-05-22T14:01:30-04:00",
        started_monotonic=0.0,
        ended_monotonic=90.0,
        duration_seconds=90.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
        verdict="pass",
        worker_results=[
            {
                "kind": "gpu",
                "mode": "gpu_3d",
                "backend": "python_vulkan_compute",
                "status": "ok",
                "gpu_index": 1,
                "target_id": "0000:02:00.0",
                "slot": "0000:02:00.0",
                "card": "card2",
                "verification_passes": 7,
            },
            {
                "kind": "gpu",
                "mode": "gpu_3d",
                "backend": "python_vulkan_compute",
                "status": "ok",
                "gpu_index": 0,
                "target_id": "0000:01:00.0",
                "slot": "0000:01:00.0",
                "card": "card1",
                "verification_passes": 8,
            },
        ],
    )
    telemetry = SimpleNamespace(
        samples=[
            Sample(1.0, {"gpu_0_power_w": 300.0, "gpu_1_power_w": 290.0}),
            Sample(45.0, {"gpu_0_power_w": 500.0, "gpu_1_power_w": 490.0}),
            Sample(89.0, {"gpu_0_power_w": 600.0, "gpu_1_power_w": 590.0}),
        ],
        _gpu_sources=[
            {"metric": "power_w", "key": "gpu_1_power_w", "label": "card2 PPT", "slot": "0000:02:00.0", "card": "card2", "gpu_index": 1},
            {"metric": "power_w", "key": "gpu_0_power_w", "label": "card1 PPT", "slot": "0000:01:00.0", "card": "card1", "gpu_index": 0},
        ],
    )
    result = exporter.build(
        RunMetadata(dept="Production"),
        "2026-05-22T14:00:00-04:00",
        "2026-05-22T14:01:30-04:00",
        90.0,
        system_info,
        {"Segments": [segment], "SegmentDetails": {}},
        telemetry,
        [window],
    )
    assert_equal(
        [device["gpu_display_name"] for device in result["Gpu"]["devices"]],
        ["NVIDIA GeForce RTX 5090 #1", "NVIDIA GeForce RTX 5090 #2"],
        "same-model GPU device display order",
    )
    assert_equal(
        [item["name"] for item in result["GpuDetails"]["power_details"]],
        ["NVIDIA GeForce RTX 5090 #1", "NVIDIA GeForce RTX 5090 #2"],
        "same-model GPU power detail order",
    )
    assert_equal(
        [item["DeviceName"] for item in result["GpuDetails"]["validation_details"]],
        ["NVIDIA GeForce RTX 5090 #1", "NVIDIA GeForce RTX 5090 #2"],
        "same-model GPU worker detail order",
    )
    assert_equal(
        [item["device"] for item in result["Gpu"]["tests"]["GPU Temperature (Temperature)"]],
        ["NVIDIA GeForce RTX 5090 #1 [edge]", "NVIDIA GeForce RTX 5090 #2 [edge]"],
        "same-model GPU temp device names",
    )
    assert_equal(
        [item["device"] for item in result["Gpu"]["tests"]["GPU Power (Power)"]],
        ["NVIDIA GeForce RTX 5090 #1", "NVIDIA GeForce RTX 5090 #2"],
        "same-model GPU metric device names",
    )
    assert_equal(
        [item["Name"] for item in result["ReportSummary"]["StageOutcomes"][0]["GpuHighlights"]],
        ["NVIDIA GeForce RTX 5090 #1", "NVIDIA GeForce RTX 5090 #2"],
        "same-model GPU report highlight names",
    )


def test_run_summary_text_fixture() -> None:
    exporter = RunSummaryTextExporter()
    text = exporter.build(
        {
            "Started": "2026-05-22T15:00:00-04:00",
            "Ended": "2026-05-22T15:01:30-04:00",
            "Metadata": {"TestName": "Summary Fixture"},
            "ExportContract": {
                "Schema": "linux_validation_suite.compat_export.v1",
                "CompatibilityMode": "legacy_additive",
                "RequiresLegacyImporterUpdate": False,
            },
            "ReportSummary": {
                "Result": "Warning",
                "OutcomeClass": "worker_verified_telemetry_limited",
                "OutcomeSummary": "Worker verified with telemetry caveat.",
                "Elapsed": "00:01:30",
                "WarningCategoryCounts": {"gpu_vram_telemetry_discrepancy": 1},
                "ErrorCategoryCounts": {},
                "ReportOnlyThresholdWouldWarnCount": 2,
                "DepartmentUseSummary": {
                    "Status": "ready_with_warnings",
                    "Decision": "Usable for department validation with documented non-blocking warnings.",
                    "Blocking": False,
                    "Confidence": "worker_verified",
                    "WorkerResultCount": 2,
                    "SuccessfulWorkerResultCount": 2,
                    "WorkerFailureCount": 0,
                    "VerificationPasses": 15,
                    "PrimaryCaveats": ["OS VRAM telemetry under-report (1)"],
                    "OperatorNotes": [
                        "VRAM worker allocation/verification passed; OS VRAM telemetry may under-report shared-memory or driver-managed allocations."
                    ],
                },
                "GpuWorkerSummary": {
                    "WorkerResultCount": 2,
                    "SuccessfulWorkerResultCount": 2,
                    "WorkerFailureCount": 0,
                    "VerificationPasses": 15,
                },
                "ActionItemSeverityCounts": {"info": 1},
                "ActionItemCategoryCounts": {"gpu_vram_telemetry_discrepancy": 1},
                "ActionItemDetails": [
                    {
                        "Severity": "info",
                        "Category": "gpu_vram_telemetry_discrepancy",
                        "Count": 1,
                        "Message": "Original raw warning message.",
                    }
                ],
                "StageOutcomes": [
                    {
                        "Label": "GPU + VRAM",
                        "Verdict": "warning",
                        "OutcomeClass": "worker_verified_telemetry_limited",
                        "PrimaryPurpose": "gpu_plus_vram_saturation",
                        "BackendConfidence": "worker_verified",
                        "TargetedGpuCount": 2,
                        "WarningCategoryCounts": {"gpu_vram_telemetry_discrepancy": 1},
                        "CoverageNotes": ["Separate concurrent VRAM worker omitted for GPU 1."],
                        "GpuHighlights": [
                            {
                                "Name": "NVIDIA GeForce RTX 5090 #1",
                                "UsageAvg": 94.0,
                                "UsageMax": 99.0,
                                "PowerAvgW": 500.0,
                                "PowerMaxW": 580.0,
                                "MemoryBusyAvg": 80.0,
                                "MemoryBusyMax": 90.0,
                                "VramUsedMaxGB": 16.0,
                                "AllocationPercent": 80.0,
                                "VerificationPasses": 8,
                                "Backends": ["python_vulkan_compute"],
                                "TargetIds": ["0000:01:00.0"],
                            }
                        ],
                    }
                ],
            },
        }
    )
    assert_true("Linux Validation Suite Run Summary" in text, "summary title")
    assert_true("Test: Summary Fixture" in text, "summary test name")
    assert_true("Status: Ready with documented warnings" in text, "summary department status")
    assert_true("GPU workers: 2/2 successful, 15 verification passes" in text, "summary worker line")
    assert_true("OS VRAM telemetry under-report: 1" in text, "summary warning category")
    assert_true("Report-only threshold caveats: 2" in text, "summary threshold caveats")
    assert_true("Coverage note: Separate concurrent VRAM worker omitted for GPU 1." in text, "summary coverage note")
    assert_true(
        "NVIDIA GeForce RTX 5090 #1: busy avg 94.00% / max 99.00%; power avg 500.00W / max 580.00W"
        in text,
        "summary GPU highlight",
    )
    assert_true("Severity counts: info=1" in text, "summary action severity counts")
    assert_true(
        "No rerun is required solely for this warning when worker allocation and verification passed"
        in text,
        "summary action message override",
    )
    assert_true("Schema: linux_validation_suite.compat_export.v1" in text, "summary export contract")


def test_run_executor_defaults_and_capture() -> None:
    class Loader:
        def load_profile(self, _path):
            return SimpleNamespace(profile_name="SmokeProfile")

        def load_segment_labels(self, _path, _profile):
            return ["Segment 1"]

    class Orchestrator:
        def make_run_dir(self, profile_name):
            return Path(f"/tmp/lvs_run_executor_{profile_name}")

        def run(self, profile_path, profile, labels, metadata, run_dir=None, **_kwargs):
            print("[phase] 2026-05-29T12:00:00-04:00 | run-start | profile=SmokeProfile")
            print("phase output captured")
            print("[phase] 2026-05-29T12:01:00-04:00 | run-end | elapsed=00:01:00 | verdict=completed")
            print(profile_path.name, profile.profile_name, labels, metadata.case_sku, metadata.description, metadata.dept)
            return run_dir or Path("/tmp/lvs_run_executor_smoke")

    calls = {"telemetry": 0, "heatsoak": 0}

    def default_metadata(_path: Path) -> RunMetadata:
        return RunMetadata(dept="", case_sku="", description="")

    def ensure() -> bool:
        calls["telemetry"] += 1
        return False

    def heatsoak(minutes: float, **_kwargs) -> bool:
        calls["heatsoak"] += 1
        print(f"heatsoak {minutes}")
        return True

    captured_lines = []
    capture = CallbackStringIO(captured_lines.append)
    capture.write("partial")
    capture.write(" line\nnext")
    assert_equal(captured_lines, ["partial line"], "run execution context streams complete lines")
    assert_true("partial line\nnext" in capture.getvalue(), "run execution context capture buffer")
    assert_equal(captured_lines[-1], "next", "run execution context flushes pending line on getvalue")

    context_metadata = RunMetadata(dept="", case_sku="", description="")
    context = build_profile_run_context(
        Path("profiles/Smoke.json"),
        context_metadata,
        None,
        settings=SimpleNamespace(suite_department="Production"),
        profile_loader=Loader(),
        default_run_metadata=default_metadata,
    )
    assert_equal(context.profile.profile_name, "SmokeProfile", "run execution context profile")
    assert_equal(context.labels, ["Segment 1"], "run execution context labels")
    assert_equal(context.metadata.case_sku, "Unknown", "run execution context default case")
    assert_equal(context.metadata.description, "SmokeProfile", "run execution context default description")
    assert_equal(context.metadata.dept, "Production", "run execution context default department")

    executor = RunExecutor(
        settings=SimpleNamespace(suite_department="Production"),
        profile_loader=Loader(),
        orchestrator=Orchestrator(),
        default_run_metadata=default_metadata,
        ensure_enhanced_telemetry_ready=ensure,
        run_heatsoak_if_requested=heatsoak,
    )
    streamed_lines = []
    streamed_events = []
    result = executor.run_profile_capture_output(
        Path("profiles/Smoke.json"),
        heatsoak_minutes=1.5,
        output_callback=streamed_lines.append,
        progress_callback=streamed_events.append,
    )
    assert_equal(result.run_dir, Path("/tmp/lvs_run_executor_smoke"), "run executor run dir")
    assert_equal(result.metadata.case_sku, "Unknown", "run executor default case")
    assert_equal(result.metadata.description, "SmokeProfile", "run executor default description")
    assert_equal(result.metadata.dept, "Production", "run executor default department")
    assert_equal(calls, {"telemetry": 1, "heatsoak": 1}, "run executor callbacks")
    assert_true("phase output captured" in result.output, "run executor stdout capture")
    assert_true("phase output captured" in streamed_lines, "run executor streamed stdout line")
    assert_true("heatsoak 1.5" in streamed_lines, "run executor streamed heatsoak line")
    assert_equal(len(result.progress_events), 4, "run executor progress event count")
    assert_equal(result.progress_events[0].event_type, "heatsoak-start", "run executor heatsoak start event")
    assert_equal(result.progress_events[1].event_type, "heatsoak-end", "run executor heatsoak end event")
    assert_equal(result.progress_events[-1].event_type, "run-end", "run executor progress event type")
    assert_true(result.run_status is not None, "run executor final status")
    assert_equal(result.run_status.status, "run_complete", "run executor final status state")
    assert_equal(result.run_status.verdict, "completed", "run executor final status verdict")
    assert_equal(result.run_status.profile, "SmokeProfile", "run executor final status profile")
    assert_equal(streamed_events[-1].fields.get("verdict"), "completed", "run executor streamed event fields")

    class DirectOrchestrator:
        def make_run_dir(self, profile_name):
            return Path(f"/tmp/lvs_run_executor_direct_{profile_name}")

        def run(self, profile_path, profile, labels, metadata, run_dir=None, **_kwargs):
            self.run_args = (profile_path, profile, labels, metadata, run_dir)
            return run_dir or Path("/tmp/lvs_run_executor_direct")

    direct_calls = {"telemetry": 0, "heatsoak": 0}
    direct_debug_paths = []
    direct_orchestrator = DirectOrchestrator()
    direct_executor = RunExecutor(
        settings=SimpleNamespace(suite_department="Production"),
        profile_loader=Loader(),
        orchestrator=direct_orchestrator,
        default_run_metadata=default_metadata,
        ensure_enhanced_telemetry_ready=lambda: direct_calls.update(telemetry=direct_calls["telemetry"] + 1) or False,
        run_heatsoak_if_requested=lambda minutes, **_kwargs: direct_calls.update(heatsoak=direct_calls["heatsoak"] + 1) or True,
    )
    direct_metadata = RunMetadata(dept="", case_sku="", description="", advanced_debug_logging=True)
    direct_run_dir = direct_executor.run_profile_direct(
        Path("profiles/Smoke.json"),
        metadata=direct_metadata,
        heatsoak_minutes=2.0,
        heatsoak_debug_callback=direct_debug_paths.append,
    )
    assert_equal(direct_run_dir, Path("/tmp/lvs_run_executor_direct_SmokeProfile"), "direct run executor run dir")
    assert_equal(direct_metadata.case_sku, "Unknown", "direct run executor default case")
    assert_equal(direct_metadata.description, "SmokeProfile", "direct run executor default description")
    assert_equal(direct_metadata.dept, "Production", "direct run executor default department")
    assert_equal(direct_calls, {"telemetry": 1, "heatsoak": 1}, "direct run executor callbacks")
    assert_equal(
        direct_debug_paths,
        [Path("/tmp/lvs_run_executor_direct_SmokeProfile/advanced_debug/heatsoak")],
        "direct run executor heatsoak debug callback",
    )
    assert_equal(direct_orchestrator.run_args[2], ["Segment 1"], "direct run executor labels")
    heatsoak_run_dir, heatsoak_debug = build_heatsoak_debug(direct_orchestrator, "SmokeProfile")
    assert_equal(heatsoak_run_dir, Path("/tmp/lvs_run_executor_direct_SmokeProfile"), "run execution context heatsoak dir")
    assert_true(heatsoak_debug is not None, "run execution context heatsoak debug logger")

    class CliStyleHeatsoak:
        def __init__(self) -> None:
            self.calls = []

        def run(self, minutes=None, *, advanced_debug=None):
            self.calls.append((minutes, advanced_debug is not None))
            return True

    cli_heatsoak = CliStyleHeatsoak()
    cli_style_executor = RunExecutor(
        settings=SimpleNamespace(suite_department="Production"),
        profile_loader=Loader(),
        orchestrator=DirectOrchestrator(),
        default_run_metadata=default_metadata,
        ensure_enhanced_telemetry_ready=lambda: True,
        run_heatsoak_if_requested=cli_heatsoak.run,
    )
    cli_style_executor.run_profile_direct(
        Path("profiles/Smoke.json"),
        metadata=RunMetadata(advanced_debug_logging=True),
        heatsoak_minutes=3.0,
    )
    assert_equal(cli_heatsoak.calls[0][0], 3.0, "direct run bound heatsoak minutes")
    assert_true(cli_heatsoak.calls[0][1], "direct run bound heatsoak debug logger")

    launcher = RunLaunchCoordinator(direct_executor)
    launched_metadata = RunMetadata(dept="", case_sku="", description="")
    launched_dir = launcher.run_direct(
        Path("profiles/Smoke.json"),
        metadata=launched_metadata,
        heatsoak_minutes=0.0,
    )
    assert_equal(launched_dir, Path("/tmp/lvs_run_executor_direct"), "run launcher direct dir")
    assert_equal(launched_metadata.description, "SmokeProfile", "run launcher direct metadata defaults")
    captured = launcher.run_capture(Path("profiles/Smoke.json"), heatsoak_minutes=0.0)
    assert_equal(captured.run_dir, Path("/tmp/lvs_run_executor_direct"), "run launcher capture dir")
    assert_equal(captured.metadata.description, "SmokeProfile", "run launcher capture metadata defaults")
    prepared_metadata = RunMetadata(dept="", case_sku="", description="")
    prepared_setup = RunSetupState(
        profile_path=Path("profiles/Prepared.json"),
        metadata=prepared_metadata,
        profile=SimpleNamespace(profile_name="PreparedProfile"),
        labels=["Prepared Segment"],
        heatsoak_minutes=0.0,
    )
    prepared_request = RunLaunchRequest.from_setup(prepared_setup)
    prepared_dir = launcher.run_prepared_direct(prepared_request)
    assert_equal(prepared_dir, Path("/tmp/lvs_run_executor_direct"), "run launcher prepared direct dir")
    assert_equal(prepared_metadata.description, "PreparedProfile", "run launcher prepared direct metadata defaults")
    assert_equal(direct_orchestrator.run_args[2], ["Prepared Segment"], "run launcher prepared direct labels")
    prepared_capture = launcher.run_prepared_capture(RunLaunchRequest.from_setup(prepared_setup))
    assert_equal(prepared_capture.run_dir, Path("/tmp/lvs_run_executor_direct"), "run launcher prepared capture dir")
    assert_equal(prepared_capture.metadata.description, "PreparedProfile", "run launcher prepared capture metadata")

    class FailingOrchestrator(Orchestrator):
        def run(self, profile_path, profile, labels, metadata, run_dir=None, **_kwargs):
            print("[phase] 2026-05-29T12:00:00-04:00 | run-start | profile=SmokeProfile")
            print("[phase] 2026-05-29T12:00:05-04:00 | stage-start | stage=Power")
            raise RuntimeError("synthetic failure")

    failing = RunExecutor(
        settings=SimpleNamespace(suite_department="Production"),
        profile_loader=Loader(),
        orchestrator=FailingOrchestrator(),
        default_run_metadata=default_metadata,
        ensure_enhanced_telemetry_ready=ensure,
        run_heatsoak_if_requested=lambda minutes, **_kwargs: True,
    )
    try:
        failing.run_profile_capture_output(Path("profiles/Smoke.json"))
        raise AssertionError("expected RunExecutionError")
    except RunExecutionError as exc:
        assert_true("synthetic failure" in str(exc), "run executor failure message")
        assert_true("stage-start" in exc.output, "run executor failure captured output")
        assert_equal(exc.progress_events[-1].event_type, "run-error", "run executor failure event")
        assert_equal(exc.run_status.status, "run_failed", "run executor failure status")
        assert_equal(exc.run_status.verdict, "failed", "run executor failure verdict")


def test_cli_run_heatsoak_reaches_prepared_launch() -> None:
    profile_path = Path("profiles/HeatsoakSmoke.json")
    profile = ValidationProfile(
        profile_name="HeatsoakSmoke",
        stages=[StageConfig(id="segment_1", name="CPU", duration_seconds=60)],
    )
    labels = ["CPU"]

    class ProfileLoaderStub:
        def list_profiles(self):
            return [profile_path]

    class RunFlowStub:
        def __init__(self) -> None:
            self.prepared_setup = None

        def inspect_profile(self, path):
            readiness = SimpleNamespace(profile=profile, labels=list(labels), validation={"errors": [], "warnings": []})
            return SimpleNamespace(readiness=readiness, errors=[], warnings=[], blocked=False)

        def prepare_setup_run(self, readiness, setup, save_blocked_report=True):
            self.prepared_setup = setup
            return SimpleNamespace(
                preflight_decision=SimpleNamespace(report={"enabled_stage_count": 1, "runnable_stage_count": 1}),
                preflight_action=SimpleNamespace(errors=[], warnings=[], blocked=False, skip_notice=None),
                launch_request=RunLaunchRequest.from_setup(setup),
            )

    class RunLauncherStub:
        def __init__(self) -> None:
            self.request = None
            self.callback_path = None
            self.capture_called = False

        def run_prepared_capture(
            self,
            request,
            *,
            output_callback=None,
            progress_callback=None,
            cancel_check=None,
            operator_stop_source="cli",
        ):
            self.request = request
            self.capture_called = True
            return RunResult(
                run_dir=Path("/tmp/heatsoak-run"),
                output="",
                metadata=request.metadata,
            )

        def run_prepared_direct(self, request, *, heatsoak_debug_callback=None):
            self.request = request
            if heatsoak_debug_callback is not None:
                self.callback_path = Path("/tmp/heatsoak-debug")
            return Path("/tmp/heatsoak-run")

    class FakeLauncher:
        def __init__(self) -> None:
            self._pending_heatsoak_minutes = 0.0
            self.profile_loader = ProfileLoaderStub()
            self.run_flow = RunFlowStub()
            self.run_launcher = RunLauncherStub()
            self.settings_manager = SimpleNamespace(settings=SimpleNamespace(suite_department="QA", prompt_for_wall_wattage=False))
            self.run_setup_manager = RunSetupManager(lambda: self.settings_manager.settings, self.profile_loader, lambda: "Production")
            self.profile_cli = SimpleNamespace(_normalize_profile_labels=lambda profile, labels: list(labels), profile_audit=lambda: None)
            self.upload_prompt = None
            self.upload_cli = SimpleNamespace(post_run_google_drive_prompt=lambda run_dir: setattr(self, "upload_prompt", run_dir))
            self.post_run_manager = SimpleNamespace()
            self.inputs = iter(["1", "3", "7.5", "u"])
            self.saved_history = None
            self.wall_prompt = None

        def _input(self, prompt):
            return next(self.inputs)

        def _profile_choice_text(self, path):
            return path.name

        def _run_setup_review(self, selected_profile_path, selected_profile, selected_labels):
            return self.run_setup_cli._run_setup_review(selected_profile_path, selected_profile, selected_labels)

        def _feature_enabled(self, name):
            return False

        def _maybe_recall_run_setup_history(self, metadata):
            return metadata

        def _run_overrides_menu(self, profile):
            raise AssertionError("stage override menu should not be reached")

        def _maybe_edit_labels(self, current_labels):
            return list(current_labels)

        def _select_case_sku(self, current):
            return current

        def _select_psu_rating(self, current):
            return current

        def _select_cpu_cooler(self, current):
            return current

        def _enter_power_limit(self, current):
            return current

        def _enter_description(self, current):
            return current

        def _enter_heatsoak_minutes(self, current=0.0):
            return self.run_setup_cli._enter_heatsoak_minutes(current)

        def _enter_psu_wattage(self, current):
            return current

        def _enter_fan_type(self, fan_type, fan_details):
            return fan_type, fan_details

        def _enter_fan_details(self, current):
            return current

        def _print_profile_execution_summary(self, preflight):
            self.preflight_summary = preflight

        def post_run_wall_wattage_prompt(self, run_dir, metadata):
            self.wall_prompt = (run_dir, metadata)

        def _save_run_setup_history(self, path, selected_profile, metadata, *, heatsoak_minutes=0.0):
            self.saved_history = (path, selected_profile, metadata, heatsoak_minutes)

    launcher = FakeLauncher()
    launcher.run_setup_cli = RunSetupCliAdapter(launcher)
    original_live_run_supported = cli_run_module.cli_live_run_supported
    cli_run_module.cli_live_run_supported = lambda stream: True
    try:
        RunCliAdapter(launcher).new_run()
    finally:
        cli_run_module.cli_live_run_supported = original_live_run_supported

    request = launcher.run_launcher.request
    assert_true(request is not None, "CLI heatsoak launch request created")
    assert_true(launcher.run_launcher.capture_called, "CLI heatsoak uses prepared capture launch")
    assert_equal(request.heatsoak_minutes, 7.5, "CLI heatsoak minutes carried to launch request")
    assert_equal(launcher._pending_heatsoak_minutes, 7.5, "CLI pending heatsoak updated")
    assert_true(launcher.run_flow.prepared_setup is request.setup, "CLI heatsoak prepared setup used for launch")
    assert_equal(request.setup.heatsoak_minutes, 7.5, "CLI heatsoak setup preserved")
    assert_equal(request.metadata.dept, "QA", "CLI heatsoak setup department normalized")
    assert_equal(launcher.upload_prompt, Path("/tmp/heatsoak-run"), "CLI heatsoak post-run upload hook reached")
    assert_equal(launcher.saved_history[0], profile_path, "CLI heatsoak history saved after run")
    assert_equal(launcher.saved_history[3], 7.5, "CLI heatsoak saved to run setup history")


def test_cli_heatsoak_cancel_plumbing_and_screen_refresh() -> None:
    cancel_requested = lambda: True

    class AdapterStub:
        def __init__(self) -> None:
            self.calls = []

        def _run_heatsoak_if_requested(self, minutes=None, *, advanced_debug=None, cancel_check=None):
            self.calls.append((minutes, advanced_debug, cancel_check))
            return True

    class CompatHost(HeatsoakCompatibilityMixin):
        def __init__(self) -> None:
            self.adapter = AdapterStub()

        def _run_setup_cli_adapter(self):
            return self.adapter

    host = CompatHost()
    assert_true(
        host._run_heatsoak_if_requested(1.25, cancel_check=cancel_requested),
        "CLI heatsoak compatibility accepts cancel_check",
    )
    assert_equal(host.adapter.calls[0][0], 1.25, "CLI heatsoak compatibility forwards minutes")
    assert_true(
        host.adapter.calls[0][2] is cancel_requested,
        "CLI heatsoak compatibility forwards cancel callback",
    )

    adapter = RunSetupCliAdapter(
        SimpleNamespace(
            _pending_heatsoak_minutes=0.0,
            orchestrator=SimpleNamespace(),
        )
    )
    assert_true(
        adapter._run_heatsoak_if_requested(0.0, cancel_check=cancel_requested),
        "CLI run setup heatsoak bridge accepts cancel_check on no-heatsoak path",
    )

    class FakeStream(io.StringIO):
        def __init__(self, tty: bool) -> None:
            super().__init__()
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    previous_term = os.environ.get("TERM")
    os.environ["TERM"] = "xterm"
    try:
        tty_stream = FakeStream(True)
        assert_true(cli_screen_refresh_supported(tty_stream), "CLI screen refresh supports TTY streams")
        assert_true(clear_cli_screen(tty_stream), "CLI screen refresh clears TTY streams")
        assert_equal(tty_stream.getvalue(), "\033[H\033[J", "CLI screen refresh ANSI sequence")

        pipe_stream = FakeStream(False)
        assert_true(not cli_screen_refresh_supported(pipe_stream), "CLI screen refresh skips non-TTY streams")
        assert_true(not clear_cli_screen(pipe_stream), "CLI screen refresh no-ops for non-TTY streams")
        assert_equal(pipe_stream.getvalue(), "", "CLI screen refresh preserves non-TTY output")
    finally:
        if previous_term is None:
            os.environ.pop("TERM", None)
        else:
            os.environ["TERM"] = previous_term


def test_compact_cli_preflight_summary() -> None:
    report = {
        "profile_name": "Smoke",
        "runnable": True,
        "enabled_stage_count": 2,
        "runnable_stage_count": 2,
        "validation": {"errors": [], "warnings": ["profile warning", "second warning"]},
        "plan": [
            {
                "label": "Power",
                "warnings": ["gpu backend fallback", "telemetry missing"],
                "issues": [],
                "gpu_workers": [{"backend": "python_vulkan_compute", "target_id": "0000:01:00.0"}],
            },
            {
                "label": "GPU",
                "warnings": [],
                "issues": [],
                "commands": ["very long backend command body"],
            },
        ],
    }
    text = compact_cli_preflight_summary(report)
    assert_true("Run Preflight" in text, "compact CLI preflight heading")
    assert_true("Runnable: yes" in text, "compact CLI preflight runnable")
    assert_true("Stages: 2/2 runnable" in text, "compact CLI preflight stage count")
    assert_true("Issues: 0 blocking, 2 warning" in text, "compact CLI preflight issue counts")
    assert_true("Power: 0 issue(s), 2 warning(s)" in text, "compact CLI preflight stage warning summary")
    assert_true("python_vulkan_compute" not in text, "compact CLI preflight omits backend detail")
    assert_true("very long backend command body" not in text, "compact CLI preflight omits command detail")
    assert_true("Dry Run / Diagnostics" in text, "compact CLI preflight points to full details")
    inferred_text = compact_cli_preflight_summary({"enabled_stage_count": 1, "runnable_stage_count": 1})
    assert_true("Runnable: yes" in inferred_text, "compact CLI preflight infers runnable when explicit flag is absent")

    blocked = dict(report)
    blocked["runnable"] = False
    blocked["validation"] = {"errors": ["missing backend"], "warnings": []}
    blocked_text = compact_cli_preflight_summary(blocked, report_dir=Path("/tmp/preflight"))
    assert_true("[error] missing backend" in blocked_text, "compact CLI preflight includes blocking issue")
    assert_true("/tmp/preflight" in blocked_text, "compact CLI preflight includes saved blocked report path")


def test_post_run_and_heatsoak_helpers() -> None:
    post_run = PostRunManager(settings=SimpleNamespace(), summary_exporter=SimpleNamespace(build=lambda payload: "summary"))
    assert_equal(post_run.normalize_wall_wattage("742 W"), "742W", "wall wattage normalization")
    assert_equal(post_run.normalize_wall_wattage("skip"), "", "wall wattage skip")
    with TemporaryDirectory(dir="/tmp") as tmp:
        result_dir = Path(tmp)
        JsonStore.write(result_dir / "parsed_results_custom.json", {"Metadata": {}})
        metadata = RunMetadata(
            wall_wattage="",
            case_sku="Case",
            description="Desc",
            advanced_debug_logging=True,
        )
        saved = post_run.save_wall_wattage(result_dir, metadata, "812W")
        assert_equal(saved, "812W", "post-run wall wattage saved")
        parsed = JsonStore.read(result_dir / "parsed_results_custom.json", {})
        assert_equal(parsed["Metadata"]["MaxWallWattage"], "812W", "post-run metadata wattage")
        assert_true(parsed["Metadata"]["AdvancedDebugLogging"], "post-run debug metadata preserved")
        handled_saved = post_run.handle_wall_wattage_input(result_dir, metadata, "900")
        assert_equal(handled_saved.normalized, "900W", "post-run handled wattage normalized")
        assert_true(handled_saved.saved, "post-run handled wattage saved flag")
        assert_equal(handled_saved.message, "Wall wattage saved: 900W", "post-run handled wattage saved message")
        handled_skip = post_run.handle_wall_wattage_input(result_dir, metadata, "")
        assert_true(handled_skip.skipped, "post-run handled wattage skipped flag")
        assert_equal(handled_skip.message, "Wall wattage skipped.", "post-run handled wattage skipped message")
        handled_invalid = post_run.handle_wall_wattage_input(result_dir, metadata, "not-a-number")
        assert_true(not handled_invalid.saved and not handled_invalid.skipped, "post-run handled wattage invalid flags")
        assert_equal(
            handled_invalid.message,
            "Invalid wall wattage. Leaving result unchanged.",
            "post-run handled wattage invalid message",
        )
        complete = post_run.run_complete_outcome(result_dir, "summary text")
        assert_equal(complete.status, "Run complete", "post-run complete status")
        assert_true("Result folder:" in complete.text and "summary text" in complete.text, "post-run complete text")
        prompt = post_run.wall_wattage_prompt_outcome(result_dir, complete.text)
        assert_equal(prompt.status, "Run complete | Waiting for wall wattage", "post-run wattage prompt status")
        assert_true("Post-Run Wall Wattage" in prompt.text, "post-run wattage prompt text")
        handled = post_run.wall_wattage_result_outcome(result_dir, "900", "900W", complete.text)
        assert_equal(handled.status, "Run complete | Wall wattage handled", "post-run wattage result status")
        assert_true("Wall wattage saved: 900W" in handled.text, "post-run wattage result text")
        upload_prompt = post_run.upload_prompt_outcome(result_dir, complete.text)
        assert_equal(upload_prompt.status, "Run complete | Waiting for upload choice", "post-run upload prompt status")
        skipped = post_run.upload_skipped_outcome(complete.text)
        assert_equal(skipped.status, "Run complete | Upload skipped", "post-run upload skipped status")
        upload_result = post_run.upload_result_outcome({"result": "success", "uploaded_count": 2, "file_count": 2})
        assert_equal(upload_result.status, "Google Drive upload success", "post-run upload result status")
        not_ready_attempt = post_run.attempt_upload_result_folder(result_dir, {"ready": False, "missing": ["credentials"]})
        assert_true(not not_ready_attempt.ready, "post-run upload attempt not ready")
        assert_equal(not_ready_attempt.payload, {}, "post-run upload attempt not ready payload")
        post_run.upload_result_folder = lambda path: {"result": "success", "uploaded_count": 1, "file_count": 1}  # type: ignore[method-assign]
        ready_attempt = post_run.attempt_upload_result_folder(result_dir, {"ready": True})
        assert_true(ready_attempt.ready, "post-run upload attempt ready")
        assert_equal(ready_attempt.payload["result"], "success", "post-run upload attempt payload")
    post_run.google_drive_readiness = lambda: {  # type: ignore[method-assign]
        "credential_exists": True,
        "credential_path": "settings/secrets/google-credentials.json",
        "shared_drive_id_configured": True,
        "dns_ok": True,
        "python_modules": {"googleapiclient.discovery": False},
        "ready": False,
        "missing": ["googleapiclient.discovery"],
    }
    readiness_text = post_run.google_drive_readiness_text()
    assert_true("Google Drive Upload Readiness" in readiness_text, "post-run drive readiness heading")
    assert_true("googleapiclient.discovery: missing" in readiness_text, "post-run drive readiness module")

    heatsoak = HeatsoakManager(orchestrator=SimpleNamespace())
    stage = heatsoak.build_heatsoak_stage(90)
    assert_equal(stage.id, "heatsoak", "heatsoak stage id")
    assert_equal(stage.name, "Combined", "heatsoak stage type")
    assert_true(stage.modules.cpu.enabled, "heatsoak CPU enabled")
    assert_equal(stage.modules.cpu.instruction_set, "avx", "heatsoak CPU instruction set")
    assert_true(stage.modules.gpu_3d.enabled, "heatsoak GPU enabled")
    assert_equal(stage.modules.gpu_3d.backend_preference, "auto", "heatsoak GPU backend")
    assert_equal(stage.modules.gpu_3d.compute_variant, "stress_hash", "heatsoak GPU variant")


def test_run_setup_metadata_specs() -> None:
    class Loader:
        def load_profile(self, _path):
            return ValidationProfile(
                profile_name="SetupSmoke",
                stages=[
                    StageConfig(
                        id="segment_1",
                        name="CPU",
                        duration_seconds=300,
                        enabled=True,
                    )
                ],
            )

        def load_segment_labels(self, _path, profile):
            return ["CPU"]

    history_settings_dir = Path("/tmp") / f"lvs_run_setup_history_smoke_{os.getpid()}"
    history_settings_dir.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        suite_department="Production",
        settings_dir=str(history_settings_dir),
        case_options=["Case A", "Other"],
        psu_rating_options=["Gold", "Skip"],
        cpu_cooler_options=["Tower", "Skip"],
    )
    from Modules.lvs_run_setup import RunSetupManager

    manager = RunSetupManager(lambda: settings, Loader(), lambda: "Production")
    setup = manager.create_run_setup(Path("profiles/SetupSmoke.json"))
    assert_equal(manager.input_field_for_key("3"), "heatsoak_minutes", "run setup key to field")
    assert_equal(manager.picker_key_for_key("7"), "cpu_cooler", "run setup key to picker")
    assert_equal(manager.setup_action_for_key("1").action, "picker", "run setup picker action")
    assert_equal(manager.setup_action_for_key("1").target, "case_sku", "run setup picker target")
    assert_equal(manager.setup_action_for_key("6").action, "power_limit_picker", "run setup power limit action")
    assert_equal(manager.setup_action_for_key("d").action, "toggle_debug_logging", "run setup debug toggle action")
    assert_equal(manager.setup_action_for_key("o").action, "stage_override_picker", "run setup stage override action")
    assert_equal(manager.setup_action_for_key("2").target, "description", "run setup input action target")
    assert_equal(manager.input_spec("psu_wattage").label, "PSU wattage", "run setup input label")
    picker = manager.option_picker_spec(setup, "case_sku")
    assert_equal(picker.title, "Case/SKU", "run setup picker title")
    assert_equal(picker.options, ["Case A", "Other"], "run setup picker options")
    assert_equal(manager.power_limit_vendor_picker_spec().options, ["Auto", "Intel", "AMD", "Other/Unknown"], "power limit vendors")
    assert_equal(manager.amd_power_limit_type_picker_spec().options, ["PPT", "TDP", "Other"], "AMD power limit options")
    setup_summary = manager.run_setup_summary_text(setup)
    assert_true("Current Run\n-----------" in setup_summary, "run setup current section")
    assert_true("Configuration\n-------------" in setup_summary, "run setup configuration section")
    assert_true("Setup Controls\n--------------" in setup_summary, "run setup controls section")
    assert_true("- 6 Power limit picker" in setup_summary, "run setup power limit control")
    assert_true("- D Advanced debug logging toggle" in setup_summary, "run setup debug control")
    assert_true("Segments\n--------" in setup_summary, "run setup segments section")
    setup_overview = manager.run_setup_overview_text(setup)
    assert_true("System Configuration\n--------------------" in setup_overview, "run setup overview configuration")
    assert_true("Total: 1 | Enabled: 1 | Disabled: 0" in setup_overview, "run setup overview stage counts")
    assert_true("1. CPU: 300s, enabled, trim 30/30s" in setup_overview, "run setup overview stage detail")
    assert_true("Setup Controls\n--------------" not in setup_overview, "run setup overview omits control duplication")
    action_specs = manager.setup_action_specs(setup)
    assert_equal([action.key for action in action_specs[:9]], ["1", "2", "3", "4", "5", "6", "7", "8", "9"], "production run setup action order")
    assert_equal(action_specs[0].label, "Case/SKU", "run setup first action label")
    assert_equal(action_specs[1].label, "Description", "run setup second action label")
    assert_equal(action_specs[1].detail, "SetupSmoke", "run setup description action detail")
    assert_true(any(action.label == "Case/SKU" and action.detail == "Not Set" for action in action_specs), "run setup unset action detail")
    assert_true(any(action.label == "Review and run" and action.detail == "SetupSmoke" for action in action_specs), "run setup review detail")
    assert_true(any(action.action == "toggle_debug_logging" and action.detail == "Disabled" for action in action_specs), "run setup debug action spec")
    assert_true(any(action.action == "stage_override_picker" for action in action_specs), "run setup stage action spec")
    assert_true(any(action.action == "run_selected" for action in action_specs), "run setup run action spec")
    case_action = next(action for action in action_specs if action.target == "case_sku")
    case_detail = manager.setup_action_detail_text(setup, case_action)
    assert_true("Selected Action\n---------------" in case_detail, "setup action detail heading")
    assert_true("1 - Case/SKU" in case_detail, "setup action detail key label")
    assert_true("Options: Case A, Other" in case_detail, "setup action detail options")
    assert_true("OEM/Other selections open text entry" in case_detail, "setup action detail case note")
    stage_action = next(action for action in action_specs if action.action == "stage_override_picker")
    stage_detail = manager.setup_action_detail_text(setup, stage_action)
    assert_true("Stages enabled: 1/1" in stage_detail, "setup action detail stage count")
    run_action = next(action for action in action_specs if action.action == "run_selected")
    run_detail = manager.setup_action_detail_text(setup, run_action)
    assert_true("Opens the two-step run confirmation screen" in run_detail, "setup action detail run note")
    debug_action = next(action for action in action_specs if action.action == "toggle_debug_logging")
    assert_true("GPU dropouts" in manager.setup_action_detail_text(setup, debug_action), "setup action detail debug note")
    assert_true(manager.toggle_advanced_debug_logging(setup), "run setup debug toggle on")
    assert_true(setup.metadata.advanced_debug_logging, "run setup debug metadata")
    setup.metadata.case_sku = "Case A"
    setup.metadata.description = "History Smoke"
    setup.metadata.psu_wattage = "850W"
    setup.heatsoak_minutes = 6.5
    manager.save_run_setup_history(
        setup.profile_path,
        setup.profile,
        setup.metadata,
        heatsoak_minutes=setup.heatsoak_minutes,
    )
    history_entries = manager.run_setup_history_entries()
    assert_equal(len(history_entries), 1, "run setup history entry count")
    assert_equal(history_entries[0].case_sku, "Case A", "run setup history case")
    assert_equal(history_entries[0].description, "History Smoke", "run setup history description")
    assert_equal(history_entries[0].heatsoak_minutes, 6.5, "run setup history heatsoak entry")
    restored = manager.create_run_setup(Path("profiles/SetupSmoke.json"))
    manager.apply_run_setup_history_entry(restored, history_entries[0])
    assert_equal(restored.metadata.case_sku, "Case A", "run setup history apply case")
    assert_equal(restored.metadata.wall_wattage, "", "run setup history clears wall wattage")
    assert_equal(restored.heatsoak_minutes, 6.5, "run setup history restores heatsoak")
    manager.save_run_setup_history(
        setup.profile_path,
        setup.profile,
        setup.metadata,
        heatsoak_minutes=setup.heatsoak_minutes,
    )
    assert_equal(len(manager.raw_run_setup_history()), 1, "run setup history dedupe")
    legacy = manager.create_run_setup(Path("profiles/SetupSmoke.json"))
    manager.apply_run_setup_history_entry(
        legacy,
        RunSetupHistoryEntry(
            index=2,
            saved="",
            profile_name="Legacy",
            profile_file="Legacy.json",
            case_sku="Case",
            description="Legacy",
            psu_wattage="",
            metadata=RunMetadata(case_sku="Case", description="Legacy"),
        ),
    )
    assert_equal(legacy.heatsoak_minutes, 0.0, "legacy run setup history keeps heatsoak disabled")

    controller_events = {"heatsoak": 0.0, "stage": 0, "labels": 0, "messages": []}
    controller = RunSetupActionController(
        manager,
        RunSetupPromptCallbacks(
            load_history=lambda metadata: metadata,
            stage_overrides=lambda profile: controller_events.update(stage=controller_events["stage"] + 1),
            edit_labels=lambda labels: controller_events.update(labels=controller_events["labels"] + 1) or ["Renamed CPU"],
            select_case_sku=lambda current: "Case A",
            select_psu_rating=lambda current: "Gold",
            select_cpu_cooler=lambda current: "Tower",
            enter_power_limit=lambda current: "Auto",
            enter_description=lambda current: "Controller Smoke",
            enter_heatsoak_minutes=lambda current: 12.5,
            enter_psu_wattage=lambda current: "",
            enter_fan_type=lambda fan_type, fan_details: ("PWM", "120mm"),
            enter_fan_details=lambda current: "front intake",
            enter_raw=lambda label: "raw value",
            normalize_labels=lambda profile, labels: list(labels),
            department=lambda: "RND",
            update_pending_heatsoak=lambda minutes: controller_events.update(heatsoak=minutes),
            notify=lambda message: controller_events["messages"].append(message),
        ),
    )
    controller_setup = manager.create_run_setup(Path("profiles/SetupSmoke.json"))
    controller.handle_action(controller_setup, manager.setup_action_for_key("2"))
    assert_equal(controller_setup.metadata.description, "Controller Smoke", "controller description action")
    controller.handle_action(controller_setup, manager.setup_action_for_key("3"))
    assert_equal(controller_setup.heatsoak_minutes, 12.5, "controller heatsoak action")
    assert_equal(controller_events["heatsoak"], 12.5, "controller heatsoak callback")
    controller_setup.metadata.psu_rating = "Gold"
    controller.handle_action(controller_setup, manager.setup_action_for_key("4"))
    assert_equal(controller_setup.metadata.psu_wattage, "", "controller PSU wattage clear")
    assert_equal(controller_setup.metadata.psu_rating, "", "controller PSU rating clear")
    controller.handle_action(controller_setup, manager.setup_action_for_key("d"))
    assert_true(controller_setup.metadata.advanced_debug_logging, "controller debug toggle")
    assert_true("Advanced debug logging enabled" in controller_events["messages"][-1], "controller debug message")
    controller.handle_action(controller_setup, manager.setup_action_for_key("l"))
    assert_equal(controller_setup.labels, ["Renamed CPU"], "controller label action")
    controller_run_action = next(action for action in manager.setup_action_specs(controller_setup) if action.action == "run_selected")
    finalized = controller.handle_action(controller_setup, controller_run_action)
    assert_true(finalized is controller_setup.metadata, "controller final metadata object")
    assert_equal(finalized.dept, "RND", "controller department normalization")

    review_setup = manager.create_run_setup(Path("profiles/SetupSmoke.json"))
    review_controller = RunSetupReviewController(
        manager,
        review_setup,
        RunSetupPromptCallbacks(
            load_history=lambda metadata: metadata,
            stage_overrides=lambda profile: None,
            edit_labels=lambda labels: list(labels),
            select_case_sku=lambda current: current,
            select_psu_rating=lambda current: current,
            select_cpu_cooler=lambda current: current,
            enter_power_limit=lambda current: current,
            enter_description=lambda current: "Review Smoke",
            enter_heatsoak_minutes=lambda current: current,
            enter_psu_wattage=lambda current: current,
            enter_fan_type=lambda fan_type, fan_details: (fan_type, fan_details),
            enter_fan_details=lambda current: current,
            enter_raw=lambda label: "",
            normalize_labels=lambda profile, labels: list(labels),
            department=lambda: "QA",
            update_pending_heatsoak=lambda minutes: None,
        ),
    )
    assert_true("System Configuration" in review_controller.overview_text(), "review controller overview")
    assert_true(review_controller.is_cancel_choice("B"), "review controller back choice")
    assert_true(review_controller.is_cancel_choice("q"), "review controller quit choice")
    assert_true(review_controller.action_for_choice("invalid") is None, "review controller invalid choice")
    review_description_action = review_controller.action_for_choice("2")
    assert_true(review_description_action is not None, "review controller description action")
    review_controller.handle_action(review_description_action)
    assert_equal(review_setup.metadata.description, "Review Smoke", "review controller handles action")
    assert_equal(review_setup.metadata.dept, "QA", "review controller normalizes department")
    review_run_action = review_controller.action_for_choice("u")
    assert_true(review_run_action is not None, "review controller run action")
    review_finalized = review_controller.handle_action(review_run_action)
    assert_true(review_finalized is review_setup.metadata, "review controller final metadata")


def test_run_preflight_manager_readiness() -> None:
    profile = ValidationProfile(
        profile_name="PreflightSmoke",
        stages=[
            StageConfig(
                id="segment_1",
                name="CPU",
                duration_seconds=300,
                enabled=True,
            ),
            StageConfig(
                id="segment_2",
                name="3D Adaptive",
                duration_seconds=300,
                enabled=True,
            ),
        ],
    )

    class Loader:
        def load_profile(self, _path):
            return profile

        def load_segment_labels(self, _path, _profile):
            return ["CPU", "GPU"]

        def inspect_segment_label_source(self, _path, _profile):
            return {"exists": True, "path": "profiles/PreflightSmoke_info.txt", "issues": ["sidecar warning"]}

    class Validator:
        def validate(self, _profile, labels):
            return {"errors": [], "warnings": [f"{len(labels)} labels"]}

    class WorkloadRunner:
        def runtime_environment(self):
            return {"ENV": "1"}

        def detect_backends(self):
            return {"python_fallback": True}

        def backend_details(self):
            return {"python_fallback": {"available": True}}

    class Orchestrator:
        validator = Validator()
        workload_runner = WorkloadRunner()

        def dry_run(self, profile_path, dry_profile, labels):
            return {
                "profile_name": dry_profile.profile_name,
                "profile_file": profile_path.name,
                "runnable": False,
                "enabled_stage_count": 2,
                "runnable_stage_count": 1,
                "validation": {"errors": ["blocked backend"], "warnings": []},
                "plan": [],
            }

    class Reports:
        def __init__(self):
            self.saved = None

        def preflight_summary_text(self, report):
            return f"summary {report['profile_name']}"

        def save_cli_preflight_report(self, profile_path, saved_profile, labels, report, **kwargs):
            self.saved = {
                "profile_path": profile_path,
                "profile": saved_profile,
                "labels": labels,
                "report": report,
                "kwargs": kwargs,
            }
            return Path("/tmp/lvs_preflight_smoke")

    calls = {"ensure": 0}
    reports = Reports()
    manager = RunPreflightManager(
        profile_loader=Loader(),
        orchestrator=Orchestrator(),
        profile_reports=reports,
        ensure_ready=lambda: calls.update(ensure=calls["ensure"] + 1) or True,
    )
    readiness = manager.inspect_profile(Path("profiles/PreflightSmoke.json"))
    assert_equal(readiness.profile.profile_name, "PreflightSmoke", "preflight readiness profile")
    assert_equal(readiness.labels, ["CPU", "GPU"], "preflight readiness labels")
    assert_equal(readiness.validation["warnings"], ["2 labels", "sidecar warning"], "preflight readiness warnings")
    setup_readiness = manager.inspect_profile_context(Path("profiles/PreflightSmoke.json"), profile, ["Edited CPU"])
    assert_equal(setup_readiness.labels, ["Edited CPU"], "preflight setup context labels")
    assert_equal(setup_readiness.validation["warnings"], ["1 labels", "sidecar warning"], "preflight setup context warnings")
    result = manager.run_preflight(readiness, save_blocked_report=True)
    assert_equal(calls["ensure"], 1, "preflight ensure callback")
    assert_equal(result.skipped_stage_count, 1, "preflight skipped stage count")
    assert_equal(result.report["validation"]["warnings"], ["sidecar warning"], "preflight warning merge")
    assert_equal(result.report_dir, Path("/tmp/lvs_preflight_smoke"), "preflight saved report dir")
    assert_equal(reports.saved["kwargs"]["runtime_environment"], {"ENV": "1"}, "preflight runtime environment")
    assert_equal(reports.saved["kwargs"]["backends"], {"python_fallback": True}, "preflight backends")
    assert_true("summary PreflightSmoke" in reports.saved["kwargs"]["summary_text"], "preflight summary")

    coordinator = RunFlowCoordinator(manager)
    profile_decision = coordinator.profile_validation_decision(readiness)
    assert_true(not profile_decision.blocked, "run flow profile not blocked")
    assert_equal(profile_decision.warnings, ["2 labels", "sidecar warning"], "run flow profile warnings")
    preflight_decision = coordinator.preflight_for_run(readiness, save_blocked_report=True)
    assert_true(preflight_decision.blocked, "run flow preflight blocked")
    assert_true(not preflight_decision.runnable, "run flow preflight not runnable")
    assert_equal(preflight_decision.skipped_stage_count, 1, "run flow skipped stages")
    assert_equal(preflight_decision.errors, ["blocked backend"], "run flow preflight errors")
    assert_equal(preflight_decision.report_dir, Path("/tmp/lvs_preflight_smoke"), "run flow report dir")
    action_summary = build_run_preflight_action_summary(preflight_decision)
    assert_true(action_summary.blocked, "run flow action summary blocked")
    assert_equal(action_summary.errors, ["blocked backend"], "run flow action summary errors")
    assert_equal(action_summary.warnings, ["sidecar warning"], "run flow action summary warnings")
    assert_equal(action_summary.report_dir, Path("/tmp/lvs_preflight_smoke"), "run flow action summary report dir")
    assert_equal(action_summary.runnable_stage_count, 1, "run flow action summary runnable stage count")
    assert_equal(action_summary.skipped_stage_count, 1, "run flow action summary skipped stage count")
    assert_equal(
        action_summary.skip_notice,
        "Proceeding with 1 runnable stage(s); 1 stage(s) will be skipped for this run.",
        "run flow action summary skip notice",
    )
    setup_metadata = RunMetadata(case_sku="CASE-123", description="Prepared run")
    setup = RunSetupState(
        profile_path=Path("profiles/PreflightSmoke.json"),
        metadata=setup_metadata,
        profile=profile,
        labels=readiness.labels,
        heatsoak_minutes=4.5,
    )
    prepared_run = coordinator.prepare_setup_run(readiness, setup, save_blocked_report=True)
    assert_true(prepared_run.preflight_action.blocked, "prepared run flow blocked")
    assert_equal(prepared_run.preflight_action.errors, ["blocked backend"], "prepared run flow errors")
    assert_true(prepared_run.launch_request.setup is setup, "prepared run flow launch setup")
    assert_true(prepared_run.launch_request.metadata is setup_metadata, "prepared run flow launch metadata")
    assert_equal(prepared_run.launch_request.profile_path, setup.profile_path, "prepared run flow launch path")
    assert_equal(prepared_run.launch_request.heatsoak_minutes, 4.5, "prepared run flow heatsoak")


def test_settings_and_result_action_specs() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        tmp_path = Path(tmp)
        service = SuiteAppService()
        service.settings.profiles_dir = str(tmp_path / "profiles")
        service.settings.results_dir = str(tmp_path / "results")
        settings_action = service.settings_action_for_key("4")
        assert_equal(settings_action.action, "toggle_bool", "settings action kind")
        assert_equal(settings_action.target, "export_compatibility_json", "settings action target")
        raw_action = service.settings_action_for_key("6")
        assert_equal(raw_action.target, "keep_raw_telemetry", "settings raw telemetry toggle target")
        wall_action = service.settings_action_for_key("7")
        assert_equal(wall_action.target, "prompt_for_wall_wattage", "settings wall wattage toggle target")
        upload_prompt_action = service.settings_action_for_key("g")
        assert_equal(upload_prompt_action.target, "google_drive_prompt_after_run", "settings upload prompt target")
        upload_move_action = service.settings_action_for_key("u")
        assert_equal(
            upload_move_action.target,
            "google_drive_move_to_uploaded_on_success",
            "settings uploaded move target",
        )
        assert_equal(service.settings_input_label("trim_start_seconds"), "Default trim start seconds", "settings input label")
        list_action = service.settings_action_for_key("k")
        assert_equal(list_action.action, "settings_list", "settings list action kind")
        assert_equal(list_action.target, "cpu_cooler_options", "settings list action target")
        settings_list_action = service.settings_list_action_for_key("enter")
        assert_equal(settings_list_action.action, "input", "settings list enter action")
        assert_equal(settings_list_action.target, "rename", "settings list rename target")
        settings_summary = service.settings_summary_text()
        assert_true("Keep raw telemetry:" in settings_summary, "settings summary raw telemetry")
        assert_true("Prompt wall wattage after run:" in settings_summary, "settings summary wall wattage")
        assert_true(
            "Prompt Google Drive upload after run:" in settings_summary,
            "settings summary upload prompt",
        )
        assert_true(
            "Move uploaded results to Uploaded/:" in settings_summary,
            "settings summary upload move",
        )
        assert_true("Google Drive credential path:" in settings_summary, "settings summary credential path")
        assert_true("Advanced debug logging: configured per run" in settings_summary, "settings summary debug scope")
        assert_true("- G toggle Google Drive upload prompt after run" in settings_summary, "settings summary G action")
        assert_true("- U toggle move successful uploads to Uploaded/" in settings_summary, "settings summary U action")
        result_action = service.result_action_for_key("b")
        assert_equal(result_action.action, "pre_import_all", "result action kind")
        assert_equal(service.result_action_for_key("e").action, "qa_review", "result QA review action kind")
        assert_equal(service.result_action_for_key("f").action, "artifact_detail", "result artifact detail action kind")
        assert_equal(service.result_action_for_key("o").action, "compare_selected", "result comparison action kind")
        assert_equal(service.result_action_for_key("?").action, "", "unknown result action")
        result_help = service.result_action_help_text()
        assert_true("- I save/show results inventory" in result_help, "result action help inventory")
        assert_true("- E QA Review: one-screen review/import/compare/escalation readiness" in result_help, "result action help QA review")
        assert_true("- F Artifacts: locate parsed results, logs, telemetry, reports, and generated files" in result_help, "result action help artifact detail")
        assert_true("- O Comparison: choose a baseline and compare it with the selected result" in result_help, "result action help comparison")
        assert_true("QA wrapper note" in result_help, "result action help explains QA wrapper scope")
        assert_true("- B pre-import sanity check all completed results" in result_help, "result action help batch")
        profile_action = service.profile_action_for_key("a")
        assert_equal(profile_action.action, "audit_profiles", "profile action kind")
        assert_equal(service.profile_action_for_key("e").action, "ensure_example_profile", "profile ensure action")
        edit_action = service.profile_edit_action_for_key("delete")
        assert_equal(edit_action.action, "remove_stage", "profile edit delete action")
        picker_action = service.profile_edit_action_for_key("g")
        assert_equal(picker_action.action, "picker", "profile edit picker action")
        assert_equal(picker_action.target, "gpu_target", "profile edit picker target")
        fake_settings = GlobalSettings(results_dir=str(tmp_path / "results"))
        saves = []
        reloads = []
        facade = SettingsFacade(
            SimpleNamespace(settings=fake_settings, save=lambda: saves.append("save")),
            lambda: reloads.append("reload"),
            lambda: {"ready": True, "missing": []},
            lambda: "Production",
            lambda values, defaults: list(values or defaults),
        )
        facade.apply_runtime_environment_overrides('{"RUSTICL_ENABLE":"radeonsi","EMPTY_KEY_TEST":1,"": "skip"}')
        assert_equal(
            fake_settings.runtime_environment,
            {"RUSTICL_ENABLE": "radeonsi", "EMPTY_KEY_TEST": "1"},
            "settings facade runtime env",
        )
        try:
            facade.apply_runtime_environment_overrides("[]")
            raise AssertionError("runtime environment non-object should fail")
        except ValueError:
            pass
        facade.apply_gpu_target_thresholds(
            {
                "target_gpu_busy_min_percent": "-5",
                "target_gpu_busy_sustain_seconds": "2.5",
                "target_gpu_memory_busy_min_percent": "74",
                "target_gpu_memory_busy_sustain_seconds": "",
            }
        )
        assert_equal(fake_settings.target_gpu_busy_min_percent, 0.0, "GPU busy threshold clamp")
        assert_equal(fake_settings.target_gpu_busy_sustain_seconds, 2.5, "GPU busy sustain parse")
        assert_equal(fake_settings.target_gpu_memory_busy_min_percent, 74.0, "GPU memory busy threshold parse")
        facade.apply_gpu_safe_mode_settings(
            {
                "gpu_safe_mode": "yes",
                "gpu_retune_warmup_seconds": "-2",
                "gpu_retune_cooldown_seconds": "1.5",
                "gpu_max_retunes_per_worker": "-3",
                "gpu_internal_ramp_step_seconds": "0.75",
                "gpu_safe_start_load_fraction": "2",
                "gpu_safe_max_tuning_step": "4",
                "gpu_safe_max_load_scale": "0.5",
                "gpu_safe_max_vram_percent": "200",
                "gpu_external_max_processes": "0",
            }
        )
        assert_true(fake_settings.gpu_safe_mode, "GPU safe mode yes")
        assert_equal(fake_settings.gpu_retune_warmup_seconds, 0.0, "GPU safe warmup clamp")
        assert_equal(fake_settings.gpu_retune_cooldown_seconds, 1.5, "GPU safe cooldown parse")
        assert_equal(fake_settings.gpu_max_retunes_per_worker, 0, "GPU retune count clamp")
        assert_equal(fake_settings.gpu_internal_ramp_step_seconds, 0.75, "GPU ramp step parse")
        assert_equal(fake_settings.gpu_safe_start_load_fraction, 1.0, "GPU safe start load max clamp")
        assert_equal(fake_settings.gpu_safe_max_tuning_step, 4, "GPU safe max tuning step")
        assert_equal(fake_settings.gpu_safe_max_load_scale, 0.75, "GPU safe load scale min clamp")
        assert_equal(fake_settings.gpu_safe_max_vram_percent, 100.0, "GPU safe VRAM max clamp")
        assert_equal(fake_settings.gpu_external_max_processes, 1, "GPU external process min clamp")
        service_facade = SuiteAppService.__new__(SuiteAppService)
        service_facade.settings_facade = facade
        group_summary = service_facade.add_profile_menu_group_text("qa lab", "QA Lab")
        assert_true("QA Lab (qa_lab)" in group_summary, "profile group add summary")
        assert_true(bool(saves), "profile group add saves")
        assert_true(bool(reloads), "profile group add reloads")
        groups = service_facade.profile_menu_groups()
        qa_index = next(index for index, item in enumerate(groups) if item["key"] == "qa_lab")
        try:
            facade.add_profile_menu_group("qa_lab", "Duplicate")
            raise AssertionError("duplicate profile menu group should fail")
        except ValueError:
            pass
        service_facade.rename_profile_menu_group_text(qa_index, "QA Renamed")
        groups = service_facade.profile_menu_groups()
        qa_index = next(index for index, item in enumerate(groups) if item["key"] == "qa_lab")
        assert_equal(groups[qa_index]["label"], "QA Renamed", "profile group rename")
        service_facade.delete_profile_menu_group_text(qa_index)
        assert_true(
            all(item["key"] != "qa_lab" for item in service_facade.profile_menu_groups()),
            "profile group delete",
        )
        restored = service_facade.restore_profile_menu_group_defaults_text()
        assert_true("standard profile (standard)" in restored, "profile group restore defaults")


def test_result_overview_text_fixture() -> None:
    assert_equal(format_result_metric_number(92.5), "92.5", "result metric number trims zeros")
    assert_equal(format_result_metric_number("92.5"), "", "result metric number ignores non-numeric")
    assert_equal(format_result_metric_triplet(75.0, 92.5, 100.0, "%"), "75 / 92.5 / 100%", "result metric triplet")
    assert_equal(format_result_metric_pair(501.25, 599.9, "W"), "avg 501.25, max 599.9W", "result metric pair")
    assert_equal(format_result_metric_pair(None, None, "W"), "", "empty result metric pair")
    assert_equal(
        result_gpu_highlight_line(
            {
                "DisplayName": "GPU 1",
                "LoadQuality": "high",
                "TargetIds": ["0000:01:00.0"],
                "Workloads": ["gpu_3d"],
                "Backends": ["python_vulkan_compute"],
                "UsageMin": 75.0,
                "UsageAvg": 92.5,
                "UsageMax": 100.0,
                "PowerAvgW": 501.25,
                "PowerMaxW": 599.9,
                "VramUsedAvgGB": 10.0,
                "VramUsedMaxGB": 12.5,
                "AllocationPercent": 80.0,
                "VerificationPasses": 42,
            }
        ),
        "  - GPU 1: load=high; target=0000:01:00.0; workloads=gpu_3d; backends=python_vulkan_compute; usage=75 / 92.5 / 100%; power=avg 501.25, max 599.9W; vram=avg 10, max 12.5GB; alloc=80.0%; verify=42",
        "result GPU highlight line",
    )
    assert_equal(
        result_overview_stage_line(
            1,
            {
                "Label": "Power",
                "Verdict": "warning",
                "TestType": "Combined",
                "GpuHighlights": [{}, {}],
            },
        ),
        "1. Power: warning (Combined, GPUs=2)",
        "result overview stage line",
    )
    action_item = {
        "Severity": "error",
        "Category": "worker_results",
        "Stage": "Power",
        "Message": "one GPU worker failed",
    }
    assert_equal(
        result_action_item_line(action_item),
        "- [error] worker_results: one GPU worker failed",
        "result action item line",
    )
    assert_equal(
        result_action_item_line(action_item, include_stage=True),
        "- [error] worker_results [Power]: one GPU worker failed",
        "result action item stage line",
    )
    assert_true("Result Overview" in missing_result_overview_text("missing"), "missing result overview text")
    assert_true("Result Stage Details" in missing_result_stage_details_text("missing"), "missing stage details text")
    validation_item = {
        "result_folder": "/tmp/results/2026-05-27_12-00-00_PL_Validation",
        "result": "warning",
        "summary": {"errors": 1, "warnings": 2},
    }
    assert_equal(
        result_validation_batch_line(validation_item),
        "- 2026-05-27_12-00-00_PL_Validation: WARNING (1e/2w)",
        "result validation batch line",
    )
    assert_equal(
        pre_import_batch_line(
            {
                "folder_name": "2026-05-27_12-00-00_PL_Validation",
                "result": "pass",
                "summary": {"errors": 0, "warnings": 1},
                "summary_refresh": {"refreshed": True},
            }
        ),
        "- 2026-05-27_12-00-00_PL_Validation: PASS (0e/1w, summary_refreshed=True)",
        "pre-import batch line",
    )
    assert_equal(
        result_validation_issue_line(
            {"severity": "warning", "category": "support_files", "message": "run_summary.txt is missing"}
        ),
        "[warning] support_files: run_summary.txt is missing",
        "result validation issue line",
    )
    validation_text = result_validation_text(
        {
            "result_folder": "/tmp/results/Fixture",
            "result": "warning",
            "summary": {
                "errors": 1,
                "warnings": 2,
                "segments": 3,
                "gpu_worker_details": 4,
                "gpu_highlights": 5,
                "action_items": 6,
                "issue_category_counts": {"support_files": 2, "segments": 1},
            },
            "checks": {"support_files": {}},
            "issues": [
                {"severity": "warning", "category": "support_files", "message": "run_summary.txt is missing"},
            ],
        }
    )
    assert_true("Result Folder Validation\nFolder: /tmp/results/Fixture" in validation_text, "result validation text header")
    assert_true("Result: WARNING (1 error(s), 2 warning(s))" in validation_text, "result validation text result")
    assert_true("GPU highlights: 5" in validation_text, "result validation text GPU highlights")
    assert_true("[warning] support_files: run_summary.txt is missing" in validation_text, "result validation text issue")
    early_validation_text = result_validation_text(
        {
            "result_folder": "/tmp/results/Missing",
            "result": "fail",
            "checks": {},
            "issues": [
                {"severity": "error", "category": "missing_file", "message": "parsed_results_custom.json was not found"},
            ],
        }
    )
    assert_true(
        "[error] parsed_results_custom.json was not found" in early_validation_text,
        "result validation text early error",
    )
    selected_sanity_text = selected_pre_import_sanity_text(
        {
            "result_folder": "/tmp/results/Fixture",
            "validation": {
                "result_folder": "/tmp/results/Fixture",
                "result": "pass",
                "summary": {
                    "errors": 0,
                    "warnings": 0,
                    "segments": 1,
                    "gpu_worker_details": 0,
                    "gpu_highlights": 0,
                    "action_items": 0,
                },
                "checks": {"support_files": {}},
                "issues": [],
            },
            "summary_refresh": {"refreshed": True, "summary_path": "/tmp/results/Fixture/run_summary.txt"},
            "comparison": None,
        }
    )
    assert_true("\nPre-Import Sanity Check\n=======================" in selected_sanity_text, "selected sanity text header")
    assert_true("Result Folder Validation\nFolder: /tmp/results/Fixture" in selected_sanity_text, "selected sanity validation")
    assert_true("Refreshed: /tmp/results/Fixture/run_summary.txt" in selected_sanity_text, "selected sanity refresh")
    assert_true("Comparison\n----------\nSkipped" in selected_sanity_text, "selected sanity skipped comparison")
    batch_sanity_text = batch_pre_import_sanity_text(
        {
            "results_dir": "/tmp/results",
            "result": "warning",
            "counts": {
                "total": 1,
                "errors": 0,
                "warnings": 1,
                "by_result": {"warning": 1},
                "issue_category_counts": {"support_files": 1},
            },
            "summary_refresh": {"refreshed": 1, "failed": 0},
            "items": [
                {
                    "folder_name": "Fixture",
                    "result": "warning",
                    "summary": {"errors": 0, "warnings": 1},
                    "summary_refresh": {"refreshed": True},
                }
            ],
        }
    )
    assert_true("\nBatch Pre-Import Sanity Check\n=============================" in batch_sanity_text, "batch sanity text header")
    assert_true("Issue categories: {'support_files': 1}" in batch_sanity_text, "batch sanity issue categories")
    assert_true("- Fixture: WARNING (0e/1w, summary_refreshed=True)" in batch_sanity_text, "batch sanity item")
    batch_validation_text = batch_result_validation_text(
        {
            "results_dir": "/tmp/results",
            "result": "warning",
            "counts": {
                "total": 1,
                "errors": 0,
                "warnings": 1,
                "by_result": {"warning": 1},
                "issue_category_counts": {"support_files": 1},
            },
            "items": [
                {
                    "folder_name": "Fixture",
                    "result": "warning",
                    "summary": {
                        "errors": 0,
                        "warnings": 1,
                        "issue_category_counts": {"support_files": 1},
                    },
                }
            ],
        }
    )
    assert_true("\nBatch Result Validation\n=======================" in batch_validation_text, "batch validation text header")
    assert_true("Issue categories: {'support_files': 1}" in batch_validation_text, "batch validation issue categories")
    assert_true(
        "- Fixture: WARNING (0e/1w, categories={'support_files': 1})" in batch_validation_text,
        "batch validation item",
    )
    with TemporaryDirectory(dir="/tmp") as tmp:
        result_dir = Path(tmp) / "2026-05-27_12-00-00_PL_Validation"
        result_dir.mkdir()
        JsonStore.write(
            result_dir / "parsed_results_custom.json",
            {
                "Result": "Warning",
                "Metadata": {
                    "ProfileName": "PL_Validation",
                    "Description": "PL Validation L10",
                    "Result": "Warning",
                },
                "ReportSummary": {
                    "Result": "Warning",
                    "DepartmentUseSummary": {
                        "Status": "ready_with_warnings",
                        "Decision": "Usable with documented warnings.",
                    },
                    "GpuWorkerSummary": {
                        "WorkerResultCount": 6,
                        "Successful": 5,
                        "Failed": 1,
                    },
                    "StageOutcomes": [
                        {
                            "Label": "Power",
                            "Verdict": "warning",
                            "TestType": "Combined",
                            "OutcomeClass": "worker_verified_non_blocking_warnings",
                            "OutcomeSummary": "Power stage completed with thermal warning.",
                            "WarningCategoryCounts": {"gpu_temperature": 1},
                            "GpuHighlights": [
                                {
                                    "Name": "GPU 1",
                                    "DisplayName": "GPU 1",
                                    "LoadQuality": "high",
                                    "TargetIds": ["0000:01:00.0"],
                                    "Workloads": ["gpu_3d"],
                                    "Backends": ["python_vulkan_compute"],
                                    "UsageMin": 75.0,
                                    "UsageAvg": 92.5,
                                    "UsageMax": 100.0,
                                    "PowerAvgW": 501.25,
                                    "PowerMaxW": 599.9,
                                    "VramUsedAvgGB": 10.0,
                                    "VramUsedMaxGB": 12.5,
                                    "AllocationPercent": 80.0,
                                    "VerificationPasses": 42,
                                },
                                {"Name": "GPU 2"},
                            ],
                        },
                        {
                            "Label": "SSE + VRAM",
                            "Verdict": "aborted",
                            "TestType": "Combined",
                        },
                    ],
                    "ActionItemDetails": [
                        {
                            "Severity": "error",
                            "Category": "worker_results",
                            "Stage": "Power",
                            "Message": "one GPU worker failed",
                        }
                    ],
                },
            },
        )
        manager = ResultReportManager(Path(tmp), RunSummaryTextExporter())
        text = manager.result_overview_text(result_dir)
        assert_true("Result Overview" in text, "result overview heading")
        assert_true("Result: Warning" in text, "result overview result")
        assert_true("Profile: PL_Validation" in text, "result overview profile")
        assert_true("GPU workers: 5/6 successful, 1 failed" in text, "result overview workers")
        assert_true("1. Power: warning (Combined, GPUs=2)" in text, "result overview stage")
        assert_true("[error] worker_results: one GPU worker failed" in text, "result overview action item")
        details = manager.result_stage_details_text(result_dir)
        assert_true("Result Stage Details" in details, "result stage detail heading")
        assert_true("1. Power" in details, "result stage detail stage")
        assert_true("Outcome: worker_verified_non_blocking_warnings" in details, "result stage detail outcome")
        assert_true("Warnings: {'gpu_temperature': 1}" in details, "result stage detail warning counts")
        assert_true(
            "GPU 1: load=high; target=0000:01:00.0; workloads=gpu_3d; backends=python_vulkan_compute" in details,
            "result stage detail GPU line",
        )
        assert_true("usage=75 / 92.5 / 100%" in details, "result stage detail usage")
        assert_true("power=avg 501.25, max 599.9W" in details, "result stage detail power")
        assert_true("[error] worker_results [Power]: one GPU worker failed" in details, "result stage detail action item")


def test_result_validation_facade_candidates_and_batch() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        pass_dir = root / "2026-05-01_12-00-00_Pass"
        warning_dir = root / "2026-05-01_13-00-00_Warning"
        crash_dir = root / "2026-05-01_14-00-00_Crash"
        archived_dir = root / "Archived" / "2026-05-01_15-00-00_Archived"
        uploaded_dir = root / "Uploaded" / "2026-05-01_16-00-00_Uploaded"
        for path in (pass_dir, warning_dir, crash_dir, archived_dir, uploaded_dir):
            path.mkdir(parents=True)
            JsonStore.write(path / "parsed_results_custom.json", {"Result": path.name})

        facade = ResultValidationFacade(root)
        active_names = {path.name for path in facade.result_candidates()}
        assert_equal(
            active_names,
            {pass_dir.name, warning_dir.name, crash_dir.name},
            "result validation facade active candidates exclude Archived/Uploaded",
        )
        all_names = {path.name for path in facade.result_candidates(include_archived=True)}
        assert_true(archived_dir.name in all_names, "result validation facade includes archived when requested")
        assert_true(uploaded_dir.name not in all_names, "result validation facade never includes Uploaded root")

        def validate_one(path: Path) -> Dict[str, Any]:
            if "Crash" in path.name:
                raise RuntimeError("fixture validation crash")
            if "Warning" in path.name:
                return {
                    "kind": "result_validation",
                    "result_folder": str(path),
                    "result": "warning",
                    "summary": {
                        "errors": 0,
                        "warnings": 2,
                        "issue_category_counts": {"support_files": 2},
                        "issue_severity_category_counts": {"warning": {"support_files": 2}},
                    },
                    "issues": [
                        {"severity": "warning", "category": "support_files", "message": "missing summary"},
                    ],
                }
            return {
                "kind": "result_validation",
                "result_folder": str(path),
                "result": "pass",
                "summary": {
                    "errors": 0,
                    "warnings": 0,
                    "issue_category_counts": {},
                    "issue_severity_category_counts": {},
                },
                "issues": [],
            }

        payload = facade.validate_batch([pass_dir, warning_dir, crash_dir], validate_one=validate_one)
        assert_equal(payload["kind"], "result_validation_batch", "result validation facade batch kind")
        assert_equal(payload["result"], "fail", "result validation facade batch result")
        assert_equal(payload["counts"]["total"], 3, "result validation facade batch total")
        assert_equal(payload["counts"]["errors"], 1, "result validation facade batch errors")
        assert_equal(payload["counts"]["warnings"], 2, "result validation facade batch warnings")
        assert_equal(payload["counts"]["by_result"], {"fail": 1, "pass": 1, "warning": 1}, "result validation facade by-result counts")
        assert_equal(
            payload["counts"]["issue_category_counts"],
            {"support_files": 2, "validation_runtime": 1},
            "result validation facade issue categories",
        )
        assert_equal(
            payload["counts"]["issue_severity_category_counts"],
            {"error": {"validation_runtime": 1}, "warning": {"support_files": 2}},
            "result validation facade severity category counts",
        )
        saved_validation_payload = {
            "kind": "result_validation",
            "result_folder": str(pass_dir),
            "result": "pass",
            "summary": {"errors": 0, "warnings": 0},
        }
        saved_validation_dir = facade.write_validation_report(
            pass_dir,
            "validation text\n",
            saved_validation_payload,
        )
        assert_equal(saved_validation_dir, pass_dir, "result validation report save target")
        assert_equal(
            JsonStore.read(pass_dir / "result_validation.json", {}).get("kind"),
            "result_validation",
            "result validation report JSON saved",
        )
        assert_equal(
            (pass_dir / "result_validation.txt").read_text(encoding="utf-8"),
            "validation text\n",
            "result validation report text saved",
        )
        batch_report_dir = facade.write_batch_validation_report(
            "batch validation text\n",
            payload,
            "2026-05-01_18-00-00",
        )
        assert_true(
            (batch_report_dir / "result_validation_batch.json").exists(),
            "result validation batch report JSON saved",
        )
        assert_equal(
            JsonStore.read(batch_report_dir / "result_validation_batch.json", {}).get("kind"),
            "result_validation_batch",
            "result validation batch report payload saved",
        )
        assert_equal(
            (batch_report_dir / "result_validation_batch.txt").read_text(encoding="utf-8"),
            "batch validation text\n",
            "result validation batch report text saved",
        )

        support_dir = root / "2026-05-01_17-00-00_Support"
        support_dir.mkdir()
        parsed = {"Result": "Finished", "Metadata": {"ProfileName": "Support Fixture"}, "Segments": []}
        JsonStore.write(support_dir / "parsed_results_custom.json", parsed)
        support_validation = facade.validate_support_files(support_dir, parsed, RunSummaryTextExporter())
        assert_equal(
            support_validation["checks"]["support_files"]["missing"],
            ["run_summary.txt", "run_manifest.json", "run_metadata.json", "profile_used.json", "system_info.json"],
            "result validation support missing files",
        )
        assert_true(
            any(issue["message"] == "run_summary.txt is missing from the result folder" for issue in support_validation["issues"]),
            "result validation support missing summary issue",
        )
        (support_dir / "run_summary.txt").write_text(RunSummaryTextExporter().build(parsed), encoding="utf-8")
        current_summary_validation = facade.validate_support_files(support_dir, parsed, RunSummaryTextExporter())
        assert_true(current_summary_validation["checks"]["run_summary"]["current"], "result validation current run summary")
        (support_dir / "run_summary.txt").write_text("stale summary\n", encoding="utf-8")
        stale_summary_validation = facade.validate_support_files(support_dir, parsed, RunSummaryTextExporter())
        assert_true(
            any(issue["message"] == "run_summary.txt does not match the current parsed_results_custom.json summary" for issue in stale_summary_validation["issues"]),
            "result validation stale summary issue",
        )
        parsed_profile = {
            "Result": "Finished",
            "Metadata": {"ProfileName": "Profile Fixture"},
            "Segments": [
                {"Label": "Stage 1", "Duration": 90},
                {"Label": "Stage 2", "Duration": 120},
            ],
        }
        JsonStore.write(
            support_dir / "profile_used.json",
            {
                "profile_name": "Profile Fixture",
                "stages": [
                    {"enabled": True, "duration_seconds": 90},
                    {"enabled": False, "duration_seconds": 1},
                    {"enabled": True, "duration_seconds": 120},
                ],
            },
        )
        profile_validation = facade.validate_profile_used(support_dir, parsed_profile)
        assert_equal(profile_validation["issues"], [], "result validation profile used no issues")
        assert_true(profile_validation["checks"]["profile_used"]["matches_result_profile_name"], "result validation profile name match")
        assert_true(profile_validation["checks"]["profile_used"]["matches_segment_count"], "result validation profile segment count match")
        JsonStore.write(
            support_dir / "profile_used.json",
            {
                "profile_name": "Other Profile",
                "stages": [
                    {"enabled": True, "duration_seconds": 91},
                    {"enabled": True, "duration_seconds": 120},
                    {"enabled": True, "duration_seconds": 30},
                ],
            },
        )
        bad_profile_validation = facade.validate_profile_used(support_dir, parsed_profile)
        bad_profile_messages = {issue["message"] for issue in bad_profile_validation["issues"]}
        assert_true(
            "profile_used.json profile_name does not match result profile name" in bad_profile_messages,
            "result validation profile used name mismatch",
        )
        assert_true(
            "profile_used.json enabled stage count does not match parsed Segments count" in bad_profile_messages,
            "result validation profile used segment count mismatch",
        )
        assert_true(
            "profile_used.json stage 1 duration does not match parsed segment duration" in bad_profile_messages,
            "result validation profile used duration mismatch",
        )
        aborted_profile_validation = facade.validate_profile_used(
            support_dir,
            {"Result": "manually_aborted", "Metadata": {"ProfileName": "Other Profile"}, "Segments": [{"Duration": 91}]},
        )
        assert_true(
            aborted_profile_validation["checks"]["profile_used"]["partial_segment_count_expected"],
            "result validation profile used partial aborted count expected",
        )
        parsed_manifest = {
            "Result": "Finished",
            "Metadata": {"ProfileName": "Manifest Fixture"},
            "Segments": [{"Duration": 90}, {"Duration": 120}],
        }
        JsonStore.write(
            support_dir / "run_manifest.json",
            {
                "profile_name": "Manifest Fixture",
                "verdict": "pass",
                "executed_plan": [{}, {}],
                "stage_windows": [{}, {}],
                "skipped_stages": [{}],
            },
        )
        manifest_validation = facade.validate_run_manifest(support_dir, parsed_manifest)
        assert_equal(manifest_validation["issues"], [], "result validation run manifest no issues")
        assert_true(manifest_validation["checks"]["run_manifest"]["matches_result_profile_name"], "result validation manifest profile match")
        assert_true(manifest_validation["checks"]["run_manifest"]["matches_segment_count"], "result validation manifest segment count match")
        assert_true(manifest_validation["checks"]["run_manifest"]["matches_verdict"], "result validation manifest verdict match")
        JsonStore.write(
            support_dir / "run_manifest.json",
            {
                "profile_name": "Other Manifest",
                "verdict": "warning",
                "executed_plan": [{}],
                "stage_windows": [{}, {}],
                "skipped_stages": [],
            },
        )
        bad_manifest_validation = facade.validate_run_manifest(support_dir, parsed_manifest)
        bad_manifest_messages = {issue["message"] for issue in bad_manifest_validation["issues"]}
        assert_true(
            "run_manifest.json profile_name does not match result profile name" in bad_manifest_messages,
            "result validation manifest name mismatch",
        )
        assert_true(
            "run_manifest.json executed stage counts do not match parsed Segments count" in bad_manifest_messages,
            "result validation manifest segment count mismatch",
        )
        assert_true(
            "run_manifest.json verdict does not match parsed result" in bad_manifest_messages,
            "result validation manifest verdict mismatch",
        )
        assert_true(
            "run_manifest.json executed_plan count does not match stage_windows count" in bad_manifest_messages,
            "result validation manifest plan/window mismatch",
        )
        parsed_metadata = {
            "serial": "ABC123",
            "Serial": "ABC123",
            "order": "ORD-9",
            "Order": "ORD-9",
            "dept": "RND",
            "Department": "RND",
            "Metadata": {
                "SerialNumber": "ABC123",
                "Department": "RND",
                "Notes": "Operator note",
                "MaxWallWattage": "812W",
            },
        }
        JsonStore.write(
            support_dir / "run_metadata.json",
            {
                "serial": "ABC123",
                "order": "ORD-9",
                "dept": "RND",
                "operator": "Operator",
                "notes": "Operator note",
                "wall_wattage": "812W",
            },
        )
        metadata_validation = facade.validate_run_metadata(support_dir, parsed_metadata)
        assert_equal(metadata_validation["issues"], [], "result validation run metadata no issues")
        assert_equal(metadata_validation["checks"]["run_metadata"]["serial"], "ABC123", "result validation metadata serial")
        assert_true(metadata_validation["checks"]["run_metadata"]["operator_present"], "result validation metadata operator")
        JsonStore.write(
            support_dir / "run_metadata.json",
            {
                "serial": "DIFFERENT",
                "order": "OTHER",
                "dept": "OPS",
                "operator": "",
                "notes": "Different note",
                "wall_wattage": "900W",
            },
        )
        bad_metadata_validation = facade.validate_run_metadata(support_dir, parsed_metadata)
        bad_metadata_messages = {issue["message"] for issue in bad_metadata_validation["issues"]}
        assert_true(
            "run_metadata.json serial does not match top-level serial" in bad_metadata_messages,
            "result validation metadata serial mismatch",
        )
        assert_true(
            "run_metadata.json order does not match top-level order" in bad_metadata_messages,
            "result validation metadata order mismatch",
        )
        assert_true(
            "run_metadata.json dept does not match Metadata.Department" in bad_metadata_messages,
            "result validation metadata department mismatch",
        )
        assert_true(
            "run_metadata.json notes do not match Metadata.Notes" in bad_metadata_messages,
            "result validation metadata notes mismatch",
        )
        assert_true(
            "run_metadata.json wall_wattage does not match Metadata.MaxWallWattage" in bad_metadata_messages,
            "result validation metadata wattage mismatch",
        )
        system_info = {
            "TestInfo": {"TestName": "System Fixture", "ConfigFile": "profiles/System Fixture.json"},
            "Hardware": {
                "Cpu": {"Name": "Smoke CPU"},
                "Gpu": [{"Name": "GPU 1"}, {"Name": "GPU 2"}],
            },
        }
        parsed_system = {
            "SystemInfo": system_info,
            "Metadata": {
                "TestName": "System Fixture",
                "TestConfigFile": "profiles/System Fixture.json",
                "CpuName": "Smoke CPU",
            },
        }
        JsonStore.write(support_dir / "system_info.json", system_info)
        system_validation = facade.validate_system_info(support_dir, parsed_system)
        assert_equal(system_validation["issues"], [], "result validation system info no issues")
        assert_true(system_validation["checks"]["system_info"]["matches_export"], "result validation system info matches export")
        assert_equal(system_validation["checks"]["system_info"]["gpu_count"], 2, "result validation system info GPU count")
        JsonStore.write(
            support_dir / "system_info.json",
            {
                "TestInfo": {"TestName": "Other Test", "ConfigFile": "profiles/Other.json"},
                "Hardware": {
                    "Cpu": {"Name": "Other CPU"},
                    "Gpu": [{"Name": "GPU 1"}],
                },
            },
        )
        bad_system_validation = facade.validate_system_info(support_dir, parsed_system)
        bad_system_messages = {issue["message"] for issue in bad_system_validation["issues"]}
        assert_true(
            "system_info.json does not match parsed_results_custom.json SystemInfo" in bad_system_messages,
            "result validation system info export mismatch",
        )
        assert_true(
            "system_info.json TestInfo.TestName does not match exported metadata" in bad_system_messages,
            "result validation system info test name mismatch",
        )
        assert_true(
            "system_info.json TestInfo.ConfigFile does not match exported metadata" in bad_system_messages,
            "result validation system info config mismatch",
        )
        assert_true(
            "system_info.json Hardware.Cpu.Name does not match exported metadata" in bad_system_messages,
            "result validation system info CPU mismatch",
        )
        missing_export_system_validation = facade.validate_system_info(
            support_dir,
            {"Metadata": {"TestName": "Other Test", "TestConfigFile": "profiles/Other.json", "CpuName": "Other CPU"}},
        )
        assert_true(
            any(issue["message"] == "parsed_results_custom.json SystemInfo is missing or malformed" for issue in missing_export_system_validation["issues"]),
            "result validation system info missing export",
        )

        parsed_report_payload = {
            "Segments": [
                {
                    "Label": "Stage 1",
                    "GpuMetrics": [{"Targeted": True}],
                }
            ],
            "ReportSummary": {
                "StageOutcomes": [
                    {
                        "Label": "Stage 1",
                        "TargetedGpuCount": 1,
                        "GpuHighlights": [
                            {
                                "Name": "",
                                "GpuIndex": None,
                                "UsageAvg": "not numeric",
                                "TargetIds": "not a list",
                                "TelemetryMissing": "no",
                            }
                        ],
                    }
                ],
                "ActionItems": [],
                "ActionItemDetails": [],
                "ActionItemCategoryCounts": {},
                "ActionItemSeverityCounts": {},
            },
            "Metadata": {
                "ReportSummary": {
                    "StageOutcomes": [],
                }
            },
        }
        parsed_report_validation = facade.validate_parsed_report_payload(parsed_report_payload)
        assert_true("export_contract" in parsed_report_validation["checks"], "result validation parsed report export contract check")
        assert_true("report_summary" in parsed_report_validation["checks"], "result validation parsed report summary check")
        assert_true("stage_counts" in parsed_report_validation["checks"], "result validation parsed report stage count check")
        assert_true("gpu_highlights" in parsed_report_validation["checks"], "result validation parsed report GPU highlight check")
        assert_true("action_items" in parsed_report_validation["checks"], "result validation parsed report action item check")
        assert_equal(len(parsed_report_validation["segments"]), 1, "result validation parsed report segments")
        assert_equal(parsed_report_validation["gpu_highlight_count"], 1, "result validation parsed report GPU highlight count")
        parsed_report_categories = {issue["category"] for issue in parsed_report_validation["issues"]}
        assert_true("segment_shape" in parsed_report_categories, "result validation parsed report segment shape warning")
        assert_true("gpu_highlights" in parsed_report_categories, "result validation parsed report GPU highlight warning")

        full_validation_dir = root / "2026-05-01_18-00-00_FullValidation"
        full_validation_dir.mkdir()
        JsonStore.write(full_validation_dir / "parsed_results_custom.json", parsed_report_payload)
        full_validation = facade.validate_result_folder(full_validation_dir, RunSummaryTextExporter())
        assert_equal(full_validation["kind"], "result_validation", "result validation full folder kind")
        assert_equal(full_validation["summary"]["segments"], 1, "result validation full folder segments")
        assert_equal(full_validation["summary"]["gpu_highlights"], 1, "result validation full folder GPU highlights")
        full_validation_categories = set(full_validation["summary"]["issue_category_counts"])
        assert_true("support_files" in full_validation_categories, "result validation full folder support files")
        assert_true("segment_shape" in full_validation_categories, "result validation full folder segment shape")
        assert_true("gpu_highlights" in full_validation_categories, "result validation full folder GPU highlights")

        missing_validation_dir = root / "2026-05-01_19-00-00_MissingParsed"
        missing_validation_dir.mkdir()
        missing_validation = facade.validate_result_folder(missing_validation_dir, RunSummaryTextExporter())
        assert_equal(missing_validation["result"], "fail", "result validation full folder missing parsed result")
        assert_equal(missing_validation["issues"][0]["category"], "missing_file", "result validation full folder missing parsed category")


def test_result_comparison_facade_payload() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        baseline_dir = root / "baseline"
        comparison_dir = root / "comparison"
        baseline_dir.mkdir()
        comparison_dir.mkdir()
        baseline = {
            "ReportSummary": {
                "Result": "pass",
                "OutcomeClass": "stable",
                "Elapsed": "00:01:30",
                "WarningCategoryCounts": {"thermal": 1},
                "ErrorCategoryCounts": {},
                "GpuWorkerSummary": {"Passed": 1, "Failed": 0},
                "ActionItemCategoryCounts": {"thermal": 1},
                "ActionItemSeverityCounts": {"warning": 1},
                "StageOutcomes": [
                    {
                        "Label": "Power",
                        "Verdict": "pass",
                        "OutcomeClass": "stable",
                        "TargetedGpuCount": 1,
                        "WarningCategoryCounts": {"thermal": 1},
                        "ErrorCategoryCounts": {},
                        "ReportOnlyThresholdWouldWarnCount": 0,
                        "GpuHighlights": [
                            {
                                "GpuIndex": 0,
                                "Name": "GPU 0",
                                "UsageAvg": 50.0,
                                "PowerMaxW": 100.0,
                                "TargetIds": ["0000:01:00.0"],
                            }
                        ],
                    }
                ],
            }
        }
        comparison = {
            "ReportSummary": {
                "Result": "warning",
                "OutcomeClass": "completed_with_warnings",
                "Elapsed": "00:01:31",
                "WarningCategoryCounts": {"thermal": 2, "telemetry": 1},
                "ErrorCategoryCounts": {"worker": 1},
                "GpuWorkerSummary": {"Passed": 0, "Failed": 1},
                "ActionItemCategoryCounts": {"thermal": 2},
                "ActionItemSeverityCounts": {"warning": 2},
                "StageOutcomes": [
                    {
                        "Label": "Power",
                        "Verdict": "warning",
                        "OutcomeClass": "completed_with_warnings",
                        "TargetedGpuCount": 1,
                        "WarningCategoryCounts": {"thermal": 2},
                        "ErrorCategoryCounts": {"worker": 1},
                        "ReportOnlyThresholdWouldWarnCount": 1,
                        "GpuHighlights": [
                            {
                                "GpuIndex": 0,
                                "Name": "GPU 0",
                                "UsageAvg": 70.0,
                                "PowerMaxW": 125.0,
                                "TargetIds": ["0000:01:00.0"],
                            }
                        ],
                    }
                ],
            }
        }
        JsonStore.write(baseline_dir / "parsed_results_custom.json", baseline)
        JsonStore.write(comparison_dir / "parsed_results_custom.json", comparison)

        payload = ResultComparisonFacade().compare_result_folders(baseline_dir, comparison_dir)
        assert_equal(payload["kind"], "result_comparison", "result comparison facade kind")
        assert_equal(payload["baseline"]["result"], "pass", "result comparison facade baseline result")
        assert_equal(payload["comparison"]["result"], "warning", "result comparison facade comparison result")
        assert_equal(payload["deltas"]["warning_categories"]["thermal"]["delta"], 1.0, "result comparison warning delta")
        assert_equal(payload["deltas"]["error_categories"]["worker"]["delta"], 1.0, "result comparison error delta")
        assert_equal(payload["deltas"]["gpu_worker_summary"]["Failed"]["delta"], 1.0, "result comparison worker delta")
        assert_equal(payload["deltas"]["action_item_categories"]["thermal"]["delta"], 1.0, "result comparison action delta")
        stage_delta = payload["deltas"]["stages"][0]
        assert_equal(stage_delta["label"], "Power", "result comparison stage label")
        assert_true("verdict: pass -> warning" in stage_delta["changes"], "result comparison stage verdict")
        gpu_delta = stage_delta["gpu_highlight_deltas"][0]
        assert_equal(gpu_delta["deltas"]["UsageAvg"]["delta"], 20.0, "result comparison GPU usage delta")
        assert_equal(gpu_delta["deltas"]["PowerMaxW"]["delta"], 25.0, "result comparison GPU power delta")
        comparison_text = result_comparison_text(payload)
        assert_true("Result Folder Comparison" in comparison_text, "result comparison text header")
        assert_true("Result: pass -> warning" in comparison_text, "result comparison text result")
        assert_true("Warning thermal: 1 -> 2 (delta 1.0)" in comparison_text, "result comparison text warning delta")
        assert_true("GPU gpu_0:GPU 0:" in comparison_text, "result comparison text GPU heading")
        assert_true("UsageAvg: 50.0 -> 70.0 (delta 20.0)" in comparison_text, "result comparison text GPU usage delta")
        canonical_baseline = ResultComparisonFacade().comparison_summary(
            {
                "ReportSummary": {
                    "GpuWorkerSummary": {
                        "WorkerResultCount": 1,
                        "SuccessfulWorkerResultCount": 1,
                        "WorkerFailureCount": 0,
                        "VerificationPasses": 10,
                    }
                }
            }
        )
        canonical_comparison = ResultComparisonFacade().comparison_summary(
            {
                "ReportSummary": {
                    "GpuWorkerSummary": {
                        "WorkerResultCount": 1,
                        "SuccessfulWorkerResultCount": 0,
                        "WorkerFailureCount": 1,
                        "VerificationPasses": 12,
                    }
                }
            }
        )
        canonical_worker_delta = ResultComparisonFacade().dict_numeric_delta(
            canonical_baseline["gpu_worker_summary"],
            canonical_comparison["gpu_worker_summary"],
        )
        assert_equal(canonical_worker_delta["Passed"]["delta"], -1.0, "result comparison canonical worker passed delta")
        assert_equal(canonical_worker_delta["Failed"]["delta"], 1.0, "result comparison canonical worker failed delta")
        assert_equal(canonical_worker_delta["VerificationPasses"]["delta"], 2.0, "result comparison canonical worker verification delta")
        assert_true("SuccessfulWorkerResultCount" not in canonical_worker_delta, "result comparison canonical success key normalized")
        assert_true("WorkerFailureCount" not in canonical_worker_delta, "result comparison canonical failure key normalized")
        comparison_facade = ResultComparisonFacade()
        comparison_report_dir = comparison_facade.write_comparison_report(
            baseline_dir,
            comparison_dir,
            "comparison text\n",
            payload,
        )
        comparison_slug = comparison_facade.comparison_report_slug(baseline_dir)
        assert_equal(comparison_report_dir, comparison_dir, "result comparison report save target")
        assert_equal(
            JsonStore.read(comparison_dir / f"result_comparison_vs_{comparison_slug}.json", {}).get("kind"),
            "result_comparison",
            "result comparison report JSON saved",
        )
        assert_equal(
            (comparison_dir / f"result_comparison_vs_{comparison_slug}.txt").read_text(encoding="utf-8"),
            "comparison text\n",
            "result comparison report text saved",
        )


def test_pre_import_sanity_facade_batch() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        refresh_dir = root / "2026-05-01_20-00-00_Refresh"
        missing_dir = root / "2026-05-01_21-00-00_Missing"
        refresh_dir.mkdir()
        missing_dir.mkdir()
        JsonStore.write(
            refresh_dir / "parsed_results_custom.json",
            {
                "Metadata": {"ProfileName": "Pre-Import Fixture"},
                "Segments": [],
                "ReportSummary": {},
            },
        )

        validation = ResultValidationFacade(root)
        facade = PreImportSanityFacade(root, validation, RunSummaryTextExporter())
        payload = facade.run_batch([refresh_dir, missing_dir])

        assert_equal(payload["kind"], "pre_import_sanity_batch", "pre-import sanity facade batch kind")
        assert_equal(payload["result"], "fail", "pre-import sanity facade batch result")
        assert_equal(payload["summary_refresh"]["total"], 2, "pre-import sanity facade refresh total")
        assert_equal(payload["summary_refresh"]["refreshed"], 1, "pre-import sanity facade refresh success")
        assert_equal(payload["summary_refresh"]["failed"], 1, "pre-import sanity facade refresh failure")
        assert_equal(len(payload["items"]), 2, "pre-import sanity facade item count")
        assert_true((refresh_dir / "run_summary.txt").exists(), "pre-import sanity facade refreshed summary")
        assert_true((refresh_dir / "result_validation.json").exists(), "pre-import sanity facade validation JSON")
        assert_true((refresh_dir / "result_validation.txt").exists(), "pre-import sanity facade validation text")
        assert_true((missing_dir / "result_validation.json").exists(), "pre-import sanity facade missing validation JSON")
        assert_true(not (missing_dir / "run_summary.txt").exists(), "pre-import sanity facade failed summary absent")
        batch_report_dir = facade.write_batch_report(
            "batch pre-import text\n",
            payload,
            "2026-05-01_21-30-00",
        )
        assert_true(
            (batch_report_dir / "pre_import_sanity_batch.json").exists(),
            "pre-import sanity batch report JSON saved",
        )
        assert_equal(
            JsonStore.read(batch_report_dir / "pre_import_sanity_batch.json", {}).get("kind"),
            "pre_import_sanity_batch",
            "pre-import sanity batch report payload saved",
        )
        assert_equal(
            (batch_report_dir / "pre_import_sanity_batch.txt").read_text(encoding="utf-8"),
            "batch pre-import text\n",
            "pre-import sanity batch report text saved",
        )

        selected_dir = root / "2026-05-01_22-00-00_Selected"
        selected_dir.mkdir()
        JsonStore.write(
            selected_dir / "parsed_results_custom.json",
            {
                "Metadata": {"ProfileName": "Selected Fixture"},
                "Segments": [],
                "ReportSummary": {},
            },
        )
        prepared = facade.prepare_selected(selected_dir)
        assert_equal(prepared["result_folder"], str(selected_dir), "pre-import sanity selected prepared folder")
        assert_equal(prepared["validation"]["kind"], "result_validation", "pre-import sanity selected validation")
        assert_true(prepared["summary_refresh"]["refreshed"], "pre-import sanity selected summary refresh")
        comparison = {"kind": "result_comparison", "baseline_path": "baseline"}
        selected_payload = facade.complete_selected(prepared, comparison)
        assert_equal(selected_payload["kind"], "pre_import_sanity", "pre-import sanity selected payload kind")
        assert_equal(selected_payload["result_folder"], str(selected_dir), "pre-import sanity selected payload folder")
        assert_equal(selected_payload["comparison"], comparison, "pre-import sanity selected comparison")
        assert_equal(selected_payload["validation"], prepared["validation"], "pre-import sanity selected validation preserved")
        saved_selected_dir = facade.write_selected_report(
            selected_dir,
            validation_text="selected validation\n",
            validation_payload=prepared["validation"],
            pre_import_text="selected pre-import\n",
            pre_import_payload=selected_payload,
        )
        assert_equal(saved_selected_dir, selected_dir, "pre-import sanity selected save target")
        assert_equal(
            JsonStore.read(selected_dir / "result_validation.json", {}).get("kind"),
            "result_validation",
            "pre-import sanity selected validation JSON saved",
        )
        assert_equal(
            (selected_dir / "result_validation.txt").read_text(encoding="utf-8"),
            "selected validation\n",
            "pre-import sanity selected validation text saved",
        )
        assert_equal(
            JsonStore.read(selected_dir / "pre_import_sanity.json", {}).get("kind"),
            "pre_import_sanity",
            "pre-import sanity selected JSON saved",
        )
        assert_equal(
            (selected_dir / "pre_import_sanity.txt").read_text(encoding="utf-8"),
            "selected pre-import\n",
            "pre-import sanity selected text saved",
        )


def test_result_validation_pre_import_realistic_fixture_contract() -> None:
    report_fixture_path = ROOT / "smoke_tests" / "fixtures" / "report_export_contract_gpu_troubleshooting_extended_trimmed.json"
    stability_fixture_path = ROOT / "smoke_tests" / "fixtures" / "stage_diagnostics_stability_gpu_troubleshooting_extended_trimmed.json"
    parsed = json.loads(report_fixture_path.read_text())
    stability_fixture = json.loads(stability_fixture_path.read_text())

    workflow_payload = build_result_validation_payload(
        Path("realistic_gpu_fixture"),
        parsed,
        True,
        lambda name: name == "parsed_results_custom.json",
    )
    assert_equal(workflow_payload["kind"], "result_validation", "realistic validation workflow kind")
    assert_equal(workflow_payload["result"], "fail", "realistic validation workflow result")
    assert_equal(workflow_payload["profile_name"], "GPU Troubleshooting Extended", "realistic validation workflow profile")
    assert_equal(workflow_payload["checks"]["segments"], {"count": 4, "ok": True}, "realistic validation workflow segment check")
    assert_equal(
        workflow_payload["checks"]["support_files"]["missing"],
        ["run_summary.txt", "run_manifest.json", "run_metadata.json", "profile_used.json", "system_info.json"],
        "realistic validation workflow missing support files",
    )
    assert_equal(
        workflow_payload["checks"]["gpu_worker_summary"],
        {
            "SuccessfulWorkerResultCount": 8,
            "VerificationPasses": 20308,
            "WorkerFailureCount": 1,
            "WorkerResultCount": 9,
        },
        "realistic validation workflow worker summary",
    )
    assert_equal(workflow_payload["summary"], {"errors": 2, "warnings": 5, "segments": 4}, "realistic validation workflow summary")
    workflow_issues = {(issue["severity"], issue["category"], issue["message"]) for issue in workflow_payload["issues"]}
    assert_true(("error", "worker_results", "1 GPU worker(s) failed") in workflow_issues, "realistic validation worker failure issue")
    assert_true(
        (
            "error",
            "workload_or_system_error",
            "Review error-level events before treating this run as passing.",
        )
        in workflow_issues,
        "realistic validation action item issue",
    )
    assert_equal(
        sum(1 for issue in workflow_payload["issues"] if issue["category"] == "support_files"),
        5,
        "realistic validation support issue count",
    )

    comparison_summary = ResultComparisonFacade().comparison_summary(parsed)
    assert_equal(comparison_summary["result"], "Failed", "realistic comparison summary result")
    assert_equal(comparison_summary["outcome_class"], "workload_or_integrity_failure", "realistic comparison summary outcome")
    assert_equal(comparison_summary["warning_categories"], {"gpu_vram_verification_coverage": 1}, "realistic comparison warnings")
    assert_equal(comparison_summary["error_categories"], {"worker_exit": 2}, "realistic comparison errors")
    assert_equal(
        comparison_summary["gpu_worker_summary"],
        {"Passed": 8, "Failed": 1, "VerificationPasses": 20308},
        "realistic comparison canonical worker summary",
    )
    assert_equal(comparison_summary["action_item_category_counts"], {"report_only_threshold_recommendation": 1, "workload_or_system_error": 1}, "realistic comparison action categories")
    first_stage = comparison_summary["stages"]["GPU (3D Auto + VRAM)"]
    assert_equal(first_stage["verdict"], "fail", "realistic comparison failed stage verdict")
    assert_equal(first_stage["outcome_class"], "workload_or_integrity_failure", "realistic comparison failed stage outcome")
    assert_equal(first_stage["report_only_threshold_would_warn_count"], 1, "realistic comparison threshold caveat count")
    assert_equal(first_stage["warning_categories"], {"gpu_vram_verification_coverage": 1}, "realistic comparison failed stage warnings")
    assert_equal(first_stage["error_categories"], {"worker_exit": 2}, "realistic comparison failed stage errors")

    vram_thresholds = stability_fixture["Segments"][1]["StabilityInterpretation"]["ThresholdRecommendations"]
    assert_equal(vram_thresholds["WorkerVerifiedNoTelemetryCount"], 1, "realistic validation fixture worker-verified no telemetry count")
    assert_equal(
        vram_thresholds["Checks"][1]["Result"],
        "telemetry_unobserved_worker_verified",
        "realistic validation fixture worker-verified no telemetry result",
    )
    assert_equal(
        vram_thresholds["Checks"][1]["WorkerEvidence"]["SuccessfulWorkerResultCount"],
        1,
        "realistic validation fixture worker-verified no telemetry worker success",
    )

    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        selected_dir = root / "2026-07-06_09-58-40_GPU Troubleshooting Extended"
        batch_dir = root / "2026-07-06_09-58-40_GPU Troubleshooting Extended Batch"
        missing_dir = root / "2026-07-06_10-00-00_Missing"
        selected_dir.mkdir()
        batch_dir.mkdir()
        missing_dir.mkdir()
        JsonStore.write(selected_dir / "parsed_results_custom.json", parsed)
        JsonStore.write(batch_dir / "parsed_results_custom.json", parsed)

        validation = ResultValidationFacade(root)
        facade = PreImportSanityFacade(root, validation, RunSummaryTextExporter())
        prepared = facade.prepare_selected(selected_dir)
        selected_payload = facade.complete_selected(prepared, {"kind": "result_comparison", "result": "warning"})
        assert_equal(selected_payload["kind"], "pre_import_sanity", "realistic selected pre-import kind")
        assert_equal(selected_payload["result_folder"], str(selected_dir), "realistic selected pre-import folder")
        assert_equal(selected_payload["comparison"]["kind"], "result_comparison", "realistic selected comparison kind")
        assert_true(selected_payload["summary_refresh"]["refreshed"], "realistic selected summary refreshed")
        assert_equal(selected_payload["summary_refresh"]["error"], "", "realistic selected summary refresh error")
        selected_validation = selected_payload["validation"]
        assert_equal(selected_validation["kind"], "result_validation", "realistic selected validation kind")
        assert_equal(selected_validation["result"], "fail", "realistic selected validation result")
        assert_equal(selected_validation["summary"]["errors"], 4, "realistic selected validation errors")
        assert_equal(selected_validation["summary"]["warnings"], 16, "realistic selected validation warnings")
        assert_equal(selected_validation["summary"]["segments"], 4, "realistic selected validation segments")
        assert_equal(selected_validation["summary"]["gpu_highlights"], 8, "realistic selected validation GPU highlights")
        assert_equal(selected_validation["summary"]["action_items"], 2, "realistic selected validation action items")
        assert_equal(
            selected_validation["checks"]["export_contract"]["compatibility_mode"],
            "legacy_additive",
            "realistic selected export contract mode",
        )
        assert_equal(selected_validation["checks"]["export_contract"]["requires_legacy_importer_update"], False, "realistic selected importer safety")
        assert_equal(selected_validation["checks"]["stage_counts"], {"segments": 4, "segment_details": 4, "stage_outcomes": 4}, "realistic selected stage counts")
        assert_equal(selected_validation["checks"]["gpu_highlights"]["gpu_highlights"], 8, "realistic selected GPU highlight count")
        assert_equal(
            selected_validation["checks"]["action_items"]["severity_counts"],
            {"error": 1, "info": 1},
            "realistic selected action severity mirror",
        )
        assert_equal(
            selected_validation["summary"]["issue_category_counts"],
            {"gpu_targeting": 4, "gpu_worker_details": 4, "gpu_worker_summary": 3, "segment_shape": 4, "support_files": 5},
            "realistic selected issue categories",
        )

        batch_payload = facade.run_batch([batch_dir, missing_dir], save_individual_validation=False)
        assert_equal(batch_payload["kind"], "pre_import_sanity_batch", "realistic pre-import batch kind")
        assert_equal(batch_payload["result"], "fail", "realistic pre-import batch result")
        assert_equal(batch_payload["counts"]["total"], 2, "realistic pre-import batch total")
        assert_equal(batch_payload["counts"]["errors"], 4, "realistic pre-import batch errors")
        assert_equal(batch_payload["counts"]["warnings"], 16, "realistic pre-import batch warnings")
        assert_equal(batch_payload["counts"]["by_result"], {"fail": 2}, "realistic pre-import batch by-result")
        assert_equal(
            batch_payload["counts"]["issue_severity_category_counts"]["error"],
            {"segment_shape": 4},
            "realistic pre-import batch error categories",
        )
        assert_equal(
            batch_payload["counts"]["issue_severity_category_counts"]["warning"],
            {"gpu_targeting": 4, "gpu_worker_details": 4, "gpu_worker_summary": 3, "support_files": 5},
            "realistic pre-import batch warning categories",
        )
        assert_equal(batch_payload["summary_refresh"]["total"], 2, "realistic pre-import batch refresh total")
        assert_equal(batch_payload["summary_refresh"]["refreshed"], 1, "realistic pre-import batch refresh success")
        assert_equal(batch_payload["summary_refresh"]["failed"], 1, "realistic pre-import batch refresh failure")
        assert_equal(batch_payload["items"][0]["result"], "fail", "realistic pre-import batch first item result")
        assert_equal(batch_payload["items"][0]["summary"]["action_items"], 2, "realistic pre-import batch first item actions")
        assert_equal(batch_payload["items"][1]["result"], "fail", "realistic pre-import batch missing item result")
        assert_equal(batch_payload["items"][1]["summary"], {}, "realistic pre-import batch missing item summary")
        assert_true(batch_payload["summary_refresh"]["items"][1]["error"], "realistic pre-import batch missing refresh error")


def test_result_validation_pre_import_text_realistic_fixture_contract() -> None:
    report_fixture_path = ROOT / "smoke_tests" / "fixtures" / "report_export_contract_gpu_troubleshooting_extended_trimmed.json"
    stability_fixture_path = ROOT / "smoke_tests" / "fixtures" / "stage_diagnostics_stability_gpu_troubleshooting_extended_trimmed.json"
    parsed = json.loads(report_fixture_path.read_text())
    stability_fixture = json.loads(stability_fixture_path.read_text())

    overview_text = result_overview_text_from_payload("realistic_fixture", parsed)
    stage_details_text = result_stage_details_text_from_payload("stability_fixture", stability_fixture)
    assert_true("Result: Failed" in overview_text, "realistic text overview failed result")
    assert_true("Profile: GPU Troubleshooting Extended" in overview_text, "realistic text overview profile")
    assert_true("GPU workers: 8/9 successful, 1 failed" in overview_text, "realistic text canonical worker summary")
    assert_true(
        "[error] workload_or_system_error: Review error-level events before treating this run as passing." in overview_text,
        "realistic text overview worker failure action",
    )
    assert_true(
        "Coverage: Separate concurrent VRAM worker omitted for Granite Ridge [Radeon Graphics]" in stage_details_text,
        "realistic text worker coverage evidence",
    )
    assert_true(
        "[info] report_only_threshold_recommendation: Review advisory performance threshold misses" in stage_details_text,
        "realistic text threshold advisory action",
    )

    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        selected_dir = root / "2026-07-06_09-58-40_GPU Troubleshooting Extended"
        batch_dir = root / "2026-07-06_09-58-40_GPU Troubleshooting Extended Batch"
        missing_dir = root / "2026-07-06_10-00-00_Missing"
        selected_dir.mkdir()
        batch_dir.mkdir()
        missing_dir.mkdir()
        JsonStore.write(selected_dir / "parsed_results_custom.json", parsed)
        JsonStore.write(batch_dir / "parsed_results_custom.json", parsed)

        validation = ResultValidationFacade(root)
        facade = PreImportSanityFacade(root, validation, RunSummaryTextExporter())
        prepared = facade.prepare_selected(selected_dir)
        selected_validation_text = result_validation_text(prepared["validation"])
        assert_true("Result Folder Validation" in selected_validation_text, "realistic text validation header")
        assert_true("Result: FAIL (4 error(s), 16 warning(s))" in selected_validation_text, "realistic text validation counts")
        assert_true("Segments: 4" in selected_validation_text, "realistic text validation segments")
        assert_true("GPU worker details: 4" in selected_validation_text, "realistic text validation worker details")
        assert_true("GPU highlights: 8" in selected_validation_text, "realistic text validation GPU highlights")
        assert_true("Action items: 2" in selected_validation_text, "realistic text validation action items")
        assert_true(
            "Issue categories: {'gpu_targeting': 4, 'gpu_worker_details': 4, 'gpu_worker_summary': 3, 'segment_shape': 4, 'support_files': 5}"
            in selected_validation_text,
            "realistic text validation issue categories",
        )
        assert_true(
            "[warning] gpu_worker_summary: GpuWorkerSummary.SuccessfulWorkerResultCount does not match validation detail statuses"
            in selected_validation_text,
            "realistic text validation canonical worker issue",
        )
        assert_true(
            "[warning] gpu_worker_details: GPU (3D Auto + VRAM) GPU worker is missing TargetId"
            in selected_validation_text,
            "realistic text validation worker detail issue",
        )

        comparison_payload = ResultComparisonFacade().compare_result_folders(selected_dir, selected_dir)
        comparison_text = result_comparison_text(comparison_payload)
        assert_true("Result Folder Comparison" in comparison_text, "realistic text comparison header")
        assert_true("Result: Failed -> Failed" in comparison_text, "realistic text comparison result")
        assert_true("Outcome: workload_or_integrity_failure -> workload_or_integrity_failure" in comparison_text, "realistic text comparison outcome")
        assert_true("GPU Worker Deltas\n-----------------\nWorker: no changes" in comparison_text, "realistic text comparison worker delta")

        selected_payload = facade.complete_selected(prepared, comparison_payload)
        selected_sanity_text = selected_pre_import_sanity_text(selected_payload)
        assert_true("Pre-Import Sanity Check" in selected_sanity_text, "realistic text selected pre-import header")
        assert_true("Validation\n----------" in selected_sanity_text, "realistic text selected validation section")
        assert_true("Result: FAIL (4 error(s), 16 warning(s))" in selected_sanity_text, "realistic text selected validation counts")
        assert_true("Run Summary\n-----------\nRefreshed:" in selected_sanity_text, "realistic text selected run summary refresh")
        assert_true("Comparison\n----------\nResult Folder Comparison" in selected_sanity_text, "realistic text selected comparison section")

        batch_payload = facade.run_batch([batch_dir, missing_dir], save_individual_validation=False)
        batch_validation_text_output = batch_result_validation_text(batch_payload["validation"])
        assert_true("Batch Result Validation" in batch_validation_text_output, "realistic text batch validation header")
        assert_true("Folders checked: 2" in batch_validation_text_output, "realistic text batch validation total")
        assert_true("Validation: 4 error(s), 16 warning(s)" in batch_validation_text_output, "realistic text batch validation counts")
        assert_true("By result: {'fail': 2}" in batch_validation_text_output, "realistic text batch validation by-result")
        assert_true(
            "- 2026-07-06_09-58-40_GPU Troubleshooting Extended Batch: FAIL (4e/16w"
            in batch_validation_text_output,
            "realistic text batch validation failed item",
        )

        batch_sanity_text_output = batch_pre_import_sanity_text(batch_payload)
        assert_true("Batch Pre-Import Sanity Check" in batch_sanity_text_output, "realistic text batch sanity header")
        assert_true("Run summaries: 1 refreshed, 1 failed" in batch_sanity_text_output, "realistic text batch sanity refresh counts")
        assert_true(
            "- 2026-07-06_10-00-00_Missing: FAIL (0e/0w, summary_refreshed=False, refresh_error=" in batch_sanity_text_output,
            "realistic text batch sanity missing-result failure",
        )
        assert_true("parsed_results_custom.json" in batch_sanity_text_output, "realistic text batch sanity missing parsed JSON")


def test_qa_result_review_facade_contract() -> None:
    report_fixture_path = ROOT / "smoke_tests" / "fixtures" / "report_export_contract_gpu_troubleshooting_extended_trimmed.json"
    parsed = json.loads(report_fixture_path.read_text())

    def assert_qa_result_contract(payload: dict, label: str) -> None:
        required_top_level = {
            "app_name",
            "app_version",
            "contract_id",
            "contract_version",
            "kind",
            "started",
            "ended",
            "result_folder",
            "identity",
            "decisions",
            "validation_status",
            "validation",
            "import_readiness",
            "pre_import_sanity",
            "summary_refresh",
            "comparison_readiness",
            "comparison",
            "artifact_availability",
            "worker_failure_evidence",
            "action_item_summary",
            "telemetry_stability_warning_summary",
        }
        missing = sorted(required_top_level.difference(payload))
        assert_equal(missing, [], f"{label} QA result required top-level fields")
        assert_required_fields(payload, QA_REVIEW_REQUIRED_FIELDS, label=f"{label} QA result")
        assert_equal(payload["contract_id"], QA_REVIEW_CONTRACT_ID, f"{label} QA result contract id")
        assert_equal(payload["contract_version"], QA_REVIEW_CONTRACT_VERSION, f"{label} QA result contract version")
        assert_equal(payload["kind"], "qa_result_review", f"{label} QA result kind")
        for section_name in (
            "identity",
            "decisions",
            "validation_status",
            "import_readiness",
            "summary_refresh",
            "comparison_readiness",
            "artifact_availability",
            "worker_failure_evidence",
            "action_item_summary",
            "telemetry_stability_warning_summary",
        ):
            assert_true(isinstance(payload[section_name], dict), f"{label} QA result {section_name} is object")
        identity_required = {
            "folder",
            "folder_name",
            "exists",
            "parsed_results_custom_exists",
            "profile_name",
            "result",
            "outcome_class",
            "department_status",
            "stage_count",
            "elapsed",
        }
        assert_equal(
            sorted(identity_required.difference(payload["identity"])),
            [],
            f"{label} QA result identity required fields",
        )
        decisions_required = {"review", "import", "compare", "escalate"}
        assert_equal(
            sorted(decisions_required.difference(payload["decisions"])),
            [],
            f"{label} QA result decisions required fields",
        )
        assert_true("status" in payload["decisions"]["review"], f"{label} QA review status present")
        assert_true("status" in payload["import_readiness"], f"{label} QA import status present")
        assert_true("status" in payload["comparison_readiness"], f"{label} QA comparison status present")
        assert_true("kind" in payload["artifact_availability"], f"{label} QA artifact kind present")
        assert_true(
            "worker_failure_count" in payload["worker_failure_evidence"],
            f"{label} QA worker failure count present",
        )
        assert_true("severity_counts" in payload["action_item_summary"], f"{label} QA action severity counts present")
        assert_true(
            "warning_categories" in payload["telemetry_stability_warning_summary"],
            f"{label} QA telemetry warning categories present",
        )
        assert_snake_case_keys(
            payload,
            excluded_subtrees={
                ("validation",),
                ("pre_import_sanity",),
                ("comparison",),
                ("review_verdict",),
                ("worker_failure_evidence", "raw_summary"),
                ("action_item_summary", "details"),
            },
            label=f"{label} QA-owned envelope",
        )

    def assert_qa_batch_contract(payload: dict) -> None:
        required_top_level = {
            "app_name",
            "app_version",
            "contract_id",
            "contract_version",
            "kind",
            "started",
            "ended",
            "results_dir",
            "counts",
            "items",
        }
        assert_equal(
            sorted(required_top_level.difference(payload)),
            [],
            "QA batch required top-level fields",
        )
        assert_required_fields(payload, QA_BATCH_REQUIRED_FIELDS, label="QA batch")
        assert_equal(payload["contract_id"], QA_REVIEW_CONTRACT_ID, "QA batch contract id")
        assert_equal(payload["contract_version"], QA_REVIEW_CONTRACT_VERSION, "QA batch contract version")
        assert_equal(payload["kind"], "qa_result_review_batch", "QA batch kind")
        count_required = {
            "total",
            "validation_by_result",
            "import_by_status",
            "review_by_status",
            "escalation_needed",
        }
        assert_equal(
            sorted(count_required.difference(payload["counts"])),
            [],
            "QA batch count required fields",
        )
        assert_true(isinstance(payload["items"], list), "QA batch items list")
        for index, item in enumerate(payload["items"]):
            assert_qa_result_contract(item, f"QA batch item {index}")
        assert_snake_case_keys(
            payload,
            excluded_subtrees={
                ("items", "*", "validation"),
                ("items", "*", "pre_import_sanity"),
                ("items", "*", "comparison"),
                ("items", "*", "review_verdict"),
                ("items", "*", "worker_failure_evidence", "raw_summary"),
                ("items", "*", "action_item_summary", "details"),
            },
            label="QA batch-owned envelope",
        )

    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        result_dir = root / "2026-07-06_09-58-40_GPU Troubleshooting Extended"
        baseline_dir = root / "2026-07-06_09-58-40_GPU Troubleshooting Extended Baseline"
        missing_dir = root / "2026-07-06_10-00-00_Missing"
        result_dir.mkdir()
        baseline_dir.mkdir()
        JsonStore.write(result_dir / "parsed_results_custom.json", parsed)
        JsonStore.write(baseline_dir / "parsed_results_custom.json", parsed)

        service = SuiteAppService.__new__(SuiteAppService)
        service.summary_exporter = RunSummaryTextExporter()
        service.result_validation = ResultValidationFacade(root)
        service.result_comparison = ResultComparisonFacade()
        service.pre_import_sanity = PreImportSanityFacade(root, service.result_validation, service.summary_exporter)
        service.result_artifacts = ResultArtifactFacade(root)

        payload = service.qa_result_review_payload(result_dir, comparison_dir=baseline_dir)
        assert_qa_result_contract(payload, "QA review realistic")
        assert_equal(payload["kind"], "qa_result_review", "QA review payload kind")
        assert_equal(payload["identity"]["folder_name"], result_dir.name, "QA review identity folder")
        assert_equal(payload["identity"]["profile_name"], "GPU Troubleshooting Extended", "QA review identity profile")
        assert_equal(payload["identity"]["result"], "Failed", "QA review identity result")
        assert_equal(payload["identity"]["outcome_class"], "workload_or_integrity_failure", "QA review identity outcome")
        assert_equal(payload["validation_status"]["result"], "fail", "QA review validation result")
        assert_equal(payload["validation_status"]["errors"], 4, "QA review validation errors")
        assert_equal(payload["validation_status"]["warnings"], 16, "QA review validation warnings")
        assert_equal(
            payload["validation_status"]["issue_category_counts"],
            {"gpu_targeting": 4, "gpu_worker_details": 4, "gpu_worker_summary": 3, "segment_shape": 4, "support_files": 5},
            "QA review validation issue categories",
        )
        assert_true(payload["summary_refresh"]["refreshed"], "QA review summary refresh")
        assert_equal(payload["import_readiness"]["status"], "fail", "QA review import readiness fail")
        assert_true(payload["import_readiness"]["blocking"], "QA review import readiness blocking")
        assert_true(payload["decisions"]["review"]["ready"], "QA review review-ready decision")
        assert_true(payload["decisions"]["escalate"]["needed"], "QA review escalation decision")
        assert_equal(
            payload["decisions"]["escalate"]["reasons"],
            ["validation_errors", "worker_failures", "error_action_items"],
            "QA review escalation reasons",
        )
        assert_equal(payload["comparison_readiness"]["status"], "compared", "QA review comparison status")
        assert_equal(payload["comparison"]["kind"], "result_comparison", "QA review comparison payload")
        assert_equal(payload["artifact_availability"]["kind"], "run_result", "QA review artifact kind")
        assert_true(payload["artifact_availability"]["has_parsed_results"], "QA review parsed artifact")
        assert_equal(payload["worker_failure_evidence"]["worker_result_count"], 9, "QA review worker total")
        assert_equal(payload["worker_failure_evidence"]["successful_worker_result_count"], 8, "QA review worker successes")
        assert_equal(payload["worker_failure_evidence"]["worker_failure_count"], 1, "QA review worker failures")
        assert_equal(payload["worker_failure_evidence"]["verification_passes"], 20308, "QA review verification passes")
        assert_true(payload["worker_failure_evidence"]["has_worker_failures"], "QA review worker failure flag")
        assert_equal(payload["action_item_summary"]["severity_counts"], {"error": 1, "info": 1}, "QA review action severities")
        assert_equal(
            payload["action_item_summary"]["category_counts"],
            {"report_only_threshold_recommendation": 1, "workload_or_system_error": 1},
            "QA review action categories",
        )
        assert_equal(
            payload["telemetry_stability_warning_summary"]["warning_categories"],
            {"gpu_vram_verification_coverage": 1},
            "QA review telemetry warning categories",
        )
        assert_equal(
            payload["telemetry_stability_warning_summary"]["error_categories"],
            {"worker_exit": 2},
            "QA review telemetry error categories",
        )

        missing_payload = service.qa_result_review_payload(missing_dir, refresh_summary=False)
        assert_qa_result_contract(missing_payload, "QA review missing")
        assert_equal(missing_payload["kind"], "qa_result_review", "QA missing review payload kind")
        assert_equal(missing_payload["identity"]["parsed_results_custom_exists"], False, "QA missing parsed flag")
        assert_equal(missing_payload["validation_status"]["result"], "fail", "QA missing validation result")
        assert_equal(missing_payload["decisions"]["review"]["status"], "blocked", "QA missing review blocked")
        assert_equal(missing_payload["comparison_readiness"]["status"], "blocked", "QA missing comparison blocked")
        assert_equal(missing_payload["artifact_availability"]["kind"], "missing", "QA missing artifact kind")
        assert_true("review_blocked" in missing_payload["decisions"]["escalate"]["reasons"], "QA missing escalation reason")

        batch_payload = service.qa_batch_review_payload([result_dir, missing_dir], refresh_summary=False)
        assert_qa_batch_contract(batch_payload)
        assert_equal(batch_payload["kind"], "qa_result_review_batch", "QA batch payload kind")
        assert_equal(batch_payload["counts"]["total"], 2, "QA batch total")
        assert_equal(batch_payload["counts"]["validation_by_result"], {"fail": 2}, "QA batch validation counts")
        assert_equal(batch_payload["counts"]["import_by_status"], {"fail": 2}, "QA batch import counts")
        assert_equal(batch_payload["counts"]["review_by_status"], {"blocked": 1, "ready": 1}, "QA batch review counts")
        assert_equal(batch_payload["counts"]["escalation_needed"], 2, "QA batch escalation count")


def test_qa_review_cli_wrapper() -> None:
    wrapper_fixture_path = ROOT / "smoke_tests" / "fixtures" / "qa_review_cli_wrapper_shape_fixture.json"
    expected_wrapper_output = json.loads(wrapper_fixture_path.read_text())

    class FakeQaService:
        def __init__(self) -> None:
            self.review_calls = []
            self.batch_calls = []

        def qa_result_review_payload(self, result_dir, comparison_dir=None, refresh_summary=True):
            self.review_calls.append((result_dir, comparison_dir, refresh_summary))
            return {
                "kind": "qa_result_review",
                "contract_id": QA_REVIEW_CONTRACT_ID,
                "contract_version": QA_REVIEW_CONTRACT_VERSION,
                "result_folder": str(result_dir),
                "comparison_folder": str(comparison_dir or ""),
                "summary_refresh_requested": refresh_summary,
                "identity": {"folder_name": Path(result_dir).name, "parsed_results_custom_exists": False},
                "decisions": {"review": {"status": "blocked"}},
                "validation_status": {"result": "fail"},
                "import_readiness": {"status": "fail"},
                "comparison_readiness": {"status": "blocked"},
                "artifact_availability": {"kind": "missing"},
                "worker_failure_evidence": {"worker_failure_count": 0},
                "action_item_summary": {"severity_counts": {}},
                "telemetry_stability_warning_summary": {"warning_categories": {}},
            }

        def qa_batch_review_payload(self, candidates=None, refresh_summary=False):
            self.batch_calls.append((candidates, refresh_summary))
            items = [
                {
                    "kind": "qa_result_review",
                    "contract_id": QA_REVIEW_CONTRACT_ID,
                    "contract_version": QA_REVIEW_CONTRACT_VERSION,
                    "result_folder": str(path),
                }
                for path in list(candidates or [])
            ]
            return {
                "kind": "qa_result_review_batch",
                "contract_id": QA_REVIEW_CONTRACT_ID,
                "contract_version": QA_REVIEW_CONTRACT_VERSION,
                "counts": {"total": len(items)},
                "items": items,
            }

    services = []

    def service_factory(settings_path):
        service = FakeQaService()
        service.settings_path = settings_path
        services.append(service)
        return service

    review_stdout = io.StringIO()
    review_stderr = io.StringIO()
    review_code = qa_review_cli_main(
        ["--settings", "/tmp/settings.json", "review", "/tmp/missing", "--comparison", "/tmp/baseline"],
        service_factory=service_factory,
        stdout=review_stdout,
        stderr=review_stderr,
    )
    review_payload = json.loads(review_stdout.getvalue())
    assert_equal(review_code, 0, "QA CLI review exit code")
    assert_equal(review_payload, expected_wrapper_output["review"], "QA CLI review JSON fixture shape")
    assert_equal(review_payload["kind"], "qa_result_review", "QA CLI review kind")
    assert_equal(review_payload["contract_id"], QA_REVIEW_CONTRACT_ID, "QA CLI review contract id")
    assert_equal(review_payload["contract_version"], QA_REVIEW_CONTRACT_VERSION, "QA CLI review contract version")
    assert_equal(review_payload["artifact_availability"]["kind"], "missing", "QA CLI missing-path payload shape")
    assert_equal(
        services[-1].review_calls,
        [(Path("/tmp/missing"), Path("/tmp/baseline"), False)],
        "QA CLI review calls service without summary refresh by default",
    )
    assert_equal(services[-1].settings_path, Path("/tmp/settings.json"), "QA CLI passes settings path")
    assert_equal(review_stderr.getvalue(), "", "QA CLI review no stderr")

    batch_stdout = io.StringIO()
    batch_code = qa_review_cli_main(
        ["batch", "/tmp/one", "/tmp/two", "--refresh-summary"],
        service_factory=service_factory,
        stdout=batch_stdout,
        stderr=io.StringIO(),
    )
    batch_payload = json.loads(batch_stdout.getvalue())
    assert_equal(batch_code, 0, "QA CLI batch exit code")
    assert_equal(batch_payload, expected_wrapper_output["batch"], "QA CLI batch JSON fixture shape")
    assert_equal(batch_payload["kind"], "qa_result_review_batch", "QA CLI batch kind")
    assert_equal(batch_payload["counts"]["total"], 2, "QA CLI batch total")
    assert_equal(
        services[-1].batch_calls,
        [([Path("/tmp/one"), Path("/tmp/two")], True)],
        "QA CLI batch calls service with explicit candidates",
    )

    failure_stdout = io.StringIO()
    failure_stderr = io.StringIO()
    failure_code = qa_review_cli_main(
        ["review", "/tmp/broken"],
        service_factory=lambda _settings_path: SimpleNamespace(
            qa_result_review_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        ),
        stdout=failure_stdout,
        stderr=failure_stderr,
    )
    assert_equal(failure_code, 1, "QA CLI failure exit code")
    assert_equal(failure_stdout.getvalue(), "", "QA CLI failure no JSON")
    assert_true("QA payload command failed: boom" in failure_stderr.getvalue(), "QA CLI failure stderr")


def test_hardware_result_validation_matrix_payloads() -> None:
    manifest_path = ROOT / "hardware_result_validation_matrix.json"
    manifest = load_hardware_matrix(manifest_path)
    assert_equal(
        manifest.get("contract_id"),
        "linux_validation_suite.hardware_result_validation_matrix",
        "hardware matrix contract id",
    )
    assert_true(manifest.get("local_state_required") is False, "hardware matrix local state optional")
    expected_categories = {
        "single_cpu_clean_run",
        "dual_cpu_package_topology_run",
        "nvidia_dgpu_clean_run",
        "nvidia_dgpu_warning_failure_run",
        "amd_gpu_or_igpu_run",
        "privileged_telemetry_run",
        "no_privileged_telemetry_run",
        "heatsoak_run",
        "gpu_vram_warning_failure_case",
        "clean_passing_run",
    }
    entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    categories = matrix_categories(manifest)
    assert_equal(categories, expected_categories, "hardware matrix categories")
    for entry in entries:
        category = entry.get("category")
        assert_true(bool(entry.get("label")), f"{category} hardware matrix label")
        assert_true(entry.get("required") is True, f"{category} hardware matrix required flag")
        expectations = entry.get("evidence_expectations")
        assert_true(isinstance(expectations, list) and bool(expectations), f"{category} evidence expectations")
        assert_true("path" not in entry, f"{category} public matrix has no retained result path")

    state_path = ROOT / matrix_state_file(manifest)
    state = load_hardware_matrix_state(state_path, manifest)
    validation = validate_hardware_matrix_state(state, ROOT)

    service = SuiteAppService.__new__(SuiteAppService)
    results_root = ROOT / "results"
    service.summary_exporter = RunSummaryTextExporter()
    service.result_validation = ResultValidationFacade(results_root)
    service.result_comparison = ResultComparisonFacade()
    service.pre_import_sanity = PreImportSanityFacade(results_root, service.result_validation, service.summary_exporter)
    service.result_artifacts = ResultArtifactFacade(results_root)

    strict = os.environ.get("LVS_STRICT_HARDWARE_MATRIX") == "1"
    checked_count = 0
    for entry in validation["missing"]:
        category = entry.get("category")
        assert_true(bool(entry.get("missing_reason")), f"{category} missing reason")

    for entry in validation["confirmed"]:
        category = entry.get("category")
        result_dir = ROOT / str(entry.get("path") or "")
        payload = service.qa_result_review_payload(result_dir, refresh_summary=False)
        assert_equal(payload["contract_id"], QA_REVIEW_CONTRACT_ID, f"{category} QA contract id")
        assert_equal(payload["contract_version"], QA_REVIEW_CONTRACT_VERSION, f"{category} QA contract version")
        assert_equal(payload["kind"], "qa_result_review", f"{category} QA payload kind")
        assert_equal(payload["result_folder"], str(result_dir), f"{category} QA result folder")
        assert_true(isinstance(payload.get("identity"), dict), f"{category} QA identity object")
        assert_true(isinstance(payload.get("validation_status"), dict), f"{category} QA validation status object")
        assert_true(isinstance(payload.get("artifact_availability"), dict), f"{category} QA artifact object")
        assert_equal(
            payload["artifact_availability"].get("has_parsed_results"),
            True,
            f"{category} QA parsed artifact available",
        )
        checked_count += 1

    if strict:
        assert_equal(validation["stale"], [], "strict hardware matrix has no stale retained result paths")
        assert_true(checked_count >= 1, "strict hardware matrix checked retained results")


def test_hardware_matrix_state_lifecycle() -> None:
    matrix = {
        "entries": [
            {"category": "clean_passing_run"},
            {"category": "heatsoak_run"},
            {"category": "privileged_telemetry_run"},
        ]
    }
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        missing_state = load_hardware_matrix_state(root / "missing_state.json", matrix)
        missing_validation = validate_hardware_matrix_state(missing_state, root)
        assert_equal(missing_validation["counts"]["missing"], 3, "missing state treated as empty local state")
        assert_equal(missing_validation["counts"]["stale"], 0, "missing state has no stale paths")

        stale_state = {
            "entries": [
                {
                    "category": "clean_passing_run",
                    "status": "confirmed",
                    "path": "results/deleted",
                },
                {
                    "category": "heatsoak_run",
                    "status": "missing",
                    "missing_reason": "not captured yet",
                },
            ]
        }
        normalized = normalize_like_loaded_state = load_hardware_matrix_state_fixture(stale_state, matrix)
        stale_validation = validate_hardware_matrix_state(normalized, root)
        assert_equal(stale_validation["counts"]["stale"], 1, "stale retained path detected")
        pruned = prune_stale_hardware_matrix_state(normalized, root)
        pruned_entry = next(entry for entry in pruned["entries"] if entry.get("category") == "clean_passing_run")
        assert_equal(pruned_entry.get("status"), "missing", "prune converts stale entry to missing")
        assert_equal(pruned_entry.get("previous_path"), "results/deleted", "prune preserves stale previous path")


def load_hardware_matrix_state_fixture(state: dict, matrix: dict) -> dict:
    with TemporaryDirectory(dir="/tmp") as tmp:
        state_path = Path(tmp) / "state.json"
        state_path.write_text(json.dumps(state))
        return load_hardware_matrix_state(state_path, matrix)


def test_hardware_matrix_state_discovery() -> None:
    matrix = {
        "entries": [
            {"category": "clean_passing_run"},
            {"category": "heatsoak_run"},
            {"category": "nvidia_dgpu_clean_run"},
            {"category": "privileged_telemetry_run"},
            {"category": "no_privileged_telemetry_run"},
        ]
    }
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        result_dir = root / "results" / "2026-01-01_00-00-00_Quick Test"
        result_dir.mkdir(parents=True)
        (result_dir / "parsed_results_custom.json").write_text(
            json.dumps(
                {
                    "FinalResult": "Pass",
                    "Metadata": {
                        "ProfileName": "Quick Test",
                        "ReportSummary": {"OutcomeClass": "Pass"},
                    },
                    "Gpu": {"Devices": [{"Name": "NVIDIA Test GPU"}]},
                    "Heatsoak": {"Enabled": True},
                }
            )
        )
        (result_dir / "telemetry_source_map.json").write_text(
            json.dumps({"telemetry_privilege": {"source_mode": "sudo_telemetry", "sudo_sources_used": True}})
        )

        discovered = discover_hardware_matrix_state(matrix, root / "results")
        validation = validate_hardware_matrix_state(discovered, root)
        confirmed_categories = {entry.get("category") for entry in validation["confirmed"]}
        assert_true("clean_passing_run" in confirmed_categories, "discovery finds clean passing run")
        assert_true("heatsoak_run" in confirmed_categories, "discovery finds heatsoak run")
        assert_true("nvidia_dgpu_clean_run" in confirmed_categories, "discovery finds NVIDIA clean run")
        assert_true("privileged_telemetry_run" in confirmed_categories, "discovery finds privileged telemetry run")
        assert_true("no_privileged_telemetry_run" not in confirmed_categories, "discovery does not invent unprivileged run")


def test_hardware_matrix_state_refresh_action() -> None:
    matrix = {
        "contract_id": "linux_validation_suite.hardware_result_validation_matrix",
        "contract_version": 2,
        "local_state_file": "hardware_result_validation_state.json",
        "entries": [
            {"category": "clean_passing_run"},
            {"category": "heatsoak_run"},
            {"category": "nvidia_dgpu_clean_run"},
        ],
    }
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        (root / "hardware_result_validation_matrix.json").write_text(json.dumps(matrix))
        retained = root / "results" / "retained-confirmed"
        retained.mkdir(parents=True)
        (retained / "parsed_results_custom.json").write_text(json.dumps({"Result": "Pass"}))
        stale_candidate = {
            "entries": [
                {
                    "category": "clean_passing_run",
                    "status": "confirmed",
                    "path": "results/retained-confirmed",
                    "source": "maintainer",
                },
                {
                    "category": "heatsoak_run",
                    "status": "candidate",
                    "path": "results/deleted-candidate",
                },
            ]
        }
        state_path = root / "hardware_result_validation_state.json"
        state_path.write_text(json.dumps(stale_candidate))

        fuzzy = root / "results" / "fuzzy"
        fuzzy.mkdir()
        (fuzzy / "parsed_results_custom.json").write_text(
            json.dumps({"Notes": "heatsoak review: no issues found; NVIDIA GPU present"})
        )
        fuzzy_discovery = discover_hardware_matrix_state(matrix, fuzzy)
        fuzzy_entries = {entry["category"]: entry for entry in fuzzy_discovery["entries"]}
        assert_equal(fuzzy_entries["heatsoak_run"]["status"], "candidate", "broad heatsoak evidence is candidate")
        assert_equal(
            fuzzy_entries["nvidia_dgpu_clean_run"]["status"],
            "candidate",
            "broad NVIDIA/clean evidence is candidate",
        )
        strong = root / "results" / "strong"
        strong.mkdir()
        (strong / "parsed_results_custom.json").write_text(
            json.dumps(
                {
                    "Result": "Pass",
                    "Gpu": {"Devices": [{"Name": "NVIDIA Test GPU"}]},
                    "Heatsoak": {"Enabled": True},
                }
            )
        )

        summary = refresh_hardware_matrix_state(root)
        written = json.loads(state_path.read_text())
        entries = {entry["category"]: entry for entry in written["entries"]}
        assert_equal(summary["stale_pruned"], 1, "refresh counts pruned stale candidate")
        assert_equal(entries["clean_passing_run"]["path"], "results/retained-confirmed", "confirmed mapping preserved")
        assert_equal(entries["clean_passing_run"]["source"], "maintainer", "confirmed mapping metadata preserved")
        assert_equal(entries["heatsoak_run"]["status"], "confirmed", "strong evidence upgrades stale candidate")
        assert_equal(entries["nvidia_dgpu_clean_run"]["status"], "confirmed", "structured NVIDIA evidence confirmed")
        assert_equal(summary["confirmed"], 3, "refresh confirmed summary")
        assert_equal(summary["missing"], 0, "refresh missing summary")
        assert_equal(summary["candidate"], 0, "refresh candidate summary")
        assert_equal(summary["state_file"], str(state_path), "refresh output state path")

        state_path.write_text("not json")
        try:
            refresh_hardware_matrix_state(root)
        except ValueError as exc:
            assert_true("unreadable" in str(exc), "refresh rejects malformed existing state")
        else:
            raise AssertionError("refresh should reject malformed existing state")
        assert_equal(state_path.read_text(), "not json", "malformed state is not overwritten")


def test_public_support_export_missing_optional_files() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        result = PublicSupportExporter(root).export()
        payload = result.payload

        assert_equal(payload["contract_id"], EXPORT_CONTRACT_ID, "local environment export contract id")
        assert_equal(payload["contract_version"], EXPORT_CONTRACT_VERSION, "local environment export contract version")
        assert_equal(payload["settings"]["global_settings"]["status"], "missing", "missing local settings allowed")
        assert_equal(payload["settings"]["run_setup_history"]["status"], "missing", "missing setup history allowed")
        assert_equal(payload["google_drive"]["configured"], False, "missing Google integration allowed")
        assert_equal(payload["results"]["active"]["status"], "missing", "missing results directory reported")
        assert_equal(payload["hardware_result_validation_state"]["status"], "missing", "missing hardware state allowed")
        assert_equal(payload["sensor_probe_logs"]["status"], "missing", "missing sensor logs allowed")
        assert_equal(payload["virtual_environment"]["status"], "missing", "missing virtual environment allowed")
        assert_true(result.json_path.is_file(), "missing-file export still writes JSON")
        assert_true(result.summary_path.is_file(), "missing-file export still writes text")


def test_public_support_export_redacts_private_values() -> None:
    secret_markers = {
        "private-client-secret-value",
        "private-shared-drive-id",
        "private-customer-name",
        "private-operator-name",
        "private-result-folder-name",
    }
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        settings_dir = root / "settings"
        credential_path = root / "private" / "client-secret.json"
        credential_path.parent.mkdir(parents=True)
        credential_path.write_text('{"client_secret": "private-client-secret-value"}', encoding="utf-8")
        settings_dir.mkdir()
        JsonStore.write(
            settings_dir / "global_settings.json",
            {
                "environment_mode": "production",
                "results_dir": "results",
                "suite_department": "private-customer-name",
                "runtime_environment": {"PRIVATE_TOKEN": "private-client-secret-value"},
                "google_drive_credentials_path": str(credential_path),
                "google_drive_shared_drive_id": "private-shared-drive-id",
            },
        )
        JsonStore.write(
            settings_dir / "run_setup_history.json",
            [{"operator": "private-operator-name", "description": "private-customer-name"}],
        )
        JsonStore.write(
            root / "hardware_result_validation_state.json",
            {
                "entries": [
                    {
                        "category": "clean_passing_run",
                        "status": "confirmed",
                        "path": "results/private-result-folder-name",
                    }
                ]
            },
        )

        result = PublicSupportExporter(root).export()
        exported = result.json_path.read_text(encoding="utf-8") + result.summary_path.read_text(encoding="utf-8")
        for marker in secret_markers:
            assert_true(marker not in exported, f"local environment export redacts {marker}")
        assert_true(str(root) not in exported, "local environment export redacts absolute local root")
        assert_equal(result.payload["google_drive"]["shared_drive_id"], "redacted", "Google ID redacted")
        assert_equal(result.payload["safety"]["secret_contents_exported"], False, "secret contents excluded")
        assert_equal(
            result.payload["hardware_result_validation_state"]["local_result_paths_exported"],
            False,
            "hardware state result paths excluded",
        )


def test_public_support_export_generated_summary_shape() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        (root / "settings").mkdir()
        JsonStore.write(
            root / "settings" / "global_settings.json",
            {"environment_mode": "end_user", "results_dir": "results"},
        )
        (root / "settings" / "global_settings.example.json").write_text("{}\n", encoding="utf-8")
        for path in (
            root / "results" / "Run A",
            root / "results" / "Run B",
            root / "results" / "Archived" / "Archived A",
            root / "results" / "Uploaded" / "Uploaded A",
        ):
            path.mkdir(parents=True)
        (root / "sensor_probe_logs").mkdir()
        (root / "sensor_probe_logs" / "probe.log").write_text("probe\n", encoding="utf-8")
        (root / ".venv").mkdir()
        (root / ".venv" / "pyvenv.cfg").write_text("version = 3.14.3\n", encoding="utf-8")
        JsonStore.write(
            root / "hardware_result_validation_state.json",
            {
                "entries": [
                    {"category": "clean", "status": "confirmed", "path": "results/Run A"},
                    {"category": "review", "status": "candidate", "path": "results/Run B"},
                    {"category": "missing", "status": "missing"},
                ]
            },
        )

        result = PublicSupportExporter(root).export()
        payload = json.loads(result.json_path.read_text(encoding="utf-8"))
        assert_contract_identity(
            payload,
            contract_id=EXPORT_CONTRACT_ID,
            contract_version=EXPORT_CONTRACT_VERSION,
            kind="public_safe_local_environment_summary",
            label="public support summary",
        )
        assert_snake_case_keys(payload, label="public support summary")
        assert_equal(payload["kind"], "public_safe_local_environment_summary", "local export summary kind")
        assert_equal(payload["results"]["active"]["directory_count"], 2, "local export active result count")
        assert_equal(payload["results"]["archived"]["directory_count"], 1, "local export archived count")
        assert_equal(payload["results"]["uploaded"]["directory_count"], 1, "local export uploaded count")
        assert_equal(payload["sensor_probe_logs"]["file_count"], 1, "local export sensor log count")
        assert_equal(payload["virtual_environment"]["python_version"], "3.14.3", "local export venv version")
        assert_equal(
            payload["hardware_result_validation_state"]["status_counts"]["confirmed"],
            1,
            "local export confirmed hardware count",
        )
        assert_equal(set(payload["output"]), {"folder", "json", "text"}, "local export output shape")
        assert_true("not a secret" in result.summary_text.lower(), "local export text explains safety boundary")
        assert_true(bool(payload["restore_recommendations"]), "public support export includes restore recommendations")


def test_private_migration_bundle_manifest_checksums_and_exclusions() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        (root / "settings" / "secrets").mkdir(parents=True)
        JsonStore.write(
            root / "settings" / "global_settings.json",
            {
                "environment_mode": "production",
                "suite_department": "Private Lab",
                "runtime_environment": {"PRIVATE_TOKEN": "runtime-secret-marker"},
                "google_drive_credentials_path": "settings/secrets/google-credentials.json",
                "google_drive_shared_drive_id": "private-drive-id-marker",
            },
        )
        JsonStore.write(root / "settings" / "run_setup_history.json", [{"description": "private history"}])
        JsonStore.write(
            root / "hardware_result_validation_state.json",
            {"entries": [{"category": "clean", "status": "missing"}]},
        )
        (root / "settings" / "secrets" / "google-credentials.json").write_text(
            "google-credential-secret-marker",
            encoding="utf-8",
        )
        (root / "results" / "Actual Result").mkdir(parents=True)
        (root / "results" / "Actual Result" / "secret-result.txt").write_text(
            "actual-result-content-marker",
            encoding="utf-8",
        )
        (root / "sensor_probe_logs").mkdir()
        (root / "sensor_probe_logs" / "probe.log").write_text("sensor-log-content-marker", encoding="utf-8")
        (root / "Files" / "OCCT Test Data").mkdir(parents=True)
        (root / "Files" / "OCCT Test Data" / "vendor.txt").write_text("vendor-data-marker", encoding="utf-8")
        (root / ".venv").mkdir()
        (root / ".venv" / "private.txt").write_text("venv-content-marker", encoding="utf-8")

        manager = LocalMigrationManager(root)
        try:
            manager.create_private_bundle(acknowledge_private_data=False)
        except ValueError:
            pass
        else:
            raise AssertionError("private migration bundle should require explicit acknowledgement")

        result = manager.create_private_bundle(acknowledge_private_data=True)
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert_contract_identity(
            manifest,
            contract_id=MIGRATION_CONTRACT_ID,
            contract_version=MIGRATION_CONTRACT_VERSION,
            kind="private_local_migration_bundle",
            label="private migration manifest",
        )
        assert_snake_case_keys(manifest, label="private migration manifest")
        assert_equal(manifest["contract_id"], MIGRATION_CONTRACT_ID, "private bundle contract id")
        assert_equal(manifest["contract_version"], MIGRATION_CONTRACT_VERSION, "private bundle contract version")
        assert_equal(manifest["safe_to_share_publicly"], False, "private bundle marked not public-safe")
        assert_equal(stat.S_IMODE(result.bundle_dir.stat().st_mode), 0o700, "private bundle directory permissions")
        assert_equal(stat.S_IMODE(result.manifest_path.stat().st_mode), 0o600, "private bundle manifest permissions")
        assert_equal(
            {item["bundle_path"] for item in manifest["files"]},
            {SETTINGS_BUNDLE_PATH, HISTORY_BUNDLE_PATH, HARDWARE_STATE_BUNDLE_PATH},
            "private bundle allowed payload inventory",
        )
        for item in manifest["files"]:
            payload_path = result.bundle_dir / item["bundle_path"]
            assert_equal(hashlib.sha256(payload_path.read_bytes()).hexdigest(), item["sha256"], "bundle checksum")
            assert_equal(payload_path.stat().st_size, item["size_bytes"], "bundle size")
            assert_equal(stat.S_IMODE(payload_path.stat().st_mode), 0o600, "private bundle payload permissions")

        portable_settings = json.loads((result.bundle_dir / SETTINGS_BUNDLE_PATH).read_text(encoding="utf-8"))
        assert_equal(portable_settings["google_drive_credentials_path"], "", "bundle removes Google credential path")
        assert_equal(portable_settings["google_drive_shared_drive_id"], "", "bundle removes Google drive ID")
        assert_equal(portable_settings["runtime_environment"], {}, "bundle removes runtime environment overrides")
        bundle_text = "\n".join(
            path.read_text(encoding="utf-8") for path in result.bundle_dir.rglob("*") if path.is_file()
        )
        for marker in (
            "runtime-secret-marker",
            "private-drive-id-marker",
            "google-credential-secret-marker",
            "actual-result-content-marker",
            "sensor-log-content-marker",
            "vendor-data-marker",
            "venv-content-marker",
        ):
            assert_true(marker not in bundle_text, f"private bundle excludes {marker}")


def test_migration_cli_menu_contract() -> None:
    class Host:
        def _input(self, prompt):
            return "5"

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        DiagnosticsCliAdapter(Host()).migration_support_menu()
    text = output.getvalue()
    assert_true("1. Public-safe Support Summary" in text, "migration CLI public support option")
    assert_true("2. Create Private Migration Bundle" in text, "migration CLI private bundle option")
    assert_true("3. Preview Migration Restore" in text, "migration CLI restore preview option")
    assert_true("4. Apply Reviewed Migration Restore" in text, "migration CLI restore apply option")
    assert_true("5. Back" in text, "migration CLI back option")


def test_migration_restore_preview_apply_and_scaffolds() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        base = Path(tmp)
        source_root = base / "source"
        target_root = base / "target"
        source_root.mkdir()
        target_root.mkdir()
        bundle = LocalMigrationManager(source_root).create_private_bundle(acknowledge_private_data=True)
        (target_root / "settings").mkdir()
        example_text = '{"environment_mode": "end_user", "google_drive_credentials_path": ""}\n'
        (target_root / "settings" / "global_settings.example.json").write_text(example_text, encoding="utf-8")

        manager = LocalMigrationManager(target_root)
        before = sorted(path.relative_to(target_root).as_posix() for path in target_root.rglob("*"))
        preview = manager.preview_restore(bundle.bundle_dir)
        after_preview = sorted(path.relative_to(target_root).as_posix() for path in target_root.rglob("*"))
        assert_true(preview.valid, "migration restore preview valid")
        assert_true(not preview.applied, "migration restore preview performs no writes")
        assert_equal(after_preview, before, "migration restore preview leaves target unchanged")
        assert_true(
            any(action["action"] == "create_from_example" for action in preview.plan["actions"]),
            "migration restore plans settings bootstrap from example",
        )

        unconfirmed = manager.apply_restore(bundle.bundle_dir, yes=False)
        assert_true(not unconfirmed.applied, "migration restore without confirmation performs no writes")
        assert_equal(
            sorted(path.relative_to(target_root).as_posix() for path in target_root.rglob("*")),
            before,
            "unconfirmed migration restore leaves target unchanged",
        )
        cli_stderr = io.StringIO()
        with contextlib.redirect_stderr(cli_stderr):
            cli_code = local_migration_main(
                ["--root", str(target_root), "restore", str(bundle.bundle_dir), "--apply"]
            )
        assert_equal(cli_code, 2, "noninteractive migration apply requires --yes")
        assert_true("requires both --apply and --yes" in cli_stderr.getvalue(), "migration CLI confirmation message")
        assert_equal(
            sorted(path.relative_to(target_root).as_posix() for path in target_root.rglob("*")),
            before,
            "CLI migration apply without --yes leaves target unchanged",
        )

        applied = manager.apply_restore(bundle.bundle_dir, yes=True)
        assert_true(applied.valid and applied.applied, "confirmed migration restore applies")
        assert_equal((target_root / "settings" / "global_settings.json").read_text(encoding="utf-8"), example_text, "settings recreated from example")
        for relative in (
            "settings/secrets",
            "results",
            "results/Archived",
            "results/Uploaded",
            "sensor_probe_logs",
        ):
            assert_true((target_root / relative).is_dir(), f"migration restore creates scaffold {relative}")
        assert_true(
            not (target_root / "settings" / "secrets" / "google-credentials.json").exists(),
            "migration restore does not create Google credentials",
        )


def test_migration_restore_no_overwrite_and_conflict_staging() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        base = Path(tmp)
        source_root = base / "source"
        target_root = base / "target"
        (source_root / "settings").mkdir(parents=True)
        JsonStore.write(source_root / "settings" / "global_settings.json", {"suite_department": "Incoming"})
        JsonStore.write(source_root / "settings" / "run_setup_history.json", [{"description": "incoming"}])
        bundle = LocalMigrationManager(source_root).create_private_bundle(acknowledge_private_data=True)

        (target_root / "settings").mkdir(parents=True)
        existing_settings = '{"suite_department": "Existing"}\n'
        existing_history = '[{"description": "existing"}]\n'
        (target_root / "settings" / "global_settings.json").write_text(existing_settings, encoding="utf-8")
        (target_root / "settings" / "run_setup_history.json").write_text(existing_history, encoding="utf-8")
        manager = LocalMigrationManager(target_root)
        preview = manager.preview_restore(bundle.bundle_dir)
        staged_targets = {
            action["target"]
            for action in preview.plan["actions"]
            if action["action"] == "stage_for_manual_merge"
        }
        assert_true("settings/global_settings.json" in staged_targets, "existing settings planned for staging")
        assert_true("settings/run_setup_history.json" in staged_targets, "existing history planned for staging")

        applied = manager.apply_restore(bundle.bundle_dir, yes=True)
        assert_true(applied.applied, "conflict migration restore applies non-conflicting actions")
        assert_equal((target_root / "settings" / "global_settings.json").read_text(), existing_settings, "existing settings not overwritten")
        assert_equal((target_root / "settings" / "run_setup_history.json").read_text(), existing_history, "existing history not overwritten")
        assert_true(applied.staging_dir is not None, "migration conflicts create staging directory")
        assert_true((applied.staging_dir / "settings" / "global_settings.json").is_file(), "incoming settings staged")
        assert_true((applied.staging_dir / "settings" / "run_setup_history.json").is_file(), "incoming history staged")


def test_migration_restore_rejects_invalid_bundles() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        base = Path(tmp)
        source_root = base / "source"
        target_root = base / "target"
        (source_root / "settings").mkdir(parents=True)
        JsonStore.write(source_root / "settings" / "global_settings.json", {"environment_mode": "end_user"})
        original = LocalMigrationManager(source_root).create_private_bundle(acknowledge_private_data=True).bundle_dir
        target_root.mkdir()
        manager = LocalMigrationManager(target_root)

        checksum_bundle = base / "checksum_bundle"
        shutil.copytree(original, checksum_bundle)
        (checksum_bundle / SETTINGS_BUNDLE_PATH).write_text("{}\n", encoding="utf-8")
        checksum_preview = manager.preview_restore(checksum_bundle)
        assert_true(not checksum_preview.valid, "migration restore rejects checksum mismatch")
        assert_true(any("checksum mismatch" in error or "size mismatch" in error for error in checksum_preview.plan["errors"]), "checksum rejection reason")

        traversal_bundle = base / "traversal_bundle"
        shutil.copytree(original, traversal_bundle)
        traversal_manifest_path = traversal_bundle / MANIFEST_NAME
        traversal_manifest = json.loads(traversal_manifest_path.read_text(encoding="utf-8"))
        traversal_manifest["files"][0]["bundle_path"] = "../escape.json"
        traversal_manifest_path.write_text(json.dumps(traversal_manifest), encoding="utf-8")
        traversal_preview = manager.preview_restore(traversal_bundle)
        assert_true(not traversal_preview.valid, "migration restore rejects traversal payload path")
        assert_true(any("not allowed" in error for error in traversal_preview.plan["errors"]), "traversal rejection reason")

        symlink_bundle = base / "symlink_bundle"
        shutil.copytree(original, symlink_bundle)
        (symlink_bundle / "payload" / "unsafe-link").symlink_to(base / "outside")
        symlink_preview = manager.preview_restore(symlink_bundle)
        assert_true(not symlink_preview.valid, "migration restore rejects bundle symlink")
        assert_true(any("symlink" in error for error in symlink_preview.plan["errors"]), "symlink rejection reason")
        assert_equal(list(target_root.iterdir()), [], "invalid migration previews perform no writes")


def test_result_artifact_facade_inventory() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        run_dir = root / "2026-05-01_23-00-00_Run"
        preflight_dir = root / "2026-05-01_23-05-00_Preflight"
        diagnostics_dir = root / "2026-05-01_23-10-00_Diagnostics"
        dependency_dir = root / "2026-05-01_23-12-00_Dependency"
        audit_dir = root / "2026-05-01_23-14-00_Audit"
        inventory_dir = root / "2026-05-01_23-16-00_Inventory"
        validation_dir = root / "2026-05-01_23-20-00_Validation"
        sanity_dir = root / "2026-05-01_23-30-00_Sanity"
        archived_dir = root / "Archived" / "old"
        uploaded_dir = root / "Uploaded" / "sent"
        for path in (
            run_dir,
            preflight_dir,
            diagnostics_dir,
            dependency_dir,
            audit_dir,
            inventory_dir,
            validation_dir,
            sanity_dir,
            archived_dir,
            uploaded_dir,
        ):
            path.mkdir(parents=True)
        JsonStore.write(
            run_dir / "parsed_results_custom.json",
            {
                "Metadata": {"ProfileName": "Run Fixture"},
                "Segments": [{"Label": "Power"}],
                "ReportSummary": {
                    "Result": "warning",
                    "OutcomeClass": "completed_with_warnings",
                    "OutcomeSummary": "Completed with warnings",
                    "DepartmentUseSummary": {
                        "Status": "review",
                        "Blocking": False,
                        "Decision": "Review GPU warning",
                    },
                    "StageOutcomes": [
                        {
                            "Label": "Power",
                            "Verdict": "warning",
                            "OutcomeClass": "completed_with_warnings",
                            "TargetedGpuCount": 1,
                            "GpuHighlights": [{"GpuIndex": 0, "Name": "GPU Fixture"}],
                        }
                    ],
                    "ActionItemDetails": [
                        {"Severity": "warning", "Category": "gpu", "Message": "Review GPU warning"}
                    ],
                    "ActionItemSeverityCounts": {"warning": 1},
                    "ActionItemCategoryCounts": {"gpu": 1},
                    "WarningCategoryCounts": {"gpu": 1},
                    "ErrorCategoryCounts": {},
                    "GpuWorkerSummary": {"expected": 1, "completed": 1},
                },
            },
        )
        JsonStore.write(
            run_dir / "result_validation.json",
            {"summary": {"errors": 0, "warnings": 1, "issue_category_counts": {"support_files": 1}}},
        )
        (run_dir / "result_comparison_vs_baseline.txt").write_text("comparison", encoding="utf-8")
        JsonStore.write(
            preflight_dir / "preflight_report.json",
            {
                "result": "Blocked",
                "preflight": {
                    "profile_name": "Preflight Fixture",
                    "runnable": False,
                    "runnable_stage_count": 1,
                    "enabled_stage_count": 2,
                    "plan": [
                        {"label": "Runnable Stage", "enabled": True, "runnable": True},
                        {"label": "Blocked Stage", "enabled": True, "runnable": False},
                    ],
                    "validation": {"errors": ["blocked"], "warnings": ["warning"]},
                },
            },
        )
        JsonStore.write(
            diagnostics_dir / "diagnostics.json",
            {
                "profile_name": "Diagnostics Fixture",
                "runnable": True,
                "runnable_stage_count": 1,
                "enabled_stage_count": 1,
                "plan": [{"label": "Stage"}],
                "validation": {"errors": [], "warnings": ["warning"]},
            },
        )
        JsonStore.write(
            dependency_dir / "dependency_check.json",
            {
                "result": "warning",
                "checks": {
                    "vulkan": {"available": True},
                    "opencl": {"available": False, "reason": "not found"},
                },
            },
        )
        JsonStore.write(
            audit_dir / "profile_audit.json",
            {
                "counts": {
                    "profiles": 2,
                    "runnable": 1,
                    "blocked": 1,
                    "validation_errors": 1,
                    "validation_warnings": 2,
                },
                "profiles": [
                    {"profile_name": "Runnable", "loaded": True, "runnable": True},
                    {"profile_name": "Blocked", "loaded": True, "runnable": False},
                ],
            },
        )
        JsonStore.write(
            inventory_dir / "results_inventory.json",
            {
                "counts": {
                    "total": 2,
                    "by_kind": {"run_result": 1, "diagnostics": 1},
                    "by_result": {"pass": 1, "Runnable": 1},
                },
                "items": [
                    {"folder_name": "Run", "kind": "run_result", "profile_name": "Run Fixture", "result": "pass"},
                    {"folder_name": "Diagnostics", "kind": "diagnostics", "result": "Runnable"},
                ],
            },
        )
        JsonStore.write(
            validation_dir / "result_validation_batch.json",
            {
                "result": "warning",
                "counts": {
                    "total": 2,
                    "errors": 0,
                    "warnings": 1,
                    "by_result": {"pass": 1, "warning": 1},
                    "issue_category_counts": {"support_files": 1},
                    "issue_severity_category_counts": {"warning": {"support_files": 1}},
                },
                "items": [{"folder_name": "Run", "result": "warning", "summary": {"warnings": 1}}],
            },
        )
        JsonStore.write(
            sanity_dir / "pre_import_sanity_batch.json",
            {
                "result": "fail",
                "counts": {
                    "total": 2,
                    "errors": 1,
                    "warnings": 0,
                    "by_result": {"fail": 1, "pass": 1},
                    "issue_category_counts": {"export": 1},
                },
                "summary_refresh": {"refreshed": 1, "failed": 1},
                "items": [
                    {
                        "folder_name": "Run",
                        "result": "fail",
                        "summary": {"errors": 1},
                        "summary_refresh": {"refreshed": False},
                    }
                ],
            },
        )
        JsonStore.write(archived_dir / "diagnostics.json", {"runnable": True})
        JsonStore.write(uploaded_dir / "dependency_check.json", {"result": "Saved"})

        facade = ResultArtifactFacade(root)
        candidate_names = {path.name for path in facade.candidates()}
        assert_equal(
            candidate_names,
            {
                run_dir.name,
                preflight_dir.name,
                diagnostics_dir.name,
                dependency_dir.name,
                audit_dir.name,
                inventory_dir.name,
                validation_dir.name,
                sanity_dir.name,
            },
            "result artifact active candidates",
        )
        run_item = facade.inventory_item(run_dir)
        assert_equal(run_item["kind"], "run_result", "result artifact run kind")
        assert_equal(run_item["profile_name"], "Run Fixture", "result artifact run profile")
        assert_equal(run_item["gpu_highlights"], 1, "result artifact GPU highlights")
        assert_equal(run_item["validation_warnings"], 1, "result artifact validation warnings")
        assert_true("result_comparison_vs_baseline.txt" in run_item["artifacts"], "result artifact comparison file")
        run_details = facade.run_result_detail_payload(run_dir)
        assert_equal(run_details["details"]["department_status"], "review", "result artifact run department status")
        assert_equal(run_details["details"]["action_item_count"], 1, "result artifact run action item count")
        assert_equal(run_details["details"]["gpu_highlight_count"], 1, "result artifact run detail GPU highlights")
        assert_equal(run_details["details"]["warning_categories"], {"gpu": 1}, "result artifact run warning categories")
        assert_equal(run_details["stage_outcomes"][0]["Label"], "Power", "result artifact run stage outcomes")
        assert_equal(run_details["action_items"][0]["Category"], "gpu", "result artifact run action items")
        preflight_details = facade.preflight_detail_payload(preflight_dir)
        assert_equal(preflight_details["details"]["result"], "Blocked", "result artifact preflight result")
        assert_equal(preflight_details["details"]["validation_errors"], 1, "result artifact preflight errors")
        assert_equal(preflight_details["details"]["stage_count"], 2, "result artifact preflight stages")
        assert_equal(preflight_details["full_detail_name"], "preflight_report.json", "result artifact preflight filename")
        diagnostics_item = facade.inventory_item(diagnostics_dir)
        assert_equal(diagnostics_item["kind"], "diagnostics", "result artifact diagnostics kind")
        assert_true(diagnostics_item["runnable"], "result artifact diagnostics runnable")
        diagnostics_details = facade.diagnostics_detail_payload(diagnostics_dir)
        assert_true(diagnostics_details["details"]["runnable"], "result artifact diagnostics detail runnable")
        assert_equal(diagnostics_details["details"]["validation_warnings"], 1, "result artifact diagnostics warnings")
        assert_equal(diagnostics_details["plan"][0]["label"], "Stage", "result artifact diagnostics plan")
        assert_equal(diagnostics_details["full_detail_name"], "diagnostics.json", "result artifact diagnostics filename")
        dependency_details = facade.dependency_detail_payload(dependency_dir)
        assert_equal(dependency_details["details"]["result"], "warning", "result artifact dependency result")
        assert_equal(dependency_details["details"]["check_count"], 2, "result artifact dependency checks")
        assert_true(dependency_details["checks"]["vulkan"]["available"], "result artifact dependency check data")
        audit_details = facade.profile_audit_detail_payload(audit_dir)
        assert_equal(audit_details["details"]["profile_count"], 2, "result artifact audit profile count")
        assert_equal(audit_details["details"]["blocked_profile_count"], 1, "result artifact audit blocked count")
        assert_equal(audit_details["profiles"][0]["profile_name"], "Runnable", "result artifact audit profiles")
        inventory_details = facade.results_inventory_detail_payload(inventory_dir)
        assert_equal(inventory_details["details"]["artifact_count"], 2, "result artifact detail inventory count")
        assert_equal(inventory_details["details"]["by_kind"]["run_result"], 1, "result artifact detail inventory kinds")
        assert_equal(inventory_details["items"][0]["folder_name"], "Run", "result artifact detail inventory items")
        validation_item = facade.inventory_item(validation_dir)
        assert_equal(validation_item["kind"], "result_validation_batch", "result artifact validation batch kind")
        assert_equal(validation_item["batch_result_counts"], {"pass": 1, "warning": 1}, "result artifact batch counts")
        validation_details = facade.result_validation_batch_detail_payload(validation_dir)
        assert_equal(validation_details["details"]["result_count"], 2, "result artifact validation detail count")
        assert_equal(
            validation_details["details"]["issue_category_counts"],
            {"support_files": 1},
            "result artifact validation detail categories",
        )
        assert_equal(validation_details["items"][0]["result"], "warning", "result artifact validation detail items")
        sanity_item = facade.inventory_item(sanity_dir)
        assert_equal(sanity_item["summary_refresh_failed"], 1, "result artifact sanity refresh failures")
        sanity_details = facade.pre_import_sanity_batch_detail_payload(sanity_dir)
        assert_equal(sanity_details["details"]["result_count"], 2, "result artifact sanity detail count")
        assert_equal(sanity_details["details"]["summary_refresh_failed"], 1, "result artifact sanity detail refresh failures")
        assert_equal(sanity_details["items"][0]["result"], "fail", "result artifact sanity detail items")
        dispatched_details = facade.detail_payload(audit_dir)
        assert_equal(dispatched_details["kind"], "profile_audit", "result artifact detail dispatcher kind")
        assert_equal(dispatched_details["details"], audit_details["details"], "result artifact detail dispatcher details")
        prepared_report = facade.prepare_detail_report(audit_dir)
        assert_equal(
            prepared_report["report"]["kind"],
            "result_artifact_details",
            "result artifact prepared report kind",
        )
        assert_equal(
            prepared_report["report"]["inventory_item"]["kind"],
            "profile_audit",
            "result artifact prepared inventory kind",
        )
        assert_equal(
            prepared_report["report"]["details"],
            audit_details["details"],
            "result artifact prepared report details",
        )
        assert_equal(
            prepared_report["detail_payload"]["kind"],
            "profile_audit",
            "result artifact prepared detail payload kind",
        )
        assert_true("ended" not in prepared_report["report"], "result artifact prepared report incomplete")
        completed_report = facade.complete_detail_report(prepared_report)
        assert_true(bool(completed_report.get("ended")), "result artifact completed report timestamp")
        assert_equal(completed_report["details"], audit_details["details"], "result artifact completed report details")
        direct_report = facade.detail_report_payload(audit_dir)
        assert_equal(direct_report["inventory_item"]["kind"], "profile_audit", "result artifact direct report inventory")
        assert_equal(direct_report["details"], audit_details["details"], "result artifact direct report details")
        artifact_text_headings = {
            run_dir: "Run Summary",
            preflight_dir: "Plan Summary",
            diagnostics_dir: "Plan Summary",
            dependency_dir: "Dependency Summary",
            audit_dir: "Profile Audit Summary",
            inventory_dir: "Results Inventory Summary",
            validation_dir: "Batch Validation Summary",
            sanity_dir: "Batch Pre-Import Sanity Summary",
        }
        for artifact_dir, heading in artifact_text_headings.items():
            text = artifact_detail_text(
                facade.prepare_detail_report(artifact_dir),
                dependency_summary_builder=lambda payload, report_dir: "Generated dependency summary\n",
            )
            assert_true("Result Artifact Details" in text, f"result artifact canonical header {heading}")
            assert_true(heading in text, f"result artifact canonical detail heading {heading}")
            assert_true(f"Folder: {artifact_dir}" in text, f"result artifact canonical folder {heading}")
        payload = facade.inventory_payload()
        assert_equal(payload["kind"], "results_inventory", "result artifact inventory kind")
        assert_equal(payload["counts"]["total"], 8, "result artifact inventory total")
        assert_equal(payload["counts"]["by_kind"]["run_result"], 1, "result artifact inventory run count")
        assert_equal(payload["excluded_root_dirs"], ["Archived", "Uploaded"], "result artifact exclusions")
        inventory_report_dir = facade.write_inventory_report("inventory text\n", payload, "2026-05-01_23-40-00")
        assert_true(
            (inventory_report_dir / "results_inventory.json").exists(),
            "result artifact inventory report JSON saved",
        )
        assert_equal(
            (inventory_report_dir / "results_inventory.txt").read_text(encoding="utf-8"),
            "inventory text\n",
            "result artifact inventory report text saved",
        )
        saved_inventory = JsonStore.read(inventory_report_dir / "results_inventory.json", {})
        assert_equal(saved_inventory["kind"], "results_inventory", "result artifact inventory report payload saved")
        saved_detail_dir = facade.write_detail_report(audit_dir, "artifact detail text\n", completed_report)
        assert_equal(saved_detail_dir, audit_dir, "result artifact detail report save target")
        assert_equal(
            JsonStore.read(audit_dir / "artifact_details.json", {}).get("kind"),
            "result_artifact_details",
            "result artifact detail report JSON saved",
        )
        assert_equal(
            (audit_dir / "artifact_details.txt").read_text(encoding="utf-8"),
            "artifact detail text\n",
            "result artifact detail report text saved",
        )


def test_result_artifact_presentation_helpers() -> None:
    item = {
        "folder_name": "2026-06-22_Run",
        "kind": "run_result",
        "profile_name": "GPU Troubleshooting",
        "result": "warning",
        "outcome_class": "completed_with_warnings",
        "department_status": "Review",
        "department_blocking": False,
        "stage_count": 3,
        "validation_errors": 1,
        "validation_warnings": 2,
        "validation_issue_category_counts": {"schema": 1, "telemetry": 2},
        "action_items": 2,
        "gpu_highlights": 4,
        "artifacts": ["parsed_results_custom.json", "run_summary.txt"],
        "notes": ["sample note"],
    }
    payload = {
        "results_dir": "results",
        "counts": {
            "total": 1,
            "by_kind": {"run_result": 1},
            "by_result": {"warning": 1},
        },
        "items": [item],
    }
    expected_inventory = (
        "\nResults Inventory\n"
        "=================\n"
        "Results folder: results\n"
        "Excluded root folders: Archived, Uploaded\n"
        "Total artifact folders: 1\n"
        "By kind: {'run_result': 1}\n"
        "By result: {'warning': 1}\n"
        "\nRecent artifacts\n"
        "----------------\n"
        "- 2026-06-22_Run | run_result | GPU Troubleshooting | warning | "
        "outcome=completed_with_warnings, department=Review,blocking=False, stages=3, "
        "validation=1e/2w, validation_categories=schema=1,telemetry=2, actions=2, gpu_highlights=4\n"
        "  artifacts: parsed_results_custom.json, run_summary.txt\n"
        "  [note] sample note\n\n"
    )
    assert_equal(result_artifact_inventory_text(payload), expected_inventory, "artifact inventory exact text")
    assert_equal(
        result_artifact_choice_label(Path("results/2026-06-22_Run"), item),
        "2026-06-22_Run | run_result | GPU Troubleshooting | warning | "
        "outcome=completed_with_warnings, stages=3, validation=1e/2w, "
        "validation_categories=schema=1,telemetry=2, actions=2, gpu_highlights=4",
        "artifact choice exact label",
    )

    assert_equal(
        result_artifact_item_extras(
            {
                "kind": "profile_audit",
                "stage_count": 8,
                "runnable_profile_count": 6,
                "blocked_profile_count": 2,
            },
            inventory=True,
        ),
        ["profiles=8, runnable=6, blocked=2"],
        "artifact profile-audit metadata",
    )
    assert_equal(
        result_artifact_item_extras(
            {
                "kind": "result_validation_batch",
                "stage_count": 4,
                "batch_result_counts": {"error": 1, "pass": 3},
            },
            inventory=True,
        ),
        ["results=4", "batch=error=1,pass=3"],
        "artifact validation-batch metadata",
    )
    sanity_batch = {
        "kind": "pre_import_sanity_batch",
        "stage_count": 5,
        "summary_refreshed": 4,
        "summary_refresh_failed": 1,
        "batch_result_counts": {"pass": 5},
    }
    assert_equal(
        result_artifact_item_extras(sanity_batch, inventory=True),
        ["results=5", "summaries=4 refreshed/1 failed", "batch=pass=5"],
        "artifact sanity inventory metadata",
    )
    assert_equal(
        result_artifact_item_extras(sanity_batch, inventory=False),
        ["results=5", "summaries=4/1", "batch=pass=5"],
        "artifact sanity choice metadata",
    )
    assert_equal(
        result_artifact_item_extras({"kind": "results_inventory", "stage_count": 12}, inventory=False),
        ["artifacts=12"],
        "artifact inventory-choice metadata",
    )

    paths = [Path("results/A"), Path("results/B")]
    items = {
        "A": {"kind": "run_result", "profile_name": "A Profile", "result": "pass"},
        "B": {"kind": "diagnostics", "result": "unknown"},
    }
    choices = result_artifact_choice_text(
        paths,
        item_for_path=lambda path: items[path.name],
        heading="Available artifacts",
        limit=1,
    )
    assert_equal(
        choices,
        "\nAvailable artifacts:\n1. A | run_result | A Profile | pass\n   results/A\n"
        "... 1 more result folder(s) not shown.\n",
        "artifact choice bounded text",
    )
    empty_text = result_artifact_inventory_text({"results_dir": "results", "counts": {}, "items": []})
    assert_true(empty_text.endswith("No active result artifacts were found.\n"), "artifact empty inventory text")


def test_profile_dry_run_summary_formatting() -> None:
    assert_equal(
        dry_run_plan_line({"label": "Stage 1", "runnable": True, "backend_usage": {"cpu": "cpu_native_helper"}}),
        "- Stage 1: runnable | cpu=cpu_native_helper",
        "dry-run plan line",
    )
    original_stage_diagnostics = dry_run_module.build_stage_diagnostics
    diagnostics_calls: List[tuple[str, str]] = []
    try:
        def fake_stage_diagnostics(_runner: object, stage: object, label: str) -> dict:
            diagnostics_calls.append((getattr(stage, "name", ""), label))
            return {"stage": getattr(stage, "name", ""), "label": label, "enabled": True, "workloads": []}

        dry_run_module.build_stage_diagnostics = fake_stage_diagnostics
        profile = SimpleNamespace(
            stages=[
                SimpleNamespace(name="Stage A"),
                SimpleNamespace(name="Stage B"),
            ]
        )
        plan = dry_run_module.build_dry_run_plan(object(), profile, ["Custom A"])
    finally:
        dry_run_module.build_stage_diagnostics = original_stage_diagnostics
    assert_equal(
        plan,
        [
            {"stage": "Stage A", "label": "Custom A", "enabled": True, "workloads": []},
            {"stage": "Stage B", "label": "Stage B", "enabled": True, "workloads": []},
        ],
        "dry-run facade plan label fallback",
    )
    assert_equal(diagnostics_calls, [("Stage A", "Custom A"), ("Stage B", "Stage B")], "dry-run facade diagnostics order")
    audit_item = {"profile_file": "Smoke.json", "loaded": True, "runnable": False, "stage_count": 2}
    assert_equal(profile_audit_item_status(audit_item), "blocked", "profile audit item status")
    assert_equal(profile_audit_item_line(audit_item), "- Smoke.json: blocked, stages=2", "profile audit item line")
    execution_stage = {
        "label": "GPU Stress",
        "type": "3D Adaptive",
        "duration_seconds": 90,
        "enabled": True,
        "runnable": True,
        "workloads": ["gpu_3d", "vram"],
    }
    assert_equal(profile_execution_stage_status(execution_stage), "runnable", "profile execution stage status")
    assert_equal(
        profile_execution_stage_header_line(execution_stage),
        "- GPU Stress: 3D Adaptive | 90s | runnable | workloads=gpu_3d, vram",
        "profile execution stage header line",
    )
    detail_stage = {
        "trim_start_seconds": 30,
        "trim_end_seconds": 10,
        "backend_usage": {
            "cpu": "cpu_native_helper",
            "memory": "memory_native_helper",
            "gpu_3d": "python_vulkan_compute",
            "vram": "python_vulkan_memory",
        },
        "cpu_mode_requested": "avx2",
        "cpu_mode_resolved": "avx2",
        "cpu_kernel_flavor": "avx2_fma",
        "gpu_backend_preferences": {"gpu_3d": "auto", "vram": "auto"},
        "gpu_3d_mode": "steady",
        "gpu_3d_intensity": "extreme",
        "gpu_3d_compute_variant": "hash",
        "gpu_target_mode": "all",
        "gpu_targets": ["0000:01:00.0", "0000:02:00.0"],
        "gpu_effective_targets": ["0000:01:00.0"],
        "gpu_excluded_targets": {"unsupported": ["0000:02:00.0"]},
        "gpu_backend_fallback_order": {
            "gpu_3d": ["python_vulkan_compute", "python_opencl_compute"],
            "vram": ["python_vulkan_memory"],
        },
        "gpu_workers": [
            {
                "workload": "gpu_3d",
                "backend": "python_vulkan_compute",
                "target_id": "0000:01:00.0",
            },
            {
                "workload": "vram",
                "backend": "python_vulkan_memory",
                "target_id": "0000:01:00.0",
                "target_vram_bytes": 2 * 1024 ** 3,
            },
            {"workload": "vram", "target_vram_bytes": 3 * 1024 ** 3},
        ],
    }
    assert_equal(
        profile_execution_trim_line(detail_stage),
        "  trim: start=30s, end=10s",
        "profile execution trim line",
    )
    assert_equal(
        profile_execution_cpu_line(detail_stage),
        "  cpu: backend=cpu_native_helper, mode=avx2->avx2, kernel=avx2_fma",
        "profile execution CPU line",
    )
    assert_equal(
        profile_execution_memory_line(detail_stage),
        "  memory: backend=memory_native_helper",
        "profile execution memory line",
    )
    assert_equal(
        profile_execution_gpu_3d_line(detail_stage),
        "  3d: preference=auto, resolved=python_vulkan_compute, mode=steady, intensity=extreme, variant=hash",
        "profile execution 3D line",
    )
    assert_equal(
        profile_execution_vram_line(detail_stage),
        "  vram: preference=auto, resolved=python_vulkan_memory, target_allocations=2.0GB, 3.0GB",
        "profile execution VRAM line",
    )
    assert_equal(
        profile_execution_gpu_detail_lines(detail_stage),
        [
            "  gpu targets: mode=all, requested=2, effective=1",
            "  effective target ids: 0000:01:00.0",
            "  excluded targets: unsupported:0000:02:00.0",
            "  backend fallback: 3d=python_vulkan_compute > python_opencl_compute; vram=python_vulkan_memory",
            "  gpu workers (3): gpu_3d:python_vulkan_compute@0000:01:00.0, vram:python_vulkan_memory@0000:01:00.0, vram:-@-",
        ],
        "profile execution GPU detail lines",
    )
    reports = ProfileReportManager(profile_loader=SimpleNamespace(), validator=SimpleNamespace(), result_reports=SimpleNamespace())
    report = {
        "profile_name": "Smoke",
        "runnable": True,
        "runnable_stage_count": 1,
        "enabled_stage_count": 1,
        "validation": {"errors": [], "warnings": ["warn one"]},
        "plan": [{"label": "Stage 1", "runnable": True, "backend_usage": {"cpu": "cpu_native_helper"}}],
    }
    text = reports.dry_run_summary_text(Path("profiles/Smoke.json"), report, save=False)
    assert_true("Profile: Smoke" in text, "dry-run summary profile")
    assert_true("Warnings: 1" in text, "dry-run summary warning count")
    assert_true("Stage 1: runnable | cpu=cpu_native_helper" in text, "dry-run summary plan")
    diagnostics = reports.diagnostics_summary_text(report)
    assert_true("Diagnostics Summary" in diagnostics, "diagnostics summary heading")
    assert_true("Full details: diagnostics.json" in diagnostics, "diagnostics summary details target")
    preflight = reports.preflight_summary_text(report)
    assert_true("Preflight Summary" in preflight, "preflight summary heading")
    assert_true("Full details: preflight_report.json" in preflight, "preflight summary details target")

    with TemporaryDirectory() as tmp:
        result_reports = ResultReportManager(Path(tmp), RunSummaryTextExporter())
        reports = ProfileReportManager(
            profile_loader=SimpleNamespace(),
            validator=SimpleNamespace(),
            result_reports=result_reports,
        )
        profile = ValidationProfile(
            profile_name="Smoke Profile",
            profile_type="custom",
            menu_description="smoke",
            menu_group="diagnostic",
            defaults=ProfileDefaults(),
            stages=[StageConfig(id="segment_1", name="CPU", duration_seconds=60)],
        )
        labels = ["CPU"]
        diagnostics_dir = reports.save_cli_diagnostics_report(
            Path("profiles/Smoke Profile.json"),
            profile,
            labels,
            report,
        )
        assert_true(diagnostics_dir.name.endswith("_Diagnostics_Smoke Profile"), "legacy diagnostics folder suffix")
        assert_true((diagnostics_dir / "diagnostics.json").exists(), "legacy diagnostics json")
        assert_true((diagnostics_dir / "diagnostics_summary.txt").exists(), "legacy diagnostics summary")
        assert_true((diagnostics_dir / "profile_used.json").exists(), "legacy diagnostics profile copy")
        preflight_dir = reports.save_cli_preflight_report(
            Path("profiles/Smoke Profile.json"),
            profile,
            labels,
            report,
            runtime_environment={"TEST_ENV": "1"},
            backends={"cpu_native_helper": True},
            backend_details={"cpu_native_helper": {"available": True}},
        )
        assert_true(preflight_dir.name.endswith("_Smoke Profile_Preflight"), "legacy preflight folder suffix")
        assert_true((preflight_dir / "preflight_report.json").exists(), "legacy preflight json")
        assert_true((preflight_dir / "preflight_summary.txt").exists(), "legacy preflight summary")
        preflight_payload = JsonStore.read(preflight_dir / "preflight_report.json", {})
        assert_equal(preflight_payload.get("kind"), "preflight_only", "legacy preflight kind")
        assert_equal(preflight_payload.get("backends", {}).get("cpu_native_helper"), True, "legacy preflight backends")
        audit_payload = {
            "kind": "profile_audit",
            "profiles_dir": "profiles",
            "counts": {
                "profiles": 1,
                "runnable": 0,
                "blocked": 1,
                "validation_errors": 1,
                "validation_warnings": 1,
            },
            "profiles": [
                {
                    "profile_file": "Smoke Profile.json",
                    "profile_name": "Smoke Profile",
                    "loaded": True,
                    "runnable": False,
                    "enabled_stage_count": 1,
                    "runnable_stage_count": 0,
                    "validation_error_count": 1,
                    "validation_warning_count": 1,
                    "errors": ["blocking issue"],
                    "warnings": ["warning issue"],
                    "stages": [
                        {
                            "label": "CPU",
                            "enabled": True,
                            "runnable": False,
                            "issues": ["stage issue"],
                        }
                    ],
                }
            ],
        }
        audit_text = reports.profile_audit_summary_text(audit_payload)
        assert_true("Profile Audit" in audit_text, "profile audit heading")
        assert_true("Smoke Profile (Smoke Profile.json): blocked" in audit_text, "profile audit status")
        assert_true("blocked stage: CPU" in audit_text, "profile audit blocked stage")
        audit_dir = reports.save_profile_audit_report(audit_text, audit_payload)
        assert_true(audit_dir.name.endswith("_Profile_Audit"), "legacy profile audit folder suffix")
        assert_true((audit_dir / "profile_audit.json").exists(), "legacy profile audit json")
        assert_true((audit_dir / "profile_audit.txt").exists(), "legacy profile audit text")

        class FakeProfileLoader:
            profiles_dir = Path("profiles")

            def list_profiles(self):
                return [Path("profiles/Smoke Profile.json")]

            def load_profile(self, profile_path):
                return profile

            def load_segment_labels(self, profile_path, loaded_profile):
                return labels

            def inspect_segment_label_source(self, profile_path, loaded_profile):
                return {"issues": ["label source warning"]}

        reports = ProfileReportManager(
            profile_loader=FakeProfileLoader(),
            validator=SimpleNamespace(),
            result_reports=result_reports,
        )
        payload = reports.profile_audit_payload(
            lambda profile_path, loaded_profile, loaded_labels: {
                "profile_name": loaded_profile.profile_name,
                "runnable": False,
                "enabled_stage_count": 1,
                "runnable_stage_count": 0,
                "validation": {"errors": ["blocking issue"], "warnings": ["warning issue"]},
                "plan": [
                    {
                        "stage_id": "segment_1",
                        "label": loaded_labels[0],
                        "type": "cpu",
                        "enabled": True,
                        "runnable": False,
                        "duration_seconds": 60,
                        "workloads": ["cpu"],
                        "backend_usage": {"cpu": "cpu_native_helper"},
                        "gpu_targets": ["0"],
                        "gpu_effective_targets": [],
                        "issues": ["stage issue"],
                    }
                ],
            }
        )
        assert_equal(payload["counts"]["profiles"], 1, "shared profile audit profile count")
        assert_equal(payload["counts"]["validation_errors"], 1, "shared profile audit error count")
        assert_equal(payload["counts"]["validation_warnings"], 2, "shared profile audit label warning count")
        shared_item = payload["profiles"][0]
        assert_equal(shared_item["profile_name"], "Smoke Profile", "shared profile audit profile name")
        assert_equal(shared_item["stages"][0]["backend_usage"]["cpu"], "cpu_native_helper", "shared audit stage backend")
        assert_true("label source warning" in shared_item["warnings"], "shared audit label warning included")


def test_strict_threshold_policy_helpers() -> None:
    profile = ValidationProfile(
        profile_name="StrictPolicySmoke",
        defaults=ProfileDefaults(strict_threshold_recommendation_warnings=None),
        stages=[
            StageConfig(id="segment_1", name="CPU", duration_seconds=60),
            StageConfig(id="segment_2", name="GPU", duration_seconds=60),
        ],
    )
    assert_true(optional_bool("enabled"), "strict policy optional enabled")
    assert_equal(optional_bool("off"), False, "strict policy optional off")
    assert_true(optional_bool("unknown") is None, "strict policy optional unknown")
    assert_true(
        profile_strict_threshold_recommendation_warnings(profile, True),
        "strict policy profile inherits global true",
    )
    assert_equal(
        profile_strict_threshold_recommendation_warnings(profile, False),
        False,
        "strict policy profile inherits global false",
    )
    profile.defaults.strict_threshold_recommendation_warnings = "yes"
    assert_true(
        profile_strict_threshold_recommendation_warnings(profile, False),
        "strict policy profile override true",
    )
    assert_true(
        stage_strict_threshold_recommendation_warnings(profile, profile.stages[0], False),
        "strict policy stage inherits profile",
    )
    assert_equal(strict_threshold_warning_scope(profile), "profile", "strict policy profile scope")
    profile.stages[1].strict_threshold_recommendation_warnings = "0"
    assert_equal(
        stage_strict_threshold_recommendation_warnings(profile, profile.stages[1], True),
        False,
        "strict policy stage override false",
    )
    assert_equal(strict_threshold_warning_scope(profile), "stage", "strict policy stage scope")
    profile.defaults.strict_threshold_recommendation_warnings = None
    profile.stages[1].strict_threshold_recommendation_warnings = None
    assert_equal(strict_threshold_warning_scope(profile), "global", "strict policy global scope")


def test_profile_validator_shared_policy() -> None:
    assert_true(ProfileValidator is SharedProfileValidator, "profile validator compatibility export")
    validator = SharedProfileValidator()
    empty_profile = ValidationProfile(
        profile_name="",
        defaults=ProfileDefaults(telemetry_interval_seconds=0),
    )
    empty_result = validator.validate(empty_profile, [])
    assert_equal(
        empty_result["errors"],
        [
            "profile_name is required",
            "profile must contain at least one stage",
            "profile has no enabled stages",
            "telemetry_interval_seconds must be > 0, got 0",
        ],
        "profile validator empty errors",
    )
    assert_equal(empty_result["warnings"], [], "profile validator empty warnings")

    editor = ProfileEditor()
    warning_profile = ValidationProfile(
        profile_name="Warning Smoke",
        defaults=ProfileDefaults(telemetry_interval_seconds=11),
    )
    disabled_stage = editor.create_stage(
        warning_profile,
        test_type="Combined",
        duration_seconds=100,
        modules=editor.build_stage_modules(
            "Combined",
            include_cpu=True,
            include_gpu_3d=True,
            gpu_backend_preference="opencl",
            gpu_compute_variant="unknown_variant",
        ),
        stage_id="duplicate",
        enabled=False,
    )
    enabled_stage = editor.create_stage(
        warning_profile,
        test_type="CPU",
        duration_seconds=100,
        modules=editor.build_stage_modules("CPU"),
        stage_id="duplicate",
    )
    warning_profile.stages = [disabled_stage, enabled_stage]
    warning_result = validator.validate(warning_profile, ["only one label"])
    assert_equal(
        warning_result["errors"],
        ["label count mismatch: 1 labels for 2 stages"],
        "profile validator label error",
    )
    assert_equal(
        warning_result["warnings"],
        [
            "stage 1 [duplicate] is disabled but still has configured workloads: cpu, gpu_3d",
            "stage 1 [duplicate] has unknown OpenCL gpu_3d.compute_variant='unknown_variant'; baseline will be used",
            "duplicate stage id detected: duplicate",
            "telemetry_interval_seconds is high (11); short stages may have sparse samples",
        ],
        "profile validator warning ordering",
    )


def test_profile_editor_stage_mutations() -> None:
    editor = ProfileEditor()
    profile = ValidationProfile(
        profile_name="EditorSmoke",
        defaults=ProfileDefaults(trim_start_seconds=10, trim_end_seconds=15),
    )
    stage = editor.create_stage(profile, test_type="CPU", duration_seconds=120)
    profile, labels = editor.add_stage(profile, [], stage, "CPU Stage")
    assert_equal(labels, ["CPU Stage"], "profile editor add label")
    assert_equal(profile.stages[0].id, "segment_1", "profile editor stage id")
    assert_equal(profile.stages[0].normalization.trim_start_seconds, 10, "profile editor trim start")
    assert_true(profile.stages[0].modules.cpu.enabled, "profile editor CPU module")
    assert_equal(editor.set_stage_duration(profile, 0, 240), 240, "profile editor duration")
    assert_equal(editor.toggle_stage_enabled(profile, 0), False, "profile editor toggle")
    labels = editor.set_stage_label(profile, labels, 0, "Renamed")
    assert_equal(labels, ["Renamed"], "profile editor label edit")
    assert_equal(editor.set_profile_menu_group(profile, "GPU Labs"), "gpu_labs", "profile editor menu group")
    assert_equal(editor.set_profile_menu_description(profile, "(Lab profile)"), "(Lab profile)", "profile editor menu description")
    assert_equal(editor.cycle_profile_strict_threshold_warnings(profile), True, "profile editor strict true")
    gpu_stage, gpu_label = editor.template_stage(profile, "gpu_3d", duration_seconds=90)
    profile, labels = editor.add_stage(profile, labels, gpu_stage, gpu_label)
    presenter = ProfileEditPresenter(editor, lambda key: key)
    edit = ProfileEditState(Path("profiles/EditorSmoke.json"), profile, labels)
    picker = presenter.stage_picker_spec(edit, 1, "backend")
    assert_equal(picker.title, "Backend Preference", "profile edit backend picker title")
    assert_true("auto" in picker.options, "profile edit backend picker options")
    assert_equal(picker.current, "auto", "profile edit backend current")
    target_picker = presenter.stage_picker_spec(edit, 1, "gpu_target")
    assert_equal(target_picker.current, "all", "profile edit gpu target current")
    duration_input = presenter.stage_input_spec(edit, 1, "duration")
    assert_equal(duration_input.field, "__profile_stage_duration", "profile edit duration input field")
    assert_equal(duration_input.label, "Stage 2 duration seconds", "profile edit duration input label")
    assert_equal(duration_input.initial_value, "90", "profile edit duration initial value")
    assert_equal(editor.cycle_profile_strict_threshold_warnings(profile), False, "profile editor strict false")
    assert_equal(editor.cycle_profile_strict_threshold_warnings(profile), None, "profile editor strict inherit")

    vram_stage = editor.create_stage(profile, test_type="VRAM", duration_seconds=90)
    profile, labels = editor.add_stage(profile, labels, vram_stage, "VRAM Stage")
    assert_equal(editor.set_profile_menu_group(profile, "custom"), "custom", "profile editor second menu group")
    assert_equal(editor.set_vram_allocation_percent(vram_stage, 120), 95, "profile editor VRAM clamp")
    assert_equal(editor.set_gpu_target_mode(vram_stage, "slots:0000:01:00.0"), "slots:0000:01:00.0", "profile editor target mode")
    assert_equal(editor.set_vram_backend_preference(vram_stage, "vulkan"), "vulkan", "profile editor VRAM backend")
    editor.set_stage_trim(profile, 2, 5, 7)
    assert_equal(vram_stage.normalization.trim_start_seconds, 5, "profile editor stage trim start")
    assert_equal(vram_stage.normalization.trim_end_seconds, 7, "profile editor stage trim end")

    gpu_stage = editor.create_stage(profile, test_type="3D Adaptive", duration_seconds=90)
    profile, labels = editor.add_stage(profile, labels, gpu_stage, "GPU Stage")
    assert_equal(editor.set_gpu_backend_preference(gpu_stage, "vulkan_compute"), "vulkan_compute", "profile editor GPU backend")
    assert_equal(editor.set_gpu_3d_mode(gpu_stage, "variable"), "variable", "profile editor GPU mode")
    assert_equal(editor.set_gpu_intensity(gpu_stage, "max"), "max", "profile editor GPU intensity")
    assert_equal(editor.set_gpu_compute_variant(gpu_stage, "stateful_memory"), "stateful_memory", "profile editor compute variant")
    assert_equal(editor.set_gpu_3d_allocation_percent(gpu_stage, -5), 0, "profile editor GPU allocation clamp low")
    assert_equal(editor.set_gpu_3d_allocation_percent(gpu_stage, 120), 95, "profile editor GPU allocation clamp high")

    cpu_stage = profile.stages[0]
    assert_equal(editor.set_cpu_instruction_set(cpu_stage, "avx2"), "avx2", "profile editor CPU instruction")
    assert_equal(editor.set_cpu_threads(cpu_stage, "6"), "6", "profile editor CPU threads")
    assert_equal(editor.set_memory_instruction_set(cpu_stage, "avx2"), "avx2", "profile editor memory instruction fallback")

    combined_modules = editor.build_stage_modules(
        "Combined",
        include_cpu=True,
        include_memory=True,
        include_gpu_3d=True,
        include_vram=True,
        gpu_target_mode="slots:0000:01:00.0",
        cpu_instruction_set="avx2",
        cpu_mode="extreme",
        cpu_load="variable",
        cpu_priority="high",
        cpu_threads="12",
        memory_allocation_percent=120,
        memory_instruction_set="avx2",
        gpu_backend_preference="vulkan_compute",
        gpu_mode="variable",
        gpu_intensity="max",
        vram_backend_preference="vulkan",
        vram_allocation_percent=110,
        clamp_allocations=False,
    )
    assert_equal(combined_modules.cpu.threads, "12", "profile editor combined CPU threads")
    assert_equal(combined_modules.memory.allocation_percent, 120, "profile editor preserves CLI memory allocation")
    assert_equal(combined_modules.gpu_3d.backend_preference, "vulkan_compute", "profile editor combined GPU backend")
    assert_equal(combined_modules.vram.allocation_percent, 110, "profile editor preserves CLI VRAM allocation")
    normalized_modules = editor.build_stage_modules(
        "Combined",
        include_memory=True,
        include_vram=True,
        memory_allocation_percent=120,
        vram_allocation_percent=110,
    )
    assert_equal(normalized_modules.memory.allocation_percent, 95, "profile editor normalized memory allocation")
    assert_equal(normalized_modules.vram.allocation_percent, 95, "profile editor normalized VRAM allocation")

    power_stage, power_label = editor.template_stage(profile, "power_auto", duration_seconds=300)
    assert_equal(power_stage.name, "Combined", "profile editor power template stage type")
    assert_equal(power_label, "Power (CPU + 3D)", "profile editor power template label")
    assert_true(power_stage.modules.cpu.enabled, "profile editor power template CPU")
    assert_true(power_stage.modules.gpu_3d.enabled, "profile editor power template GPU")
    sse_stage, sse_label = editor.template_stage(profile, "sse_vram", duration_seconds=300)
    assert_equal(sse_label, "SSE + VRAM", "profile editor SSE template label")
    assert_equal(sse_stage.modules.cpu.instruction_set, "sse", "profile editor SSE template CPU instruction")
    assert_true(sse_stage.modules.vram.enabled, "profile editor SSE template VRAM")
    avx_stage, avx_label = editor.template_stage(profile, "avx_ram", duration_seconds=300)
    assert_equal(avx_label, "AVX (CPU + RAM)", "profile editor AVX template label")
    assert_equal(avx_stage.modules.cpu.instruction_set, "avx2", "profile editor AVX template CPU instruction")
    assert_equal(avx_stage.modules.memory.instruction_set, "avx2", "profile editor AVX template memory instruction")

    profile, labels = editor.remove_stage(profile, labels, 0)
    assert_equal(labels, ["3D Adaptive", "VRAM Stage", "GPU Stage"], "profile editor remove label")
    assert_equal(len(profile.stages), 3, "profile editor remove stage")


def test_profile_edit_controller_dispatch() -> None:
    editor = ProfileEditor()
    controller = ProfileEditController(editor)
    profile = ValidationProfile(profile_name="Controller Smoke")
    stage = editor.create_stage(
        profile,
        test_type="Combined",
        duration_seconds=120,
        modules=editor.build_stage_modules(
            "Combined",
            include_cpu=True,
            include_memory=True,
            include_gpu_3d=True,
            include_vram=True,
        ),
    )
    profile.stages = [stage]
    labels = ["Combined Stage"]

    assert_equal(controller.stage_action("1").key, "detail", "profile controller first action")
    assert_equal(controller.stage_action("17").key, "back", "profile controller final action")
    assert_equal(controller.stage_action("bad"), None, "profile controller invalid action")
    disabled = editor.create_stage(profile, test_type="Combined", duration_seconds=60)
    assert_equal(
        controller.stage_action_error(disabled, "cpu_instruction"),
        "CPU module is not enabled on this stage.",
        "profile controller CPU requirement",
    )
    assert_equal(
        controller.stage_action_error(disabled, "gpu_target"),
        "No GPU workload is enabled on this stage.",
        "profile controller GPU requirement",
    )

    labels = controller.apply_stage_action(profile, labels, 0, "label", "Renamed").labels
    assert_equal(labels, ["Renamed"], "profile controller label")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "duration", 240).value, 240, "profile controller duration")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "toggle").value, False, "profile controller toggle")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "cpu_instruction", "avx2").value, "avx2", "profile controller CPU instruction")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "cpu_threads", "8").value, "8", "profile controller CPU threads")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "memory_instruction", "avx2").value, "avx2", "profile controller memory instruction")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "memory_allocation", 88).value, 88, "profile controller memory allocation")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "gpu_target", "discrete_all").value, "discrete_all", "profile controller GPU target")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "gpu_backend", "opencl").value, "opencl", "profile controller GPU backend")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "gpu_mode", "variable").value, "variable", "profile controller GPU mode")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "gpu_intensity", "max").value, "max", "profile controller GPU intensity")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "gpu_compute_variant", "stateful_memory").value, "stateful_memory", "profile controller GPU variant")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "gpu_allocation", 77).value, 77, "profile controller GPU allocation")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "vram_backend", "vulkan").value, "vulkan", "profile controller VRAM backend")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "vram_allocation", 81).value, 81, "profile controller VRAM allocation")
    controller.apply_stage_action(profile, labels, 0, "trim", 4, secondary_value=9)
    assert_equal(stage.normalization.trim_start_seconds, 4, "profile controller trim start")
    assert_equal(stage.normalization.trim_end_seconds, 9, "profile controller trim end")
    assert_equal(controller.apply_stage_action(profile, labels, 0, "strict").value, True, "profile controller strict")

    edit = ProfileEditState(Path("profiles/Controller Smoke.json"), profile, labels)
    assert_equal(controller.apply_picker(edit, 0, "backend", "vulkan_compute").value, "vulkan_compute", "profile controller picker")
    assert_true(edit.dirty, "profile controller picker dirty")
    edit.dirty = False
    assert_equal(
        controller.apply_input(edit, "__profile_stage_duration", "360", stage_index=0).value,
        360,
        "profile controller input duration",
    )
    controller.apply_input(edit, "__profile_stage_trim_end", "12", stage_index=0, trim_start=6)
    assert_equal((stage.normalization.trim_start_seconds, stage.normalization.trim_end_seconds), (6, 12), "profile controller input trim")
    controller.apply_input(edit, "__profile_name", "Renamed Profile")
    controller.apply_input(edit, "__profile_description", "Controller description")
    assert_equal(profile.profile_name, "Renamed Profile", "profile controller profile name")
    assert_equal(profile.menu_description, "Controller description", "profile controller description")

    group_result = controller.cycle_profile_menu_group(profile, edit.labels, ["custom", "gpu"])
    assert_equal(group_result.value, "gpu", "profile controller menu group cycle")
    strict_result = controller.cycle_profile_strict(profile, group_result.labels)
    assert_equal(strict_result.value, True, "profile controller profile strict")
    added = controller.add_stage(profile, strict_result.labels, disabled, "Disabled", position=0)
    assert_equal(added.labels[0], "Disabled", "profile controller add stage")
    removed = controller.remove_stage(profile, added.labels, 0)
    assert_equal(removed.labels, ["Renamed"], "profile controller remove stage")

    launcher = Launcher.__new__(Launcher)
    launcher.profile_editor = editor
    launcher.profile_edit_controller = controller
    launcher.profile_creation = ProfileCreationController(editor)
    responses = iter(["", "Inserted Stage", "180"])
    launcher._input = lambda _prompt="": next(responses)
    launcher._choose_test_type = lambda: "CPU"
    launcher._build_stage_modules = lambda test_type: editor.build_stage_modules(test_type)
    inserted_labels = launcher._add_profile_stage(profile, removed.labels)
    assert_equal(inserted_labels[-1], "Inserted Stage", "CLI valid-duration stage insertion")
    assert_equal(profile.stages[-1].duration_seconds, 180, "CLI valid-duration stage duration")


def test_profile_detail_presentation_helpers() -> None:
    editor = ProfileEditor()
    stage = StageConfig(
        id="segment_1",
        name="Combined",
        duration_seconds=600,
        modules=editor.build_stage_modules(
            "Combined",
            include_cpu=True,
            include_memory=True,
            include_gpu_3d=True,
            include_vram=True,
            cpu_instruction_set="avx2",
            cpu_mode="extreme",
            cpu_load="variable",
            cpu_priority="high",
            cpu_threads="8",
            memory_allocation_percent=90,
            memory_instruction_set="avx2",
            gpu_backend_preference="vulkan_compute",
            gpu_mode="steady",
            gpu_intensity="extreme",
            gpu_compute_variant="hash",
            vram_backend_preference="vulkan",
            vram_allocation_percent=80,
        ),
        strict_threshold_recommendation_warnings=True,
    )
    stage.normalization.trim_start_seconds = 10
    stage.normalization.trim_end_seconds = 20

    def gpu_catalog(preference: str) -> List[Dict[str, Any]]:
        assert_equal(preference, "vulkan_compute", "profile presentation normalized GPU preference")
        return [{
            "backend": "python_vulkan_compute",
            "api_family": "Vulkan",
            "suite_scaling_mode": "parametric",
            "suite_verification": "compute_readback",
            "recommended_for_saturation": True,
            "notes": "catalog note",
        }]

    def stage_lines(item: StageConfig, label: str) -> List[str]:
        return profile_stage_detail_lines(
            item,
            label,
            normalize_gpu_preference=lambda value: str(value).lower(),
            gpu_target_summary=lambda value: f"summary:{value}",
            normalize_gpu_intensity=lambda value: str(value).lower(),
            gpu_preference_catalog=gpu_catalog,
            normalize_vram_preference=lambda value: str(value).lower(),
        )

    assert_equal(
        stage_lines(stage, "Combined Label"),
        [
            "",
            "Stage Details",
            "Label: Combined Label",
            "Stage ID: segment_1",
            "Type: Combined",
            "Enabled: True",
            "Duration: 600s",
            "Trim: start=10s, end=20s",
            "Strict threshold warnings: enabled",
            "Enabled workloads: cpu, memory, gpu_3d, vram",
            "CPU: instruction=avx2, threads=8, mode=extreme, load=variable, priority=high",
            "Memory/RAM: allocation=90%, instruction=avx2, threads=all, priority=normal",
            "3D: target=summary:all, preference=vulkan_compute, mode=steady, intensity=extreme, compute_variant=hash, vram_hint=0%",
            "3D backend candidates:",
            "  - python_vulkan_compute: Vulkan / parametric / compute_readback / saturation=yes",
            "    catalog note",
            "VRAM: target=summary:all, preference=vulkan, allocation=80%",
            "VRAM backend candidates:",
            "  - python_vulkan_compute: suite-controlled Vulkan stateful-memory allocation and readback verification",
            "  - python_opencl: suite-controlled OpenCL buffer allocation, write, and readback verification",
            "  - python_egl_gles2: EGL/GLES texture allocation fallback for systems without usable OpenCL",
        ],
        "profile stage detail exact fixture",
    )
    disabled_stage = StageConfig(
        id="segment_2",
        name="Disabled",
        duration_seconds=60,
        modules=editor.build_stage_modules("Combined"),
        strict_threshold_recommendation_warnings=None,
    )
    assert_equal(stage_enabled_module_names(disabled_stage), [], "profile presentation disabled modules")
    disabled_lines = stage_lines(disabled_stage, "Disabled")
    assert_equal(
        disabled_lines[-4:],
        ["CPU: disabled", "Memory/RAM: disabled", "3D: disabled", "VRAM: disabled"],
        "profile presentation disabled workload details",
    )
    assert_equal(strict_threshold_override_text(None), "inherit", "profile presentation strict inherit")
    assert_equal(strict_threshold_override_text(True), "enabled", "profile presentation strict enabled")
    assert_equal(strict_threshold_override_text(False), "disabled", "profile presentation strict disabled")
    assert_equal(
        vram_backend_candidates_for_preference("opencl", normalize_preference=str.lower),
        ["python_opencl", "python_egl_gles2"],
        "profile presentation VRAM preference",
    )
    assert_equal(vram_backend_display_name("unknown"), "unknown", "profile presentation unknown VRAM name")
    assert_equal(
        vram_backend_description("unknown"),
        "unknown VRAM backend",
        "profile presentation unknown VRAM description",
    )

    profile = ValidationProfile(
        profile_name="Presentation",
        menu_group="custom",
        defaults=ProfileDefaults(
            telemetry_interval_seconds=2,
            trim_start_seconds=5,
            trim_end_seconds=6,
            strict_threshold_recommendation_warnings=False,
        ),
        stages=[stage, disabled_stage],
    )
    detail_lines = profile_detail_lines(
        profile,
        ["Combined Label"],
        menu_group_label=lambda value: f"Group:{value}",
        stage_detail_lines=stage_lines,
    )
    assert_equal(
        detail_lines[:8],
        [
            "",
            "Profile Details",
            "Name: Presentation",
            "Type: validation_schedule",
            "Menu group: Group:custom",
            "Stages: 2",
            "Defaults: telemetry_interval=2s, trim_start=5s, trim_end=6s, strict_threshold_warnings=disabled",
            "",
        ],
        "profile detail exact header fixture",
    )
    assert_true("Label: Disabled" in detail_lines, "profile detail stage label fallback")

    errors = [f"error {index}" for index in range(13)]
    warnings = [f"warning {index}" for index in range(17)]
    preview = profile_dry_run_preview_text(
        {"runnable": False, "validation": {"errors": errors, "warnings": warnings}},
        ["Execution Plan", "Profile: Presentation"],
    )
    expected_preview_lines = [
        "",
        "Profile Dry Run Preview",
        "Runnable: False",
        "Validation errors: 13",
        *[f"  [error] error {index}" for index in range(12)],
        "  ... 1 more error(s)",
        "Validation warnings: 17",
        *[f"  [warn] warning {index}" for index in range(16)],
        "  ... 1 more warning(s)",
        "",
        "Execution Plan",
        "Profile: Presentation",
        "",
    ]
    assert_equal(preview, "\n".join(expected_preview_lines) + "\n", "profile dry-run preview exact fixture")


def test_profile_creation_controller() -> None:
    editor = ProfileEditor()
    controller = ProfileCreationController(editor)
    result = controller.build_profile(ProfileCreationRequest(
        profile_name="Creation Smoke",
        menu_group="gpu",
        telemetry_interval_seconds=2.5,
        trim_start_seconds=7,
        trim_end_seconds=9,
        stages=[
            ProfileStageDraft(
                label="CPU Segment",
                test_type="CPU",
                duration_seconds=-10,
                modules=editor.build_stage_modules("CPU"),
            ),
            ProfileStageDraft(
                label="GPU Segment",
                test_type="3D Adaptive",
                duration_seconds=90,
                modules=editor.build_stage_modules(
                    "3D Adaptive",
                    gpu_target_mode="slots:0000:01:00.0",
                    gpu_backend_preference="vulkan_compute",
                ),
            ),
        ],
    ))
    profile = result.profile
    assert_equal(profile.profile_name, "Creation Smoke", "profile creation name")
    assert_equal(profile.profile_type, "validation_schedule", "profile creation type")
    assert_equal(profile.segment_label_source, "Creation Smoke_info.txt", "profile creation label source")
    assert_equal(profile.menu_group, "gpu", "profile creation menu group")
    assert_equal(profile.defaults.telemetry_interval_seconds, 2.5, "profile creation telemetry interval")
    assert_equal(profile.defaults.trim_start_seconds, 7, "profile creation trim start")
    assert_equal(profile.defaults.trim_end_seconds, 9, "profile creation trim end")
    assert_equal(result.labels, ["CPU Segment", "GPU Segment"], "profile creation labels")
    assert_equal([stage.id for stage in profile.stages], ["segment_1", "segment_2"], "profile creation stage IDs")
    assert_equal(profile.stages[0].duration_seconds, -10, "profile creation preserves CLI duration")
    assert_equal(profile.stages[1].normalization.trim_start_seconds, 7, "profile creation stage trim start")
    assert_equal(profile.stages[1].normalization.trim_end_seconds, 9, "profile creation stage trim end")
    assert_equal(profile.stages[1].modules.gpu_3d.backend_preference, "vulkan_compute", "profile creation GPU backend")

    inserted = controller.insert_stage(
        profile,
        result.labels,
        ProfileStageDraft(
            label="Memory Segment",
            test_type="Memory",
            duration_seconds=0,
            modules=editor.build_stage_modules("Memory"),
        ),
        position=1,
    )
    assert_equal(inserted.stage.id, "segment_3", "profile insertion stage ID")
    assert_equal(inserted.stage.duration_seconds, 1, "profile insertion duration minimum")
    assert_equal(inserted.labels, ["CPU Segment", "Memory Segment", "GPU Segment"], "profile insertion labels")
    assert_equal([stage.name for stage in profile.stages], ["CPU", "Memory", "3D Adaptive"], "profile insertion order")
    assert_equal(inserted.stage.normalization.trim_start_seconds, 7, "profile insertion trim start")
    assert_equal(inserted.stage.normalization.trim_end_seconds, 9, "profile insertion trim end")


def test_profile_save_controller() -> None:
    class ValidatorStub:
        def __init__(self) -> None:
            self.payload = {"errors": ["blocking error"], "warnings": ["review warning"]}

        def validate(self, profile: ValidationProfile, labels: List[str]) -> Dict[str, List[str]]:
            return self.payload

    class LoaderStub:
        def __init__(self) -> None:
            self.saved: List[tuple[Path, ValidationProfile, List[str]]] = []

        def save_profile(self, path: Path, profile: ValidationProfile, labels: List[str]) -> None:
            self.saved.append((path, profile, list(labels)))

    editor = ProfileEditor()
    profile = ValidationProfile(profile_name="Save Smoke")
    profile.stages.append(editor.create_stage(profile, test_type="CPU", duration_seconds=30))
    validator = ValidatorStub()
    loader = LoaderStub()
    controller = ProfileSaveController(editor, loader, validator)

    preparation = controller.prepare(profile, [])
    assert_equal(preparation.labels, ["CPU"], "profile save normalizes labels")
    assert_equal(preparation.errors, ["blocking error"], "profile save errors")
    assert_equal(preparation.warnings, ["review warning"], "profile save warnings")
    assert_true(not preparation.save_allowed, "profile save blocked eligibility")
    try:
        controller.save(Path("profiles/Save Smoke.json"), preparation)
        raise AssertionError("profile save should reject blocking errors")
    except ValueError as exc:
        assert_true("blocking error" in str(exc), "profile save blocked message")
    assert_equal(loader.saved, [], "profile save blocked write")

    saved_path = controller.save(
        Path("profiles/Save Smoke.json"),
        preparation,
        allow_errors=True,
    )
    assert_equal(saved_path, Path("profiles/Save Smoke.json"), "profile save forced path")
    assert_equal(loader.saved[0][2], ["CPU"], "profile save forced labels")

    validator.payload = {"errors": [], "warnings": ["warning only"]}
    warning_preparation = controller.prepare(profile, ["CPU Label"])
    assert_true(warning_preparation.save_allowed, "profile save warning eligibility")
    controller.save(Path("profiles/Save Smoke.json"), warning_preparation)
    assert_equal(loader.saved[1][2], ["CPU Label"], "profile save warning labels")


def test_profile_loader_round_trip_and_sorting() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        tmp_path = Path(tmp)
        loader = ProfileLoader(
            tmp_path,
            [
                {"key": "standard", "label": "Standard"},
                {"key": "gpu", "label": "GPU"},
            ],
        )
        editor = ProfileEditor()

        standard = ValidationProfile(
            profile_name="Standard Smoke",
            segment_label_source="Standard Smoke_info.txt",
            menu_group="standard",
            menu_description="Standard profile",
        )
        standard.stages.append(editor.create_stage(standard, test_type="CPU", duration_seconds=30))
        loader.save_profile(tmp_path / "Standard Smoke.json", standard, ["CPU"])

        gpu = ValidationProfile(
            profile_name="GPU Smoke",
            segment_label_source="GPU Smoke_info.txt",
            menu_group="GPU",
            menu_description="(GPU smoke profile)",
        )
        gpu.stages.append(editor.create_stage(gpu, test_type="3D Adaptive", duration_seconds=90))
        loader.save_profile(tmp_path / "GPU Smoke.json", gpu, ["GPU Stage"])

        paths = [path.name for path in loader.list_profiles()]
        assert_equal(paths, ["GPU Smoke.json", "Standard Smoke.json"], "profile loader alphabetic sorting")

        metadata = loader.profile_menu_metadata(tmp_path / "GPU Smoke.json")
        assert_equal(metadata["menu_group"], "gpu", "profile loader menu group metadata")
        assert_equal(metadata["menu_description"], "GPU smoke profile", "profile loader menu description metadata")
        assert_equal(loader.menu_group_label("gpu"), "GPU", "profile loader group label")

        loaded = loader.load_profile(tmp_path / "GPU Smoke.json")
        assert_equal(loaded.profile_name, "GPU Smoke", "profile loader loaded name")
        assert_equal(loaded.menu_group, "gpu", "profile loader loaded group")
        assert_equal(loaded.menu_description, "GPU smoke profile", "profile loader loaded description")
        assert_equal(len(loaded.stages), 1, "profile loader loaded stage count")
        assert_true(loaded.stages[0].modules.gpu_3d.enabled, "profile loader loaded GPU module")
        labels = loader.load_segment_labels(tmp_path / "GPU Smoke.json", loaded)
        assert_equal(labels, ["GPU Stage"], "profile loader sidecar labels")
        label_source = loader.inspect_segment_label_source(tmp_path / "GPU Smoke.json", loaded)
        assert_true(label_source["exists"], "profile loader sidecar exists")
        assert_equal(label_source["issues"], [], "profile loader sidecar issues")


def test_google_drive_not_ready_manifest() -> None:
    assert_true(issubclass(GoogleDriveUploader, ModuleGoogleDriveUploader), "cli google uploader wrapper")

    class NotReadyUploader(ModuleGoogleDriveUploader):
        def readiness(self):
            return {
                "ready": False,
                "missing": ["credential_file", "googleapiclient.discovery"],
                "credential_path": "/tmp/missing-google-credentials.json",
            }

    with TemporaryDirectory(dir="/tmp") as tmp:
        tmp_path = Path(tmp)
        result_dir = tmp_path / "2026-05-26_00-00-00_Upload_Smoke"
        result_dir.mkdir()
        (result_dir / "parsed_results_custom.json").write_text("{}", encoding="utf-8")
        settings = GlobalSettings(results_dir=str(tmp_path), google_drive_move_to_uploaded_on_success=True)
        uploader = NotReadyUploader(settings)

        payload = uploader.upload_result_folder(result_dir)
        assert_equal(payload["result"], "failed", "google upload not-ready result")
        assert_true(result_dir.exists(), "google upload not-ready keeps source folder")
        assert_true((result_dir / "upload_manifest.json").exists(), "google upload not-ready manifest")
        assert_true((result_dir / "google_drive_upload.json").exists(), "google upload not-ready detail manifest")
        manifest = JsonStore.read(result_dir / "upload_manifest.json", {})
        assert_equal(manifest.get("result"), "failed", "google upload manifest result")
        assert_true("credential_file" in manifest.get("errors", [""])[0], "google upload manifest missing credentials")
        text = PostRunManager(settings, RunSummaryTextExporter()).upload_result_summary_text(payload)
        assert_true("Google Drive Upload" in text, "google upload summary title")
        assert_true("Result: failed" in text, "google upload summary failure")


def test_fresh_user_settings_bootstrap() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        tmp_path = Path(tmp)
        settings_dir = tmp_path / "settings"
        settings_path = settings_dir / "global_settings.json"
        JsonStore.write(
            settings_dir / "global_settings.example.json",
            {
                "environment_mode": "end_user",
                "results_dir": "results",
                "profiles_dir": "profiles",
                "settings_dir": "settings",
                "google_drive_credentials_path": "",
                "google_drive_shared_drive_id": "",
                "google_drive_move_to_uploaded_on_success": False,
                "google_drive_prompt_after_run": False,
            },
        )

        manager = SettingsManager(settings_path)
        assert_true(settings_path.exists(), "fresh settings file created")
        assert_equal(manager.settings.environment_mode, "end_user", "fresh settings use example environment")
        assert_equal(manager.settings.google_drive_shared_drive_id, "", "fresh settings shared drive blank")
        assert_equal(manager.settings.google_drive_credentials_path, "", "fresh settings credentials blank")
        assert_true(not manager.settings.google_drive_prompt_after_run, "fresh settings upload prompt disabled")
        assert_true((settings_dir / "secrets").is_dir(), "fresh settings secrets dir created")

        readiness = ModuleGoogleDriveUploader(manager.settings).readiness()
        assert_true(not readiness["ready"], "fresh settings upload not ready")
        assert_true("shared_drive_id" in readiness["missing"], "fresh settings missing shared drive")


def test_dependency_report_summary_with_injected_telemetry() -> None:
    telemetry_init = {}

    class FakeTelemetry:
        def __init__(self, **kwargs):
            telemetry_init.update(kwargs)

        def detect_capabilities(self):
            return {
                "cpu_temp_c": {"available": True, "source": "hwmon:Tctl"},
                "cpu_power_w": {"available": False, "source": "not found"},
                "memory_temp_c": {"available": True, "source": "spd5118", "count": 4},
                "gpu_temp_c": {"available": True, "source": "nvidia-smi temperature", "count": 2},
                "gpu_power_w": {"available": True, "source": "nvidia-smi power", "count": 2},
                "gpu_busy_percent": {"available": True, "source": "nvidia-smi utilization", "count": 2},
                "gpu_vram_used_gb": {"available": True, "source": "nvidia-smi memory", "count": 2},
            }

    fake_gpu_cards = [
        {"target_id": "0000:01:00.0", "slot": "0000:01:00.0", "vendor": "nvidia", "name": "RTX A"},
        {"target_id": "0000:02:00.0", "slot": "0000:02:00.0", "vendor": "amd", "name": "Radeon B"},
    ]

    def fake_opencl_match(card):
        if card.get("vendor") == "nvidia":
            return {"name": "NVIDIA OpenCL", "required_env": {"OCL_ICD_VENDORS": "/etc/OpenCL/vendors/nvidia.icd"}}
        return None

    workload_runner = SimpleNamespace(
        detect_backends=lambda: {
            "cpu_native_helper": True,
            "memory_native_helper": False,
            "python_vulkan_compute": True,
            "python_vulkan_transfer": True,
            "python_opencl": True,
            "python_egl_gles2": False,
            "nvidia_smi": True,
            "glmark2": False,
            "vkmark": False,
        },
        backend_details=lambda: {"intel_gpu_top": {"usable": True}},
        runtime_environment=lambda: {"PATH": "/usr/bin"},
        _discover_gpu_cards=lambda: fake_gpu_cards,
        _opencl_device_for_target=fake_opencl_match,
    )
    settings = SimpleNamespace(
        sample_interval_seconds=0.25,
        runtime_environment={"RUSTICL_ENABLE": "radeonsi"},
        privileged_helper_enabled=True,
    )
    manager = DependencyReportManager(
        settings,
        SimpleNamespace(workload_runner=workload_runner),
        lambda: {
            "ready": False,
            "credential_exists": True,
            "shared_drive_id_configured": False,
            "missing": ["googleapiclient.discovery"],
        },
        telemetry_factory=FakeTelemetry,
        memory_modules_factory=lambda privileged: [
            {"position": "DIMM A1", "part_number": "ABC123", "source": "dmidecode" if privileged else "inxi"}
        ],
    )

    text = manager.dependency_summary_text()
    assert_equal(telemetry_init["interval_seconds"], 0.25, "dependency telemetry interval")
    assert_equal(telemetry_init["runtime_environment"], {"RUSTICL_ENABLE": "radeonsi"}, "dependency runtime env")
    assert_equal(telemetry_init["privileged_helper_enabled"], True, "dependency privileged telemetry flag")
    assert_true("- CPU native helper: OK" in text, "dependency CPU helper status")
    assert_true("- Memory native helper: missing" in text, "dependency memory helper status")
    assert_true("- intel_gpu_top: OK" in text, "dependency intel gpu top status")
    assert_true("- GPU temp: OK (nvidia-smi temperature, count=2)" in text, "dependency GPU temp count")
    assert_true("- Ready: no" in text, "dependency drive readiness status")
    assert_true("- Missing: googleapiclient.discovery" in text, "dependency drive missing list")
    built_payload = manager.dependency_check_payload(sudo_noninteractive_ready=lambda: True)
    assert_equal(built_payload["app_name"], "Linux Validation Suite", "dependency payload app name")
    assert_true(built_payload["execution_context"]["privileged_helper_effective"], "dependency payload helper effective")
    assert_equal(built_payload["runtime_environment"], {"PATH": "/usr/bin"}, "dependency payload runtime environment")
    assert_equal(
        built_payload["memory_identity"]["identified_module_count"],
        1,
        "dependency payload memory identity count",
    )
    assert_equal(len(built_payload["gpu_opencl_coverage"]), 2, "dependency payload OpenCL coverage count")
    assert_true(built_payload["gpu_opencl_coverage"][0]["available"], "dependency payload OpenCL covered GPU")
    assert_true(not built_payload["gpu_opencl_coverage"][1]["available"], "dependency payload OpenCL missing GPU")
    detail_text = manager.dependency_check_detail_text(built_payload)
    assert_true("Dependency Check" in detail_text, "dependency detail heading")
    assert_true("  [OK] CPU native helper" in detail_text, "dependency detail legacy status format")
    assert_true("  [missing preferred] Memory native helper" in detail_text, "dependency detail preferred missing format")
    assert_true("Per-GPU OpenCL coverage:" in detail_text, "dependency detail OpenCL coverage")
    assert_true("DIMM A1 | ABC123" in detail_text, "dependency detail memory module line")
    service = SuiteAppService()
    service.dependency_reports = manager
    service_payload = service.dependency_check_payload()
    assert_equal(service_payload["kind"], "dependency_check", "service dependency payload kind")
    payload = {
        "execution_context": {
            "user": "tester",
            "effective_uid": 1000,
            "is_root": False,
            "privileged_helper_enabled": True,
            "privileged_helper_effective": False,
            "privileged_helper_prompt_for_sudo": True,
            "python_executable": "/usr/bin/python3.14",
        },
        "backends": workload_runner.detect_backends(),
        "backend_details": {
            "python_vulkan_compute": {"available": True, "runtime_gpu_device_count": 2},
            "python_opencl": {"available": True, "devices": [{"name": "GPU"}], "selected_context": "native"},
            "intel_gpu_top": {"available": True, "usable": False, "reason": "permission denied"},
        },
        "telemetry_capabilities": {
            "cpu_temp_c": {"available": True},
            "cpu_power_w": {"available": False, "permission_issue": True},
            "memory_temp_c": {"available": True},
            "storage_temp_c": {"available": False},
            "gpu_temp_c": {"available": True},
            "gpu_power_w": {"available": True},
            "gpu_busy_percent": {"available": True},
            "gpu_vram_used_gb": {"available": True},
            "gpu_telemetry_by_gpu": {
                "gpus": [
                    {
                        "gpu_index": 0,
                        "slot": "0000:01:00.0",
                        "metrics": {
                            "temp": {"available": True},
                            "memory_busy": {"available": False},
                        },
                    }
                ]
            },
        },
        "memory_identity": {
            "available": False,
            "identified_module_count": 0,
            "module_count": 2,
            "source": "not found",
        },
        "gpu_opencl_coverage": [
            {"target_id": "0000:01:00.0", "available": True},
            {"target_id": "0000:02:00.0", "available": False, "fix": "missing OpenCL device"},
        ],
        "google_drive_upload": {
            "ready": False,
            "credential_path": "settings/secrets/google-credentials.json",
            "missing": ["googleapiclient.discovery"],
        },
    }
    summary = manager.dependency_check_summary_text(payload)
    assert_true("Dependency Check Summary" in summary, "dependency check summary heading")
    assert_true("Covered GPUs: 1/2" in summary, "dependency check OpenCL coverage")
    assert_true("Privileged Helper Suggestions" in summary, "dependency check helper hints")
    with TemporaryDirectory() as tmp:
        report_dir = manager.save_dependency_check_report(Path(tmp), "Full dependency text", payload)
        assert_true(report_dir.name.endswith("_Dependency_Check"), "dependency check folder suffix")
        assert_true((report_dir / "dependency_check.json").exists(), "dependency check json")
        assert_true((report_dir / "dependency_check.txt").exists(), "dependency check text")
        assert_true((report_dir / "dependency_check_summary.txt").exists(), "dependency check summary")
    with TemporaryDirectory() as tmp:
        result = manager.run_dependency_check(Path(tmp), sudo_noninteractive_ready=lambda: True)
        assert_equal(result.payload["kind"], "dependency_check", "dependency action payload kind")
        assert_equal(result.payload["result"], "Saved", "dependency action saved result")
        assert_true("Dependency Check" in result.detail_text, "dependency action detail text")
        assert_true("Dependency Check Summary" in result.summary_text, "dependency action summary text")
        assert_true((result.report_dir / "dependency_check.json").exists(), "dependency action json")
        service = SuiteAppService.__new__(SuiteAppService)
        service.settings_manager = SimpleNamespace(settings=SimpleNamespace(results_dir=tmp))
        service.dependency_reports = manager
        service_result = service.run_dependency_check()
        assert_equal(service_result.payload["kind"], "dependency_check", "service dependency action payload kind")
        assert_true(service_result.report_dir.exists(), "service dependency action report dir")


def test_telemetry_source_helpers() -> None:
    sources = [
        {
            "kind": "gpu_sensor",
            "metric": "temp_core_c",
            "gpu_index": 1,
            "label": "card1 edge",
            "path": "/sys/class/drm/card1/device/hwmon/hwmon2/temp1_input",
            "key": "gpu_1_temp_core_c",
            "card": "card1",
            "slot": "0000:03:00.0",
            "threshold_source": "suite_default",
        },
        {
            "kind": "gpu_sensor",
            "metric": "temp_core_c",
            "gpu_index": 0,
            "label": "card0 edge",
            "path": "/sys/class/drm/card0/device/hwmon/hwmon3/temp1_input",
            "key": "gpu_0_temp_core_c",
            "card": "card0",
            "slot": "0000:13:00.0",
            "warn_threshold_c": 93.0,
            "fail_threshold_c": 100.0,
            "threshold_source": "hwmon_limit",
        },
        {
            "kind": "gpu_sensor",
            "metric": "power_w",
            "gpu_index": 0,
            "label": "card0 PPT",
            "path": "/sys/class/drm/card0/device/hwmon/hwmon3/power1_average",
            "key": "gpu_0_power_w",
            "card": "card0",
            "slot": "0000:13:00.0",
            "score": 20,
        },
        {
            "kind": "nvidia_smi",
            "metric": "fan_percent",
            "gpu_index": 0,
            "label": "card0 fan speed",
            "path": "nvidia-smi:0000:13:00.0",
            "key": "gpu_0_fan_percent",
            "card": "card0",
            "slot": "0000:13:00.0",
            "query_field": "fan.speed",
        },
        {
            "kind": "nvidia_smi",
            "metric": "throttle_hw_thermal",
            "gpu_index": 0,
            "label": "card0 hardware thermal slowdown",
            "path": "nvidia-smi:0000:13:00.0",
            "key": "gpu_0_throttle_hw_thermal",
            "card": "card0",
            "slot": "0000:13:00.0",
            "query_field": "clocks_event_reasons.hw_thermal_slowdown",
            "evidence_only": True,
        },
        {
            "kind": "gpu_sensor",
            "metric": "vddgfx_v",
            "gpu_index": 0,
            "label": "card0 vddgfx",
            "path": "/sys/class/drm/card0/device/hwmon/hwmon3/in0_input",
            "key": "gpu_0_vddgfx_v",
            "card": "card0",
            "slot": "0000:13:00.0",
        },
        {
            "kind": "gpu_sensor",
            "metric": "vddnb_v",
            "gpu_index": 0,
            "label": "card0 vddnb",
            "path": "/sys/class/drm/card0/device/hwmon/hwmon3/in1_input",
            "key": "gpu_0_vddnb_v",
            "card": "card0",
            "slot": "0000:13:00.0",
        },
    ]
    preferred = preferred_metric_source(sources, "temp_core_c", prefer_hardware_thresholds=True)
    assert_equal(preferred["gpu_index"], 0, "preferred telemetry source prefers hardware thresholds")
    assert_equal(metric_gpu_count(sources, "temp_core_c"), 2, "telemetry metric GPU count")
    assert_equal(
        source_thresholds(preferred, 90.0, 95.0),
        {"warn_c": 93.0, "fail_c": 100.0, "source": "hwmon_limit", "derived_from_hardware": True},
        "telemetry source thresholds",
    )
    assert_equal(
        telemetry_source_description(preferred),
        "gpu_sensor:card0 edge (/sys/class/drm/card0/device/hwmon/hwmon3/temp1_input)",
        "telemetry source description",
    )
    assert_equal(telemetry_source_description(None), "not found", "missing telemetry source description")
    assert_true(
        unreadable_source_description(sources).startswith("present but unreadable:"),
        "unreadable telemetry source description",
    )
    matrix = build_gpu_telemetry_matrix(
        [
            {"gpu_index": 1, "card": "card1", "slot": "0000:03:00.0", "vendor": "AMD", "driver": "amdgpu"},
            {"gpu_index": 0, "card": "card0", "slot": "0000:13:00.0", "vendor": "AMD", "driver": "amdgpu"},
        ],
        sources,
    )
    assert_equal([entry["gpu_index"] for entry in matrix], [0, 1], "telemetry matrix sorted by GPU index")
    assert_true(matrix[0]["metrics"]["temperature"]["available"], "telemetry matrix temperature available")
    assert_true(matrix[0]["metrics"]["power"]["available"], "telemetry matrix power available")
    assert_true(matrix[0]["metrics"]["fan"]["available"], "telemetry matrix fan available")
    assert_true(matrix[0]["metrics"]["throttle_hw_thermal"]["available"], "telemetry matrix throttle evidence available")
    assert_true(matrix[0]["metrics"]["vddgfx_voltage"]["available"], "telemetry matrix vddgfx available")
    assert_true(matrix[0]["metrics"]["vddnb_voltage"]["available"], "telemetry matrix vddnb available")
    assert_equal(matrix[1]["metrics"]["power"]["source"], "not found", "telemetry matrix missing metric")
    capability_summary = build_telemetry_capability_summary(
        cpu_temp_source={"kind": "hwmon", "label": "Tctl", "path": "/sys/class/hwmon/hwmon0/temp1_input"},
        cpu_power_source=None,
        cpu_power_unreadable_sources=[{"kind": "rapl", "label": "package-0", "path": "/sys/class/powercap/intel-rapl:0/energy_uj"}],
        cpu_clock_source={"kind": "cpufreq", "label": "scaling_cur_freq", "path": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"},
        cpu_core_clock_sources=[
            {"kind": "cpufreq_core", "label": "Core 0 Clock", "path": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"},
            {"kind": "cpufreq_core", "label": "Core 1 Clock", "path": "/sys/devices/system/cpu/cpu1/cpufreq/scaling_cur_freq"},
        ],
        cpu_core_classification={"core_count": 2, "p_core_count": 2, "e_core_count": 0},
        memory_temp_sources=[],
        storage_temp_sources=[
            {
                "kind": "storage_temp",
                "key": "storage_drive_0_temp_c",
                "label": "NVMe Composite",
                "drive_index": 0,
                "block_name": "nvme0n1",
                "path": "/sys/class/hwmon/hwmon8/temp1_input",
                "pcie_link": {
                    "MaxLinkSpeed": "16.0 GT/s",
                    "CurrentLinkSpeed": "16.0 GT/s",
                    "MaxLinkWidth": "4",
                    "CurrentLinkWidth": "4",
                    "PciSlot": "0000:06:00.0",
                },
            },
            {
                "kind": "storage_temp_secondary",
                "key": "storage_drive_0_sensor_1_temp_c",
                "label": "NVMe Sensor 1",
                "drive_index": 0,
                "sensor_index": 1,
                "block_name": "nvme0n1",
                "path": "/sys/class/hwmon/hwmon8/temp2_input",
            },
        ],
        device_temp_sources=[
            {
                "kind": "nic_temp",
                "key": "nic_0_temp_c",
                "label": "r8169_0_e00:00",
                "nic_index": 0,
                "device_name": "r8169_0_e00:00",
                "path": "/sys/class/hwmon/hwmon4/temp1_input",
                "evidence_only": True,
            },
            {
                "kind": "board_temp",
                "key": "board_0_temp_c",
                "label": "gigabyte_wmi temp1",
                "board_sensor_index": 0,
                "device_name": "gigabyte_wmi",
                "path": "/sys/class/hwmon/hwmon6/temp1_input",
                "evidence_only": True,
            },
            {
                "kind": "wifi_temp",
                "key": "wifi_0_temp_c",
                "label": "iwlwifi_1",
                "wifi_index": 0,
                "device_name": "iwlwifi_1",
                "path": "/sys/class/hwmon/hwmon11/temp1_input",
                "evidence_only": True,
            },
        ],
        gpu_sources=sources,
        gpu_temp_source=preferred,
        describe_source=telemetry_source_description,
        describe_unreadable_sources=unreadable_source_description,
        metric_thresholds=lambda key: (
            {"warn_c": 95.0, "fail_c": 100.0, "source": "suite_default", "derived_from_hardware": False}
            if key == "cpu_temp_c"
            else source_thresholds(preferred, 90.0, 95.0)
        ),
        gpu_metric_threshold_summary=lambda metric: [
            {"gpu_index": source["gpu_index"], "source": telemetry_source_description(source), "thresholds": source_thresholds(source, 90.0, 95.0)}
            for source in sources
            if source.get("metric") == metric
        ],
        gpu_telemetry_matrix=lambda: matrix,
        memory_used_available=True,
    )
    assert_true(capability_summary["cpu_temp_c"]["available"], "capability summary CPU temp")
    assert_true(capability_summary["cpu_power_w"]["permission_issue"], "capability summary CPU power permission issue")
    assert_equal(capability_summary["cpu_core_clock_mhz"]["count"], 2, "capability summary core clock count")
    assert_true(capability_summary["storage_temp_c"]["available"], "capability summary storage primary")
    assert_equal(capability_summary["storage_temp_c"]["count"], 1, "capability summary storage primary count")
    assert_true(capability_summary["storage_secondary_temp_c"]["available"], "capability summary storage secondary")
    assert_equal(capability_summary["storage_secondary_temp_c"]["count"], 1, "capability summary storage secondary count")
    assert_true(capability_summary["nic_temp_c"]["available"], "capability summary NIC temp evidence")
    assert_equal(capability_summary["nic_temp_c"]["count"], 1, "capability summary NIC temp count")
    assert_true(capability_summary["nic_temp_c"]["evidence_only"], "capability summary NIC temp evidence-only marker")
    assert_true(capability_summary["board_temp_c"]["available"], "capability summary board temp evidence")
    assert_equal(capability_summary["board_temp_c"]["count"], 1, "capability summary board temp count")
    assert_true(capability_summary["board_temp_c"]["evidence_only"], "capability summary board temp evidence-only marker")
    assert_true(capability_summary["wifi_temp_c"]["available"], "capability summary Wi-Fi temp evidence")
    assert_equal(capability_summary["wifi_temp_c"]["count"], 1, "capability summary Wi-Fi temp count")
    assert_true(capability_summary["wifi_temp_c"]["evidence_only"], "capability summary Wi-Fi temp evidence-only marker")
    assert_equal(capability_summary["gpu_temp_c"]["count"], 2, "capability summary GPU temp count")
    assert_true(capability_summary["gpu_telemetry_by_gpu"]["gpus"][0]["metrics"]["power"]["available"], "capability summary GPU matrix")
    assert_true(capability_summary["gpu_fan_percent"]["available"], "capability summary GPU fan")
    assert_equal(capability_summary["gpu_fan_percent"]["count"], 1, "capability summary GPU fan count")
    assert_true(capability_summary["gpu_throttle_hw_thermal"]["available"], "capability summary GPU throttle evidence")
    assert_true(capability_summary["gpu_throttle_hw_thermal"]["evidence_only"], "capability summary GPU throttle evidence-only marker")
    assert_true(capability_summary["gpu_vddgfx_v"]["available"], "capability summary GPU vddgfx")
    assert_true(capability_summary["gpu_vddnb_v"]["available"], "capability summary GPU vddnb")
    assert_equal(
        capability_summary["telemetry_privilege"]["source_mode"],
        "unprivileged",
        "capability summary telemetry privilege default mode",
    )
    privileged_capability_summary = build_telemetry_capability_summary(
        cpu_temp_source={"kind": "hwmon", "label": "Tctl", "path": "/sys/class/hwmon/hwmon0/temp1_input"},
        cpu_power_source={
            "kind": "aggregate_energy",
            "label": "CPU package power",
            "path": "",
            "sources": [
                {"kind": "rapl", "label": "package-0", "path": "/sys/class/powercap/intel-rapl:0/energy_uj"},
                {"kind": "sudo_rapl", "label": "package-1 via sudo", "path": "/sys/class/powercap/intel-rapl:1/energy_uj"},
            ],
        },
        cpu_power_unreadable_sources=[],
        cpu_clock_source=None,
        cpu_core_clock_sources=[],
        cpu_core_classification={},
        memory_temp_sources=[],
        storage_temp_sources=[],
        gpu_sources=[],
        gpu_temp_source=None,
        describe_source=telemetry_source_description,
        describe_unreadable_sources=unreadable_source_description,
        metric_thresholds=lambda _key: None,
        gpu_metric_threshold_summary=lambda _metric: [],
        gpu_telemetry_matrix=lambda: [],
        memory_used_available=True,
        privileged_helper_enabled=True,
        process_is_root=False,
        sudo_available=True,
    )
    assert_equal(
        privileged_capability_summary["telemetry_privilege"],
        {
            "source_mode": "sudo_telemetry",
            "privileged_helper_enabled": True,
            "process_is_root": False,
            "sudo_available": True,
            "sudo_sources_used": True,
            "sudo_source_kinds": ["sudo_rapl"],
            "sudo_source_count": 1,
            "unreadable_privileged_candidate_count": 0,
        },
        "capability summary telemetry privilege sudo mode",
    )

    source_map = build_telemetry_source_map(
        cpu_temp_source={"kind": "hwmon", "label": "Tctl", "path": "/sys/class/hwmon/hwmon0/temp1_input"},
        cpu_package_temp_sources=[
            {
                "kind": "hwmon",
                "key": "cpu_package_0_temp_c",
                "label": "Tctl",
                "path": "/sys/class/hwmon/hwmon0/temp1_input",
                "package_id": 0,
            }
        ],
        cpu_power_source=None,
        cpu_clock_source={"kind": "cpufreq", "label": "scaling_cur_freq", "path": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"},
        cpu_core_clock_sources=[
            {"kind": "cpufreq_core", "key": "cpu_core_0_clock_mhz", "label": "Core 0 Clock", "path": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"}
        ],
        memory_temp_sources=[
            {"kind": "ipmi_memory_temp", "key": "memory_module_0_temp_c", "label": "DIMM_A1", "sensor_id": "DIMM_A1", "module_index": 0, "path": "ipmitool sensor"}
        ],
        storage_temp_sources=[
            {
                "kind": "storage_temp",
                "key": "storage_drive_0_temp_c",
                "label": "NVMe Composite",
                "drive_index": 0,
                "block_name": "nvme0n1",
                "path": "/sys/class/hwmon/hwmon8/temp1_input",
                "pcie_link": {
                    "MaxLinkSpeed": "16.0 GT/s",
                    "CurrentLinkSpeed": "16.0 GT/s",
                    "MaxLinkWidth": "4",
                    "CurrentLinkWidth": "4",
                    "PciSlot": "0000:06:00.0",
                },
            },
            {
                "kind": "storage_temp_secondary",
                "key": "storage_drive_0_sensor_1_temp_c",
                "label": "NVMe Sensor 1",
                "drive_index": 0,
                "sensor_index": 1,
                "block_name": "nvme0n1",
                "path": "/sys/class/hwmon/hwmon8/temp2_input",
            },
        ],
        device_temp_sources=[
            {
                "kind": "nic_temp",
                "key": "nic_0_temp_c",
                "label": "r8169_0_e00:00",
                "nic_index": 0,
                "device_name": "r8169_0_e00:00",
                "path": "/sys/class/hwmon/hwmon4/temp1_input",
                "evidence_only": True,
            },
            {
                "kind": "board_temp",
                "key": "board_0_temp_c",
                "label": "gigabyte_wmi temp1",
                "board_sensor_index": 0,
                "device_name": "gigabyte_wmi",
                "path": "/sys/class/hwmon/hwmon6/temp1_input",
                "evidence_only": True,
            },
            {
                "kind": "wifi_temp",
                "key": "wifi_0_temp_c",
                "label": "iwlwifi_1",
                "wifi_index": 0,
                "device_name": "iwlwifi_1",
                "path": "/sys/class/hwmon/hwmon11/temp1_input",
                "evidence_only": True,
            },
        ],
        gpu_sources=sources,
        gpu_cards=[
            {
                "gpu_index": 0,
                "card": "card0",
                "slot": "0000:13:00.0",
                "vendor": "AMD",
                "driver": "amdgpu",
                "pcie_link": {
                    "MaxLinkSpeed": "16.0 GT/s",
                    "CurrentLinkSpeed": "8.0 GT/s",
                    "MaxLinkWidth": "16",
                    "CurrentLinkWidth": "8",
                    "PciSlot": "0000:13:00.0",
                },
            },
            {
                "gpu_index": 1,
                "card": "card1",
                "slot": "0000:03:00.0",
                "vendor": "AMD",
                "driver": "amdgpu",
                "pcie_link": {
                    "MaxLinkSpeed": "8.0 GT/s",
                    "CurrentLinkSpeed": "8.0 GT/s",
                    "MaxLinkWidth": "8",
                    "CurrentLinkWidth": "8",
                    "PciSlot": "0000:13:00.0",
                },
            },
        ],
        privileged_helper_enabled=True,
        process_is_root=False,
        sudo_available=True,
    )
    assert_equal(source_map["fields"]["gpu_0_power_w"]["slot"], "0000:13:00.0", "source map GPU slot")
    assert_equal(source_map["fields"]["gpu_0_power_w"]["access_mode"], "direct", "source map direct access mode")
    assert_equal(source_map["fields"]["gpu_0_fan_percent"]["query_field"], "fan.speed", "source map GPU fan query field")
    assert_equal(source_map["fields"]["gpu_0_throttle_hw_thermal"]["query_field"], "clocks_event_reasons.hw_thermal_slowdown", "source map GPU throttle query field")
    assert_true(source_map["fields"]["gpu_0_throttle_hw_thermal"]["evidence_only"], "source map GPU throttle evidence-only marker")
    assert_equal(source_map["fields"]["gpu_0_vddgfx_v"]["metric"], "vddgfx_v", "source map GPU vddgfx metric")
    assert_equal(source_map["fields"]["gpu_0_vddnb_v"]["metric"], "vddnb_v", "source map GPU vddnb metric")
    assert_equal(source_map["fields"]["cpu_package_0_temp_c"]["package_id"], 0, "source map CPU package temp")
    assert_equal(source_map["fields"]["memory_module_0_temp_c"]["sensor_id"], "DIMM_A1", "source map DIMM sensor")
    assert_equal(source_map["fields"]["storage_drive_0_temp_c"]["kind"], "storage_temp", "source map storage primary kind")
    assert_equal(source_map["fields"]["storage_drive_0_temp_c"]["pcie_link"]["CurrentLinkWidth"], "4", "source map storage PCIe link field")
    assert_equal(source_map["storage_link_map"][0]["block_name"], "nvme0n1", "source map storage PCIe link map")
    assert_equal(source_map["gpu_index_map"][0]["pcie_link"]["CurrentLinkSpeed"], "8.0 GT/s", "source map GPU PCIe link map")
    assert_true("pcie_link" not in source_map["gpu_index_map"][1], "source map drops mismatched GPU PCIe link")
    assert_equal(source_map["fields"]["nic_0_temp_c"]["kind"], "nic_temp", "source map NIC temp kind")
    assert_true(source_map["fields"]["nic_0_temp_c"]["evidence_only"], "source map NIC temp evidence-only marker")
    assert_equal(source_map["fields"]["nic_0_temp_c"]["nic_index"], 0, "source map NIC temp index")
    assert_equal(source_map["fields"]["board_0_temp_c"]["kind"], "board_temp", "source map board temp kind")
    assert_true(source_map["fields"]["board_0_temp_c"]["evidence_only"], "source map board temp evidence-only marker")
    assert_equal(source_map["fields"]["board_0_temp_c"]["board_sensor_index"], 0, "source map board temp index")
    assert_equal(source_map["fields"]["wifi_0_temp_c"]["kind"], "wifi_temp", "source map Wi-Fi temp kind")
    assert_true(source_map["fields"]["wifi_0_temp_c"]["evidence_only"], "source map Wi-Fi temp evidence-only marker")
    assert_equal(source_map["fields"]["wifi_0_temp_c"]["wifi_index"], 0, "source map Wi-Fi temp index")
    assert_equal(
        source_map["fields"]["storage_drive_0_sensor_1_temp_c"]["kind"],
        "storage_temp_secondary",
        "source map storage secondary kind",
    )
    assert_equal(
        source_map["fields"]["storage_drive_0_sensor_1_temp_c"]["sensor_index"],
        1,
        "source map storage secondary sensor index",
    )
    assert_equal(source_map["fields"]["cpu_power_w"]["available"], False, "source map missing CPU power")
    assert_equal(source_map["gpu_index_map"][1]["card"], "card1", "source map GPU index map")
    assert_equal(
        source_map["telemetry_privilege"]["source_mode"],
        "privileged_helper_available",
        "source map telemetry privilege helper available mode",
    )
    privileged_source_map = build_telemetry_source_map(
        cpu_temp_source=None,
        cpu_package_temp_sources=[],
        cpu_power_source={
            "kind": "aggregate_energy",
            "label": "CPU package power",
            "path": "",
            "sources": [
                {
                    "kind": "sudo_rapl",
                    "key": "cpu_package_1_power_w",
                    "label": "package-1 via sudo",
                    "path": "/sys/class/powercap/intel-rapl:1/energy_uj",
                    "package_id": 1,
                }
            ],
        },
        cpu_clock_source=None,
        cpu_core_clock_sources=[],
        memory_temp_sources=[],
        storage_temp_sources=[],
        gpu_sources=[],
        gpu_cards=[],
        privileged_helper_enabled=True,
        process_is_root=False,
        sudo_available=True,
    )
    assert_equal(
        privileged_source_map["fields"]["cpu_package_1_power_w"]["access_mode"],
        "sudo",
        "source map sudo access mode",
    )
    assert_equal(
        privileged_source_map["telemetry_privilege"]["source_mode"],
        "sudo_telemetry",
        "source map telemetry privilege sudo mode",
    )


def test_telemetry_source_capability_fixture_contract() -> None:
    fixture_path = ROOT / "smoke_tests" / "fixtures" / "telemetry_source_capability_dual_cpu_nvidia_trimmed.json"
    fixture = json.loads(fixture_path.read_text())
    capabilities = fixture["telemetry_capabilities"]
    source_map = fixture["telemetry_source_map"]
    fields = source_map["fields"]

    assert_equal(
        fixture["_FixtureSourceMapSource"],
        "trimmed retained QA telemetry source-map fixture",
        "telemetry source map fixture source",
    )
    assert_equal(
        fixture["_FixtureCapabilitySource"],
        "trimmed retained QA run-manifest fixture",
        "telemetry capability fixture source",
    )
    assert_equal(source_map["version"], 1, "telemetry source map version")
    assert_equal(
        source_map["purpose"],
        "Maps raw_telemetry.csv field names to hardware telemetry sources.",
        "telemetry source map purpose",
    )

    assert_equal(fields["timestamp"]["source"], "time.monotonic()", "source map timestamp source")
    assert_equal(fields["memory_used_gb"]["source"], "/proc/meminfo", "source map memory used source")
    assert_equal(fields["cpu_temp_c"]["kind"], "hwmon", "source map CPU temp hwmon")
    assert_equal(fields["cpu_temp_c"]["label"], "Tctl", "source map CPU temp label")
    assert_equal(fields["cpu_package_0_temp_c"]["package_id"], 0, "source map package 0 temp package id")
    assert_equal(fields["cpu_package_1_temp_c"]["package_id"], 1, "source map package 1 temp package id")
    assert_equal(fields["cpu_package_0_temp_c"]["kind"], "hwmon", "source map package 0 temp source kind")
    assert_equal(fields["cpu_package_1_temp_c"]["path"], "/sys/class/hwmon/hwmon3/temp1_input", "source map package 1 temp path")

    assert_equal(fields["cpu_power_w"]["kind"], "aggregate_energy", "source map aggregate CPU power kind")
    assert_equal(fields["cpu_power_w"]["package_count"], 2, "source map aggregate CPU power package count")
    assert_equal(
        fields["cpu_power_w"]["component_sources"],
        [
            "rapl:package-0 (/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/energy_uj)",
            "sudo_rapl:package-1 via sudo (/sys/devices/virtual/powercap/intel-rapl/intel-rapl:1/energy_uj)",
        ],
        "source map aggregate CPU power components",
    )
    assert_equal(fields["cpu_package_0_power_w"]["kind"], "rapl", "source map package 0 power kind")
    assert_equal(fields["cpu_package_1_power_w"]["kind"], "sudo_rapl", "source map package 1 power kind")
    assert_equal(fields["cpu_clock_mhz"]["kind"], "cpufreq", "source map CPU clock kind")
    assert_equal(fields["cpu_core_0_clock_mhz"]["kind"], "cpufreq_core", "source map first core clock kind")
    assert_equal(fields["cpu_core_95_clock_mhz"]["path"], "/sys/devices/system/cpu/cpu95/cpufreq/scaling_cur_freq", "source map last core clock path")

    assert_equal(len(source_map["gpu_index_map"]), 4, "source map GPU count")
    assert_equal([entry["slot"] for entry in source_map["gpu_index_map"]], ["0000:75:00.0", "0000:76:00.0", "0000:06:00.0", "0000:07:00.0"], "source map GPU slots")
    assert_equal(fields["gpu_0_temp_core_c"]["kind"], "nvidia_smi", "source map GPU temp NVML/NVIDIA SMI source")
    assert_equal(fields["gpu_0_power_w"]["query_field"], "power.draw", "source map GPU power query field")
    assert_equal(fields["gpu_0_clock_mhz"]["query_field"], "clocks.current.graphics", "source map GPU clock query field")
    assert_equal(fields["gpu_0_vram_used_gb"]["query_field"], "memory.used", "source map GPU VRAM query field")

    assert_true(capabilities["cpu_temp_c"]["available"], "capability CPU temp available")
    assert_equal(capabilities["cpu_temp_c"]["source"], fields["cpu_temp_c"]["source"], "capability CPU temp source mirror")
    assert_equal(
        capabilities["cpu_temp_c"]["thresholds"],
        {"derived_from_hardware": False, "fail_c": 100.0, "source": "suite_default", "warn_c": 95.0},
        "capability CPU temp thresholds",
    )
    assert_true(capabilities["cpu_power_w"]["available"], "capability CPU power available")
    assert_true(not capabilities["cpu_power_w"]["permission_issue"], "capability CPU power permission status")
    assert_equal(capabilities["cpu_power_w"]["source"], fields["cpu_power_w"]["source"], "capability CPU power source mirror")
    assert_true(capabilities["cpu_clock_mhz"]["available"], "capability CPU clock available")
    assert_equal(capabilities["cpu_clock_mhz"]["source"], fields["cpu_clock_mhz"]["source"], "capability CPU clock source mirror")
    assert_equal(capabilities["cpu_core_clock_mhz"]["count"], 96, "capability CPU core clock count")
    assert_equal(capabilities["cpu_core_clock_mhz"]["classification"]["logical_count"], 96, "capability CPU logical count")
    assert_equal(capabilities["cpu_core_clock_mhz"]["classification"]["physical_count"], 48, "capability CPU physical count")
    assert_equal(capabilities["cpu_core_clock_mhz"]["classification"]["p_core_count"], 48, "capability CPU P-core count")
    assert_equal(capabilities["cpu_core_clock_mhz"]["classification"]["e_core_count"], 0, "capability CPU E-core count")

    assert_true(not capabilities["memory_temp_c"]["available"], "capability memory temp unavailable")
    assert_true(not capabilities["storage_temp_c"]["available"], "capability storage temp unavailable")
    assert_true(capabilities["memory_used_gb"]["available"], "capability memory used available")
    assert_equal(capabilities["memory_used_gb"]["source"], "/proc/meminfo", "capability memory used source")
    assert_true(capabilities["gpu_temp_c"]["available"], "capability GPU temp available")
    assert_equal(capabilities["gpu_temp_c"]["count"], 4, "capability GPU temp count")
    assert_equal(capabilities["gpu_power_w"]["count"], 4, "capability GPU power count")
    assert_equal(capabilities["gpu_clock_mhz"]["count"], 4, "capability GPU clock count")
    assert_equal(capabilities["gpu_vram_used_gb"]["count"], 4, "capability GPU VRAM count")
    assert_true(not capabilities["gpu_memory_temp_c"]["available"], "capability GPU memory temp unavailable")
    assert_equal(capabilities["gpu_memory_temp_c"]["source"], "not found", "capability GPU memory temp source")

    gpu_matrix = capabilities["gpu_telemetry_by_gpu"]
    assert_true(gpu_matrix["available"], "capability per-GPU matrix available")
    assert_equal(gpu_matrix["source"], "per-gpu telemetry source matrix", "capability per-GPU matrix source")
    assert_equal([gpu["slot"] for gpu in gpu_matrix["gpus"]], ["0000:75:00.0", "0000:76:00.0"], "trimmed capability GPU matrix slots")
    assert_true(gpu_matrix["gpus"][0]["metrics"]["temperature"]["available"], "capability matrix GPU temperature")
    assert_true(gpu_matrix["gpus"][0]["metrics"]["power"]["available"], "capability matrix GPU power")
    assert_true(not gpu_matrix["gpus"][0]["metrics"]["memory_temperature"]["available"], "capability matrix missing memory temperature")
    assert_equal(gpu_matrix["gpus"][0]["metrics"]["temperature"]["kind"], "nvidia_smi", "capability matrix GPU source kind")


def test_telemetry_sensor_io_helpers() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        hwmon = root / "hwmon0"
        hwmon.mkdir()
        temp_path = hwmon / "temp1_input"
        temp_path.write_text("65000", encoding="utf-8")
        (hwmon / "temp1_label").write_text("edge", encoding="utf-8")
        (hwmon / "temp1_max").write_text("90000", encoding="utf-8")
        (hwmon / "temp1_crit").write_text("100000", encoding="utf-8")
        assert_equal(safe_read_text(temp_path), "65000", "sensor IO safe read")
        assert_equal(telemetry_sensor_label(temp_path), "edge", "sensor IO label read")
        assert_equal(read_temp_limit_c(hwmon / "temp1_crit"), 100.0, "sensor IO temp limit")
        assert_equal(read_hwmon_temp_limit(temp_path, "max"), 90.0, "sensor IO hwmon max limit")
        assert_equal(hwmon_temp_thresholds(temp_path), (90.0, 100.0, "hwmon_limit"), "sensor IO hwmon thresholds")

        thermal_zone = root / "thermal_zone0"
        thermal_zone.mkdir()
        (thermal_zone / "trip_point_0_type").write_text("passive", encoding="utf-8")
        (thermal_zone / "trip_point_0_temp").write_text("85000", encoding="utf-8")
        (thermal_zone / "trip_point_1_type").write_text("critical", encoding="utf-8")
        (thermal_zone / "trip_point_1_temp").write_text("95000", encoding="utf-8")
        assert_equal(
            thermal_zone_thresholds(thermal_zone),
            (85.0, 95.0, "thermal_zone_trip"),
            "sensor IO thermal zone thresholds",
        )


def test_telemetry_device_helpers() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        hwmon_root = root / "hwmon"
        nic_hwmon = hwmon_root / "hwmon4"
        board_hwmon = hwmon_root / "hwmon6"
        wifi_hwmon = hwmon_root / "hwmon11"
        ath_hwmon = hwmon_root / "hwmon12"
        other_hwmon = hwmon_root / "hwmon5"
        nic_hwmon.mkdir(parents=True)
        board_hwmon.mkdir(parents=True)
        wifi_hwmon.mkdir(parents=True)
        ath_hwmon.mkdir(parents=True)
        other_hwmon.mkdir(parents=True)
        (nic_hwmon / "name").write_text("r8169_0_e00:00", encoding="utf-8")
        (nic_hwmon / "temp1_input").write_text("35000", encoding="utf-8")
        (board_hwmon / "name").write_text("gigabyte_wmi", encoding="utf-8")
        (board_hwmon / "temp1_input").write_text("27000", encoding="utf-8")
        (board_hwmon / "temp2_input").write_text("41000", encoding="utf-8")
        (wifi_hwmon / "name").write_text("iwlwifi_1", encoding="utf-8")
        (wifi_hwmon / "temp1_input").write_text("23000", encoding="utf-8")
        (ath_hwmon / "name").write_text("ath11k_hwmon-pci-40100", encoding="utf-8")
        (ath_hwmon / "temp1_input").write_text("45000", encoding="utf-8")
        (other_hwmon / "name").write_text("unknown", encoding="utf-8")
        (other_hwmon / "temp1_input").write_text("99000", encoding="utf-8")

        sources = discover_nic_temp_sources(hwmon_root=hwmon_root)
        assert_equal(len(sources), 1, "NIC telemetry source count")
        assert_equal(sources[0]["key"], "nic_0_temp_c", "NIC telemetry raw key")
        assert_equal(sources[0]["kind"], "nic_temp", "NIC telemetry source kind")
        assert_true(sources[0]["evidence_only"], "NIC telemetry evidence-only marker")
        assert_equal(
            read_device_temps(sources, read_temperature=lambda path: 35.0 if path.name == "temp1_input" else None),
            {"nic_0_temp_c": 35.0},
            "NIC telemetry value reader",
        )
        assert_equal(discover_nic_temp_sources(hwmon_root=other_hwmon), [], "NIC telemetry absent cleanly")
        board_sources = discover_board_temp_sources(hwmon_root=hwmon_root)
        assert_equal(len(board_sources), 2, "board telemetry source count")
        assert_equal(board_sources[0]["key"], "board_0_temp_c", "board telemetry raw key")
        assert_equal(board_sources[0]["kind"], "board_temp", "board telemetry source kind")
        assert_true(board_sources[0]["evidence_only"], "board telemetry evidence-only marker")
        assert_equal(
            read_device_temps(
                board_sources,
                read_temperature=lambda path: 27.0 if path.name == "temp1_input" else 41.0,
            ),
            {"board_0_temp_c": 27.0, "board_1_temp_c": 41.0},
            "board telemetry value reader",
        )
        assert_equal(discover_board_temp_sources(hwmon_root=other_hwmon), [], "board telemetry absent cleanly")
        wifi_sources = discover_wifi_temp_sources(hwmon_root=hwmon_root)
        assert_equal(len(wifi_sources), 2, "Wi-Fi telemetry source count")
        assert_equal(wifi_sources[0]["key"], "wifi_0_temp_c", "Wi-Fi telemetry raw key")
        assert_equal(wifi_sources[0]["kind"], "wifi_temp", "Wi-Fi telemetry source kind")
        assert_true(wifi_sources[0]["evidence_only"], "Wi-Fi telemetry evidence-only marker")
        assert_equal(wifi_sources[1]["device_name"], "ath11k_hwmon-pci-40100", "ath11k Wi-Fi telemetry device name")
        assert_equal(
            read_device_temps(
                wifi_sources,
                read_temperature=lambda path: 23.0 if "hwmon11" in str(path) else 45.0 if "hwmon12" in str(path) else None,
            ),
            {"wifi_0_temp_c": 23.0, "wifi_1_temp_c": 45.0},
            "Wi-Fi telemetry value reader",
        )
        assert_equal(discover_wifi_temp_sources(hwmon_root=other_hwmon), [], "Wi-Fi telemetry absent cleanly")


def test_telemetry_nvidia_helpers() -> None:
    calls: list[list[str]] = []
    original_run = lvs_telemetry_nvidia.subprocess.run

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        query_arg = next((part for part in cmd if str(part).startswith("--query-gpu=")), "")
        fields = str(query_arg).removeprefix("--query-gpu=").split(",")
        if "uuid" in fields:
            return SimpleNamespace(
                returncode=0,
                stdout="0, 0000:01:00.0, GPU-abc, NVIDIA GeForce RTX 3080, 555.55, 10240\n",
            )
        if any(field.startswith("clocks_event_reasons.") for field in fields):
            values = []
            for field in fields[1:]:
                values.append("Active" if field in {"clocks_event_reasons.sw_power_cap", "clocks_event_reasons.hw_thermal_slowdown"} else "Not Active")
            return SimpleNamespace(returncode=0, stdout=f"0000:01:00.0, {', '.join(values)}\n")
        return SimpleNamespace(
            returncode=0,
            stdout="0000:01:00.0, 65, 125.5, 1800, 9501, 78, 12, 9000, 44, 124.5\n",
        )

    try:
        lvs_telemetry_nvidia.subprocess.run = fake_run
        command_exists = lambda name: name == "nvidia-smi"
        command_env = lambda: {"PATH": "/usr/bin"}
        gpus = discover_nvidia_smi_gpus(command_exists, command_env)
        assert_equal(gpus[0]["slot"], "0000:01:00.0", "NVIDIA discovery normalizes slot")
        assert_equal(gpus[0]["uuid"], "GPU-abc", "NVIDIA discovery keeps UUID")
        assert_equal(gpus[0]["memory_mb"], 10240.0, "NVIDIA discovery memory total")
        assert_equal(
            [field["query_field"] for field in gpus[0]["clock_event_reason_fields"]],
            [field for _metric, field, _label in NVIDIA_CLOCK_EVENT_REASON_FIELDS],
            "NVIDIA discovery keeps supported clock event reason fields",
        )
        snapshot = read_nvidia_smi_gpu_metrics(
            [
                {"kind": "nvidia_smi", "metric": "temp_core_c"},
                {"kind": "nvidia_smi", "metric": "power_w"},
                {"kind": "nvidia_smi", "metric": "vram_used_gb"},
                {"kind": "nvidia_smi", "metric": "fan_percent"},
                {"kind": "nvidia_smi", "metric": "throttle_sw_power_cap"},
                {"kind": "nvidia_smi", "metric": "throttle_hw_thermal"},
                {"kind": "nvidia_smi", "metric": "throttle_idle"},
            ],
            command_env,
        )
        values = snapshot["0000:01:00.0"]
        assert_equal(values["temp_core_c"], 65.0, "NVIDIA telemetry core temp")
        assert_equal(values["power_w"], 125.5, "NVIDIA telemetry instant power")
        assert_equal(values["busy_percent"], 78.0, "NVIDIA telemetry busy")
        assert_equal(values["vram_used_gb"], 8.79, "NVIDIA telemetry VRAM MiB to GiB")
        assert_equal(values["fan_percent"], 44.0, "NVIDIA telemetry fan percent")
        assert_equal(values["throttle_sw_power_cap"], 1.0, "NVIDIA telemetry SW power cap event active")
        assert_equal(values["throttle_hw_thermal"], 1.0, "NVIDIA telemetry HW thermal event active")
        assert_equal(values["throttle_idle"], 0.0, "NVIDIA telemetry idle event inactive")
        assert_equal(parse_nvidia_active_flag("Active"), 1.0, "NVIDIA active flag parsing active")
        assert_equal(parse_nvidia_active_flag("Not Active"), 0.0, "NVIDIA active flag parsing inactive")
        assert_equal(parse_nvidia_active_flag("[Not Supported]"), None, "NVIDIA active flag unsupported absent")
        assert_true(any("power.draw.average" in " ".join(call) for call in calls), "NVIDIA telemetry asks for average power fallback field")
    finally:
        lvs_telemetry_nvidia.subprocess.run = original_run


def test_telemetry_nvidia_event_reasons_absent_when_unsupported() -> None:
    original_run = lvs_telemetry_nvidia.subprocess.run

    def fake_run(cmd, **_kwargs):
        query_arg = next((part for part in cmd if str(part).startswith("--query-gpu=")), "")
        fields = str(query_arg).removeprefix("--query-gpu=").split(",")
        if "uuid" in fields:
            return SimpleNamespace(
                returncode=0,
                stdout="0, 0000:01:00.0, GPU-abc, NVIDIA GeForce RTX 3080, 555.55, 10240\n",
            )
        if any(field.startswith("clocks_event_reasons.") for field in fields):
            return SimpleNamespace(returncode=1, stdout="", stderr="Unknown query field")
        return SimpleNamespace(
            returncode=0,
            stdout="0000:01:00.0, 65, 125.5, 1800, 9501, 78, 12, 9000, 44, 124.5\n",
        )

    try:
        lvs_telemetry_nvidia.subprocess.run = fake_run
        command_env = lambda: {"PATH": "/usr/bin"}
        gpus = discover_nvidia_smi_gpus(lambda name: name == "nvidia-smi", command_env)
        assert_equal(gpus[0]["clock_event_reason_fields"], [], "NVIDIA unsupported event reasons are absent from discovery")
        snapshot = read_nvidia_smi_gpu_metrics(
            [
                {"kind": "nvidia_smi", "metric": "temp_core_c"},
                {"kind": "nvidia_smi", "metric": "fan_percent"},
                {"kind": "nvidia_smi", "metric": "throttle_hw_thermal"},
            ],
            command_env,
        )
        values = snapshot["0000:01:00.0"]
        assert_equal(values["temp_core_c"], 65.0, "NVIDIA unsupported event reasons preserve temp")
        assert_equal(values["fan_percent"], 44.0, "NVIDIA unsupported event reasons preserve fan")
        assert_true("throttle_hw_thermal" not in values, "NVIDIA unsupported event reason value absent cleanly")
    finally:
        lvs_telemetry_nvidia.subprocess.run = original_run


def test_telemetry_intel_helpers() -> None:
    text = 'noise {"engines":{"Render/3D":{"busy":25.0}}} {"engines":{"Compute":{"busy":75.0}}}'
    assert_equal(
        intel_gpu_top_metrics_from_text(text),
        {"busy_percent": 75.0},
        "Intel telemetry helper uses latest parseable snapshot",
    )
    sources = [
        {"kind": "intel_gpu_top", "gpu_index": 2, "metric": "busy_percent"},
        {"kind": "gpu_sensor", "gpu_index": 2, "metric": "temp_core_c"},
    ]

    original_attempt = lvs_telemetry_intel.intel_gpu_top_json_sample_attempt
    try:
        lvs_telemetry_intel.intel_gpu_top_json_sample_attempt = lambda **_kwargs: {
            "stdout": '{"engines":{"Render/3D":{"busy":33.5}}}',
        }
        values = read_intel_gpu_top_metrics(
            sources,
            command_exists=lambda command: command == "intel_gpu_top",
            command_env=lambda: {"PATH": "/usr/bin"},
        )
        assert_equal(values, {2: {"busy_percent": 33.5}}, "Intel telemetry helper maps metrics to Intel source GPU index")
    finally:
        lvs_telemetry_intel.intel_gpu_top_json_sample_attempt = original_attempt


def test_telemetry_gpu_helpers() -> None:
    assert_equal(gpu_temp_metric("edge", "amdgpu"), "temp_core_c", "GPU temp edge metric")
    assert_equal(gpu_temp_metric("junction", "amdgpu"), "temp_hotspot_c", "GPU temp hotspot metric")
    assert_equal(gpu_temp_metric("", "i915", Path("temp1_input")), "temp_core_c", "GPU temp unlabeled Intel metric")

    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        drm_root = root / "drm"
        hwmon_root = root / "hwmon"
        card = drm_root / "card0"
        device = card / "device"
        hwmon = device / "hwmon" / "hwmon0"
        hwmon.mkdir(parents=True)
        hwmon_root.mkdir()
        (device / "uevent").write_text(
            "PCI_SLOT_NAME=0000:05:00.0\nPCI_ID=1002:744C\nDRIVER=amdgpu\n",
            encoding="utf-8",
        )
        (device / "max_link_speed").write_text("16.0 GT/s", encoding="utf-8")
        (device / "current_link_speed").write_text("8.0 GT/s", encoding="utf-8")
        (device / "max_link_width").write_text("16", encoding="utf-8")
        (device / "current_link_width").write_text("8", encoding="utf-8")
        (hwmon / "name").write_text("amdgpu", encoding="utf-8")
        (hwmon / "temp1_input").write_text("65000", encoding="utf-8")
        (hwmon / "temp1_label").write_text("edge", encoding="utf-8")
        (hwmon / "temp1_crit").write_text("95000", encoding="utf-8")
        (hwmon / "power1_input").write_text("225000000", encoding="utf-8")
        (hwmon / "power1_label").write_text("PPT", encoding="utf-8")
        (hwmon / "in0_input").write_text("1329", encoding="utf-8")
        (hwmon / "in0_label").write_text("vddgfx", encoding="utf-8")
        (hwmon / "in1_input").write_text("1185", encoding="utf-8")
        (hwmon / "in1_label").write_text("vddnb", encoding="utf-8")
        (device / "pp_dpm_sclk").write_text("2: 2400Mhz *\n1: 1200Mhz", encoding="utf-8")
        (device / "gpu_busy_percent").write_text("87", encoding="utf-8")
        (device / "mem_info_vram_used").write_text(str(4 * 1024 ** 3), encoding="utf-8")

        def read_fixture(path: Path) -> str | None:
            try:
                return path.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                return None

        def label_fixture(path: Path) -> str:
            label_path = path.with_name(path.name.replace("_input", "_label").replace("_average", "_label"))
            return read_fixture(label_path) or ""

        discovered_cards = discover_gpu_cards_helper(drm_root)
        assert_equal(len(discovered_cards), 1, "GPU card discovery helper count")
        assert_equal(discovered_cards[0]["card"], "card0", "GPU card discovery helper card")
        assert_equal(discovered_cards[0]["slot"], "0000:05:00.0", "GPU card discovery helper slot")
        assert_equal(discovered_cards[0]["vendor"], "AMD", "GPU card discovery helper vendor")
        assert_equal(discovered_cards[0]["driver"], "amdgpu", "GPU card discovery helper driver")
        assert_equal(discovered_cards[0]["gpu_index"], 0, "GPU card discovery helper index")
        assert_equal(
            discovered_cards[0]["pcie_link"]["CurrentLinkSpeed"],
            "8.0 GT/s",
            "GPU card discovery PCIe current link speed",
        )
        assert_equal(
            discovered_cards[0]["pcie_link"]["CurrentLinkWidth"],
            "8",
            "GPU card discovery PCIe current link width",
        )
        assert_equal(gpu_hwmon_dirs(card, read_fixture, hwmon_root), [hwmon], "GPU hwmon directory helper")
        sources = discover_gpu_sources_helper(
            read_fixture,
            label_fixture,
            lambda _path: (90.0, 95.0, "fixture"),
            command_exists=lambda _command: False,
            discover_nvidia_smi_gpus=lambda: [],
            intel_gpu_top_json_sample_metrics=lambda: {},
            drm_root=drm_root,
            hwmon_root=hwmon_root,
        )
        keys = {source["key"] for source in sources}
        assert_true("gpu_0_temp_core_c" in keys, "GPU source discovery temp key")
        assert_true("gpu_0_power_w" in keys, "GPU source discovery power key")
        assert_true("gpu_0_clock_mhz" in keys, "GPU source discovery clock key")
        assert_true("gpu_0_busy_percent" in keys, "GPU source discovery busy key")
        assert_true("gpu_0_vram_used_gb" in keys, "GPU source discovery VRAM key")
        assert_true("gpu_0_vddgfx_v" in keys, "GPU source discovery vddgfx voltage key")
        assert_true("gpu_0_vddnb_v" in keys, "GPU source discovery vddnb voltage key")
        assert_equal(gpu_voltage_metric("vddgfx"), "vddgfx_v", "GPU voltage vddgfx metric")
        assert_equal(gpu_voltage_metric("vddnb"), "vddnb_v", "GPU voltage vddnb metric")
        assert_equal(gpu_voltage_metric("12V"), None, "GPU voltage ignores unrelated rail")
        assert_equal(parse_voltage_text_v("1329"), 1.329, "GPU voltage millivolt parsing")
        assert_equal(parse_voltage_text_v("1.185"), 1.185, "GPU voltage volt parsing")
        assert_equal(read_gpu_clock(device / "pp_dpm_sclk", read_fixture), 2400.0, "GPU clock helper")
        values = read_gpu_values(sources, read_fixture, read_fixture, {}, {}, {}, 10.0)
        assert_equal(values["gpu_0_temp_core_c"], 65.0, "GPU read values temp")
        assert_equal(values["gpu_0_power_w"], 225.0, "GPU read values power")
        assert_equal(values["gpu_0_clock_mhz"], 2400.0, "GPU read values clock")
        assert_equal(values["gpu_0_busy_percent"], 87.0, "GPU read values busy")
        assert_equal(values["gpu_0_vram_used_gb"], 4.0, "GPU read values VRAM")
        assert_equal(values["gpu_0_vddgfx_v"], 1.329, "GPU read values vddgfx voltage")
        assert_equal(values["gpu_0_vddnb_v"], 1.185, "GPU read values vddnb voltage")

        nvidia_sources = discover_gpu_sources_helper(
            read_fixture,
            label_fixture,
            lambda _path: (90.0, 95.0, "fixture"),
            command_exists=lambda _command: False,
            discover_nvidia_smi_gpus=lambda: [
                {
                    "slot": "0000:05:00.0",
                    "name": "NVIDIA Test",
                    "card": "card0",
                    "memory_temperature_c": 72.0,
                }
            ],
            intel_gpu_top_json_sample_metrics=lambda: {},
            drm_root=drm_root,
            hwmon_root=hwmon_root,
        )
        assert_true(
            any(source["kind"] == "nvidia_smi" and source["key"] == "gpu_0_temp_memory_c" for source in nvidia_sources),
            "GPU source discovery maps NVIDIA SMI to existing slot index",
        )
        assert_true(
            any(source["kind"] == "nvidia_smi" and source["key"] == "gpu_0_fan_percent" for source in nvidia_sources),
            "GPU source discovery maps NVIDIA fan speed",
        )
        nvidia_values = read_gpu_values(
            nvidia_sources,
            read_fixture,
            read_fixture,
            {},
            {"0000:05:00.0": {"fan_percent": 42.0, "temp_memory_c": 72.0}},
            {},
            10.0,
        )
        assert_equal(nvidia_values["gpu_0_fan_percent"], 42.0, "GPU read values NVIDIA fan percent")
        assert_equal(nvidia_values["gpu_0_temp_memory_c"], 72.0, "GPU read values NVIDIA memory temp")


def test_telemetry_sampling_helpers() -> None:
    assert_equal(parse_temperature_text("65000"), 65.0, "millidegree temperature parsing")
    assert_equal(parse_temperature_text("65.5"), 65.5, "degree temperature parsing")
    assert_equal(parse_temperature_text("250000"), None, "temperature upper bound")
    assert_equal(parse_power_text_w("185000000", max_watts=500.0), 185.0, "microwatt power parsing")
    assert_equal(parse_power_text_w("185.25", max_watts=500.0), 185.25, "watt power parsing")
    assert_equal(parse_percent_text("101"), None, "percent upper bound")
    assert_equal(parse_optional_float("[Not Supported]", 100.0), None, "unsupported optional float")
    assert_equal(parse_vram_used_gb_from_bytes_text(str(3 * 1024 ** 3)), 3.0, "VRAM bytes to GB")
    assert_equal(parse_mb_to_gb("12288"), 12.0, "MiB to GiB")
    assert_equal(parse_gpu_clock_text("2: 2400Mhz *\n1: 1200Mhz"), 2400.0, "AMD pp_dpm selected clock")
    assert_equal(parse_gpu_clock_text("2400000"), 2400.0, "raw kHz clock")
    objects = json_objects_from_text('noise {"engines":{"Render/3D":{"busy": "33.5%"}}} {"value": 2}')
    assert_equal(len(objects), 2, "JSON object stream parsing")
    assert_equal(metric_number({"busy": "44.25 %"}), 44.25, "metric number from dict")
    assert_true(any(key.endswith("busy") for key, _ in walk_json_numbers({"engine": {"busy": 12.5}})), "walk JSON numbers")
    assert_equal(
        parse_intel_gpu_top_snapshot({"engines": {"Render/3D": {"busy": 55.0}, "Compute": {"busy": 60.0}}}),
        {"busy_percent": 100.0},
        "Intel engine busy caps at 100",
    )
    assert_equal(
        parse_intel_gpu_top_snapshot({"root": {"rcs_busy": 42.0}, "clients": {"busy": 99.0}}),
        {"busy_percent": 42.0},
        "Intel fallback busy skips client counters",
    )


def test_telemetry_sample_csv_helpers() -> None:
    samples = [
        Sample(1.5, {"gpu_0_temp_core_c": 70.0}),
        Sample(2.5, {"cpu_temp_c": 55.0, "gpu_0_temp_core_c": None}),
    ]
    assert_equal(
        telemetry_csv_fieldnames(samples),
        ["timestamp", "cpu_temp_c", "gpu_0_temp_core_c"],
        "telemetry CSV field ordering",
    )
    assert_equal(
        telemetry_sample_row(samples[0]),
        {"timestamp": 1.5, "gpu_0_temp_core_c": 70.0},
        "telemetry sample row shape",
    )
    with TemporaryDirectory(dir="/tmp") as tmp:
        csv_path = Path(tmp) / "raw_telemetry.csv"
        write_telemetry_csv(samples, csv_path)
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        assert_equal(lines[0], "timestamp,cpu_temp_c,gpu_0_temp_core_c", "telemetry CSV header")
        assert_equal(lines[1], "1.5,,70.0", "telemetry CSV sparse row")
        assert_equal(lines[2], "2.5,55.0,", "telemetry CSV None row")


def test_telemetry_memory_helpers() -> None:
    labels = ["DIMM_B2 Temp", "DDR_A1 Temp", "DIMM_A2 Temp", "DDR_B1 Temp"]
    ordered = sorted(labels, key=ipmi_memory_sensor_sort_key)
    assert_equal(ordered, ["DDR_A1 Temp", "DDR_B1 Temp", "DIMM_A2 Temp", "DIMM_B2 Temp"], "IPMI DIMM sort order")
    assert_true(looks_like_ipmi_memory_temperature("DDR_A1 Temp"), "DDR IPMI memory temp label")
    assert_true(looks_like_ipmi_memory_temperature("DIMM B2"), "DIMM IPMI memory temp label")
    assert_true(looks_like_ipmi_memory_temperature("DRAM Temp"), "DRAM IPMI memory temp label")
    assert_true(not looks_like_ipmi_memory_temperature("GPU Memory Temp"), "GPU memory temp is not DIMM temp")
    assert_true(not looks_like_ipmi_memory_temperature("VRM DIMM Rail"), "VRM DIMM rail is not DIMM temp")
    assert_true(not looks_like_ipmi_memory_temperature("System Ambient"), "ambient temp is not DIMM temp")
    ipmi_text = """
DDR_A1 Temp | 42.000 | degrees C | ok
GPU Memory Temp | 70.000 | degrees C | ok
Bad DIMM | na | degrees C | ns
DIMM_B2 Temp | 43.500 | C | ok
"""
    ipmi_values = parse_ipmi_sensor_temperatures(ipmi_text)
    assert_equal(ipmi_values["DDR_A1 Temp"], 42.0, "IPMI memory temperature parse")
    assert_equal(ipmi_values["DIMM_B2 Temp"], 43.5, "IPMI C unit parse")
    original_run = lvs_telemetry_memory.subprocess.run
    calls: list[dict[str, object]] = []

    def fake_ipmi_run(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        return SimpleNamespace(returncode=0, stdout=ipmi_text)

    try:
        lvs_telemetry_memory.subprocess.run = fake_ipmi_run
        sensor_text = run_ipmitool_sensor_text(
            command_exists=lambda command: command == "ipmitool",
            command_env=lambda: {"PATH": "/usr/bin"},
        )
        assert_true("DDR_A1 Temp" in sensor_text, "IPMI command helper returns sensor text")
        assert_equal(calls[0]["command"], ["ipmitool", "sensor"], "IPMI command helper command")
        assert_equal(
            read_ipmi_sensor_temperatures(
                command_exists=lambda command: command == "ipmitool",
                command_env=lambda: {"PATH": "/usr/bin"},
            )["DIMM_B2 Temp"],
            43.5,
            "IPMI command helper parses temperatures",
        )
    finally:
        lvs_telemetry_memory.subprocess.run = original_run

    cache_reads = 0

    def read_cached_ipmi() -> dict[str, float]:
        nonlocal cache_reads
        cache_reads += 1
        return {"DDR_A1 Temp": 42.0}

    cached_values, cache = cached_ipmi_sensor_temperatures(None, 10.0, read_cached_ipmi)
    assert_equal(cached_values, {"DDR_A1 Temp": 42.0}, "IPMI cache first read")
    cached_values, cache = cached_ipmi_sensor_temperatures(cache, 12.0, read_cached_ipmi)
    assert_equal(cache_reads, 1, "IPMI cache reuses fresh values")
    assert_equal(cached_values, {"DDR_A1 Temp": 42.0}, "IPMI cache value copy")
    cached_values, cache = cached_ipmi_sensor_temperatures(cache, 20.0, read_cached_ipmi, force=True)
    assert_equal(cache_reads, 2, "IPMI cache force refresh")
    with TemporaryDirectory(dir="/tmp") as tmp:
        empty_hwmon_root = Path(tmp) / "empty_hwmon"
        empty_hwmon_root.mkdir()
        ipmi_sources = discover_memory_temp_sources(hwmon_root=empty_hwmon_root, ipmi_temperatures=ipmi_values)
        assert_equal([source["sensor_id"] for source in ipmi_sources], ["DDR_A1 Temp", "DIMM_B2 Temp"], "IPMI memory source filtering")
        assert_equal(ipmi_sources[0]["key"], "memory_module_0_temp_c", "IPMI memory source key")
        fallback_sources = discover_memory_temp_sources_with_ipmi(
            read_text=lambda path: None,
            command_exists=lambda command: command == "ipmitool",
            local_ipmi_available=lambda: True,
            read_ipmi_temperatures_cached=lambda: ipmi_values,
        )
        assert_equal(
            [source["sensor_id"] for source in fallback_sources],
            ["DDR_A1 Temp", "DIMM_B2 Temp"],
            "IPMI fallback memory source discovery",
        )
        memory_values = read_memory_temps(
            [
                {"kind": "memory_temp", "key": "memory_module_0_temp_c", "path": "/memory/temp0"},
                {"kind": "ipmi_memory_temp", "key": "memory_module_1_temp_c", "sensor_id": "DIMM_B2 Temp"},
            ],
            read_temperature=lambda path: 40.0 if str(path) == "/memory/temp0" else None,
            read_ipmi_temperatures_cached=lambda: ipmi_values,
        )
        assert_equal(
            memory_values,
            {"memory_module_0_temp_c": 40.0, "memory_module_1_temp_c": 43.5},
            "memory temp reader combines SPD and IPMI sources",
        )
        hwmon_root = Path(tmp) / "hwmon"
        hwmon = hwmon_root / "hwmon0"
        hwmon.mkdir(parents=True)
        (hwmon / "name").write_text("spd5118", encoding="utf-8")
        (hwmon / "temp1_input").write_text("40000", encoding="utf-8")
        (hwmon / "temp2_input").write_text("41000", encoding="utf-8")
        spd_sources = discover_memory_temp_sources(
            hwmon_root=hwmon_root,
            ipmi_temperatures={"DDR_A1 Temp": 42.0},
        )
        assert_equal(len(spd_sources), 2, "SPD5118 memory source count")
        assert_equal(spd_sources[0]["kind"], "memory_temp", "SPD5118 preferred over IPMI")
        assert_equal(spd_sources[1]["key"], "memory_module_1_temp_c", "SPD5118 memory source key")


def test_telemetry_cpu_helpers() -> None:
    assert_true(score_cpu_temp_source("k10temp", "Tctl") > score_cpu_temp_source("acpitz", "temp1"), "CPU temp source scoring")
    assert_true(score_thermal_zone("x86_pkg_temp") > score_thermal_zone("acpitz"), "thermal zone scoring")
    assert_true(score_cpu_power_source("zenpower", "CPU Package Power") > score_cpu_power_source("amdgpu", "PPT"), "CPU power source scoring")
    assert_true(score_cpu_power_source("amd_hsmp_hwmon", "") > score_cpu_power_source("amdgpu", "PPT"), "AMD HSMP CPU power source scoring")
    assert_true(score_rapl_source("package-0") > score_rapl_source("core"), "RAPL package scoring")
    assert_true(score_energy_source("zenergy", "Esocket") > score_energy_source("zenergy", "Ecore0"), "energy socket scoring")
    assert_equal(parse_explicit_core_type("performance"), "P", "explicit performance core")
    assert_equal(parse_explicit_core_type("c-core"), "E", "explicit compact core")
    assert_equal(parse_explicit_core_type("1"), "", "numeric core type ignored")
    assert_equal(parse_cpu_list("0-3,8,10-9,bad"), [0, 1, 2, 3, 8, 9, 10], "CPU list parsing")
    assert_equal(cpu_index_from_name("cpu17"), 17, "CPU index parse")
    assert_equal(cpu_index_from_name("cpux"), -1, "invalid CPU index")
    assert_equal(read_cpu_sysfs_int(Path("/unused"), lambda _path: "0x10"), 16, "CPU sysfs int parsing")
    fixture_values = {
        "/cpu/temp0": "65000",
        "/cpu/temp1": "61000",
        "/cpu/power0": "125000000",
        "/cpu/energy0": "100000000",
        "/cpu/clock0": "3200000",
        "/cpu/clock1": "3100000",
        "/proc/cpuinfo": "cpu MHz\t\t: 2999.500\ncpu MHz\t\t: 3000.500\n",
    }
    def read_cpu_fixture(path: Path) -> str | None:
        return fixture_values.get(str(path))
    assert_equal(read_temperature_path(Path("/cpu/temp0"), read_cpu_fixture), 65.0, "CPU temp path helper")
    assert_equal(
        read_cpu_package_temps(
            [
                {"key": "cpu_package_0_temp_c", "path": "/cpu/temp0"},
                {"key": "cpu_package_1_temp_c", "path": "/cpu/temp1"},
            ],
            read_cpu_fixture,
        ),
        {"cpu_package_0_temp_c": 65.0, "cpu_package_1_temp_c": 61.0},
        "CPU package temp helper",
    )
    assert_equal(
        read_cpu_temp([{"path": "/cpu/temp1"}], read_cpu_fixture, {"cpu_package_0_temp_c": 65.0}),
        65.0,
        "CPU aggregate temp prefers hottest package",
    )
    assert_equal(
        read_hwmon_power_source({"path": "/cpu/power0"}, read_cpu_fixture, max_watts=1000.0),
        125.0,
        "CPU hwmon power helper",
    )
    energy_state: dict[str, dict[str, float]] = {}
    energy_source = {"kind": "rapl", "path": "/cpu/energy0", "max_energy_range_uj": 1000000000}
    assert_equal(
        read_energy_power_source(energy_source, 1.0, energy_state, read_cpu_fixture, read_cpu_fixture, max_watts=1000.0),
        None,
        "CPU energy helper seeds state",
    )
    fixture_values["/cpu/energy0"] = "250000000"
    assert_equal(
        read_energy_power_source(energy_source, 2.0, energy_state, read_cpu_fixture, read_cpu_fixture, max_watts=1000.0),
        150.0,
        "CPU energy helper computes watts",
    )
    fixture_values["/cpu/energy0"] = "100000000"
    aggregate_state: dict[str, dict[str, float]] = {}
    aggregate_source = {
        "kind": "aggregate_energy",
        "sources": [
            {"kind": "rapl", "path": "/cpu/energy0", "package_id": 0, "max_energy_range_uj": 1000000000},
            {"kind": "hwmon", "path": "/cpu/power0", "package_id": 1},
        ],
    }
    assert_equal(read_cpu_power(aggregate_source, 1.0, aggregate_state, read_cpu_fixture, read_cpu_fixture), (125.0, {"cpu_package_1_power_w": 125.0}), "CPU aggregate power first sample")
    fixture_values["/cpu/energy0"] = "200000000"
    assert_equal(
        read_cpu_power(aggregate_source, 2.0, aggregate_state, read_cpu_fixture, read_cpu_fixture),
        (225.0, {"cpu_package_0_power_w": 100.0, "cpu_package_1_power_w": 125.0}),
        "CPU aggregate power helper keeps package values",
    )
    assert_equal(
        read_cpu_clock_mhz({"kind": "cpufreq", "paths": ["/cpu/clock0", "/cpu/clock1"]}, read_cpu_fixture),
        3150.0,
        "CPU clock helper averages cpufreq",
    )
    assert_equal(
        read_cpu_clock_mhz({"kind": "proc_cpuinfo", "path": "/proc/cpuinfo"}, read_cpu_fixture),
        3000.0,
        "CPU clock helper parses cpuinfo",
    )
    assert_equal(
        read_cpu_core_clocks(
            [
                {"key": "cpu_core_0_clock_mhz", "path": "/cpu/clock0"},
                {"key": "cpu_core_1_clock_mhz", "path": "/cpu/clock1"},
            ],
            read_cpu_fixture,
        ),
        {"cpu_core_0_clock_mhz": 3200.0, "cpu_core_1_clock_mhz": 3100.0},
        "CPU core clock helper",
    )
    topology = {0: {"package_id": 0}, 1: {"package_id": 1}}
    assert_equal(cpu_package_ids_from_topology(topology), [0, 1], "CPU package ids from topology")
    explicit_temp_source = {"kind": "hwmon", "label": "Package id 1", "path": "/sys/class/hwmon/hwmon1/temp1_input"}
    assert_equal(cpu_package_id_from_temp_source(explicit_temp_source), 1, "CPU package id from temp source")
    assigned_sources = assign_cpu_package_temp_sources(
        [
            {"kind": "hwmon", "hwmon_name": "k10temp", "label": "Tctl", "path": "/tmp/temp0"},
            {"kind": "hwmon", "hwmon_name": "k10temp", "label": "Tctl", "path": "/tmp/temp1"},
        ],
        topology,
    )
    assert_equal(
        [source["key"] for source in assigned_sources],
        ["cpu_package_0_temp_c", "cpu_package_1_temp_c"],
        "CPU package temp helper assigns implicit sources",
    )
    assert_equal(
        cpu_package_id_from_power_source({"label": "package-1", "path": "/sys/class/powercap/intel-rapl:1/energy_uj"}),
        "1",
        "CPU package id from power source label",
    )
    tiers = performance_tiers({"p0": 6000, "p1": 5900, "e0": 4200, "e1": 4150})
    assert_equal(len(tiers), 2, "performance tier grouping")
    assert_equal(set(tiers[0][1]), {"p0", "p1"}, "performance top tier keys")
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        cpu_root = root / "cpu"
        for cpu_index, package_id, core_id, capacity, core_type in (
            (0, 0, 0, 1024, "performance"),
            (1, 0, 1, 1024, "performance"),
            (2, 0, 2, 512, "efficient"),
            (3, 0, 3, 512, "efficient"),
        ):
            cpu_dir = cpu_root / f"cpu{cpu_index}"
            topology_dir = cpu_dir / "topology"
            cpufreq_dir = cpu_dir / "cpufreq"
            topology_dir.mkdir(parents=True)
            cpufreq_dir.mkdir()
            (topology_dir / "physical_package_id").write_text(str(package_id), encoding="utf-8")
            (topology_dir / "core_id").write_text(str(core_id), encoding="utf-8")
            (topology_dir / "thread_siblings_list").write_text(str(cpu_index), encoding="utf-8")
            (cpu_dir / "cpu_capacity").write_text(str(capacity), encoding="utf-8")
            (cpu_dir / "core_type").write_text(core_type, encoding="utf-8")
            (cpufreq_dir / "scaling_cur_freq").write_text("3200000", encoding="utf-8")
        topology = discover_cpu_core_topology(cpu_root)
        assert_equal(topology[0]["core_type"], "P", "topology explicit P-core")
        assert_equal(topology[2]["core_type"], "E", "topology explicit E-core")
        assert_equal(topology[3]["physical_core_index"], 3, "topology physical core index")
        summary = cpu_core_classification_summary_from_topology(topology)
        assert_equal(summary["p_core_count"], 2, "topology P-core summary")
        assert_equal(summary["e_core_count"], 2, "topology E-core summary")
        clock_sources = discover_cpu_core_clock_sources(topology, cpu_root)
        assert_equal(len(clock_sources), 4, "CPU core clock source count")
        assert_equal(clock_sources[2]["label"], "E-Core 2 Clock", "CPU core clock source label")
        clock_source = discover_cpu_clock_source(cpu_root=cpu_root, read_text=lambda path: path.read_text(encoding="utf-8", errors="ignore").strip() if path.exists() else None)
        assert_equal(clock_source["kind"], "cpufreq", "CPU average clock source discovers cpufreq")
        assert_equal(len(clock_source["paths"]), 4, "CPU average clock source path count")
        cpuinfo_path = root / "cpuinfo"
        cpuinfo_path.write_text("processor\t: 0\ncpu MHz\t\t: 3200.000\n", encoding="utf-8")
        assert_equal(
            discover_cpu_clock_source(
                cpu_root=root / "missing_cpu_root",
                proc_cpuinfo_path=cpuinfo_path,
                read_text=lambda path: path.read_text(encoding="utf-8", errors="ignore").strip() if path.exists() else None,
            ),
            {"kind": "proc_cpuinfo", "path": str(cpuinfo_path), "label": "cpu MHz"},
            "CPU average clock source falls back to cpuinfo",
        )
        hwmon_root = root / "hwmon"
        cpu_hwmon = hwmon_root / "hwmon0"
        gpu_hwmon = hwmon_root / "hwmon1" / "device" / "drm" / "card0"
        cpu_hwmon.mkdir(parents=True)
        gpu_hwmon.mkdir(parents=True)
        (cpu_hwmon / "name").write_text("k10temp", encoding="utf-8")
        (cpu_hwmon / "temp1_input").write_text("64000", encoding="utf-8")
        (cpu_hwmon / "temp1_label").write_text("Tctl", encoding="utf-8")
        (cpu_hwmon / "power1_input").write_text("125000000", encoding="utf-8")
        (cpu_hwmon / "power1_label").write_text("CPU Package Power", encoding="utf-8")
        (cpu_hwmon / "energy1_input").write_text("1000000", encoding="utf-8")
        (cpu_hwmon / "energy1_label").write_text("CPU Package Energy", encoding="utf-8")
        (cpu_hwmon / "energy1_max").write_text("1000000000", encoding="utf-8")
        (gpu_hwmon / "name").write_text("amdgpu", encoding="utf-8")
        (gpu_hwmon / "power1_input").write_text("250000000", encoding="utf-8")
        thermal_root = root / "thermal"
        thermal_zone = thermal_root / "thermal_zone0"
        thermal_zone.mkdir(parents=True)
        (thermal_zone / "type").write_text("x86_pkg_temp", encoding="utf-8")
        (thermal_zone / "temp").write_text("66000", encoding="utf-8")
        cpu_temp_sources = discover_cpu_temp_sources(
            hwmon_root=hwmon_root,
            thermal_root=thermal_root,
            sensor_label=lambda path: (path.with_name(path.name.replace("_input", "_label")).read_text(encoding="utf-8") if path.with_name(path.name.replace("_input", "_label")).exists() else ""),
            hwmon_temp_thresholds=lambda _path: (90.0, 100.0, "fixture"),
            thermal_zone_thresholds=lambda _path: (91.0, 101.0, "fixture-zone"),
        )
        hwmon_temp_source = next(source for source in cpu_temp_sources if source["kind"] == "hwmon")
        assert_equal(hwmon_temp_source["label"], "Tctl", "CPU temp discovery hwmon label")
        assert_equal(hwmon_temp_source["warn_threshold_c"], 90.0, "CPU temp discovery threshold callback")
        assert_equal(cpu_temp_sources[0]["label"], "x86_pkg_temp", "CPU temp discovery preserves scoring order")
        powercap_root = root / "powercap"
        readable_rapl = powercap_root / "intel-rapl:0"
        unreadable_rapl = powercap_root / "intel-rapl:1"
        readable_rapl.mkdir(parents=True)
        unreadable_rapl.mkdir(parents=True)
        (readable_rapl / "name").write_text("package-0", encoding="utf-8")
        (readable_rapl / "energy_uj").write_text("1000000", encoding="utf-8")
        (readable_rapl / "max_energy_range_uj").write_text("1000000000", encoding="utf-8")
        (unreadable_rapl / "name").write_text("package-1", encoding="utf-8")
        (unreadable_rapl / "energy_uj").write_text("2000000", encoding="utf-8")
        (unreadable_rapl / "max_energy_range_uj").write_text("1000000000", encoding="utf-8")
        unreadable_energy_path = unreadable_rapl / "energy_uj"
        def read_power_fixture(path: Path) -> str | None:
            if path == unreadable_energy_path:
                return None
            try:
                return path.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                return None
        power_sources, unreadable_power_sources = discover_cpu_power_candidates(
            hwmon_root=hwmon_root,
            powercap_roots=[powercap_root],
            read_text=read_power_fixture,
            sensor_label=lambda path: (path.with_name(path.name.replace("_input", "_label").replace("_average", "_label")).read_text(encoding="utf-8") if path.with_name(path.name.replace("_input", "_label").replace("_average", "_label")).exists() else ""),
        )
        assert_true(any(source["kind"] == "hwmon" for source in power_sources), "CPU power hwmon candidate")
        assert_true(any(source["kind"] == "rapl" and source["label"] == "package-0" for source in power_sources), "CPU power readable RAPL candidate")
        assert_equal(unreadable_power_sources[0]["label"], "package-1", "CPU power unreadable RAPL candidate")
        assert_true(not any("amdgpu" in str(source.get("label", "")).lower() for source in power_sources), "CPU power skips DRM hwmon")
        package_0 = root / "intel-rapl:0" / "energy_uj"
        package_1 = root / "intel-rapl:1" / "energy_uj"
        package_0.parent.mkdir()
        package_1.parent.mkdir()
        package_0.write_text("100000000", encoding="utf-8")
        package_1.write_text("200000000", encoding="utf-8")
        mixed_sources_for_helper = [{"kind": "rapl", "label": "package-0", "path": str(package_0), "score": 120}]
        add_privileged_cpu_power_sources(
            mixed_sources_for_helper,
            [{"kind": "rapl", "label": "package-1", "path": str(package_1), "score": 120}],
            lambda path: Path(path).read_text(encoding="utf-8", errors="ignore").strip(),
            privileged_helper_enabled=True,
        )
        assert_equal(len(mixed_sources_for_helper), 2, "CPU privileged power helper adds sudo source")
        assert_equal(mixed_sources_for_helper[1]["kind"], "sudo_rapl", "CPU privileged power helper sudo kind")
        selected_power_source, selected_unreadable = discover_cpu_power_source(
            hwmon_root=hwmon_root,
            powercap_roots=[powercap_root],
            read_text=read_power_fixture,
            sensor_label=lambda path: (path.with_name(path.name.replace("_input", "_label").replace("_average", "_label")).read_text(encoding="utf-8") if path.with_name(path.name.replace("_input", "_label").replace("_average", "_label")).exists() else ""),
            read_text_sudo=lambda path: Path(path).read_text(encoding="utf-8", errors="ignore").strip(),
            privileged_helper_enabled=True,
        )
        assert_true(selected_power_source is not None, "CPU power source helper selects source")
        assert_true(any(source["label"] == "package-1" for source in selected_unreadable), "CPU power source helper returns unreadable sources")
        collector = TelemetryCollector.__new__(TelemetryCollector)
        collector._energy_source_state = {}
        collector._safe_read_text_sudo = lambda path: Path(path).read_text(encoding="utf-8", errors="ignore").strip()
        collector._privileged_helper_enabled = True
        collector._cpu_power_unreadable_sources = [
            {"kind": "rapl", "label": "package-1", "path": str(package_1), "score": 120}
        ]
        mixed_sources = [{"kind": "rapl", "label": "package-0", "path": str(package_0), "score": 120}]
        collector._add_privileged_cpu_power_sources(mixed_sources)
        assert_equal(len(mixed_sources), 2, "mixed readable/privileged package RAPL sources are combined")
        assert_equal(mixed_sources[1]["kind"], "sudo_rapl", "unreadable package RAPL uses sudo source")
        helper_aggregate = aggregate_cpu_package_power_source(
            [
                {"kind": "rapl", "label": "package-0", "path": str(package_0), "score": 120},
                {"kind": "sudo_rapl", "label": "package-1 via sudo", "path": str(package_1), "score": 120},
                {"kind": "rapl", "label": "core", "path": str(root / "intel-rapl:0:0" / "energy_uj"), "score": 20},
            ]
        )
        assert_equal(helper_aggregate["kind"], "aggregate_energy", "CPU package power helper aggregate kind")
        aggregate = collector._aggregate_cpu_package_power_source(
            [
                {"kind": "rapl", "label": "package-0", "path": str(package_0), "score": 120},
                {"kind": "sudo_rapl", "label": "package-1 via sudo", "path": str(package_1), "score": 120},
                {"kind": "rapl", "label": "core", "path": str(root / "intel-rapl:0:0" / "energy_uj"), "score": 20},
            ]
        )
        assert_equal(aggregate["kind"], "aggregate_energy", "multi-package RAPL aggregate source")
        assert_equal(aggregate["package_count"], 2, "multi-package RAPL package count")
        collector._cpu_power_source = aggregate
        assert_equal(collector._read_cpu_power(1.0), None, "first RAPL sample seeds state")
        package_0.write_text("250000000", encoding="utf-8")
        package_1.write_text("450000000", encoding="utf-8")
        assert_equal(collector._read_cpu_power(2.0), 400.0, "multi-package RAPL watts are summed")
        assert_equal(
            collector._last_cpu_package_power_values,
            {"cpu_package_0_power_w": 150.0, "cpu_package_1_power_w": 250.0},
            "multi-package RAPL individual watts are retained",
        )
        hsmp_0 = root / "AMDI0097:00" / "hwmon" / "hwmon4" / "power1_input"
        hsmp_1 = root / "AMDI0097:01" / "hwmon" / "hwmon5" / "power1_input"
        hsmp_0.parent.mkdir(parents=True)
        hsmp_1.parent.mkdir(parents=True)
        hsmp_0.write_text("98000000", encoding="utf-8")
        hsmp_1.write_text("93000000", encoding="utf-8")
        collector._safe_read_text = lambda path: Path(path).read_text(encoding="utf-8", errors="ignore").strip()
        hsmp_aggregate = collector._aggregate_cpu_package_power_source(
            [
                {"kind": "hwmon", "label": "amd_hsmp_hwmon", "path": str(hsmp_0), "score": 360},
                {"kind": "hwmon", "label": "amd_hsmp_hwmon", "path": str(hsmp_1), "score": 360},
            ]
        )
        assert_equal(hsmp_aggregate["kind"], "aggregate_power", "multi-package HSMP aggregate source")
        collector._cpu_power_source = hsmp_aggregate
        assert_equal(collector._read_cpu_power(3.0), 191.0, "multi-package HSMP watts are summed")
        assert_equal(
            collector._last_cpu_package_power_values,
            {"cpu_package_0_power_w": 98.0, "cpu_package_1_power_w": 93.0},
            "multi-package HSMP individual watts are retained",
        )
        temp_0 = root / "pci0000:00" / "0000:00:18.3" / "hwmon" / "hwmon2" / "temp1_input"
        temp_1 = root / "pci0000:00" / "0000:00:19.3" / "hwmon" / "hwmon3" / "temp1_input"
        temp_0.parent.mkdir(parents=True)
        temp_1.parent.mkdir(parents=True)
        temp_0.write_text("62500", encoding="utf-8")
        temp_1.write_text("58750", encoding="utf-8")
        collector._cpu_core_topology = {
            0: {"package_id": 0},
            1: {"package_id": 1},
        }
        collector._cpu_temp_sources = [
            {"kind": "hwmon", "hwmon_name": "k10temp", "label": "Tctl", "path": str(temp_0), "score": 130},
            {"kind": "hwmon", "hwmon_name": "k10temp", "label": "Tctl", "path": str(temp_1), "score": 130},
        ]
        collector._cpu_package_temp_sources = collector._assign_cpu_package_temp_sources()
        assert_equal(
            [source["key"] for source in collector._cpu_package_temp_sources],
            ["cpu_package_0_temp_c", "cpu_package_1_temp_c"],
            "dual-package CPU temp sources are assigned",
        )
        package_temps = collector._read_cpu_package_temps()
        assert_equal(
            package_temps,
            {"cpu_package_0_temp_c": 62.5, "cpu_package_1_temp_c": 58.75},
            "dual-package CPU temps are read",
        )
        assert_equal(collector._read_cpu_temp(package_temps), 62.5, "aggregate CPU temp uses hottest package")


def test_gpu_identity_helpers() -> None:
    assert_equal(normalize_pci_id("0x10DE"), "10de", "normalize PCI vendor id")
    assert_equal(normalize_pci_slot("00000000:01:00.0"), "0000:01:00.0", "normalize long PCI slot")
    assert_equal(normalize_pci_slot("01:00.0"), "0000:01:00.0", "normalize short PCI slot")
    assert_equal(normalize_pci_slot("pci-0000:13:00.0"), "0000:13:00.0", "normalize pci-prefixed slot")
    assert_true(pci_slot_sort_key("0000:01:00.0") < pci_slot_sort_key("0000:13:00.0"), "PCI slot sort key")
    assert_equal(gpu_vendor_name("0x8086"), "Intel", "GPU vendor name")
    assert_equal(gpu_vendor_name("1a03"), "1A03", "unknown GPU vendor name")
    assert_equal(
        friendly_pci_gpu_name("AMD", "Navi 23 [Radeon RX 6600/6600 XT/6600M]", "73FF"),
        "Navi 23 [Radeon RX 6600/6600 XT/6600M]",
        "friendly PCI GPU name preserves explicit Radeon text",
    )
    assert_equal(
        friendly_pci_gpu_name("AMD", "Raphael", "164E"),
        "AMD Radeon Graphics (Raphael)",
        "friendly PCI GPU name improves generic AMD PCI name",
    )
    assert_equal(gpu_vendor_family_from_inventory({"vendor_id": "0x10de"}), "nvidia", "vendor family from PCI ID")
    assert_equal(gpu_vendor_family_from_inventory({"driver": "amdgpu"}), "amd", "vendor family from driver")
    assert_equal(gpu_vendor_family_from_name("Intel Arc A380 Graphics"), "intel", "vendor family from runtime name")
    assert_true(
        is_management_display_adapter({"driver": "ast", "vendor_id": "1a03", "memory": ""}),
        "management display adapter",
    )
    assert_true(is_unhelpful_runtime_gpu_name("llvmpipe (LLVM 20.1.2)"), "unhelpful runtime GPU name")
    assert_true(looks_like_cpu_package_gpu_name("AMD Ryzen 9 7950X 16-Core Processor"), "CPU package GPU name")
    assert_equal(
        clean_runtime_gpu_name("AMD Radeon RX 6600 XT (radeonsi, navi23, LLVM 21.1.8, DRM 3.64)"),
        "AMD Radeon RX 6600 XT",
        "clean runtime GPU name",
    )
    candidate = {
        "name": "AMD Radeon RX 6600 XT",
        "raw": "AMD Radeon RX 6600 XT (radeonsi, navi23)",
        "source": "egl_renderer",
    }
    gpu = {"vendor_id": "1002", "driver": "amdgpu", "pci_name": "Navi 23 [Radeon RX 6600/6600 XT/6600M]"}
    assert_true(runtime_gpu_name_score(gpu, candidate) > 0, "runtime GPU name score")
    assert_equal(select_runtime_gpu_name(gpu, [candidate])["name"], "AMD Radeon RX 6600 XT", "select runtime GPU name")
    assert_equal(
        runtime_gpu_name_score(gpu, {"name": "Intel Arc A380", "raw": "Intel Arc A380", "source": "vulkaninfo"}),
        -1000,
        "runtime GPU name rejects cross-vendor candidate",
    )
    vulkan_text = """
GPU0:
    vendorID           = 0x1002
    deviceID           = 0x73ff
    deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    deviceName         = AMD Radeon RX 6600 XT (RADV NAVI23)
    deviceUUID         = 00000000-0300-0000-0000-000000000000
GPU1:
    vendorID           = 0x10005
    deviceID           = 0x0000
    deviceType         = PHYSICAL_DEVICE_TYPE_CPU
    deviceName         = llvmpipe
"""
    devices = parse_vulkan_summary_devices(vulkan_text)
    assert_equal(len(devices), 2, "parse Vulkan summary devices")
    assert_equal(device_class_from_vulkan_type(devices[0]["deviceType"]), "discrete", "Vulkan discrete class")
    assert_equal(
        slot_from_mesa_vulkan_uuid(
            "00000000-0300-0000-0000-000000000000",
            [{"pci_slot": "0000:03:00.0"}],
        ),
        "0000:03:00.0",
        "Mesa Vulkan UUID to PCI slot",
    )
    assert_equal(
        slot_for_vulkan_device(
            devices[0],
            [{"pci_slot": "0000:03:00.0", "vendor_id": "1002", "device_id": "73ff"}],
        ),
        "0000:03:00.0",
        "Vulkan device to PCI slot",
    )


def test_gpu_target_helpers() -> None:
    cards = [
        {
            "card": "card0",
            "slot": "0000:01:00.0",
            "vendor": "NVIDIA",
            "driver": "nvidia",
            "vram_total": 24 * 1024 ** 3,
            "target_id": "0000:01:00.0",
        },
        {
            "card": "card1",
            "slot": "0000:02:00.0",
            "vendor": "AMD",
            "driver": "amdgpu",
            "vram_total": 4 * 1024 ** 3,
            "target_id": "0000:02:00.0",
        },
        {
            "card": "card2",
            "slot": "0000:03:00.0",
            "vendor": "Intel",
            "driver": "i915",
            "vram_total": 0,
            "target_id": "0000:03:00.0",
        },
    ]
    assert_equal(dri_prime_selector("0000:01:00.0"), "pci-0000_01_00_0", "DRI_PRIME selector")
    assert_equal(gpu_card_class(cards[0]), "discrete", "NVIDIA target class")
    assert_equal([card["card"] for card in likely_discrete_gpu_cards(cards)], ["card0"], "likely discrete cards")
    assert_equal([card["card"] for card in gpu_targets("all", cards)], ["card0", "card1", "card2"], "all GPU targets")
    assert_equal([card["card"] for card in gpu_targets("discrete_max_vram", cards)], ["card0"], "max VRAM target")
    assert_equal([card["card"] for card in gpu_targets("slots:0000:02:00.0", cards)], ["card1"], "slot target")
    assert_equal([card["card"] for card in gpu_targets("cards:card2", cards)], ["card2"], "card target")
    assert_equal(gpu_target_summary("dgpu_all"), "discrete_all", "target summary alias")
    assert_equal(gpu_target_summary("slots: 0000:02:00.0 , card1"), "slots:0000:02:00.0,card1", "slot summary")
    assert_equal(gpu_target_display_label(cards[0]), "card0 | 0000:01:00.0 | NVIDIA | 24.0 GB", "target label")
    assert_equal(gpu_target_by_id(cards, "0000:03:00.0"), cards[2], "target lookup")
    pci_names = {"10de": {"2684": "GB202 [GeForce RTX 5090]"}}
    assert_equal(
        lookup_pci_device_name(pci_names, "0x10de", "2684"),
        "GB202 [GeForce RTX 5090]",
        "PCI device name lookup",
    )


def test_gpu_capability_profile_helpers() -> None:
    assert_equal(gpu_capability_cache_key(None), "default", "GPU capability default cache key")
    assert_equal(gpu_capability_cache_key({"card": "card2"}), "card2", "GPU capability card cache key")
    assert_equal(
        likely_discrete_target_ids([{"target_id": " 0000:01:00.0 "}, {"target_id": ""}]),
        {"0000:01:00.0"},
        "GPU capability discrete IDs",
    )

    base = build_gpu_capability_profile(
        target=None,
        likely_discrete_ids=[],
        explicit_device_class="",
        vulkan_device_class="",
        opencl_device=None,
    )
    assert_equal(base["device_class"], "unknown", "GPU capability unknown class")
    assert_equal(base["device_class_source"], "unknown", "GPU capability unknown class source")
    assert_equal(base["memory_scale"], 0.75, "GPU capability baseline memory scale")
    assert_equal(base["load_scale"], 0.75, "GPU capability baseline load scale")
    assert_equal(base["parallelism_hint"], 1, "GPU capability baseline parallelism")

    target = {"target_id": "GPU-A", "vendor": "AMD", "vram_total": 0}
    selection = build_gpu_capability_profile(
        target=target,
        likely_discrete_ids=["gpu-a"],
        explicit_device_class="",
        vulkan_device_class="",
        opencl_device=None,
    )
    assert_equal(selection["device_class"], "discrete", "GPU capability selection class")
    assert_equal(selection["device_class_source"], "selection", "GPU capability selection class source")

    driver = build_gpu_capability_profile(
        target=target,
        likely_discrete_ids=["gpu-a"],
        explicit_device_class="integrated",
        vulkan_device_class="",
        opencl_device=None,
    )
    assert_equal(driver["device_class"], "integrated", "GPU capability driver class")
    assert_equal(driver["device_class_source"], "driver", "GPU capability driver class source")

    vulkan = build_gpu_capability_profile(
        target=target,
        likely_discrete_ids=["gpu-a"],
        explicit_device_class="integrated",
        vulkan_device_class="discrete",
        opencl_device=None,
    )
    assert_equal(vulkan["device_class"], "discrete", "GPU capability Vulkan class precedence")
    assert_equal(vulkan["device_class_source"], "vulkan", "GPU capability Vulkan class source")

    scale_cases = [
        (1, 0.75),
        (2, 1.0),
        (4, 1.2),
        (8, 1.5),
        (12, 1.8),
        (20, 2.2),
    ]
    for vram_gib, expected_scale in scale_cases:
        profile = build_gpu_capability_profile(
            target={"vram_total": vram_gib * 1024 ** 3},
            likely_discrete_ids=[],
            explicit_device_class="",
            vulkan_device_class="",
            opencl_device=None,
        )
        assert_equal(profile["memory_scale"], expected_scale, f"GPU capability {vram_gib} GiB scale")

    enriched = build_gpu_capability_profile(
        target=target,
        likely_discrete_ids=[],
        explicit_device_class="discrete",
        vulkan_device_class="",
        opencl_device={
            "global_mem_bytes": 24 * 1024 ** 3,
            "compute_units": 48,
            "max_work_group_size": 1024,
            "max_clock_mhz": 2860,
            "opencl_index": None,
        },
    )
    assert_equal(enriched["source"], "opencl", "GPU capability OpenCL source")
    assert_equal(enriched["vram_gib"], 24.0, "GPU capability OpenCL VRAM fallback")
    assert_equal(enriched["compute_scale"], 2.0, "GPU capability compute scale")
    assert_equal(enriched["clock_scale"], 1.3, "GPU capability clock cap")
    assert_equal(enriched["load_scale"], 2.6, "GPU capability combined load scale")
    assert_equal(enriched["parallelism_hint"], 3, "GPU capability parallelism hint")
    assert_equal(enriched["opencl_index"], -1, "GPU capability missing OpenCL index")

    capped = build_gpu_capability_profile(
        target={"vram_total": 4 * 1024 ** 3},
        likely_discrete_ids=[],
        explicit_device_class="discrete",
        vulkan_device_class="",
        opencl_device={
            "global_mem_bytes": 48 * 1024 ** 3,
            "compute_units": 120,
            "max_clock_mhz": 4000,
        },
    )
    assert_equal(capped["vram_gib"], 4.0, "GPU capability target VRAM precedence")
    assert_equal(capped["compute_scale"], 3.0, "GPU capability compute cap")
    assert_equal(capped["load_scale"], 3.5, "GPU capability load cap")

    runner = WorkloadRunner()
    opencl_calls = []
    cached_target = {"target_id": "GPU-CACHED", "vendor": "Intel", "vram_total": 2 * 1024 ** 3}
    runner._discover_gpu_cards = lambda: [cached_target]
    runner._likely_discrete_gpu_cards = lambda cards: list(cards)
    runner._gpu_card_class = lambda _target: ""
    runner._vulkan_device_class = lambda _target: ""
    runner._opencl_device_for_target = lambda _target: opencl_calls.append(True) or None
    first = runner._gpu_capability_profile(cached_target)
    first["load_scale"] = 999
    second = runner._gpu_capability_profile(cached_target)
    assert_equal(len(opencl_calls), 1, "GPU capability runner caches discovery")
    assert_equal(second["load_scale"], 1.0, "GPU capability runner returns defensive cache copy")


def test_inventory_memory_helpers() -> None:
    assert_equal(clean_dmi_value("To Be Filled By O.E.M."), "", "DMI placeholder cleanup")
    assert_equal(clean_dmi_value("F5-6000J3444F64G"), "F5-6000J3444F64G", "DMI useful value")
    assert_equal(
        memory_module_display_part_number("A-DATA", "AX5U5200C3816G-B"),
        "A-DATA AX5U5200C3816G-B",
        "memory display part number with manufacturer",
    )
    assert_equal(
        memory_module_display_part_number("Samsung", "Samsung M323R1GB4BB0-CQKOL"),
        "Samsung M323R1GB4BB0-CQKOL",
        "memory display part number avoids duplicated manufacturer",
    )
    assert_equal(parse_memory_capacity_gb("32768 MB"), 32, "memory capacity MB to GB")
    assert_equal(parse_memory_capacity_gb("64 GB"), 64, "memory capacity GB")
    assert_equal(parse_memory_speed_mhz("5600 MT/s"), 5600, "memory speed MT/s")
    dmidecode_text = """
Memory Device
        Size: 32768 MB
        Form Factor: DIMM
        Locator: Controller0-ChannelA-DIMM0
        Bank Locator: BANK 0
        Type: DDR5
        Type Detail: Synchronous
        Speed: 4800 MT/s
        Configured Memory Speed: 5600 MT/s
        Manufacturer: A-DATA
        Serial Number: 12345678
        Part Number: AX5U5200C3816G-B
        Configured Voltage: 1.25 V
Memory Device
        Size: No Module Installed
        Locator: Controller0-ChannelB-DIMM0
"""
    dmi_modules = parse_dmidecode_memory_modules(dmidecode_text)
    assert_equal(len(dmi_modules), 1, "parse dmidecode memory modules")
    assert_equal(dmi_modules[0]["position"], "BANK 0/Controller0-ChannelA-DIMM0", "dmidecode memory position")
    normalized = normalize_memory_modules_for_export(dmi_modules)
    assert_equal(normalized[0]["PartNumber"], "A-DATA AX5U5200C3816G-B", "normalized memory part number")
    assert_equal(normalized[0]["CapacityGB"], 32, "normalized memory capacity")
    assert_equal(normalized[0]["Speed"], 5600, "normalized memory speed")
    assert_equal(normalized[0]["ConfiguredSpeedMTs"], 5600, "normalized configured memory speed")
    assert_equal(normalized[0]["RatedSpeedMTs"], 4800, "normalized rated memory speed")
    assert_equal(normalized[0]["OperatingSpeedMTs"], 5600, "normalized operating memory speed")
    dmi_speed_summary = build_memory_speed_summary(normalized)
    assert_equal(dmi_speed_summary["OperatingSpeedMTs"], 5600, "memory speed summary operating speed")
    assert_equal(dmi_speed_summary["RatedSpeedMTs"], 4800, "memory speed summary rated speed")
    inxi_text = """
  Device-1: DIMM_A1 type: DDR5 size: 16 GiB speed: 6000 MT/s volts: 1.35 manufacturer: G.Skill part-no: F5-6000J3444F64G serial: N/A
"""
    inxi_modules = normalize_memory_modules_for_export(parse_inxi_memory_modules(inxi_text))
    assert_equal(len(inxi_modules), 1, "parse inxi memory module")
    assert_equal(inxi_modules[0]["PartNumber"], "G.Skill F5-6000J3444F64G", "inxi memory part number")
    assert_equal(inxi_modules[0]["CapacityGB"], 16, "inxi memory capacity")
    assert_equal(inxi_modules[0]["OperatingSpeedMTs"], 6000, "inxi operating memory speed")


def test_storage_inventory_helpers() -> None:
    assert_equal(clean_storage_value("  Samsung   SSD  "), "Samsung SSD", "storage cleanup whitespace")
    assert_equal(clean_storage_value("Not Available"), "", "storage cleanup placeholder")
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp) / "block"
        nvme = root / "nvme0n1"
        sata = root / "sda"
        ignored = root / "loop0"
        pci_device = Path(tmp) / "devices" / "pci0000:00" / "0000:06:00.0"
        for path in (
            pci_device,
            nvme / "queue",
            sata / "device",
            sata / "queue",
            ignored / "device",
        ):
            path.mkdir(parents=True, exist_ok=True)
        os.symlink(pci_device, nvme / "device")
        (nvme / "size").write_text(str((1024 * 1024 ** 3) // 512), encoding="utf-8")
        (pci_device / "model").write_text("Smoke NVMe", encoding="utf-8")
        (pci_device / "serial").write_text("NVME123", encoding="utf-8")
        (pci_device / "firmware_rev").write_text("1.0A", encoding="utf-8")
        (pci_device / "max_link_speed").write_text("16.0 GT/s", encoding="utf-8")
        (pci_device / "current_link_speed").write_text("16.0 GT/s", encoding="utf-8")
        (pci_device / "max_link_width").write_text("4", encoding="utf-8")
        (pci_device / "current_link_width").write_text("4", encoding="utf-8")
        (pci_device / "uevent").write_text("PCI_SLOT_NAME=0000:06:00.0\n", encoding="utf-8")
        (nvme / "queue" / "rotational").write_text("0", encoding="utf-8")
        (sata / "size").write_text(str((512 * 1024 ** 3) // 512), encoding="utf-8")
        (sata / "device" / "vendor").write_text("ATA", encoding="utf-8")
        (sata / "device" / "model").write_text("Smoke SATA", encoding="utf-8")
        (sata / "device" / "rev").write_text("R2", encoding="utf-8")
        (sata / "queue" / "rotational").write_text("1", encoding="utf-8")
        (ignored / "size").write_text(str((64 * 1024 ** 3) // 512), encoding="utf-8")

        assert_equal(block_device_capacity_gb(nvme), 1024, "storage capacity")
        assert_equal(storage_interface_type("nvme0n1", nvme), "NVMe", "nvme interface")
        assert_equal(storage_media_type("sda", sata, "SCSI/SATA"), "Hard Disk Drive", "rotational media")

        devices = collect_storage_info(root)
        assert_equal([device["Name"] for device in devices], ["nvme0n1", "sda"], "storage device filtering")
        assert_equal(devices[0]["Model"], "Smoke NVMe", "nvme model")
        assert_equal(devices[0]["CapacityGB"], 1024, "nvme capacity")
        assert_equal(devices[0]["Interface"], "NVMe", "nvme export interface")
        assert_equal(devices[0]["MediaType"], "NVMe Drives", "nvme export media")
        assert_equal(devices[0]["PcieCurrentLinkSpeed"], "16.0 GT/s", "nvme PCIe current link speed")
        assert_equal(devices[0]["PcieCurrentLinkWidth"], "4", "nvme PCIe current link width")
        assert_equal(devices[0]["PcieSlot"], "0000:06:00.0", "nvme PCIe slot")
        assert_equal(
            pcie_link_info_for_path(nvme / "device", lambda path: path.read_text(encoding="utf-8").strip()),
            devices[0]["PcieLink"],
            "PCIe helper maps block device to link info",
        )
        assert_equal(devices[1]["Model"], "ATA Smoke SATA", "sata vendor model")
        assert_equal(devices[1]["Firmware"], "R2", "sata firmware fallback")
        assert_equal(devices[1]["MediaType"], "Hard Disk Drive", "sata media")

        hwmon_root = Path(tmp) / "devices" / "pci0000:00" / "nvme" / "nvme0" / "nvme0n1" / "hwmon"
        hwmon = hwmon_root / "hwmon0"
        hwmon.mkdir(parents=True)
        (hwmon / "name").write_text("nvme", encoding="utf-8")
        (hwmon / "temp1_input").write_text("41000", encoding="utf-8")
        (hwmon / "temp1_label").write_text("Composite", encoding="utf-8")
        (hwmon / "temp2_input").write_text("42000", encoding="utf-8")
        (hwmon / "temp2_label").write_text("Sensor 1", encoding="utf-8")
        (hwmon / "temp3_input").write_text("43000", encoding="utf-8")
        (hwmon / "temp3_label").write_text("Sensor 2", encoding="utf-8")
        telemetry_sources = discover_storage_temp_sources(hwmon_root=hwmon_root, block_root=root)
        assert_equal(len(telemetry_sources), 3, "storage telemetry mapped drive source count")
        assert_equal(telemetry_sources[0]["key"], "storage_drive_0_temp_c", "storage telemetry key")
        assert_equal(telemetry_sources[0]["block_name"], "nvme0n1", "storage telemetry block mapping")
        assert_equal(telemetry_sources[0]["label"], "Smoke NVMe Composite", "storage telemetry label")
        assert_equal(telemetry_sources[0]["pcie_link"]["CurrentLinkWidth"], "4", "storage telemetry PCIe link evidence")
        assert_equal(telemetry_sources[1]["key"], "storage_drive_0_sensor_1_temp_c", "storage telemetry secondary sensor 1 key")
        assert_equal(telemetry_sources[1]["kind"], "storage_temp_secondary", "storage telemetry secondary sensor kind")
        assert_equal(telemetry_sources[1]["sensor_index"], 1, "storage telemetry secondary sensor 1 index")
        assert_equal(telemetry_sources[2]["key"], "storage_drive_0_sensor_2_temp_c", "storage telemetry secondary sensor 2 key")
        assert_equal(telemetry_sources[2]["sensor_index"], 2, "storage telemetry secondary sensor 2 index")
        assert_true(
            str(telemetry_sources[0]["path"]).endswith("temp1_input"),
            "storage telemetry prefers composite/temp1 sensor",
        )
        assert_equal(
            read_storage_temps(
                telemetry_sources,
                read_temperature=lambda path: {
                    "temp1_input": 41.0,
                    "temp2_input": 42.0,
                    "temp3_input": 43.0,
                }.get(path.name),
            ),
            {
                "storage_drive_0_temp_c": 41.0,
                "storage_drive_0_sensor_1_temp_c": 42.0,
                "storage_drive_0_sensor_2_temp_c": 43.0,
            },
            "storage telemetry value reader",
        )


def test_system_info_gpu_pcie_attribution() -> None:
    class FakeSystemInfoCollector(SystemInfoCollector):
        def _discover_drm_gpus(self):
            return [
                {
                    "card": "card0",
                    "name": "Integrated GPU",
                    "marketing_name": "Integrated GPU",
                    "pci_name": "Integrated GPU",
                    "name_source": "fixture",
                    "chipset": "Intel 1234",
                    "driver": "i915",
                    "pci_slot": "0000:00:02.0",
                    "vendor_id": "8086",
                    "device_id": "1234",
                    "device_class": "integrated",
                    "device_class_source": "fixture",
                    "device_class_confidence": "high",
                    "memory": "",
                    "pcie_link": {
                        "MaxLinkSpeed": "Unknown",
                        "CurrentLinkSpeed": "Unknown",
                        "MaxLinkWidth": "255",
                        "CurrentLinkWidth": "0",
                        "PciSlot": "0000:00:02.0",
                    },
                },
                {
                    "card": "card1",
                    "name": "Discrete GPU",
                    "marketing_name": "Discrete GPU",
                    "pci_name": "Discrete GPU",
                    "name_source": "fixture",
                    "chipset": "AMD 744C",
                    "driver": "amdgpu",
                    "pci_slot": "0000:04:00.0",
                    "vendor_id": "1002",
                    "device_id": "744C",
                    "device_class": "discrete",
                    "device_class_source": "fixture",
                    "device_class_confidence": "high",
                    "memory": "8 GB",
                    "pcie_link": {
                        "MaxLinkSpeed": "16.0 GT/s PCIe",
                        "CurrentLinkSpeed": "16.0 GT/s PCIe",
                        "MaxLinkWidth": "16",
                        "CurrentLinkWidth": "16",
                        "PciSlot": "0000:04:00.0",
                    },
                },
                {
                    "card": "card2",
                    "name": "Partial GPU",
                    "marketing_name": "Partial GPU",
                    "pci_name": "Partial GPU",
                    "name_source": "fixture",
                    "chipset": "NVIDIA 1ABC",
                    "driver": "nouveau",
                    "pci_slot": "0000:05:00.0",
                    "vendor_id": "10DE",
                    "device_id": "1ABC",
                    "device_class": "discrete",
                    "device_class_source": "fixture",
                    "device_class_confidence": "high",
                    "memory": "4 GB",
                    "pcie_link": {
                        "MaxLinkSpeed": "16.0 GT/s PCIe",
                        "CurrentLinkSpeed": "8.0 GT/s PCIe",
                        "MaxLinkWidth": "16",
                        "CurrentLinkWidth": "8",
                        "PciSlot": "0000:04:00.0",
                    },
                },
            ]

        def _vulkan_gpu_classes_by_slot(self, _drm_gpus):
            return {}

        def _runtime_gpu_names_by_slot(self, _drm_gpus):
            return {}

        def _discover_nvidia_smi_gpus(self):
            return []

    gpus = FakeSystemInfoCollector()._gpu_info()
    by_slot = {gpu["Interface"]: gpu for gpu in gpus}
    assert_equal(by_slot["0000:04:00.0"]["PcieCurrentLinkSpeed"], "16.0 GT/s PCIe", "dGPU PCIe speed retained")
    assert_equal(by_slot["0000:04:00.0"]["PcieCurrentLinkWidth"], "16", "dGPU PCIe width retained")
    assert_equal(by_slot["0000:04:00.0"]["PcieSlot"], "0000:04:00.0", "dGPU flat PCIe slot")
    assert_equal(by_slot["0000:00:02.0"]["PcieSlot"], "0000:00:02.0", "iGPU flat PCIe slot")
    assert_equal(by_slot["0000:05:00.0"]["PcieLink"], {}, "mismatched GPU PCIe link omitted")
    assert_equal(by_slot["0000:05:00.0"]["PcieSlot"], "", "mismatched GPU flat PCIe slot omitted")
    assert_equal(
        trusted_pcie_link_for_slot({"PciSlot": "0000:04:00.0", "CurrentLinkWidth": "16"}, "0000:05:00.0"),
        {},
        "PCIe helper rejects neighboring GPU slot",
    )


def test_system_identity_helpers() -> None:
    assert_equal(normalize_dmi_sysfs_value("To Be Filled By O.E.M."), "", "DMI sysfs placeholder")
    dmi = {
        "sys_vendor": "ASUSTeK COMPUTER INC.",
        "product_name": "System Product Name",
        "product_version": "",
        "product_serial": "SYS123",
        "board_vendor": "ASUSTeK COMPUTER INC.",
        "board_name": "PRIME X670-P WIFI",
        "board_version": "Rev 1.xx",
        "board_asset_tag": "",
        "board_serial": "BOARD123",
        "bios_vendor": "American Megatrends Inc.",
        "bios_version": "3287",
        "bios_date": "04/01/2026",
    }
    motherboard = build_motherboard_info(dmi)
    assert_equal(
        motherboard["Product"],
        "ASUSTeK COMPUTER INC. PRIME X670-P WIFI",
        "motherboard sys_vendor plus board_name",
    )
    assert_equal(motherboard["ProductRaw"], "PRIME X670-P WIFI", "motherboard raw board name")
    assert_equal(motherboard["SerialNumber"], "BOARD123", "motherboard serial")
    bios = build_bios_info(dmi)
    assert_equal(bios["Name"], "3287", "bios name uses version")
    assert_equal(bios["Version"], "3287", "bios explicit version")
    assert_equal(bios["FullName"], "American Megatrends Inc. 3287", "bios full name")
    os_release = 'NAME="Bazzite"\nPRETTY_NAME="Bazzite 44"\n'
    assert_equal(parse_os_release_pretty_name(os_release), "Bazzite 44", "os-release pretty name")
    assert_equal(
        build_linux_os_name("openSUSE Tumbleweed", "Linux", "7.0.5-1-default"),
        "openSUSE Tumbleweed Linux 7.0.5-1-default",
        "linux OS name prepends distro",
    )


def test_cpu_power_limit_helpers() -> None:
    assert_equal(format_watts(125.0), "125W", "format whole watts")
    assert_equal(format_watts(125.55), "125.55W", "format fractional watts")
    assert_equal(format_seconds(28.0), "28s", "format whole seconds")
    assert_equal(format_seconds(0.1234), "0.123s", "format fractional seconds")
    with TemporaryDirectory(dir="/tmp") as tmp:
        package = Path(tmp) / "intel-rapl:0"
        package.mkdir()
        (package / "constraint_0_name").write_text("long_term", encoding="utf-8")
        (package / "constraint_0_power_limit_uw").write_text("125000000", encoding="utf-8")
        (package / "constraint_0_max_power_uw").write_text("253000000", encoding="utf-8")
        (package / "constraint_0_time_window_us").write_text("28000000", encoding="utf-8")
        (package / "constraint_1_name").write_text("short_term", encoding="utf-8")
        (package / "constraint_1_power_limit_uw").write_text("253000000", encoding="utf-8")
        (package / "constraint_1_max_power_uw").write_text("409000000", encoding="utf-8")
        (package / "constraint_1_time_window_us").write_text("2440", encoding="utf-8")
        (package / "constraint_bad_name").write_text("ignored", encoding="utf-8")

        read = lambda path: path.read_text(encoding="utf-8").strip() if path.exists() else None
        assert_equal(select_rapl_package_dir([Path(tmp) / "missing", package]), package, "select RAPL dir")
        assert_equal(read_microunit_watts(package / "constraint_0_power_limit_uw", read), 125.0, "read microwatts")
        assert_equal(read_microseconds(package / "constraint_1_time_window_us", read), 0.002, "read microseconds")
        constraints = collect_rapl_constraints(package, read)
        assert_equal(len(constraints), 2, "RAPL constraint count")
        assert_equal(constraints[0]["Name"], "long_term", "RAPL constraint name")
        assert_equal(constraints[1]["PowerLimitW"], 253.0, "RAPL PL2 watts")
        info = build_cpu_power_limit_info(package, read)
        assert_equal(info["Source"], str(package), "RAPL source")
        assert_equal(info["PowerLimitData"], "PL1:125W|PL2:253W|Turbo:28s", "RAPL power limit data")
        assert_equal(info["AmdPpt"], "", "RAPL AMD PPT placeholder")
    assert_equal(
        build_cpu_power_limit_info(None, lambda path: None),
        {"Source": "not found", "PowerLimitData": "", "AmdPpt": ""},
        "missing RAPL info",
    )


def test_cpu_topology_helpers() -> None:
    cpuinfo_text = """
processor   : 0
model name  : AMD EPYC 9255 24-Core Processor

processor   : 1
model name  : AMD EPYC 9255 24-Core Processor

processor   : 2
model name  : AMD EPYC 9255 24-Core Processor

processor   : 3
model name  : AMD EPYC 9255 24-Core Processor
"""
    models = parse_proc_cpuinfo_models(cpuinfo_text)
    assert_equal(models[0], "AMD EPYC 9255 24-Core Processor", "cpuinfo model parse")
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp) / "cpu"
        for cpu_index, package_id, core_id in (
            (0, 0, 0),
            (1, 0, 1),
            (2, 1, 0),
            (3, 1, 1),
        ):
            topology = root / f"cpu{cpu_index}" / "topology"
            topology.mkdir(parents=True)
            (topology / "physical_package_id").write_text(str(package_id), encoding="utf-8")
            (topology / "core_id").write_text(str(core_id), encoding="utf-8")
        read = lambda path: path.read_text(encoding="utf-8").strip() if path.exists() else None
        info = collect_cpu_topology_info(
            cpu_root=root,
            cpuinfo_text=cpuinfo_text,
            read_text=read,
            fallback_name="AMD EPYC 9255 24-Core Processor",
        )
        assert_equal(info["NameSummary"], "2x AMD EPYC 9255 24-Core Processor", "dual CPU name summary")
        assert_equal(
            info["Aggregate"]["Name"],
            "2x AMD EPYC 9255 24-Core Processor",
            "dual CPU aggregate name",
        )
        assert_equal(info["PackageCount"], 2, "dual CPU package count")
        assert_equal(info["LogicalCpuCount"], 4, "logical CPU count")
        assert_equal(info["PhysicalCoreCount"], 4, "physical core count")
        assert_equal(info["Packages"][0]["LogicalCpuRange"], "0-1", "package 0 CPU range")
        assert_equal(info["Packages"][1]["LogicalCpuRange"], "2-3", "package 1 CPU range")
        package_devices = cpu_package_devices_from_topology(info)
        assert_equal(package_devices[0]["DeviceId"], "cpu_package_0", "package 0 device id")
        assert_equal(
            package_devices[1]["DisplayName"],
            "CPU 1: AMD EPYC 9255 24-Core Processor",
            "package 1 display name",
        )


def test_run_progress_helpers() -> None:
    phase = "[phase] 2026-05-27T12:00:00-04:00 | stage-start | stage=Power | planned=00:01:30"
    assert_true("T" in future_local_iso(1), "future local ISO timestamp")
    assert_equal(
        phase_line("2026-05-27T12:00:00-04:00", "stage-start", stage="Power", planned="00:01:30"),
        phase,
        "phase line builder preserves format",
    )
    assert_equal(normalize_progress_line(phase + "\n"), phase, "progress line normalize")
    assert_true(is_phase_progress_line(phase), "phase prefix progress line")
    assert_true(is_phase_progress_line("2026-05-27 | run-end | elapsed=00:01:30"), "run event progress line")
    assert_true(not is_phase_progress_line("ordinary stdout"), "ordinary stdout not phase")
    assert_equal(
        latest_phase_line(["ordinary stdout", phase, "worker output", "2026-05-27 | run-end | elapsed=00:01:30"]),
        "2026-05-27 | run-end | elapsed=00:01:30",
        "latest phase line",
    )
    shortened = short_status_text("one two three four five", limit=13)
    assert_equal(shortened, "one two th...", "short status text")
    event = parse_progress_event(phase)
    assert_true(event is not None, "parse progress event")
    assert_equal(event.event_type, "stage-start", "progress event type")
    assert_equal(event.fields.get("stage"), "Power", "progress event stage")
    heatsoak_event = parse_progress_event("[heatsoak] elapsed=00:00:30 | remaining=00:00:30")
    assert_true(heatsoak_event is not None, "parse heatsoak progress event")
    assert_equal(heatsoak_event.event_type, "heatsoak-progress", "heatsoak progress event type")
    assert_equal(heatsoak_event.fields.get("remaining"), "00:00:30", "heatsoak progress remaining")
    tracker = RunStatusTracker()
    tracker.update_line("[phase] 2026-05-27T11:59:00-04:00 | heatsoak-start | minutes=1")
    assert_equal(tracker.snapshot.status, "heatsoak_active", "progress tracker heatsoak active")
    tracker.update_line("[heatsoak] elapsed=00:00:30 | remaining=00:00:30")
    assert_equal(tracker.snapshot.elapsed, "00:00:30", "progress tracker heatsoak elapsed")
    tracker.update_line("[phase] 2026-05-27T11:59:59-04:00 | heatsoak-end | verdict=completed")
    tracker.update_line("[phase] 2026-05-27T12:00:00-04:00 | run-start | profile=PL_Validation")
    tracker.update_line(phase)
    tracker.update_line("[phase] 2026-05-27T12:01:30-04:00 | stage-end | stage=Power | actual=00:01:30 | verdict=warning")
    tracker.update_line("[phase] 2026-05-27T12:01:31-04:00 | run-end | elapsed=00:01:31 | verdict=warning")
    assert_equal(tracker.snapshot.profile, "PL_Validation", "progress tracker profile")
    assert_equal(tracker.snapshot.stage, "Power", "progress tracker stage")
    assert_equal(tracker.snapshot.verdict, "warning", "progress tracker verdict")
    assert_true(not tracker.snapshot.active, "progress tracker inactive after run-end")
    detail = run_status_detail_text(tracker.snapshot)
    assert_true("Status: run complete" in detail, "progress detail status")
    assert_true("Profile: PL_Validation" in detail, "progress detail profile")
    assert_true("Stage: Power" in detail, "progress detail stage")
    history = run_event_history_text(tracker.events, limit=3)
    assert_true("Recent Events" in history, "progress event history heading")
    assert_true("stage end: stage=Power, verdict=warning" in history, "progress event history stage end")
    assert_true("run end: verdict=warning, elapsed=00:01:31" in history, "progress event history run end")


def test_cli_live_run_presenter_helpers() -> None:
    class FakeTty(io.StringIO):
        def isatty(self) -> bool:
            return True

    class FakePipe(io.StringIO):
        def isatty(self) -> bool:
            return False

    tty = FakeTty()
    presenter = CliLiveRunPresenter(stream=tty, enabled=True, width=90)
    presenter.write_line("[phase] 2026-07-13T12:00:00-04:00 | run-start | profile=Quick Test")
    presenter.write_line(
        "[phase] 2026-07-13T12:00:01-04:00 | stage-start | stage=Power (CPU + 3D) | planned=00:01:30"
    )
    presenter.write_line(
        "2026-07-13T12:00:30-04:00 | stage=Power (CPU + 3D) | elapsed=00:00:30 | remaining=00:01:00 | gpu_target=gpu0,busy=99.0%,very-long-extra-field-that-should-not-make-the-status-unreadable"
    )
    first_lines = presenter.render_lines()
    presenter.write_line(
        "2026-07-13T12:00:45-04:00 | stage=Power (CPU + 3D) | elapsed=00:00:45 | remaining=00:00:45 | gpu_target=gpu0,busy=98.0%"
    )
    second_lines = presenter.render_lines()
    assert_true("elapsed=00:00:45" in "\n".join(second_lines), "CLI live presenter updates active stage elapsed")
    assert_true("elapsed=00:00:30" not in "\n".join(second_lines), "CLI live presenter replaces stale active stage")
    assert_equal(
        len([line for line in second_lines if "Active stage:" in line]),
        1,
        "CLI live presenter keeps one active stage line",
    )
    presenter.write_line(
        "[phase] 2026-07-13T12:01:30-04:00 | stage-end | stage=Power (CPU + 3D) | actual=00:01:30 | verdict=pass"
    )
    final_lines = presenter.render_lines()
    assert_true("Completed stages:" in final_lines, "CLI live presenter shows completed stages")
    assert_true(
        any("Power (CPU + 3D) | verdict=pass | actual=00:01:30" in line for line in final_lines),
        "CLI live presenter summarizes completed stage",
    )
    presenter.write_line("[warn] GPU telemetry source temporarily unavailable")
    assert_true(
        "GPU telemetry source temporarily unavailable" in "\n".join(presenter.render_lines()),
        "CLI live presenter keeps warning detail visible",
    )
    assert_true("\x1b[" in tty.getvalue(), "CLI live presenter uses ANSI refresh on TTY")

    pipe = FakePipe()
    fallback = CliLiveRunPresenter(stream=pipe, enabled=False)
    fallback.write_line("plain progress line")
    assert_equal(pipe.getvalue(), "plain progress line\n", "CLI live presenter non-TTY passthrough")
    assert_true(not cli_live_run_supported(pipe), "CLI live presenter detects non-TTY fallback")


def test_gpu_progress_helpers() -> None:
    telemetry = SimpleNamespace(
        samples=[
            Sample(0.0, {"gpu_0_busy_percent": 10.0}),
            Sample(
                1.0,
                {
                    "gpu_0_busy_percent": 80.0,
                    "gpu_1_busy_percent": 0.5,
                    "gpu_1_power_w": 4.0,
                    "gpu_2_busy_percent": 12.345,
                    "gpu_2_memory_busy_percent": 30.0,
                    "gpu_2_power_w": 40.0,
                    "gpu_2_temp_core_c": 55.0,
                    "gpu_2_clock_mhz": 2100.0,
                    "gpu_2_vram_used_gb": 1.25,
                },
            ),
        ],
    )
    assert_equal(latest_sample_value(telemetry, "gpu_0_busy_percent"), 80.0, "latest GPU sample value")
    assert_equal(latest_sample_value(SimpleNamespace(samples=[]), "gpu_0_busy_percent"), None, "empty latest sample")
    assert_equal(
        other_gpu_progress_summary(telemetry, {0: {"target_id": "0000:01:00.0"}}),
        "gpu_other=gpu2:busy=12.35%,mem_busy=30.0%,pwr=40.0W,temp=55.0C,clk=2100.0MHz,vram=1.25GB",
        "other GPU progress summary",
    )
    assert_equal(
        other_gpu_progress_summary(telemetry, {0: {}, 2: {}}),
        "",
        "other GPU progress suppresses target and low-noise GPUs",
    )
    assert_equal(
        target_gpu_metric_progress_parts(telemetry, 2),
        ["busy=12.35%", "mem_busy=30.0%", "pwr=40.0W", "temp=55.0C", "clk=2100.0MHz", "vram=1.25GB"],
        "target GPU metric progress parts",
    )
    state_parts = target_gpu_state_progress_parts(
        [
            {
                "active_load_fraction": 0.625,
                "phase": "steady",
                "active_target_vram_bytes": 2 * 1024 ** 3,
                "allocated_vram_bytes": 1024 ** 3,
                "active_fill_buffer_count": 4,
                "active_process_count": 2,
                "target_process_count": 3,
                "active_launches_per_cycle": 7,
                "active_buffer_count": 5,
                "compute_rounds": 11,
            }
        ],
        [
            {
                "active_load_fraction": 0.25,
                "active_phase": "planned",
                "active_draw_count": 900,
                "active_buffer_bytes": 64 * 1024 ** 2,
                "active_compute_rounds": 3,
            }
        ],
        target_vram_total=4 * 1024 ** 3,
    )
    assert_equal(
        state_parts,
        [
            "load=62.5%",
            "phase=steady",
            "vram_target=2.0/4.0GB",
            "alloc=1.0/2.0GB",
            "fill_buf=4",
            "draw=900",
            "proc=2/3",
            "launch=7",
            "comp_buf=5",
            "buf=64.0MB",
            "rounds=11",
        ],
        "target GPU state progress parts",
    )
    target_summary = target_gpu_progress_summary(
        2,
        {
            "target_id": "0000:02:00.0",
            "workloads": ["gpu_3d", "vram"],
            "backends": ["python_vulkan_compute"],
        },
        ["busy=95.0%", "pwr=120.0W"],
        ["load=80.0%", "rounds=7"],
    )
    assert_equal(
        target_summary,
        "gpu2@0000:02:00.0[gpu_3d+vram]/python_vulkan_compute:busy=95.0%,pwr=120.0W|state=load=80.0%,rounds=7",
        "target GPU progress summary",
    )
    assert_equal(
        stage_gpu_progress_summary([target_summary], "gpu_other=gpu1:busy=3.0%"),
        " | gpu_target=gpu2@0000:02:00.0[gpu_3d+vram]/python_vulkan_compute:busy=95.0%,pwr=120.0W|state=load=80.0%,rounds=7 | gpu_other=gpu1:busy=3.0%",
        "stage GPU progress summary",
    )
    assert_equal(stage_gpu_progress_summary([], ""), "", "empty stage GPU progress summary")


def test_gpu_retune_helpers() -> None:
    samples = [
        Sample(90.0, {"gpu_0_busy_percent": 50.0}),
        Sample(96.0, {"gpu_0_busy_percent": 70.0}),
        Sample(99.0, {"gpu_0_busy_percent": 95.0}),
    ]
    assert_equal(
        recent_metric_values(samples, "gpu_0_busy_percent", 5.0, now_monotonic=100.0),
        [70.0, 95.0],
        "recent metric values",
    )
    assert_equal(recent_metric_values(samples, "missing", 5.0, now_monotonic=100.0), [], "recent missing metric")
    spec = SimpleNamespace(target_id="0000:01:00.0", card="card1", workload="gpu_3d")
    events = [
        {"target_id": "0000:01:00.0", "workload": "gpu_3d"},
        {"target_id": "0000:01:00.0", "workload": "vram"},
        {"target_id": "0000:02:00.0", "workload": "gpu_3d"},
    ]
    assert_equal(worker_retune_count(events, spec), 1, "worker retune count")
    assert_true(
        abs(effective_gpu_retune_warmup_seconds(60.0, True, 90.0) - 31.5) < 0.001,
        "safe retune warmup scaled",
    )
    assert_equal(effective_gpu_retune_warmup_seconds(60.0, False, 90.0), 60.0, "unsafe retune warmup unchanged")
    assert_equal(effective_gpu_retune_cooldown_seconds(30.0, True, 90.0), 18.0, "safe retune cooldown scaled")
    assert_equal(minimum_gpu_retune_remaining_seconds(45.0, 90.0), 54.0, "retune minimum remaining seconds")
    assert_equal(minimum_gpu_retune_remaining_seconds(5.0, 0.0), 20.0, "retune minimum remaining open-ended")


def test_gpu_retune_policy_helpers() -> None:
    settings = SimpleNamespace(
        gpu_safe_mode=True,
        gpu_retune_warmup_seconds=60.0,
        gpu_retune_cooldown_seconds=30.0,
        gpu_internal_ramp_step_seconds=45.0,
        gpu_max_retunes_per_worker=2,
    )
    spec = GpuWorkerSpec(
        "gpu_3d",
        "python_egl_gles2",
        0,
        "card1",
        "0000:01:00.0",
        "0000:01:00.0",
        ["egl"],
    )

    decision = gpu_worker_retune_decision(
        spec,
        settings=settings,
        retune_events=[],
        stage_elapsed_seconds=70.0,
        stage_duration_seconds=180.0,
        latest_metric_value=lambda key: 55.0,
        recent_metric_values_for_key=lambda key, window_seconds: [52.0, 55.0, 58.0],
        thermal_safe_for_gpu=lambda gpu_index: True,
    )
    assert_true(decision.should_retune, "low busy GPU worker retunes")
    assert_equal(decision.busy_percent, 55.0, "retune decision busy percent")

    warmup_decision = gpu_worker_retune_decision(
        spec,
        settings=settings,
        retune_events=[],
        stage_elapsed_seconds=5.0,
        stage_duration_seconds=180.0,
        latest_metric_value=lambda key: 55.0,
        recent_metric_values_for_key=lambda key, window_seconds: [52.0, 55.0, 58.0],
        thermal_safe_for_gpu=lambda gpu_index: True,
    )
    assert_equal(warmup_decision.reason, "warmup", "retune policy warmup block")

    high_busy_decision = gpu_worker_retune_decision(
        spec,
        settings=settings,
        retune_events=[],
        stage_elapsed_seconds=70.0,
        stage_duration_seconds=180.0,
        latest_metric_value=lambda key: 96.0,
        recent_metric_values_for_key=lambda key, window_seconds: [52.0, 55.0, 58.0],
        thermal_safe_for_gpu=lambda gpu_index: True,
    )
    assert_equal(high_busy_decision.reason, "busy_unavailable_or_high", "retune policy busy block")

    vram_spec = GpuWorkerSpec(
        "vram",
        "python_opencl",
        0,
        "card1",
        "0000:01:00.0",
        "0000:01:00.0",
        ["opencl-vram"],
    )
    vram_decision = gpu_worker_retune_decision(
        vram_spec,
        settings=settings,
        retune_events=[],
        stage_elapsed_seconds=70.0,
        stage_duration_seconds=180.0,
        latest_metric_value=lambda key: 55.0,
        recent_metric_values_for_key=lambda key, window_seconds: [52.0, 55.0, 58.0],
        thermal_safe_for_gpu=lambda gpu_index: True,
    )
    assert_equal(vram_decision.reason, "vram_stable", "retune policy keeps VRAM workers stable")


def test_advanced_debug_logger_helpers() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        run_dir = Path(tmp)
        logger = AdvancedDebugLogger(run_dir, enabled=True)
        assert_equal(logger._safe_name("GPU 0 / stage"), "GPU_0___stage", "debug safe name")
        filtered = logger._filter_lines("ok\nNVRM: Xid 79\nplain\nPCIe AER fault\n", ["xid", "aer"])
        assert_true("Xid 79" in filtered and "AER fault" in filtered and "plain" not in filtered, "debug log filtering")
        logger._capture_command("missing_command", ["lvs-definitely-missing-command"], timeout=1)
        assert_true((run_dir / "advanced_debug" / "missing_command.txt").exists(), "missing command debug output")
        logger._capture_event("run_start", started_iso="2026-05-28T12:00:00-04:00", profile_name="Smoke")
        logger._write_manifest()
        assert_true((run_dir / "advanced_debug" / "advanced_debug_manifest.json").exists(), "debug manifest")
        text = (run_dir / "advanced_debug" / "advanced_debug_log.txt").read_text(encoding="utf-8")
        assert_true("Event: run_start" in text, "debug log content")
        heatsoak_logger = AdvancedDebugLogger(run_dir, enabled=True, scope="heatsoak")
        heatsoak_logger.capture_heatsoak_start(timestamp_iso="2026-05-28T12:00:00-04:00", duration_seconds=60)
        heatsoak_logger.capture_heatsoak_end(
            timestamp_iso="2026-05-28T12:01:00-04:00",
            since_iso="2026-05-28T12:00:00-04:00",
            verdict="completed",
        )
        heatsoak_manifest = run_dir / "advanced_debug" / "heatsoak" / "heatsoak_debug_manifest.json"
        assert_true(heatsoak_manifest.exists(), "heatsoak debug manifest")
        assert_true((run_dir / "advanced_debug" / "heatsoak" / "heatsoak_debug_log.txt").exists(), "heatsoak debug log")
        reloaded_heatsoak_logger = AdvancedDebugLogger(run_dir, enabled=True, scope="heatsoak")
        assert_true(len(reloaded_heatsoak_logger.events) >= 2, "heatsoak debug event reload")


def test_intel_gpu_sidecar_helpers() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        tmp_path = Path(tmp)
        raw_path = tmp_path / "intel_gpu_top.json"
        stderr_path = tmp_path / "intel_gpu_top.stderr.log"
        summary_path = tmp_path / "intel_gpu_top.summary.json"
        raw_path.write_text(
            'noise {"engines":{"Render/3D/0":{"busy":0},"Compute/0":{"busy":10}}}\n'
            '{"engines":{"Render/3D/0":{"busy":50},"Compute/0":{"busy":75}}}\n'
            'tail {"engines":{"Render/3D/0":{"busy":100},"Copy/0":{"busy":0}}}',
            encoding="utf-8",
        )
        stderr_path.write_text("sample stderr", encoding="utf-8")
        objects = load_intel_gpu_top_objects(raw_path)
        assert_equal(len(objects), 3, "intel_gpu_top concatenated JSON object count")
        series = summarize_numeric_series([0.0, 50.0, 100.0, 0.0])
        assert_equal(series["sample_count"], 4, "intel series sample count")
        assert_equal(series["max"], 100.0, "intel series max")
        assert_equal(series["samples_at_or_below_1_percent"], 2, "intel zero samples")
        assert_equal(series["zero_crossing_transitions"], 2, "intel zero crossing transitions")
        summary = summarize_intel_gpu_top_sidecar(
            {
                "stage_id": "segment_1",
                "stage_name": "Intel",
                "started": "2026-01-01T00:00:00-05:00",
                "command": ["intel_gpu_top"],
                "raw_path": raw_path,
                "stderr_path": stderr_path,
                "summary_path": summary_path,
            }
        )
        assert_true(summary["available"], "intel sidecar summary available")
        assert_equal(summary["object_count"], 3, "intel sidecar object count")
        assert_equal(summary["aggregate_engine_busy"]["max"], 100.0, "intel sidecar aggregate max")
        assert_true("Render/3D/0" in summary["engines"], "intel sidecar engine summary")
        missing_reason = intel_gpu_top_failure_reason("permission denied opening pmu; CAP_PERFMON required")
        assert_true("CAP_PERFMON" in missing_reason, "intel sidecar failure reason")


def test_intel_gpu_runtime_diagnostics_helpers() -> None:
    missing = collect_intel_gpu_top_details(
        command_exists=lambda _command: False,
        command_env=lambda: {},
    )
    assert_equal(missing["available"], False, "Intel diagnostics missing command unavailable")
    assert_equal(missing["reason"], "intel_gpu_top not found", "Intel diagnostics missing command reason")

    failed_list = collect_intel_gpu_top_details(
        command_exists=lambda _command: True,
        command_env=lambda: {"TEST_ENV": "1"},
        run_command=lambda *_args, **_kwargs: SimpleNamespace(stdout="", stderr="list denied", returncode=1),
    )
    assert_equal(failed_list["available"], True, "Intel diagnostics installed command available")
    assert_equal(failed_list["list_available"], False, "Intel diagnostics failed list unavailable")
    assert_equal(failed_list["reason"], "list denied", "Intel diagnostics failed list reason")

    list_exception = collect_intel_gpu_top_details(
        command_exists=lambda _command: True,
        command_env=lambda: {},
        run_command=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert_equal(list_exception["reason"], "intel_gpu_top -L failed: boom", "Intel diagnostics list exception")

    list_calls = []

    def list_run(command, **kwargs):
        list_calls.append((list(command), dict(kwargs)))
        return SimpleNamespace(stdout="card0 Intel Arc\ncard1 Intel UHD\n", stderr="", returncode=0)

    sample = {
        "command": ["intel_gpu_top", "-J"],
        "returncode": 0,
        "stdout": 'noise {"engines":{"Render/3D":{"busy":55.0}}}',
        "stderr": "",
        "fallback_used": True,
        "error": "",
    }
    usable = collect_intel_gpu_top_details(
        command_exists=lambda _command: True,
        command_env=lambda: {"TEST_ENV": "1"},
        run_command=list_run,
        sample_attempt=lambda: dict(sample),
    )
    assert_equal(list_calls[0][0], ["intel_gpu_top", "-L"], "Intel diagnostics list command")
    assert_equal(list_calls[0][1]["timeout"], 5, "Intel diagnostics list timeout")
    assert_equal(list_calls[0][1]["env"], {"TEST_ENV": "1"}, "Intel diagnostics command environment")
    assert_equal(usable["devices"], [{"raw": "card0 Intel Arc"}, {"raw": "card1 Intel UHD"}], "Intel diagnostics devices")
    assert_equal(usable["json_sample_available"], True, "Intel diagnostics JSON sample available")
    assert_equal(usable["json_sample_metrics"], {"busy_percent": 55.0}, "Intel diagnostics JSON metrics")
    assert_equal(usable["json_sample_fallback_used"], True, "Intel diagnostics sample fallback flag")
    assert_equal(usable["usable"], True, "Intel diagnostics usable")

    permission = collect_intel_gpu_top_details(
        command_exists=lambda _command: True,
        command_env=lambda: {},
        run_command=list_run,
        sample_attempt=lambda: {
            "command": ["intel_gpu_top", "-J"],
            "returncode": 1,
            "stdout": "",
            "stderr": "permission denied opening PMU; CAP_PERFMON required",
            "fallback_used": False,
            "error": "",
        },
    )
    assert_true("CAP_PERFMON" in permission["reason"], "Intel diagnostics permission reason")
    assert_equal(permission["usable"], False, "Intel diagnostics permission failure unusable")

    malformed = collect_intel_gpu_top_details(
        command_exists=lambda _command: True,
        command_env=lambda: {},
        run_command=list_run,
        sample_attempt=lambda: {
            "command": ["intel_gpu_top", "-J"],
            "returncode": 0,
            "stdout": "not JSON",
            "stderr": "",
            "fallback_used": False,
            "error": "",
        },
    )
    assert_equal(
        malformed["reason"],
        "intel_gpu_top is installed, but JSON sample did not expose parseable busy counters",
        "Intel diagnostics malformed sample reason",
    )

    sample_calls = []

    def sample_run(command, **kwargs):
        sample_calls.append((list(command), dict(kwargs)))
        if "-d" in command:
            return SimpleNamespace(stdout="", stderr="target selector unsupported", returncode=1)
        return SimpleNamespace(stdout='{"engines":{"Render/3D":{"busy":25.0}}}', stderr="", returncode=0)

    fallback = intel_gpu_top_json_sample_attempt(
        command_exists=lambda _command: True,
        command_env=lambda: {"SAMPLE_ENV": "1"},
        run_command=sample_run,
    )
    assert_equal(len(sample_calls), 2, "Intel JSON sample fallback attempts")
    assert_equal(sample_calls[0][1]["timeout"], 3, "Intel JSON sample timeout")
    assert_equal(sample_calls[0][1]["env"], {"SAMPLE_ENV": "1"}, "Intel JSON sample environment")
    assert_equal(fallback["fallback_used"], True, "Intel JSON sample fallback used")
    assert_true("-d" not in fallback["command"], "Intel JSON fallback omits device selector")
    assert_true(bool(fallback["stdout"]), "Intel JSON fallback captures output")


def test_intel_gpu_sidecar_lifecycle_helpers() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        run_dir = Path(tmp)
        missing = start_intel_gpu_top_sidecar(
            stage_id="stage 1",
            stage_name="Stage 1",
            run_dir=run_dir,
            which_func=lambda command: None,
        )
        assert_true(missing is None, "intel sidecar missing binary")

        writes: list[tuple[Path, dict[str, object]]] = []

        def failing_popen(*args, **kwargs):
            raise RuntimeError("launch failed")

        failed = start_intel_gpu_top_sidecar(
            stage_id="stage 1",
            stage_name="Stage 1",
            run_dir=run_dir,
            which_func=lambda command: "/usr/bin/intel_gpu_top",
            popen_factory=failing_popen,
            json_writer=lambda path, payload: writes.append((path, payload)),
        )
        assert_true(failed is None, "intel sidecar launch failure")
        assert_equal(len(writes), 1, "intel sidecar launch failure summary write")
        assert_equal(writes[0][1]["available"], False, "intel sidecar launch failure availability")
        assert_true("launch failed" in str(writes[0][1]["error"]), "intel sidecar launch failure error")

        class FakeProcess:
            def __init__(self) -> None:
                self.terminated = False
                self.killed = False

            def poll(self):
                return None if not self.terminated else 0

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout=None) -> int:
                return 0

            def kill(self) -> None:
                self.killed = True

        process = FakeProcess()
        started = start_intel_gpu_top_sidecar(
            stage_id="Stage/2",
            stage_name="Stage 2",
            run_dir=run_dir,
            which_func=lambda command: "/usr/bin/intel_gpu_top",
            popen_factory=lambda *args, **kwargs: process,
            now_func=lambda: "2026-06-05T12:00:00-04:00",
        )
        assert_true(started is not None, "intel sidecar started")
        assert_equal((started or {})["stage_id"], "Stage/2", "intel sidecar stage id")
        assert_true(str((started or {})["raw_path"]).endswith("Stage_2.json"), "intel sidecar safe raw path")
        assert_equal((started or {})["started"], "2026-06-05T12:00:00-04:00", "intel sidecar started time")
        assert_true(not bool((started or {})["stderr_handle"].closed), "intel sidecar stderr open")

        stop_writes: list[tuple[Path, dict[str, object]]] = []
        summary = {"available": True, "stage_id": "Stage/2"}
        stopped = stop_intel_gpu_top_sidecar(
            started,
            summary_builder=lambda sidecar: summary,
            json_writer=lambda path, payload: stop_writes.append((path, payload)),
        )
        assert_equal(stopped, summary, "intel sidecar stop summary")
        assert_true(process.terminated, "intel sidecar process terminated")
        assert_true((started or {})["stderr_handle"].closed, "intel sidecar stderr closed")
        assert_equal(stop_writes[0][1], summary, "intel sidecar stop summary write")
        assert_true(stop_intel_gpu_top_sidecar(None) is None, "intel sidecar stop none")


def test_stability_event_helpers() -> None:
    event = create_stability_event(
        "gpu_target_utilization",
        "warning",
        "Power",
        "gpu_0_busy_percent",
        "target GPU did not sustain busy",
        {"gpu_index": 0},
    )
    assert_equal(event["category"], "gpu_target_utilization", "stability event category")
    assert_equal(event["details"]["gpu_index"], 0, "stability event details")
    assert_equal(
        event_signature(event),
        ("gpu_target_utilization", "gpu_0_busy_percent", "target GPU did not sustain busy"),
        "stability event signature",
    )
    duplicate = dict(event)
    duplicate["timestamp"] = "different"
    other = create_stability_event("worker_exit", "error", "Power", "gpu", "worker exited")
    assert_equal(len(dedupe_events([event, duplicate, other])), 2, "stability event dedupe")
    assert_equal(new_unique_events([duplicate, other], [event]), [other], "stability event new unique filter")
    samples = [
        Sample(0.0, {"gpu_0_busy_percent": 0.0}),
        Sample(1.0, {"gpu_0_busy_percent": 80.0}),
        Sample(2.0, {"gpu_0_busy_percent": 90.0}),
        Sample(3.0, {"gpu_0_busy_percent": 40.0}),
        Sample(4.0, {"gpu_0_busy_percent": 95.0}),
    ]
    assert_equal(
        threshold_run_seconds(samples, "gpu_0_busy_percent", 75.0, 1.0),
        2.0,
        "threshold run seconds",
    )


def test_sensor_event_helpers() -> None:
    samples = [
        Sample(
            0.0,
            {
                "cpu_temp_c": 101.0,
                "gpu_0_temp_core_c": 88.0,
                "gpu_0_temp_hotspot_c": 106.0,
                "gpu_0_temp_memory_c": 96.0,
            },
        )
    ]

    def thresholds(key: str):
        if key == "cpu_temp_c":
            return {"warn_c": 95.0, "fail_c": 100.0, "source": "cpu_hw"}
        return None

    events = stage_sensor_events(
        samples=samples,
        stage_name="Power",
        metric_thresholds=thresholds,
        abort_on_fail_threshold=False,
        gpu_thermal_throttle_hint_c=85.0,
        gpu_hotspot_warn_c=100.0,
        gpu_hotspot_fail_c=105.0,
        gpu_memory_temp_warn_c=94.0,
        gpu_memory_temp_fail_c=100.0,
    )
    assert_equal(
        [event["category"] for event in events],
        ["cpu_temperature", "gpu_thermal_throttle_zone", "gpu_hotspot", "gpu_memory_temperature"],
        "sensor event categories",
    )
    assert_equal(events[0]["severity"], "warning", "sensor fail threshold warning when abort disabled")
    assert_equal(events[0]["details"]["threshold_source"], "cpu_hw", "sensor threshold source")
    assert_equal(events[1]["details"]["threshold_source"], "suite_throttle_hint", "sensor throttle hint source")
    assert_equal(events[2]["details"]["threshold"], 105.0, "sensor hotspot default fail threshold")
    abort_events = stage_sensor_events(
        samples=samples,
        stage_name="Power",
        metric_thresholds=thresholds,
        abort_on_fail_threshold=True,
        gpu_thermal_throttle_hint_c=85.0,
        gpu_hotspot_warn_c=100.0,
        gpu_hotspot_fail_c=105.0,
        gpu_memory_temp_warn_c=94.0,
        gpu_memory_temp_fail_c=100.0,
    )
    assert_equal(abort_events[0]["severity"], "error", "sensor fail threshold error when abort enabled")
    assert_equal(abort_events[2]["severity"], "error", "sensor hotspot fail threshold error when abort enabled")


def test_gpu_stage_event_helpers() -> None:
    backend_profiles = {
        "glxgears": {"load_class": "compatibility", "recommended_for_saturation": False},
        "python_vulkan_compute": {"load_class": "high_load", "recommended_for_saturation": False},
        "python_vulkan_transfer": {"load_class": "diagnostic", "recommended_for_saturation": False},
        "preferred": {"load_class": "high_load", "recommended_for_saturation": True},
    }

    def backend_profile(name: str):
        return backend_profiles.get(name, {})

    backend_events = gpu_backend_effectiveness_events(
        target_gpus={
            0: {"target_id": "0000:01:00.0", "workloads": ["gpu_3d"], "backends": ["glxgears"], "device_class": "discrete"},
            1: {"target_id": "0000:02:00.0", "workloads": ["gpu_3d"], "backends": ["python_vulkan_compute"], "device_class": "discrete"},
            2: {"target_id": "0000:03:00.0", "workloads": ["gpu_3d"], "backends": ["python_vulkan_transfer"], "device_class": "discrete"},
            3: {"target_id": "0000:04:00.0", "workloads": ["gpu_3d"], "backends": ["preferred"], "device_class": "discrete"},
        },
        samples=[
            Sample(
                0.0,
                {
                    "gpu_0_busy_percent": 2.0,
                    "gpu_1_busy_percent": 40.0,
                    "gpu_1_power_w": 100.0,
                    "gpu_2_busy_percent": 20.0,
                    "gpu_2_power_w": 45.0,
                    "gpu_3_busy_percent": 1.0,
                },
            ),
            Sample(
                1.0,
                {
                    "gpu_0_busy_percent": 3.0,
                    "gpu_1_busy_percent": 60.0,
                    "gpu_1_power_w": 130.0,
                    "gpu_2_busy_percent": 30.0,
                    "gpu_2_power_w": 55.0,
                    "gpu_3_busy_percent": 1.0,
                },
            ),
        ],
        stage_name="Vulkan",
        backend_profile_lookup=backend_profile,
        gpu_3d_backend_preference="auto",
        gpu_3d_backend_resolved="python_vulkan_compute",
    )
    assert_equal(
        [event["category"] for event in backend_events],
        ["gpu_backend_effectiveness", "gpu_backend_effectiveness", "gpu_backend_effectiveness"],
        "GPU backend effectiveness categories",
    )
    assert_true("smoke test" in backend_events[0]["message"], "GPU compatibility backend warning")
    assert_true("under-drove" in backend_events[1]["message"], "GPU high-load underdrive warning")
    assert_equal(backend_events[1]["details"]["expected_avg_busy_percent"], 70.0, "GPU high-load expected avg")
    assert_equal(backend_events[2]["severity"], "info", "GPU diagnostic backend info")
    assert_true("shader power saturation" in backend_events[2]["message"], "GPU diagnostic low power wording")

    utilization_events = target_gpu_utilization_events(
        target_gpus={
            0: {"target_id": "0000:01:00.0", "workloads": ["gpu_3d"], "backends": ["python_vulkan_compute"]},
            1: {"target_id": "0000:02:00.0", "workloads": ["vram"], "backends": ["python_opencl"]},
            2: {"target_id": "0000:03:00.0", "workloads": ["vram"], "backends": ["python_opencl"]},
        },
        samples=[
            Sample(0.0, {"gpu_0_busy_percent": 50.0, "gpu_2_memory_busy_percent": 10.0}),
            Sample(1.0, {"gpu_0_busy_percent": 95.0, "gpu_2_memory_busy_percent": 90.0}),
            Sample(2.0, {"gpu_0_busy_percent": 40.0, "gpu_2_memory_busy_percent": 20.0}),
        ],
        stage_name="Power",
        telemetry_interval_seconds=1.0,
        target_busy_threshold=90.0,
        target_busy_sustain=2.0,
        target_mem_busy_threshold=80.0,
        target_mem_busy_sustain=2.0,
    )
    assert_equal(
        [event["category"] for event in utilization_events],
        ["gpu_target_utilization", "gpu_target_memory_utilization", "gpu_target_memory_utilization"],
        "GPU utilization event categories",
    )
    assert_equal(utilization_events[0]["details"]["max_busy_percent"], 95.0, "GPU utilization max busy")
    assert_equal(utilization_events[1]["severity"], "warning", "GPU memory busy missing telemetry warning")
    assert_equal(utilization_events[2]["details"]["max_memory_busy_percent"], 90.0, "GPU memory busy max")

    one_gib = 1024 ** 3
    events = vram_target_attainment_events(
        worker_results=[
            {
                "kind": "gpu",
                "mode": "vram",
                "target_id": "0000:01:00.0",
                "gpu_index": 0,
                "target_vram_bytes": 10 * one_gib,
                "allocated_vram_bytes": 5 * one_gib,
                "verification_passes": 0,
                "device_class": "discrete",
                "verification_interval_seconds": 20,
                "phase": "steady",
            }
        ],
        samples=[Sample(1.0, {"gpu_0_vram_used_gb": 5.0})],
        stage_name="SSE + VRAM",
        stage_duration_seconds=90.0,
    )
    assert_equal(
        [event["category"] for event in events],
        ["gpu_vram_target_attainment", "gpu_vram_verification_coverage"],
        "VRAM target miss categories",
    )
    assert_equal(events[0]["severity"], "error", "VRAM target miss severity")
    assert_equal(events[0]["details"]["allocation_ratio"], 0.5, "VRAM target allocation ratio")
    assert_equal(events[1]["details"]["verification_threshold"], 3, "VRAM discrete verification threshold")

    telemetry_events = vram_target_attainment_events(
        worker_results=[
            {
                "kind": "gpu",
                "workload": "vram",
                "target_id": "0000:02:00.0",
                "gpu_index": 1,
                "active_target_vram_bytes": 10 * one_gib,
                "allocated_vram_bytes": 9 * one_gib,
                "verification_passes": 3,
                "device_class": "discrete",
            }
        ],
        samples=[Sample(1.0, {"gpu_1_vram_used_gb": 3.0})],
        stage_name="SSE + VRAM",
        stage_duration_seconds=90.0,
    )
    assert_equal(len(telemetry_events), 1, "VRAM telemetry discrepancy event count")
    assert_equal(telemetry_events[0]["category"], "gpu_vram_telemetry_discrepancy", "VRAM telemetry discrepancy")
    assert_equal(telemetry_events[0]["details"]["target_attainment"], "worker_verified", "VRAM worker verified flag")

    integrated_events = vram_target_attainment_events(
        worker_results=[
            {
                "kind": "gpu",
                "mode": "vram",
                "target_id": "0000:03:00.0",
                "gpu_index": 2,
                "target_vram_bytes": one_gib,
                "allocated_vram_bytes": one_gib,
                "verification_passes": 1,
                "device_class": "integrated",
            }
        ],
        samples=[Sample(1.0, {"gpu_2_vram_used_gb": 1.0})],
        stage_name="SSE + VRAM",
        stage_duration_seconds=90.0,
    )
    assert_equal(integrated_events[0]["category"], "gpu_vram_verification_coverage", "VRAM integrated thin coverage")
    assert_equal(integrated_events[0]["details"]["verification_threshold"], 2, "VRAM integrated verification threshold")


def test_gpu_stage_target_helpers() -> None:
    assert_equal(gpu_index_from_metric_key("gpu_12_temp_core_c"), 12, "gpu index from metric key")
    assert_equal(gpu_index_from_metric_key("bad"), 0, "gpu index fallback")
    process_targets = stage_target_gpu_details_from_processes(
        [
            SimpleNamespace(
                gpu_spec=SimpleNamespace(
                    gpu_index=1,
                    target_id="0000:01:00.0",
                    card="card1",
                    workload="gpu_3d",
                    backend="python_vulkan_compute",
                    device_class="discrete",
                )
            ),
            SimpleNamespace(
                gpu_spec=SimpleNamespace(
                    gpu_index=1,
                    target_id="0000:01:00.0",
                    card="card1",
                    workload="vram",
                    backend="python_vulkan_transfer",
                    device_class="discrete",
                )
            ),
            SimpleNamespace(gpu_spec=None),
        ]
    )
    assert_equal(process_targets[1]["workloads"], ["gpu_3d", "vram"], "process target workloads")
    assert_equal(
        process_targets[1]["backends"],
        ["python_vulkan_compute", "python_vulkan_transfer"],
        "process target backends",
    )
    worker_targets = stage_target_gpu_details_from_worker_dicts(
        [
            {
                "gpu_index": "0",
                "target_id": "0000:00:02.0",
                "workload": "gpu_3d",
                "backend": "python_egl_gles2",
                "device_class": "integrated",
            },
            {
                "gpu_index": "0",
                "target_id": "0000:00:02.0",
                "workload": "gpu_3d",
                "backend": "python_egl_gles2",
                "device_class": "integrated",
            },
        ]
    )
    assert_equal(worker_targets[0]["workloads"], ["gpu_3d"], "worker target deduped workloads")
    assert_equal(worker_targets[0]["backends"], ["python_egl_gles2"], "worker target deduped backends")


def test_worker_evidence_helpers() -> None:
    assert_equal(read_log_tail(None), "", "missing log tail")
    with TemporaryDirectory(dir="/tmp") as tmp:
        path = Path(tmp) / "worker.stderr.log"
        path.write_text("  one\ntwo\nthree  ", encoding="utf-8")
        assert_equal(read_log_tail(str(path)), "one\ntwo\nthree", "worker log stripped")
        assert_equal(read_log_tail(str(path), max_chars=5), "three", "worker log tail")
        assert_equal(read_log_tail(str(Path(tmp) / "missing.log")), "", "missing worker log")
    gpu_spec = SimpleNamespace(
        backend="python_vulkan_compute",
        backend_api_family="Vulkan",
        suite_scaling_mode="parametric",
        suite_verification="compute_readback",
        profile_mode="steady",
        profile_intensity="extreme",
        workload="gpu_3d",
        gpu_index=2,
        card="card2",
        slot="0000:02:00.0",
        target_id="0000:02:00.0",
        target_vram_bytes=1024,
        tuning_step=1,
        process_count=2,
        resolved_device_name="GPU",
        selection_ambiguous=False,
        device_class="discrete",
    )
    entry = SimpleNamespace(
        kind="gpu",
        result_path="/tmp/result.json",
        stdout_path="/tmp/stdout.log",
        stderr_path="/tmp/stderr.log",
        gpu_spec=gpu_spec,
    )
    payload = apply_worker_entry_context({"status": "ok"}, entry, return_code=-9, stdout_tail="out", stderr_tail="err")
    assert_equal(payload["backend"], "python_vulkan_compute", "worker payload backend")
    assert_equal(payload["observed_exit_signal"], 9, "worker payload signal")
    assert_equal(payload["status"], "crashed", "worker payload crashed status")
    assert_equal(payload["reported_status"], "ok", "worker payload reported status")
    assert_equal(payload["stdout_tail"], "out", "worker payload stdout tail")
    fallback = fallback_worker_payload(entry, 0, stdout_tail="done")
    assert_equal(fallback["status"], "ok", "fallback worker ok status")
    assert_equal(fallback["stdout_tail"], "done", "fallback worker stdout tail")
    exit_events = worker_result_events_from_payload(
        {"kind": "gpu", "observed_exit_code": 12},
        "Power",
        entry_kind="gpu",
        backend_name="python_vulkan_compute",
        backend_load_class="high_load",
    )
    assert_equal(exit_events[0]["category"], "worker_exit", "worker result exit event")
    assert_equal(exit_events[0]["severity"], "error", "worker result exit severity")
    runtime_events = worker_result_events_from_payload(
        {
            "kind": "gpu",
            "status": "error",
            "error_count": 2,
            "child_failure_count": 2,
            "suite_verification": "telemetry_only",
        },
        "Smoke",
        entry_kind="gpu",
        backend_name="glxgears",
        backend_load_class="compatibility",
    )
    assert_equal(runtime_events[0]["category"], "backend_runtime_failure", "worker runtime failure event")
    assert_equal(runtime_events[0]["severity"], "warning", "compat runtime failure warning")
    allocation_events = worker_result_events_from_payload(
        {
            "kind": "gpu",
            "backend": "python_opencl",
            "target_vram_bytes": 1000,
            "allocated_vram_bytes": 900,
            "selection_ambiguous": True,
        },
        "VRAM",
        entry_kind="gpu",
        backend_name="python_opencl",
        backend_load_class="high_load",
    )
    assert_equal(
        [event["category"] for event in allocation_events],
        ["allocation_shortfall", "device_selection"],
        "worker allocation and selection events",
    )


def test_gpu_worker_state_helpers() -> None:
    settings = SimpleNamespace(
        gpu_safe_mode=True,
        gpu_internal_ramp_step_seconds=10.0,
        gpu_safe_start_load_fraction=0.25,
    )
    assert_equal(round(current_internal_load_fraction(settings, 0.0), 3), 0.25, "initial GPU load fraction")
    assert_equal(round(current_internal_load_fraction(settings, 30.0), 3), 1.0, "final GPU load fraction")
    direct_settings = SimpleNamespace(gpu_safe_mode=False)
    assert_equal(current_internal_load_fraction(direct_settings, 0.0), 1.0, "unsafe mode load fraction")
    gpu_spec = SimpleNamespace(
        backend="python_vulkan_compute",
        workload="gpu_3d",
        draw_count=1000,
        clear_passes=0,
        target_vram_bytes=1024 * 1024 * 1024,
        shader_iterations=42,
        device_class="discrete",
    )
    planned_3d = planned_internal_gpu_worker_state(settings, gpu_spec, 0.0)
    assert_equal(planned_3d["active_draw_count"], 250, "planned draw count ramp")
    assert_equal(planned_3d["active_buffer_bytes"], 256 * 1024 * 1024, "planned active buffer ramp")
    assert_equal(planned_3d["active_compute_rounds"], 42, "planned compute rounds")
    vram_spec = SimpleNamespace(
        backend="python_opencl",
        workload="vram",
        draw_count=0,
        clear_passes=0,
        target_vram_bytes=2 * 1024 * 1024 * 1024,
        shader_iterations=0,
        device_class="discrete",
    )
    assert_equal(
        planned_internal_gpu_worker_state(settings, vram_spec, 1.0)["active_phase"],
        "allocation_only",
        "planned VRAM allocation phase",
    )
    assert_equal(
        planned_internal_gpu_worker_state(settings, vram_spec, 20.0)["active_phase"],
        "fill",
        "planned VRAM fill phase",
    )
    assert_equal(
        planned_internal_gpu_worker_state(settings, vram_spec, 60.0)["active_phase"],
        "verify",
        "planned VRAM verify phase",
    )


def test_gpu_worker_plan_helpers() -> None:
    worker = GpuWorkerSpec(
        workload="gpu_3d",
        backend="python_vulkan_compute",
        gpu_index=2,
        card="/dev/dri/card2",
        slot="0000:02:00.0",
        target_id="0000:02:00.0",
        command=["python", "native/vulkan_compute_worker.py"],
        draw_count=1024,
        shader_iterations=64,
        surface_size=2048,
        target_vram_bytes=4 * 1024 ** 3,
        tuning_step=1,
        backend_api_family="Vulkan",
        suite_scaling_mode="parametric",
        suite_verification="compute_readback",
        process_count=1,
        resolved_device_name="RTX 5090",
        selection_ambiguous=False,
        device_class="discrete",
        profile_mode="steady",
        profile_intensity="extreme",
        compute_variant="hash",
    )
    serialized = serialize_gpu_worker_spec(worker)
    assert_equal(serialized["backend"], "python_vulkan_compute", "worker plan backend")
    assert_equal(serialized["target_id"], "0000:02:00.0", "worker plan target")
    assert_equal(serialized["target_vram_bytes"], 4 * 1024 ** 3, "worker plan VRAM bytes")
    assert_true("command" not in serialized, "worker plan serialization excludes launch command")


def test_gpu_worker_param_helpers() -> None:
    discrete_target = {"vram_total": 24 * 1024 ** 3}
    large_target = {"vram_total": 64 * 1024 ** 3}
    params = {"capability": {"device_class": "discrete", "load_scale": 1.2}}
    integrated_params = {"capability": {"device_class": "integrated", "load_scale": 1.0}}

    assert_equal(
        vulkan_transfer_buffer_bytes(discrete_target, params, safe_mode_enabled=True),
        384 * 1024 * 1024,
        "Vulkan transfer safe-mode buffer cap",
    )
    assert_equal(
        vulkan_compute_buffer_bytes(
            discrete_target,
            params,
            normalized_variant="hash",
            safe_mode_enabled=True,
            cap_gpu_vram_target_bytes=lambda _target, requested: requested,
        ),
        256 * 1024 * 1024,
        "Vulkan hash safe-mode buffer cap",
    )
    assert_equal(
        vulkan_compute_buffer_bytes(
            large_target,
            params,
            normalized_variant="stateful_memory",
            allocation_percent=50,
            safe_mode_enabled=True,
            cap_gpu_vram_target_bytes=lambda _target, requested: min(requested, 40 * 1024 ** 3),
        ),
        32 * 1024 * 1024 * 1024,
        "Vulkan stateful percent allocation uses cap callback",
    )
    assert_equal(
        vulkan_compute_buffer_bytes(
            None,
            integrated_params,
            normalized_variant="stateful_memory",
            allocation_percent=50,
            safe_mode_enabled=True,
            cap_gpu_vram_target_bytes=lambda _target, requested: requested,
        ),
        1024 * 1024 * 1024,
        "Vulkan stateful percent allocation fallback without VRAM total",
    )
    assert_equal(
        vulkan_compute_rounds(
            params,
            profile_intensity_factor=1.3,
            normalized_variant="stress_hash",
            safe_mode_enabled=True,
        ),
        160,
        "Vulkan stress rounds safe-mode cap",
    )
    assert_equal(
        vulkan_compute_rounds(
            integrated_params,
            profile_intensity_factor=0.7,
            normalized_variant="hash",
            safe_mode_enabled=True,
        ),
        8,
        "Vulkan hash rounds integrated scale",
    )
    assert_equal(
        vulkan_compute_dispatch_repeats(large_target, normalized_variant="stress_hash"),
        8,
        "Vulkan stress dispatch repeats high VRAM",
    )
    assert_equal(
        vulkan_compute_dispatch_repeats(discrete_target, normalized_variant="hash"),
        1,
        "Vulkan non-stress dispatch repeats",
    )

    baseline = gpu_worker_baseline_params(
        discrete_target,
        capability={"device_class": "discrete", "vram_total": 24 * 1024 ** 3, "load_scale": 1.4},
        backend="python_egl_gles2",
        workload="gpu_3d",
        normalized_profile_intensity="extreme",
        profile_intensity_factor=1.3,
        profile_mode="steady",
        safe_mode_enabled=True,
        safe_max_load_scale=1.0,
    )
    assert_equal(baseline["surface_size"], 2688, "GPU worker baseline surface")
    assert_equal(baseline["draw_count"], 559, "GPU worker baseline draw count")
    assert_equal(baseline["shader_iterations"], 103, "GPU worker baseline shader iterations")
    assert_equal(baseline["effective_load_scale"], 1.3, "GPU worker baseline effective load")

    opencl_baseline = gpu_worker_baseline_params(
        discrete_target,
        capability={"device_class": "discrete", "vram_total": 24 * 1024 ** 3, "load_scale": 1.0},
        backend="python_opencl_compute",
        workload="gpu_3d",
        normalized_profile_intensity="extreme",
        profile_intensity_factor=1.3,
        profile_mode="burst",
        safe_mode_enabled=True,
        safe_max_load_scale=1.0,
    )
    assert_true(opencl_baseline["draw_count"] > baseline["draw_count"] * 0.8, "OpenCL baseline boosted relative load")
    assert_equal(opencl_baseline["effective_intensity"], "extreme", "GPU worker baseline effective intensity")

    vram_baseline = gpu_worker_baseline_params(
        {"vram_total": 1536 * 1024 ** 2},
        capability={"device_class": "integrated", "vram_total": 1536 * 1024 ** 2, "load_scale": 0.9, "compute_units": 8},
        backend="python_egl_gles2",
        workload="vram",
        safe_mode_enabled=True,
        safe_max_load_scale=1.0,
    )
    assert_equal(vram_baseline["texture_side"], 2048, "GPU worker VRAM small target texture cap")
    assert_true(vram_baseline["draw_count"] >= 8, "GPU worker VRAM draw floor")

    tuned = gpu_worker_tuned_params(
        baseline,
        tuning_step=2,
        backend="python_egl_gles2",
        workload="gpu_3d",
        safe_mode_enabled=True,
    )
    assert_equal(tuned["surface_size"], 3712, "GPU worker tuned surface")
    assert_equal(tuned["draw_count"], 879, "GPU worker tuned draw count")
    assert_equal(tuned["shader_iterations"], 143, "GPU worker tuned shader iterations")

    amd_integrated_tuned = gpu_worker_tuned_params(
        {
            "surface_size": 2048,
            "draw_count": 300,
            "shader_iterations": 120,
            "texture_side": 4096,
            "clear_passes": 5,
            "capability": {"device_class": "integrated", "vendor": "amd", "vram_total": 512 * 1024 ** 2},
        },
        tuning_step=3,
        backend="python_egl_gles2",
        workload="gpu_3d",
        safe_mode_enabled=True,
    )
    assert_equal(amd_integrated_tuned["surface_size"], 1536, "AMD integrated safe surface cap")
    assert_equal(amd_integrated_tuned["draw_count"], 112, "AMD integrated safe draw cap")
    assert_equal(amd_integrated_tuned["shader_iterations"], 48, "AMD integrated safe shader cap")
    assert_equal(amd_integrated_tuned["clear_passes"], 2, "AMD integrated safe clear cap")


def test_vram_policy_helpers() -> None:
    assert_equal(
        capacity_vram_request_cap_bytes(1024 ** 3),
        768 * 1024 ** 2,
        "VRAM capacity cap 1 GiB",
    )
    assert_equal(
        capacity_vram_request_cap_bytes(2 * 1024 ** 3),
        2 * 1024 ** 3 - int(2 * 1024 ** 3 * 0.15),
        "VRAM capacity cap 2 GiB",
    )
    assert_equal(
        cap_gpu_vram_target_bytes(
            requested_bytes=10 * 1024 ** 3,
            target_total=8 * 1024 ** 3,
            safe_mode_enabled=True,
            safe_max_vram_percent=50,
        ),
        4 * 1024 ** 3,
        "VRAM safe percent cap",
    )
    assert_equal(
        shared_memory_gpu_target_total_bytes(
            opencl_global_mem_bytes=12 * 1024 ** 3,
            system_total=32 * 1024 ** 3,
            system_available=20 * 1024 ** 3,
            memory_allocation_percent=80,
        ),
        2 * 1024 ** 3,
        "shared-memory GPU budget memory stage",
    )
    assert_equal(
        shared_memory_gpu_target_total_bytes(
            opencl_global_mem_bytes=0,
            system_total=16 * 1024 ** 3,
            system_available=8 * 1024 ** 3,
            concurrent_gpu_3d=True,
            stage_duration_seconds=120,
        ),
        int(16 * 1024 ** 3 * 0.15),
        "shared-memory GPU short mixed-stage budget",
    )
    assert_true(
        opencl_device_looks_like_shared_memory(
            device_class="integrated",
            opencl_global_mem_bytes=0,
            system_total=0,
            explicit_vram_total=0,
        ),
        "integrated OpenCL device treated as shared memory",
    )
    assert_true(
        opencl_device_looks_like_shared_memory(
            device_class="",
            opencl_global_mem_bytes=13 * 1024 ** 3,
            system_total=16 * 1024 ** 3,
            explicit_vram_total=0,
        ),
        "large OpenCL global memory treated as shared memory",
    )
    assert_equal(
        fallback_vram_total_for_target({"vendor": "nvidia", "name": "RTX"}),
        8 * 1024 ** 3,
        "fallback NVIDIA VRAM total",
    )
    assert_equal(
        target_vram_allocation_bytes(
            allocation_percent=90,
            target={"vram_total": 1024 ** 3},
            target_total=1024 ** 3,
            device_class="integrated",
            concurrent_gpu_3d=True,
        ),
        int(1024 ** 3 * 0.40),
        "integrated mixed-stage VRAM cap",
    )
    amd_a = {"vendor": "amd", "vendor_id": "1002", "driver": "amdgpu"}
    amd_b = {"vendor": "amd", "vendor_id": "1002", "driver": "amdgpu"}
    integrated = {"vendor": "intel", "vram_total": 1024 ** 3}
    assert_equal(
        amd_discrete_target_count(
            [
                (amd_a, {"device_class": "discrete"}),
                (amd_b, {"device_class": "discrete"}),
                (integrated, {"device_class": "integrated"}),
            ]
        ),
        2,
        "AMD discrete target count",
    )
    assert_true(
        skip_concurrent_vram_worker_for_target(
            target=amd_a,
            capability={"device_class": "discrete"},
            concurrent_gpu_3d=True,
            concurrent_amd_discrete_target_count=2,
            vram_backend="python_opencl",
        ),
        "multi-AMD OpenCL VRAM skip policy",
    )
    assert_true(
        skip_concurrent_vram_worker_for_target(
            target=integrated,
            capability={"device_class": "integrated"},
            concurrent_gpu_3d=True,
            concurrent_amd_discrete_target_count=0,
            vram_backend="python_opencl",
        ),
        "integrated mixed-stage VRAM skip policy",
    )
    assert_true(
        use_vulkan_vram_worker_for_target(
            target=amd_a,
            capability={"device_class": "discrete"},
            concurrent_gpu_3d=True,
            concurrent_amd_discrete_target_count=2,
            resolved_vram_backend="python_opencl",
            vulkan_vram_backend_available=True,
            vulkan_vram_target_supported=True,
        ),
        "multi-AMD OpenCL VRAM routes to Vulkan when supported",
    )
    assert_true(
        not use_vulkan_vram_worker_for_target(
            target=amd_a,
            capability={"device_class": "discrete"},
            concurrent_gpu_3d=True,
            concurrent_amd_discrete_target_count=2,
            resolved_vram_backend="python_opencl",
            vulkan_vram_backend_available=False,
            vulkan_vram_target_supported=True,
        ),
        "multi-AMD Vulkan routing requires available backend",
    )


def test_vram_orchestration_helpers() -> None:
    def unexpected(*_args, **_kwargs):
        raise AssertionError("unexpected VRAM discovery call")

    explicit = resolve_target_vram_allocation_bytes(
        allocation_percent=50,
        target={"target_id": "gpu0", "vram_total": 8 * 1024 ** 3},
        memory_allocation_percent=0,
        concurrent_gpu_3d=False,
        stage_duration_seconds=0,
        opencl_device_for_target=unexpected,
        capability_for_target=lambda _target: {"device_class": "discrete"},
        system_memory_total=unexpected,
        system_memory_available=unexpected,
        sysfs_vram_totals=unexpected,
    )
    assert_equal(explicit, 4 * 1024 ** 3, "VRAM resolver explicit target capacity")

    system_total = 16 * 1024 ** 3
    shared_budget = shared_memory_gpu_target_total_bytes(
        opencl_global_mem_bytes=16 * 1024 ** 3,
        system_total=system_total,
        system_available=8 * 1024 ** 3,
        memory_allocation_percent=80,
    )
    shared = resolve_target_vram_allocation_bytes(
        allocation_percent=50,
        target={"target_id": "igpu", "vendor": "intel", "vram_total": 0},
        memory_allocation_percent=80,
        concurrent_gpu_3d=False,
        stage_duration_seconds=600,
        opencl_device_for_target=lambda _target: {"global_mem_bytes": system_total},
        capability_for_target=lambda _target: {"device_class": "integrated"},
        system_memory_total=lambda: system_total,
        system_memory_available=lambda: 8 * 1024 ** 3,
        sysfs_vram_totals=unexpected,
    )
    assert_equal(shared, int(shared_budget * 0.50), "VRAM resolver shared-memory budget")

    sysfs = resolve_target_vram_allocation_bytes(
        allocation_percent=25,
        target=None,
        memory_allocation_percent=0,
        concurrent_gpu_3d=False,
        stage_duration_seconds=0,
        opencl_device_for_target=unexpected,
        capability_for_target=unexpected,
        system_memory_total=unexpected,
        system_memory_available=unexpected,
        sysfs_vram_totals=lambda: [2 * 1024 ** 3, 4 * 1024 ** 3],
    )
    assert_equal(sysfs, 1024 ** 3, "VRAM resolver largest sysfs capacity")

    default = resolve_target_vram_allocation_bytes(
        allocation_percent=90,
        target=None,
        memory_allocation_percent=0,
        concurrent_gpu_3d=False,
        stage_duration_seconds=0,
        opencl_device_for_target=unexpected,
        capability_for_target=unexpected,
        system_memory_total=unexpected,
        system_memory_available=unexpected,
        sysfs_vram_totals=lambda: [],
    )
    assert_equal(default, 512 * 1024 ** 2, "VRAM resolver unknown-capacity default")

    fallback = resolve_target_vram_allocation_bytes(
        allocation_percent=50,
        target={"target_id": "nvidia0", "vendor": "nvidia", "vram_total": 0},
        memory_allocation_percent=0,
        concurrent_gpu_3d=False,
        stage_duration_seconds=0,
        opencl_device_for_target=lambda _target: None,
        capability_for_target=lambda _target: {"device_class": "discrete"},
        system_memory_total=unexpected,
        system_memory_available=unexpected,
        sysfs_vram_totals=unexpected,
    )
    assert_equal(fallback, 4 * 1024 ** 3, "VRAM resolver vendor fallback capacity")

    amd_target = {"target_id": "amd0", "vendor": "amd", "vram_total": 16 * 1024 ** 3}
    assert_true(
        not route_vulkan_vram_worker_for_target(
            target=amd_target,
            concurrent_gpu_3d=False,
            concurrent_amd_discrete_target_count=2,
            resolved_vram_backend="python_opencl",
            capability_for_target=unexpected,
            vram_backend_available=unexpected,
            gpu_backend_target_supported=unexpected,
        ),
        "VRAM routing inactive mixed stage",
    )
    routing_calls = []
    routed = route_vulkan_vram_worker_for_target(
        target=amd_target,
        concurrent_gpu_3d=True,
        concurrent_amd_discrete_target_count=2,
        resolved_vram_backend="python_opencl",
        capability_for_target=lambda _target: {"device_class": "discrete"},
        vram_backend_available=lambda backend: routing_calls.append(("available", backend)) or True,
        gpu_backend_target_supported=lambda backend, target, workload: routing_calls.append(
            ("supported", backend, target["target_id"], workload)
        ) or True,
    )
    assert_true(routed, "VRAM routing uses Vulkan for supported multi-AMD target")
    assert_equal(routing_calls[0], ("available", "python_vulkan_compute"), "VRAM routing backend check")
    assert_equal(routing_calls[1][-1], "vram", "VRAM routing target workload")

    amd_target_1 = {"target_id": "amd1", "vendor": "amd", "vram_total": 16 * 1024 ** 3}
    labels = concurrent_vram_skip_target_labels(
        targets=[amd_target, amd_target_1],
        concurrent_gpu_3d=True,
        vram_backend="python_opencl",
        capability_for_target=lambda _target: {"device_class": "discrete"},
        vram_backend_available=lambda _backend: True,
        gpu_backend_target_supported=lambda _backend, target, _workload: target["target_id"] == "amd0",
    )
    assert_equal(labels, ["amd1"], "VRAM routing labels unsupported multi-AMD target")

    integrated_labels = concurrent_vram_skip_target_labels(
        targets=[{"card": "card9", "vendor": "intel", "vram_total": 1024 ** 3}],
        concurrent_gpu_3d=True,
        vram_backend="python_opencl",
        capability_for_target=lambda _target: {"device_class": "integrated"},
        vram_backend_available=unexpected,
        gpu_backend_target_supported=unexpected,
    )
    assert_equal(integrated_labels, ["card9"], "VRAM routing integrated skip label")


def test_gpu_backend_resolution_helpers() -> None:
    resolution = {
        "backend": "python_opencl_compute",
        "candidate_reports": [
            {"backend": "missing_backend", "available": False, "support": None},
            {
                "backend": "python_opencl_compute",
                "available": True,
                "support": {
                    "supported": False,
                    "supported_targets": [
                        {"target_label": "0000:01:00.0"},
                    ],
                    "unsupported_targets": [
                        {"target_label": "0000:02:00.0", "reason": "no matching OpenCL GPU device found"},
                    ],
                },
            },
        ],
        "support": {
            "supported": False,
            "supported_targets": [
                {"target_label": "0000:01:00.0"},
            ],
            "unsupported_targets": [
                {"target_label": "0000:02:00.0", "reason": "no matching OpenCL GPU device found"},
            ],
        },
        "partial": True,
    }
    best_report = best_partial_gpu_backend_report(resolution)
    assert_equal(best_report["backend"], "python_opencl_compute", "best partial GPU backend report")
    assert_equal(
        unsupported_gpu_target_issue(workload_label="3D", resolution=resolution, preference="auto"),
        "3D backend 'python_opencl_compute' cannot support all requested GPU targets; supported: 0000:01:00.0; unsupported: 0000:02:00.0 (no matching OpenCL GPU device found)",
        "unsupported GPU target issue text",
    )
    assert_equal(
        partial_gpu_target_warning(workload_label="3D", resolution=resolution),
        "3D backend 'python_opencl_compute' will run on supported GPU targets only; running: 0000:01:00.0; skipped: 0000:02:00.0 (no matching OpenCL GPU device found)",
        "partial GPU target warning text",
    )
    messages = gpu_backend_resolution_messages(
        workload_label="3D",
        resolution=resolution,
        preference="auto",
    )
    assert_equal(
        messages["issue"],
        "3D backend 'python_opencl_compute' cannot support all requested GPU targets; supported: 0000:01:00.0; unsupported: 0000:02:00.0 (no matching OpenCL GPU device found)",
        "GPU backend resolution messages issue",
    )
    assert_equal(
        messages["warning"],
        "3D backend 'python_opencl_compute' will run on supported GPU targets only; running: 0000:01:00.0; skipped: 0000:02:00.0 (no matching OpenCL GPU device found)",
        "GPU backend resolution messages warning",
    )
    assert_equal(
        gpu_excluded_targets_summary(gpu_3d_resolution=resolution, vram_resolution={"support": None}),
        {"gpu_3d": ["0000:02:00.0"], "vram": []},
        "excluded target summary",
    )
    assert_equal(
        gpu_backend_usage_summary(
            cpu_backend="cpu_native_helper",
            memory_backend="stress_ng",
            gpu_3d_resolution=resolution,
            vram_resolution={"backend": "none"},
            cpu_enabled=True,
            memory_enabled=False,
            gpu_3d_enabled=True,
            vram_enabled=False,
        ),
        {"cpu": "cpu_native_helper", "memory": "", "gpu_3d": "python_opencl_compute", "vram": ""},
        "GPU backend usage summary",
    )


def test_stage_gpu_backend_diagnostics_helpers() -> None:
    stage = SimpleNamespace(
        modules=SimpleNamespace(
            cpu=SimpleNamespace(enabled=True),
            memory=SimpleNamespace(enabled=False),
            gpu_3d=SimpleNamespace(enabled=True, backend_preference="auto", gpus="all"),
            vram=SimpleNamespace(enabled=True, backend_preference="vulkan", gpus="discrete"),
        )
    )
    targets_by_mode = {
        "all": [{"target_id": "gpu0"}, {"target_id": "gpu1"}],
        "discrete": [{"target_id": "gpu1"}],
    }

    def resolve_backend(*, candidates: list[str], targets: list[dict], workload: str) -> dict:
        return {
            "backend": candidates[0] if candidates else "none",
            "candidate_reports": [],
            "support": {"supported": True, "supported_targets": targets, "unsupported_targets": []},
            "workload": workload,
        }

    diagnostics = build_stage_gpu_backend_diagnostics(
        stage=stage,
        stage_gpu_target_mode=lambda _stage: "all",
        gpu_targets=lambda mode: list(targets_by_mode.get(mode, [])),
        normalize_gpu_3d_backend_preference=lambda value: str(value),
        normalize_vram_backend_preference=lambda value: str(value),
        gpu_3d_backend_candidates=lambda _gpu, _stage: ["python_vulkan_compute", "python_egl_gles2"],
        vram_backend_candidates=lambda _vram: ["python_vulkan_compute", "python_opencl"],
        resolve_gpu_backend_for_targets=resolve_backend,
        cpu_backend_name=lambda _cpu: "cpu_native_helper",
        memory_backend_name=lambda _memory: "memory_native_helper",
    )
    assert_equal(diagnostics["gpu_target_mode"], "all", "stage GPU diagnostics target mode")
    assert_equal([target["target_id"] for target in diagnostics["gpu_targets"]], ["gpu0", "gpu1"], "stage GPU diagnostics target list")
    assert_equal(diagnostics["gpu_3d_preference"], "auto", "stage GPU diagnostics 3D preference")
    assert_equal(diagnostics["vram_preference"], "vulkan", "stage GPU diagnostics VRAM preference")
    assert_equal(diagnostics["gpu_3d_candidates"], ["python_vulkan_compute", "python_egl_gles2"], "stage GPU diagnostics 3D candidates")
    assert_equal(diagnostics["vram_candidates"], ["python_vulkan_compute", "python_opencl"], "stage GPU diagnostics VRAM candidates")
    assert_equal(diagnostics["gpu_3d_resolution"]["backend"], "python_vulkan_compute", "stage GPU diagnostics 3D resolution")
    assert_equal(diagnostics["vram_resolution"]["backend"], "python_vulkan_compute", "stage GPU diagnostics VRAM resolution")
    assert_equal(
        diagnostics["backend_usage"],
        {
            "cpu": "cpu_native_helper",
            "memory": "",
            "gpu_3d": "python_vulkan_compute",
            "vram": "python_vulkan_compute",
        },
        "stage GPU diagnostics backend usage",
    )
    assert_equal(
        gpu_3d_preference_fallback_warning(
            enabled=True,
            preference="vulkan_compute",
            resolved_backend="python_egl_gles2",
        ),
        "3D backend preference 'vulkan_compute' is unavailable; falling back to python_egl_gles2",
        "stage GPU diagnostics 3D fallback warning",
    )
    assert_equal(
        gpu_3d_preference_fallback_warning(
            enabled=True,
            preference="vulkan_compute",
            resolved_backend="python_vulkan_compute",
        ),
        "",
        "stage GPU diagnostics 3D matched preference warning",
    )
    assert_equal(
        vram_preference_fallback_warning(
            enabled=True,
            preference="opencl",
            resolved_backend="python_vulkan_compute",
        ),
        "VRAM backend preference 'opencl' is unavailable; falling back to python_vulkan_compute",
        "stage GPU diagnostics VRAM fallback warning",
    )
    assert_equal(
        vram_preference_fallback_warning(
            enabled=True,
            preference="vulkan",
            resolved_backend="python_vulkan_compute",
        ),
        "",
        "stage GPU diagnostics VRAM matched preference warning",
    )
    identity_warnings = gpu_3d_backend_identity_warnings(
        enabled=True,
        resolved_backend="vkmark",
        backend_profile={
            "api_family": "Vulkan",
            "suite_scaling_mode": "process_parallel",
            "suite_verification": "telemetry_only",
            "test_purpose": "external_smoke_diagnostic",
            "load_class": "external_smoke",
        },
        gpu_workers=[
            SimpleNamespace(
                workload="gpu_3d",
                backend="vkmark",
                process_count=3,
                resolved_device_name="RTX 5090",
                selection_ambiguous=True,
            ),
            SimpleNamespace(
                workload="gpu_3d",
                backend="vkmark",
                process_count=2,
                resolved_device_name="RTX 5090",
                selection_ambiguous=False,
            ),
        ],
        vulkan_runtime_available=False,
    )
    assert_equal(
        identity_warnings,
        [
            "3D backend 'vkmark' is curated as Vulkan / process_parallel / telemetry_only / purpose=external_smoke_diagnostic",
            "3D backend 'vkmark' is staged with up to 3 supervised process(es) per targeted GPU",
            "Vulkan runtime inventory is unavailable in the current environment; Vulkan target mapping metadata may be limited even though the backend can still launch",
            "Vulkan target mapping resolved to: RTX 5090",
            "Vulkan device selection is ambiguous for at least one target GPU; runtime routing will rely on Mesa target env hints",
            "3D stage is using external smoke backend 'vkmark'; this should not be treated as a suite stress result",
        ],
        "stage GPU diagnostics backend identity warnings",
    )
    assert_equal(
        gpu_3d_backend_identity_warnings(
            enabled=True,
            resolved_backend="glxgears",
            backend_profile={"load_class": "compatibility"},
            gpu_workers=[],
            vulkan_runtime_available=True,
        ),
        [
            "3D backend 'glxgears' is curated as  /  /  / purpose=unknown",
            "3D stage is using 'glxgears', which is a compatibility-oriented backend and may not fully saturate powerful GPUs",
        ],
        "stage GPU diagnostics compatibility warning",
    )
    assert_equal(
        suite_native_gpu_3d_backend_warnings(
            enabled=True,
            resolved_backend="python_opencl_compute",
            compute_variant="integer_mix",
            allocation_percent=0,
            gpu_3d_preference="opencl",
            selected_opencl_context="rusticl_iris",
            opencl_compute_variants={"integer_mix": {"status": "experimental"}},
            vulkan_compute_variants={},
        ),
        [
            "3D stage is using the built-in OpenCL compute backend",
            "3D OpenCL compute variant 'integer_mix' selected",
            "3D OpenCL compute variant 'integer_mix' is experimental; baseline remains the validated production path",
            "3D OpenCL runtime selected compatibility context 'rusticl_iris'",
        ],
        "stage GPU diagnostics OpenCL suite-native warnings",
    )
    assert_equal(
        suite_native_gpu_3d_backend_warnings(
            enabled=True,
            resolved_backend="python_vulkan_transfer",
            compute_variant="hash",
            allocation_percent=0,
            gpu_3d_preference="vulkan",
            selected_opencl_context="",
            opencl_compute_variants={},
            vulkan_compute_variants={},
        ),
        [
            "3D stage is using the suite-native Vulkan transfer/readback backend",
            "Vulkan transfer/readback validates Vulkan routing and memory movement; it is not yet a shader or ray-tracing saturation workload",
        ],
        "stage GPU diagnostics Vulkan transfer warnings",
    )
    assert_equal(
        suite_native_gpu_3d_backend_warnings(
            enabled=True,
            resolved_backend="python_vulkan_compute",
            compute_variant="stateful_memory",
            allocation_percent=125,
            gpu_3d_preference="auto",
            selected_opencl_context="",
            opencl_compute_variants={},
            vulkan_compute_variants={"stateful_memory": {"status": "validated_experimental"}},
        ),
        [
            "3D stage is using the suite-native Vulkan compute/readback backend",
            "3D Vulkan compute variant 'stateful_memory' selected",
            "3D Vulkan compute variant 'stateful_memory' is experimental; hash remains the validated production path",
            "3D Vulkan stateful-memory allocation target is explicitly set to 100% with capacity-based safety reserves",
            "GPU auto selected the suite-native Vulkan compute/readback family as the preferred curated stress backend",
        ],
        "stage GPU diagnostics Vulkan compute warnings",
    )
    assert_equal(
        vram_backend_warnings(
            enabled=True,
            resolved_backend="python_opencl",
            selected_opencl_context="rusticl_radeonsi",
        ),
        [
            "VRAM stage is using the built-in OpenCL verification backend",
            "VRAM OpenCL runtime selected compatibility context 'rusticl_radeonsi'",
        ],
        "stage GPU diagnostics VRAM OpenCL compatibility warning",
    )
    assert_equal(
        vram_backend_warnings(
            enabled=True,
            resolved_backend="python_opencl",
            selected_opencl_context="native",
        ),
        ["VRAM stage is using the built-in OpenCL verification backend"],
        "stage GPU diagnostics VRAM native OpenCL warning",
    )
    assert_equal(
        vram_backend_warnings(
            enabled=True,
            resolved_backend="python_vulkan_compute",
            selected_opencl_context="",
        ),
        ["VRAM stage is using the suite-native Vulkan stateful-memory/readback backend"],
        "stage GPU diagnostics VRAM Vulkan warning",
    )
    assert_equal(
        vram_backend_warnings(
            enabled=True,
            resolved_backend="python_egl_gles2",
            selected_opencl_context="",
        ),
        ["VRAM stage is using the suite-native EGL/GLES render/readback backend"],
        "stage GPU diagnostics VRAM EGL/GLES warning",
    )
    assert_equal(
        vram_backend_warnings(
            enabled=False,
            resolved_backend="python_opencl",
            selected_opencl_context="rusticl_radeonsi",
        ),
        [],
        "stage GPU diagnostics disabled VRAM warning",
    )
    assert_equal(
        opencl_high_headroom_safety_warning(
            enabled=True,
            resolved_backend="python_opencl_compute",
            safe_mode_enabled=True,
            target_labels=["0000:03:00.0", "0000:03:00.0", "0000:02:00.0"],
        ),
        "3D OpenCL compute is using a conservative maintained safety cap on higher-headroom AMD discrete targets "
        + "(0000:02:00.0, 0000:03:00.0) with load=0.9, verify=0.9, "
        + "reduced load-phase buffer fan-out, and slower hot-loop cadence to reduce compute-ring reset risk on current Linux stacks",
        "stage GPU diagnostics high-headroom OpenCL warning",
    )
    assert_equal(
        opencl_high_headroom_safety_warning(
            enabled=True,
            resolved_backend="python_opencl_compute",
            safe_mode_enabled=False,
            target_labels=["0000:03:00.0"],
        ),
        "",
        "stage GPU diagnostics disabled high-headroom OpenCL warning",
    )
    assert_equal(
        per_target_backend_selection_warning(
            enabled=True,
            per_target_backends=["python_vulkan_compute", "python_vulkan_compute", "python_egl_gles2"],
        ),
        "3D auto mode selected per-target backends for broader and stronger coverage: python_egl_gles2, python_vulkan_compute",
        "stage GPU diagnostics per-target backend warning",
    )
    assert_equal(
        mixed_stage_gpu_safety_warnings(
            gpu_3d_enabled=True,
            vram_enabled=True,
            prefer_graphics_backend_for_mixed_stage=True,
            gpu_3d_backend="python_egl_gles2",
            vram_backend="python_opencl",
            amd_vulkan_vram_target_labels=["0000:05:00.0", "0000:04:00.0", "0000:04:00.0"],
            fused_vulkan_vram_target_labels=["0000:06:00.0"],
            skipped_vram_target_labels=["0000:07:00.0"],
        ),
        [
            "Mixed-stage GPU safety is using EGL/GLES for 3D while VRAM uses OpenCL because the preferred Vulkan path was unavailable",
            "Mixed-stage AMD discrete GPU safety routes VRAM pressure through Vulkan stateful-memory workers on "
            + "0000:04:00.0, 0000:05:00.0"
            + " instead of OpenCL because simultaneous Vulkan compute plus OpenCL VRAM triggered amdgpu resets on multi-AMD systems",
            "Mixed-stage Vulkan VRAM workers are fused GPU+VRAM stateful-memory workers on "
            + "0000:06:00.0"
            + "; separate same-target Vulkan 3D workers are not launched to avoid doubling Vulkan worker pressure",
            "Mixed-stage GPU safety suppresses separate concurrent OpenCL VRAM workers on selected targets "
            + "(0000:07:00.0) because standalone VRAM coverage already runs separately and concurrent 3D+VRAM has triggered driver resets on these target classes",
        ],
        "stage GPU diagnostics mixed EGL/OpenCL safety warnings",
    )
    assert_equal(
        mixed_stage_gpu_safety_warnings(
            gpu_3d_enabled=True,
            vram_enabled=True,
            prefer_graphics_backend_for_mixed_stage=False,
            gpu_3d_backend="python_vulkan_compute",
            vram_backend="python_opencl",
            amd_vulkan_vram_target_labels=[],
            fused_vulkan_vram_target_labels=[],
            skipped_vram_target_labels=[],
        ),
        [
            "Mixed-stage GPU safety is using the suite-native Vulkan compute backend for 3D while VRAM uses OpenCL where that combination is considered safe",
        ],
        "stage GPU diagnostics mixed Vulkan/OpenCL safety warning",
    )
    assert_equal(
        mixed_stage_gpu_safety_warnings(
            gpu_3d_enabled=True,
            vram_enabled=True,
            prefer_graphics_backend_for_mixed_stage=False,
            gpu_3d_backend="python_opencl_compute",
            vram_backend="python_opencl",
            amd_vulkan_vram_target_labels=[],
            fused_vulkan_vram_target_labels=[],
            skipped_vram_target_labels=[],
        ),
        [
            "3D and VRAM are both using built-in OpenCL backends in the same stage; this is the highest-risk combination on current Linux driver stacks",
        ],
        "stage GPU diagnostics mixed OpenCL risk warning",
    )
    assert_equal(
        gpu_safe_mode_worker_warnings(
            safe_mode_enabled=True,
            internal_worker_present=True,
            ramp_start_load_fraction=0.35,
            ramp_step_seconds=7.0,
            vram_cap_entries=[
                {
                    "label": "0000:09:00.0",
                    "requested_bytes": 10 * 1024 ** 3,
                    "capped_bytes": 8 * 1024 ** 3,
                }
            ],
        ),
        [
            "Internal GPU workers will ramp from 35% load over approximately 21s",
            "VRAM target for 0000:09:00.0 was capped by safe mode from 10.0GB to 8.0GB",
        ],
        "stage GPU diagnostics safe-mode worker warnings",
    )
    assert_equal(
        gpu_3d_intensity_warning(
            enabled=True,
            resolved_backend="python_vulkan_compute",
            normalized_intensity="high",
        ),
        "3D intensity 'high' is shaping suite-native GPU load scaling for this stage",
        "stage GPU diagnostics intensity warning",
    )


def test_gpu_backend_resolver_helpers() -> None:
    targets = [
        {"target_id": "0000:01:00.0"},
        {"target_id": "0000:02:00.0"},
        {"target_id": "0000:03:00.0"},
    ]

    def target_support(backend: str, target: dict | None, workload: str) -> dict:
        label = str((target or {}).get("target_id") or "default")
        supported = backend == "backend_full" or (
            backend == "backend_partial_two" and label in {"0000:01:00.0", "0000:02:00.0"}
        ) or (
            backend == "backend_partial_one" and label == "0000:01:00.0"
        )
        return {
            "backend": backend,
            "workload": workload,
            "target": dict(target) if target else None,
            "target_label": label,
            "supported": supported,
            "reason": "" if supported else "unsupported",
            "resolved_device_name": label if supported else "",
        }

    summary = gpu_backend_support_summary(
        backend="backend_partial_two",
        targets=targets,
        workload="gpu_3d",
        target_support=target_support,
    )
    assert_true(not summary["supported"], "backend support summary partial")
    assert_equal(len(summary["supported_targets"]), 2, "backend support summary supported count")
    assert_equal(len(summary["unsupported_targets"]), 1, "backend support summary unsupported count")

    availability = {
        "missing": False,
        "backend_partial_one": True,
        "backend_partial_two": True,
        "backend_full": True,
    }

    full = resolve_gpu_backend_for_targets(
        candidates=["missing", "backend_partial_one", "backend_full"],
        targets=targets,
        workload="gpu_3d",
        backend_available=lambda backend, _workload: bool(availability.get(backend)),
        support_summary=lambda backend, selected_targets, workload: gpu_backend_support_summary(
            backend=backend,
            targets=selected_targets,
            workload=workload,
            target_support=target_support,
        ),
    )
    assert_equal(full["backend"], "backend_full", "backend resolver full backend")
    assert_true(not full["partial"], "backend resolver full backend not partial")
    assert_equal([report["backend"] for report in full["candidate_reports"]], ["missing", "backend_partial_one", "backend_full"], "backend resolver preserves reports before full match")

    partial = resolve_gpu_backend_for_targets(
        candidates=["backend_partial_one", "backend_partial_two"],
        targets=targets,
        workload="gpu_3d",
        backend_available=lambda backend, _workload: bool(availability.get(backend)),
        support_summary=lambda backend, selected_targets, workload: gpu_backend_support_summary(
            backend=backend,
            targets=selected_targets,
            workload=workload,
            target_support=target_support,
        ),
    )
    assert_equal(partial["backend"], "backend_partial_two", "backend resolver best partial backend")
    assert_true(partial["partial"], "backend resolver partial flag")
    assert_equal(len(partial["candidate_reports"]), 2, "backend resolver partial report count")

    none = resolve_gpu_backend_for_targets(
        candidates=["missing"],
        targets=targets,
        workload="vram",
        backend_available=lambda backend, _workload: bool(availability.get(backend)),
        support_summary=lambda backend, selected_targets, workload: gpu_backend_support_summary(
            backend=backend,
            targets=selected_targets,
            workload=workload,
            target_support=target_support,
        ),
    )
    assert_equal(none["backend"], "none", "backend resolver no backend")
    assert_equal(none["support"], None, "backend resolver no support")
    assert_true(not none["partial"], "backend resolver no partial")


def test_gpu_backend_support_helpers() -> None:
    target = {"target_id": "0000:01:00.0", "vendor": "amd", "vendor_id": "1002"}
    base = base_gpu_backend_target_support(
        backend="python_opencl",
        target=target,
        workload="vram",
    )
    assert_equal(base["target_label"], "0000:01:00.0", "backend support base target label")
    assert_true(not base["supported"], "backend support base unsupported")

    matched = opencl_backend_target_support(
        backend="python_opencl",
        target=target,
        workload="vram",
        matched_device={"name": "AMD Radeon RX 7900 XTX"},
        all_devices=[],
    )
    assert_true(matched["supported"], "OpenCL support matched device")
    assert_equal(matched["resolved_device_name"], "AMD Radeon RX 7900 XTX", "OpenCL support matched name")

    no_devices = opencl_backend_target_support(
        backend="python_opencl",
        target=target,
        workload="vram",
        matched_device=None,
        all_devices=[],
    )
    assert_equal(
        no_devices["reason"],
        "no OpenCL GPU devices found at all; check that an OpenCL runtime is installed",
        "OpenCL support no devices reason",
    )

    wrong_vendor = opencl_backend_target_support(
        backend="python_opencl_compute",
        target={"target_id": "0000:02:00.0", "vendor": "intel", "vendor_id": "8086"},
        workload="gpu_3d",
        matched_device=None,
        all_devices=[
            {"vendor": "NVIDIA Corporation", "platform_vendor": "NVIDIA", "name": "RTX 5090", "vendor_id": "10de"},
            {"vendor": "Advanced Micro Devices, Inc.", "platform_vendor": "AMD", "name": "Radeon", "vendor_id": "1002"},
        ],
    )
    assert_equal(
        wrong_vendor["reason"],
        "no intel OpenCL device found after native, Intel ICD, and Rusticl iris probes; found 2 OpenCL GPU(s) from: NVIDIA Corporation, Advanced Micro Devices, Inc.",
        "OpenCL support wrong vendor reason",
    )

    same_vendor = opencl_backend_target_support(
        backend="python_opencl_compute",
        target=target,
        workload="gpu_3d",
        matched_device=None,
        all_devices=[
            {"vendor": "Advanced Micro Devices, Inc.", "platform_vendor": "AMD", "name": "Radeon RX 6600 XT", "vendor_id": "1002"},
        ],
    )
    assert_equal(
        same_vendor["reason"],
        "OpenCL devices exist for this vendor, but no device matched the target GPU",
        "OpenCL support same vendor mismatch reason",
    )

    dropout_reason = vulkan_nvidia_dropout_reason(
        target={"target_id": "0000:65:00.0", "vendor": "nvidia", "driver": "nvidia"},
        nvidia_smi_available=True,
        nvidia_slots={"0000:17:00.0"},
    )
    assert_equal(
        dropout_reason,
        "NVIDIA target 0000:65:00.0 is not visible to nvidia-smi; the card may be dropped/offline, so Vulkan stress is skipped for this target",
        "Vulkan support NVIDIA dropout reason",
    )

    vulkan_drop = vulkan_backend_target_support(
        backend="python_vulkan_compute",
        target={"target_id": "0000:65:00.0", "vendor": "nvidia", "driver": "nvidia"},
        workload="gpu_3d",
        vulkan_match={"available": True, "device": {"deviceName": "RTX 5090"}},
        nvidia_dropout_reason=dropout_reason,
    )
    assert_true(not vulkan_drop["supported"], "Vulkan support dropout unsupported")
    assert_equal(vulkan_drop["reason"], dropout_reason, "Vulkan support dropout reason")

    vulkan_match = vulkan_backend_target_support(
        backend="python_vulkan_compute",
        target={"target_id": "0000:17:00.0", "vendor": "nvidia", "driver": "nvidia"},
        workload="gpu_3d",
        vulkan_match={"available": True, "device": {"deviceName": "RTX 5090"}},
    )
    assert_true(vulkan_match["supported"], "Vulkan support matched target")
    assert_equal(vulkan_match["resolved_device_name"], "RTX 5090", "Vulkan support matched name")

    vulkan_missing = vulkan_backend_target_support(
        backend="python_vulkan_transfer",
        target={"target_id": "0000:02:00.0", "vendor": "amd", "driver": "amdgpu"},
        workload="vram",
        vulkan_match={"available": False},
    )
    assert_equal(
        vulkan_missing["reason"],
        "no matching Vulkan GPU device found for this target",
        "Vulkan support no match reason",
    )

    egl_match = egl_backend_target_support(
        backend="python_egl_gles2",
        target={"target_id": "0000:17:00.0", "vendor": "nvidia"},
        workload="gpu_3d",
        egl_probe={
            "available": True,
            "renderer": "NVIDIA RTX 5090",
            "egl_device_exact_match": True,
            "egl_selected_device": {"slot": "0000:17:00.0"},
            "selected_env": {
                "LVS_EGL_TARGET_PCI_SLOT": "0000:17:00.0",
                "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/10_nvidia.json",
                "PATH": "/tmp/not-exported",
            },
        },
    )
    assert_true(egl_match["supported"], "EGL support matched target")
    assert_equal(egl_match["resolved_device_name"], "NVIDIA RTX 5090", "EGL support matched renderer")
    assert_equal(egl_match["egl_device_exact_match"], True, "EGL support exact match")
    assert_equal(
        egl_match["selected_env"],
        {
            "LVS_EGL_TARGET_PCI_SLOT": "0000:17:00.0",
            "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/10_nvidia.json",
        },
        "EGL support selected env filtering",
    )

    egl_missing = egl_backend_target_support(
        backend="python_egl_gles2",
        target={"target_id": "0000:02:00.0", "vendor": "amd"},
        workload="gpu_3d",
        egl_probe={"available": False},
    )
    assert_equal(
        egl_missing["reason"],
        "targeted EGL renderer unavailable",
        "EGL support default unavailable reason",
    )

    glmark_missing = egl_backend_target_support(
        backend="glmark2",
        target={"target_id": "0000:02:00.0", "vendor": "amd"},
        workload="gpu_3d",
        egl_probe={"available": False, "reason": "renderer mismatch"},
    )
    assert_equal(glmark_missing["reason"], "renderer mismatch", "EGL smoke backend explicit reason")
    assert_true("selected_env" not in glmark_missing, "EGL smoke backend omits selected env")

    calls: List[str] = []

    def opencl_provider() -> Dict[str, Any]:
        calls.append("opencl")
        return matched

    def vulkan_provider() -> Dict[str, Any]:
        calls.append("vulkan")
        return vulkan_match

    def egl_provider() -> Dict[str, Any]:
        calls.append("egl")
        return egl_match

    facade_opencl = gpu_backend_target_support(
        backend="python_opencl_compute",
        target=target,
        workload="gpu_3d",
        opencl_support=opencl_provider,
        vulkan_support=vulkan_provider,
        egl_support=egl_provider,
    )
    assert_equal(facade_opencl["resolved_device_name"], "AMD Radeon RX 7900 XTX", "support facade OpenCL dispatch")
    assert_equal(calls, ["opencl"], "support facade OpenCL lazy providers")

    calls.clear()
    facade_vulkan = gpu_backend_target_support(
        backend="python_vulkan_compute",
        target=target,
        workload="gpu_3d",
        opencl_support=opencl_provider,
        vulkan_support=vulkan_provider,
        egl_support=egl_provider,
    )
    assert_equal(facade_vulkan["resolved_device_name"], "RTX 5090", "support facade Vulkan dispatch")
    assert_equal(calls, ["vulkan"], "support facade Vulkan lazy providers")

    calls.clear()
    facade_egl = gpu_backend_target_support(
        backend="python_egl_gles2",
        target=target,
        workload="gpu_3d",
        opencl_support=opencl_provider,
        vulkan_support=vulkan_provider,
        egl_support=egl_provider,
    )
    assert_equal(facade_egl["resolved_device_name"], "NVIDIA RTX 5090", "support facade EGL dispatch")
    assert_equal(calls, ["egl"], "support facade EGL lazy providers")

    calls.clear()
    facade_default = gpu_backend_target_support(
        backend="unknown_backend",
        target=target,
        workload="gpu_3d",
        opencl_support=opencl_provider,
        vulkan_support=vulkan_provider,
        egl_support=egl_provider,
    )
    assert_true(facade_default["supported"], "support facade unknown backend default supported")
    assert_equal(calls, [], "support facade unknown backend skips providers")

    calls.clear()
    facade_no_target = gpu_backend_target_support(
        backend="python_opencl_compute",
        target=None,
        workload="gpu_3d",
        opencl_support=opencl_provider,
    )
    assert_true(facade_no_target["supported"], "support facade no target supported")
    assert_equal(calls, [], "support facade no target skips providers")


def test_gpu_backend_catalog_helpers() -> None:
    assert_equal(normalize_gpu_3d_backend_preference("python_egl_gles2"), "egl", "GPU 3D EGL alias")
    assert_equal(normalize_gpu_3d_backend_preference("vulkan compute"), "vulkan_compute", "GPU 3D Vulkan compute alias")
    assert_equal(normalize_gpu_3d_backend_preference("unknown"), "auto", "GPU 3D invalid preference fallback")
    assert_equal(normalize_vram_backend_preference("python_vulkan_compute"), "vulkan", "VRAM Vulkan alias")
    assert_equal(normalize_vram_backend_preference("bad"), "auto", "VRAM invalid preference fallback")
    assert_equal(
        gpu_3d_backend_candidates_by_preference("auto"),
        ["python_vulkan_compute", "python_egl_gles2", "python_opencl_compute"],
        "GPU 3D auto candidate order",
    )
    assert_equal(
        gpu_3d_backend_candidates("auto", prefer_graphics_mixed_stage=True),
        ["python_vulkan_compute", "python_egl_gles2", "python_opencl_compute"],
        "GPU 3D mixed-stage preferred candidate order",
    )
    assert_equal(
        gpu_3d_backend_preference_catalog("egl")[0]["backend"],
        "python_egl_gles2",
        "GPU 3D preference catalog entry",
    )
    assert_equal(
        gpu_3d_backend_catalog_entry("python_vulkan_compute")["api_family"],
        "Vulkan",
        "GPU 3D catalog API family",
    )
    assert_true(
        prefer_graphics_backend_for_mixed_stage(
            gpu_backend_preference="auto",
            safe_mode_enabled=True,
            vram_enabled=True,
            vram_backend_name="python_opencl",
        ),
        "mixed-stage graphics preference enabled for safe OpenCL VRAM",
    )
    assert_true(
        not prefer_graphics_backend_for_mixed_stage(
            gpu_backend_preference="opencl",
            safe_mode_enabled=True,
            vram_enabled=True,
            vram_backend_name="python_opencl",
        ),
        "mixed-stage graphics preference respects explicit GPU backend",
    )
    assert_true(
        not allow_per_target_auto_gpu_3d_backends(
            gpu_backend_preference="auto",
            stage_present=True,
            stage_vram_enabled=True,
            stage_vram_backend_name="python_opencl",
        ),
        "per-target auto GPU backend disabled for OpenCL VRAM mixed stage",
    )
    assert_true(
        allow_per_target_auto_gpu_3d_backends(
            gpu_backend_preference="auto",
            stage_present=False,
            stage_vram_enabled=False,
            stage_vram_backend_name="",
        ),
        "per-target auto GPU backend allowed without stage context",
    )
    assert_equal(
        vram_backend_candidates("vulkan"),
        ["python_vulkan_compute", "python_opencl", "python_egl_gles2"],
        "VRAM Vulkan preference candidate order",
    )

    calls: list[str] = []

    def callback(name: str, value: bool):
        def inner() -> bool:
            calls.append(name)
            return value

        return inner

    assert_true(
        gpu_3d_backend_available(
            "python_opencl_compute",
            command_exists=lambda _name: False,
            python_runtime_available=callback("python", True),
            egl_available=callback("egl", False),
            opencl_available=callback("opencl", True),
            vulkan_compute_available=callback("vulkan_compute", False),
            vulkan_transfer_available=callback("vulkan_transfer", False),
        ),
        "GPU 3D OpenCL backend availability",
    )
    assert_equal(calls, ["python", "opencl"], "GPU 3D availability probes only selected backend")

    calls.clear()
    assert_true(
        vram_backend_available(
            "python_vulkan_compute",
            python_runtime_available=callback("python", True),
            vulkan_compute_available=callback("vulkan_compute", True),
            opencl_available=callback("opencl", False),
            egl_available=callback("egl", False),
        ),
        "VRAM Vulkan backend availability",
    )
    assert_equal(calls, ["python", "vulkan_compute"], "VRAM availability probes only selected backend")

    calls.clear()
    context = GpuBackendAvailabilityContext(
        command_exists=lambda _name: False,
        python_runtime_available=callback("python", True),
        egl_available=callback("egl", True),
        opencl_available=callback("opencl", True),
        vulkan_compute_available=callback("vulkan_compute", True),
        vulkan_transfer_available=callback("vulkan_transfer", True),
    )
    assert_true(
        gpu_3d_backend_available_from_context("python_egl_gles2", context),
        "GPU 3D availability context EGL backend",
    )
    assert_equal(calls, ["python", "egl"], "GPU 3D availability context selected callbacks")

    calls.clear()
    assert_true(
        vram_backend_available_from_context("python_opencl", context),
        "VRAM availability context OpenCL backend",
    )
    assert_equal(calls, ["python", "opencl"], "VRAM availability context selected callbacks")


def test_vulkan_targeting_helpers() -> None:
    gpu_cards = [
        {"slot": "0000:01:00.0", "target_id": "0000:01:00.0", "vendor_id": "10de", "device": "2b85"},
        {"slot": "0000:02:00.0", "target_id": "0000:02:00.0", "vendor_id": "10de", "device": "2b85"},
    ]
    target = {
        "slot": "0000:02:00.0",
        "target_id": "0000:02:00.0",
        "vendor_id": "10de",
        "device": "2b85",
        "vendor": "nvidia",
        "gpu_index": 1,
    }
    selected_device = {
        "index": 1,
        "vendorID": "0x10de",
        "deviceID": "0x2b85",
        "deviceName": "NVIDIA RTX 5090",
        "deviceType": "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
        "pci_slot": "0000:02:00.0",
    }
    wrong_slot_device = dict(selected_device, index=0, pci_slot="0000:01:00.0")

    assert_equal(
        slot_from_mesa_style_vulkan_uuid("00000000-0200-0000-0000-000000000000", gpu_cards),
        "0000:02:00.0",
        "Vulkan Mesa UUID slot decode",
    )
    assert_equal(
        vulkan_device_pci_slot({"vendorID": "10de", "deviceID": "2b85", "deviceUUID": "00000000-0200-0000-0000-000000000000"}, gpu_cards),
        "0000:02:00.0",
        "Vulkan device PCI slot fallback",
    )
    assert_true(
        vulkan_device_score_for_target(
            selected_device,
            target,
            gpu_cards=gpu_cards,
            likely_discrete_ids={"0000:01:00.0", "0000:02:00.0"},
        ) > 3000.0,
        "Vulkan target score prefers exact slot",
    )
    assert_equal(
        vulkan_device_score_for_target(
            wrong_slot_device,
            target,
            gpu_cards=gpu_cards,
            likely_discrete_ids={"0000:01:00.0", "0000:02:00.0"},
        ),
        -1000000.0,
        "Vulkan target score rejects wrong explicit slot",
    )
    matched = vulkan_device_for_target(
        [wrong_slot_device, selected_device],
        target,
        gpu_cards=gpu_cards,
        likely_discrete_ids={"0000:01:00.0", "0000:02:00.0"},
    )
    assert_true(matched["available"], "Vulkan target match available")
    assert_equal(matched["device"]["pci_slot"], "0000:02:00.0", "Vulkan target match selected slot")
    assert_equal(vulkan_device_class_from_match(matched), "discrete", "Vulkan target class")

    ambiguous = vulkan_device_for_target(
        [
            {"index": 0, "vendorID": "10de", "deviceID": "2b85", "deviceName": "NVIDIA RTX 5090", "deviceType": "discrete"},
            {"index": 1, "vendorID": "10de", "deviceID": "2b85", "deviceName": "NVIDIA RTX 5090", "deviceType": "discrete"},
        ],
        {"vendor_id": "10de", "device": "2b85", "vendor": "nvidia"},
        gpu_cards=[],
        likely_discrete_ids=set(),
    )
    assert_true(ambiguous["available"], "Vulkan ambiguous same-model match available")
    assert_true(ambiguous["ambiguous"], "Vulkan ambiguous same-model match flagged")


def test_gpu_worker_planner_helpers() -> None:
    targets = [
        {"target_id": "0000:01:00.0", "card": "card1", "gpu_index": 0},
        {"target_id": "0000:02:00.0", "card": "card2", "gpu_index": 1},
    ]

    def worker(workload: str, backend: str, target: dict, compute_variant: str = "") -> GpuWorkerSpec:
        return GpuWorkerSpec(
            workload=workload,
            backend=backend,
            gpu_index=int(target.get("gpu_index", 0)),
            card=str(target.get("card", "")),
            slot=str(target.get("target_id", "")),
            target_id=str(target.get("target_id", "")),
            command=[backend],
            compute_variant=compute_variant,
        )

    class FakeRunner:
        def _gpu_targets(self, selection: str) -> list[dict]:
            return list(targets)

        def _resolve_gpu_backend_for_targets(self, *, candidates: list[str], targets: list[dict], workload: str) -> dict:
            return {
                "backend": "python_egl_gles2" if workload == "gpu_3d" else "python_vulkan_compute",
                "support": {
                    "unsupported_targets": [{"target_label": "0000:02:00.0"}] if workload == "gpu_3d" else [],
                    "supported_targets": [{"target": target} for target in targets],
                },
            }

        def _effective_gpu_targets(self, target_list: list[dict], resolution: dict) -> list[dict]:
            return list(target_list)

        def _normalize_gpu_3d_backend_preference(self, preference: str) -> str:
            return "auto"

        def _allow_per_target_auto_gpu_3d_backends(self, gpu: object, stage: object) -> bool:
            return True

        def _gpu_3d_backend_candidates(self, gpu: object, stage: object) -> list[str]:
            return ["python_egl_gles2", "python_opencl_compute"]

        def _gpu_3d_backend_available(self, backend: str) -> bool:
            return True

        def _gpu_backend_target_support(self, backend: str, target: dict, workload: str) -> dict:
            target_id = str(target.get("target_id", ""))
            return {"supported": (backend == "python_egl_gles2" and target_id.endswith("01:00.0")) or (backend == "python_opencl_compute" and target_id.endswith("02:00.0"))}

        def _build_python_gpu_3d_worker(self, target: dict, profile_mode: str = "", profile_intensity: str = "") -> GpuWorkerSpec:
            return worker("gpu_3d", "python_egl_gles2", target)

        def _build_python_opencl_compute_worker(self, target: dict, profile_mode: str = "", profile_intensity: str = "", compute_variant: str = "") -> GpuWorkerSpec:
            return worker("gpu_3d", "python_opencl_compute", target, compute_variant)

        def _vram_backend_candidates(self, vram: object) -> list[str]:
            return ["python_vulkan_compute"]

        def _amd_discrete_target_count(self, target_list: list[dict]) -> int:
            return 0

        def _use_vulkan_vram_worker_for_target(self, target: dict, **kwargs: object) -> bool:
            return False

        def _skip_concurrent_vram_worker_for_target(self, target: dict, concurrent_gpu_3d: bool, **kwargs: object) -> bool:
            return False

        def _target_vram_allocation_bytes(self, allocation_percent: int, target: dict, **kwargs: object) -> int:
            return 1024

        def _build_python_vulkan_vram_worker(self, target: dict, target_bytes: int) -> GpuWorkerSpec:
            spec = worker("vram", "python_vulkan_compute", target, "stateful_memory")
            spec.target_vram_bytes = target_bytes
            return spec

    gpu = SimpleNamespace(
        gpus="all",
        backend_preference="auto",
        mode="steady",
        intensity="extreme",
        compute_variant="baseline",
        allocation_percent=0,
        enabled=True,
    )
    vram = SimpleNamespace(gpus="all", allocation_percent=80, enabled=True)
    memory = SimpleNamespace(enabled=False, allocation_percent=0)
    stage = SimpleNamespace(
        duration_seconds=90,
        modules=SimpleNamespace(gpu_3d=gpu, vram=vram, memory=memory),
    )
    planned_gpu_workers = build_gpu_3d_worker_specs(FakeRunner(), gpu, stage)
    assert_equal(
        [spec.backend for spec in planned_gpu_workers],
        ["python_egl_gles2", "python_opencl_compute"],
        "per-target GPU 3D backend planning",
    )
    stage_workers = build_stage_gpu_worker_specs(FakeRunner(), stage)
    assert_equal(
        [spec.workload for spec in stage_workers],
        ["vram", "vram"],
        "fused Vulkan VRAM worker suppresses duplicate 3D workers for same targets",
    )


def test_gpu_worker_materializer_helpers() -> None:
    target = {"target_id": "0000:01:00.0", "card": "card1", "gpu_index": 0}

    class FakeRunner:
        def _gpu_target_by_id(self, target_id: str) -> dict:
            assert_equal(target_id, "0000:01:00.0", "materializer target lookup")
            return dict(target)

        def _build_supervised_external_gpu_command(self, *, backend: str, target: dict, process_count: int, result_file: str) -> list[str]:
            return [backend, str(process_count), result_file]

        def _build_python_opencl_compute_worker(self, target: dict, tuning_step: int = 0, result_file: str = "", profile_mode: str = "", profile_intensity: str = "", compute_variant: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec(
                workload="gpu_3d",
                backend="python_opencl_compute",
                gpu_index=int(target.get("gpu_index", 0)),
                card=str(target.get("card", "")),
                slot=str(target.get("target_id", "")),
                target_id=str(target.get("target_id", "")),
                command=["opencl", str(tuning_step), result_file, profile_mode, profile_intensity, compute_variant],
                tuning_step=tuning_step,
                profile_mode=profile_mode,
                profile_intensity=profile_intensity,
                compute_variant=compute_variant,
            )

        def _build_python_vulkan_transfer_worker(self, target: dict, tuning_step: int = 0, result_file: str = "", profile_mode: str = "", profile_intensity: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec("gpu_3d", "python_vulkan_transfer", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["vulkan-transfer", result_file])

        def _build_python_vulkan_compute_worker(self, target: dict, tuning_step: int = 0, result_file: str = "", profile_mode: str = "", profile_intensity: str = "", compute_variant: str = "", buffer_bytes_override: int = 0) -> GpuWorkerSpec:
            return GpuWorkerSpec("gpu_3d", "python_vulkan_compute", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["vulkan-compute", result_file, str(buffer_bytes_override)], target_vram_bytes=buffer_bytes_override)

        def _build_python_vulkan_vram_worker(self, target: dict, target_vram_bytes: int, tuning_step: int = 0, result_file: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec("vram", "python_vulkan_compute", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["vulkan-vram", result_file, str(target_vram_bytes)], target_vram_bytes=target_vram_bytes, compute_variant="stateful_memory")

        def _build_python_opencl_vram_worker(self, target: dict, target_vram_bytes: int, tuning_step: int = 0, result_file: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec("vram", "python_opencl", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["opencl-vram", result_file, str(target_vram_bytes)], target_vram_bytes=target_vram_bytes)

        def _build_python_gpu_3d_worker(self, target: dict, tuning_step: int = 0, result_file: str = "", profile_mode: str = "", profile_intensity: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec("gpu_3d", "python_egl_gles2", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["egl", result_file])

        def _build_python_vram_worker(self, target: dict, target_vram_bytes: int, tuning_step: int = 0, result_file: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec("vram", "python_egl_gles2", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["egl-vram", result_file, str(target_vram_bytes)], target_vram_bytes=target_vram_bytes)

    planned = GpuWorkerSpec(
        workload="gpu_3d",
        backend="python_opencl_compute",
        gpu_index=0,
        card="card1",
        slot="0000:01:00.0",
        target_id="0000:01:00.0",
        command=["planned"],
        tuning_step=2,
        profile_mode="steady",
        profile_intensity="extreme",
        compute_variant="baseline",
    )
    materialized = materialize_gpu_worker(FakeRunner(), planned, "/tmp/result.json")
    assert_equal(
        materialized.command,
        ["opencl", "2", "/tmp/result.json", "steady", "extreme", "baseline"],
        "OpenCL compute materialization",
    )
    external = materialize_gpu_worker(
        FakeRunner(),
        GpuWorkerSpec("gpu_3d", "vkmark", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["vkmark"], process_count=3),
        "/tmp/external.json",
    )
    assert_equal(external.command, ["vkmark", "3", "/tmp/external.json"], "external worker materialization")
    passthrough = GpuWorkerSpec("gpu_3d", "unknown", 0, "", "", "", ["unchanged"])
    assert_true(materialize_gpu_worker(FakeRunner(), passthrough, "/tmp/ignored.json") is passthrough, "unknown backend passthrough")


def test_gpu_worker_retune_helpers() -> None:
    target = {"target_id": "0000:01:00.0", "card": "card1", "gpu_index": 0, "vram_total": 4096}

    class FakeRunner:
        def _gpu_target_by_id(self, target_id: str) -> dict:
            assert_equal(target_id, "0000:01:00.0", "retune target lookup")
            return dict(target)

        def _gpu_safe_max_tuning_step(self) -> int:
            return 2

        def _build_python_opencl_compute_worker(self, target: dict, tuning_step: int = 0, profile_mode: str = "", profile_intensity: str = "", compute_variant: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec(
                "gpu_3d",
                "python_opencl_compute",
                int(target.get("gpu_index", 0)),
                str(target.get("card", "")),
                str(target.get("target_id", "")),
                str(target.get("target_id", "")),
                ["opencl-compute", str(tuning_step), profile_mode, profile_intensity, compute_variant],
                tuning_step=tuning_step,
                profile_mode=profile_mode,
                profile_intensity=profile_intensity,
                compute_variant=compute_variant,
            )

        def _build_python_gpu_3d_worker(self, target: dict, tuning_step: int = 0, profile_mode: str = "", profile_intensity: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec("gpu_3d", "python_egl_gles2", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["egl", str(tuning_step)], tuning_step=tuning_step)

        def _cap_gpu_vram_target_bytes(self, target: dict, requested_bytes: int) -> int:
            return min(requested_bytes, 2048)

        def _build_python_opencl_vram_worker(self, target: dict, target_vram_bytes: int, tuning_step: int = 0) -> GpuWorkerSpec:
            return GpuWorkerSpec("vram", "python_opencl", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["opencl-vram", str(target_vram_bytes), str(tuning_step)], target_vram_bytes=target_vram_bytes, tuning_step=tuning_step)

        def _build_python_vram_worker(self, target: dict, target_vram_bytes: int, tuning_step: int = 0) -> GpuWorkerSpec:
            return GpuWorkerSpec("vram", "python_egl_gles2", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["egl-vram", str(target_vram_bytes), str(tuning_step)], target_vram_bytes=target_vram_bytes, tuning_step=tuning_step)

    compute_spec = GpuWorkerSpec(
        "gpu_3d",
        "python_opencl_compute",
        0,
        "card1",
        "0000:01:00.0",
        "0000:01:00.0",
        ["planned"],
        tuning_step=1,
        profile_mode="steady",
        profile_intensity="extreme",
        compute_variant="baseline",
    )
    tuned_compute = retune_gpu_worker(FakeRunner(), compute_spec)
    assert_equal(tuned_compute.command, ["opencl-compute", "2", "steady", "extreme", "baseline"], "OpenCL compute retune")
    vram_spec = GpuWorkerSpec(
        "vram",
        "python_opencl",
        0,
        "card1",
        "0000:01:00.0",
        "0000:01:00.0",
        ["planned"],
        target_vram_bytes=2000,
        tuning_step=0,
    )
    tuned_vram = retune_gpu_worker(FakeRunner(), vram_spec)
    assert_equal(tuned_vram.target_vram_bytes, 2048, "VRAM retune target cap")
    maxed_spec = GpuWorkerSpec("gpu_3d", "python_egl_gles2", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["planned"], tuning_step=2)
    assert_equal(retune_gpu_worker(FakeRunner(), maxed_spec), None, "retune max step blocks")
    unsupported_spec = GpuWorkerSpec("gpu_3d", "python_vulkan_compute", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["planned"])
    assert_equal(retune_gpu_worker(FakeRunner(), unsupported_spec), None, "unsupported retune backend")


def test_gpu_retune_process_helpers() -> None:
    class FakeProcess:
        def __init__(self, fail_wait: bool = False) -> None:
            self.terminated = False
            self.killed = False
            self.fail_wait = fail_wait

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float = 0) -> None:
            if self.fail_wait:
                raise TimeoutError("timeout")

        def kill(self) -> None:
            self.killed = True

    previous_spec = GpuWorkerSpec(
        "gpu_3d",
        "python_egl_gles2",
        0,
        "card1",
        "0000:01:00.0",
        "0000:01:00.0",
        ["old"],
        tuning_step=0,
    )
    new_spec = GpuWorkerSpec(
        "gpu_3d",
        "python_egl_gles2",
        0,
        "card1",
        "0000:01:00.0",
        "0000:01:00.0",
        ["new"],
        tuning_step=1,
    )
    old_process = FakeProcess(fail_wait=True)
    entry = StageProcess(
        kind="gpu_3d",
        command=["old"],
        process=old_process,
        gpu_spec=previous_spec,
        result_path="/tmp/worker.json",
    )
    created: list[dict] = []
    output: list[str] = []

    def fake_popen(cmd: list[str], stdout: object = None, stderr: object = None, env: object = None) -> FakeProcess:
        created.append({"cmd": cmd, "stdout": stdout, "stderr": stderr, "env": env})
        return FakeProcess()

    replacement, event = replace_gpu_process_for_retune(
        entry=entry,
        new_spec=new_spec,
        display_name="GPU Stage",
        metric_summary="busy=55%",
        command_env={"LVS": "1"},
        serialize_worker=serialize_gpu_worker_spec,
        popen_factory=fake_popen,
        print_func=output.append,
    )
    assert_true(old_process.terminated and old_process.killed, "retune stops old process")
    assert_equal(created[0]["cmd"], ["new"], "retune launches new command")
    assert_equal(created[0]["env"], {"LVS": "1"}, "retune command env")
    assert_equal(replacement.gpu_spec.tuning_step, 1, "retune replacement stage process")
    assert_equal(event["previous_tuning_step"], 0, "retune previous step event")
    assert_true("gpu-retune" in output[0], "retune phase line emitted")

    failed_output: list[str] = []

    def failing_popen(*args: object, **kwargs: object) -> FakeProcess:
        raise RuntimeError("boom")

    failed_replacement, failed_event = replace_gpu_process_for_retune(
        entry=entry,
        new_spec=new_spec,
        display_name="GPU Stage",
        metric_summary="busy=55%",
        command_env={},
        serialize_worker=serialize_gpu_worker_spec,
        popen_factory=failing_popen,
        print_func=failed_output.append,
    )
    assert_equal(failed_replacement, None, "failed retune replacement")
    assert_equal(failed_event, None, "failed retune event")
    assert_true("Failed to retune GPU worker" in failed_output[0], "failed retune warning")


def test_cpu_execution_helpers_select_policy_candidates_and_best_result() -> None:
    assert_equal(cpu_tuning_policy("auto", True), "max_power", "CPU auto power tuning policy")
    assert_equal(cpu_tuning_policy("avx2", True), "family_locked", "CPU explicit mode locks tuning family")
    assert_equal(cpu_tuning_policy("auto", False), "highest_supported", "CPU no-power fallback policy")
    assert_equal(cpu_mode_for_kernel_flavor("avx2_fma"), "avx2", "CPU kernel flavor mode map")

    collector_calls: list[dict] = []

    class FakeTelemetryCollector:
        def __init__(self, **kwargs: object) -> None:
            collector_calls.append(dict(kwargs))

        def detect_capabilities(self) -> dict:
            return {"cpu_power_w": {"available": True}}

    assert_equal(
        cpu_power_tuning_available(
            telemetry_collector_factory=FakeTelemetryCollector,
            interval_seconds=0.25,
            runtime_environment={"LVS": "1"},
            privileged_helper_enabled=True,
        ),
        True,
        "CPU power tuning availability reads telemetry capability",
    )
    assert_equal(collector_calls[0]["interval_seconds"], 0.25, "CPU power tuning helper interval")
    assert_equal(collector_calls[0]["runtime_environment"], {"LVS": "1"}, "CPU power tuning helper env")
    assert_equal(collector_calls[0]["privileged_helper_enabled"], True, "CPU power tuning helper privileged flag")

    supported = {"avx512_fma", "avx2_fma", "scalar"}
    max_power_candidates = cpu_candidate_kernel_flavors(
        helper_available=True,
        policy="max_power",
        resolved_mode="avx2",
        supports_kernel_flavor=lambda flavor: flavor in supported,
    )
    assert_equal(max_power_candidates, ["avx512_fma", "avx2_fma", "scalar"], "CPU max-power candidate order")

    family_candidates = cpu_candidate_kernel_flavors(
        helper_available=True,
        policy="family_locked",
        resolved_mode="avx2",
        supports_kernel_flavor=lambda flavor: flavor in supported,
    )
    assert_equal(family_candidates, ["avx2_fma"], "CPU family-locked candidate order")

    base = build_cpu_execution_base(
        backend="cpu_native_helper",
        requested_mode="auto",
        resolved_mode="avx2",
        kernel_flavor="avx2_fma",
        tuning_policy="max_power",
        candidate_kernel_flavors=max_power_candidates,
    )
    assert_equal(base["tuned"], False, "CPU execution base starts untuned")
    assert_equal(base["candidate_kernel_flavors"], max_power_candidates, "CPU execution base preserves candidates")

    best = best_valid_cpu_tuning_candidate(
        [
            {"kernel_flavor": "scalar", "avg_cpu_power_w": 500.0, "valid": False},
            {"kernel_flavor": "avx2_fma", "avg_cpu_power_w": 125.0, "valid": True},
            {"kernel_flavor": "avx512_fma", "avg_cpu_power_w": None, "valid": True},
        ]
    )
    assert_equal(best["kernel_flavor"] if best else "", "avx2_fma", "CPU tuning ignores invalid high-power result")


def test_cpu_execution_resolution_policy() -> None:
    def unexpected_power_probe() -> bool:
        raise AssertionError("power probe should not run")

    def unexpected_benchmark(_flavor: str) -> dict:
        raise AssertionError("benchmark should not run")

    def unexpected_worker_count() -> int:
        raise AssertionError("worker count should not run")

    untuned = resolve_cpu_execution_policy(
        backend="stress_ng",
        requested_mode="auto",
        resolved_mode="approximate",
        kernel_flavor="",
        tuning_policy="highest_supported",
        candidate_kernel_flavors=[],
        tune_max_power=True,
        worker_count=unexpected_worker_count,
        power_tuning_available=unexpected_power_probe,
        benchmark_candidate=unexpected_benchmark,
        tuning_cache={},
    )
    assert_equal(untuned["backend"], "stress_ng", "CPU resolver non-native backend")
    assert_equal(untuned["tuned"], False, "CPU resolver non-native remains untuned")

    unavailable_calls = []
    unavailable = resolve_cpu_execution_policy(
        backend="cpu_native_helper",
        requested_mode="auto",
        resolved_mode="avx2",
        kernel_flavor="avx2_fma",
        tuning_policy="max_power",
        candidate_kernel_flavors=["avx2_fma", "scalar"],
        tune_max_power=True,
        worker_count=unexpected_worker_count,
        power_tuning_available=lambda: unavailable_calls.append(True) or False,
        benchmark_candidate=unexpected_benchmark,
        tuning_cache={},
    )
    assert_equal(len(unavailable_calls), 1, "CPU resolver checks tuning telemetry")
    assert_equal(unavailable["candidate_results"], [], "CPU resolver unavailable telemetry skips benchmarks")

    tuning_cache = {}
    worker_calls = []
    single = resolve_cpu_execution_policy(
        backend="cpu_native_helper",
        requested_mode="auto",
        resolved_mode="avx2",
        kernel_flavor="avx2",
        tuning_policy="max_power",
        candidate_kernel_flavors=["avx512_fma"],
        tune_max_power=True,
        worker_count=lambda: worker_calls.append(True) or 16,
        power_tuning_available=lambda: True,
        benchmark_candidate=unexpected_benchmark,
        tuning_cache=tuning_cache,
    )
    assert_equal(single["kernel_flavor"], "avx512_fma", "CPU resolver single candidate flavor")
    assert_equal(single["resolved_mode"], "avx512", "CPU resolver single candidate mode")
    assert_equal(len(worker_calls), 1, "CPU resolver tuning cache worker count")
    single["kernel_flavor"] = "mutated"
    cached = resolve_cpu_execution_policy(
        backend="cpu_native_helper",
        requested_mode="auto",
        resolved_mode="avx2",
        kernel_flavor="avx2",
        tuning_policy="max_power",
        candidate_kernel_flavors=["avx512_fma"],
        tune_max_power=True,
        worker_count=lambda: 16,
        power_tuning_available=lambda: True,
        benchmark_candidate=unexpected_benchmark,
        tuning_cache=tuning_cache,
    )
    assert_equal(cached["kernel_flavor"], "avx512_fma", "CPU resolver defensive cache copy")

    failed_results = [
        {"kernel_flavor": "avx2_fma", "valid": False, "avg_cpu_power_w": 150.0},
        {"kernel_flavor": "scalar", "valid": True, "avg_cpu_power_w": None},
    ]
    failed = resolve_cpu_execution_policy(
        backend="cpu_native_helper",
        requested_mode="auto",
        resolved_mode="avx2",
        kernel_flavor="avx2",
        tuning_policy="max_power",
        candidate_kernel_flavors=["avx2_fma", "scalar"],
        tune_max_power=True,
        worker_count=lambda: 8,
        power_tuning_available=lambda: True,
        benchmark_candidate=lambda flavor: dict(next(item for item in failed_results if item["kernel_flavor"] == flavor)),
        tuning_cache={},
    )
    assert_equal(failed["tuned"], False, "CPU resolver invalid candidates remain untuned")
    assert_equal(len(failed["candidate_results"]), 2, "CPU resolver preserves failed candidate evidence")

    benchmark_calls = []
    benchmark_results = {
        "avx2_fma": {"kernel_flavor": "avx2_fma", "valid": True, "avg_cpu_power_w": 120.0},
        "avx512_fma": {"kernel_flavor": "avx512_fma", "valid": True, "avg_cpu_power_w": 145.0},
    }
    tuned = resolve_cpu_execution_policy(
        backend="cpu_native_helper",
        requested_mode="auto",
        resolved_mode="avx2",
        kernel_flavor="avx2_fma",
        tuning_policy="max_power",
        candidate_kernel_flavors=["avx2_fma", "avx512_fma"],
        tune_max_power=True,
        worker_count=lambda: 32,
        power_tuning_available=lambda: True,
        benchmark_candidate=lambda flavor: benchmark_calls.append(flavor) or dict(benchmark_results[flavor]),
        tuning_cache={},
    )
    assert_equal(benchmark_calls, ["avx2_fma", "avx512_fma"], "CPU resolver benchmark order")
    assert_equal(tuned["kernel_flavor"], "avx512_fma", "CPU resolver best power candidate")
    assert_equal(tuned["resolved_mode"], "avx512", "CPU resolver tuned mode")
    assert_equal(tuned["tuned_avg_power_w"], 145.0, "CPU resolver tuned power")


def test_cpu_execution_helpers_build_and_parse_helper_probes() -> None:
    assert_equal(normalize_cpu_helper_mode("AVX2"), "avx2", "CPU helper mode normalization")
    assert_equal(normalize_cpu_helper_mode("bad"), "auto", "CPU helper invalid mode normalization")
    assert_equal(normalize_cpu_probe_mode(""), "auto", "CPU probe empty mode normalization")
    assert_equal(
        build_cpu_resolved_mode_probe_command("/tmp/cpu_helper", "AVX2"),
        ["/tmp/cpu_helper", "--mode", "avx2", "--print-resolved-mode"],
        "CPU resolved-mode probe command",
    )
    assert_equal(
        build_cpu_default_kernel_probe_command("/tmp/cpu_helper", "auto"),
        ["/tmp/cpu_helper", "--mode", "auto", "--print-kernel-flavor"],
        "CPU default-kernel probe command",
    )
    assert_equal(
        build_cpu_kernel_support_probe_command("/tmp/cpu_helper", "AVX2_FMA"),
        ["/tmp/cpu_helper", "--kernel-flavor", "avx2_fma", "--print-kernel-flavor"],
        "CPU kernel-support probe command",
    )
    assert_equal(parse_cpu_resolved_mode_probe(0, "AVX512\n"), "avx512", "CPU resolved-mode probe parse")
    assert_equal(parse_cpu_resolved_mode_probe(1, "avx2"), "", "CPU resolved-mode probe rejects nonzero")
    assert_equal(parse_cpu_resolved_mode_probe(0, "bad"), "", "CPU resolved-mode probe rejects unknown")
    assert_equal(parse_cpu_default_kernel_probe(0, "avx2_fma\n"), "avx2_fma", "CPU default-kernel probe parse")
    assert_equal(parse_cpu_default_kernel_probe(0, "bad"), "", "CPU default-kernel probe rejects unknown")
    assert_equal(cpu_kernel_support_probe_matches(0, "AVX2_FMA\n", "avx2_fma"), True, "CPU kernel support match")
    assert_equal(cpu_kernel_support_probe_matches(0, "avx", "avx2_fma"), False, "CPU kernel support mismatch")


def test_cpu_execution_helpers_build_commands_and_benchmark_results() -> None:
    helper_cmd = build_cpu_command(
        worker_count=4,
        helper_available=True,
        helper_path="/tmp/cpu_helper",
        requested_mode="auto",
        instruction_set="avx2",
        mode="normal",
        stress_ng_available=True,
        python_runtime="/usr/bin/python3",
        cpu_kernel_flavor="avx2_fma",
        result_file="/tmp/result.json",
    )
    assert_equal(
        helper_cmd,
        [
            "/tmp/cpu_helper",
            "--mode",
            "auto",
            "--threads",
            "4",
            "--kernel-flavor",
            "avx2_fma",
            "--result-file",
            "/tmp/result.json",
        ],
        "CPU native helper command",
    )

    stress_cmd = build_cpu_command(
        worker_count=2,
        helper_available=False,
        helper_path="",
        requested_mode="auto",
        instruction_set="sse",
        mode="normal",
        stress_ng_available=True,
        python_runtime="/usr/bin/python3",
    )
    assert_equal(stress_cmd, ["stress-ng", "--cpu", "2", "--cpu-method", "int64", "--metrics-brief"], "CPU stress-ng SSE command")

    fallback_cmd = build_cpu_command(
        worker_count=1,
        helper_available=False,
        helper_path="",
        requested_mode="auto",
        instruction_set="avx512",
        mode="extreme",
        stress_ng_available=False,
        python_runtime="/usr/bin/python3",
    )
    assert_equal(fallback_cmd[:2] if fallback_cmd else [], ["/usr/bin/python3", "-c"], "CPU Python fallback command")
    assert_true("ITERATIONS = 180000" in fallback_cmd[2], "CPU fallback script intensity")
    assert_equal(cpu_fallback_params("sse", "normal")["algorithm"], "sha256", "CPU fallback SSE params")
    assert_true("count = 3" in build_cpu_fallback_script("auto", "normal", 3), "CPU fallback worker count")

    ok_result = build_cpu_benchmark_result(
        kernel_flavor="avx2_fma",
        samples=[100.0, 110.0],
        result_payload={"status": "ok", "error_count": 0},
        return_code=0,
    )
    assert_equal(ok_result["avg_cpu_power_w"], 105.0, "CPU benchmark average")
    assert_equal(ok_result["valid"], True, "CPU benchmark valid result")

    failed_result = build_cpu_benchmark_result(
        kernel_flavor="scalar",
        samples=[150.0],
        result_payload={"status": "error", "error_count": 1},
        return_code=4,
    )
    assert_equal(failed_result["valid"], False, "CPU benchmark failed result invalid")

    class FakeTelemetry:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.samples: list[SimpleNamespace] = []
            self.values = [101.0, 123.0]

        def collect_once(self) -> None:
            value = self.values[min(len(self.samples), len(self.values) - 1)]
            self.samples.append(SimpleNamespace(values={"cpu_power_w": value}))

    class FakeProcess:
        returncode = 0

        def poll(self) -> object:
            return None

    def fake_temp_file_factory(prefix: str, suffix: str, delete: bool) -> object:
        class FakeTempFile:
            def __init__(self) -> None:
                self.name = str(Path(temp_dir.name) / f"{prefix}fixture{suffix}")

            def __enter__(self) -> object:
                return self

            def __exit__(self, *args: object) -> bool:
                return False

        return FakeTempFile()

    monotonic_values = iter([0.0, 0.05, 0.15, 0.2, 0.25, 0.35])
    popen_calls: list[dict] = []
    stopped: list[object] = []

    with TemporaryDirectory() as temp_name:
        temp_dir = SimpleNamespace(name=temp_name)

        def build_benchmark_command(flavor: str, result_path: str) -> list[str]:
            Path(result_path).write_text(json.dumps({"status": "ok", "error_count": 0}), encoding="utf-8")
            return ["cpu-helper", "--kernel-flavor", flavor]

        benchmark = benchmark_cpu_kernel_candidate(
            kernel_flavor="avx2_fma",
            build_command=build_benchmark_command,
            command_env={"LVS": "1"},
            telemetry_collector_factory=FakeTelemetry,
            popen_factory=lambda cmd, **kwargs: popen_calls.append({"cmd": cmd, **kwargs}) or FakeProcess(),
            stop_processes=lambda processes: stopped.extend(processes),
            temp_file_factory=fake_temp_file_factory,
            interval_seconds=0.1,
            warmup_seconds=0.1,
            measure_seconds=0.2,
            runtime_environment={"ENV": "1"},
            privileged_helper_enabled=True,
            stdout_target="stdout-null",
            stderr_target="stderr-null",
            monotonic=lambda: next(monotonic_values, 0.35),
            sleep=lambda seconds: None,
        )
    assert_equal(benchmark["kernel_flavor"], "avx2_fma", "CPU benchmark helper kernel flavor")
    assert_equal(benchmark["avg_cpu_power_w"], 112.0, "CPU benchmark helper average")
    assert_equal(benchmark["valid"], True, "CPU benchmark helper valid payload")
    assert_equal(popen_calls[0]["cmd"], ["cpu-helper", "--kernel-flavor", "avx2_fma"], "CPU benchmark helper command")
    assert_equal(popen_calls[0]["env"], {"LVS": "1"}, "CPU benchmark helper env")
    assert_equal(len(stopped), 1, "CPU benchmark helper stops process")

    with TemporaryDirectory() as temp_name:
        temp_dir = SimpleNamespace(name=temp_name)
        no_command = benchmark_cpu_kernel_candidate(
            kernel_flavor="scalar",
            build_command=lambda flavor, result_path: None,
            command_env={},
            telemetry_collector_factory=FakeTelemetry,
            popen_factory=lambda cmd, **kwargs: FakeProcess(),
            stop_processes=lambda processes: None,
            temp_file_factory=fake_temp_file_factory,
            interval_seconds=0.1,
            warmup_seconds=0.1,
            measure_seconds=0.2,
            runtime_environment={},
            privileged_helper_enabled=False,
            stdout_target=None,
            stderr_target=None,
        )
    assert_equal(
        no_command,
        {"kernel_flavor": "scalar", "avg_cpu_power_w": None, "max_cpu_power_w": None},
        "CPU benchmark helper no-command result",
    )


def test_memory_execution_helpers_build_commands_and_targets() -> None:
    assert_equal(memory_worker_count("all", 16), 16, "memory all-worker count")
    assert_equal(memory_worker_count("4", 16), 4, "memory explicit worker count")
    assert_equal(memory_worker_count("bad", 16), 16, "memory invalid worker count fallback")
    assert_equal(memory_target_bytes(50, 1024 * 1024, 1024 * 1024), 512 * 1024 * 1024, "memory target total cap")
    assert_equal(memory_target_bytes(95, 0, 0), 512 * 1024 * 1024, "memory target missing meminfo fallback")

    helper_cmd = build_memory_command(
        helper_available=True,
        helper_path="/tmp/memory_helper",
        target_bytes=1024,
        worker_count=2,
        allocation_percent=80,
        stress_ng_available=True,
        python_runtime="/usr/bin/python3",
        result_file="/tmp/memory.json",
    )
    assert_equal(
        helper_cmd,
        ["/tmp/memory_helper", "--bytes", "1024", "--threads", "2", "--result-file", "/tmp/memory.json"],
        "memory native helper command",
    )

    stress_cmd = build_memory_command(
        helper_available=False,
        helper_path="",
        target_bytes=1024,
        worker_count=2,
        allocation_percent=80,
        stress_ng_available=True,
        python_runtime="/usr/bin/python3",
    )
    assert_equal(stress_cmd, ["stress-ng", "--vm", "1", "--vm-bytes", "80%", "--vm-keep"], "memory stress-ng command")

    fallback_cmd = build_memory_command(
        helper_available=False,
        helper_path="",
        target_bytes=1024,
        worker_count=2,
        allocation_percent=120,
        stress_ng_available=False,
        python_runtime="/usr/bin/python3",
    )
    assert_equal(fallback_cmd[:2] if fallback_cmd else [], ["/usr/bin/python3", "-c"], "memory Python fallback command")
    assert_true("95 / 100.0" in fallback_cmd[2], "memory fallback clamps allocation percent")
    assert_true("target_kb = int" in build_memory_fallback_script(80), "memory fallback script target")


def test_native_helper_status_helpers_resolve_build_states() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "helper.c"
        binary = root / "helper"
        base = native_helper_status_base(source, binary, None)
        assert_equal(base["path"], str(binary), "native helper base path")
        assert_equal(
            native_helper_build_command("/usr/bin/gcc", source, binary),
            ["/usr/bin/gcc", "-O3", "-std=c11", "-pthread", str(source), "-o", str(binary)],
            "native helper build command",
        )

        missing = resolve_native_helper_status(
            source=source,
            binary=binary,
            compiler="/usr/bin/gcc",
            reason_label="CPU",
            build_runner=lambda cmd: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        assert_equal(missing["available"], False, "native helper missing source unavailable")
        assert_equal(missing["reason"], "native CPU helper source missing", "native helper missing source reason")

        source.write_text("int main(void){return 0;}\n", encoding="utf-8")
        no_compiler = resolve_native_helper_status(
            source=source,
            binary=binary,
            compiler=None,
            reason_label="memory",
            build_runner=lambda cmd: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        assert_equal(no_compiler["reason"], "no C compiler found; install gcc or build-essential", "native helper no compiler reason")

        def successful_build(cmd: list[str]) -> SimpleNamespace:
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        built = resolve_native_helper_status(
            source=source,
            binary=binary,
            compiler="/usr/bin/gcc",
            reason_label="CPU",
            build_runner=successful_build,
        )
        assert_equal(built["available"], True, "native helper successful build available")
        assert_equal(built["built"], True, "native helper successful build flag")

        binary.unlink()
        failed = resolve_native_helper_status(
            source=source,
            binary=binary,
            compiler="/usr/bin/gcc",
            reason_label="memory",
            build_runner=lambda cmd: SimpleNamespace(returncode=2, stdout="stdout reason", stderr=""),
        )
        assert_equal(failed["available"], False, "native helper failed build unavailable")
        assert_equal(failed["reason"], "stdout reason", "native helper failed build reason")


def test_native_helper_runtime_service() -> None:
    compiler_queries = []
    assert_equal(
        find_c_compiler(lambda name: compiler_queries.append(name) or ("/usr/bin/cc" if name == "cc" else None)),
        "/usr/bin/cc",
        "native runtime compiler fallback",
    )
    assert_equal(compiler_queries, ["gcc", "cc"], "native runtime compiler search order")

    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        source = root / "cpu_helper.c"
        binary = root / "cpu_helper"
        source.write_text("int main(void){return 0;}\n", encoding="utf-8")
        command_calls = []

        def run_command(command, **kwargs):
            command_calls.append((list(command), dict(kwargs)))
            if "-std=c11" in command:
                binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                binary.chmod(0o755)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "--mode" in command and "--print-resolved-mode" in command:
                return SimpleNamespace(returncode=0, stdout="avx2\n", stderr="")
            if "--mode" in command and "--print-kernel-flavor" in command:
                return SimpleNamespace(returncode=0, stdout="avx2_fma\n", stderr="")
            if "--kernel-flavor" in command:
                flavor = command[command.index("--kernel-flavor") + 1]
                return SimpleNamespace(
                    returncode=0 if flavor == "avx2_fma" else 2,
                    stdout=f"{flavor}\n" if flavor == "avx2_fma" else "",
                    stderr="",
                )
            raise AssertionError(f"unexpected native helper command: {command}")

        service = NativeHelperRuntimeService(
            command_env=lambda: {"LVS_NATIVE_TEST": "1"},
            run_command=run_command,
        )
        compiler_calls = []
        status = service.helper_status(
            cache_key="cpu",
            source=source,
            binary=binary,
            compiler_path=lambda: compiler_calls.append(True) or "/usr/bin/gcc",
            reason_label="CPU",
        )
        assert_equal(status["available"], True, "native runtime built helper available")
        assert_equal(status["built"], True, "native runtime built helper flag")
        assert_equal(command_calls[0][1]["timeout"], 60, "native runtime build timeout")
        assert_equal(command_calls[0][1]["env"], {"LVS_NATIVE_TEST": "1"}, "native runtime build environment")
        cached_status = service.helper_status(
            cache_key="cpu",
            source=source,
            binary=binary,
            compiler_path=lambda: compiler_calls.append(True) or "/unexpected/compiler",
            reason_label="CPU",
        )
        assert_true(cached_status is status, "native runtime status cache identity")
        assert_equal(len(compiler_calls), 1, "native runtime cached status skips compiler lookup")

        helper_status_calls = []

        def helper_status():
            helper_status_calls.append(True)
            return status

        assert_equal(service.cpu_resolved_mode("AUTO", helper_status=helper_status), "avx2", "native runtime resolved mode")
        assert_equal(service.cpu_resolved_mode("auto", helper_status=helper_status), "avx2", "native runtime resolved mode cache")
        assert_equal(service.cpu_default_kernel_flavor("auto", helper_status=helper_status), "avx2_fma", "native runtime default kernel")
        assert_equal(service.cpu_default_kernel_flavor("AUTO", helper_status=helper_status), "avx2_fma", "native runtime kernel cache")
        assert_true(service.cpu_supports_kernel_flavor("AVX2_FMA", helper_status=helper_status), "native runtime supported kernel")
        assert_true(service.cpu_supports_kernel_flavor("avx2_fma", helper_status=helper_status), "native runtime supported kernel cache")
        assert_true(not service.cpu_supports_kernel_flavor("scalar", helper_status=helper_status), "native runtime unsupported kernel")
        assert_true(not service.cpu_supports_kernel_flavor("scalar", helper_status=helper_status), "native runtime unsupported kernel cache")
        probe_calls = [call for call in command_calls if "--print-resolved-mode" in call[0] or "--print-kernel-flavor" in call[0]]
        assert_equal(len(probe_calls), 4, "native runtime executes each normalized probe once")
        assert_true(all(call[1]["timeout"] == 10 for call in probe_calls), "native runtime probe timeout")
        assert_true(all(call[1]["env"] == {"LVS_NATIVE_TEST": "1"} for call in probe_calls), "native runtime probe environment")

        unavailable_service = NativeHelperRuntimeService(command_env=lambda: {}, run_command=run_command)
        unavailable_calls = []
        unavailable_status = lambda: unavailable_calls.append(True) or {"available": False, "path": str(binary)}
        assert_equal(unavailable_service.cpu_resolved_mode("auto", helper_status=unavailable_status), "", "native runtime unavailable mode")
        assert_true(
            not unavailable_service.cpu_supports_kernel_flavor("avx2", helper_status=unavailable_status),
            "native runtime unavailable kernel",
        )
        assert_true(
            not unavailable_service.cpu_supports_kernel_flavor("avx2", helper_status=unavailable_status),
            "native runtime unavailable kernel cache",
        )
        assert_equal(len(unavailable_calls), 2, "native runtime caches unsupported result only")


def test_backend_readiness_helpers_build_payloads() -> None:
    availability = build_backend_availability(
        cpu_native_helper_available=True,
        memory_native_helper_available=False,
        command_available={
            "stress-ng": True,
            "glmark2": False,
            "vkmark": True,
            "vkcube": False,
            "glxgears": True,
            "nvidia-smi": True,
            "intel_gpu_top": False,
            "ipmitool": True,
            "ipmi-sensors": False,
        },
        vulkaninfo_available=True,
        python_vulkan_compute_available=True,
        python_vulkan_transfer_available=False,
        python_opencl_available=True,
        python_egl_gles2_available=False,
        python_runtime_available=True,
    )
    assert_equal(availability["cpu_native_helper"], True, "backend readiness CPU helper")
    assert_equal(availability["memory_native_helper"], False, "backend readiness memory helper")
    assert_equal(availability["python_opencl_compute"], True, "backend readiness OpenCL compute alias")
    assert_equal(availability["python_opencl"], True, "backend readiness OpenCL VRAM alias")
    assert_equal(availability["ipmi_sensors"], False, "backend readiness ipmi-sensors key")
    availability_from_sources = build_backend_availability_from_probe_results(
        cpu_native_helper={"available": True},
        memory_native_helper={"available": False},
        command_available={
            "stress-ng": True,
            "glmark2": False,
            "vkmark": True,
            "vkcube": False,
            "glxgears": True,
            "nvidia-smi": True,
            "intel_gpu_top": False,
            "ipmitool": True,
            "ipmi-sensors": False,
        },
        vulkaninfo={"available": True},
        python_vulkan_compute={"available": True},
        python_vulkan_transfer={"available": False},
        python_opencl={"available": True},
        python_egl_gles2={"available": False},
        python_runtime_available=True,
    )
    assert_equal(availability_from_sources, availability, "backend readiness availability from sources")

    modes = probe_cpu_helper_modes(lambda mode: f"{mode}-resolved", modes=("auto", "avx2"))
    assert_equal(modes, {"auto": "auto-resolved", "avx2": "avx2-resolved"}, "backend readiness CPU mode probes")

    unavailable = enrich_cpu_helper_backend_details(
        {"available": False, "path": "helper"},
        resolved_modes={"auto": "avx2"},
        default_kernel_flavors={"auto": "avx2_fma"},
        supported_kernel_flavors=["avx2_fma"],
    )
    assert_true("resolved_modes" not in unavailable, "backend readiness leaves unavailable helper un-enriched")

    enriched = enrich_cpu_helper_backend_details(
        {"available": True, "path": "helper"},
        resolved_modes={"auto": "avx2"},
        default_kernel_flavors={"auto": "avx2_fma"},
        supported_kernel_flavors=["avx2_fma"],
    )
    assert_equal(enriched["resolved_modes"]["auto"], "avx2", "backend readiness helper resolved modes")
    assert_equal(enriched["supported_kernel_flavors"], ["avx2_fma"], "backend readiness helper kernels")

    details = build_backend_details_payload(
        cpu_native_helper=enriched,
        memory_native_helper={"available": True},
        gpu_3d_catalog={"python_opencl_compute": {"label": "OpenCL"}},
        python_opencl_compute={"available": True, "safety_profile": {}},
        python_opencl={"available": True},
        python_egl_gles2={"available": False},
        python_vulkan_compute={"available": True},
        python_vulkan_transfer={"available": True},
        vulkaninfo={"available": True},
        nvidia_smi={"available": False, "path": ""},
        intel_gpu_top={"usable": True},
        ipmi_sensors={"available": False},
    )
    assert_equal(details["gpu_3d_catalog"]["python_opencl_compute"]["label"], "OpenCL", "backend details catalog")
    assert_equal(details["intel_gpu_top"]["usable"], True, "backend details intel telemetry")

    source_details = build_backend_details_from_probe_results(
        cpu_native_helper={"available": True, "path": "helper"},
        memory_native_helper={"available": True},
        cpu_mode_resolver=lambda mode: f"{mode}-resolved",
        cpu_default_kernel_flavor_resolver=lambda mode: f"{mode}-kernel",
        cpu_supported_kernel_flavors=lambda: ["scalar", "avx2_fma"],
        gpu_3d_catalog={"python_opencl_compute": {"label": "OpenCL"}},
        python_opencl={"available": True, "platforms": 1},
        opencl_safety_profile={"safe_mode_enabled": True},
        python_egl_gles2={"available": False},
        python_vulkan_compute={"available": True},
        python_vulkan_transfer={"available": True},
        vulkaninfo={"available": True},
        nvidia_smi_available=False,
        intel_gpu_top={"usable": True},
        ipmi_sensors={"available": False},
    )
    assert_equal(source_details["cpu_native_helper"]["resolved_modes"]["auto"], "auto-resolved", "backend details source CPU modes")
    assert_equal(source_details["python_opencl_compute"]["safety_profile"]["safe_mode_enabled"], True, "backend details source OpenCL safety")
    assert_equal(source_details["python_opencl"]["platforms"], 1, "backend details source OpenCL VRAM alias")
    assert_equal(source_details["nvidia_smi"]["path"], "", "backend details source NVIDIA path")

    class FakeBackendRunner:
        def __init__(self) -> None:
            self.commands = {
                "stress-ng": True,
                "glmark2": False,
                "vkmark": True,
                "vkcube": False,
                "glxgears": True,
                "nvidia-smi": True,
                "intel_gpu_top": False,
                "ipmitool": False,
                "ipmi-sensors": True,
            }

        def _cpu_helper_status(self) -> dict:
            return {"available": True, "path": "cpu-helper"}

        def _memory_helper_status(self) -> dict:
            return {"available": True, "path": "memory-helper"}

        def _command_exists(self, name: str) -> bool:
            return bool(self.commands.get(name))

        def _vulkan_runtime_details(self) -> dict:
            return {"available": True}

        def _vulkan_native_backend(self) -> dict:
            return {"available": True}

        def _vulkan_transfer_backend(self) -> dict:
            return {"available": True}

        def _opencl_gpu_backend(self) -> dict:
            return {"available": True, "platforms": 2}

        def _egl_gpu_backend(self) -> dict:
            return {"available": False, "reason": "no EGL"}

        def _python_runtime(self) -> str:
            return "python3.14"

        def _cpu_helper_resolved_mode(self, mode: str) -> str:
            return f"{mode}-resolved"

        def _cpu_helper_default_kernel_flavor(self, mode: str) -> str:
            return f"{mode}-kernel"

        def _cpu_supported_kernel_flavors(self) -> list[str]:
            return ["scalar", "avx2_fma"]

        def _gpu_3d_backend_catalog_entry(self, backend: str) -> dict:
            return {"backend": backend, "label": backend.upper()}

        def _opencl_compute_safety_profile(self) -> dict:
            return {"safe_mode_enabled": True}

        def _intel_gpu_top_details(self) -> dict:
            return {"usable": False}

        def _ipmi_sensor_details(self) -> dict:
            return {"available": True}

    fake_runner = FakeBackendRunner()
    runner_availability = collect_backend_availability_from_runner(fake_runner)
    assert_equal(runner_availability["cpu_native_helper"], True, "backend readiness runner CPU helper")
    assert_equal(runner_availability["python_opencl"], True, "backend readiness runner OpenCL")
    assert_equal(runner_availability["python_egl_gles2"], False, "backend readiness runner EGL")
    assert_equal(runner_availability["ipmi_sensors"], True, "backend readiness runner IPMI sensors")
    runner_details = collect_backend_details_from_runner(fake_runner, ["python_opencl_compute", "python_egl_gles2"])
    assert_equal(runner_details["gpu_3d_catalog"]["python_opencl_compute"]["label"], "PYTHON_OPENCL_COMPUTE", "backend details runner catalog")
    assert_equal(runner_details["python_opencl"]["platforms"], 2, "backend details runner OpenCL")
    assert_equal(runner_details["python_opencl_compute"]["safety_profile"]["safe_mode_enabled"], True, "backend details runner safety profile")
    assert_equal(runner_details["nvidia_smi"]["available"], True, "backend details runner NVIDIA command")

    supported_calls: List[str] = []
    unavailable_source_details = build_backend_details_from_probe_results(
        cpu_native_helper={"available": False, "path": "helper"},
        memory_native_helper={"available": True},
        cpu_mode_resolver=lambda mode: f"{mode}-resolved",
        cpu_default_kernel_flavor_resolver=lambda mode: f"{mode}-kernel",
        cpu_supported_kernel_flavors=lambda: supported_calls.append("called") or ["avx2_fma"],
        gpu_3d_catalog={},
        python_opencl={},
        opencl_safety_profile={},
        python_egl_gles2={},
        python_vulkan_compute={},
        python_vulkan_transfer={},
        vulkaninfo={},
        nvidia_smi_available=True,
        intel_gpu_top={},
        ipmi_sensors={},
    )
    assert_true("resolved_modes" not in unavailable_source_details["cpu_native_helper"], "backend details source skips unavailable CPU enrichment")
    assert_equal(supported_calls, [], "backend details source keeps CPU supported-kernel provider lazy")

    opencl_payload = build_opencl_backend_payload(
        selected_probe={
            "available": True,
            "context": "native",
            "selected_env": {"OCL": "native"},
            "library": "libOpenCL.so",
        },
        probe_attempts=[
            {
                "context": "native",
                "available": True,
                "selected_env": {"OCL": "native"},
                "devices": [{"name": "GPU"}],
                "platform_count": 1,
                "platforms": [{"name": "Platform"}],
            }
        ],
        devices=[
            {
                "name": "GPU",
                "probe_context": "native",
                "required_env": {"OCL": "native"},
            }
        ],
    )
    assert_equal(opencl_payload["available"], True, "backend readiness OpenCL payload available")
    assert_equal(opencl_payload["selected_context"], "native", "backend readiness OpenCL native context")
    assert_equal(opencl_payload["selected_env"], {"OCL": "native"}, "backend readiness OpenCL native env")
    assert_equal(opencl_payload["devices"][0]["opencl_index"], 0, "backend readiness OpenCL device index")
    assert_equal(opencl_payload["probe_attempts"][0]["device_count"], 1, "backend readiness OpenCL attempt device count")

    mixed_opencl_payload = build_opencl_backend_payload(
        selected_probe={"available": True, "context": "native", "selected_env": {"OCL": "native"}},
        probe_attempts=[
            {"context": "native", "available": True, "selected_env": {}, "devices": [{"name": "GPU A"}]},
            {"context": "rusticl", "available": True, "selected_env": {"RUSTICL": "1"}, "devices": [{"name": "GPU B"}]},
        ],
        devices=[
            {"name": "GPU A", "probe_context": "native"},
            {"name": "GPU B", "probe_context": "rusticl"},
        ],
    )
    assert_equal(mixed_opencl_payload["selected_context"], "mixed_per_target", "backend readiness OpenCL mixed context")
    assert_equal(mixed_opencl_payload["selected_env"], {}, "backend readiness OpenCL mixed env omitted")

    empty_opencl_payload = build_opencl_backend_payload(
        selected_probe={"available": False, "context": "rusticl", "selected_env": {"RUSTICL": "1"}},
        probe_attempts=[],
        devices=[],
    )
    assert_equal(empty_opencl_payload["available"], False, "backend readiness empty OpenCL unavailable")
    assert_equal(empty_opencl_payload["selected_context"], "rusticl", "backend readiness empty OpenCL context fallback")

    egl_payload = build_egl_backend_payload(
        payload={"available": True, "renderer": "RADV Navi", "vendor": "Mesa"},
        returncode=0,
        stdout="",
        stderr="",
        target={"card": "card1", "dri_prime": "pci-0000_01_00_0"},
        is_software_renderer=lambda renderer: "llvmpipe" in renderer.lower(),
    )
    assert_equal(egl_payload["available"], True, "backend readiness EGL hardware available")
    assert_equal(egl_payload["renderer"], "RADV Navi", "backend readiness EGL renderer")
    assert_equal(egl_payload["target_gpu"], "card1", "backend readiness EGL target GPU")
    assert_equal(egl_payload["target_dri_prime"], "pci-0000_01_00_0", "backend readiness EGL DRI prime")

    egl_software = build_egl_backend_payload(
        payload={"available": True, "renderer": "llvmpipe", "vendor": "Mesa"},
        returncode=0,
        stdout="",
        stderr="",
        target=None,
        is_software_renderer=lambda renderer: "llvmpipe" in renderer.lower(),
    )
    assert_equal(egl_software["available"], False, "backend readiness EGL software unavailable")
    assert_equal(egl_software["reason"], "software renderer detected: llvmpipe", "backend readiness EGL software reason")

    egl_failed = build_egl_backend_payload(
        payload={},
        returncode=1,
        stdout="stdout failure",
        stderr="stderr failure",
        target=None,
        is_software_renderer=lambda _renderer: False,
    )
    assert_equal(egl_failed["reason"], "stderr failure", "backend readiness EGL stderr reason")

    egl_empty = build_egl_backend_payload(
        payload={},
        returncode=0,
        stdout="",
        stderr="",
        target=None,
        is_software_renderer=lambda _renderer: False,
    )
    assert_equal(egl_empty["reason"], "EGL hardware renderer unavailable", "backend readiness EGL empty reason")

    class FakePath:
        def __init__(self, path: str, exists: bool) -> None:
            self.path = path
            self._exists = exists

        def exists(self) -> bool:
            return self._exists

        def __str__(self) -> str:
            return self.path

    vulkan_native = build_vulkan_native_backend_payload(
        runtime={
            "available": True,
            "instance_version": "1.3.0",
            "devices": [
                {"deviceType": "CPU", "deviceName": "llvmpipe"},
                {"deviceType": "DISCRETE_GPU", "deviceName": "GPU 1"},
            ],
        },
        library="libvulkan.so.1",
        loader_version="1.3.0",
        loader_reason="",
        native_inventory={"available": False, "reason": "unused"},
        worker_path=FakePath("native/vulkan_compute_worker.py", True),
    )
    assert_equal(vulkan_native["available"], True, "backend readiness Vulkan native available")
    assert_equal(vulkan_native["runtime_device_count"], 2, "backend readiness Vulkan native device count")
    assert_equal(vulkan_native["runtime_gpu_device_count"], 1, "backend readiness Vulkan native GPU filtering")
    assert_equal(vulkan_native["target_verification"], "compute_readback", "backend readiness Vulkan native verification")
    vulkan_transfer = build_vulkan_transfer_backend_payload(
        vulkan_native,
        worker_path=FakePath("native/vulkan_transfer_worker.py", True),
    )
    assert_equal(vulkan_transfer["available"], True, "backend readiness Vulkan transfer available")
    assert_equal(vulkan_transfer["planned_backend"], "python_vulkan_transfer", "backend readiness Vulkan transfer backend")
    assert_equal(vulkan_transfer["target_verification"], "transfer_readback", "backend readiness Vulkan transfer verification")

    missing_vulkan = build_vulkan_native_backend_payload(
        runtime={"available": False, "reason": "runtime missing", "devices": []},
        library="",
        loader_version="",
        loader_reason="loader missing",
        native_inventory={"available": False, "reason": "native missing"},
        worker_path=FakePath("native/vulkan_compute_worker.py", False),
    )
    assert_equal(missing_vulkan["available"], False, "backend readiness missing Vulkan unavailable")
    assert_true("loader missing" in missing_vulkan["reason"], "backend readiness missing Vulkan loader reason")
    assert_true("worker script not found" in missing_vulkan["reason"], "backend readiness missing Vulkan worker reason")


def test_vulkan_runtime_discovery_helpers() -> None:
    summary = """Vulkan Instance Version: 1.3.280
GPU0:
    apiVersion = 1.3.280
    vendorID = 0x10de
    deviceID = 0x2b85
    deviceType = VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    deviceName = NVIDIA RTX
GPU1:
    apiVersion = 1.3.280
    deviceType = VK_PHYSICAL_DEVICE_TYPE_CPU
    deviceName = llvmpipe
"""
    parsed = parse_vulkaninfo_summary(summary)
    assert_equal(parsed["available"], True, "Vulkan runtime summary available")
    assert_equal(parsed["instance_version"], "1.3.280", "Vulkan runtime instance version")
    assert_equal(len(parsed["devices"]), 2, "Vulkan runtime summary device count")
    assert_equal(parsed["devices"][0]["deviceName"], "NVIDIA RTX", "Vulkan runtime summary device name")

    missing = collect_vulkan_runtime_details(
        command_exists=lambda _name: False,
        command_env=lambda: {},
    )
    assert_equal(missing["path"], "", "Vulkan runtime missing path")
    assert_equal(missing["reason"], "vulkaninfo not found", "Vulkan runtime missing reason")

    commands: List[List[str]] = []

    def fake_run(command: List[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(list(command))
        return SimpleNamespace(stdout=summary, stderr="driver warning", returncode=1)

    recovered = collect_vulkan_runtime_details(
        command_exists=lambda name: name == "vulkaninfo",
        command_env=lambda: {"TEST_ENV": "1"},
        run_command=fake_run,
    )
    assert_equal(commands, [["vulkaninfo", "--summary"]], "Vulkan runtime command")
    assert_equal(recovered["available"], True, "Vulkan runtime nonzero recovery")
    assert_equal(
        recovered["reason"],
        "vulkaninfo returned nonzero exit, but device inventory was recovered: driver warning",
        "Vulkan runtime nonzero recovery reason",
    )

    attempted_libraries: List[str] = []

    def fake_load_library(candidate: str) -> object:
        attempted_libraries.append(candidate)
        if candidate == "/custom/libvulkan.so":
            return object()
        raise OSError("not loadable")

    selected_library = resolve_vulkan_library(
        environment={"VULKAN_LIBRARY_PATH": "/custom/libvulkan.so"},
        find_library=lambda _name: "libvulkan.so.1",
        load_library=fake_load_library,
    )
    assert_equal(selected_library, "/custom/libvulkan.so", "Vulkan runtime environment library priority")
    assert_equal(attempted_libraries, ["/custom/libvulkan.so"], "Vulkan runtime library attempts")
    assert_equal(
        collect_vulkan_native_physical_devices(""),
        {"available": False, "devices": [], "reason": "Vulkan loader library not found"},
        "Vulkan native missing loader",
    )
    failed_inventory = collect_vulkan_native_physical_devices(
        "/bad/libvulkan.so",
        load_library=lambda _library: (_ for _ in ()).throw(OSError("loader failure")),
    )
    assert_equal(failed_inventory["reason"], "loader failure", "Vulkan native loader failure")

    with TemporaryDirectory(dir="/tmp") as tmp:
        worker_path = Path(tmp) / "vulkan_compute_worker.py"
        worker_path.touch()
        backend = build_vulkan_native_runtime_backend(
            runtime={
                "available": True,
                "instance_version": "1.3.280",
                "devices": [
                    {
                        "deviceType": "VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
                        "deviceName": "NVIDIA RTX",
                    }
                ],
            },
            worker_path=worker_path,
            library_resolver=lambda: "/custom/libvulkan.so",
            native_inventory_collector=lambda _library: {"available": False, "devices": [], "reason": "unused"},
            load_library=lambda _library: SimpleNamespace(),
        )
    assert_equal(backend["available"], True, "Vulkan runtime native backend available")
    assert_equal(backend["loader_version"], "1.0-compatible loader", "Vulkan runtime loader compatibility")
    assert_equal(backend["runtime_gpu_device_count"], 1, "Vulkan runtime backend GPU count")


def test_cpu_max_power_tuning_skips_invalid_candidates() -> None:
    import linux_validation_suite as lvs

    original_telemetry_collector = lvs.TelemetryCollector

    class FakeTelemetryCollector:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def detect_capabilities(self) -> dict:
            return {"cpu_power_w": {"available": True}}

    runner = WorkloadRunner()
    runner._cpu_backend_name = lambda cpu: "cpu_native_helper"
    runner._cpu_helper_mode = lambda cpu: "auto"
    runner._cpu_resolved_mode = lambda cpu: "avx2"
    runner._cpu_tuning_policy = lambda cpu: "max_power"
    runner._cpu_helper_default_kernel_flavor = lambda mode: "avx2"
    runner._cpu_candidate_kernel_flavors = lambda cpu: ["scalar", "avx2"]
    runner._cpu_worker_count = lambda cpu: 2
    benchmark_results = {
        "scalar": {
            "kernel_flavor": "scalar",
            "avg_cpu_power_w": 125.0,
            "max_cpu_power_w": 130.0,
            "valid": False,
            "return_code": 4,
            "status": "error",
            "error_count": 1,
        },
        "avx2": {
            "kernel_flavor": "avx2",
            "avg_cpu_power_w": 100.0,
            "max_cpu_power_w": 105.0,
            "valid": True,
            "return_code": 0,
            "status": "ok",
            "error_count": 0,
        },
    }
    runner._benchmark_cpu_kernel = lambda cpu, flavor: dict(benchmark_results[flavor])
    lvs.TelemetryCollector = FakeTelemetryCollector
    try:
        result = runner.resolve_cpu_execution(ModuleCpu(enabled=True, instruction_set="auto"), tune_max_power=True)
    finally:
        lvs.TelemetryCollector = original_telemetry_collector

    assert_equal(result["kernel_flavor"], "avx2", "CPU tuning skips invalid high-power candidate")
    assert_equal(result["tuned_avg_power_w"], 100.0, "CPU tuning keeps best valid candidate power")
    assert_equal(result["candidate_results"][0]["valid"], False, "CPU tuning preserves invalid candidate evidence")


def test_stage_event_state_helpers() -> None:
    existing: list[dict] = []
    reasons: list[str] = []
    events = [
        {
            "category": "worker_exit",
            "source": "gpu_3d",
            "message": "gpu_3d worker exited early with code 12",
            "severity": "error",
        }
    ]
    state = apply_stage_events(
        events,
        existing,
        reasons,
        "pass",
        abort_on_error=True,
    )
    assert_equal(state.verdict, "aborted", "error event aborts when policy requests abort")
    assert_true(state.aborted, "event state aborted flag")
    assert_equal(state.abort_reason, "gpu_3d worker exited early with code 12", "event abort reason")
    assert_equal(reasons, ["gpu_3d worker exited early with code 12"], "event failure reason")

    duplicate_state = apply_stage_events(
        events,
        existing,
        reasons,
        state.verdict,
        aborted=state.aborted,
        abort_reason=state.abort_reason,
    )
    assert_equal(duplicate_state.new_events, [], "duplicate events ignored")
    assert_equal(len(existing), 1, "duplicate event not appended")

    warning_existing: list[dict] = []
    warning_reasons: list[str] = []
    warning_state = apply_stage_events(
        [
            {
                "category": "thermal",
                "source": "gpu_0_temp_c",
                "message": "GPU temperature reached warning threshold",
                "severity": "warning",
            }
        ],
        warning_existing,
        warning_reasons,
        "pass",
    )
    assert_equal(warning_state.verdict, "warning", "warning event promotes pass to warning")
    assert_equal(warning_reasons, [], "warning event not stored as failure reason")

    existing_warning: list[dict] = []
    warning_error_reasons: list[str] = []
    fail_only_state = apply_stage_events(
        events,
        existing_warning,
        warning_error_reasons,
        "warning",
        fail_only_from_pass=True,
    )
    assert_equal(fail_only_state.verdict, "warning", "fail-only-from-pass preserves prior warning")
    assert_equal(warning_error_reasons, ["gpu_3d worker exited early with code 12"], "fail-only event still records reason")

    first_event_state = apply_stage_events(
        [
            {
                "category": "worker_integrity",
                "source": "gpu_3d",
                "message": "worker reported warning evidence",
                "severity": "warning",
            },
            {
                "category": "worker_integrity",
                "source": "gpu_3d",
                "message": "worker reported error evidence",
                "severity": "error",
            },
        ],
        [],
        [],
        "pass",
        abort_on_error=True,
        abort_reason_from_first_event=True,
    )
    assert_equal(first_event_state.abort_reason, "worker reported warning evidence", "first-event abort reason compatibility")


def test_stage_completion_helpers() -> None:
    stage = SimpleNamespace(
        id="segment_1",
        name="3D Adaptive",
        normalization=SimpleNamespace(trim_start_seconds=5, trim_end_seconds=7),
    )
    gpu_spec = SimpleNamespace(target_id="0000:01:00.0", backend="python_vulkan_compute")
    stage_processes = [SimpleNamespace(gpu_spec=gpu_spec), SimpleNamespace(gpu_spec=None)]

    def serialize_worker(spec: object) -> dict:
        return {
            "target_id": getattr(spec, "target_id", ""),
            "backend": getattr(spec, "backend", ""),
        }

    final_workers = serialize_final_gpu_workers(stage_processes, serialize_worker)
    assert_equal(final_workers, [{"target_id": "0000:01:00.0", "backend": "python_vulkan_compute"}], "final GPU worker serialization")
    assert_equal(stage_issue_count([{"severity": "warning"}, {"severity": "info"}, {"severity": "error"}]), 2, "stage issue count")
    check_window = build_stage_check_window(
        stage_window_cls=SimpleNamespace,
        stage=stage,
        display_name="GPU Stage",
        started_iso="2026-06-11T10:00:00-04:00",
        ended_iso="2026-06-11T10:01:00-04:00",
        started_monotonic=100.0,
        ended_monotonic=160.0,
        duration_seconds=60.0,
        gpu_target_mode="all",
        gpu_targets=["0000:01:00.0"],
        gpu_workers_initial=[{"target_id": "0000:01:00.0"}],
        gpu_workers_final=final_workers,
    )
    assert_equal(check_window.trim_start_seconds, 5, "check window default trim start")
    assert_equal(check_window.trim_end_seconds, 7, "check window default trim end")
    assert_equal(check_window.gpu_workers_final, final_workers, "check window final workers")
    live_window = build_stage_check_window(
        stage_window_cls=SimpleNamespace,
        stage=stage,
        display_name="GPU Stage",
        started_iso="2026-06-11T10:00:00-04:00",
        ended_iso="2026-06-11T10:00:10-04:00",
        started_monotonic=100.0,
        ended_monotonic=110.0,
        duration_seconds=10.0,
        trim_start_seconds=0,
        trim_end_seconds=0,
    )
    assert_equal(live_window.trim_start_seconds, 0, "check window live trim start override")
    assert_equal(live_window.trim_end_seconds, 0, "check window live trim end override")

    stage_plan: dict = {}
    error_events = [{"severity": "warning", "message": "thermal warning"}]
    record = complete_stage_record(
        stage_window_cls=SimpleNamespace,
        stage=stage,
        display_name="GPU Stage",
        stage_started_iso="2026-06-11T10:00:00-04:00",
        stage_ended_iso="2026-06-11T10:10:00-04:00",
        stage_start=100.0,
        stage_end=700.0,
        stage_elapsed=600.0,
        stage_processes=stage_processes,
        serialize_gpu_worker=serialize_worker,
        stage_plan=stage_plan,
        cpu_backend="cpu_native_helper",
        cpu_mode_requested="auto",
        cpu_mode_resolved="avx2",
        cpu_kernel_flavor="avx2",
        cpu_tuning_policy="max_power",
        cpu_tuned_avg_power_w=125.5,
        gpu_3d_backend_preference="vulkan_compute",
        gpu_3d_backend_resolved="python_vulkan_compute",
        vram_backend_preference="vulkan_memory",
        vram_backend_resolved="python_vulkan_compute",
        gpu_target_mode="all",
        gpu_targets=["0000:01:00.0"],
        gpu_workers_initial=[{"target_id": "0000:01:00.0"}],
        gpu_retune_events=[{"event": "retune"}],
        stage_verdict="warning",
        stage_failure_reasons=[],
        stage_error_events=error_events,
        stage_worker_results=[{"status": "pass"}],
        intel_gpu_top_sidecar_summary={"available": False},
        strict_threshold_recommendation_warnings=True,
        gpu_workers_final=final_workers,
    )
    assert_equal(record.issue_count, 1, "completion issue count")
    assert_equal(record.stage_window.display_name, "GPU Stage", "completion window display name")
    assert_equal(record.stage_window.gpu_workers_final, final_workers, "completion window final workers")
    assert_equal(stage_plan["gpu_workers_final"], final_workers, "completion mirrors final workers to plan")
    assert_equal(stage_plan["verdict"], "warning", "completion mirrors verdict to plan")
    assert_equal(stage_plan["worker_results"], [{"status": "pass"}], "completion mirrors worker results to plan")


def test_stage_evaluation_helpers() -> None:
    stage = SimpleNamespace(
        id="segment_1",
        name="3D Adaptive",
        normalization=SimpleNamespace(trim_start_seconds=5, trim_end_seconds=7),
        modules=SimpleNamespace(
            gpu_3d=SimpleNamespace(enabled=True, backend_preference="vulkan_compute"),
            vram=SimpleNamespace(enabled=True, backend_preference="vulkan_memory"),
        ),
    )
    gpu_spec = SimpleNamespace(target_id="0000:01:00.0", backend="python_vulkan_compute")
    stage_processes = [SimpleNamespace(gpu_spec=gpu_spec)]

    def serialize_worker(spec: object) -> dict:
        return {
            "target_id": getattr(spec, "target_id", ""),
            "backend": getattr(spec, "backend", ""),
        }

    callbacks_seen: list[str] = []

    def worker_events(processes: list, display_name: str) -> tuple[list[dict], list[dict]]:
        callbacks_seen.append("worker")
        return [{"status": "error"}], [
            {
                "category": "worker_integrity",
                "source": "gpu_3d",
                "message": "worker warning before error",
                "severity": "warning",
            },
            {
                "category": "worker_integrity",
                "source": "gpu_3d",
                "message": "worker error",
                "severity": "error",
            },
        ]

    def no_events(window: object) -> list[dict]:
        callbacks_seen.append("sensor")
        return []

    def utilization_events(window: object) -> list[dict]:
        callbacks_seen.append(f"util:{len(getattr(window, 'gpu_workers_final', []))}")
        return [{"category": "gpu_utilization", "source": "gpu", "message": "GPU utilization low", "severity": "warning"}]

    def backend_events(window: object) -> list[dict]:
        callbacks_seen.append(str(getattr(window, "gpu_3d_backend_preference", "")))
        return []

    def vram_events(window: object) -> list[dict]:
        callbacks_seen.append(f"vram_results:{len(getattr(window, 'worker_results', []))}")
        return []

    result = evaluate_completed_stage(
        stage_window_cls=SimpleNamespace,
        stage=stage,
        display_name="GPU Stage",
        stage_started_iso="2026-06-11T10:00:00-04:00",
        stage_ended_iso="2026-06-11T10:10:00-04:00",
        stage_start=100.0,
        stage_end=700.0,
        stage_elapsed=600.0,
        stage_processes=stage_processes,
        serialize_gpu_worker=serialize_worker,
        operator_stop_requested=False,
        abort_on_worker_error=True,
        abort_on_fail_threshold=True,
        stage_verdict="pass",
        stage_aborted=False,
        stage_abort_reason="",
        stage_error_events=[],
        stage_failure_reasons=[],
        gpu_target_mode="all",
        gpu_targets=["0000:01:00.0"],
        gpu_workers_initial=[{"target_id": "0000:01:00.0"}],
        gpu_3d_backend_preference="vulkan_compute",
        gpu_3d_backend_resolved="python_vulkan_compute",
        vram_backend_preference="vulkan_memory",
        vram_backend_resolved="python_vulkan_compute",
        worker_result_events_func=worker_events,
        sensor_events_func=no_events,
        utilization_events_func=utilization_events,
        backend_effectiveness_events_func=backend_events,
        vram_attainment_events_func=vram_events,
    )
    assert_equal(result.stage_verdict, "aborted", "stage evaluation aborts on worker error")
    assert_true(result.stage_aborted, "stage evaluation aborted flag")
    assert_equal(result.stage_abort_reason, "worker warning before error", "stage evaluation worker abort reason compatibility")
    assert_equal(result.stage_worker_results, [{"status": "error"}], "stage evaluation worker results")
    assert_equal(result.gpu_workers_final, [{"target_id": "0000:01:00.0", "backend": "python_vulkan_compute"}], "stage evaluation final workers")
    assert_true("util:1" in callbacks_seen and "vulkan_compute" in callbacks_seen and "vram_results:1" in callbacks_seen, "stage evaluation GPU callbacks")

    stopped_seen: list[str] = []
    stopped_result = evaluate_completed_stage(
        stage_window_cls=SimpleNamespace,
        stage=stage,
        display_name="GPU Stage",
        stage_started_iso="2026-06-11T10:00:00-04:00",
        stage_ended_iso="2026-06-11T10:10:00-04:00",
        stage_start=100.0,
        stage_end=700.0,
        stage_elapsed=600.0,
        stage_processes=stage_processes,
        serialize_gpu_worker=serialize_worker,
        operator_stop_requested=True,
        abort_on_worker_error=True,
        abort_on_fail_threshold=True,
        stage_verdict="aborted",
        stage_aborted=True,
        stage_abort_reason="operator stop requested",
        stage_error_events=[],
        stage_failure_reasons=[],
        gpu_target_mode="all",
        gpu_targets=["0000:01:00.0"],
        gpu_workers_initial=[{"target_id": "0000:01:00.0"}],
        gpu_3d_backend_preference="vulkan_compute",
        gpu_3d_backend_resolved="python_vulkan_compute",
        vram_backend_preference="vulkan_memory",
        vram_backend_resolved="python_vulkan_compute",
        worker_result_events_func=lambda processes, name: ([{"status": "partial"}], [{"severity": "error", "message": "ignored"}]),
        sensor_events_func=lambda window: [],
        utilization_events_func=lambda window: stopped_seen.append("util") or [],
        backend_effectiveness_events_func=lambda window: stopped_seen.append("backend") or [],
        vram_attainment_events_func=lambda window: stopped_seen.append("vram") or [],
    )
    assert_equal(stopped_result.stage_verdict, "aborted", "operator stop verdict preserved")
    assert_equal(stopped_seen, [], "operator stop skips GPU validation callbacks")


def test_stage_run_context_helpers() -> None:
    stage_plan = {
        "backend_usage": {
            "cpu": "cpu_native_helper",
            "gpu_3d": "python_opencl_compute",
            "vram": "python_vulkan_compute",
        },
        "cpu_mode_requested": "auto",
        "cpu_mode_resolved": "avx2",
        "cpu_kernel_flavor": "avx2",
        "cpu_tuning_policy": "max_power",
        "gpu_backend_preferences": {
            "gpu_3d": "opencl_compute",
            "vram": "vulkan_memory",
        },
        "gpu_target_mode": "all",
        "gpu_3d_mode": "steady",
        "gpu_3d_intensity": "extreme",
        "gpu_3d_compute_variant": "hash",
        "gpu_targets": ["0000:01:00.0", "0000:02:00.0"],
        "gpu_effective_targets": ["0000:02:00.0"],
        "gpu_excluded_targets": {"gpu_3d": ["0000:01:00.0"]},
        "gpu_workers": [{"target_id": "0000:02:00.0"}],
    }
    context = stage_run_context_from_plan(stage_plan)
    assert_equal(context.cpu_backend, "cpu_native_helper", "stage context CPU backend")
    assert_equal(context.gpu_targets, ["0000:02:00.0"], "stage context effective GPU targets")
    assert_equal(context.gpu_workers_initial, [{"target_id": "0000:02:00.0"}], "stage context initial GPU workers")
    assert_equal(
        cpu_stage_start_suffix(
            cpu_backend=context.cpu_backend,
            cpu_mode_requested=context.cpu_mode_requested,
            cpu_mode_resolved=context.cpu_mode_resolved,
            cpu_kernel_flavor=context.cpu_kernel_flavor,
            cpu_tuned_avg_power_w=125.5,
        ),
        " | cpu=cpu_native_helper (auto -> avx2) | kernel=avx2 | tuned=125.5W",
        "stage context CPU suffix",
    )
    stage = SimpleNamespace(
        modules=SimpleNamespace(
            gpu_3d=SimpleNamespace(enabled=True),
            vram=SimpleNamespace(enabled=True),
        )
    )
    assert_equal(
        gpu_stage_start_suffix(stage, context),
        " | gpu=3d=opencl_compute->python_opencl_compute (steady/extreme)/hash,vram=vulkan_memory->python_vulkan_compute | gpu_targets=all | gpu_effective=0000:02:00.0 | gpu_skipped=0000:01:00.0",
        "stage context GPU suffix",
    )
    assert_equal(
        internal_gpu_backend_set("python_opencl_compute", "vkmark", "python_vulkan_compute"),
        {"python_opencl_compute", "python_vulkan_compute"},
        "stage context internal backend set",
    )
    cpu_execution = {
        "backend": "cpu_native_helper",
        "requested_mode": "auto",
        "resolved_mode": "avx2",
        "kernel_flavor": "avx2",
        "tuning_policy": "max_power",
        "tuned_avg_power_w": 142.25,
        "candidate_results": [
            {"kernel_flavor": "sse", "avg_cpu_power_w": None},
            {"kernel_flavor": "avx2", "avg_cpu_power_w": 142.25},
        ],
    }
    tuned_context = apply_cpu_tuning_execution(stage_plan, cpu_execution)
    assert_equal(tuned_context.cpu_kernel_flavor, "avx2", "CPU tuning context selected kernel")
    assert_equal(stage_plan["cpu_tuned_avg_power_w"], 142.25, "CPU tuning updates stage plan")
    assert_equal(
        cpu_tune_summary_suffix(tuned_context.cpu_tune_results),
        " | sse=n/a, avx2=142.25W",
        "CPU tune summary suffix",
    )


def test_stage_lifecycle_helpers() -> None:
    intel_plan = {
        "gpu_target_details": [{"vendor": "Intel", "driver": "xe"}],
        "gpu_workers": [],
    }
    assert_true(stage_targets_intel_gpu(intel_plan, gpu_target_by_id=lambda target_id: None), "Intel target detail starts sidecar")
    worker_plan = {
        "gpu_target_details": [],
        "gpu_workers": [{"slot": "0000:03:00.0", "target_id": "0000:03:00.0"}],
    }
    assert_true(
        stage_targets_intel_gpu(worker_plan, gpu_target_by_id=lambda target_id: {"vendor": "Intel"}),
        "Intel worker target starts sidecar",
    )
    assert_true(
        not stage_targets_intel_gpu(worker_plan, gpu_target_by_id=lambda target_id: {"vendor": "NVIDIA"}),
        "non-Intel worker target skips sidecar",
    )

    marker_calls: list[dict] = []
    sidecar_calls: list[dict] = []

    def write_marker(**kwargs: object) -> None:
        marker_calls.append(dict(kwargs))

    def start_sidecar(**kwargs: object) -> dict:
        sidecar_calls.append(dict(kwargs))
        return {"process": "fake", "stage_id": kwargs.get("stage_id")}

    state = start_stage_lifecycle(
        profile_name="GPU Troubleshooting",
        stage_id="segment_1",
        stage_name="GPU Stage",
        run_dir=Path("/tmp/lvs-stage"),
        stage_plan=intel_plan,
        gpu_backends={"python_vulkan_compute", "python_opencl"},
        gpu_targets=["0000:03:00.0"],
        gpu_target_by_id=lambda target_id: None,
        write_gpu_safety_marker=write_marker,
        start_intel_gpu_top_sidecar=start_sidecar,
    )
    assert_equal(marker_calls[0]["gpu_backends"], ["python_opencl", "python_vulkan_compute"], "stage lifecycle sorted safety backends")
    assert_equal(sidecar_calls[0]["stage_id"], "segment_1", "stage lifecycle sidecar start")
    assert_equal(state.internal_gpu_backends, {"python_vulkan_compute", "python_opencl"}, "stage lifecycle state backends")

    stopped: list[object] = []
    cleared: list[bool] = []
    summary = stop_stage_lifecycle(
        state,
        stop_intel_gpu_top_sidecar=lambda sidecar: stopped.append(sidecar) or {"rows": 5},
        clear_gpu_safety_marker=lambda: cleared.append(True),
    )
    assert_equal(summary, {"rows": 5}, "stage lifecycle sidecar summary")
    assert_equal(stopped[0], state.intel_gpu_top_sidecar, "stage lifecycle stopped sidecar")
    assert_equal(cleared, [True], "stage lifecycle clears safety marker")


def test_stage_live_loop_helpers() -> None:
    stage = SimpleNamespace(
        id="segment_1",
        name="3D Adaptive",
        duration_seconds=25.0,
        normalization=SimpleNamespace(trim_start_seconds=0, trim_end_seconds=0),
    )
    current_time = [0.0]
    telemetry_calls = []
    retune_calls = []
    progress_lines = []

    def sleep(seconds: float) -> None:
        current_time[0] += seconds

    result = run_stage_live_loop(
        stage_window_cls=StageWindow,
        stage=stage,
        display_name="GPU Stage",
        stage_started_iso="2026-06-11T00:00:00",
        stage_start=0.0,
        stage_processes=["worker-a"],
        telemetry_collect_once=lambda: telemetry_calls.append(current_time[0]),
        telemetry_interval_seconds=10.0,
        stage_error_events=[],
        stage_failure_reasons=[],
        stage_verdict="pass",
        stage_aborted=False,
        stage_abort_reason="",
        abort_on_worker_error=True,
        abort_on_fail_threshold=True,
        gpu_retune_events=[],
        progress_interval_seconds=30.0,
        poll_stage_process_failures=lambda processes, name: [],
        stage_sensor_events=lambda window: [],
        maybe_retune_gpu_processes=lambda processes, elapsed, duration: retune_calls.append((elapsed, duration)) or ["worker-b"],
        stage_target_gpu_progress_summary=lambda processes, elapsed: f" | workers={','.join(processes)}",
        effective_gpu_retune_cooldown_seconds=lambda duration: 12.0,
        now_local_iso=lambda: "2026-06-11T00:00:10",
        monotonic=lambda: current_time[0],
        sleep=sleep,
        format_duration_hms=lambda seconds: f"{int(seconds)}s",
        print_progress=progress_lines.append,
    )
    assert_equal(telemetry_calls, [0.0, 10.0, 20.0], "live loop telemetry cadence")
    assert_equal(retune_calls, [(20.0, 25.0)], "live loop retune timing")
    assert_equal(result.stage_processes, ["worker-b"], "live loop returns retuned processes")
    assert_equal(result.stage_verdict, "pass", "live loop preserves passing verdict")
    assert_true(progress_lines and "workers=worker-a" in progress_lines[0], "live loop emits progress through callback")

    current_time[0] = 0.0
    try:
        run_stage_live_loop(
            stage_window_cls=StageWindow,
            stage=stage,
            display_name="GPU Stage",
            stage_started_iso="2026-06-11T00:00:00",
            stage_start=0.0,
            stage_processes=[],
            telemetry_collect_once=lambda: None,
            telemetry_interval_seconds=5.0,
            stage_error_events=[],
            stage_failure_reasons=[],
            stage_verdict="pass",
            stage_aborted=False,
            stage_abort_reason="",
            abort_on_worker_error=True,
            abort_on_fail_threshold=True,
            gpu_retune_events=[],
            progress_interval_seconds=30.0,
            poll_stage_process_failures=lambda processes, name: [],
            stage_sensor_events=lambda window: [],
            maybe_retune_gpu_processes=lambda processes, elapsed, duration: processes,
            stage_target_gpu_progress_summary=lambda processes, elapsed: "",
            effective_gpu_retune_cooldown_seconds=lambda duration: 12.0,
            now_local_iso=lambda: "2026-06-11T00:00:01",
            monotonic=lambda: current_time[0],
            sleep=sleep,
            format_duration_hms=lambda seconds: f"{int(seconds)}s",
            print_progress=lambda line: None,
            cancel_check=lambda: True,
        )
        raise AssertionError("live loop cancellation should raise KeyboardInterrupt")
    except KeyboardInterrupt:
        pass

    sensor_events = []
    failure_reasons = []
    current_time[0] = 0.0
    error_result = run_stage_live_loop(
        stage_window_cls=StageWindow,
        stage=stage,
        display_name="GPU Stage",
        stage_started_iso="2026-06-11T00:00:00",
        stage_start=0.0,
        stage_processes=[],
        telemetry_collect_once=lambda: None,
        telemetry_interval_seconds=5.0,
        stage_error_events=sensor_events,
        stage_failure_reasons=failure_reasons,
        stage_verdict="pass",
        stage_aborted=False,
        stage_abort_reason="",
        abort_on_worker_error=True,
        abort_on_fail_threshold=True,
        gpu_retune_events=[],
        progress_interval_seconds=30.0,
        poll_stage_process_failures=lambda processes, name: [],
        stage_sensor_events=lambda window: [
            {
                "timestamp": "2026-06-11T00:00:01",
                "category": "sensor_threshold",
                "severity": "error",
                "message": "synthetic sensor error",
            }
        ],
        maybe_retune_gpu_processes=lambda processes, elapsed, duration: processes,
        stage_target_gpu_progress_summary=lambda processes, elapsed: "",
        effective_gpu_retune_cooldown_seconds=lambda duration: 12.0,
        now_local_iso=lambda: "2026-06-11T00:00:01",
        monotonic=lambda: current_time[0],
        sleep=sleep,
        format_duration_hms=lambda seconds: f"{int(seconds)}s",
        print_progress=lambda line: None,
    )
    assert_equal(error_result.stage_verdict, "aborted", "live loop aborts on configured sensor error")
    assert_true(error_result.stage_aborted, "live loop marks sensor abort")
    assert_equal(failure_reasons, ["synthetic sensor error"], "live loop records sensor failure reason")
    assert_equal(sensor_events[0]["severity"], "error", "live loop appends sensor event")


def test_stage_postprocess_helpers() -> None:
    stage_window = SimpleNamespace(
        verdict="pass",
        system_faults=[],
        failure_reasons=[],
    )
    stage_plan = {"verdict": "pass"}
    stage_windows = []
    executed_plan = []
    failure_reasons = []
    captures = []
    fault_event = {
        "timestamp": "2026-06-11T00:01:00",
        "category": "kernel_fault",
        "severity": "error",
        "message": "synthetic kernel fault",
    }
    result = apply_completed_stage_bookkeeping(
        stage_window=stage_window,
        stage_plan=stage_plan,
        stage_windows=stage_windows,
        executed_plan=executed_plan,
        stage_failure_reasons=failure_reasons,
        run_aborted=False,
        stage_aborted=False,
        stage_abort_reason="",
        operator_stop_requested=False,
        abort_run_on_stage_abort=False,
        abort_on_system_fault=False,
        stage_id="segment_1",
        stage_name="Fault Stage",
        stage_started_iso="2026-06-11T00:00:00",
        stage_ended_iso="2026-06-11T00:01:00",
        collect_stage_faults=lambda window: [fault_event],
        capture_stage_end=lambda **kwargs: captures.append(dict(kwargs)),
    )
    assert_equal(stage_windows, [stage_window], "postprocess appends stage window")
    assert_equal(executed_plan, [stage_plan], "postprocess appends executed plan")
    assert_equal(stage_window.verdict, "fail", "postprocess fault escalates verdict")
    assert_equal(executed_plan[-1]["verdict"], "fail", "postprocess mirrors verdict to plan")
    assert_equal(executed_plan[-1]["system_faults"], [fault_event], "postprocess mirrors system faults")
    assert_equal(failure_reasons, ["synthetic kernel fault"], "postprocess records fault reason")
    assert_true(not result.should_break_run, "postprocess does not break on fail verdict")
    assert_equal(captures[0]["verdict"], "fail", "postprocess captures final stage verdict")

    aborted_window = SimpleNamespace(
        verdict="aborted",
        system_faults=[],
        failure_reasons=[],
    )
    abort_captures = []
    abort_result = apply_completed_stage_bookkeeping(
        stage_window=aborted_window,
        stage_plan={},
        stage_windows=[],
        executed_plan=[],
        stage_failure_reasons=[],
        run_aborted=False,
        stage_aborted=True,
        stage_abort_reason="worker exited early",
        operator_stop_requested=False,
        abort_run_on_stage_abort=True,
        abort_on_system_fault=True,
        stage_id="segment_2",
        stage_name="Abort Stage",
        stage_started_iso="2026-06-11T00:00:00",
        stage_ended_iso="2026-06-11T00:01:00",
        collect_stage_faults=lambda window: [],
        capture_stage_end=lambda **kwargs: abort_captures.append(dict(kwargs)),
    )
    assert_true(abort_result.run_aborted, "postprocess sets run aborted on configured aborted stage")
    assert_true(abort_result.should_break_run, "postprocess breaks on configured aborted stage")
    assert_equal(abort_captures[0]["verdict"], "aborted", "postprocess captures aborted final stage verdict")


def test_stage_execution_runtime_helpers() -> None:
    stage = SimpleNamespace(
        id="segment_1",
        name="3D Adaptive",
        duration_seconds=0.0,
        normalization=SimpleNamespace(trim_start_seconds=0, trim_end_seconds=0),
    )
    stage_plan = {"gpu_target_details": [{"vendor": "Intel", "driver": "xe"}], "gpu_workers": []}
    calls = []

    result = execute_stage_runtime(
        profile_name="GPU Troubleshooting",
        stage_window_cls=StageWindow,
        stage=stage,
        display_name="GPU Stage",
        run_dir=Path("/tmp/lvs-stage-exec"),
        stage_plan=stage_plan,
        stage_started_iso="2026-06-12T00:00:00",
        stage_start=0.0,
        cpu_kernel_flavor="",
        cpu_backend="",
        cpu_mode_requested="",
        cpu_mode_resolved="",
        cpu_tuning_policy="",
        cpu_tuned_avg_power_w=None,
        gpu_3d_backend_preference="vulkan_compute",
        gpu_3d_backend_resolved="python_vulkan_compute",
        vram_backend_preference="",
        vram_backend_resolved="",
        gpu_target_mode="all",
        gpu_targets=["0000:03:00.0"],
        gpu_workers_initial=[],
        gpu_lifecycle_backends={"python_vulkan_compute"},
        gpu_retune_events=[],
        stage_error_events=[],
        stage_failure_reasons=[],
        stage_verdict="pass",
        stage_aborted=False,
        stage_abort_reason="",
        run_aborted=False,
        abort_on_worker_error=True,
        abort_on_fail_threshold=True,
        telemetry_interval_seconds=1.0,
        progress_interval_seconds=30.0,
        strict_threshold_recommendation_warnings=False,
        gpu_target_by_id=lambda target_id: {"vendor": "Intel"},
        write_gpu_safety_marker=lambda **kwargs: calls.append(("marker", kwargs["stage_name"])),
        start_intel_gpu_top_sidecar=lambda **kwargs: calls.append(("sidecar-start", kwargs["stage_id"])) or {"fake": True},
        stop_intel_gpu_top_sidecar=lambda sidecar: calls.append(("sidecar-stop", bool(sidecar))) or {"rows": 1},
        clear_gpu_safety_marker=lambda: calls.append(("marker-clear", True)),
        launch_stage_processes=lambda stage_arg, kernel, run_dir: calls.append(("launch", stage_arg.id, kernel)) or [],
        stop_stage_processes=lambda processes: calls.append(("stop", len(processes))),
        telemetry_collect_once=lambda: calls.append(("telemetry", True)),
        poll_stage_process_failures=lambda processes, name: [],
        stage_sensor_events=lambda window: [],
        maybe_retune_gpu_processes=lambda processes, elapsed, duration: processes,
        stage_target_gpu_progress_summary=lambda processes, elapsed: "",
        effective_gpu_retune_cooldown_seconds=lambda duration: 20.0,
        serialize_gpu_worker=lambda spec: {},
        worker_result_events_func=lambda processes, name: ([], []),
        utilization_events_func=lambda window: [],
        backend_effectiveness_events_func=lambda window: [],
        vram_attainment_events_func=lambda window: [],
        now_local_iso=lambda: "2026-06-12T00:00:01",
        monotonic=lambda: 1.0,
        sleep=lambda seconds: None,
        format_duration_hms=lambda seconds: f"{int(seconds)}s",
        print_progress=lambda line: calls.append(("progress", line)),
        operator_stop_source="smoke",
        on_operator_stop=lambda event: calls.append(("operator-stop", event)),
    )
    assert_equal(result.stage_verdict, "pass", "stage execution preserves pass verdict")
    assert_equal(result.stage_completion.stage_window.verdict, "pass", "stage execution builds completed window")
    assert_equal(stage_plan["intel_gpu_top_sidecar"], {"rows": 1}, "stage execution stores sidecar summary")
    assert_true(("marker", "GPU Stage") in calls, "stage execution writes lifecycle marker")
    assert_true(("sidecar-start", "segment_1") in calls, "stage execution starts sidecar")
    assert_true(("stop", 0) in calls, "stage execution stops stage processes")
    assert_true(("marker-clear", True) in calls, "stage execution clears lifecycle marker")

    interrupt_stage = SimpleNamespace(
        id="segment_2",
        name="CPU Load",
        duration_seconds=30.0,
        normalization=SimpleNamespace(trim_start_seconds=0, trim_end_seconds=0),
    )
    interrupt_events = []
    interrupt_reasons = []
    operator_events = []

    def raise_keyboard_interrupt() -> None:
        raise KeyboardInterrupt

    interrupt_result = execute_stage_runtime(
        profile_name="Quick Test",
        stage_window_cls=StageWindow,
        stage=interrupt_stage,
        display_name="Interrupt Stage",
        run_dir=Path("/tmp/lvs-stage-exec"),
        stage_plan={},
        stage_started_iso="2026-06-12T00:00:00",
        stage_start=0.0,
        cpu_kernel_flavor="",
        cpu_backend="",
        cpu_mode_requested="",
        cpu_mode_resolved="",
        cpu_tuning_policy="",
        cpu_tuned_avg_power_w=None,
        gpu_3d_backend_preference="",
        gpu_3d_backend_resolved="",
        vram_backend_preference="",
        vram_backend_resolved="",
        gpu_target_mode="",
        gpu_targets=[],
        gpu_workers_initial=[],
        gpu_lifecycle_backends=set(),
        gpu_retune_events=[],
        stage_error_events=interrupt_events,
        stage_failure_reasons=interrupt_reasons,
        stage_verdict="pass",
        stage_aborted=False,
        stage_abort_reason="",
        run_aborted=False,
        abort_on_worker_error=True,
        abort_on_fail_threshold=True,
        telemetry_interval_seconds=1.0,
        progress_interval_seconds=30.0,
        strict_threshold_recommendation_warnings=False,
        gpu_target_by_id=lambda target_id: None,
        write_gpu_safety_marker=lambda **kwargs: None,
        start_intel_gpu_top_sidecar=lambda **kwargs: None,
        stop_intel_gpu_top_sidecar=lambda sidecar: None,
        clear_gpu_safety_marker=lambda: None,
        launch_stage_processes=lambda stage_arg, kernel, run_dir: [],
        stop_stage_processes=lambda processes: None,
        telemetry_collect_once=raise_keyboard_interrupt,
        poll_stage_process_failures=lambda processes, name: [],
        stage_sensor_events=lambda window: [],
        maybe_retune_gpu_processes=lambda processes, elapsed, duration: processes,
        stage_target_gpu_progress_summary=lambda processes, elapsed: "",
        effective_gpu_retune_cooldown_seconds=lambda duration: 20.0,
        serialize_gpu_worker=lambda spec: {},
        worker_result_events_func=lambda processes, name: ([], []),
        utilization_events_func=lambda window: [],
        backend_effectiveness_events_func=lambda window: [],
        vram_attainment_events_func=lambda window: [],
        now_local_iso=lambda: "2026-06-12T00:00:02",
        monotonic=lambda: 2.0,
        sleep=lambda seconds: None,
        format_duration_hms=lambda seconds: f"{int(seconds)}s",
        print_progress=lambda line: None,
        operator_stop_source="tui",
        on_operator_stop=operator_events.append,
    )
    assert_true(interrupt_result.run_aborted, "stage execution marks run aborted on operator stop")
    assert_true(interrupt_result.operator_stop_requested, "stage execution records operator stop")
    assert_equal(interrupt_result.stage_verdict, "aborted", "stage execution aborts interrupted stage")
    assert_equal(operator_events[0]["source"], "tui", "stage execution uses injected operator source")
    assert_equal(interrupt_events[0]["category"], "operator_stop", "stage execution records operator stop event")

    cancel_events = []
    cancel_reasons = []
    cancel_operator_events = []
    cancel_result = execute_stage_runtime(
        profile_name="Quick Test",
        stage_window_cls=StageWindow,
        stage=interrupt_stage,
        display_name="Cancel Stage",
        run_dir=Path("/tmp/lvs-stage-exec"),
        stage_plan={},
        stage_started_iso="2026-06-12T00:00:00",
        stage_start=0.0,
        cpu_kernel_flavor="",
        cpu_backend="",
        cpu_mode_requested="",
        cpu_mode_resolved="",
        cpu_tuning_policy="",
        cpu_tuned_avg_power_w=None,
        gpu_3d_backend_preference="",
        gpu_3d_backend_resolved="",
        vram_backend_preference="",
        vram_backend_resolved="",
        gpu_target_mode="",
        gpu_targets=[],
        gpu_workers_initial=[],
        gpu_lifecycle_backends=set(),
        gpu_retune_events=[],
        stage_error_events=cancel_events,
        stage_failure_reasons=cancel_reasons,
        stage_verdict="pass",
        stage_aborted=False,
        stage_abort_reason="",
        run_aborted=False,
        abort_on_worker_error=True,
        abort_on_fail_threshold=True,
        telemetry_interval_seconds=1.0,
        progress_interval_seconds=30.0,
        strict_threshold_recommendation_warnings=False,
        gpu_target_by_id=lambda target_id: None,
        write_gpu_safety_marker=lambda **kwargs: None,
        start_intel_gpu_top_sidecar=lambda **kwargs: None,
        stop_intel_gpu_top_sidecar=lambda sidecar: None,
        clear_gpu_safety_marker=lambda: None,
        launch_stage_processes=lambda stage_arg, kernel, run_dir: [],
        stop_stage_processes=lambda processes: None,
        telemetry_collect_once=lambda: None,
        poll_stage_process_failures=lambda processes, name: [],
        stage_sensor_events=lambda window: [],
        maybe_retune_gpu_processes=lambda processes, elapsed, duration: processes,
        stage_target_gpu_progress_summary=lambda processes, elapsed: "",
        effective_gpu_retune_cooldown_seconds=lambda duration: 20.0,
        serialize_gpu_worker=lambda spec: {},
        worker_result_events_func=lambda processes, name: ([], []),
        utilization_events_func=lambda window: [],
        backend_effectiveness_events_func=lambda window: [],
        vram_attainment_events_func=lambda window: [],
        now_local_iso=lambda: "2026-06-12T00:00:02",
        monotonic=lambda: 2.0,
        sleep=lambda seconds: None,
        format_duration_hms=lambda seconds: f"{int(seconds)}s",
        print_progress=lambda line: None,
        operator_stop_source="tui",
        on_operator_stop=cancel_operator_events.append,
        cancel_check=lambda: True,
    )
    assert_true(cancel_result.run_aborted, "TUI cancel callback marks run aborted")
    assert_true(cancel_result.operator_stop_requested, "TUI cancel callback records operator stop")
    assert_equal(cancel_result.stage_verdict, "aborted", "TUI cancel callback aborts stage like manual stop")
    assert_equal(cancel_operator_events[0]["source"], "tui", "TUI cancel callback records TUI operator source")
    assert_equal(cancel_events[0]["category"], "operator_stop", "TUI cancel callback uses operator stop event")


def test_stage_adapter_helpers() -> None:
    stage = SimpleNamespace(
        id="segment_1",
        name="CPU Load",
        duration_seconds=0.0,
        normalization=SimpleNamespace(trim_start_seconds=0, trim_end_seconds=0),
        modules=SimpleNamespace(
            cpu=SimpleNamespace(enabled=True),
            gpu_3d=SimpleNamespace(enabled=False),
            vram=SimpleNamespace(enabled=False),
        ),
    )
    stage_plan = {
        "backend_usage": {"cpu": "native_cpu"},
        "cpu_mode_requested": "auto",
        "cpu_mode_resolved": "sse",
        "cpu_kernel_flavor": "sse",
        "cpu_tuning_policy": "max_power",
    }
    stage_windows = []
    executed_plan = []
    output = []
    captures = []
    times = [0.0, 0.5, 1.0, 1.5]

    def monotonic() -> float:
        return times.pop(0) if times else 2.0

    result = run_stage_adapter(
        profile_name="Quick Test",
        stage_window_cls=StageWindow,
        stage=stage,
        display_name="CPU Stage",
        run_dir=Path("/tmp/lvs-stage-adapter"),
        stage_plan=stage_plan,
        stage_windows=stage_windows,
        executed_plan=executed_plan,
        run_aborted=False,
        abort_on_worker_error=True,
        abort_on_system_fault=False,
        abort_run_on_stage_abort=False,
        abort_on_fail_threshold=True,
        telemetry_interval_seconds=1.0,
        progress_interval_seconds=30.0,
        cpu_tuning_policy_for_stage=lambda cpu_module: "max_power",
        resolve_cpu_execution=lambda cpu_module: {
            "backend": "native_cpu",
            "requested_mode": "auto",
            "resolved_mode": "avx2",
            "kernel_flavor": "avx2",
            "tuning_policy": "max_power",
            "tuned_avg_power_w": 88.5,
            "candidate_results": [{"kernel_flavor": "avx2", "avg_cpu_power_w": 88.5}],
        },
        strict_threshold_recommendation_warnings=lambda: False,
        gpu_target_by_id=lambda target_id: None,
        write_gpu_safety_marker=lambda **kwargs: output.append(("marker", kwargs)),
        start_intel_gpu_top_sidecar=lambda **kwargs: None,
        stop_intel_gpu_top_sidecar=lambda sidecar: None,
        clear_gpu_safety_marker=lambda: output.append(("marker-clear", True)),
        launch_stage_processes=lambda stage_arg, kernel, run_dir: output.append(("launch", kernel)) or [],
        stop_stage_processes=lambda processes: output.append(("stop", len(processes))),
        telemetry_collect_once=lambda: output.append(("telemetry", True)),
        poll_stage_process_failures=lambda processes, name: [],
        stage_sensor_events=lambda window: [],
        maybe_retune_gpu_processes=lambda processes, elapsed, duration, retune_events: processes,
        stage_target_gpu_progress_summary=lambda processes, elapsed: "",
        effective_gpu_retune_cooldown_seconds=lambda duration: 20.0,
        serialize_gpu_worker=lambda spec: {},
        worker_result_events_func=lambda processes, name: ([], []),
        utilization_events_func=lambda window: [],
        backend_effectiveness_events_func=lambda window: [],
        vram_attainment_events_func=lambda window: [],
        collect_stage_faults=lambda started, ended, window: [],
        capture_stage_start=lambda **kwargs: captures.append(("start", kwargs)),
        capture_stage_end=lambda **kwargs: captures.append(("end", kwargs)),
        now_local_iso=lambda: "2026-06-12T00:00:00",
        monotonic=monotonic,
        sleep=lambda seconds: None,
        future_local_iso=lambda seconds: "2026-06-12T00:00:00",
        format_duration_hms=lambda seconds: f"{int(seconds)}s",
        print_cpu_tune_start=lambda timestamp, policy: output.append(("cpu-start", policy)),
        print_cpu_tune_end=lambda timestamp, elapsed, selected, suffix: output.append(("cpu-end", selected, suffix)),
        print_stage_start=lambda timestamp, stage_type, planned, expected_end, cpu_suffix, gpu_suffix: output.append(("stage-start", cpu_suffix, gpu_suffix)),
        print_stage_abort=lambda timestamp, reason: output.append(("stage-abort", reason)),
        print_stage_end=lambda timestamp, elapsed, verdict, issue_count: output.append(("stage-end", verdict, issue_count)),
        print_progress=lambda line: output.append(("progress", line)),
        operator_stop_source="smoke",
        on_operator_stop=lambda event: output.append(("operator-stop", event)),
    )
    assert_true(not result.run_aborted, "stage adapter preserves non-aborted run")
    assert_true(not result.should_break_run, "stage adapter does not break passing stage")
    assert_equal(stage_plan["cpu_kernel_flavor"], "avx2", "stage adapter applies CPU tuning to plan")
    assert_true(any(item[0] == "cpu-start" for item in output), "stage adapter emits CPU tune start")
    assert_true(any(item[0] == "cpu-end" and item[1] == "avx2" and "88.5W" in item[2] for item in output), "stage adapter emits CPU tune end")
    assert_true(any(item[0] == "stage-start" and "native_cpu" in item[1] for item in output), "stage adapter emits stage start suffix")
    assert_true(any(item[0] == "stage-end" and item[1] == "pass" for item in output), "stage adapter emits stage end")
    assert_equal(len(stage_windows), 1, "stage adapter appends stage window")
    assert_equal(len(executed_plan), 1, "stage adapter appends executed plan")
    assert_equal(captures[0][0], "start", "stage adapter captures stage start")
    assert_equal(captures[-1][0], "end", "stage adapter captures stage end")


def test_run_stage_loop_helpers() -> None:
    stages = [
        SimpleNamespace(id="segment_1", name="First Stage", enabled=True),
        SimpleNamespace(id="segment_2", name="Disabled Stage", enabled=False),
        SimpleNamespace(id="segment_3", name="Third Stage", enabled=True),
    ]
    effective_profile = SimpleNamespace(stages=stages)
    preflight_plan = [
        {"stage": "first"},
        {"stage": "disabled"},
        {"stage": "third"},
    ]
    stage_windows = []
    executed_plan = []
    calls = []
    original_adapter = run_stage_loop_module.run_stage_adapter

    def fake_run_stage_adapter(**kwargs):
        calls.append(kwargs)
        kwargs["stage_windows"].append(SimpleNamespace(display_name=kwargs["display_name"]))
        kwargs["executed_plan"].append(kwargs["stage_plan"])
        assert_true(kwargs["stage_plan"] is not preflight_plan[len(calls) - 1], "run stage loop copies preflight plan")
        assert_true(kwargs["strict_threshold_recommendation_warnings"]() is True, "run stage loop binds strict warning stage")
        return SimpleNamespace(run_aborted=len(calls) == 2, should_break_run=len(calls) == 2)

    run_stage_loop_module.run_stage_adapter = fake_run_stage_adapter
    try:
        result = run_stage_loop_module.run_effective_stages(
            profile_name="Loop Smoke",
            effective_profile=effective_profile,
            labels=["Label One"],
            preflight_plan=preflight_plan,
            stage_window_cls=StageWindow,
            run_dir=Path("/tmp/lvs-run-stage-loop"),
            stage_windows=stage_windows,
            executed_plan=executed_plan,
            run_aborted=False,
            abort_on_worker_error=True,
            abort_on_system_fault=True,
            abort_run_on_stage_abort=True,
            abort_on_fail_threshold=True,
            telemetry_interval_seconds=1.0,
            progress_interval_seconds=30.0,
            cpu_tuning_policy_for_stage=lambda cpu_module: "auto",
            resolve_cpu_execution=lambda cpu_module: {},
            strict_threshold_recommendation_warnings=lambda stage: stage.id.startswith("segment_"),
            gpu_target_by_id=lambda target_id: None,
            write_gpu_safety_marker=lambda **kwargs: None,
            start_intel_gpu_top_sidecar=lambda **kwargs: None,
            stop_intel_gpu_top_sidecar=lambda sidecar: None,
            clear_gpu_safety_marker=lambda: None,
            launch_stage_processes=lambda stage, kernel, run_dir: [],
            stop_stage_processes=lambda processes: None,
            telemetry_collect_once=lambda: None,
            poll_stage_process_failures=lambda processes, name: [],
            stage_sensor_events=lambda window: [],
            maybe_retune_gpu_processes=lambda processes, display_name, retune_events, elapsed, duration: processes,
            stage_target_gpu_progress_summary=lambda processes, elapsed: "",
            effective_gpu_retune_cooldown_seconds=lambda duration: 20.0,
            serialize_gpu_worker=lambda spec: {},
            worker_result_events_func=lambda processes, name: ([], []),
            utilization_events_func=lambda window: [],
            backend_effectiveness_events_func=lambda window: [],
            vram_attainment_events_func=lambda window: [],
            collect_stage_faults=lambda started, ended, window: [],
            capture_stage_start=lambda **kwargs: None,
            capture_stage_end=lambda **kwargs: None,
            now_local_iso=lambda: "2026-06-12T00:00:00",
            monotonic=lambda: 0.0,
            sleep=lambda seconds: None,
            future_local_iso=lambda seconds: "2026-06-12T00:00:00",
            format_duration_hms=lambda seconds: f"{int(seconds)}s",
            print_cpu_tune_start=lambda display_name, timestamp, policy: None,
            print_cpu_tune_end=lambda display_name, timestamp, tune_elapsed, selected, suffix: None,
            print_stage_start=lambda display_name, timestamp, stage_type, planned, expected_end, cpu_suffix, gpu_suffix: None,
            print_stage_abort=lambda display_name, timestamp, reason: None,
            print_stage_end=lambda display_name, timestamp, stage_elapsed, verdict, issue_count: None,
            print_progress=lambda line: None,
            operator_stop_source="smoke",
            on_operator_stop=lambda display_name, event: None,
        )
    finally:
        run_stage_loop_module.run_stage_adapter = original_adapter

    assert_true(result.run_aborted, "run stage loop propagates run abort")
    assert_equal([call["display_name"] for call in calls], ["Label One", "Third Stage"], "run stage loop labels enabled stages")
    assert_equal([call["stage"].id for call in calls], ["segment_1", "segment_3"], "run stage loop skips disabled stage")
    assert_equal(len(stage_windows), 2, "run stage loop passes stage windows")
    assert_equal(executed_plan[1]["stage"], "third", "run stage loop passes copied stage plan")


def test_stage_launch_plan_helpers() -> None:
    worker = GpuWorkerSpec(
        workload="gpu_3d",
        backend="python_egl_gles2",
        gpu_index=0,
        card="card1",
        slot="0000:01:00.0",
        target_id="0000:01:00.0",
        command=["planned-gpu"],
    )

    class FakeRunner:
        def _cpu_command(self, cpu: object, cpu_kernel_flavor: str = "", result_file: str = "") -> list[str]:
            return ["cpu", cpu_kernel_flavor, result_file]

        def _memory_command(self, memory: object, result_file: str = "") -> list[str]:
            return ["memory", result_file]

        def _gpu_worker_specs(self, stage: object) -> list[GpuWorkerSpec]:
            return [worker]

        def _materialize_gpu_worker(self, worker: GpuWorkerSpec, result_file: str = "") -> GpuWorkerSpec:
            return GpuWorkerSpec(
                workload=worker.workload,
                backend=worker.backend,
                gpu_index=worker.gpu_index,
                card=worker.card,
                slot=worker.slot,
                target_id=worker.target_id,
                command=["gpu", result_file or ""],
            )

    stage = SimpleNamespace(
        id="segment_1",
        enabled=True,
        modules=SimpleNamespace(
            cpu=SimpleNamespace(enabled=True),
            memory=SimpleNamespace(enabled=True),
            gpu_3d=SimpleNamespace(enabled=True),
            vram=SimpleNamespace(enabled=False),
        ),
    )
    with TemporaryDirectory() as tmpdir:
        worker_results_dir = Path(tmpdir) / "worker_results"
        planned = build_stage_launch_commands(FakeRunner(), stage, "avx2", worker_results_dir)
    assert_equal([entry.kind for entry in planned], ["cpu", "memory", "gpu_3d"], "stage launch plan kinds")
    assert_true(planned[0].command[-1].endswith("segment_1_cpu.json"), "CPU launch result path")
    assert_true(planned[1].command[-1].endswith("segment_1_memory.json"), "memory launch result path")
    assert_true(planned[2].command[-1].endswith("segment_1_gpu_3d_1.json"), "GPU launch result path")
    assert_true(planned[2].gpu_spec is not None, "GPU launch plan carries materialized worker")
    stage.enabled = False
    assert_equal(build_stage_launch_commands(FakeRunner(), stage), [], "disabled stage launch plan")


def test_stage_process_control_helpers() -> None:
    created: list[dict] = []

    class FakeProcess:
        def __init__(self, cmd: list[str]) -> None:
            self.cmd = cmd
            self.terminated = False
            self.killed = False
            self.wait_calls = 0
            self.fail_wait = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float = 0) -> None:
            self.wait_calls += 1
            if self.fail_wait:
                raise TimeoutError("timeout")

        def kill(self) -> None:
            self.killed = True

    def fake_popen(cmd: list[str], stdout: object = None, stderr: object = None, env: object = None) -> FakeProcess:
        created.append({"cmd": cmd, "stdout": stdout, "stderr": stderr, "env": env})
        return FakeProcess(cmd)

    with TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir) / "logs"
        logs_dir.mkdir()
        planned = [
            SimpleNamespace(
                kind="cpu",
                command=["cpu"],
                gpu_spec=None,
                result_path="/tmp/cpu.json",
            ),
            SimpleNamespace(
                kind="gpu_3d",
                command=["gpu"],
                gpu_spec=GpuWorkerSpec("gpu_3d", "python_egl_gles2", 0, "", "", "", ["gpu"]),
                result_path="/tmp/gpu.json",
            ),
        ]
        launched = launch_stage_processes_from_plan(
            planned,
            stage_id="segment_1",
            worker_logs_dir=logs_dir,
            command_env={"LVS": "1"},
            popen_factory=fake_popen,
        )
        assert_equal(len(launched), 2, "stage process launch count")
        assert_true(launched[0].stdout_path.endswith("segment_1_cpu_1.stdout.log"), "CPU stdout path")
        assert_true(launched[1].stderr_path.endswith("segment_1_gpu_3d_2.stderr.log"), "GPU stderr path")
        assert_equal(created[0]["env"], {"LVS": "1"}, "process launch env")

    proc_ok = FakeProcess(["ok"])
    proc_timeout = FakeProcess(["timeout"])
    proc_timeout.fail_wait = True
    stop_processes([proc_ok, proc_timeout], timeout_seconds=0.01)
    assert_true(proc_ok.terminated and proc_timeout.terminated, "process terminate called")
    assert_true(proc_timeout.killed, "process kill after wait failure")
    stop_stage_processes(launched, timeout_seconds=0.01)
    assert_true(all(entry.process.terminated for entry in launched), "stage process stop delegates to process stop")


def test_stage_worker_evidence_helpers() -> None:
    class FakeProcess:
        def __init__(self, return_code: int | None) -> None:
            self.return_code = return_code

        def poll(self) -> int | None:
            return self.return_code

    def backend_profile(name: str) -> dict:
        return {"load_class": "compatibility"} if name == "vkmark" else {"load_class": "stress"}

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        stdout_path = tmp_path / "worker.stdout.log"
        stderr_path = tmp_path / "worker.stderr.log"
        stdout_path.write_text("stdout line\n", encoding="utf-8")
        stderr_path.write_text("stderr line\n", encoding="utf-8")
        gpu_spec = GpuWorkerSpec(
            "gpu_3d",
            "vkmark",
            0,
            "card1",
            "0000:01:00.0",
            "0000:01:00.0",
            ["vkmark"],
        )
        exited_entry = StageProcess(
            kind="gpu_3d",
            command=["vkmark"],
            process=FakeProcess(0),
            gpu_spec=gpu_spec,
            result_path=str(tmp_path / "missing.json"),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        fallback = read_worker_result(exited_entry)
        assert_equal(fallback["status"], "ok", "fallback worker result status")
        process_events = poll_stage_process_failures([exited_entry], "Stage A", backend_profile)
        assert_equal(process_events[0]["severity"], "warning", "compatibility worker exit warning")
        assert_true("compatibility backend worker exited" in process_events[0]["message"], "compatibility exit message")

        result_path = tmp_path / "worker.json"
        result_path.write_text(
            json.dumps(
                {
                    "kind": "gpu_3d",
                    "backend": "python_egl_gles2",
                    "status": "error",
                    "error_count": 1,
                    "error_message": "draw mismatch",
                }
            ),
            encoding="utf-8",
        )
        error_entry = StageProcess(
            kind="gpu_3d",
            command=["egl"],
            process=FakeProcess(0),
            gpu_spec=GpuWorkerSpec("gpu_3d", "python_egl_gles2", 0, "card1", "0000:01:00.0", "0000:01:00.0", ["egl"]),
            result_path=str(result_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        results, events = worker_result_events([error_entry], "Stage B", backend_profile)
        assert_equal(results[0]["result_path"], str(result_path), "worker result path preserved")
        assert_true(any(event["category"] == "verification_error" for event in events), "worker result event generated")


def test_gpu_telemetry_warning_helpers() -> None:
    capabilities = {
        "gpu_telemetry_by_gpu": {
            "gpus": [
                {
                    "gpu_index": 0,
                    "slot": "0000:01:00.0",
                    "vendor": "NVIDIA",
                    "driver": "nvidia",
                    "metrics": {
                        "temperature": {"available": False},
                        "power": {"available": False},
                        "busy": {"available": False},
                        "vram_used": {"available": False},
                    },
                },
                {
                    "gpu_index": 1,
                    "slot": "0000:02:00.0",
                    "vendor": "AMD",
                    "driver": "amdgpu",
                    "metrics": {
                        "temperature": {"available": True},
                        "power": {"available": False},
                        "busy": {"available": True},
                        "vram_used": {"available": True},
                    },
                },
            ]
        }
    }
    assert_equal(gpu_telemetry_coverage_warnings(capabilities, {"cpu"}), [], "no GPU telemetry warning for CPU-only")
    warnings = gpu_telemetry_coverage_warnings(capabilities, {"gpu_3d"})
    assert_equal(len(warnings), 2, "GPU telemetry warning count")
    assert_true("nvidia-smi does not expose this card" in warnings[0], "NVIDIA dropout warning")
    assert_true("missing power metrics" in warnings[1], "partial telemetry warning")


def test_nvidia_opencl_env_uses_only_nvml_identity() -> None:
    runner = WorkloadRunner()
    runner._opencl_device_for_target = lambda target: {  # type: ignore[method-assign]
        "opencl_index": 2,
        "pci_slot": "0000:f1:00.0",
    }
    dropped_from_nvml = {
        "vendor": "NVIDIA",
        "slot": "0000:f1:00.0",
        "target_id": "0000:f1:00.0",
    }
    env = runner._opencl_target_env(dropped_from_nvml, {})
    assert_true("CUDA_VISIBLE_DEVICES" not in env, "no CUDA_VISIBLE_DEVICES without NVML identity")

    visible_by_nvml = {
        "vendor": "NVIDIA",
        "slot": "0000:21:00.0",
        "target_id": "0000:21:00.0",
        "nvidia_index": "1",
    }
    env = runner._opencl_target_env(visible_by_nvml, {})
    assert_equal(env.get("CUDA_DEVICE_ORDER"), "PCI_BUS_ID", "NVIDIA OpenCL device order")
    assert_equal(env.get("CUDA_VISIBLE_DEVICES"), "1", "CUDA_VISIBLE_DEVICES uses nvidia index")


def test_runtime_services_factory() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        settings = GlobalSettings(
            profiles_dir=str(root / "profiles"),
            results_dir=str(root / "results"),
            suite_department="",
            case_options=[" Case A ", "case a", "Case B"],
            psu_rating_options=[],
            cpu_cooler_options=[" Air ", "air"],
            profile_menu_groups=[],
        )

        def normalize_text_list(values, defaults):
            source = values if isinstance(values, list) and values else defaults
            normalized = []
            seen = set()
            for value in source:
                text_value = " ".join(str(value or "").strip().split())
                key = text_value.lower()
                if text_value and key not in seen:
                    normalized.append(text_value)
                    seen.add(key)
            return normalized or list(defaults)

        normalize_runtime_settings(settings, normalize_text_list=normalize_text_list)
        assert_equal(settings.case_options, ["Case A", "Case B"], "runtime factory normalizes case options")
        assert_equal(settings.cpu_cooler_options, ["Air"], "runtime factory normalizes cooler options")
        assert_true(bool(settings.psu_rating_options), "runtime factory restores PSU defaults")
        assert_equal(settings.suite_department, "Production", "runtime factory department fallback")
        assert_true(any(group["key"] == "custom" for group in settings.profile_menu_groups), "runtime factory menu groups")

        class FakeValidator:
            def validate(self, _profile, _labels):
                return {"errors": [], "warnings": []}

        workload_runner = object()
        summary_exporter = object()
        orchestrator_calls = []

        def orchestrator_factory(runtime_settings):
            orchestrator_calls.append(runtime_settings)
            return SimpleNamespace(
                validator=FakeValidator(),
                workload_runner=workload_runner,
                summary_exporter=object(),
            )

        ensure_calls = []
        runtime = build_runtime_services(
            settings=settings,
            orchestrator_factory=orchestrator_factory,
            ensure_ready=lambda: ensure_calls.append(True) or True,
            run_heatsoak_if_requested=lambda *_args, **_kwargs: True,
            environment_mode_label=lambda: "Production",
            summary_exporter=summary_exporter,
            ensure_example_profile=True,
        )
        assert_equal(orchestrator_calls, [settings], "runtime factory orchestrator settings")
        assert_true(runtime.workload_runner is workload_runner, "runtime factory workload runner identity")
        assert_true(runtime.summary_exporter is summary_exporter, "runtime factory summary exporter identity")
        assert_equal(runtime.profile_loader.profiles_dir, Path(settings.profiles_dir), "runtime factory profile path")
        assert_equal(runtime.result_reports.results_dir, Path(settings.results_dir), "runtime factory results path")
        assert_true(runtime.profile_reports.profile_loader is runtime.profile_loader, "runtime factory profile graph identity")
        assert_true(
            runtime.profile_edit_controller.profile_editor is runtime.profile_editor,
            "runtime factory profile edit controller identity",
        )
        assert_true(runtime.run_preflight_manager.profile_reports is runtime.profile_reports, "runtime factory preflight graph identity")
        assert_true(runtime.run_executor.profile_loader is runtime.profile_loader, "runtime factory executor loader identity")
        assert_true(runtime.run_executor.orchestrator is runtime.orchestrator, "runtime factory executor orchestrator identity")
        assert_true(runtime.run_launcher.executor is runtime.run_executor, "runtime factory launcher identity")
        assert_true(runtime.run_setup_manager.profile_loader is runtime.profile_loader, "runtime factory setup loader identity")
        assert_true(
            isinstance(runtime.local_migration_manager, LocalMigrationManager),
            "runtime factory local migration manager",
        )
        assert_true(any(Path(settings.profiles_dir).glob("*.json")), "runtime factory ensures example profile")
        assert_equal(ensure_calls, [], "runtime factory does not eagerly invoke frontend readiness")

        holder = SimpleNamespace()
        runtime.bind_to(holder)
        assert_true(holder.run_launcher is runtime.run_launcher, "runtime factory bind launcher")
        assert_true(holder.result_validation is runtime.result_validation, "runtime factory bind validation")
        assert_true(holder.profile_save is runtime.profile_save, "runtime factory bind profile save")
        assert_true(
            holder.profile_edit_controller is runtime.profile_edit_controller,
            "runtime factory bind profile edit controller",
        )


def test_service_new_profile_round_trip() -> None:
    with TemporaryDirectory(dir="/tmp") as tmp:
        tmp_path = Path(tmp)
        service = SuiteAppService()
        service.settings.profiles_dir = str(tmp_path)
        service.profile_loader.profiles_dir = tmp_path
        edit = service.create_new_profile_edit("Created Smoke Profile")
        assert_equal(edit.profile_path.parent, tmp_path, "new profile temp parent")
        assert_equal(edit.profile.profile_name, "Created Smoke Profile", "new profile name")
        assert_equal(edit.labels, ["CPU"], "new profile starter label")
        assert_true(edit.profile.stages[0].modules.cpu.enabled, "new profile starter CPU")
        items = service.profile_edit_items(edit)
        assert_true(any(item.kind == "save" for item in items), "new profile edit save row")
        assert_true(any(item.kind == "stage" and item.index == 0 for item in items), "new profile edit stage row")
        service.set_profile_name(edit.profile, "Renamed Smoke Profile")
        stage, label = service.create_profile_stage_from_template(edit.profile, "gpu_vram", duration_seconds=300)
        edit.labels = service.add_profile_stage(edit.profile, edit.labels, stage, label)
        service.save_profile_edit(edit)
        assert_true(edit.profile_path.exists(), "new profile saved JSON")
        assert_true((tmp_path / "Created Smoke Profile_info.txt").exists(), "new profile saved labels")
        reloaded = service.create_profile_edit(edit.profile_path)
        assert_equal(reloaded.profile.profile_name, "Renamed Smoke Profile", "new profile reloaded name")
        assert_equal(reloaded.labels, ["CPU", "3D + VRAM"], "new profile reloaded labels")
        assert_true(reloaded.profile.stages[1].modules.gpu_3d.enabled, "new profile reloaded GPU")
        assert_true(reloaded.profile.stages[1].modules.vram.enabled, "new profile reloaded VRAM")


def test_service_frontend_contract_methods() -> None:
    expected_methods = [
        "list_profiles",
        "profile_summary_text",
        "dry_run_profile",
        "prepare_setup_run_flow",
        "create_profile_edit",
        "create_new_profile_edit",
        "save_profile_edit",
        "create_run_setup",
        "setup_action_specs",
        "run_profile_capture_output",
        "run_complete_outcome",
        "list_results",
        "result_summary_text",
        "validate_result_text",
        "pre_import_sanity_text",
        "qa_result_review_payload",
        "qa_batch_review_payload",
        "result_artifact_inventory_payload",
        "settings_summary_text",
        "settings_action_for_key",
        "dependency_check_payload",
        "public_support_export_text",
        "create_private_migration_bundle",
        "preview_migration_restore",
        "apply_migration_restore",
        "profile_audit_payload",
    ]
    missing = [name for name in expected_methods if not callable(getattr(SuiteAppService, name, None))]
    assert_equal(missing, [], "service frontend contract methods")


def test_service_orchestrator_factory_injection() -> None:
    calls = []

    class FakeValidator:
        def validate(self, profile, labels):
            return {"errors": [], "warnings": []}

    class FakeOrchestrator:
        def __init__(self, settings) -> None:
            self.settings = settings
            self.validator = FakeValidator()

        def dry_run(self, profile_path, profile, labels):
            self.last_dry_run = {
                "profile_path": profile_path,
                "profile": profile,
                "labels": list(labels),
            }
            return {
                "profile_name": profile.profile_name,
                "runnable": True,
                "enabled_stage_count": 1,
                "runnable_stage_count": 1,
                "validation": {"errors": [], "warnings": []},
                "telemetry_capabilities": {},
                "backends": {},
                "backend_details": {},
                "plan": [],
            }

    def factory(settings):
        calls.append(settings)
        return FakeOrchestrator(settings)

    with TemporaryDirectory(dir="/tmp") as tmp:
        tmp_path = Path(tmp)
        settings_path = tmp_path / "settings" / "global_settings.json"
        service = SuiteAppService(settings_path=settings_path, orchestrator_factory=factory)
        service.settings.profiles_dir = str(tmp_path / "profiles")
        service.profile_loader.profiles_dir = Path(service.settings.profiles_dir)
        profile_path = service.profile_loader.ensure_example_profile()
        report = service.dry_run_profile(profile_path)
        assert_true(calls, "service orchestrator factory called")
        assert_equal(report["profile_name"], "PL Validation", "service fake orchestrator dry run")
        assert_equal(service.orchestrator.last_dry_run["labels"], service.profile_loader.load_segment_labels(profile_path, service.profile_loader.load_profile(profile_path)), "service preflight manager labels")
        setup = service.create_run_setup(profile_path)
        setup.labels = ["Edited Label"]
        review_controller = service.create_run_setup_review_controller(
            setup,
            RunSetupPromptCallbacks(
                load_history=lambda metadata: metadata,
                stage_overrides=lambda profile: None,
                edit_labels=lambda labels: list(labels),
                select_case_sku=lambda current: current,
                select_psu_rating=lambda current: current,
                select_cpu_cooler=lambda current: current,
                enter_power_limit=lambda current: current,
                enter_description=lambda current: "Service Review Smoke",
                enter_heatsoak_minutes=lambda current: current,
                enter_psu_wattage=lambda current: current,
                enter_fan_type=lambda fan_type, fan_details: (fan_type, fan_details),
                enter_fan_details=lambda current: current,
                enter_raw=lambda label: "",
                normalize_labels=lambda profile, labels: list(labels),
                department=lambda: "Service",
                update_pending_heatsoak=lambda minutes: None,
            ),
        )
        service_description_action = review_controller.action_for_choice("2")
        assert_true(service_description_action is not None, "service review controller action lookup")
        review_controller.handle_action(service_description_action)
        assert_equal(setup.metadata.description, "Service Review Smoke", "service review controller action")
        assert_equal(setup.metadata.dept, "Service", "service review controller department")
        service_result_dir = tmp_path / "service_result"
        service_result_dir.mkdir()
        JsonStore.write(service_result_dir / "parsed_results_custom.json", {"Metadata": {}})
        service_comparison_dir = tmp_path / "service_comparison"
        service_comparison_dir.mkdir()
        JsonStore.write(
            service_comparison_dir / "parsed_results_custom.json",
            {"ReportSummary": {"Result": "warning", "WarningCategoryCounts": {"service": 1}}},
        )
        service_comparison = service.compare_result_payload(service_result_dir, service_comparison_dir)
        assert_equal(service_comparison["kind"], "result_comparison", "service result comparison payload")
        assert_equal(
            service_comparison["deltas"]["warning_categories"]["service"]["delta"],
            1.0,
            "service result comparison warning delta",
        )
        assert_true(
            "Warning service: 0 -> 1 (delta 1.0)" in service.result_comparison_text(service_comparison),
            "service result comparison text",
        )
        service_comparison_report = service.write_result_comparison_report(
            service_result_dir,
            service_comparison_dir,
            "service comparison\n",
            service_comparison,
        )
        assert_equal(service_comparison_report, service_comparison_dir, "service result comparison report target")
        assert_true(
            bool(list(service_comparison_dir.glob("result_comparison_vs_*.json"))),
            "service result comparison JSON saved",
        )
        service_prepared = service.prepare_pre_import_sanity(service_result_dir)
        service_selected_sanity = service.complete_pre_import_sanity(service_prepared, service_comparison)
        assert_equal(service_selected_sanity["kind"], "pre_import_sanity", "service selected pre-import sanity payload")
        assert_equal(
            service_selected_sanity["comparison"]["kind"],
            "result_comparison",
            "service selected pre-import sanity comparison",
        )
        assert_true(
            "Result Folder Comparison" in service.selected_pre_import_sanity_text(service_selected_sanity),
            "service selected pre-import sanity text",
        )
        service_pre_import = service.pre_import_sanity_batch_payload([service_result_dir])
        assert_equal(service_pre_import["kind"], "pre_import_sanity_batch", "service pre-import sanity batch payload")
        assert_equal(service_pre_import["summary_refresh"]["refreshed"], 1, "service pre-import sanity summary refresh")
        assert_true(
            "Batch Pre-Import Sanity Check" in service.batch_pre_import_sanity_text(service_pre_import),
            "service batch pre-import sanity text",
        )
        service.result_validation.results_dir = tmp_path
        service.pre_import_sanity.results_dir = tmp_path
        service.result_reports.results_dir = tmp_path
        service.result_artifacts.results_dir = tmp_path
        service_artifact_inventory = service.result_artifact_inventory_payload()
        assert_equal(service_artifact_inventory["kind"], "results_inventory", "service result artifact inventory payload")
        assert_true(
            service_result_dir in service.result_artifact_candidates(),
            "service result artifact candidates",
        )
        assert_equal(
            service.result_artifact_inventory_item(service_result_dir)["kind"],
            "run_result",
            "service result artifact inventory item",
        )
        assert_equal(
            service.run_result_artifact_detail_payload(service_result_dir)["details"]["stage_count"],
            0,
            "service result artifact run detail payload",
        )
        service_preflight_dir = tmp_path / "service_preflight"
        service_preflight_dir.mkdir()
        JsonStore.write(
            service_preflight_dir / "preflight_report.json",
            {
                "result": "Blocked",
                "preflight": {
                    "runnable": False,
                    "plan": [],
                    "validation": {"errors": ["blocked"], "warnings": []},
                },
            },
        )
        assert_equal(
            service.preflight_artifact_detail_payload(service_preflight_dir)["details"]["result"],
            "Blocked",
            "service result artifact preflight detail payload",
        )
        service_diagnostics_dir = tmp_path / "service_diagnostics"
        service_diagnostics_dir.mkdir()
        JsonStore.write(
            service_diagnostics_dir / "diagnostics.json",
            {"runnable": True, "plan": [], "validation": {"errors": [], "warnings": []}},
        )
        assert_true(
            service.diagnostics_artifact_detail_payload(service_diagnostics_dir)["details"]["runnable"],
            "service result artifact diagnostics detail payload",
        )
        assert_equal(
            service.result_artifact_detail_payload(service_diagnostics_dir)["kind"],
            "diagnostics",
            "service result artifact detail dispatcher",
        )
        service_detail_report = service.result_artifact_detail_report_payload(service_diagnostics_dir)
        assert_equal(
            service_detail_report["kind"],
            "result_artifact_details",
            "service result artifact detail report kind",
        )
        assert_equal(
            service_detail_report["inventory_item"]["kind"],
            "diagnostics",
            "service result artifact detail report inventory",
        )
        assert_true(bool(service_detail_report.get("ended")), "service result artifact detail report completed")
        assert_true(
            "Plan Summary" in service.result_artifact_detail_text(service_diagnostics_dir),
            "service result artifact canonical detail text",
        )
        service_inventory_report = service.write_result_artifact_inventory_report(
            "service inventory\n",
            service_artifact_inventory,
            "2026-05-02_00-00-00",
        )
        assert_true(
            (service_inventory_report / "results_inventory.json").exists(),
            "service result artifact inventory report JSON saved",
        )
        service_detail_report_path = service.write_result_artifact_detail_report(
            service_diagnostics_dir,
            "service detail\n",
            service_detail_report,
        )
        assert_equal(
            service_detail_report_path,
            service_diagnostics_dir,
            "service result artifact detail report target",
        )
        assert_equal(
            JsonStore.read(service_diagnostics_dir / "artifact_details.json", {}).get("kind"),
            "result_artifact_details",
            "service result artifact detail report JSON saved",
        )
        selected_validation_text = service.validate_result_text(service_result_dir, save=True)
        assert_true("GPU highlights:" in selected_validation_text, "service canonical selected validation text")
        selected_validation_payload = JsonStore.read(service_result_dir / "result_validation.json", {})
        assert_true("export_contract" in selected_validation_payload.get("checks", {}), "service canonical validation payload")
        batch_validation_output = service.validate_all_results_text(save=True)
        assert_true("Batch Result Validation" in batch_validation_output, "service canonical batch validation text")
        assert_true("Excluded root folders: Archived, Uploaded" in batch_validation_output, "service batch exclusions")
        service_batch_validation_reports = sorted(tmp_path.glob("*_Result_Validation_Batch/result_validation_batch.json"))
        assert_true(bool(service_batch_validation_reports), "service batch validation JSON saved")
        selected_sanity_output = service.pre_import_sanity_text(service_result_dir, save=True)
        assert_true("Pre-Import Sanity Check" in selected_sanity_output, "service canonical selected sanity text")
        assert_true((service_result_dir / "pre_import_sanity.json").exists(), "service selected sanity JSON saved")
        batch_sanity_output = service.pre_import_sanity_all_text(save=True)
        assert_true("Batch Pre-Import Sanity Check" in batch_sanity_output, "service canonical batch sanity text")
        assert_true("Excluded root folders: Archived, Uploaded" in batch_sanity_output, "service batch sanity exclusions")
        service_batch_sanity_reports = sorted(tmp_path.glob("*_Pre_Import_Sanity_Batch/pre_import_sanity_batch.json"))
        assert_true(bool(service_batch_sanity_reports), "service batch pre-import sanity JSON saved")
        service_wattage = service.handle_wall_wattage_input(service_result_dir, setup.metadata, "777")
        assert_equal(service_wattage.normalized, "777W", "service wall wattage handler normalized")
        assert_true(service_wattage.saved, "service wall wattage handler saved")
        service_not_ready_upload = service.attempt_upload_result_folder(service_result_dir, {"ready": False})
        assert_true(not service_not_ready_upload.ready, "service upload attempt not ready")
        service.post_run_manager.upload_result_folder = lambda path: {"result": "success", "uploaded_count": 1, "file_count": 1}  # type: ignore[method-assign]
        service_ready_upload = service.attempt_upload_result_folder(service_result_dir, {"ready": True})
        assert_true(service_ready_upload.ready, "service upload attempt ready")
        assert_equal(service_ready_upload.payload["result"], "success", "service upload attempt payload")
        setup_decision = service.inspect_setup_run_flow(setup)
        assert_true(not setup_decision.blocked, "service setup run flow validation")
        preflight_decision = service.run_setup_preflight_decision(setup)
        assert_equal(service.orchestrator.last_dry_run["labels"], ["Edited Label"], "service setup preflight labels")
        assert_true(preflight_decision.runnable, "service setup preflight runnable")
        prepared_flow = service.prepare_setup_run_flow(setup)
        assert_true(not prepared_flow.preflight_action.blocked, "service prepared run flow runnable")
        assert_true(prepared_flow.launch_request.setup is setup, "service prepared run flow launch setup")
        assert_equal(prepared_flow.launch_request.profile_path, setup.profile_path, "service prepared run flow launch path")
        assert_equal(
            prepared_flow.launch_request.heatsoak_minutes,
            float(setup.heatsoak_minutes or 0.0),
            "service prepared run flow heatsoak",
        )


def main() -> int:
    tests = [
        test_modules_compile_recursively,
        test_modules_have_no_static_internal_import_cycles,
        test_modules_cold_import_manifest,
        test_textual_is_confined_to_optional_tui_boundary,
        test_output_contract_index_and_casing_policy,
        test_lvs_owned_versioned_contract_key_casing,
        test_legacy_result_fixture_contract_and_consumer_paths,
        test_duplicate_gpu_temperature_names,
        test_storage_secondary_temperature_parsed_detail,
        test_segment_formatting_helpers,
        test_tui_view_model_row_labels,
        test_tui_list_adapter,
        test_tui_input_state_helpers,
        test_tui_navigation_reset_spec,
        test_tui_picker_presentation_helpers,
        test_tui_profile_edit_presentation_helpers,
        test_tui_result_presentation_helpers,
        test_tui_profile_presentation_helpers,
        test_tui_settings_list_presentation_helpers,
        test_tui_post_run_prompt_specs,
        test_tui_run_setup_presentation_helpers,
        test_tui_run_setup_adapter_helpers,
        test_tui_profile_edit_adapter_helpers,
        test_tui_results_adapter_helpers,
        test_cli_result_qa_review_action,
        test_tui_settings_adapter_helpers,
        test_tui_run_execution_adapter_helpers,
        test_tui_app_actions_adapter_helpers,
        test_tui_event_adapter_helpers,
        test_tui_run_presentation_helpers,
        test_segment_parser_cpu_package_metrics,
        test_segment_parser_single_cpu_keeps_legacy_shape,
        test_cpu_system_info_dual_cpu_fixture_contract,
        test_report_highlights_and_xid_language,
        test_report_stage_summary_builder,
        test_report_summary_builder,
        test_report_export_result_contract_bundle,
        test_result_report_text_contract_from_payload,
        test_report_export_realistic_trimmed_fixture_contract,
        test_stage_diagnostics_stability_fixture_contract,
        test_overall_stability_interpretation_builder,
        test_manual_abort_export_classification,
        test_compatibility_export_helper_classification,
        test_run_verdict_precedence,
        test_run_finalization_helpers,
        test_cli_run_event_presenter_helpers,
        test_run_completion_helpers,
        test_final_run_artifact_writer_helpers,
        test_egl_gles_worker_script_builder,
        test_workload_runner_egl_probe_script_available,
        test_egl_runtime_discovery_helpers,
        test_opencl_compute_worker_script_builder,
        test_opencl_vram_worker_script_builder,
        test_opencl_probe_script_builder,
        test_opencl_targeting_helpers,
        test_opencl_runtime_discovery_helpers,
        test_external_gpu_supervisor_script_builder,
        test_compatibility_export_metric_helpers,
        test_compatibility_export_hardware_sections,
        test_compatibility_export_gpu_section,
        test_gpu_power_details_builder,
        test_gpu_worker_metric_test_builder,
        test_gpu_worker_validation_detail_builder,
        test_compatibility_export_run_context,
        test_compatibility_export_metadata_block,
        test_compatibility_export_identity_envelope,
        test_compatibility_export_finalizer,
        test_compatibility_export_document_builder,
        test_linux_fault_collector_classification,
        test_gpu_safety_marker_store,
        test_compatibility_export_fixture_shape,
        test_compatibility_export_skipped_stage_fixture,
        test_compatibility_export_same_model_gpu_ordering_fixture,
        test_run_summary_text_fixture,
        test_run_executor_defaults_and_capture,
        test_cli_run_heatsoak_reaches_prepared_launch,
        test_cli_heatsoak_cancel_plumbing_and_screen_refresh,
        test_compact_cli_preflight_summary,
        test_post_run_and_heatsoak_helpers,
        test_run_bootstrap_artifact_helpers,
        test_run_setup_metadata_specs,
        test_run_preflight_manager_readiness,
        test_settings_and_result_action_specs,
        test_result_overview_text_fixture,
        test_result_validation_facade_candidates_and_batch,
        test_result_comparison_facade_payload,
        test_pre_import_sanity_facade_batch,
        test_result_validation_pre_import_realistic_fixture_contract,
        test_result_validation_pre_import_text_realistic_fixture_contract,
        test_qa_result_review_facade_contract,
        test_qa_review_cli_wrapper,
        test_hardware_result_validation_matrix_payloads,
        test_hardware_matrix_state_lifecycle,
        test_hardware_matrix_state_discovery,
        test_hardware_matrix_state_refresh_action,
        test_public_support_export_missing_optional_files,
        test_public_support_export_redacts_private_values,
        test_public_support_export_generated_summary_shape,
        test_private_migration_bundle_manifest_checksums_and_exclusions,
        test_migration_cli_menu_contract,
        test_migration_restore_preview_apply_and_scaffolds,
        test_migration_restore_no_overwrite_and_conflict_staging,
        test_migration_restore_rejects_invalid_bundles,
        test_result_artifact_facade_inventory,
        test_result_artifact_presentation_helpers,
        test_profile_dry_run_summary_formatting,
        test_strict_threshold_policy_helpers,
        test_profile_validator_shared_policy,
        test_profile_editor_stage_mutations,
        test_profile_edit_controller_dispatch,
        test_profile_detail_presentation_helpers,
        test_profile_creation_controller,
        test_profile_save_controller,
        test_profile_loader_round_trip_and_sorting,
        test_google_drive_not_ready_manifest,
        test_fresh_user_settings_bootstrap,
        test_dependency_report_summary_with_injected_telemetry,
        test_telemetry_source_helpers,
        test_telemetry_source_capability_fixture_contract,
        test_telemetry_sensor_io_helpers,
        test_telemetry_device_helpers,
        test_telemetry_nvidia_helpers,
        test_telemetry_nvidia_event_reasons_absent_when_unsupported,
        test_telemetry_intel_helpers,
        test_telemetry_gpu_helpers,
        test_telemetry_sampling_helpers,
        test_telemetry_sample_csv_helpers,
        test_telemetry_memory_helpers,
        test_telemetry_cpu_helpers,
        test_gpu_identity_helpers,
        test_gpu_target_helpers,
        test_gpu_capability_profile_helpers,
        test_inventory_memory_helpers,
        test_storage_inventory_helpers,
        test_system_info_gpu_pcie_attribution,
        test_system_identity_helpers,
        test_cpu_power_limit_helpers,
        test_cpu_topology_helpers,
        test_run_progress_helpers,
        test_cli_live_run_presenter_helpers,
        test_gpu_progress_helpers,
        test_gpu_retune_helpers,
        test_gpu_retune_policy_helpers,
        test_advanced_debug_logger_helpers,
        test_intel_gpu_sidecar_helpers,
        test_intel_gpu_runtime_diagnostics_helpers,
        test_intel_gpu_sidecar_lifecycle_helpers,
        test_stability_event_helpers,
        test_sensor_event_helpers,
        test_gpu_stage_event_helpers,
        test_gpu_stage_target_helpers,
        test_worker_evidence_helpers,
        test_gpu_worker_state_helpers,
        test_gpu_worker_plan_helpers,
        test_gpu_worker_param_helpers,
        test_vram_policy_helpers,
        test_vram_orchestration_helpers,
        test_gpu_backend_resolution_helpers,
        test_stage_gpu_backend_diagnostics_helpers,
        test_gpu_backend_resolver_helpers,
        test_gpu_backend_support_helpers,
        test_gpu_backend_catalog_helpers,
        test_vulkan_targeting_helpers,
        test_gpu_worker_planner_helpers,
        test_gpu_worker_materializer_helpers,
        test_gpu_worker_retune_helpers,
        test_gpu_retune_process_helpers,
        test_cpu_execution_helpers_select_policy_candidates_and_best_result,
        test_cpu_execution_resolution_policy,
        test_cpu_execution_helpers_build_and_parse_helper_probes,
        test_cpu_execution_helpers_build_commands_and_benchmark_results,
        test_memory_execution_helpers_build_commands_and_targets,
        test_native_helper_status_helpers_resolve_build_states,
        test_native_helper_runtime_service,
        test_backend_readiness_helpers_build_payloads,
        test_vulkan_runtime_discovery_helpers,
        test_cpu_max_power_tuning_skips_invalid_candidates,
        test_stage_event_state_helpers,
        test_stage_completion_helpers,
        test_stage_evaluation_helpers,
        test_stage_run_context_helpers,
        test_stage_lifecycle_helpers,
        test_stage_live_loop_helpers,
        test_stage_postprocess_helpers,
        test_stage_execution_runtime_helpers,
        test_stage_adapter_helpers,
        test_run_stage_loop_helpers,
        test_stage_launch_plan_helpers,
        test_stage_process_control_helpers,
        test_stage_worker_evidence_helpers,
        test_gpu_telemetry_warning_helpers,
        test_nvidia_opencl_env_uses_only_nvml_identity,
        test_runtime_services_factory,
        test_service_new_profile_round_trip,
        test_service_frontend_contract_methods,
        test_service_orchestrator_factory_injection,
    ]
    for test in tests:
        captured_output = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured_output):
                test()
        except BaseException:
            output = captured_output.getvalue()
            if output:
                print(f"CAPTURED OUTPUT FROM {test.__name__}:")
                print(output, end="" if output.endswith("\n") else "\n")
            raise
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
