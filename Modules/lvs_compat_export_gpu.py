#!/usr/bin/env python3
"""Compatibility export GPU section assembly."""

from __future__ import annotations

import statistics
from copy import deepcopy
from typing import Any, Callable

from .lvs_compat_export_helpers import build_gpu_metric_test, build_gpu_temp_test
from .lvs_worker_integrity import worker_verification_required, worker_verification_satisfied


def _integer_index_or_unavailable(payload: dict[str, Any], key: str) -> int:
    """Preserve valid zero-based Vulkan indices while retaining the legacy sentinel."""
    value = payload.get(key)
    if value is None or value == "":
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def build_gpu_power_details(
    *,
    gpu_sources: list[dict[str, Any]],
    samples: list[Any],
    should_blank_source: Callable[[dict[str, Any], list[Any]], bool],
    source_device_name: Callable[[dict[str, Any]], str],
    sort_key: Callable[[dict[str, Any]], tuple[int, str]],
) -> list[dict[str, Any]] | None:
    """Build normalized GPU power detail rows from telemetry sources."""
    details: list[dict[str, Any]] = []
    for source in gpu_sources:
        if source.get("metric") != "power_w":
            continue
        key = source.get("key")
        if not key:
            continue
        values = [
            sample.values.get(key)
            for sample in samples
            if sample.values.get(key) is not None
        ]
        if not values:
            continue
        if should_blank_source(source, values):
            continue
        details.append(
            {
                "name": source_device_name(source),
                "sensor_name": source.get("label", "power"),
                "category": "board",
                "is_primary": True,
                "min": round(min(values), 2),
                "avg": round(statistics.mean(values), 2),
                "max": round(max(values), 2),
            }
        )
    details.sort(key=sort_key)
    return details or None


def build_gpu_worker_validation_detail(
    *,
    stage_name: str,
    stage_type: str,
    stage_verdict: str,
    payload: dict[str, Any],
    backend_name: str,
    device_name: str,
) -> dict[str, Any]:
    """Build one compatibility GPU worker validation-detail row."""
    expected_gpu_index = payload.get("gpu_index")
    if expected_gpu_index is None:
        expected_gpu_index = payload.get("target_gpu_index")
    try:
        expected_gpu_index = int(expected_gpu_index)
    except Exception:
        expected_gpu_index = None
    expected_target_id = str(payload.get("target_id") or "").strip()
    expected_slot = str(payload.get("slot") or payload.get("target_slot") or "").strip()
    expected_card = str(payload.get("card") or payload.get("target_card") or "").strip()
    worker_mode = str(payload.get("mode") or payload.get("workload") or "").strip()
    allocated_vram_bytes = int(payload.get("allocated_vram_bytes") or payload.get("buffer_allocation_bytes") or 0)
    target_vram_bytes = int(
        payload.get("active_target_vram_bytes")
        or payload.get("target_vram_bytes")
        or payload.get("target_buffer_bytes")
        or 0
    )
    allocation_percent = (
        round(allocated_vram_bytes / target_vram_bytes * 100.0, 4)
        if allocated_vram_bytes > 0 and target_vram_bytes > 0
        else None
    )
    return {
        "Stage": stage_name,
        "StageType": stage_type,
        "StageVerdict": stage_verdict,
        "Mode": worker_mode,
        "Workload": worker_mode,
        "Backend": backend_name,
        "WorkerVersion": str(payload.get("worker_version") or ""),
        "BackendApiFamily": str(payload.get("backend_api_family") or ""),
        "SuiteScalingMode": str(payload.get("suite_scaling_mode") or ""),
        "SuiteVerification": str(payload.get("suite_verification") or ""),
        "VerificationRequired": worker_verification_required(payload),
        "VerificationSatisfied": worker_verification_satisfied(payload),
        "DiagnosticBackend": bool(payload.get("diagnostic_backend")),
        "SaturationResult": bool(payload.get("saturation_result")),
        "PowerSaturationExpected": bool(payload.get("power_saturation_expected")),
        "ProfileMode": str(payload.get("profile_mode") or ""),
        "ProfileIntensity": str(payload.get("profile_intensity") or ""),
        "SelectionAmbiguous": bool(payload.get("selection_ambiguous")),
        "DeviceName": device_name,
        "ExpectedGpuIndex": expected_gpu_index,
        "ExpectedTargetId": expected_target_id,
        "ExpectedSlot": expected_slot,
        "ExpectedCard": expected_card,
        "ExpectedTargetMapping": {
            "GpuIndex": expected_gpu_index,
            "TargetId": expected_target_id,
            "Slot": expected_slot,
            "Card": expected_card,
        },
        "GpuIndex": expected_gpu_index,
        "TargetId": expected_target_id,
        "Slot": expected_slot,
        "Card": expected_card,
        "Status": str(payload.get("status") or ""),
        "GpuMemoryKind": str(payload.get("gpu_memory_kind") or "unknown"),
        "MemoryClassificationSource": str(payload.get("memory_classification_source") or ""),
        "MemoryClassificationConfidence": str(payload.get("memory_classification_confidence") or "low"),
        "DedicatedGpuMemoryBytes": int(payload.get("dedicated_vram_capacity_bytes") or 0),
        "SharedAddressableGpuMemoryBytes": int(payload.get("shared_addressable_capacity_bytes") or 0),
        "ApiAddressableGpuMemoryBytes": int(payload.get("api_addressable_capacity_bytes") or 0),
        "ApiAddressableGpuMemorySource": str(payload.get("api_addressable_capacity_source") or ""),
        "ComputeVariant": str(payload.get("compute_variant") or payload.get("kernel_variant") or ""),
        "WorkloadPurpose": str(payload.get("workload_purpose") or ""),
        "ErrorCount": int(payload.get("error_count") or 0),
        "GlErrorCount": int(payload.get("gl_error_count") or 0),
        "DrawMismatchCount": int(payload.get("draw_mismatch_count") or 0),
        "VramMismatchCount": int(payload.get("vram_mismatch_count") or 0),
        "TransferMismatchCount": int(payload.get("transfer_mismatch_count") or 0),
        "VerificationPasses": int(payload.get("verification_passes") or 0),
        "RenderVerificationPasses": int(payload.get("render_verification_passes") or 0),
        "VramVerificationPasses": int(payload.get("vram_verification_passes") or 0),
        "Frames": int(payload.get("frames") or 0),
        "TuningStep": int(payload.get("tuning_step") or 0),
        "ActiveLoadFraction": round(float(payload.get("active_load_fraction")), 3)
        if payload.get("active_load_fraction") is not None
        else None,
        "TargetProcessCount": int(payload.get("target_process_count") or 0),
        "ActiveProcessCount": int(payload.get("active_process_count") or 0),
        "ActiveTargetVramBytes": int(payload.get("active_target_vram_bytes") or 0),
        "ActiveTargetTextureCount": int(payload.get("active_target_texture_count") or 0),
        "ActiveFillBufferCount": int(payload.get("active_fill_buffer_count") or 0),
        "ActiveDrawCount": int(payload.get("active_draw_count") or 0),
        "ActiveClearPasses": int(payload.get("active_clear_passes") or 0),
        "ActiveLaunchesPerCycle": int(payload.get("active_launches_per_cycle") or 0),
        "ActiveComputeRounds": int(payload.get("active_compute_rounds") or 0),
        "ComputeRounds": int(payload.get("compute_rounds") or 0),
        "ActiveDispatchRepeats": int(payload.get("active_dispatch_repeats") or 0),
        "DispatchRepeats": int(payload.get("dispatch_repeats") or 0),
        "EffectiveComputeRounds": int(payload.get("effective_compute_rounds") or 0),
        "DependentComputeRounds": int(payload.get("dependent_compute_rounds") or 0),
        "IndependentDispatchRepetitions": int(payload.get("independent_dispatch_repetitions") or 0),
        "QueueSubmissionCount": int(payload.get("queue_submission_count") or 0),
        "ComputeDispatchCount": int(payload.get("compute_dispatch_count") or 0),
        "TimingInstrumentationScope": str(payload.get("timing_instrumentation_scope") or ""),
        "FenceWaitSemantics": str(payload.get("fence_wait_semantics") or ""),
        "CommandBufferRecordCount": int(payload.get("command_buffer_record_count") or 0),
        "CommandBufferReuseCount": int(payload.get("command_buffer_reuse_count") or 0),
        "CommandRecordElapsedSeconds": float(payload.get("command_record_elapsed_seconds") or 0.0),
        "QueueSubmitElapsedSeconds": float(payload.get("queue_submit_elapsed_seconds") or 0.0),
        "FenceWaitElapsedSeconds": float(payload.get("fence_wait_elapsed_seconds") or 0.0),
        "VerificationReadbackCount": int(payload.get("verification_readback_count") or 0),
        "VerificationReadbackElapsedSeconds": float(payload.get("verification_readback_elapsed_seconds") or 0.0),
        "VerificationIntervalsSeconds": list(payload.get("verification_intervals_seconds") or []),
        "InitialVerificationCompleted": payload.get("initial_verification_completed"),
        "FinalVerificationCompleted": payload.get("final_verification_completed"),
        "ResultWriteCount": int(payload.get("result_write_count") or 0),
        "ResultWriteElapsedSeconds": float(payload.get("result_write_elapsed_seconds") or 0.0),
        "SlowOperationEvidence": deepcopy(payload.get("slow_operation_evidence")),
        "ResultWriteErrorCount": payload.get("result_write_error_count"),
        "LastResultWriteError": payload.get("last_result_write_error"),
        "SleepYieldElapsedSeconds": float(payload.get("sleep_yield_elapsed_seconds") or 0.0),
        "CycleCount": int(payload.get("cycle_count") or 0),
        "CycleElapsedSeconds": float(payload.get("cycle_elapsed_seconds") or 0.0),
        "SubmissionBatchIterations": int(payload.get("submission_batch_iterations") or 0),
        "SubmissionBatchIterationsMax": int(payload.get("submission_batch_iterations_max") or 0),
        "WorkgroupLocalSize": list(payload.get("workgroup_local_size") or []),
        "DispatchGroupCount": list(payload.get("dispatch_group_count") or []),
        "GpuTimestampStatus": str(payload.get("gpu_timestamp_status") or ""),
        "GpuTimestampReason": str(payload.get("gpu_timestamp_reason") or ""),
        "GpuTimestampSemantics": str(payload.get("gpu_timestamp_semantics") or ""),
        "GpuTimestampBatchCount": int(payload.get("gpu_timestamp_batch_count") or 0),
        "GpuTimestampElapsedSeconds": float(payload.get("gpu_timestamp_elapsed_seconds") or 0.0),
        "StartupCheckpoint": str(payload.get("startup_checkpoint") or ""),
        "StartupComplete": payload.get("startup_complete"),
        "FaultDiagnosticsEnabled": payload.get("fault_diagnostics_enabled"),
        "ActiveWorkItems": int(payload.get("active_work_items") or 0),
        "ActiveBufferBytes": int(payload.get("active_buffer_bytes") or 0),
        "ActiveDispatchBufferBytes": int(payload.get("active_dispatch_buffer_bytes") or 0),
        "ActiveBufferCount": int(payload.get("active_buffer_count") or 0),
        "ActiveBufferIndex": int(payload.get("active_buffer_index") or 0),
        "BufferBytes": int(payload.get("buffer_bytes") or 0),
        "AllocatedVramBytes": allocated_vram_bytes,
        "TargetVramBytes": target_vram_bytes,
        "AllocatedGpuMemoryBytes": allocated_vram_bytes,
        "TargetGpuMemoryBytes": target_vram_bytes,
        "AllocationPercent": allocation_percent,
        "RequestedBufferBytes": int(payload.get("requested_buffer_bytes") or 0),
        "TargetBufferBytes": int(payload.get("target_buffer_bytes") or 0),
        "WorkerTotalCapBytes": int(payload.get("worker_total_cap_bytes") or 0),
        "BufferCount": int(payload.get("buffer_count") or 0),
        "BufferCountLimit": int(payload.get("buffer_count_limit") or 0),
        "PerBufferCapBytes": int(payload.get("per_buffer_cap_bytes") or 0),
        "BufferSizeMinBytes": int(payload.get("buffer_size_min_bytes") or 0),
        "BufferSizeMaxBytes": int(payload.get("buffer_size_max_bytes") or 0),
        "BufferSizeAvgBytes": int(payload.get("buffer_size_avg_bytes") or 0),
        "BufferAllocationBytes": int(payload.get("buffer_allocation_bytes") or 0),
        "AllocationStrategy": str(payload.get("allocation_strategy") or ""),
        "RequestedDeviceLocalHeapPercent": float(payload.get("requested_device_local_heap_percent") or 0.0),
        "TargetDeviceLocalHeapPercent": float(payload.get("target_device_local_heap_percent") or 0.0),
        "BufferMemoryTypeIndex": _integer_index_or_unavailable(payload, "buffer_memory_type_index"),
        "BufferMemoryTypeFlags": int(payload.get("buffer_memory_type_flags") or 0),
        "BufferMemoryHeapIndex": _integer_index_or_unavailable(payload, "buffer_memory_heap_index"),
        "BufferDeviceLocalHeapPercent": float(payload.get("buffer_device_local_heap_percent") or 0.0),
        "StagingMemoryTypeIndex": _integer_index_or_unavailable(payload, "staging_memory_type_index"),
        "DeviceLocalHeapBytes": int(payload.get("device_local_heap_bytes") or 0),
        "DeviceLocalHeapGB": float(payload.get("device_local_heap_gb") or 0.0),
        "EstimatedDeviceMemoryBytes": int(payload.get("estimated_device_memory_bytes") or 0),
        "EstimatedDeviceMemoryGB": float(payload.get("estimated_device_memory_gb") or 0.0),
        "EstimatedDeviceMemoryGBps": float(payload.get("estimated_device_memory_gbps") or 0.0),
        "PeakEstimatedDeviceMemoryGBps": float(payload.get("peak_estimated_device_memory_gbps") or 0.0),
        "ElapsedSeconds": float(payload.get("elapsed_seconds") or 0.0),
        "VerifiedBufferCount": int(payload.get("verified_buffer_count") or 0),
        "VerifiedBufferCoveragePercent": (
            float(payload.get("verified_buffer_coverage_percent"))
            if payload.get("verified_buffer_coverage_percent") is not None
            else None
        ),
        "VerifiedBufferIndexes": list(payload.get("verified_buffer_indexes") or []),
        "BufferDispatchMin": int(payload.get("buffer_dispatch_min") or 0),
        "BufferDispatchMax": int(payload.get("buffer_dispatch_max") or 0),
        "BufferDispatchAvg": float(payload.get("buffer_dispatch_avg") or 0.0),
        "Phase": str(payload.get("phase") or ""),
        "RuntimeTargetCapBytes": int(payload.get("runtime_target_cap_bytes") or 0),
        "PhaseLimitBytes": int(payload.get("phase_limit_bytes") or 0),
        "LastSuccessfulBytes": int(payload.get("last_successful_bytes") or 0),
        "RuntimeWorkItemCap": int(payload.get("runtime_work_item_cap") or 0),
        "RuntimeLaunchCap": int(payload.get("runtime_launch_cap") or 0),
        "RuntimeRoundCap": int(payload.get("runtime_round_cap") or 0),
        "RuntimeBufferCount": int(payload.get("runtime_buffer_count") or 0),
        "AllocationAttempts": int(payload.get("allocation_attempts") or 0),
        "AllocationTouchCount": int(payload.get("allocation_touch_count") or 0),
        "AllocationFailures": int(payload.get("allocation_failures") or 0),
        "AllocationExhausted": bool(payload.get("allocation_exhausted")),
        "AllocationShortfallBytes": int(payload.get("allocation_shortfall_bytes") or 0),
        "SelectedDeviceName": str(payload.get("selected_device_name") or ""),
        "PlatformName": str(payload.get("platform_name") or ""),
        "PlatformVendor": str(payload.get("platform_vendor") or ""),
        "Renderer": str(payload.get("renderer") or ""),
        "ResolvedDeviceName": str(payload.get("resolved_device_name") or ""),
        "ResultPath": str(payload.get("result_path") or ""),
    }


def build_gpu_worker_metric_test(
    *,
    windows: list[Any],
    mode: str,
    metric_key: str,
    device_name_resolver: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    """Aggregate one GPU worker metric into compatibility test rows."""
    results: dict[str, dict[str, dict[str, float | None]]] = {}
    any_non_zero = False
    target_mode = (mode or "").strip().lower()
    for window in windows:
        for payload in window.worker_results:
            if str(payload.get("kind") or "").lower() != "gpu":
                continue
            payload_mode = str(payload.get("mode") or payload.get("workload") or "").strip().lower()
            if payload_mode != target_mode:
                continue
            if metric_key not in payload:
                continue
            value = payload.get(metric_key)
            if value is None:
                continue
            try:
                numeric = float(value)
            except Exception:
                continue
            if numeric != 0.0:
                any_non_zero = True
            device_name = device_name_resolver(payload)
            results.setdefault(device_name, {})[window.display_name] = {
                "max": round(numeric, 2),
                "avg": round(numeric, 2),
                "min": round(numeric, 2),
            }
    if not any_non_zero:
        return []
    return [
        {"device": device_name, "results": device_results}
        for device_name, device_results in results.items()
    ]


def build_compatibility_gpu_section(
    *,
    gpu_devices: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    worker_metric_tests: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build the stable compatibility GPU section from normalized inputs."""
    devices = [
        {
            "gpu_name": gpu.get("Name", "-"),
            "gpu_display_name": gpu.get("DisplayName", gpu.get("Name", "-")),
            "gpu_physical_id": gpu.get("PhysicalGpuId", ""),
            "gpu_identity_source": gpu.get("PhysicalGpuIdentitySource", ""),
            "gpu_identity_confidence": gpu.get("PhysicalGpuIdentityConfidence", ""),
            "gpu_platform_device_path": gpu.get("PlatformDevicePath", ""),
            "gpu_chipset": gpu.get("Chipset", "-"),
            "gpu_driver": gpu.get("DriverVersion", "-"),
            "gpu_memory": gpu.get("Memory", "-"),
            "gpu_device_class": gpu.get("DeviceClass", "unknown"),
            "gpu_device_class_source": gpu.get("DeviceClassSource", ""),
            "gpu_memory_architecture": gpu.get("MemoryArchitecture", "unknown"),
            "gpu_memory_architecture_source": gpu.get("MemoryArchitectureSource", ""),
            "gpu_memory_architecture_confidence": gpu.get("MemoryArchitectureConfidence", "low"),
            "gpu_dedicated_memory_bytes": gpu.get("DedicatedMemoryBytes"),
            "gpu_dedicated_memory_status": gpu.get("DedicatedMemoryStatus", "unknown"),
            "gpu_vulkan_device_local_api_capacity_bytes": gpu.get("VulkanDeviceLocalHeapBytes"),
        }
        for gpu in gpu_devices
    ]

    tests: dict[str, Any] = {}

    core_temps = build_gpu_temp_test(segments, "Core")
    hotspot_temps = build_gpu_temp_test(segments, "Hotspot")
    memory_temps = build_gpu_temp_test(segments, "Memory")
    gpu_clocks = build_gpu_metric_test(segments, "Clock")
    gpu_memory_clocks = build_gpu_metric_test(segments, "MemoryClock")
    gpu_power = build_gpu_metric_test(segments, "Power")
    gpu_usage = build_gpu_metric_test(segments, "Usage")
    gpu_memory_usage = build_gpu_metric_test(segments, "MemoryUsage")
    gpu_vram_used = build_gpu_metric_test(segments, "VramUsedGB")

    if core_temps:
        tests["GPU Temperature (Temperature)"] = core_temps
    if hotspot_temps:
        tests["GPU Hotspot Temperature (Temperature)"] = hotspot_temps
    if memory_temps:
        tests["GPU Memory Junction Temperature (Temperature)"] = memory_temps
    if gpu_clocks:
        tests["GPU Clock (Frequency)"] = gpu_clocks
    if gpu_memory_clocks:
        tests["GPU Memory Clock (Frequency)"] = gpu_memory_clocks
    if gpu_power:
        tests["GPU Power (Power)"] = gpu_power
    if gpu_usage:
        tests["GPU Usage (Usage)"] = gpu_usage
    if gpu_memory_usage:
        tests["GPU Memory Controller Usage (Usage)"] = gpu_memory_usage
    if gpu_vram_used:
        tests["GPU VRAM Used (Usage)"] = gpu_vram_used

    worker_test_names = (
        ("gpu_3d_errors", "GPU 3D Verification Errors (Errors)"),
        ("gpu_3d_api_errors", "GPU 3D API Errors (Errors)"),
        ("gpu_3d_draw_mismatches", "GPU 3D Draw Mismatches (Errors)"),
        ("gpu_vram_errors", "GPU VRAM Verification Errors (Errors)"),
        ("gpu_vram_api_errors", "GPU VRAM API Errors (Errors)"),
        ("gpu_vram_mismatches", "GPU VRAM Data Mismatches (Errors)"),
        ("gpu_vram_shortfall", "GPU VRAM Allocation Shortfall (Bytes)"),
    )
    for key, label in worker_test_names:
        value = worker_metric_tests.get(key)
        if value:
            tests[label] = value

    return {"devices": devices, "tests": tests}
