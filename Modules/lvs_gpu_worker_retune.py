from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


def retune_gpu_worker(runner: Any, spec: GpuWorkerSpec) -> Optional[GpuWorkerSpec]:
    if spec.backend not in {"python_egl_gles2", "python_opencl_compute", "python_opencl"}:
        return None
    if spec.system_memory_budget_participation and (
        spec.workload == "gpu_3d" or spec.backend == "python_egl_gles2"
    ):
        # These workers derive fixed buffers/textures from tuned load
        # parameters. Until they expose a byte-target retune control, the
        # launch-time shared-memory assignment is authoritative.
        return None
    target = runner._gpu_target_by_id(spec.target_id)
    next_step = spec.tuning_step + 1
    if next_step > runner._gpu_safe_max_tuning_step():
        return None
    if spec.workload == "gpu_3d":
        if spec.backend == "python_opencl_compute":
            rebuilt = runner._build_python_opencl_compute_worker(
                target,
                next_step,
                profile_mode=spec.profile_mode,
                profile_intensity=spec.profile_intensity,
                compute_variant=spec.compute_variant,
            )
        else:
            rebuilt = runner._build_python_gpu_3d_worker(
                target,
                next_step,
                profile_mode=spec.profile_mode,
                profile_intensity=spec.profile_intensity,
            )
        return replace(
            rebuilt,
            gpu_memory_kind=spec.gpu_memory_kind,
            memory_classification_source=spec.memory_classification_source,
            memory_capacity_source=spec.memory_capacity_source,
            dedicated_vram_capacity_bytes=spec.dedicated_vram_capacity_bytes,
            shared_addressable_capacity_bytes=spec.shared_addressable_capacity_bytes,
            reported_vram_total_bytes=spec.reported_vram_total_bytes,
            reported_vram_total_semantics=spec.reported_vram_total_semantics,
            ambiguous_integrated_vram_report_bytes=spec.ambiguous_integrated_vram_report_bytes,
            current_gpu_memory_used_bytes=spec.current_gpu_memory_used_bytes,
            current_gpu_memory_used_source=spec.current_gpu_memory_used_source,
            firmware_preallocated_or_stolen_bytes=spec.firmware_preallocated_or_stolen_bytes,
            firmware_preallocated_or_stolen_source=spec.firmware_preallocated_or_stolen_source,
            requested_gpu_memory_target_bytes=spec.requested_gpu_memory_target_bytes,
            planned_gpu_memory_target_bytes=spec.planned_gpu_memory_target_bytes,
            system_memory_budget_participation=spec.system_memory_budget_participation,
            memory_budget_consumer_id=spec.memory_budget_consumer_id,
            memory_budgetability=spec.memory_budgetability,
            target_cap_reason=spec.target_cap_reason,
        )
    if spec.workload == "vram":
        target_total = int(target.get("vram_total") or 0) if target else 0
        tuned_target = int(spec.target_vram_bytes * 1.15)
        if target_total > 0:
            tuned_target = min(tuned_target, int(target_total * 0.99))
        tuned_target = runner._cap_gpu_vram_target_bytes(target, tuned_target)
        if spec.system_memory_budget_participation:
            tuned_target = min(tuned_target, int(spec.planned_gpu_memory_target_bytes or spec.target_vram_bytes))
        if spec.backend == "python_opencl":
            rebuilt = runner._build_python_opencl_vram_worker(target, tuned_target, next_step)
        else:
            rebuilt = runner._build_python_vram_worker(target, tuned_target, next_step)
        return replace(
            rebuilt,
            gpu_memory_kind=spec.gpu_memory_kind,
            memory_classification_source=spec.memory_classification_source,
            memory_capacity_source=spec.memory_capacity_source,
            dedicated_vram_capacity_bytes=spec.dedicated_vram_capacity_bytes,
            shared_addressable_capacity_bytes=spec.shared_addressable_capacity_bytes,
            reported_vram_total_bytes=spec.reported_vram_total_bytes,
            reported_vram_total_semantics=spec.reported_vram_total_semantics,
            ambiguous_integrated_vram_report_bytes=spec.ambiguous_integrated_vram_report_bytes,
            current_gpu_memory_used_bytes=spec.current_gpu_memory_used_bytes,
            current_gpu_memory_used_source=spec.current_gpu_memory_used_source,
            firmware_preallocated_or_stolen_bytes=spec.firmware_preallocated_or_stolen_bytes,
            firmware_preallocated_or_stolen_source=spec.firmware_preallocated_or_stolen_source,
            requested_gpu_memory_target_bytes=spec.requested_gpu_memory_target_bytes,
            planned_gpu_memory_target_bytes=spec.planned_gpu_memory_target_bytes,
            system_memory_budget_participation=spec.system_memory_budget_participation,
            memory_budget_consumer_id=spec.memory_budget_consumer_id,
            memory_budgetability=spec.memory_budgetability,
            target_cap_reason=spec.target_cap_reason,
        )
    return None
