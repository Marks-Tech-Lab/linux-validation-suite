from __future__ import annotations

import statistics
from typing import Any, Dict, List


class GpuWorkerStateSummaryBuilder:
    """Build parsed GPU worker state summaries from stage worker payloads."""

    def summary(self, window: Any) -> Dict[str, Any]:
        workers: List[Dict[str, Any]] = []
        load_values: List[float] = []
        active_vram_targets_gb: List[float] = []
        active_buffer_mb_values: List[float] = []
        allocated_vram_gb: List[float] = []
        allocation_percent_values: List[float] = []
        allocation_shortfall_mb_values: List[float] = []
        estimated_memory_gbps_values: List[float] = []
        estimated_memory_gb_values: List[float] = []
        for payload in window.worker_results:
            if str(payload.get("kind") or "").lower() != "gpu":
                continue
            gpu_index = payload.get("gpu_index")
            try:
                gpu_index = int(gpu_index)
            except Exception:
                gpu_index = None
            active_load_fraction = payload.get("active_load_fraction")
            try:
                active_load_fraction = float(active_load_fraction) if active_load_fraction is not None else None
            except Exception:
                active_load_fraction = None
            active_target_vram_bytes = (
                payload.get("active_target_vram_bytes")
                or payload.get("target_vram_bytes")
                or payload.get("target_buffer_bytes")
            )
            try:
                active_target_vram_bytes = int(active_target_vram_bytes) if active_target_vram_bytes is not None else None
            except Exception:
                active_target_vram_bytes = None
            active_buffer_bytes = payload.get("active_buffer_bytes")
            try:
                active_buffer_bytes = int(active_buffer_bytes) if active_buffer_bytes is not None else None
            except Exception:
                active_buffer_bytes = None
            allocated_vram_bytes = payload.get("allocated_vram_bytes") or payload.get("buffer_allocation_bytes")
            try:
                allocated_vram_bytes = int(allocated_vram_bytes) if allocated_vram_bytes is not None else None
            except Exception:
                allocated_vram_bytes = None
            allocation_shortfall_bytes = payload.get("allocation_shortfall_bytes")
            try:
                allocation_shortfall_bytes = int(allocation_shortfall_bytes) if allocation_shortfall_bytes is not None else None
            except Exception:
                allocation_shortfall_bytes = None
            allocation_percent = None
            if active_target_vram_bytes and allocated_vram_bytes is not None:
                allocation_percent = min(100.0, (allocated_vram_bytes / float(active_target_vram_bytes)) * 100.0)
                allocation_percent_values.append(allocation_percent)
            if active_target_vram_bytes and allocation_shortfall_bytes is not None:
                allocation_shortfall_mb_values.append(allocation_shortfall_bytes / float(1024 ** 2))
            if active_load_fraction is not None:
                load_values.append(active_load_fraction)
            if active_target_vram_bytes:
                active_vram_targets_gb.append(active_target_vram_bytes / float(1024 ** 3))
            if active_buffer_bytes:
                active_buffer_mb_values.append(active_buffer_bytes / float(1024 ** 2))
            if allocated_vram_bytes:
                allocated_vram_gb.append(allocated_vram_bytes / float(1024 ** 3))
            estimated_memory_gbps = payload.get("estimated_device_memory_gbps")
            try:
                estimated_memory_gbps = float(estimated_memory_gbps) if estimated_memory_gbps is not None else None
            except Exception:
                estimated_memory_gbps = None
            estimated_memory_gb = payload.get("estimated_device_memory_gb")
            try:
                estimated_memory_gb = float(estimated_memory_gb) if estimated_memory_gb is not None else None
            except Exception:
                estimated_memory_gb = None
            if estimated_memory_gbps is not None:
                estimated_memory_gbps_values.append(estimated_memory_gbps)
            if estimated_memory_gb is not None:
                estimated_memory_gb_values.append(estimated_memory_gb)
            workers.append(
                {
                    "Mode": str(payload.get("mode") or payload.get("workload") or ""),
                    "Backend": str(payload.get("backend") or ""),
                    "WorkerVersion": str(payload.get("worker_version") or ""),
                    "ProfileMode": str(payload.get("profile_mode") or ""),
                    "ProfileIntensity": str(payload.get("profile_intensity") or ""),
                    "DiagnosticBackend": bool(payload.get("diagnostic_backend")),
                    "SaturationResult": bool(payload.get("saturation_result")),
                    "PowerSaturationExpected": bool(payload.get("power_saturation_expected")),
                    "ComputeVariant": str(payload.get("compute_variant") or payload.get("kernel_variant") or ""),
                    "GpuIndex": gpu_index,
                    "TargetId": str(payload.get("target_id") or payload.get("slot") or payload.get("card") or ""),
                    "Status": str(payload.get("status") or ""),
                    "TuningStep": int(payload.get("tuning_step") or 0),
                    "ActiveLoadFraction": round(active_load_fraction, 3) if active_load_fraction is not None else None,
                    "ActiveTargetVramGB": round(active_target_vram_bytes / float(1024 ** 3), 2) if active_target_vram_bytes else None,
                    "ActiveBufferMB": round(active_buffer_bytes / float(1024 ** 2), 2) if active_buffer_bytes else None,
                    "ActiveDispatchBufferMB": round(float(payload.get("active_dispatch_buffer_bytes") or 0) / float(1024 ** 2), 2)
                    if payload.get("active_dispatch_buffer_bytes") is not None
                    else None,
                    "ActiveBufferCount": int(payload.get("active_buffer_count") or 0),
                    "ActiveBufferIndex": int(payload.get("active_buffer_index") or 0),
                    "BufferCount": int(payload.get("buffer_count") or 0),
                    "BufferCountLimit": int(payload.get("buffer_count_limit") or 0),
                    "PerBufferCapMB": round(float(payload.get("per_buffer_cap_bytes") or 0) / float(1024 ** 2), 2)
                    if payload.get("per_buffer_cap_bytes") is not None
                    else None,
                    "AllocationStrategy": str(payload.get("allocation_strategy") or ""),
                    "VerifiedBufferCount": int(payload.get("verified_buffer_count") or 0),
                    "VerifiedBufferCoveragePercent": (
                        round(float(payload.get("verified_buffer_coverage_percent")), 4)
                        if payload.get("verified_buffer_coverage_percent") is not None
                        else None
                    ),
                    "AllocatedVramGB": round(allocated_vram_bytes / float(1024 ** 3), 2) if allocated_vram_bytes else None,
                    "VramAllocationPercent": round(allocation_percent, 4) if allocation_percent is not None else None,
                    "AllocationShortfallMB": round(allocation_shortfall_bytes / float(1024 ** 2), 4) if active_target_vram_bytes and allocation_shortfall_bytes is not None else None,
                    "ActiveTargetTextureCount": payload.get("active_target_texture_count"),
                    "ActiveDrawCount": payload.get("active_draw_count"),
                    "ActiveClearPasses": payload.get("active_clear_passes"),
                    "ActiveLaunchesPerCycle": payload.get("active_launches_per_cycle"),
                    "ActiveComputeRounds": payload.get("active_compute_rounds"),
                    "ComputeRounds": payload.get("compute_rounds"),
                    "ActiveWorkItems": payload.get("active_work_items"),
                    "EstimatedDeviceMemoryGB": round(estimated_memory_gb, 3) if estimated_memory_gb is not None else None,
                    "EstimatedDeviceMemoryGBps": round(estimated_memory_gbps, 3) if estimated_memory_gbps is not None else None,
                    "PeakEstimatedDeviceMemoryGBps": (
                        round(float(payload.get("peak_estimated_device_memory_gbps")), 3)
                        if payload.get("peak_estimated_device_memory_gbps") is not None
                        else None
                    ),
                    "Frames": int(payload.get("frames") or 0),
                    "VerificationPasses": int(payload.get("verification_passes") or 0),
                    "TransferMismatchCount": int(payload.get("transfer_mismatch_count") or 0),
                }
            )
        aggregate = {
            "WorkerCount": len(workers),
            "MinActiveLoadFraction": round(min(load_values), 3) if load_values else None,
            "AvgActiveLoadFraction": round(statistics.mean(load_values), 3) if load_values else None,
            "MaxActiveLoadFraction": round(max(load_values), 3) if load_values else None,
            "MaxActiveTargetVramGB": round(max(active_vram_targets_gb), 2) if active_vram_targets_gb else None,
            "MaxActiveBufferMB": round(max(active_buffer_mb_values), 2) if active_buffer_mb_values else None,
            "AvgActiveBufferMB": round(statistics.mean(active_buffer_mb_values), 2) if active_buffer_mb_values else None,
            "MaxAllocatedVramGB": round(max(allocated_vram_gb), 2) if allocated_vram_gb else None,
            "MinVramAllocationPercent": round(min(allocation_percent_values), 4) if allocation_percent_values else None,
            "MaxAllocationShortfallMB": round(max(allocation_shortfall_mb_values), 4) if allocation_shortfall_mb_values else None,
            "MaxEstimatedDeviceMemoryGBps": round(max(estimated_memory_gbps_values), 3) if estimated_memory_gbps_values else None,
            "SumEstimatedDeviceMemoryGBps": round(sum(estimated_memory_gbps_values), 3) if estimated_memory_gbps_values else None,
            "MaxEstimatedDeviceMemoryGB": round(max(estimated_memory_gb_values), 3) if estimated_memory_gb_values else None,
            "SumEstimatedDeviceMemoryGB": round(sum(estimated_memory_gb_values), 3) if estimated_memory_gb_values else None,
        }
        return {"Aggregate": aggregate, "Workers": workers}
