"""One allocation-safety decision; device topology is not memory architecture."""
from __future__ import annotations

import json
import os

ENV_KEY = "LVS_GPU_ALLOCATION_SAFETY"
CONTRACT = "gpu_allocation_safety_v1"


def resolve_gpu_allocation_safety(evidence: dict) -> dict:
    kind = str(evidence.get("memory_kind", evidence.get("gpu_memory_kind", "unknown")) or "unknown").lower()
    source = evidence.get("classification_source", evidence.get("memory_classification_source", ""))
    source = source.strip() if isinstance(source, str) else ""
    confidence = str(evidence.get("classification_confidence", evidence.get("memory_classification_confidence", "low")) or "low").lower()
    capacity = evidence.get("dedicated_vram_capacity_bytes")
    explicit = str(evidence.get("memory_architecture") or evidence.get("MemoryArchitecture") or "").lower()
    conflict = (bool(explicit and explicit != kind) or "conflict" in source.lower()
                or evidence.get("classification_conflict") is True)
    for primary, alternate in (("memory_kind", "gpu_memory_kind"),
                               ("classification_confidence", "memory_classification_confidence"),
                               ("classification_source", "memory_classification_source")):
        if evidence.get(primary) and evidence.get(alternate) and evidence[primary] != evidence[alternate]:
            conflict = True
    dedicated = (kind == "dedicated" and confidence == "high" and bool(source)
                 and source.lower() not in {"unknown", "insufficient_evidence"}
                 and type(capacity) is int and capacity > 0 and not conflict)
    return dict(contract=CONTRACT, memory_kind=kind, classification_source=source,
                classification_confidence=confidence, dedicated_vram_capacity_bytes=capacity if type(capacity) is int else None,
                classification_conflict=conflict,
                device_memory_requires_system_guard=not dedicated,
                host_memory_requires_system_guard=True,
                reason="positively_established_dedicated_memory" if dedicated else "conservative_shared_unknown_or_conflicting_memory")


def runtime_gpu_allocation_safety(encoded: str | None = None) -> dict:
    """Revalidate propagated evidence; a boolean alone cannot authorize exemption."""
    try:
        value = json.loads(os.environ.get(ENV_KEY, "") if encoded is None else encoded)
    except (ValueError, TypeError):
        value = {}
    if not isinstance(value, dict) or value.get("contract") != CONTRACT:
        value = {}
    result = resolve_gpu_allocation_safety(value)
    if value.get("device_memory_requires_system_guard") is not False:
        result["device_memory_requires_system_guard"] = True
    return result


def gpu_assignment_minimum_bytes(backend: str, workload: str) -> int:
    if workload == "vram" and backend in {"python_egl_gles2", "python_opencl"}:
        return 64 * 1024**2
    if backend == "python_vulkan_compute":
        return 8 * 1024**2
    if backend == "python_vulkan_transfer":
        return 16 * 1024**2
    return 0


def validate_gpu_assignment(backend: str, workload: str, target: int) -> int:
    minimum = gpu_assignment_minimum_bytes(backend, workload)
    if type(target) is not int or target < minimum or target < 0:
        raise ValueError(f"GPU allocation configuration infeasible: {backend}/{workload} assignment {target!r} bytes is below backend minimum {minimum} bytes; assignment must not be enlarged")
    return target
