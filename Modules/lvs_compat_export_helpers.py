#!/usr/bin/env python3
"""Pure helpers for the legacy-compatible export shape."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .lvs_gpu_export_helpers import normalize_gpu_interface


_ADDITIVE_STRESS_NG_EVIDENCE_FIELDS = {
    "backend",
    "errors",
    "requested_stressor_count",
    "dispatched_stressor_count",
    "passed_stressor_count",
    "failed_stressor_count",
    "skipped_stressor_count",
    "metrics_untrustworthy_count",
    "stressor_metrics",
    "verification_enabled",
    "executed_command",
    "executable_requested",
    "executable_resolved_path",
    "executable_version",
    "process_pid",
    "process_started_iso",
    "process_ended_iso",
    "process_elapsed_seconds",
    "expected_termination",
    "result_write_error",
}

_ADDITIVE_NATIVE_AFFINITY_FIELDS = {
    "affinity_attempted_count",
    "affinity_applied_count",
    "affinity_failed_count",
    "affinity_target_cpu",
    "affinity_attempted",
    "affinity_applied",
    "affinity_required",
    "affinity_error_code",
    "observed_cpu",
}

_ADDITIVE_CPU_TARGETING_FIELDS = {
    "available_cpu_ids",
    "online_cpu_ids",
    "allowed_cpu_ids",
    "target_cpu_ids",
    "requested_thread_count",
    "actual_worker_count",
    "affinity_requested",
    "affinity_status",
    "affinity_unavailable_count",
    "affinity_evidence",
    "worker_progress",
    "verification_passes",
    "verification_error_count",
    "verification_method",
    "capability_scope",
    "common_safe_instruction_set",
    "per_cpu_capabilities",
    "capability_probe_failures",
    "capability_intersection_reason",
}

_ADDITIVE_PYTHON_MEMORY_FIELDS = {
    "assigned_target_bytes",
    "planned_target_bytes",
    "successfully_allocated_bytes",
    "successful_chunk_count",
    "attempted_chunk_count",
    "allocation_failure_count",
    "final_attempted_chunk_bytes",
    "memory_error_occurred",
    "allocation_shortfall_bytes",
    "allocation_ratio",
    "allocation_outcome",
    "allocation_valid",
    "allocation_verified",
    "verification_passes",
    "verification_failures",
    "verified_bytes_per_pass",
    "verification_chunks_completed",
    "current_pattern",
    "first_verification_error",
    "actual_allocated_bytes",
    "target_cap_reason",
    "runtime_memory_guard_triggered",
    "runtime_memory_guard_details",
    "allocation_growth_stopped",
}

_ADDITIVE_GPU_MEMORY_PLAN_FIELDS = {
    "hardware_device_verified",
    "device_match_score",
    "device_match_ambiguous",
    "target_device_name",
    "physical_gpu_id",
    "failure_reason",
    "gpu_memory_kind",
    "memory_classification_source",
    "memory_capacity_source",
    "dedicated_vram_capacity_bytes",
    "shared_addressable_capacity_bytes",
    "shared_addressable_capacity_status",
    "api_addressable_capacity_bytes",
    "api_addressable_capacity_source",
    "backend_addressable_capacity_bytes",
    "backend_addressable_capacity_source",
    "backend_addressable_capacity_status",
    "total_capacity_trust",
    "system_memory_pool_ceiling_bytes",
    "max_single_allocation_bytes",
    "max_single_allocation_source",
    "max_buffer_or_object_bytes",
    "max_buffer_or_object_source",
    "max_allocation_count",
    "max_allocation_count_source",
    "allocation_granularity_bytes",
    "planned_allocation_chunks",
    "planned_allocation_chunk_count",
    "reported_vram_total_bytes",
    "reported_vram_total_semantics",
    "ambiguous_integrated_vram_report_bytes",
    "current_gpu_memory_used_bytes",
    "current_gpu_memory_used_source",
    "current_gpu_memory_available_bytes",
    "current_gpu_memory_available_source",
    "firmware_preallocated_or_stolen_bytes",
    "firmware_preallocated_or_stolen_source",
    "requested_gpu_memory_target_bytes",
    "requested_gpu_memory_percent",
    "planned_gpu_memory_target_bytes",
    "system_memory_budget_participation",
    "system_memory_commitment_multiplier",
    "system_memory_fixed_commitment_bytes",
    "memory_budget_consumer_id",
    "memory_budgetability",
    "target_cap_reason",
    "allocation_backoff_attempts",
    "actual_allocated_bytes",
    "allocation_ratio",
    "allocation_outcome",
    "allocation_valid",
    "allocation_runtime_failed",
    "nominal_allocated_texture_bytes",
    "physical_commitment_known",
    "staging_allocation_bytes",
    "minimum_viable_allocation_bytes",
    "minimum_viable_allocation_source",
    "runtime_memory_guard_triggered",
    "runtime_memory_guard_details",
    "allocation_growth_stopped",
}


def preserve_legacy_worker_evidence_contract(value: Any) -> Any:
    """Remove additive worker/planning evidence from the legacy document only."""
    if isinstance(value, list):
        return [
            preserve_legacy_worker_evidence_contract(item)
            for item in value
            if not (
                isinstance(item, dict)
                and str(item.get("kind") or "").lower() == "memory"
                and str(item.get("backend") or "").lower() in {"python_fallback", "stress_ng"}
            )
        ]
    if not isinstance(value, dict):
        return value
    is_stress_ng_evidence = (
        str(value.get("kind") or "").lower() == "cpu"
        and (
            str(value.get("backend") or "").lower() == "stress_ng"
            or str(value.get("executable_requested") or "").endswith("stress-ng")
        )
    )
    has_native_affinity_evidence = any(
        key in value
        for key in (
            "affinity_attempted_count",
            "affinity_target_cpu",
            "affinity_error_code",
        )
    )
    blocked = set(_ADDITIVE_GPU_MEMORY_PLAN_FIELDS)
    if str(value.get("kind") or "").lower() == "cpu":
        blocked.update(_ADDITIVE_CPU_TARGETING_FIELDS)
    if str(value.get("kind") or "").lower() == "memory" and str(value.get("backend") or "").lower() == "python_fallback":
        blocked.update(_ADDITIVE_PYTHON_MEMORY_FIELDS)
    if has_native_affinity_evidence:
        blocked.update(_ADDITIVE_NATIVE_AFFINITY_FIELDS)
    if is_stress_ng_evidence:
        blocked.update(_ADDITIVE_STRESS_NG_EVIDENCE_FIELDS)
    return {
        key: preserve_legacy_worker_evidence_contract(item)
        for key, item in value.items()
        if key not in blocked
    }


def compatibility_elapsed_string(seconds: float) -> str:
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def window_has_operator_stop(window: Any) -> bool:
    return any(
        str(event.get("category") or "").strip().lower() == "operator_stop"
        for event in [
            *list(getattr(window, "error_events", []) or []),
            *list(getattr(window, "system_faults", []) or []),
        ]
        if isinstance(event, dict)
    )


def run_manually_aborted(windows: Iterable[Any]) -> bool:
    return any(window_has_operator_stop(window) for window in windows)


def compatibility_overall_result(windows: Iterable[Any], manual_abort: bool | None = None) -> str:
    window_list = list(windows)
    if manual_abort is None:
        manual_abort = run_manually_aborted(window_list)
    if manual_abort:
        return "manually_aborted"
    if any(str(getattr(window, "verdict", "")) == "aborted" for window in window_list):
        return "Aborted"
    if any(str(getattr(window, "verdict", "")) == "fail" for window in window_list):
        return "Failed"
    if any(str(getattr(window, "verdict", "")) == "warning" for window in window_list):
        return "Warning"
    return "Finished"


def compatibility_execution_detail(overall_result: str, skipped_stage_count: int) -> str:
    if str(overall_result) == "Finished" and int(skipped_stage_count or 0) > 0:
        return "FinishedWithSkips"
    return str(overall_result)


def compatibility_cpu_power_limit_value(cpu_power_limits: dict[str, Any], name: str) -> str:
    constraints = cpu_power_limits.get("Constraints") if isinstance(cpu_power_limits, dict) else []
    if not isinstance(constraints, list):
        return ""
    for constraint in constraints:
        if not isinstance(constraint, dict):
            continue
        if str(constraint.get("Name") or "").lower() != str(name or "").lower():
            continue
        value = constraint.get("PowerLimitW")
        if value is None:
            return ""
        try:
            watts = float(value)
        except Exception:
            return ""
        return f"{int(watts) if watts.is_integer() else round(watts, 2):g}W"
    return ""


def gpu_temp_export_name(gpu: dict[str, Any]) -> str:
    name = gpu.get("DisplayName") or gpu.get("Name", "")
    if not name and gpu.get("GpuIndex") is not None:
        name = f"GPU {gpu.get('GpuIndex')}"
    sensor_name = gpu.get("SensorName", "")
    if not sensor_name:
        return str(name or "")
    return f"{name} [{sensor_name}]"


def build_gpu_temp_test(segments: list[dict[str, Any]], bucket: str) -> list[dict[str, Any]]:
    results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        gpus = segment.get("Temperatures", {}).get("Gpu", {}).get(bucket, {}).get("Gpus", [])
        for gpu in gpus:
            if not isinstance(gpu, dict):
                continue
            device_name = gpu_temp_export_name(gpu)
            stats = gpu.get("Temperatures", {})
            if not device_name or not isinstance(stats, dict):
                continue
            results.setdefault(device_name, {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [{"device": device_name, "results": device_results} for device_name, device_results in results.items()]


def build_gpu_metric_test(segments: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        for metric in segment.get("GpuMetrics", []):
            if not isinstance(metric, dict):
                continue
            device_name = metric.get("DisplayName") or metric.get("Name")
            if not device_name and metric.get("GpuIndex") is not None:
                device_name = f"GPU {metric.get('GpuIndex')}"
            stats = metric.get(field, {})
            if not device_name or not isinstance(stats, dict):
                continue
            results.setdefault(str(device_name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [{"device": device_name, "results": device_results} for device_name, device_results in results.items()]


def build_memory_temperature_tests(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    memory_temp_results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        modules = segment.get("Temperatures", {}).get("Memory", {}).get("Modules", [])
        for module in modules:
            if not isinstance(module, dict):
                continue
            device_name = module.get("Name") or module.get("SensorName")
            stats = module.get("Temperatures", {})
            if not device_name or not isinstance(stats, dict):
                continue
            memory_temp_results.setdefault(str(device_name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [
        {"device": device_name, "results": results}
        for device_name, results in memory_temp_results.items()
    ]


def build_storage_temperature_tests(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drive_temp_results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        drives = segment.get("Temperatures", {}).get("Storage", {}).get("Drives", [])
        for drive in drives:
            if not isinstance(drive, dict):
                continue
            device_name = drive.get("DeviceName") or drive.get("Model") or drive.get("SensorName")
            stats = drive.get("Temperatures", {})
            if not device_name or not isinstance(stats, dict):
                continue
            drive_temp_results.setdefault(str(device_name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [
        {"device": device_name, "results": results}
        for device_name, results in drive_temp_results.items()
    ]


def has_core_clock_data(parser_output: dict[str, Any]) -> bool:
    for segment in parser_output.get("Segments", []):
        if isinstance(segment, dict) and segment.get("Clocks", {}).get("Cores"):
            return True
    return False


def has_core_type_data(parser_output: dict[str, Any], core_type: str) -> bool:
    expected = str(core_type or "").upper()
    for segment in parser_output.get("Segments", []):
        if not isinstance(segment, dict):
            continue
        for core in segment.get("Clocks", {}).get("Cores", []):
            if isinstance(core, dict) and str(core.get("CoreType", "") or "").upper() == expected:
                return True
    return False


def build_cpu_core_frequency_tests(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    core_results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        for core in segment.get("Clocks", {}).get("Cores", []):
            if not isinstance(core, dict):
                continue
            name = core.get("Name")
            stats = core.get("Stats", {})
            if not name or not isinstance(stats, dict):
                continue
            core_results.setdefault(str(name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [{name: results} for name, results in core_results.items()]


def gpu_worker_backend_name(payload: dict[str, Any], *, vulkan_gpu_3d_backend: str = "python_vulkan_transfer") -> str:
    backend = str(payload.get("backend") or "").strip()
    if backend:
        return backend
    mode = str(payload.get("mode") or payload.get("workload") or "").strip().lower()
    if payload.get("renderer"):
        return "python_egl_gles2"
    if payload.get("selected_vulkan_index") is not None:
        return vulkan_gpu_3d_backend if mode == "gpu_3d" else "python_vulkan_transfer"
    if payload.get("selected_opencl_index") is not None or payload.get("platform_name"):
        return "python_opencl_compute" if mode == "gpu_3d" else "python_opencl"
    return ""


def resolve_gpu_worker_device_name(payload: dict[str, Any], gpus: list[dict[str, Any]]) -> str:
    slot = str(payload.get("slot") or payload.get("target_id") or "").strip().lower()
    if slot:
        for gpu in gpus:
            interface = str(gpu.get("Interface") or "").strip().lower()
            if interface == slot:
                return str(gpu.get("DisplayName") or gpu.get("Name") or slot)
    gpu_index = payload.get("gpu_index")
    try:
        index = int(gpu_index)
    except Exception:
        index = None
    if index is not None and 0 <= index < len(gpus):
        return str(gpus[index].get("DisplayName") or gpus[index].get("Name") or f"GPU {index}")
    selected_name = str(payload.get("selected_device_name") or "").strip()
    if selected_name:
        return selected_name
    card = str(payload.get("card") or "").strip()
    if card:
        return card
    renderer = str(payload.get("renderer") or "").strip()
    if renderer:
        return renderer
    return "GPU"


def gpu_source_device_class(source: dict[str, Any], gpus: list[dict[str, Any]]) -> str:
    slot = normalize_gpu_interface(source.get("slot"))
    card = str(source.get("card") or "").strip().lower()
    for gpu in gpus:
        if slot and normalize_gpu_interface(gpu.get("Interface")) == slot:
            return str(gpu.get("DeviceClass") or "").strip().lower()
        if card and str(gpu.get("Card") or "").strip().lower() == card:
            return str(gpu.get("DeviceClass") or "").strip().lower()
    return ""


def should_blank_gpu_power_source(source: dict[str, Any], gpus: list[dict[str, Any]], values: list[Any]) -> bool:
    device_class = gpu_source_device_class(source, gpus)
    if device_class not in {"integrated", "apu"}:
        return False
    numeric_values: list[float] = []
    for value in values:
        try:
            numeric_values.append(float(value))
        except Exception:
            continue
    return bool(numeric_values) and max(numeric_values) < 1.0


def gpu_detail_export_sort_key(item: dict[str, Any], gpus: list[dict[str, Any]]) -> tuple[int, str]:
    name = str(item.get("name") or item.get("DeviceName") or "").strip()
    slot = normalize_gpu_interface(
        item.get("Slot")
        or item.get("ExpectedSlot")
        or item.get("slot")
        or item.get("target_slot")
        or item.get("ExpectedTargetId")
        or item.get("TargetId")
    )
    card = str(item.get("Card") or item.get("ExpectedCard") or item.get("card") or "").strip().lower()
    for index, gpu in enumerate(gpus):
        if slot and normalize_gpu_interface(gpu.get("Interface")) == slot:
            return (index, name)
        if card and str(gpu.get("Card") or "").strip().lower() == card:
            return (index, name)
        if name and name == str(gpu.get("DisplayName") or gpu.get("Name") or ""):
            return (index, name)
    try:
        gpu_index = int(item.get("GpuIndex", item.get("ExpectedGpuIndex", 9999)))
    except Exception:
        gpu_index = 9999
    return (gpu_index, name)


def resolve_gpu_source_device_name(source: dict[str, Any], gpus: list[dict[str, Any]]) -> str:
    slot = normalize_gpu_interface(source.get("slot"))
    if slot:
        for gpu in gpus:
            if normalize_gpu_interface(gpu.get("Interface")) == slot:
                return str(gpu.get("DisplayName") or gpu.get("Name") or slot)
    card = str(source.get("card") or "").strip().lower()
    if not card:
        label = str(source.get("label") or "")
        match = re.search(r"\b(card[0-9]+)\b", label)
        if match is not None:
            card = match.group(1).lower()
    if card:
        for gpu in gpus:
            if str(gpu.get("Card") or "").strip().lower() == card:
                return str(gpu.get("DisplayName") or gpu.get("Name") or card)
    try:
        gpu_index = int(source.get("gpu_index", 0))
    except Exception:
        gpu_index = 0
    if 0 <= gpu_index < len(gpus):
        return str(gpus[gpu_index].get("DisplayName") or gpus[gpu_index].get("Name") or f"GPU {gpu_index}")
    return f"GPU {gpu_index}"
