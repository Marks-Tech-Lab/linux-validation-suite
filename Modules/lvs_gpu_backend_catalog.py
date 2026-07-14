#!/usr/bin/env python3
"""GPU backend catalog and profile-edit option data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List


GPU_3D_BACKEND_PREFERENCE_OPTIONS = (
    "auto",
    "vulkan",
    "vulkan_compute",
    "egl",
    "opencl",
)

VRAM_BACKEND_PREFERENCE_OPTIONS = (
    "auto",
    "vulkan",
    "opencl",
    "egl",
)


@dataclass(frozen=True)
class GpuBackendAvailabilityContext:
    command_exists: Callable[[str], bool]
    python_runtime_available: Callable[[], bool]
    egl_available: Callable[[], bool]
    opencl_available: Callable[[], bool]
    vulkan_compute_available: Callable[[], bool]
    vulkan_transfer_available: Callable[[], bool]

GPU_3D_BACKEND_CATALOG: Dict[str, Dict[str, Any]] = {
    "glmark2": {
        "display_name": "glmark2",
        "api_family": "OpenGL",
        "kind": "external",
        "suite_scaling_mode": "process_parallel",
        "suite_verification": "telemetry_only",
        "load_class": "external_smoke",
        "test_purpose": "external_smoke_diagnostic",
        "recommended_for_saturation": False,
        "notes": "External OpenGL benchmark/smoke diagnostic. Useful for driver sanity checks, but not a suite stress result.",
    },
    "vkmark": {
        "display_name": "vkmark",
        "api_family": "Vulkan",
        "kind": "external",
        "suite_scaling_mode": "process_parallel",
        "suite_verification": "telemetry_only",
        "load_class": "external_smoke",
        "test_purpose": "external_smoke_diagnostic",
        "recommended_for_saturation": False,
        "notes": "External Vulkan benchmark/smoke diagnostic. It is not a controlled suite stress engine.",
    },
    "vkcube": {
        "display_name": "vkcube",
        "api_family": "Vulkan",
        "kind": "external",
        "suite_scaling_mode": "process_parallel",
        "suite_verification": "telemetry_only",
        "load_class": "compatibility",
        "test_purpose": "external_smoke_diagnostic",
        "recommended_for_saturation": False,
        "notes": "Compatibility fallback for Vulkan presence; not a serious saturation backend by itself.",
    },
    "glxgears": {
        "display_name": "glxgears",
        "api_family": "OpenGL",
        "kind": "external",
        "suite_scaling_mode": "process_parallel",
        "suite_verification": "telemetry_only",
        "load_class": "compatibility",
        "test_purpose": "external_smoke_diagnostic",
        "recommended_for_saturation": False,
        "notes": "Last-resort OpenGL compatibility path only.",
    },
    "python_egl_gles2": {
        "display_name": "Built-in EGL/GLES",
        "api_family": "EGL/GLES2",
        "kind": "internal",
        "suite_scaling_mode": "parametric",
        "suite_verification": "render_readback",
        "load_class": "high_load",
        "test_purpose": "render_validation_fallback",
        "recommended_for_saturation": True,
        "notes": "Suite-controlled render loop with readback verification and safe-mode ramping.",
    },
    "python_opencl_compute": {
        "display_name": "Built-in OpenCL compute",
        "api_family": "OpenCL",
        "kind": "internal",
        "suite_scaling_mode": "parametric",
        "suite_verification": "compute_readback",
        "load_class": "high_load",
        "test_purpose": "compute_validation_fallback",
        "recommended_for_saturation": True,
        "notes": "Suite-controlled compute workload with explicit device selection, verification, and ramping.",
    },
    "python_vulkan_compute": {
        "display_name": "Built-in Vulkan compute",
        "api_family": "Vulkan",
        "kind": "internal",
        "suite_scaling_mode": "parametric",
        "suite_verification": "compute_readback",
        "load_class": "high_load",
        "test_purpose": "suite_native_gpu_stress",
        "recommended_for_saturation": True,
        "notes": "Suite-native Vulkan compute/readback backend. This is the preferred curated GPU stress family when available.",
    },
    "python_vulkan_transfer": {
        "display_name": "Built-in Vulkan transfer",
        "api_family": "Vulkan",
        "kind": "internal",
        "suite_scaling_mode": "parametric",
        "suite_verification": "transfer_readback",
        "load_class": "diagnostic",
        "test_purpose": "transfer_diagnostic",
        "recommended_for_saturation": False,
        "notes": "Suite-controlled Vulkan buffer fill/copy/readback worker. This validates Vulkan routing and memory transfers; it is not a shader/RT saturation workload.",
    },
}

GPU_3D_PREFERENCE_CANDIDATE_MAP: Dict[str, List[str]] = {
    "auto": [
        "python_vulkan_compute",
        "python_egl_gles2",
        "python_opencl_compute",
    ],
    "glmark2": ["glmark2"],
    "vulkan": ["python_vulkan_transfer"],
    "vulkan_compute": ["python_vulkan_compute"],
    "vkmark": ["vkmark"],
    "vkcube": ["vkcube"],
    "egl": ["python_egl_gles2"],
    "opencl": ["python_opencl_compute"],
    "glxgears": ["glxgears"],
}

GPU_3D_INTENSITY_FACTORS: Dict[str, float] = {
    "low": 0.7,
    "medium": 0.85,
    "normal": 0.9,
    "high": 1.0,
    "extreme": 1.15,
    "max": 1.3,
}

OPENCL_COMPUTE_VARIANTS: Dict[str, Dict[str, str]] = {
    "baseline": {
        "display_name": "Baseline deterministic ALU/memory pattern",
        "status": "stable",
        "notes": "Current validated OpenCL compute workload; keep as the safe reference path.",
    },
    "integer_mix": {
        "display_name": "Experimental integer rotation/multiply mix",
        "status": "validated_experimental",
        "notes": "Alternative deterministic compute shape. It previously triggered an amdgpu compute-ring reset on the test host; the current capped envelope has repeated stable 90-second passes and should not be raised without new evidence.",
    },
}

VULKAN_COMPUTE_VARIANTS: Dict[str, Dict[str, str]] = {
    "hash": {
        "display_name": "Deterministic integer hash compute",
        "status": "stable",
        "notes": "Validated Vulkan compute/readback path. This is the safe explicit Vulkan compute baseline.",
    },
    "stress_hash": {
        "display_name": "Heavier deterministic integer hash compute",
        "status": "experimental",
        "notes": "Higher-round Vulkan compute/readback workload for stress characterization. It preserves deterministic verification while using a larger dispatch envelope than the hash baseline.",
    },
    "stateful_memory": {
        "display_name": "Stateful memory read/modify/write",
        "status": "validated_experimental",
        "notes": "Validated experimental Vulkan memory-path workload. It uses deterministic stateful read/modify/write on device-local storage with sampled staging readback verification; keep isolated from auto until broader hardware coverage exists.",
    },
}


def normalize_gpu_3d_backend_preference(preference: Any) -> str:
    normalized = str(preference or "auto").strip().lower() or "auto"
    aliases = {
        "gles": "egl",
        "egl_gles2": "egl",
        "python_egl_gles2": "egl",
        "cl": "opencl",
        "python_opencl_compute": "opencl",
        "vk_transfer": "vulkan",
        "vulkan_transfer": "vulkan",
        "python_vulkan_transfer": "vulkan",
        "vk_compute": "vulkan_compute",
        "vulkan-compute": "vulkan_compute",
        "vulkan compute": "vulkan_compute",
        "python_vulkan_compute": "vulkan_compute",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in GPU_3D_PREFERENCE_CANDIDATE_MAP:
        return normalized
    return "auto"


def normalize_vram_backend_preference(preference: Any) -> str:
    normalized = str(preference or "auto").strip().lower() or "auto"
    aliases = {
        "vk": "vulkan",
        "vulkan_compute": "vulkan",
        "python_vulkan_compute": "vulkan",
        "gles": "egl",
        "egl_gles2": "egl",
        "python_egl_gles2": "egl",
        "cl": "opencl",
        "python_opencl": "opencl",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in VRAM_BACKEND_PREFERENCE_OPTIONS:
        return normalized
    return "auto"


def gpu_3d_backend_load_class(backend: Any) -> str:
    entry = GPU_3D_BACKEND_CATALOG.get(str(backend or ""), {})
    if entry.get("load_class"):
        return str(entry["load_class"])
    return "unknown"


def gpu_3d_backend_catalog_entry(backend: Any) -> Dict[str, Any]:
    backend_name = str(backend or "")
    entry = GPU_3D_BACKEND_CATALOG.get(backend_name, {})
    return {
        "backend": backend_name,
        "display_name": entry.get("display_name", backend_name or "unknown"),
        "api_family": entry.get("api_family", "Unknown"),
        "kind": entry.get("kind", "unknown"),
        "suite_scaling_mode": entry.get("suite_scaling_mode", "unknown"),
        "suite_verification": entry.get("suite_verification", "unknown"),
        "load_class": entry.get("load_class", gpu_3d_backend_load_class(backend_name)),
        "test_purpose": entry.get("test_purpose", "unknown"),
        "recommended_for_saturation": bool(entry.get("recommended_for_saturation", False)),
        "notes": entry.get("notes", ""),
    }


def gpu_3d_backend_candidates_by_preference(preference: Any) -> List[str]:
    normalized = normalize_gpu_3d_backend_preference(preference)
    seen: List[str] = []
    for candidate in GPU_3D_PREFERENCE_CANDIDATE_MAP.get(normalized, GPU_3D_PREFERENCE_CANDIDATE_MAP["auto"]):
        if candidate not in seen:
            seen.append(candidate)
    return seen


def gpu_3d_backend_preference_catalog(preference: Any) -> List[Dict[str, Any]]:
    return [
        gpu_3d_backend_catalog_entry(candidate)
        for candidate in gpu_3d_backend_candidates_by_preference(preference)
    ]


def prefer_graphics_backend_for_mixed_stage(
    *,
    gpu_backend_preference: Any,
    safe_mode_enabled: bool,
    vram_enabled: bool,
    vram_backend_name: str,
) -> bool:
    if not safe_mode_enabled:
        return False
    if not vram_enabled:
        return False
    if normalize_gpu_3d_backend_preference(gpu_backend_preference) != "auto":
        return False
    return str(vram_backend_name or "") == "python_opencl"


def gpu_3d_backend_candidates(
    gpu_backend_preference: Any,
    *,
    prefer_graphics_mixed_stage: bool = False,
) -> List[str]:
    candidates = gpu_3d_backend_candidates_by_preference(gpu_backend_preference)
    if not prefer_graphics_mixed_stage:
        return candidates
    preferred_order = [
        "python_vulkan_compute",
        "python_egl_gles2",
        "python_opencl_compute",
    ]
    return [candidate for candidate in preferred_order if candidate in candidates]


def allow_per_target_auto_gpu_3d_backends(
    *,
    gpu_backend_preference: Any,
    stage_present: bool,
    stage_vram_enabled: bool,
    stage_vram_backend_name: str,
) -> bool:
    if normalize_gpu_3d_backend_preference(gpu_backend_preference) != "auto":
        return False
    if not stage_present:
        return True
    if stage_vram_enabled and str(stage_vram_backend_name or "") == "python_opencl":
        return False
    return True


def vram_backend_candidates(preference: Any) -> List[str]:
    normalized = normalize_vram_backend_preference(preference)
    candidate_map = {
        "auto": ["python_opencl", "python_vulkan_compute", "python_egl_gles2"],
        "vulkan": ["python_vulkan_compute", "python_opencl", "python_egl_gles2"],
        "opencl": ["python_opencl", "python_egl_gles2"],
        "egl": ["python_egl_gles2", "python_opencl"],
    }
    return candidate_map.get(normalized, candidate_map["auto"])


def gpu_3d_backend_available(
    backend: Any,
    *,
    command_exists: Callable[[str], bool],
    python_runtime_available: Callable[[], bool],
    egl_available: Callable[[], bool],
    opencl_available: Callable[[], bool],
    vulkan_compute_available: Callable[[], bool],
    vulkan_transfer_available: Callable[[], bool],
) -> bool:
    backend_name = str(backend or "")
    if backend_name == "glmark2":
        return command_exists("glmark2")
    if backend_name == "vkmark":
        return command_exists("vkmark")
    if backend_name == "vkcube":
        return command_exists("vkcube")
    if backend_name == "python_egl_gles2":
        return bool(python_runtime_available()) and bool(egl_available())
    if backend_name == "python_opencl_compute":
        return bool(python_runtime_available()) and bool(opencl_available())
    if backend_name == "python_vulkan_compute":
        return bool(python_runtime_available()) and bool(vulkan_compute_available())
    if backend_name == "python_vulkan_transfer":
        return bool(python_runtime_available()) and bool(vulkan_transfer_available())
    if backend_name == "glxgears":
        return command_exists("glxgears")
    return False


def vram_backend_available(
    backend: Any,
    *,
    python_runtime_available: Callable[[], bool],
    vulkan_compute_available: Callable[[], bool],
    opencl_available: Callable[[], bool],
    egl_available: Callable[[], bool],
) -> bool:
    backend_name = str(backend or "")
    if backend_name == "python_vulkan_compute":
        return bool(python_runtime_available()) and bool(vulkan_compute_available())
    if backend_name == "python_opencl":
        return bool(python_runtime_available()) and bool(opencl_available())
    if backend_name == "python_egl_gles2":
        return bool(python_runtime_available()) and bool(egl_available())
    return False


def gpu_3d_backend_available_from_context(
    backend: Any,
    context: GpuBackendAvailabilityContext,
) -> bool:
    return gpu_3d_backend_available(
        backend,
        command_exists=context.command_exists,
        python_runtime_available=context.python_runtime_available,
        egl_available=context.egl_available,
        opencl_available=context.opencl_available,
        vulkan_compute_available=context.vulkan_compute_available,
        vulkan_transfer_available=context.vulkan_transfer_available,
    )


def vram_backend_available_from_context(
    backend: Any,
    context: GpuBackendAvailabilityContext,
) -> bool:
    return vram_backend_available(
        backend,
        python_runtime_available=context.python_runtime_available,
        vulkan_compute_available=context.vulkan_compute_available,
        opencl_available=context.opencl_available,
        egl_available=context.egl_available,
    )
