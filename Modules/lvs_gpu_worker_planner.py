from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


def gpu_backend_minimum_viable_allocation(backend: str, workload: str) -> tuple[int, str]:
    backend_name = str(backend or "")
    workload_name = str(workload or "")
    if workload_name == "vram" and backend_name in {"python_opencl", "python_egl_gles2"}:
        return 64 * 1024 * 1024, f"{backend_name}_current_verified_workload_floor"
    if backend_name == "python_vulkan_transfer":
        return 16 * 1024 * 1024, "vulkan_transfer_current_buffer_floor"
    if backend_name == "python_vulkan_compute":
        return 8 * 1024 * 1024, "vulkan_compute_current_buffer_floor"
    return 0, "fixed_commitment_or_uncontrolled_backend"


def build_gpu_3d_worker_specs(
    runner: Any,
    gpu: Any,
    stage: Optional[Any] = None,
) -> List[GpuWorkerSpec]:
    targets = runner._gpu_targets(gpu.gpus)
    resolution = runner._resolve_gpu_backend_for_targets(
        candidates=runner._gpu_3d_backend_candidates(gpu, stage),
        targets=targets,
        workload="gpu_3d",
    )
    target_list = runner._effective_gpu_targets(targets, resolution)
    backend_name = str(resolution.get("backend") or "none")
    normalized_preference = runner._normalize_gpu_3d_backend_preference(gpu.backend_preference)

    def build_workers_for_backend(
        selected_backend: str,
        selected_targets: List[Optional[Dict[str, Any]]],
    ) -> List[GpuWorkerSpec]:
        if selected_backend == "glmark2":
            return [
                runner._external_gpu_worker_spec(
                    workload="gpu_3d",
                    backend="glmark2",
                    target=target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                )
                for target in selected_targets
            ]
        if selected_backend == "vkmark":
            return [
                runner._external_gpu_worker_spec(
                    workload="gpu_3d",
                    backend="vkmark",
                    target=target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                )
                for target in selected_targets
            ]
        if selected_backend == "vkcube":
            return [
                runner._external_gpu_worker_spec(
                    workload="gpu_3d",
                    backend="vkcube",
                    target=target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                )
                for target in selected_targets
            ]
        if selected_backend == "python_egl_gles2":
            return [
                runner._build_python_gpu_3d_worker(
                    target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                )
                for target in selected_targets
            ]
        if selected_backend == "python_opencl_compute":
            return [
                runner._build_python_opencl_compute_worker(
                    target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                    compute_variant=gpu.compute_variant,
                )
                for target in selected_targets
            ]
        if selected_backend == "python_vulkan_transfer":
            return [
                runner._build_python_vulkan_transfer_worker(
                    target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                )
                for target in selected_targets
            ]
        if selected_backend == "python_vulkan_compute":
            return [
                runner._build_python_vulkan_compute_worker(
                    target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                    compute_variant=gpu.compute_variant,
                    allocation_percent=gpu.allocation_percent,
                )
                for target in selected_targets
            ]
        if selected_backend == "glxgears":
            return [
                runner._external_gpu_worker_spec(
                    workload="gpu_3d",
                    backend="glxgears",
                    target=target,
                    profile_mode=gpu.mode,
                    profile_intensity=gpu.intensity,
                )
                for target in selected_targets
            ]
        return []

    if (
        normalized_preference == "auto"
        and targets
        and runner._allow_per_target_auto_gpu_3d_backends(gpu, stage)
        and (resolution.get("support") or {}).get("unsupported_targets")
    ):
        workers: List[GpuWorkerSpec] = []
        for target in targets:
            for candidate in runner._gpu_3d_backend_candidates(gpu, stage):
                if not runner._gpu_3d_backend_available(candidate):
                    continue
                support = runner._gpu_backend_target_support(candidate, target, "gpu_3d")
                if support.get("supported"):
                    workers.extend(build_workers_for_backend(candidate, [target]))
                    break
        if workers:
            return workers

    return build_workers_for_backend(backend_name, target_list)


def build_vram_worker_specs(
    runner: Any,
    vram: Any,
    stage: Optional[Any] = None,
) -> List[GpuWorkerSpec]:
    targets = runner._gpu_targets(vram.gpus)
    resolution = runner._resolve_gpu_backend_for_targets(
        candidates=runner._vram_backend_candidates(vram),
        targets=targets,
        workload="vram",
    )
    target_list = runner._effective_gpu_targets(targets, resolution)
    backend_name = str(resolution.get("backend") or "none")
    memory_allocation_percent = (
        int(stage.modules.memory.allocation_percent or 0)
        if stage is not None and stage.modules.memory.enabled
        else 0
    )
    concurrent_gpu_3d = bool(stage is not None and stage.modules.gpu_3d.enabled)
    stage_duration_seconds = int(stage.duration_seconds or 0) if stage is not None else 0
    concurrent_amd_discrete_target_count = (
        runner._amd_discrete_target_count(target_list)
        if concurrent_gpu_3d
        else 0
    )
    target_list = [
        target
        for target in target_list
        if (
            runner._use_vulkan_vram_worker_for_target(
                target,
                concurrent_gpu_3d=concurrent_gpu_3d,
                concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
                resolved_vram_backend=backend_name,
            )
            or not runner._skip_concurrent_vram_worker_for_target(
                target,
                concurrent_gpu_3d,
                concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
                vram_backend=backend_name,
            )
        )
    ]
    if backend_name == "python_opencl":
        workers: List[GpuWorkerSpec] = []
        for target in target_list:
            use_vulkan_vram = runner._use_vulkan_vram_worker_for_target(
                target,
                concurrent_gpu_3d=concurrent_gpu_3d,
                concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
                resolved_vram_backend=backend_name,
            )
            target_bytes = runner._target_vram_allocation_bytes(
                vram.allocation_percent,
                target,
                memory_allocation_percent=memory_allocation_percent,
                concurrent_gpu_3d=concurrent_gpu_3d,
                stage_duration_seconds=stage_duration_seconds,
                concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
                vram_backend="python_vulkan_compute" if use_vulkan_vram else backend_name,
            )
            if use_vulkan_vram:
                workers.append(runner._build_python_vulkan_vram_worker(target, target_bytes))
            else:
                workers.append(runner._build_python_opencl_vram_worker(target, target_bytes))
        return workers
    if backend_name == "python_vulkan_compute":
        return [
            runner._build_python_vulkan_vram_worker(
                target,
                runner._target_vram_allocation_bytes(
                    vram.allocation_percent,
                    target,
                    memory_allocation_percent=memory_allocation_percent,
                    concurrent_gpu_3d=concurrent_gpu_3d,
                    stage_duration_seconds=stage_duration_seconds,
                    concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
                    vram_backend=backend_name,
                ),
            )
            for target in target_list
        ]
    if backend_name != "python_egl_gles2":
        return []
    return [
        runner._build_python_vram_worker(
            target,
            runner._target_vram_allocation_bytes(
                vram.allocation_percent,
                target,
                memory_allocation_percent=memory_allocation_percent,
                concurrent_gpu_3d=concurrent_gpu_3d,
                stage_duration_seconds=stage_duration_seconds,
                concurrent_amd_discrete_target_count=concurrent_amd_discrete_target_count,
                vram_backend=backend_name,
            ),
        )
        for target in target_list
    ]


def build_stage_gpu_worker_specs(runner: Any, stage: Any) -> List[GpuWorkerSpec]:
    gpu_3d_workers: List[GpuWorkerSpec] = []
    vram_workers: List[GpuWorkerSpec] = []
    if stage.modules.gpu_3d.enabled:
        gpu_3d_workers.extend(build_gpu_3d_worker_specs(runner, stage.modules.gpu_3d, stage))
    if stage.modules.vram.enabled:
        vram_workers.extend(build_vram_worker_specs(runner, stage.modules.vram, stage))
    if stage.modules.gpu_3d.enabled and stage.modules.vram.enabled:
        fused_vulkan_vram_targets = {
            str(worker.target_id or worker.card or "")
            for worker in vram_workers
            if worker.backend == "python_vulkan_compute"
            and worker.workload == "vram"
            and worker.compute_variant == "stateful_memory"
        }
        if fused_vulkan_vram_targets:
            gpu_3d_workers = [
                worker
                for worker in gpu_3d_workers
                if str(worker.target_id or worker.card or "") not in fused_vulkan_vram_targets
            ]
    workers = gpu_3d_workers + vram_workers
    annotated: List[GpuWorkerSpec] = []
    for worker_index, worker in enumerate(workers, start=1):
        target_lookup = getattr(runner, "_gpu_target_by_id", None)
        target = target_lookup(worker.target_id) if callable(target_lookup) else None
        capability_lookup = getattr(runner, "_gpu_capability_profile", None)
        capability = capability_lookup(target) if callable(capability_lookup) else {}
        if worker.backend in {"python_opencl", "python_opencl_compute"}:
            backend_capacity = int(capability.get("opencl_global_memory_bytes") or 0)
            backend_capacity_source = "opencl_global_memory" if backend_capacity else ""
            backend_max_single = int(capability.get("opencl_max_single_allocation_bytes") or 0)
            backend_max_object = backend_max_single
            backend_max_count = 0
            backend_limit_source = "opencl_max_mem_alloc_size" if backend_max_single else ""
            backend_granularity = 4096
        elif worker.backend in {"python_vulkan_compute", "python_vulkan_transfer"}:
            backend_capacity = int(capability.get("vulkan_device_local_heap_bytes") or 0)
            backend_capacity_source = "vulkan_device_local_heap" if backend_capacity else ""
            backend_max_single = 0
            backend_max_object = int(capability.get("vulkan_max_storage_buffer_range_bytes") or 0)
            backend_max_count = int(capability.get("vulkan_max_memory_allocation_count") or 0)
            backend_limit_source = "vulkan_max_storage_buffer_range" if backend_max_object else ""
            backend_granularity = 1024
        elif worker.backend == "python_egl_gles2":
            backend_capacity = int(capability.get("shared_addressable_capacity_bytes") or 0)
            backend_capacity_source = str(capability.get("shared_addressable_capacity_source") or "")
            backend_max_single = 0
            backend_max_object = int(capability.get("gles_max_texture_object_bytes") or 0)
            backend_max_count = 512
            backend_limit_source = "gles_max_texture_size_rgba8" if backend_max_object else ""
            backend_granularity = 4
        else:
            backend_capacity = 0
            backend_capacity_source = ""
            backend_max_single = 0
            backend_max_object = 0
            backend_max_count = 0
            backend_limit_source = ""
            backend_granularity = 1
        minimum_viable, minimum_source = gpu_backend_minimum_viable_allocation(worker.backend, worker.workload)
        requested_percent = int(
            stage.modules.vram.allocation_percent
            if worker.workload == "vram"
            else stage.modules.gpu_3d.allocation_percent
            if worker.workload == "gpu_3d"
            else 0
        )
        memory_kind = str(capability.get("memory_kind") or "unknown")
        budgetable = bool(
            memory_kind in {"shared", "unknown"}
            and (
                int(worker.target_vram_bytes or 0) > 0
                or int(worker.system_memory_fixed_commitment_bytes or 0) > 0
                or (worker.workload == "vram" and requested_percent > 0)
            )
            and (
                worker.workload == "vram"
                or worker.backend in {"python_vulkan_compute", "python_vulkan_transfer"}
            )
        )
        if budgetable:
            budgetability = (
                "nominal_fixed_texture_budget_physical_commitment_unknown"
                if worker.backend == "python_egl_gles2" and worker.workload == "gpu_3d"
                else "enforceable_byte_target"
                if memory_kind == "shared"
                else "unknown_memory_kind_conservatively_system_budgeted"
            )
        elif memory_kind != "shared":
            budgetability = (
                "dedicated_vram_outside_system_pool"
                if memory_kind == "dedicated"
                else "unknown_memory_kind_without_enforceable_target"
            )
        elif worker.backend in {"glmark2", "vkmark", "vkcube", "glxgears"}:
            budgetability = "externally_controlled_unbounded"
        else:
            budgetability = "fixed_small_or_runtime_managed_without_credible_byte_bound"
        annotated.append(
            replace(
                worker,
                gpu_memory_kind=memory_kind,
                memory_classification_source=str(capability.get("classification_source") or ""),
                memory_capacity_source=str(
                    capability.get("shared_addressable_capacity_source")
                    if memory_kind == "shared"
                    else capability.get("dedicated_vram_capacity_source")
                    or ""
                ),
                dedicated_vram_capacity_bytes=int(capability.get("dedicated_vram_capacity_bytes") or 0),
                shared_addressable_capacity_bytes=int(capability.get("shared_addressable_capacity_bytes") or 0),
                shared_addressable_capacity_status=str(capability.get("shared_addressable_capacity_status") or "unknown"),
                api_addressable_capacity_bytes=int(capability.get("api_addressable_capacity_bytes") or 0),
                api_addressable_capacity_source=str(capability.get("api_addressable_capacity_source") or ""),
                backend_addressable_capacity_bytes=backend_capacity if memory_kind == "shared" else int(capability.get("dedicated_vram_capacity_bytes") or 0),
                backend_addressable_capacity_source=backend_capacity_source if memory_kind == "shared" else str(capability.get("dedicated_vram_capacity_source") or ""),
                backend_addressable_capacity_status=(
                    "api_addressable_upper_bound"
                    if memory_kind == "shared" and backend_capacity > 0
                    else "unknown_bounded_by_system_pool"
                    if memory_kind == "shared"
                    else "trusted_dedicated_capacity"
                    if memory_kind == "dedicated"
                    else "unknown"
                ),
                total_capacity_trust=str(capability.get("total_capacity_trust") or "unknown"),
                system_memory_pool_ceiling_bytes=int(capability.get("system_memory_pool_ceiling_bytes") or 0),
                max_single_allocation_bytes=backend_max_single,
                max_single_allocation_source=backend_limit_source if backend_max_single else "",
                max_buffer_or_object_bytes=backend_max_object,
                max_buffer_or_object_source=backend_limit_source,
                max_allocation_count=backend_max_count,
                max_allocation_count_source=(
                    "vulkan_max_memory_allocation_count"
                    if worker.backend.startswith("python_vulkan") and backend_max_count
                    else "lvs_egl_texture_count_practical_cap"
                    if worker.backend == "python_egl_gles2"
                    else ""
                ),
                allocation_granularity_bytes=backend_granularity,
                reported_vram_total_bytes=int(capability.get("reported_vram_total_bytes") or 0),
                reported_vram_total_semantics=str(capability.get("reported_vram_total_semantics") or "unknown"),
                ambiguous_integrated_vram_report_bytes=int(capability.get("ambiguous_integrated_vram_report_bytes") or 0),
                current_gpu_memory_used_bytes=capability.get("current_gpu_memory_used_bytes"),
                current_gpu_memory_used_source=str(capability.get("current_gpu_memory_used_source") or ""),
                current_gpu_memory_available_bytes=capability.get("current_gpu_memory_available_bytes"),
                current_gpu_memory_available_source=str(capability.get("current_gpu_memory_available_source") or ""),
                firmware_preallocated_or_stolen_bytes=capability.get("firmware_preallocated_or_stolen_bytes"),
                firmware_preallocated_or_stolen_source=str(capability.get("firmware_preallocated_or_stolen_source") or ""),
                requested_gpu_memory_target_bytes=int(worker.target_vram_bytes or 0),
                requested_gpu_memory_percent=requested_percent,
                planned_gpu_memory_target_bytes=int(worker.target_vram_bytes or 0),
                system_memory_budget_participation=budgetable,
                system_memory_commitment_multiplier=(2 if worker.backend == "python_vulkan_transfer" else 1),
                system_memory_fixed_commitment_bytes=(
                    max(int(worker.system_memory_fixed_commitment_bytes or 0), 1024 * 1024)
                    if worker.backend == "python_vulkan_compute"
                    else int(worker.system_memory_fixed_commitment_bytes or 0)
                ),
                memory_budget_consumer_id=(
                    f"gpu:{worker_index}:{worker.workload}:{worker.backend}:{worker.target_id or worker.card}"
                ),
                memory_budgetability=budgetability,
                target_cap_reason=(
                    "profile_percentage_and_api_addressable_upper_bound"
                    if memory_kind == "shared" and int(capability.get("shared_addressable_capacity_bytes") or 0) > 0
                    else "unknown_capacity_bounded_by_system_pool"
                    if memory_kind == "shared"
                    else "profile_percentage_and_dedicated_capacity"
                    if memory_kind == "dedicated"
                    else "conservative_unknown_memory_budget"
                ),
                minimum_viable_allocation_bytes=minimum_viable,
                minimum_viable_allocation_source=minimum_source,
            )
        )
    return annotated
