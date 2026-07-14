#!/usr/bin/env python3
"""Stage-level GPU backend resolution helpers."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from .lvs_gpu_backend_resolution import gpu_backend_usage_summary

GPU_3D_PREFERENCE_BACKEND_MAP = {
    "glmark2": "glmark2",
    "vulkan": "python_vulkan_transfer",
    "vulkan_compute": "python_vulkan_compute",
    "vkmark": "vkmark",
    "vkcube": "vkcube",
    "egl": "python_egl_gles2",
    "opencl": "python_opencl_compute",
    "glxgears": "glxgears",
}


def build_stage_gpu_backend_diagnostics(
    *,
    stage: Any,
    stage_gpu_target_mode: Callable[[Any], str],
    gpu_targets: Callable[[str], List[Dict[str, Any]]],
    normalize_gpu_3d_backend_preference: Callable[[Any], str],
    normalize_vram_backend_preference: Callable[[Any], str],
    gpu_3d_backend_candidates: Callable[[Any, Any], List[str]],
    vram_backend_candidates: Callable[[Any], List[str]],
    resolve_gpu_backend_for_targets: Callable[..., Dict[str, Any]],
    cpu_backend_name: Callable[[Any], str],
    memory_backend_name: Callable[[Any], str],
) -> Dict[str, Any]:
    modules = stage.modules
    gpu_target_mode = stage_gpu_target_mode(stage)
    selected_gpu_targets = gpu_targets(gpu_target_mode) if gpu_target_mode else []
    gpu_3d_preference = (
        normalize_gpu_3d_backend_preference(modules.gpu_3d.backend_preference)
        if modules.gpu_3d.enabled
        else ""
    )
    vram_preference = (
        normalize_vram_backend_preference(modules.vram.backend_preference)
        if modules.vram.enabled
        else ""
    )
    gpu_3d_targets = gpu_targets(modules.gpu_3d.gpus) if modules.gpu_3d.enabled else []
    vram_targets = gpu_targets(modules.vram.gpus) if modules.vram.enabled else []
    gpu_3d_candidates = gpu_3d_backend_candidates(modules.gpu_3d, stage) if modules.gpu_3d.enabled else []
    vram_candidates = vram_backend_candidates(modules.vram) if modules.vram.enabled else []
    gpu_3d_resolution = (
        resolve_gpu_backend_for_targets(
            candidates=gpu_3d_candidates,
            targets=gpu_3d_targets,
            workload="gpu_3d",
        )
        if modules.gpu_3d.enabled
        else {"backend": "none", "candidate_reports": [], "support": None}
    )
    vram_resolution = (
        resolve_gpu_backend_for_targets(
            candidates=vram_candidates,
            targets=vram_targets,
            workload="vram",
        )
        if modules.vram.enabled
        else {"backend": "none", "candidate_reports": [], "support": None}
    )
    backend_usage = gpu_backend_usage_summary(
        cpu_backend=cpu_backend_name(modules.cpu) if modules.cpu.enabled else "",
        memory_backend=memory_backend_name(modules.memory) if modules.memory.enabled else "",
        gpu_3d_resolution=gpu_3d_resolution,
        vram_resolution=vram_resolution,
        cpu_enabled=modules.cpu.enabled,
        memory_enabled=modules.memory.enabled,
        gpu_3d_enabled=modules.gpu_3d.enabled,
        vram_enabled=modules.vram.enabled,
    )
    return {
        "gpu_target_mode": gpu_target_mode,
        "gpu_targets": selected_gpu_targets,
        "gpu_3d_preference": gpu_3d_preference,
        "vram_preference": vram_preference,
        "gpu_3d_targets": gpu_3d_targets,
        "vram_targets": vram_targets,
        "gpu_3d_candidates": gpu_3d_candidates,
        "vram_candidates": vram_candidates,
        "gpu_3d_resolution": gpu_3d_resolution,
        "vram_resolution": vram_resolution,
        "backend_usage": backend_usage,
    }


def gpu_3d_preference_fallback_warning(
    *,
    enabled: bool,
    preference: str,
    resolved_backend: str,
) -> str:
    if not enabled or not preference or preference == "auto" or resolved_backend == "none":
        return ""
    preferred = GPU_3D_PREFERENCE_BACKEND_MAP.get(preference)
    matched = resolved_backend in preferred if isinstance(preferred, set) else resolved_backend == preferred
    if matched:
        return ""
    return f"3D backend preference '{preference}' is unavailable; falling back to {resolved_backend}"


def vram_preference_fallback_warning(
    *,
    enabled: bool,
    preference: str,
    resolved_backend: str,
) -> str:
    if not enabled or not preference or preference == "auto" or resolved_backend == "none":
        return ""
    preferred = (
        "python_vulkan_compute"
        if preference == "vulkan"
        else ("python_opencl" if preference == "opencl" else "python_egl_gles2")
    )
    if resolved_backend == preferred:
        return ""
    return f"VRAM backend preference '{preference}' is unavailable; falling back to {resolved_backend}"


def gpu_3d_backend_identity_warnings(
    *,
    enabled: bool,
    resolved_backend: str,
    backend_profile: Dict[str, Any],
    gpu_workers: List[Any],
    vulkan_runtime_available: bool,
) -> List[str]:
    if not enabled:
        return []

    warnings: List[str] = []
    backend_load_class = str(backend_profile.get("load_class", "") or "")
    scaling_mode = str(backend_profile.get("suite_scaling_mode", "") or "")
    verification_mode = str(backend_profile.get("suite_verification", "") or "")
    api_family = str(backend_profile.get("api_family", "") or "")
    if resolved_backend != "none":
        warnings.append(
            f"3D backend '{resolved_backend}' is curated as {api_family} / {scaling_mode} / {verification_mode} / purpose={backend_profile.get('test_purpose', 'unknown')}"
        )
        external_worker_counts = [
            int(getattr(worker, "process_count", 0) or 0)
            for worker in gpu_workers
            if getattr(worker, "workload", "") == "gpu_3d" and getattr(worker, "backend", "") == resolved_backend
        ]
        if scaling_mode == "process_parallel" and external_worker_counts:
            warnings.append(
                f"3D backend '{resolved_backend}' is staged with up to {max(external_worker_counts)} supervised process(es) per targeted GPU"
            )
        if resolved_backend in {"vkmark", "vkcube"}:
            if not vulkan_runtime_available:
                warnings.append(
                    "Vulkan runtime inventory is unavailable in the current environment; Vulkan target mapping metadata may be limited even though the backend can still launch"
                )
            resolved_names = [
                str(getattr(worker, "resolved_device_name", "") or "").strip()
                for worker in gpu_workers
                if getattr(worker, "workload", "") == "gpu_3d"
                and getattr(worker, "backend", "") == resolved_backend
                and str(getattr(worker, "resolved_device_name", "") or "").strip()
            ]
            if resolved_names:
                warnings.append(
                    f"Vulkan target mapping resolved to: {', '.join(sorted(dict.fromkeys(resolved_names)))}"
                )
            if any(
                getattr(worker, "selection_ambiguous", False)
                for worker in gpu_workers
                if getattr(worker, "workload", "") == "gpu_3d" and getattr(worker, "backend", "") == resolved_backend
            ):
                warnings.append(
                    "Vulkan device selection is ambiguous for at least one target GPU; runtime routing will rely on Mesa target env hints"
                )
    if backend_load_class == "compatibility":
        warnings.append(
            f"3D stage is using '{resolved_backend}', which is a compatibility-oriented backend and may not fully saturate powerful GPUs"
        )
    elif backend_load_class == "external_smoke":
        warnings.append(
            f"3D stage is using external smoke backend '{resolved_backend}'; this should not be treated as a suite stress result"
        )
    elif backend_load_class == "mixed":
        warnings.append(
            f"3D stage is using '{resolved_backend}', which may behave more like a smoke or benchmark run than a dedicated saturation workload depending on the driver stack"
        )
    elif backend_load_class == "experimental":
        warnings.append(
            f"3D stage is using '{resolved_backend}', which has readback validation but is not yet promoted to the normal saturation path"
        )
    return warnings


def suite_native_gpu_3d_backend_warnings(
    *,
    enabled: bool,
    resolved_backend: str,
    compute_variant: str,
    allocation_percent: int,
    gpu_3d_preference: str,
    selected_opencl_context: str,
    opencl_compute_variants: Dict[str, Dict[str, Any]],
    vulkan_compute_variants: Dict[str, Dict[str, Any]],
) -> List[str]:
    if not enabled:
        return []

    warnings: List[str] = []
    if resolved_backend == "python_egl_gles2":
        warnings.append("3D stage is using the suite-native EGL/GLES render/readback backend")
    if resolved_backend == "python_opencl_compute":
        warnings.append("3D stage is using the built-in OpenCL compute backend")
        warnings.append(f"3D OpenCL compute variant '{compute_variant}' selected")
        variant_meta = opencl_compute_variants.get(compute_variant, {})
        if str(variant_meta.get("status", "") or "").lower() != "stable":
            warnings.append(
                f"3D OpenCL compute variant '{compute_variant}' is experimental; baseline remains the validated production path"
            )
        if selected_opencl_context and selected_opencl_context != "native":
            warnings.append(f"3D OpenCL runtime selected compatibility context '{selected_opencl_context}'")
    if resolved_backend == "python_vulkan_transfer":
        warnings.append("3D stage is using the suite-native Vulkan transfer/readback backend")
        warnings.append(
            "Vulkan transfer/readback validates Vulkan routing and memory movement; it is not yet a shader or ray-tracing saturation workload"
        )
    if resolved_backend == "python_vulkan_compute":
        warnings.append("3D stage is using the suite-native Vulkan compute/readback backend")
        warnings.append(f"3D Vulkan compute variant '{compute_variant}' selected")
        variant_meta = vulkan_compute_variants.get(compute_variant, {})
        if str(variant_meta.get("status", "") or "").lower() != "stable":
            warnings.append(
                f"3D Vulkan compute variant '{compute_variant}' is experimental; hash remains the validated production path"
            )
        if compute_variant == "stateful_memory" and int(allocation_percent or 0) > 0:
            warnings.append(
                "3D Vulkan stateful-memory allocation target is explicitly set to "
                + f"{max(1, min(100, int(allocation_percent)))}% with capacity-based safety reserves"
            )
        if gpu_3d_preference == "auto":
            warnings.append(
                "GPU auto selected the suite-native Vulkan compute/readback family as the preferred curated stress backend"
            )
    return warnings


def vram_backend_warnings(
    *,
    enabled: bool,
    resolved_backend: str,
    selected_opencl_context: str,
) -> List[str]:
    if not enabled:
        return []

    warnings: List[str] = []
    if resolved_backend == "python_opencl":
        warnings.append("VRAM stage is using the built-in OpenCL verification backend")
        if selected_opencl_context and selected_opencl_context != "native":
            warnings.append(f"VRAM OpenCL runtime selected compatibility context '{selected_opencl_context}'")
    if resolved_backend == "python_vulkan_compute":
        warnings.append("VRAM stage is using the suite-native Vulkan stateful-memory/readback backend")
    if resolved_backend == "python_egl_gles2":
        warnings.append("VRAM stage is using the suite-native EGL/GLES render/readback backend")
    return warnings


def opencl_high_headroom_safety_warning(
    *,
    enabled: bool,
    resolved_backend: str,
    safe_mode_enabled: bool,
    target_labels: List[str],
) -> str:
    if not enabled or resolved_backend != "python_opencl_compute" or not safe_mode_enabled or not target_labels:
        return ""
    targets = ", ".join(sorted(dict.fromkeys(target_labels)))
    return (
        "3D OpenCL compute is using a conservative maintained safety cap on higher-headroom AMD discrete targets "
        + f"({targets}) with load=0.9, verify=0.9, "
        + "reduced load-phase buffer fan-out, and slower hot-loop cadence to reduce compute-ring reset risk on current Linux stacks"
    )


def per_target_backend_selection_warning(*, enabled: bool, per_target_backends: List[str]) -> str:
    backends = sorted({str(backend or "") for backend in per_target_backends if str(backend or "")})
    if not enabled or len(backends) <= 1:
        return ""
    return "3D auto mode selected per-target backends for broader and stronger coverage: " + ", ".join(backends)


def mixed_stage_gpu_safety_warnings(
    *,
    gpu_3d_enabled: bool,
    vram_enabled: bool,
    prefer_graphics_backend_for_mixed_stage: bool,
    gpu_3d_backend: str,
    vram_backend: str,
    amd_vulkan_vram_target_labels: List[str],
    fused_vulkan_vram_target_labels: List[str],
    skipped_vram_target_labels: List[str],
) -> List[str]:
    if not gpu_3d_enabled or not vram_enabled:
        return []

    warnings: List[str] = []
    if (
        prefer_graphics_backend_for_mixed_stage
        and vram_backend == "python_opencl"
        and gpu_3d_backend == "python_egl_gles2"
    ):
        warnings.append(
            "Mixed-stage GPU safety is using EGL/GLES for 3D while VRAM uses OpenCL because the preferred Vulkan path was unavailable"
        )
    if gpu_3d_backend == "python_vulkan_compute" and vram_backend == "python_opencl":
        warnings.append(
            "Mixed-stage GPU safety is using the suite-native Vulkan compute backend for 3D while VRAM uses OpenCL where that combination is considered safe"
        )
    if amd_vulkan_vram_target_labels:
        warnings.append(
            "Mixed-stage AMD discrete GPU safety routes VRAM pressure through Vulkan stateful-memory workers on "
            + ", ".join(sorted(dict.fromkeys(amd_vulkan_vram_target_labels)))
            + " instead of OpenCL because simultaneous Vulkan compute plus OpenCL VRAM triggered amdgpu resets on multi-AMD systems"
        )
    if fused_vulkan_vram_target_labels:
        warnings.append(
            "Mixed-stage Vulkan VRAM workers are fused GPU+VRAM stateful-memory workers on "
            + ", ".join(sorted(dict.fromkeys(fused_vulkan_vram_target_labels)))
            + "; separate same-target Vulkan 3D workers are not launched to avoid doubling Vulkan worker pressure"
        )
    if skipped_vram_target_labels:
        warnings.append(
            "Mixed-stage GPU safety suppresses separate concurrent OpenCL VRAM workers on selected targets "
            + f"({', '.join(sorted(dict.fromkeys(skipped_vram_target_labels)))}) because standalone VRAM coverage already runs separately and concurrent 3D+VRAM has triggered driver resets on these target classes"
        )
    if gpu_3d_backend == "python_opencl_compute" and vram_backend == "python_opencl":
        warnings.append(
            "3D and VRAM are both using built-in OpenCL backends in the same stage; this is the highest-risk combination on current Linux driver stacks"
        )
    return warnings


def gpu_safe_mode_worker_warnings(
    *,
    safe_mode_enabled: bool,
    internal_worker_present: bool,
    ramp_start_load_fraction: float,
    ramp_step_seconds: float,
    vram_cap_entries: List[Dict[str, Any]],
) -> List[str]:
    if not safe_mode_enabled:
        return []

    warnings: List[str] = []
    if internal_worker_present:
        warnings.append(
            f"Internal GPU workers will ramp from {ramp_start_load_fraction * 100:.0f}% load over approximately {ramp_step_seconds * 3:.0f}s"
        )
    for entry in vram_cap_entries:
        label = str(entry.get("label") or "GPU")
        requested_bytes = int(entry.get("requested_bytes") or 0)
        capped_bytes = int(entry.get("capped_bytes") or 0)
        warnings.append(
            f"VRAM target for {label} was capped by safe mode from {round(requested_bytes / (1024 ** 3), 2)}GB to {round(capped_bytes / (1024 ** 3), 2)}GB"
        )
    return warnings


def gpu_3d_intensity_warning(
    *,
    enabled: bool,
    resolved_backend: str,
    normalized_intensity: str,
) -> str:
    if not enabled or resolved_backend not in {
        "python_egl_gles2",
        "python_opencl_compute",
        "python_vulkan_transfer",
        "python_vulkan_compute",
    }:
        return ""
    return f"3D intensity '{normalized_intensity}' is shaping suite-native GPU load scaling for this stage"
