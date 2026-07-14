#!/usr/bin/env python3
"""GPU telemetry coverage warning helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


IMPORTANT_GPU_TELEMETRY_METRICS = {"temperature", "power", "busy", "vram_used"}


def gpu_telemetry_coverage_warnings(
    telemetry_capabilities: Dict[str, Any],
    enabled_workloads: Iterable[str],
) -> List[str]:
    if not ({"gpu_3d", "vram"} & set(enabled_workloads)):
        return []
    matrix = ((telemetry_capabilities.get("gpu_telemetry_by_gpu") or {}).get("gpus") or [])
    warnings: List[str] = []
    for gpu in matrix:
        metrics = gpu.get("metrics") if isinstance(gpu.get("metrics"), dict) else {}
        missing = [
            name
            for name, detail in metrics.items()
            if isinstance(detail, dict) and not detail.get("available")
        ]
        available = [
            name
            for name, detail in metrics.items()
            if isinstance(detail, dict) and detail.get("available")
        ]
        if not missing:
            continue
        label = str(gpu.get("slot") or gpu.get("card") or f"GPU {gpu.get('gpu_index')}").strip()
        vendor = str(gpu.get("vendor") or "").strip()
        driver = str(gpu.get("driver") or "").strip()
        missing_important = [name for name in missing if name in IMPORTANT_GPU_TELEMETRY_METRICS]
        available_important = [name for name in available if name in IMPORTANT_GPU_TELEMETRY_METRICS]
        if vendor.lower() == "nvidia" and driver.lower() == "nvidia" and not available_important:
            warnings.append(
                f"GPU telemetry missing for NVIDIA GPU {label}; nvidia-smi does not expose this card, "
                "so temperature/power/utilization/VRAM metrics will be blank. This can indicate a GPU/driver dropout."
            )
        elif missing_important:
            warnings.append(
                f"GPU telemetry partial for GPU {label}; missing {', '.join(missing_important)} metrics will be blank"
            )
    return warnings
