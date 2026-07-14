#!/usr/bin/env python3
"""GPU worker parameter sizing helpers shared by runner/frontends."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def align_down_4096(value: int) -> int:
    return int(value) - (int(value) % 4096)


def gpu_worker_baseline_params(
    target: Optional[Dict[str, Any]],
    *,
    capability: Dict[str, Any],
    backend: str = "",
    workload: str = "gpu_3d",
    normalized_profile_intensity: str = "extreme",
    profile_intensity_factor: float = 1.0,
    profile_mode: str = "steady",
    safe_mode_enabled: bool,
    safe_max_load_scale: float,
) -> Dict[str, Any]:
    vram_total = int(target.get("vram_total") or 0) if target else 0
    if vram_total >= 20 * 1024 ** 3:
        base = {"surface_size": 2048, "draw_count": 256, "shader_iterations": 56, "texture_side": 4096, "clear_passes": 5}
    elif vram_total >= 8 * 1024 ** 3:
        base = {"surface_size": 1536, "draw_count": 192, "shader_iterations": 40, "texture_side": 4096, "clear_passes": 3}
    elif vram_total >= 2 * 1024 ** 3:
        base = {"surface_size": 1280, "draw_count": 144, "shader_iterations": 28, "texture_side": 4096, "clear_passes": 2}
    else:
        base = {"surface_size": 896, "draw_count": 96, "shader_iterations": 20, "texture_side": 2048, "clear_passes": 1}
    capability = dict(capability or {})
    load_scale = float(capability.get("load_scale", 1.0) or 1.0)
    if safe_mode_enabled and backend in {"python_egl_gles2", "python_opencl_compute", "python_opencl"}:
        load_scale = min(load_scale, max(0.75, float(safe_max_load_scale or 1.0)))
    device_class = str(capability.get("device_class", "integrated") or "integrated")
    compute_units = int(capability.get("compute_units", 0) or 0)
    intensity_factor = profile_intensity_factor if workload == "gpu_3d" else 1.0
    mode_factor = 1.0 if str(profile_mode or "").strip().lower() in {"", "steady"} else 0.95
    if workload == "gpu_3d":
        load_scale *= intensity_factor * mode_factor
    high_capacity_target = vram_total >= 1024 ** 3 or device_class == "discrete"
    if workload == "gpu_3d" and high_capacity_target:
        surface_scale = min(2.35, max(0.85, 0.9 + load_scale * 0.3))
        draw_scale = min(5.25, max(1.0, 0.95 + load_scale * 0.95))
        shader_scale = min(4.2, max(0.95, 0.9 + load_scale * 0.72))
        clear_scale = min(3.25, max(1.0, 0.8 + load_scale * 0.5))
    else:
        surface_scale = min(1.7, max(0.8, 0.85 + load_scale * 0.22))
        draw_scale = min(3.5, max(0.9, 0.9 + load_scale * 0.7))
        shader_scale = min(3.0, max(0.9, 0.85 + load_scale * 0.55))
        clear_scale = min(2.5, max(1.0, 0.7 + load_scale * 0.45))
    if backend == "python_opencl_compute":
        if high_capacity_target:
            draw_scale = min(4.4, draw_scale + 0.45)
            shader_scale = min(3.9, shader_scale + 0.35)
        else:
            draw_scale = min(4.0, draw_scale + 0.35)
            shader_scale = min(3.5, shader_scale + 0.25)
    if workload == "vram":
        surface_scale = min(surface_scale, 1.15)
        draw_scale = min(draw_scale, 1.6)
        shader_scale = min(shader_scale, 1.6)
        clear_scale = min(3.0, clear_scale + 0.35)
    if not high_capacity_target and compute_units and compute_units <= 12:
        draw_scale = max(0.75, draw_scale * 0.8)
        shader_scale = max(0.8, shader_scale * 0.85)
    surface_size = int(round(base["surface_size"] * surface_scale / 128.0)) * 128
    draw_count = int(round(base["draw_count"] * draw_scale))
    shader_iterations = int(round(base["shader_iterations"] * shader_scale))
    clear_passes = int(round(base["clear_passes"] * clear_scale))
    texture_side = base["texture_side"]
    if workload == "vram" and vram_total > 0 and vram_total < 2 * 1024 ** 3:
        texture_side = min(texture_side, 2048)
    surface_cap = 4096 if workload == "gpu_3d" and high_capacity_target else 3072
    draw_cap = 2048 if workload == "gpu_3d" and high_capacity_target else 1408
    shader_cap = 320 if workload == "gpu_3d" and high_capacity_target else 224
    return {
        "surface_size": max(768 if workload == "gpu_3d" else 512, min(surface_cap, surface_size)),
        "draw_count": max(32 if workload == "gpu_3d" else 8, min(draw_cap, draw_count)),
        "shader_iterations": max(16 if workload == "gpu_3d" else 12, min(shader_cap, shader_iterations)),
        "texture_side": 4096 if texture_side >= 4096 or load_scale >= 1.2 else texture_side,
        "clear_passes": max(1, min(12, clear_passes)),
        "capability": capability,
        "effective_load_scale": round(load_scale, 2),
        "effective_intensity": normalized_profile_intensity if workload == "gpu_3d" else "",
    }


def gpu_worker_tuned_params(
    base: Dict[str, Any],
    *,
    tuning_step: int = 0,
    backend: str = "",
    workload: str = "gpu_3d",
    safe_mode_enabled: bool,
) -> Dict[str, Any]:
    capability = dict(base.get("capability") or {})
    device_class = str(capability.get("device_class", "integrated") or "integrated")
    vram_total = int(capability.get("vram_total", 0) or 0)
    high_capacity_target = vram_total >= 1024 ** 3 or device_class == "discrete"
    surface_cap = 4352 if workload == "gpu_3d" and high_capacity_target else 3328
    draw_cap = 2304 if workload == "gpu_3d" and high_capacity_target else 1536
    shader_cap = 384 if workload == "gpu_3d" and high_capacity_target else 224
    surface_step = 512 if workload == "gpu_3d" and high_capacity_target else 384
    draw_step = 160 if workload == "gpu_3d" and high_capacity_target else 112
    shader_step = 20 if workload == "gpu_3d" and high_capacity_target else 14
    surface_size = min(surface_cap, base["surface_size"] + tuning_step * surface_step)
    draw_count = min(draw_cap, base["draw_count"] + tuning_step * draw_step)
    shader_iterations = min(shader_cap, base["shader_iterations"] + tuning_step * shader_step)
    clear_passes = min(10, base["clear_passes"] + tuning_step)
    texture_side = 4096 if base["texture_side"] >= 4096 or tuning_step > 0 else base["texture_side"]
    vendor = str(capability.get("vendor", "") or "").strip().lower()
    if (
        safe_mode_enabled
        and backend == "python_egl_gles2"
        and workload == "gpu_3d"
        and vendor == "amd"
        and device_class != "discrete"
    ):
        surface_size = min(surface_size, 1536)
        draw_count = min(draw_count, 112)
        shader_iterations = min(shader_iterations, 48)
        clear_passes = min(clear_passes, 2)
    return {
        "surface_size": surface_size,
        "draw_count": draw_count,
        "shader_iterations": shader_iterations,
        "texture_side": texture_side,
        "clear_passes": clear_passes,
        "capability": capability,
    }


def vulkan_transfer_buffer_bytes(
    target: Optional[Dict[str, Any]],
    params: Dict[str, Any],
    *,
    safe_mode_enabled: bool,
) -> int:
    vram_total = int(target.get("vram_total") or 0) if target else 0
    capability = dict(params.get("capability") or {})
    device_class = str(capability.get("device_class", "") or "")
    load_scale = float(capability.get("load_scale", 1.0) or 1.0)
    if device_class == "discrete":
        base = 192 * 1024 * 1024
    else:
        base = 64 * 1024 * 1024
    if vram_total >= 12 * 1024 ** 3:
        base = 384 * 1024 * 1024
    elif vram_total >= 8 * 1024 ** 3:
        base = 256 * 1024 * 1024
    scaled = int(base * max(0.75, min(1.75, load_scale)))
    if safe_mode_enabled:
        scaled = min(scaled, 384 * 1024 * 1024)
    return max(32 * 1024 * 1024, min(512 * 1024 * 1024, align_down_4096(scaled)))


def vulkan_compute_buffer_bytes(
    target: Optional[Dict[str, Any]],
    params: Dict[str, Any],
    *,
    normalized_variant: str,
    allocation_percent: int = 0,
    safe_mode_enabled: bool,
    cap_gpu_vram_target_bytes: Callable[[Optional[Dict[str, Any]], int], int],
) -> int:
    vram_total = int(target.get("vram_total") or 0) if target else 0
    capability = dict(params.get("capability") or {})
    device_class = str(capability.get("device_class", "") or "")
    load_scale = float(capability.get("load_scale", 1.0) or 1.0)
    if normalized_variant == "stateful_memory":
        percent = max(0, min(100, int(allocation_percent or 0)))
        if vram_total > 0 and percent > 0:
            requested = int(vram_total * (percent / 100.0))
            requested = cap_gpu_vram_target_bytes(target, requested)
            return max(16 * 1024 * 1024, align_down_4096(requested))
        if vram_total <= 0 and percent > 0:
            return 1024 * 1024 * 1024
        if device_class == "discrete":
            if vram_total >= 64 * 1024 ** 3:
                base = 32 * 1024 * 1024 * 1024
                max_cap = 48 * 1024 * 1024 * 1024
            elif vram_total >= 32 * 1024 ** 3:
                base = 6 * 1024 * 1024 * 1024
                max_cap = 12 * 1024 * 1024 * 1024
            elif vram_total >= 24 * 1024 ** 3:
                base = 4 * 1024 * 1024 * 1024
                max_cap = 8 * 1024 * 1024 * 1024
            elif vram_total >= 12 * 1024 ** 3:
                base = 1536 * 1024 * 1024
                max_cap = 3 * 1024 * 1024 * 1024
            elif vram_total >= 8 * 1024 ** 3:
                base = 1024 * 1024 * 1024
                max_cap = 2 * 1024 * 1024 * 1024
            elif vram_total >= 2 * 1024 ** 3:
                base = 1024 * 1024 * 1024
                max_cap = 1536 * 1024 * 1024
            elif vram_total <= 0:
                base = 1024 * 1024 * 1024
                max_cap = 1024 * 1024 * 1024
            else:
                base = 512 * 1024 * 1024
                max_cap = 512 * 1024 * 1024
        else:
            if vram_total >= 8 * 1024 ** 3:
                base = 512 * 1024 * 1024
                max_cap = 1024 * 1024 * 1024
            elif vram_total >= 2 * 1024 ** 3:
                base = 128 * 1024 * 1024
                max_cap = 512 * 1024 * 1024
            else:
                base = 64 * 1024 * 1024
                max_cap = 128 * 1024 * 1024
        scaled = int(base * max(0.75, min(1.5, load_scale)))
        if safe_mode_enabled:
            scaled = min(scaled, max_cap)
        return max(16 * 1024 * 1024, min(max_cap, align_down_4096(scaled)))
    if device_class == "discrete":
        base = 128 * 1024 * 1024
    else:
        base = 32 * 1024 * 1024
    if normalized_variant == "stress_hash":
        if vram_total >= 48 * 1024 ** 3:
            base = 1024 * 1024 * 1024
            max_cap = 1536 * 1024 * 1024
        elif vram_total >= 24 * 1024 ** 3:
            base = 768 * 1024 * 1024
            max_cap = 1024 * 1024 * 1024
        elif vram_total >= 12 * 1024 ** 3:
            base = 512 * 1024 * 1024
            max_cap = 768 * 1024 * 1024
        elif vram_total >= 8 * 1024 ** 3:
            base = 256 * 1024 * 1024
            max_cap = 512 * 1024 * 1024
        elif vram_total >= 4 * 1024 ** 3:
            base = 256 * 1024 * 1024
            max_cap = 384 * 1024 * 1024
        elif vram_total >= 1024 ** 3:
            base = 128 * 1024 * 1024
            max_cap = 256 * 1024 * 1024
        else:
            base = 64 * 1024 * 1024
            max_cap = 128 * 1024 * 1024
        scaled = int(base * max(0.75, min(1.5, load_scale)))
        if safe_mode_enabled:
            scaled = min(scaled, max_cap)
        return max(16 * 1024 * 1024, min(max_cap, align_down_4096(scaled)))
    if vram_total >= 16 * 1024 ** 3:
        base = max(base, 256 * 1024 * 1024)
    elif vram_total >= 8 * 1024 ** 3:
        base = max(base, 192 * 1024 * 1024)
    scaled = int(base * max(0.75, min(1.5, load_scale)))
    if safe_mode_enabled:
        scaled = min(scaled, 1024 * 1024 * 1024 if normalized_variant == "stress_hash" else 256 * 1024 * 1024)
    max_cap = 1536 * 1024 * 1024 if normalized_variant == "stress_hash" else 384 * 1024 * 1024
    return max(16 * 1024 * 1024, min(max_cap, align_down_4096(scaled)))


def vulkan_compute_rounds(
    params: Dict[str, Any],
    *,
    profile_intensity_factor: float,
    normalized_variant: str,
    safe_mode_enabled: bool,
) -> int:
    capability = dict(params.get("capability") or {})
    device_class = str(capability.get("device_class", "") or "")
    load_scale = float(capability.get("load_scale", 1.0) or 1.0)
    if normalized_variant == "stateful_memory":
        base = 5 if device_class == "discrete" else 4
    elif normalized_variant == "stress_hash":
        base = 128 if device_class == "discrete" else 72
    else:
        base = 18 if device_class == "discrete" else 10
    rounds = int(round(base * max(0.85, min(1.35, load_scale * profile_intensity_factor))))
    if safe_mode_enabled:
        if normalized_variant == "stateful_memory":
            rounds = min(rounds, 9 if device_class == "discrete" else 6)
        elif normalized_variant == "stress_hash":
            rounds = min(rounds, 160 if device_class == "discrete" else 96)
        else:
            rounds = min(rounds, 28 if device_class == "discrete" else 16)
    if normalized_variant == "stateful_memory":
        minimum = 3
        maximum = 64
    elif normalized_variant == "stress_hash":
        minimum = 24
        maximum = 192
    else:
        minimum = 6
        maximum = 64
    return max(minimum, min(maximum, rounds))


def vulkan_compute_dispatch_repeats(
    target: Optional[Dict[str, Any]],
    *,
    normalized_variant: str,
) -> int:
    if normalized_variant != "stress_hash":
        return 1
    vram_total = int(target.get("vram_total") or 0) if target else 0
    if vram_total >= 48 * 1024 ** 3:
        return 8
    if vram_total >= 24 * 1024 ** 3:
        return 6
    return 4
