#!/usr/bin/env python3
"""Shared run-context assembly for compatibility exports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .lvs_compat_export_helpers import (
    compatibility_execution_detail,
    compatibility_overall_result,
    run_manually_aborted,
)
from .lvs_cpu_topology import cpu_package_devices_from_topology


def build_compatibility_run_context(
    metadata: Any,
    system_info: Dict[str, Any],
    windows: Iterable[Any],
    skipped_stages: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build shared identity, power-limit, and execution state for an export."""
    window_list = list(windows)
    hardware = system_info["Hardware"]
    cpu_name = hardware["Cpu"]["Name"]
    test_info = system_info.get("TestInfo", {}) if isinstance(system_info.get("TestInfo"), dict) else {}
    test_name = str(test_info.get("TestName") or "")
    profile_display_name = str(test_info.get("ProfileDisplayName") or test_name)
    config_file = str(test_info.get("ConfigFile") or "")
    profile_name = str(test_info.get("ProfileName") or "")
    if not profile_name:
        profile_name = Path(config_file).stem if config_file else profile_display_name.replace(" Linux Validation", "").strip()

    motherboard_info = hardware.get("Motherboard", {})
    bios_info = hardware.get("Bios", {})
    bios_name = bios_info.get("Name", "")
    cpu_info = hardware.get("Cpu", {}) if isinstance(hardware.get("Cpu"), dict) else {}
    cpu_power_limits = cpu_info.get("PowerLimits", {}) if isinstance(cpu_info.get("PowerLimits"), dict) else {}
    cpu_topology = cpu_info.get("Topology", {}) if isinstance(cpu_info.get("Topology"), dict) else {}
    cpu_package_devices = cpu_info.get("PackageDevices")
    if not isinstance(cpu_package_devices, list):
        cpu_package_devices = cpu_package_devices_from_topology(cpu_topology)
    auto_power_limit_data = str(cpu_power_limits.get("PowerLimitData") or "")
    skipped = list(skipped_stages or [])
    all_error_events = [
        event
        for window in window_list
        for event in [*window.error_events, *window.system_faults]
    ]
    manual_abort = run_manually_aborted(window_list)
    overall_result = compatibility_overall_result(window_list, manual_abort=manual_abort)

    return {
        "cpu_name": cpu_name,
        "cpu_topology": cpu_topology,
        "cpu_aggregate": cpu_topology.get("Aggregate", {}) if isinstance(cpu_topology.get("Aggregate"), dict) else {},
        "cpu_package_devices": cpu_package_devices,
        "test_name": test_name,
        "profile_display_name": profile_display_name,
        "profile_name": profile_name,
        "motherboard_name": motherboard_info.get("Product", ""),
        "motherboard_manufacturer": motherboard_info.get("Manufacturer", ""),
        "motherboard_description": motherboard_info.get("Description", ""),
        "motherboard_version": motherboard_info.get("Version", ""),
        "motherboard_system_vendor": motherboard_info.get("SystemVendor", ""),
        "motherboard_board_vendor": motherboard_info.get("BoardVendor", ""),
        "motherboard_board_name": motherboard_info.get("BoardName", ""),
        "bios_name": bios_name,
        "bios_version": bios_info.get("Version", "") or bios_name,
        "bios_full_name": bios_info.get("FullName", "") or bios_name,
        "cpu_power_limits": cpu_power_limits,
        "effective_power_limit_data": metadata.power_limit_data or auto_power_limit_data,
        "effective_amd_ppt": str(cpu_power_limits.get("AmdPpt") or ""),
        "all_error_events": all_error_events,
        "top_level_error_count": sum(
            1 for event in all_error_events if event.get("severity") == "error"
        ),
        "skipped_stages": skipped,
        "skipped_stage_count": len(skipped),
        "executed_stage_count": len(window_list),
        "manual_abort": manual_abort,
        "overall_result": overall_result,
        "execution_detail": compatibility_execution_detail(overall_result, len(skipped)),
    }
