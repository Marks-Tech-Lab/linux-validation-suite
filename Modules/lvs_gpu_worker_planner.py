from __future__ import annotations

from typing import Any, Dict, List, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


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
    return gpu_3d_workers + vram_workers
