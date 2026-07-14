from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GpuWorkerSpec:
    workload: str
    backend: str
    gpu_index: int
    card: str
    slot: str
    target_id: str
    command: List[str]
    env_overrides: Dict[str, str] = field(default_factory=dict)
    draw_count: int = 0
    shader_iterations: int = 0
    surface_size: int = 0
    target_vram_bytes: int = 0
    texture_side: int = 0
    clear_passes: int = 0
    tuning_step: int = 0
    backend_api_family: str = ""
    suite_scaling_mode: str = ""
    suite_verification: str = ""
    process_count: int = 0
    resolved_device_name: str = ""
    selection_ambiguous: bool = False
    device_class: str = ""
    profile_mode: str = ""
    profile_intensity: str = ""
    compute_variant: str = ""


def serialize_gpu_worker_spec(worker: GpuWorkerSpec) -> Dict[str, Any]:
    return {
        "workload": worker.workload,
        "backend": worker.backend,
        "backend_api_family": worker.backend_api_family,
        "suite_scaling_mode": worker.suite_scaling_mode,
        "suite_verification": worker.suite_verification,
        "profile_mode": worker.profile_mode,
        "profile_intensity": worker.profile_intensity,
        "process_count": worker.process_count,
        "resolved_device_name": worker.resolved_device_name,
        "selection_ambiguous": worker.selection_ambiguous,
        "compute_variant": worker.compute_variant,
        "gpu_index": worker.gpu_index,
        "card": worker.card,
        "slot": worker.slot,
        "target_id": worker.target_id,
        "surface_size": worker.surface_size,
        "draw_count": worker.draw_count,
        "shader_iterations": worker.shader_iterations,
        "target_vram_bytes": worker.target_vram_bytes,
        "texture_side": worker.texture_side,
        "clear_passes": worker.clear_passes,
        "tuning_step": worker.tuning_step,
    }
