#!/usr/bin/env python3
"""Shared top-level identity/result envelope for compatibility exports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from .lvs_compat_export_helpers import compatibility_elapsed_string


def build_compatibility_identity_envelope(
    metadata: Any,
    started_iso: str,
    ended_iso: str,
    elapsed_seconds: float,
    context: Dict[str, Any],
    app_version: str,
    *,
    lower_date_text: Optional[str] = None,
    upper_date_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Build stable top-level identity/result fields and motherboard devices."""
    return {
        "serial": metadata.serial,
        "order": metadata.order,
        "dept": metadata.dept,
        "case_sku": metadata.case_sku,
        "description": metadata.description,
        "psu_wattage": metadata.psu_wattage,
        "psu_rating": metadata.psu_rating,
        "power_limit_data": context["effective_power_limit_data"],
        "cpu_cooler": metadata.cpu_cooler,
        "fan_type": metadata.fan_type,
        "fan_details": metadata.fan_details,
        "advanced_debug_logging": bool(getattr(metadata, "advanced_debug_logging", False)),
        "date": lower_date_text if lower_date_text is not None else datetime.now().strftime("%Y-%m-%d"),
        "errors": context["top_level_error_count"],
        "started": started_iso,
        "ended": ended_iso,
        "elapsed": compatibility_elapsed_string(elapsed_seconds),
        "result": context["overall_result"],
        "execution_detail": context["execution_detail"],
        "manual_abort": context["manual_abort"],
        "Serial": metadata.serial,
        "Order": metadata.order,
        "Department": metadata.dept,
        "Case": metadata.case_sku,
        "Description": metadata.description,
        "CombinedDescription": (
            f"{metadata.case_sku}={metadata.description}"
            if metadata.case_sku or metadata.description
            else ""
        ),
        "PsuWattage": metadata.psu_wattage,
        "PsuRating": metadata.psu_rating,
        "PowerLimitData": context["effective_power_limit_data"],
        "AmdPpt": context["effective_amd_ppt"],
        "CpuCooler": metadata.cpu_cooler,
        "FanType": metadata.fan_type,
        "FanDetails": metadata.fan_details,
        "AdvancedDebugLogging": bool(getattr(metadata, "advanced_debug_logging", False)),
        "Date": upper_date_text if upper_date_text is not None else datetime.now().strftime("%Y-%m-%d"),
        "Errors": context["top_level_error_count"],
        "Started": started_iso,
        "Ended": ended_iso,
        "Elapsed": compatibility_elapsed_string(elapsed_seconds),
        "Result": context["overall_result"],
        "ExecutionDetail": context["execution_detail"],
        "ManualAbort": context["manual_abort"],
        "ProfileName": context["profile_name"],
        "source_engine": "linux_runner",
        "source_version": app_version,
        "SourceEngine": "linux_runner",
        "SourceVersion": app_version,
        "Motherboard": {
            "devices": {
                "motherboard_name": context["motherboard_name"],
                "motherboard_manufacturer": context["motherboard_manufacturer"],
                "motherboard_description": context["motherboard_description"],
                "motherboard_version": context["motherboard_version"],
                "motherboard_system_vendor": context["motherboard_system_vendor"],
                "motherboard_board_vendor": context["motherboard_board_vendor"],
                "motherboard_board_name": context["motherboard_board_name"],
                "motherboard_chipset": "",
                "bios_version": context["bios_version"],
                "bios_name": context["bios_name"],
                "bios_full_name": context["bios_full_name"],
            },
            "tests": {},
        },
    }
