#!/usr/bin/env python3
"""Pure helpers for the legacy-compatible export shape."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .lvs_gpu_export_helpers import normalize_gpu_interface


def compatibility_elapsed_string(seconds: float) -> str:
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def window_has_operator_stop(window: Any) -> bool:
    return any(
        str(event.get("category") or "").strip().lower() == "operator_stop"
        for event in [
            *list(getattr(window, "error_events", []) or []),
            *list(getattr(window, "system_faults", []) or []),
        ]
        if isinstance(event, dict)
    )


def run_manually_aborted(windows: Iterable[Any]) -> bool:
    return any(window_has_operator_stop(window) for window in windows)


def compatibility_overall_result(windows: Iterable[Any], manual_abort: bool | None = None) -> str:
    window_list = list(windows)
    if manual_abort is None:
        manual_abort = run_manually_aborted(window_list)
    if manual_abort:
        return "manually_aborted"
    if any(str(getattr(window, "verdict", "")) == "aborted" for window in window_list):
        return "Aborted"
    if any(str(getattr(window, "verdict", "")) == "fail" for window in window_list):
        return "Failed"
    if any(str(getattr(window, "verdict", "")) == "warning" for window in window_list):
        return "Warning"
    return "Finished"


def compatibility_execution_detail(overall_result: str, skipped_stage_count: int) -> str:
    if str(overall_result) == "Finished" and int(skipped_stage_count or 0) > 0:
        return "FinishedWithSkips"
    return str(overall_result)


def compatibility_cpu_power_limit_value(cpu_power_limits: dict[str, Any], name: str) -> str:
    constraints = cpu_power_limits.get("Constraints") if isinstance(cpu_power_limits, dict) else []
    if not isinstance(constraints, list):
        return ""
    for constraint in constraints:
        if not isinstance(constraint, dict):
            continue
        if str(constraint.get("Name") or "").lower() != str(name or "").lower():
            continue
        value = constraint.get("PowerLimitW")
        if value is None:
            return ""
        try:
            watts = float(value)
        except Exception:
            return ""
        return f"{int(watts) if watts.is_integer() else round(watts, 2):g}W"
    return ""


def gpu_temp_export_name(gpu: dict[str, Any]) -> str:
    name = gpu.get("DisplayName") or gpu.get("Name", "")
    if not name and gpu.get("GpuIndex") is not None:
        name = f"GPU {gpu.get('GpuIndex')}"
    sensor_name = gpu.get("SensorName", "")
    if not sensor_name:
        return str(name or "")
    return f"{name} [{sensor_name}]"


def build_gpu_temp_test(segments: list[dict[str, Any]], bucket: str) -> list[dict[str, Any]]:
    results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        gpus = segment.get("Temperatures", {}).get("Gpu", {}).get(bucket, {}).get("Gpus", [])
        for gpu in gpus:
            if not isinstance(gpu, dict):
                continue
            device_name = gpu_temp_export_name(gpu)
            stats = gpu.get("Temperatures", {})
            if not device_name or not isinstance(stats, dict):
                continue
            results.setdefault(device_name, {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [{"device": device_name, "results": device_results} for device_name, device_results in results.items()]


def build_gpu_metric_test(segments: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        for metric in segment.get("GpuMetrics", []):
            if not isinstance(metric, dict):
                continue
            device_name = metric.get("DisplayName") or metric.get("Name")
            if not device_name and metric.get("GpuIndex") is not None:
                device_name = f"GPU {metric.get('GpuIndex')}"
            stats = metric.get(field, {})
            if not device_name or not isinstance(stats, dict):
                continue
            results.setdefault(str(device_name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [{"device": device_name, "results": device_results} for device_name, device_results in results.items()]


def build_memory_temperature_tests(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    memory_temp_results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        modules = segment.get("Temperatures", {}).get("Memory", {}).get("Modules", [])
        for module in modules:
            if not isinstance(module, dict):
                continue
            device_name = module.get("Name") or module.get("SensorName")
            stats = module.get("Temperatures", {})
            if not device_name or not isinstance(stats, dict):
                continue
            memory_temp_results.setdefault(str(device_name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [
        {"device": device_name, "results": results}
        for device_name, results in memory_temp_results.items()
    ]


def build_storage_temperature_tests(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drive_temp_results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        drives = segment.get("Temperatures", {}).get("Storage", {}).get("Drives", [])
        for drive in drives:
            if not isinstance(drive, dict):
                continue
            device_name = drive.get("DeviceName") or drive.get("Model") or drive.get("SensorName")
            stats = drive.get("Temperatures", {})
            if not device_name or not isinstance(stats, dict):
                continue
            drive_temp_results.setdefault(str(device_name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [
        {"device": device_name, "results": results}
        for device_name, results in drive_temp_results.items()
    ]


def has_core_clock_data(parser_output: dict[str, Any]) -> bool:
    for segment in parser_output.get("Segments", []):
        if isinstance(segment, dict) and segment.get("Clocks", {}).get("Cores"):
            return True
    return False


def has_core_type_data(parser_output: dict[str, Any], core_type: str) -> bool:
    expected = str(core_type or "").upper()
    for segment in parser_output.get("Segments", []):
        if not isinstance(segment, dict):
            continue
        for core in segment.get("Clocks", {}).get("Cores", []):
            if isinstance(core, dict) and str(core.get("CoreType", "") or "").upper() == expected:
                return True
    return False


def build_cpu_core_frequency_tests(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    core_results: dict[str, dict[str, dict[str, float | None]]] = {}
    for segment in segments:
        label = segment.get("TestType", "")
        for core in segment.get("Clocks", {}).get("Cores", []):
            if not isinstance(core, dict):
                continue
            name = core.get("Name")
            stats = core.get("Stats", {})
            if not name or not isinstance(stats, dict):
                continue
            core_results.setdefault(str(name), {})[str(label)] = {
                "max": stats.get("Max"),
                "avg": stats.get("Avg"),
                "min": stats.get("Min"),
            }
    return [{name: results} for name, results in core_results.items()]


def gpu_worker_backend_name(payload: dict[str, Any], *, vulkan_gpu_3d_backend: str = "python_vulkan_transfer") -> str:
    backend = str(payload.get("backend") or "").strip()
    if backend:
        return backend
    mode = str(payload.get("mode") or payload.get("workload") or "").strip().lower()
    if payload.get("renderer"):
        return "python_egl_gles2"
    if payload.get("selected_vulkan_index") is not None:
        return vulkan_gpu_3d_backend if mode == "gpu_3d" else "python_vulkan_transfer"
    if payload.get("selected_opencl_index") is not None or payload.get("platform_name"):
        return "python_opencl_compute" if mode == "gpu_3d" else "python_opencl"
    return ""


def resolve_gpu_worker_device_name(payload: dict[str, Any], gpus: list[dict[str, Any]]) -> str:
    slot = str(payload.get("slot") or payload.get("target_id") or "").strip().lower()
    if slot:
        for gpu in gpus:
            interface = str(gpu.get("Interface") or "").strip().lower()
            if interface == slot:
                return str(gpu.get("DisplayName") or gpu.get("Name") or slot)
    gpu_index = payload.get("gpu_index")
    try:
        index = int(gpu_index)
    except Exception:
        index = None
    if index is not None and 0 <= index < len(gpus):
        return str(gpus[index].get("DisplayName") or gpus[index].get("Name") or f"GPU {index}")
    selected_name = str(payload.get("selected_device_name") or "").strip()
    if selected_name:
        return selected_name
    card = str(payload.get("card") or "").strip()
    if card:
        return card
    renderer = str(payload.get("renderer") or "").strip()
    if renderer:
        return renderer
    return "GPU"


def gpu_source_device_class(source: dict[str, Any], gpus: list[dict[str, Any]]) -> str:
    slot = normalize_gpu_interface(source.get("slot"))
    card = str(source.get("card") or "").strip().lower()
    for gpu in gpus:
        if slot and normalize_gpu_interface(gpu.get("Interface")) == slot:
            return str(gpu.get("DeviceClass") or "").strip().lower()
        if card and str(gpu.get("Card") or "").strip().lower() == card:
            return str(gpu.get("DeviceClass") or "").strip().lower()
    return ""


def should_blank_gpu_power_source(source: dict[str, Any], gpus: list[dict[str, Any]], values: list[Any]) -> bool:
    device_class = gpu_source_device_class(source, gpus)
    if device_class not in {"integrated", "apu"}:
        return False
    numeric_values: list[float] = []
    for value in values:
        try:
            numeric_values.append(float(value))
        except Exception:
            continue
    return bool(numeric_values) and max(numeric_values) < 1.0


def gpu_detail_export_sort_key(item: dict[str, Any], gpus: list[dict[str, Any]]) -> tuple[int, str]:
    name = str(item.get("name") or item.get("DeviceName") or "").strip()
    slot = normalize_gpu_interface(
        item.get("Slot")
        or item.get("ExpectedSlot")
        or item.get("slot")
        or item.get("target_slot")
        or item.get("ExpectedTargetId")
        or item.get("TargetId")
    )
    card = str(item.get("Card") or item.get("ExpectedCard") or item.get("card") or "").strip().lower()
    for index, gpu in enumerate(gpus):
        if slot and normalize_gpu_interface(gpu.get("Interface")) == slot:
            return (index, name)
        if card and str(gpu.get("Card") or "").strip().lower() == card:
            return (index, name)
        if name and name == str(gpu.get("DisplayName") or gpu.get("Name") or ""):
            return (index, name)
    try:
        gpu_index = int(item.get("GpuIndex", item.get("ExpectedGpuIndex", 9999)))
    except Exception:
        gpu_index = 9999
    return (gpu_index, name)


def resolve_gpu_source_device_name(source: dict[str, Any], gpus: list[dict[str, Any]]) -> str:
    slot = normalize_gpu_interface(source.get("slot"))
    if slot:
        for gpu in gpus:
            if normalize_gpu_interface(gpu.get("Interface")) == slot:
                return str(gpu.get("DisplayName") or gpu.get("Name") or slot)
    card = str(source.get("card") or "").strip().lower()
    if not card:
        label = str(source.get("label") or "")
        match = re.search(r"\b(card[0-9]+)\b", label)
        if match is not None:
            card = match.group(1).lower()
    if card:
        for gpu in gpus:
            if str(gpu.get("Card") or "").strip().lower() == card:
                return str(gpu.get("DisplayName") or gpu.get("Name") or card)
    try:
        gpu_index = int(source.get("gpu_index", 0))
    except Exception:
        gpu_index = 0
    if 0 <= gpu_index < len(gpus):
        return str(gpus[gpu_index].get("DisplayName") or gpus[gpu_index].get("Name") or f"GPU {gpu_index}")
    return f"GPU {gpu_index}"
