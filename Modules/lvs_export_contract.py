#!/usr/bin/env python3
"""Compatibility export contract metadata."""

from __future__ import annotations

from typing import Any, Dict, List


PARSER_FACING_STABLE_FIELDS = [
    "Segments",
    "SegmentDetails",
    "Metadata",
    "SystemInfo",
    "Motherboard",
    "Memory",
    "Storage",
    "Gpu",
    "Cpu",
    "CpuCores",
]


def build_export_contract(app_name: str, app_version: str) -> Dict[str, Any]:
    """Return the parser-safe additive export contract block."""

    return {
        "Schema": "linux_validation_suite.compat_export.v1",
        "Producer": app_name,
        "ProducerVersion": app_version,
        "ReferenceProject": "Legacy compatibility schema",
        "ReferenceExporter": "CustomResultExporter",
        "ReferenceImporter": "Legacy compatibility importer",
        "CompatibilityMode": "legacy_additive",
        "ParserSafeAdditiveFields": True,
        "RequiresLegacyImporterUpdate": False,
        "Policy": "Preserve existing compatibility fields; add Linux-specific report fields without changing current importer assumptions.",
        "StableConsumerFields": [
            "Segments",
            "SegmentDetails",
            "GpuDetails.power_details",
            "Metadata",
            "SystemInfo",
            "Motherboard",
            "Memory",
            "Storage",
            "Gpu",
            "Cpu",
            "CpuCores",
        ],
        "AdditiveLinuxFields": [
            "ReportSummary",
            "report_summary",
            "Metadata.ReportSummary",
            "ReportSummary.ActionItemDetails",
            "ReportSummary.ActionItemCategoryCounts",
            "ReportSummary.ActionItemSeverityCounts",
            "ReportSummary.StageOutcomes[].GpuHighlights",
            "ReportSummary.StageOutcomes[].IntelGpuTopSidecar",
            "Metadata.ExportContract",
            "ExportContract",
            "StabilityInterpretation",
            "Segments[].StabilityInterpretation",
            "Segments[].GpuExecution",
            "Segments[].IntelGpuTopSidecar",
            "Segments[].GpuExecution.IntelGpuTopSidecar",
            "GpuDetails.validation_details",
        ],
        "DeferredImporterWork": [
            "Optional sheet columns for ReportSummary.OutcomeClass",
            "Optional sheet columns for warning/error category counts",
            "Optional sheet columns for ReportSummary.ActionItems",
            "Optional sheet columns for ReportSummary.ActionItemSeverityCounts",
            "Optional sheet columns for per-stage targeted GPU counts",
            "Optional sheet columns for per-stage GPU highlight telemetry",
        ],
    }


def validate_export_contract_compatibility(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Validate parser-facing compatibility fields and export contract mirrors."""

    parsed = parsed if isinstance(parsed, dict) else {}
    issues: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}

    missing_stable = [field for field in PARSER_FACING_STABLE_FIELDS if field not in parsed]
    if missing_stable:
        issues.append(
            {
                "severity": "error",
                "category": "compatibility_shape",
                "message": "Missing parser-facing compatibility fields",
                "details": {"missing": missing_stable},
            }
        )
    checks["stable_consumer_fields"] = {
        "required": list(PARSER_FACING_STABLE_FIELDS),
        "missing": missing_stable,
        "ok": not missing_stable,
    }

    metadata = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
    export_contract = parsed.get("ExportContract")
    metadata_contract = metadata.get("ExportContract") if isinstance(metadata, dict) else None
    contract_ok = isinstance(export_contract, dict) and isinstance(metadata_contract, dict)
    if not contract_ok:
        issues.append(
            {
                "severity": "warning",
                "category": "export_contract",
                "message": "ExportContract is missing at top level or Metadata.ExportContract",
                "details": {},
            }
        )
    elif export_contract.get("RequiresLegacyImporterUpdate") is not False:
        issues.append(
            {
                "severity": "error",
                "category": "export_contract",
                "message": "ExportContract must keep RequiresLegacyImporterUpdate=false for current importer compatibility",
                "details": {"RequiresLegacyImporterUpdate": export_contract.get("RequiresLegacyImporterUpdate")},
            }
        )
    checks["export_contract"] = {
        "top_level_present": isinstance(export_contract, dict),
        "metadata_present": isinstance(metadata_contract, dict),
        "compatibility_mode": export_contract.get("CompatibilityMode") if isinstance(export_contract, dict) else None,
        "requires_legacy_importer_update": export_contract.get("RequiresLegacyImporterUpdate") if isinstance(export_contract, dict) else None,
        "ok": contract_ok and export_contract.get("RequiresLegacyImporterUpdate") is False,
    }
    return {"checks": checks, "issues": issues}
