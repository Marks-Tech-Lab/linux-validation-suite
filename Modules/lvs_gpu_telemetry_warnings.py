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
        query_errors = [
            name for name in missing_important
            if str((metrics.get(name) or {}).get("measurement_status") or "") == "query_error"
        ]
        if vendor.lower() == "nvidia" and driver.lower() == "nvidia" and not available_important:
            if query_errors:
                warnings.append(
                    f"GPU telemetry query failed for NVIDIA GPU {label}; "
                    "temperature/power/utilization/VRAM metrics may be blank. This can indicate a provider or GPU/driver dropout."
                )
            else:
                warnings.append(
                    f"GPU telemetry unavailable for NVIDIA GPU {label}; nvidia-smi exposed the device but no important metrics, "
                    "so temperature/power/utilization/VRAM metrics will be blank"
                )
        elif missing_important:
            unavailable = [
                name for name in missing_important
                if str((metrics.get(name) or {}).get("measurement_status") or "") == "unavailable"
            ]
            qualifier = "unavailable" if unavailable else "missing"
            warnings.append(
                f"GPU telemetry partial for GPU {label}; {qualifier} {', '.join(missing_important)} metrics will be blank"
            )
    return warnings
