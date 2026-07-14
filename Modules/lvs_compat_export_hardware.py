#!/usr/bin/env python3
"""Compatibility export hardware and non-GPU test section builders."""

from __future__ import annotations

import statistics
from typing import Any

from .lvs_compat_export_helpers import (
    build_cpu_core_frequency_tests,
    build_memory_temperature_tests,
    build_storage_temperature_tests,
    compatibility_cpu_power_limit_value,
)
from .lvs_cpu_topology import cpu_package_devices_from_topology


def build_segment_stats_by_device(
    windows: list[Any],
    samples: list[Any],
    metric_key: str,
    device: str,
) -> list[dict[str, Any]]:
    """Build compatibility min/average/max results for one telemetry metric."""
    result_map: dict[str, dict[str, float | None]] = {}
    for window in windows:
        window_samples = [
            sample
            for sample in samples
            if window.analysis_start <= sample.timestamp <= window.analysis_end
        ]
        values = [
            float(sample.values[metric_key])
            for sample in window_samples
            if sample.values.get(metric_key) is not None
        ]
        result_map[window.display_name] = {
            "max": round(max(values), 2) if values else None,
            "avg": round(statistics.mean(values), 2) if values else None,
            "min": round(min(values), 2) if values else None,
        }
    return [{"device": device, "results": result_map}]


def build_memory_tests(
    parser_output: dict[str, Any],
    windows: list[Any],
    samples: list[Any],
) -> dict[str, Any]:
    tests: dict[str, Any] = {
        "System Memory Used (Usage)": build_segment_stats_by_device(
            windows,
            samples,
            "memory_used_gb",
            "System Memory",
        )
    }
    memory_temp_tests = build_memory_temperature_tests(parser_output.get("Segments", []))
    if memory_temp_tests:
        tests["SPD Hub Temperature (Temperature)"] = memory_temp_tests
    return tests


def build_storage_tests(parser_output: dict[str, Any]) -> dict[str, Any]:
    drive_temp_tests = build_storage_temperature_tests(parser_output.get("Segments", []))
    if not drive_temp_tests:
        return {}
    return {"Drive Temperature (Temperature)": drive_temp_tests}


def build_compatibility_hardware_sections(
    *,
    system_info: dict[str, Any],
    parser_output: dict[str, Any],
    windows: list[Any],
    samples: list[Any],
    cpu_name: str,
    cpu_power_limits: dict[str, Any],
    gpu_section: dict[str, Any],
) -> dict[str, Any]:
    """Build stable compatibility hardware sections while preserving field order."""
    hardware = system_info["Hardware"]
    cpu_info = hardware.get("Cpu", {}) if isinstance(hardware.get("Cpu"), dict) else {}
    cpu_topology = cpu_info.get("Topology", {}) if isinstance(cpu_info.get("Topology"), dict) else {}
    cpu_package_devices = cpu_info.get("PackageDevices")
    if not isinstance(cpu_package_devices, list):
        cpu_package_devices = cpu_package_devices_from_topology(cpu_topology)
    cpu_devices = {
        "cpu_model": cpu_name,
        "aggregate_cpu_model": cpu_name,
        "cpu_topology": cpu_topology,
        "cpu_package_count": cpu_topology.get("PackageCount"),
        "logical_cpu_count": cpu_topology.get("LogicalCpuCount"),
        "physical_core_count": cpu_topology.get("PhysicalCoreCount"),
        "cpu_packages": cpu_topology.get("Packages", []),
        "cpu_package_devices": cpu_package_devices,
        "cpu_package_names": [
            package.get("Name", "")
            for package in cpu_package_devices
            if isinstance(package, dict) and package.get("Name")
        ],
        "amd_ppt": "",
        "power_limit_2": compatibility_cpu_power_limit_value(cpu_power_limits, "short_term"),
        "power_limit_1": compatibility_cpu_power_limit_value(cpu_power_limits, "long_term"),
    }
    return {
        "Memory": {
            "devices": hardware["Memory"].get("Modules", []),
            "summary": hardware["Memory"].get("SpeedSummary", {}),
            "tests": build_memory_tests(parser_output, windows, samples),
        },
        "Storage": {
            "devices": hardware.get("Storage", []),
            "tests": build_storage_tests(parser_output),
        },
        "Gpu": gpu_section,
        "Cpu": {
            "devices": dict(cpu_devices),
            "tests": {
                "CPU Package (Temperature)": build_segment_stats_by_device(
                    windows,
                    samples,
                    "cpu_temp_c",
                    cpu_name,
                ),
                "CPU Package Power (Power)": build_segment_stats_by_device(
                    windows,
                    samples,
                    "cpu_power_w",
                    cpu_name,
                ),
            },
        },
        "CpuCores": {
            "devices": dict(cpu_devices),
            "tests": {
                "Frequency": build_cpu_core_frequency_tests(parser_output.get("Segments", [])),
            },
        },
    }
