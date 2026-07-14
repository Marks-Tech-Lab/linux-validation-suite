#!/usr/bin/env python3
"""Shared final composition for compatibility exports."""

from __future__ import annotations

from typing import Any, Dict, Optional


def finalize_compatibility_export(
    base_output: Dict[str, Any],
    metadata_block: Dict[str, Any],
    export_contract: Dict[str, Any],
    report_summary: Dict[str, Any],
    stability_interpretation: Dict[str, Any],
    system_info: Dict[str, Any],
    parser_output: Dict[str, Any],
    recovery_report: Optional[Dict[str, Any]] = None,
    gpu_power_details: Any = None,
    gpu_validation_details: Any = None,
) -> Dict[str, Any]:
    """Attach shared report mirrors and optional completion details."""
    metadata_block["Stability"]["InterpretationSummary"] = stability_interpretation
    metadata_block["ReportSummary"] = report_summary

    output = dict(base_output)
    output.update(
        {
            "Metadata": metadata_block,
            "ExecutionSummary": metadata_block["ExecutionSummary"],
            "ExportContract": export_contract,
            "ReportSummary": report_summary,
            "report_summary": report_summary,
            "Stability": metadata_block["Stability"],
            "StabilityInterpretation": stability_interpretation,
            "SystemInfo": system_info,
            **parser_output,
        }
    )
    if recovery_report:
        output["Recovery"] = recovery_report

    gpu_details: Dict[str, Any] = {}
    if gpu_power_details:
        gpu_details["power_details"] = gpu_power_details
    if gpu_validation_details:
        gpu_details["validation_details"] = gpu_validation_details
    if gpu_details:
        output["GpuDetails"] = gpu_details
    return output
