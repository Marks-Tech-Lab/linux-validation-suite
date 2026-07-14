#!/usr/bin/env python3
"""Shared compatibility export document assembly."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .lvs_compat_export_context import build_compatibility_run_context
from .lvs_compat_export_envelope import build_compatibility_identity_envelope
from .lvs_compat_export_finalizer import finalize_compatibility_export
from .lvs_compat_export_hardware import build_compatibility_hardware_sections
from .lvs_compat_export_metadata import build_compatibility_metadata_block
from .lvs_report_helpers import build_overall_stability_interpretation, build_report_summary


def build_compatibility_export_document(
    *,
    metadata: Any,
    started_iso: str,
    ended_iso: str,
    elapsed_seconds: float,
    system_info: Dict[str, Any],
    parser_output: Dict[str, Any],
    windows: list[Any],
    samples: list[Any],
    app_version: str,
    export_contract: Dict[str, Any],
    gpu_section: Dict[str, Any],
    gpu_power_details: Any = None,
    gpu_validation_details: Any = None,
    recovery_report: Optional[Dict[str, Any]] = None,
    skipped_stages: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the complete compatibility export from normalized inputs."""
    context = build_compatibility_run_context(metadata, system_info, windows, skipped_stages)
    overall_result = context["overall_result"]
    execution_detail = context["execution_detail"]
    metadata_block = build_compatibility_metadata_block(
        metadata,
        started_iso,
        ended_iso,
        elapsed_seconds,
        system_info,
        parser_output,
        windows,
        context,
        gpu_power_details,
        export_contract,
        recovery_report,
    )
    stability_interpretation = build_overall_stability_interpretation(
        overall_result,
        parser_output.get("Segments", []),
    )
    report_summary = build_report_summary(
        overall_result=overall_result,
        execution_detail=execution_detail,
        elapsed=metadata_block["Elapsed"],
        segments=parser_output.get("Segments", []),
        stability_interpretation=stability_interpretation,
        all_error_events=context["all_error_events"],
        gpu_validation_details=gpu_validation_details,
        skipped_stages=context["skipped_stages"],
    )
    hardware_sections = build_compatibility_hardware_sections(
        system_info=system_info,
        parser_output=parser_output,
        windows=windows,
        samples=samples,
        cpu_name=context["cpu_name"],
        cpu_power_limits=context["cpu_power_limits"],
        gpu_section=gpu_section,
    )
    base_output = {
        **build_compatibility_identity_envelope(
            metadata,
            started_iso,
            ended_iso,
            elapsed_seconds,
            context,
            app_version,
        ),
        **hardware_sections,
    }
    return finalize_compatibility_export(
        base_output,
        metadata_block,
        export_contract,
        report_summary,
        stability_interpretation,
        system_info,
        parser_output,
        recovery_report,
        gpu_power_details,
        gpu_validation_details,
    )
