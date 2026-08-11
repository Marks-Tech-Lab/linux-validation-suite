from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


_MEMORY_PLAN_FIELDS = (
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
    "minimum_viable_allocation_bytes",
    "minimum_viable_allocation_source",
)


def _preserve_memory_plan(materialized: GpuWorkerSpec, planned: GpuWorkerSpec) -> GpuWorkerSpec:
    return replace(
        materialized,
        **{field: getattr(planned, field) for field in _MEMORY_PLAN_FIELDS},
    )


def materialize_gpu_worker(
    runner: Any,
    worker: GpuWorkerSpec,
    result_file: Optional[str] = None,
) -> GpuWorkerSpec:
    if worker.backend in {"glmark2", "vkmark", "vkcube", "glxgears"}:
        target = runner._gpu_target_by_id(worker.target_id)
        return GpuWorkerSpec(
            **{
                **asdict(worker),
                "command": runner._build_supervised_external_gpu_command(
                    backend=worker.backend,
                    target=target,
                    process_count=max(1, int(worker.process_count or 1)),
                    result_file=result_file or "",
                ),
            }
        )
    if worker.backend == "python_opencl_compute":
        target = runner._gpu_target_by_id(worker.target_id)
        if worker.workload == "gpu_3d":
            return _preserve_memory_plan(runner._build_python_opencl_compute_worker(
                target,
                worker.tuning_step,
                result_file or "",
                profile_mode=worker.profile_mode,
                profile_intensity=worker.profile_intensity,
                compute_variant=worker.compute_variant,
            ), worker)
        return worker
    if worker.backend == "python_vulkan_transfer":
        target = runner._gpu_target_by_id(worker.target_id)
        if worker.workload == "gpu_3d":
            return _preserve_memory_plan(runner._build_python_vulkan_transfer_worker(
                target,
                worker.tuning_step,
                result_file or "",
                profile_mode=worker.profile_mode,
                profile_intensity=worker.profile_intensity,
                buffer_bytes_override=worker.target_vram_bytes,
            ), worker)
        return worker
    if worker.backend == "python_vulkan_compute":
        target = runner._gpu_target_by_id(worker.target_id)
        if worker.workload == "gpu_3d":
            return _preserve_memory_plan(runner._build_python_vulkan_compute_worker(
                target,
                worker.tuning_step,
                result_file or "",
                profile_mode=worker.profile_mode,
                profile_intensity=worker.profile_intensity,
                compute_variant=worker.compute_variant,
                buffer_bytes_override=worker.target_vram_bytes,
                system_memory_fixed_commitment_bytes=worker.system_memory_fixed_commitment_bytes,
            ), worker)
        if worker.workload == "vram":
            return _preserve_memory_plan(runner._build_python_vulkan_vram_worker(
                target,
                worker.target_vram_bytes,
                worker.tuning_step,
                result_file or "",
                system_memory_fixed_commitment_bytes=worker.system_memory_fixed_commitment_bytes,
            ), worker)
        return worker
    if worker.backend == "python_opencl":
        target = runner._gpu_target_by_id(worker.target_id)
        if worker.workload == "vram":
            return _preserve_memory_plan(runner._build_python_opencl_vram_worker(
                target,
                worker.target_vram_bytes,
                worker.tuning_step,
                result_file or "",
            ), worker)
        return worker
    if worker.backend != "python_egl_gles2":
        return worker
    target = runner._gpu_target_by_id(worker.target_id)
    if worker.workload == "gpu_3d":
        return _preserve_memory_plan(runner._build_python_gpu_3d_worker(
            target,
            worker.tuning_step,
            result_file or "",
            profile_mode=worker.profile_mode,
            profile_intensity=worker.profile_intensity,
        ), worker)
    if worker.workload == "vram":
        return _preserve_memory_plan(runner._build_python_vram_worker(
            target,
            worker.target_vram_bytes,
            worker.tuning_step,
            result_file or "",
        ), worker)
    return worker
