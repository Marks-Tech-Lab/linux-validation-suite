from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


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
            return runner._build_python_opencl_compute_worker(
                target,
                worker.tuning_step,
                result_file or "",
                profile_mode=worker.profile_mode,
                profile_intensity=worker.profile_intensity,
                compute_variant=worker.compute_variant,
            )
        return worker
    if worker.backend == "python_vulkan_transfer":
        target = runner._gpu_target_by_id(worker.target_id)
        if worker.workload == "gpu_3d":
            return runner._build_python_vulkan_transfer_worker(
                target,
                worker.tuning_step,
                result_file or "",
                profile_mode=worker.profile_mode,
                profile_intensity=worker.profile_intensity,
            )
        return worker
    if worker.backend == "python_vulkan_compute":
        target = runner._gpu_target_by_id(worker.target_id)
        if worker.workload == "gpu_3d":
            return runner._build_python_vulkan_compute_worker(
                target,
                worker.tuning_step,
                result_file or "",
                profile_mode=worker.profile_mode,
                profile_intensity=worker.profile_intensity,
                compute_variant=worker.compute_variant,
                buffer_bytes_override=worker.target_vram_bytes,
            )
        if worker.workload == "vram":
            return runner._build_python_vulkan_vram_worker(
                target,
                worker.target_vram_bytes,
                worker.tuning_step,
                result_file or "",
            )
        return worker
    if worker.backend == "python_opencl":
        target = runner._gpu_target_by_id(worker.target_id)
        if worker.workload == "vram":
            return runner._build_python_opencl_vram_worker(
                target,
                worker.target_vram_bytes,
                worker.tuning_step,
                result_file or "",
            )
        return worker
    if worker.backend != "python_egl_gles2":
        return worker
    target = runner._gpu_target_by_id(worker.target_id)
    if worker.workload == "gpu_3d":
        return runner._build_python_gpu_3d_worker(
            target,
            worker.tuning_step,
            result_file or "",
            profile_mode=worker.profile_mode,
            profile_intensity=worker.profile_intensity,
        )
    if worker.workload == "vram":
        return runner._build_python_vram_worker(
            target,
            worker.target_vram_bytes,
            worker.tuning_step,
            result_file or "",
        )
    return worker
