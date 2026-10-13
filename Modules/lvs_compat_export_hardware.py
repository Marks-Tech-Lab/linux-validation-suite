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


def build_platform_thermal_zone_tests(parser_output: dict[str, Any]) -> list[dict[str, Any]]:
    by_zone: dict[tuple[str, str], dict[str, Any]] = {}
    for segment in parser_output.get("Segments", []) if isinstance(parser_output.get("Segments"), list) else []:
        if not isinstance(segment, dict):
            continue
        temperatures = segment.get("Temperatures", {}) if isinstance(segment.get("Temperatures"), dict) else {}
        for zone in temperatures.get("PlatformThermalZones", []) if isinstance(temperatures.get("PlatformThermalZones"), list) else []:
            if not isinstance(zone, dict):
                continue
            identity = (str(zone.get("ZoneId") or ""), str(zone.get("Source") or ""))
            record = by_zone.setdefault(identity, {
                "device": str(zone.get("SensorName") or zone.get("ZoneId") or "Platform thermal zone"),
                "zone_id": identity[0],
                "zone_type": str(zone.get("ZoneType") or ""),
                "source": identity[1],
                "confidence": str(zone.get("Confidence") or "unknown"),
                "threshold_source": str(zone.get("ThresholdSource") or ""),
                "trip_points": list(zone.get("TripPoints") or []),
                "results": {},
            })
            record["results"][str(segment.get("Label") or segment.get("Name") or "Stage")] = {
                "max": (zone.get("Temperatures") or {}).get("Max"),
                "avg": (zone.get("Temperatures") or {}).get("Avg"),
                "min": (zone.get("Temperatures") or {}).get("Min"),
            }
    return [by_zone[key] for key in sorted(by_zone)]


def cpu_temperature_compatibility_name(parser_output: dict[str, Any]) -> tuple[str, str]:
    provenance: dict[str, Any] = {}
    for segment in parser_output.get("Segments", []) if isinstance(parser_output.get("Segments"), list) else []:
        temperatures = segment.get("Temperatures", {}) if isinstance(segment, dict) else {}
        candidate = temperatures.get("CpuProvenance", {}) if isinstance(temperatures, dict) else {}
        if isinstance(candidate, dict) and candidate:
            provenance = candidate
            break
    semantic = str(provenance.get("semantic_classification") or "")
    names = {
        "cpu_package_temperature": "CPU Package (Temperature)",
        "cpu_core_temperature": "CPU Core (Temperature)",
        "cpu_subsystem_temperature": "CPU Subsystem (Temperature)",
    }
    return names.get(semantic, "CPU Temperature (Provenance Unknown)"), semantic or "unknown"


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
    platform_zone_tests = build_platform_thermal_zone_tests(parser_output)
    cpu_temperature_test_name, cpu_temperature_provenance = cpu_temperature_compatibility_name(parser_output)
    cpu_devices["cpu_temperature_provenance"] = cpu_temperature_provenance
    if platform_zone_tests:
        cpu_devices["cpu_temperature_availability"] = (
            "measured" if any(sample.values.get("cpu_temp_c") is not None for sample in samples) else "unavailable"
        )
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
        "Platform": {
            "devices": [
                {key: item[key] for key in ("zone_id", "zone_type", "source", "confidence", "threshold_source", "trip_points")}
                for item in platform_zone_tests
            ],
            "tests": {"Thermal Zone (Temperature)": platform_zone_tests} if platform_zone_tests else {},
        },
        "Gpu": gpu_section,
        "Cpu": {
            "devices": dict(cpu_devices),
            "tests": {
                cpu_temperature_test_name: build_segment_stats_by_device(
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
