from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    gpu_memory_kind: str = "unknown"
    memory_classification_source: str = ""
    memory_capacity_source: str = ""
    dedicated_vram_capacity_bytes: int = 0
    shared_addressable_capacity_bytes: int = 0
    shared_addressable_capacity_status: str = "unknown"
    api_addressable_capacity_bytes: int = 0
    api_addressable_capacity_source: str = ""
    backend_addressable_capacity_bytes: int = 0
    backend_addressable_capacity_source: str = ""
    backend_addressable_capacity_status: str = "unknown"
    total_capacity_trust: str = "unknown"
    system_memory_pool_ceiling_bytes: int = 0
    max_single_allocation_bytes: int = 0
    max_single_allocation_source: str = ""
    max_buffer_or_object_bytes: int = 0
    max_buffer_or_object_source: str = ""
    max_allocation_count: int = 0
    max_allocation_count_source: str = ""
    allocation_granularity_bytes: int = 1
    planned_allocation_chunks: List[int] = field(default_factory=list)
    planned_allocation_chunk_count: int = 0
    reported_vram_total_bytes: int = 0
    reported_vram_total_semantics: str = "unknown"
    ambiguous_integrated_vram_report_bytes: int = 0
    current_gpu_memory_used_bytes: Optional[int] = None
    current_gpu_memory_used_source: str = ""
    current_gpu_memory_available_bytes: Optional[int] = None
    current_gpu_memory_available_source: str = ""
    firmware_preallocated_or_stolen_bytes: Optional[int] = None
    firmware_preallocated_or_stolen_source: str = ""
    requested_gpu_memory_target_bytes: int = 0
    requested_gpu_memory_percent: int = 0
    planned_gpu_memory_target_bytes: int = 0
    system_memory_budget_participation: bool = False
    system_memory_commitment_multiplier: int = 1
    system_memory_fixed_commitment_bytes: int = 0
    memory_budget_consumer_id: str = ""
    memory_budgetability: str = ""
    target_cap_reason: str = ""
    minimum_viable_allocation_bytes: int = 0
    minimum_viable_allocation_source: str = ""


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
        "gpu_memory_kind": worker.gpu_memory_kind,
        "memory_classification_source": worker.memory_classification_source,
        "memory_capacity_source": worker.memory_capacity_source,
        "dedicated_vram_capacity_bytes": worker.dedicated_vram_capacity_bytes,
        "shared_addressable_capacity_bytes": worker.shared_addressable_capacity_bytes,
        "shared_addressable_capacity_status": worker.shared_addressable_capacity_status,
        "api_addressable_capacity_bytes": worker.api_addressable_capacity_bytes,
        "api_addressable_capacity_source": worker.api_addressable_capacity_source,
        "backend_addressable_capacity_bytes": worker.backend_addressable_capacity_bytes,
        "backend_addressable_capacity_source": worker.backend_addressable_capacity_source,
        "backend_addressable_capacity_status": worker.backend_addressable_capacity_status,
        "total_capacity_trust": worker.total_capacity_trust,
        "system_memory_pool_ceiling_bytes": worker.system_memory_pool_ceiling_bytes,
        "max_single_allocation_bytes": worker.max_single_allocation_bytes,
        "max_single_allocation_source": worker.max_single_allocation_source,
        "max_buffer_or_object_bytes": worker.max_buffer_or_object_bytes,
        "max_buffer_or_object_source": worker.max_buffer_or_object_source,
        "max_allocation_count": worker.max_allocation_count,
        "max_allocation_count_source": worker.max_allocation_count_source,
        "allocation_granularity_bytes": worker.allocation_granularity_bytes,
        "planned_allocation_chunks": list(worker.planned_allocation_chunks),
        "planned_allocation_chunk_count": worker.planned_allocation_chunk_count,
        "reported_vram_total_bytes": worker.reported_vram_total_bytes,
        "reported_vram_total_semantics": worker.reported_vram_total_semantics,
        "ambiguous_integrated_vram_report_bytes": worker.ambiguous_integrated_vram_report_bytes,
        "current_gpu_memory_used_bytes": worker.current_gpu_memory_used_bytes,
        "current_gpu_memory_used_source": worker.current_gpu_memory_used_source,
        "current_gpu_memory_available_bytes": worker.current_gpu_memory_available_bytes,
        "current_gpu_memory_available_source": worker.current_gpu_memory_available_source,
        "firmware_preallocated_or_stolen_bytes": worker.firmware_preallocated_or_stolen_bytes,
        "firmware_preallocated_or_stolen_source": worker.firmware_preallocated_or_stolen_source,
        "requested_gpu_memory_target_bytes": worker.requested_gpu_memory_target_bytes,
        "requested_gpu_memory_percent": worker.requested_gpu_memory_percent,
        "planned_gpu_memory_target_bytes": worker.planned_gpu_memory_target_bytes,
        "system_memory_budget_participation": worker.system_memory_budget_participation,
        "system_memory_commitment_multiplier": worker.system_memory_commitment_multiplier,
        "system_memory_fixed_commitment_bytes": worker.system_memory_fixed_commitment_bytes,
        "memory_budget_consumer_id": worker.memory_budget_consumer_id,
        "memory_budgetability": worker.memory_budgetability,
        "target_cap_reason": worker.target_cap_reason,
        "minimum_viable_allocation_bytes": worker.minimum_viable_allocation_bytes,
        "minimum_viable_allocation_source": worker.minimum_viable_allocation_source,
    }
