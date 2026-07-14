#!/usr/bin/env python3
"""Parsed result/report payload validation helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .lvs_export_contract import validate_export_contract_compatibility
from .lvs_report_helpers import (
    validate_gpu_worker_summary,
    validate_report_action_items,
    validate_report_stage_counts,
    validate_report_summary_mirror,
    validate_stability_alignment,
)


def _add_issue(
    issues: List[Dict[str, Any]],
    severity: str,
    category: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    issues.append(
        {
            "severity": severity,
            "category": category,
            "message": message,
            "details": details or {},
        }
    )


def validate_parsed_report_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}

    export_contract_validation = validate_export_contract_compatibility(parsed)
    checks.update(export_contract_validation.get("checks", {}))
    issues.extend(export_contract_validation.get("issues", []))

    report_summary_validation = validate_report_summary_mirror(parsed)
    checks.update(report_summary_validation.get("checks", {}))
    issues.extend(report_summary_validation.get("issues", []))
    report_summary = report_summary_validation.get("report_summary", {})

    stability_validation = validate_stability_alignment(parsed, report_summary)
    checks.update(stability_validation.get("checks", {}))
    issues.extend(stability_validation.get("issues", []))

    stage_count_validation = validate_report_stage_counts(parsed, report_summary)
    checks.update(stage_count_validation.get("checks", {}))
    issues.extend(stage_count_validation.get("issues", []))
    segments = stage_count_validation.get("segments", [])
    segment_details = stage_count_validation.get("segment_details", {})
    stage_outcomes = stage_count_validation.get("stage_outcomes", [])

    gpu_highlight_count = 0
    gpu_highlight_mapping_warning_count = 0
    stage_alignment_warning_count = 0
    for index, stage in enumerate(stage_outcomes, start=1):
        if not isinstance(stage, dict):
            _add_issue(issues, "warning", "gpu_highlights", f"Stage outcome {index} is not an object")
            continue
        label = stage.get("Label") or stage.get("Stage") or f"stage_{index}"
        segment = segments[index - 1] if 0 <= index - 1 < len(segments) and isinstance(segments[index - 1], dict) else {}
        segment_label = segment.get("Label") or segment.get("TestDescription") or segment.get("TestType") or ""
        if segment_label and str(label) != str(segment_label):
            stage_alignment_warning_count += 1
            _add_issue(
                issues,
                "warning",
                "stage_alignment",
                f"Stage outcome {index} label does not match segment label",
                {"stage_outcome": label, "segment": segment_label},
            )
        if segment:
            for stage_field, segment_field, display_name in (
                ("TestType", "TestType", "TestType"),
                ("Verdict", "Verdict", "Verdict"),
            ):
                if stage.get(stage_field) is not None and segment.get(segment_field) is not None and stage.get(stage_field) != segment.get(segment_field):
                    stage_alignment_warning_count += 1
                    _add_issue(
                        issues,
                        "warning",
                        "stage_alignment",
                        f"{label} StageOutcomes.{display_name} does not match segment {display_name}",
                        {"stage_outcome": stage.get(stage_field), "segment": segment.get(segment_field)},
                    )
        interpretation = segment.get("StabilityInterpretation") if isinstance(segment.get("StabilityInterpretation"), dict) else {}
        if interpretation:
            for field_name in ("OutcomeClass", "OutcomeSummary", "PrimaryPurpose", "BackendConfidence"):
                if stage.get(field_name) is not None and interpretation.get(field_name) is not None and stage.get(field_name) != interpretation.get(field_name):
                    stage_alignment_warning_count += 1
                    _add_issue(
                        issues,
                        "warning",
                        "stage_alignment",
                        f"{label} StageOutcomes.{field_name} does not match segment StabilityInterpretation.{field_name}",
                        {"stage_outcome": stage.get(field_name), "segment": interpretation.get(field_name)},
                    )
            for field_name in ("WarningCategoryCounts", "ErrorCategoryCounts", "TargetedLoadQualityCounts"):
                stage_counts = stage.get(field_name) if isinstance(stage.get(field_name), dict) else {}
                segment_counts = interpretation.get(field_name) if isinstance(interpretation.get(field_name), dict) else {}
                if stage_counts != segment_counts:
                    stage_alignment_warning_count += 1
                    _add_issue(
                        issues,
                        "warning",
                        "stage_alignment",
                        f"{label} StageOutcomes.{field_name} does not match segment StabilityInterpretation.{field_name}",
                        {"stage_outcome": stage_counts, "segment": segment_counts},
                    )
            recommendations = interpretation.get("ThresholdRecommendations") if isinstance(interpretation.get("ThresholdRecommendations"), dict) else {}
            if recommendations:
                try:
                    stage_threshold_count = int(stage.get("ReportOnlyThresholdWouldWarnCount") or 0)
                except Exception:
                    stage_threshold_count = -1
                try:
                    segment_threshold_count = int(recommendations.get("WouldWarnCount") or 0)
                except Exception:
                    segment_threshold_count = -1
                if stage_threshold_count != segment_threshold_count:
                    stage_alignment_warning_count += 1
                    _add_issue(
                        issues,
                        "warning",
                        "stage_alignment",
                        f"{label} ReportOnlyThresholdWouldWarnCount does not match segment threshold recommendations",
                        {"stage_outcome": stage_threshold_count, "segment": segment_threshold_count},
                    )
        segment_gpu_metrics = segment.get("GpuMetrics") if isinstance(segment.get("GpuMetrics"), list) else []
        targeted_metric_count = sum(1 for metric in segment_gpu_metrics if isinstance(metric, dict) and bool(metric.get("Targeted")))
        targeted_count_value = stage.get("TargetedGpuCount")
        if segment_gpu_metrics and targeted_count_value is not None:
            try:
                targeted_count_int = int(targeted_count_value)
            except Exception:
                targeted_count_int = -1
            if targeted_count_int != targeted_metric_count:
                stage_alignment_warning_count += 1
                _add_issue(
                    issues,
                    "warning",
                    "stage_alignment",
                    f"{label} TargetedGpuCount does not match targeted Segment.GpuMetrics entries",
                    {"stage_outcome": targeted_count_int, "segment_gpu_metrics": targeted_metric_count},
                )
        highlights = stage.get("GpuHighlights")
        if highlights is None:
            if targeted_metric_count > 0:
                stage_alignment_warning_count += 1
                _add_issue(
                    issues,
                    "warning",
                    "stage_alignment",
                    f"{label} has targeted Segment.GpuMetrics entries but no GpuHighlights",
                    {"segment_gpu_metrics": targeted_metric_count},
                )
            continue
        if not isinstance(highlights, list):
            _add_issue(
                issues,
                "warning",
                "gpu_highlights",
                f"{label} GpuHighlights is not a list",
            )
            continue
        gpu_highlight_count += len(highlights)
        if targeted_metric_count > 0 and len(highlights) != targeted_metric_count:
            stage_alignment_warning_count += 1
            _add_issue(
                issues,
                "warning",
                "stage_alignment",
                f"{label} GpuHighlights count does not match targeted Segment.GpuMetrics entries",
                {"gpu_highlights": len(highlights), "segment_gpu_metrics": targeted_metric_count},
            )
        targeted_count = stage.get("TargetedGpuCount")
        if targeted_count is not None:
            try:
                targeted_int = int(targeted_count)
            except Exception:
                targeted_int = -1
            if targeted_int >= 0 and len(highlights) > targeted_int:
                _add_issue(
                    issues,
                    "warning",
                    "gpu_highlights",
                    f"{label} has more GPU highlights than targeted GPUs",
                    {"targeted_gpu_count": targeted_int, "gpu_highlights": len(highlights)},
                )
        for highlight_index, highlight in enumerate(highlights, start=1):
            if not isinstance(highlight, dict):
                _add_issue(
                    issues,
                    "warning",
                    "gpu_highlights",
                    f"{label} GPU highlight {highlight_index} is not an object",
                )
                continue
            if not str(highlight.get("Name") or "").strip() and highlight.get("GpuIndex") is None:
                _add_issue(
                    issues,
                    "warning",
                    "gpu_highlights",
                    f"{label} GPU highlight {highlight_index} is missing Name/GpuIndex",
                )
            if highlight.get("UsageAvg") is None and highlight.get("UsageMax") is None:
                _add_issue(
                    issues,
                    "warning",
                    "gpu_highlights",
                    f"{label} GPU highlight {highlight_index} is missing busy telemetry",
                )
            list_mapping_fields = ("TargetIds", "Cards", "Slots", "Workloads", "Backends")
            mapping_present = False
            for field_name in list_mapping_fields:
                value = highlight.get(field_name)
                if value is None:
                    continue
                if not isinstance(value, list):
                    gpu_highlight_mapping_warning_count += 1
                    _add_issue(
                        issues,
                        "warning",
                        "gpu_highlights",
                        f"{label} GPU highlight {highlight_index} has non-list {field_name}",
                        {"value": value},
                    )
                    continue
                if any(str(item).strip() for item in value):
                    mapping_present = True
            if not mapping_present:
                gpu_highlight_mapping_warning_count += 1
                _add_issue(
                    issues,
                    "warning",
                    "gpu_highlights",
                    f"{label} GPU highlight {highlight_index} is missing target/backend mapping",
                )
            load_quality = highlight.get("LoadQuality")
            if load_quality is not None and not str(load_quality).strip():
                gpu_highlight_mapping_warning_count += 1
                _add_issue(
                    issues,
                    "warning",
                    "gpu_highlights",
                    f"{label} GPU highlight {highlight_index} has blank LoadQuality",
                )
            telemetry_missing = highlight.get("TelemetryMissing")
            if telemetry_missing is not None and not isinstance(telemetry_missing, bool):
                gpu_highlight_mapping_warning_count += 1
                _add_issue(
                    issues,
                    "warning",
                    "gpu_highlights",
                    f"{label} GPU highlight {highlight_index} has non-boolean TelemetryMissing",
                    {"value": telemetry_missing},
                )
            for metric_name in ("UsageAvg", "UsageMax", "MemoryBusyAvg", "MemoryBusyMax", "PowerAvgW", "PowerMaxW", "VramUsedAvgGB", "VramUsedMaxGB", "AllocationPercent"):
                value = highlight.get(metric_name)
                if value is None:
                    continue
                try:
                    numeric = float(value)
                except Exception:
                    _add_issue(
                        issues,
                        "warning",
                        "gpu_highlights",
                        f"{label} GPU highlight {highlight_index} has non-numeric {metric_name}",
                        {"value": value},
                    )
                    continue
                if numeric != numeric:
                    _add_issue(
                        issues,
                        "warning",
                        "gpu_highlights",
                        f"{label} GPU highlight {highlight_index} has NaN {metric_name}",
                    )
                if metric_name in {"UsageAvg", "UsageMax", "MemoryBusyAvg", "MemoryBusyMax", "AllocationPercent"} and not (0.0 <= numeric <= 100.0):
                    _add_issue(
                        issues,
                        "warning",
                        "gpu_highlights",
                        f"{label} GPU highlight {highlight_index} has out-of-range {metric_name}",
                        {"value": numeric},
                    )
    checks["gpu_highlights"] = {
        "stage_outcomes": len(stage_outcomes),
        "gpu_highlights": gpu_highlight_count,
        "mapping_warnings": gpu_highlight_mapping_warning_count,
    }
    checks["stage_alignment"] = {
        "warnings": stage_alignment_warning_count,
    }

    action_item_validation = validate_report_action_items(report_summary)
    checks.update(action_item_validation.get("checks", {}))
    issues.extend(action_item_validation.get("issues", []))
    action_details = action_item_validation.get("action_details", [])

    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            _add_issue(issues, "error", "segments", f"Segment {index} is not an object")
            continue
        label = segment.get("Label") or segment.get("TestDescription") or segment.get("TestType") or f"segment_{index}"
        missing_segment_fields = [
            field
            for field in ("TestType", "TestDescription", "Duration", "AnalysisWindow", "Clocks", "Temperatures", "Power", "Voltage", "GpuMetrics")
            if field not in segment
        ]
        if missing_segment_fields:
            _add_issue(
                issues,
                "error",
                "segment_shape",
                f"{label} is missing parser-facing segment fields",
                {"missing": missing_segment_fields},
            )
        detail_key = f"segment_{index}"
        if detail_key not in segment_details:
            _add_issue(
                issues,
                "warning",
                "segment_details",
                f"{label} is missing SegmentDetails.{detail_key}",
            )
        interpretation = segment.get("StabilityInterpretation") if isinstance(segment.get("StabilityInterpretation"), dict) else {}
        targeting = ((segment.get("GpuExecution") or {}).get("Targeting") or []) if isinstance(segment.get("GpuExecution"), dict) else []
        targeted_count = sum(1 for entry in targeting if isinstance(entry, dict) and bool(entry.get("Targeted")))
        observed_only_count = sum(1 for entry in targeting if isinstance(entry, dict) and not bool(entry.get("Targeted")))
        if interpretation:
            expected_targeted = int(interpretation.get("TargetedGpuCount") or 0)
            expected_observed = int(interpretation.get("ObservedOnlyGpuCount") or 0)
            if expected_targeted != targeted_count:
                _add_issue(
                    issues,
                    "warning",
                    "gpu_targeting",
                    f"{label} TargetedGpuCount does not match GpuExecution.Targeting",
                    {"interpretation": expected_targeted, "targeting": targeted_count},
                )
            if expected_observed != observed_only_count:
                _add_issue(
                    issues,
                    "warning",
                    "gpu_targeting",
                    f"{label} ObservedOnlyGpuCount does not match GpuExecution.Targeting",
                    {"interpretation": expected_observed, "targeting": observed_only_count},
                )
        for entry in targeting:
            if not isinstance(entry, dict) or bool(entry.get("Targeted")):
                continue
            evidence = entry.get("WorkerEvidence") if isinstance(entry.get("WorkerEvidence"), dict) else {}
            if int(evidence.get("WorkerResultCount") or 0) > 0:
                _add_issue(
                    issues,
                    "warning",
                    "gpu_targeting",
                    f"{label} has observed-only GPU telemetry with worker evidence attached",
                    {"gpu_index": entry.get("GpuIndex")},
                )

    gpu_worker_validation = validate_gpu_worker_summary(parsed, report_summary)
    issues.extend(gpu_worker_validation.get("issues", []))
    validation_details = gpu_worker_validation.get("validation_details", [])

    return {
        "checks": checks,
        "issues": issues,
        "segments": segments,
        "validation_details": validation_details,
        "gpu_highlight_count": gpu_highlight_count,
        "action_details": action_details,
    }
