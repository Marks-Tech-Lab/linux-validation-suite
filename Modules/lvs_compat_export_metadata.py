#!/usr/bin/env python3
"""Shared metadata-block assembly for compatibility exports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from .lvs_compat_export_helpers import compatibility_elapsed_string, has_core_type_data
from .lvs_core import now_local_iso


def build_compatibility_metadata_block(
    metadata: Any,
    started_iso: str,
    ended_iso: str,
    elapsed_seconds: float,
    system_info: Dict[str, Any],
    parser_output: Dict[str, Any],
    windows: Iterable[Any],
    context: Dict[str, Any],
    gpu_power_details: Any,
    export_contract: Dict[str, Any],
    recovery_report: Optional[Dict[str, Any]] = None,
    *,
    date_text: Optional[str] = None,
    parsed_datetime: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the stable compatibility metadata block without frontend behavior."""
    window_list = list(windows)
    all_error_events = context["all_error_events"]
    gpus = system_info["Hardware"].get("Gpu", [])
    block = {
        "SerialNumber": metadata.serial,
        "Department": metadata.dept,
        "Date": date_text if date_text is not None else datetime.now().strftime("%Y-%m-%d"),
        "Errors": context["top_level_error_count"],
        "Started": started_iso,
        "Ended": ended_iso,
        "Elapsed": compatibility_elapsed_string(elapsed_seconds),
        "Result": context["overall_result"],
        "ExecutionDetail": context["execution_detail"],
        "ManualAbort": context["manual_abort"],
        "ProfileName": context["profile_name"],
        "ProfileDisplayName": context["profile_display_name"],
        "TestName": context["test_name"],
        "CpuName": context["cpu_name"],
        "CpuAggregateName": context["cpu_name"],
        "CpuTopology": context["cpu_topology"],
        "CpuAggregate": context["cpu_aggregate"],
        "CpuPackageDevices": context["cpu_package_devices"],
        "CpuPackageNames": [
            package.get("Name", "")
            for package in context["cpu_package_devices"]
            if isinstance(package, dict) and package.get("Name")
        ],
        "CpuPackageCount": context["cpu_topology"].get("PackageCount"),
        "CpuLogicalCount": context["cpu_topology"].get("LogicalCpuCount"),
        "CpuPhysicalCoreCount": context["cpu_topology"].get("PhysicalCoreCount"),
        "MotherboardManufacturer": context["motherboard_manufacturer"],
        "MotherboardName": context["motherboard_name"],
        "MotherboardDescription": context["motherboard_description"],
        "MotherboardVersion": context["motherboard_version"],
        "MotherboardSystemVendor": context["motherboard_system_vendor"],
        "MotherboardBoardVendor": context["motherboard_board_vendor"],
        "MotherboardBoardName": context["motherboard_board_name"],
        "BiosVersion": context["bios_version"],
        "BiosName": context["bios_name"],
        "BiosFullName": context["bios_full_name"],
        "HasPCores": has_core_type_data(parser_output, "P"),
        "HasECores": has_core_type_data(parser_output, "E"),
        "HasDGPU": bool(gpus),
        "DgpuName": gpus[0].get("Name", "-") if gpus else "-",
        "DiscreteGpuNames": [gpu.get("Name", "") for gpu in gpus if gpu.get("Name")],
        "MaxWallWattage": metadata.wall_wattage or "-",
        "Case": metadata.case_sku or "-",
        "Description": metadata.description or "-",
        "CombinedDescription": (
            f"{metadata.case_sku}={metadata.description}"
            if metadata.case_sku or metadata.description
            else "-"
        ),
        "PsuWattage": metadata.psu_wattage or "-",
        "PsuRating": metadata.psu_rating or "-",
        "PowerLimitData": context["effective_power_limit_data"] or "-",
        "AmdPpt": context["effective_amd_ppt"] or None,
        "CpuPowerLimits": context["cpu_power_limits"],
        "CpuCooler": metadata.cpu_cooler or "-",
        "FanType": metadata.fan_type or "-",
        "FanDetails": metadata.fan_details or "-",
        "AdvancedDebugLogging": bool(getattr(metadata, "advanced_debug_logging", False)),
        "Notes": metadata.notes or "-",
        "ParsedDateTime": parsed_datetime if parsed_datetime is not None else now_local_iso(),
        "TestConfigFile": system_info.get("TestInfo", {}).get("ConfigFile", ""),
        "ClockDataSource": "linux raw telemetry",
        "GpuPowerDetails": gpu_power_details,
        "CpuInstructionModes": [
            {
                "Segment": window.display_name,
                "Backend": window.cpu_backend or "",
                "Requested": window.cpu_mode_requested or "",
                "Resolved": window.cpu_mode_resolved or "",
                "KernelFlavor": window.cpu_kernel_flavor or "",
                "TuningPolicy": window.cpu_tuning_policy or "",
                "TunedAvgPowerW": window.cpu_tuned_avg_power_w,
            }
            for window in window_list
            if window.cpu_backend
        ],
        "GpuExecutionModes": [
            {
                "Segment": window.display_name,
                "TargetMode": window.gpu_target_mode,
                "Targets": window.gpu_targets,
                "WorkersInitial": window.gpu_workers_initial,
                "WorkersFinal": window.gpu_workers_final,
                "RetuneEvents": window.gpu_retune_events,
            }
            for window in window_list
            if window.gpu_target_mode or window.gpu_workers_initial or window.gpu_workers_final
        ],
        "Stability": {
            "Verdict": context["overall_result"],
            "ManualAbort": context["manual_abort"],
            "ErrorCount": context["top_level_error_count"],
            "WarningCount": sum(
                1 for event in all_error_events if event.get("severity") == "warning"
            ),
            "FailureEvents": all_error_events,
        },
        "ExecutionSummary": {
            "RequestedStageCount": context["executed_stage_count"] + context["skipped_stage_count"],
            "ExecutedStageCount": context["executed_stage_count"],
            "SkippedStageCount": context["skipped_stage_count"],
            "SkippedStages": context["skipped_stages"],
        },
        "ExportContract": export_contract,
    }
    if recovery_report:
        block["GpuRecovery"] = {
            "UncleanMarkerPresent": bool(recovery_report.get("unclean_marker_present")),
            "PreviousBootFaultSummary": recovery_report.get("previous_boot_fault_summary", {}),
        }
    return block
