from __future__ import annotations

from typing import Any, Optional

from Modules.lvs_gpu_worker_plan import GpuWorkerSpec


def retune_gpu_worker(runner: Any, spec: GpuWorkerSpec) -> Optional[GpuWorkerSpec]:
    if spec.backend not in {"python_egl_gles2", "python_opencl_compute", "python_opencl"}:
        return None
    target = runner._gpu_target_by_id(spec.target_id)
    next_step = spec.tuning_step + 1
    if next_step > runner._gpu_safe_max_tuning_step():
        return None
    if spec.workload == "gpu_3d":
        if spec.backend == "python_opencl_compute":
            return runner._build_python_opencl_compute_worker(
                target,
                next_step,
                profile_mode=spec.profile_mode,
                profile_intensity=spec.profile_intensity,
                compute_variant=spec.compute_variant,
            )
        return runner._build_python_gpu_3d_worker(
            target,
            next_step,
            profile_mode=spec.profile_mode,
            profile_intensity=spec.profile_intensity,
        )
    if spec.workload == "vram":
        target_total = int(target.get("vram_total") or 0) if target else 0
        tuned_target = int(spec.target_vram_bytes * 1.15)
        if target_total > 0:
            tuned_target = min(tuned_target, int(target_total * 0.99))
        tuned_target = runner._cap_gpu_vram_target_bytes(target, tuned_target)
        if spec.backend == "python_opencl":
            return runner._build_python_opencl_vram_worker(target, tuned_target, next_step)
        return runner._build_python_vram_worker(target, tuned_target, next_step)
    return None
