#!/usr/bin/env python3
"""Report-summary helper logic for compatibility exports."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


REPORT_SUMMARY_MIRROR_FIELDS = (
    "Schema",
    "Result",
    "ExecutionDetail",
    "OutcomeClass",
    "State",
    "WarningCount",
    "ErrorCount",
    "StageCount",
    "SkippedStageCount",
    "ActionItemCategoryCounts",
    "ActionItemSeverityCounts",
)

STABILITY_INTERPRETATION_MIRROR_FIELDS = (
    "State",
    "Result",
    "OutcomeClass",
    "OutcomeSummary",
    "OverallResult",
    "WarningCategoryCounts",
    "ErrorCategoryCounts",
    "ReportOnlyThresholdWouldWarnCount",
    "ReportOnlyThresholdUnobservedCount",
)

REPORT_TO_STABILITY_FIELDS = (
    ("Result", "OverallResult"),
    ("OutcomeClass", "OutcomeClass"),
    ("OutcomeSummary", "OutcomeSummary"),
    ("State", "State"),
    ("WarningCategoryCounts", "WarningCategoryCounts"),
    ("ErrorCategoryCounts", "ErrorCategoryCounts"),
    ("ReportOnlyThresholdWouldWarnCount", "ReportOnlyThresholdWouldWarnCount"),
    ("ReportOnlyThresholdUnobservedCount", "ReportOnlyThresholdUnobservedCount"),
)


def friendly_report_category(category: Any) -> str:
    key = str(category or "").strip()
    labels = {
        "gpu_thermal_throttle_zone": "GPU thermal warning zone",
        "gpu_temperature": "GPU temperature threshold",
        "gpu_vram_telemetry_discrepancy": "OS VRAM telemetry under-report",
        "gpu_vram_target_attainment": "VRAM allocation target miss",
        "gpu_backend_effectiveness": "GPU backend effectiveness",
        "nvidia_xid": "NVIDIA Xid driver/GPU fault",
        "operator_stop": "operator manual stop",
        "report_only_threshold_recommendation": "report-only performance recommendation",
        "workload_or_system_error": "workload/system error",
        "skipped_stage": "skipped stage",
    }
    return labels.get(key, key.replace("_", " ") if key else "uncategorized")


def _review_verdict_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or text in {"none", "null", "unknown", "-"}:
        return ""
    if text in {"pass", "passed", "ok", "success", "successful", "completed", "finished"}:
        return "Pass"
    if text in {"warning", "warn", "ready_with_warnings"}:
        return "Warning"
    if text in {"fail", "failed", "error", "critical", "not_ready"}:
        return "Fail"
    if text in {"aborted", "manual_abort", "manually_aborted", "cancelled", "canceled"}:
        return text.replace("_", " ").title()
    return str(value).strip()


def _review_stage_verdicts(parsed: Dict[str, Any], report_summary: Dict[str, Any]) -> List[str]:
    stages = report_summary.get("StageOutcomes") if isinstance(report_summary.get("StageOutcomes"), list) else []
    if not stages:
        stages = parsed.get("Segments") if isinstance(parsed.get("Segments"), list) else []
    verdicts: List[str] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        verdict = _review_verdict_label(stage.get("Verdict") or stage.get("Result"))
        if verdict:
            verdicts.append(verdict)
    return verdicts


def clean_review_verdict_from_payload(
    parsed: Dict[str, Any],
    validation_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return an operator-facing verdict without changing legacy run result fields.

    Compatibility exports historically carry run completion terms such as
    ``Finished`` in ``Result``. Review UIs need a pass/warn/fail verdict when
    stages/rules were actually evaluated. If evaluated stages all pass and
    validation has no errors, the display/effective verdict is ``Pass`` even
    when older final verdict fields are absent.
    """

    parsed = parsed if isinstance(parsed, dict) else {}
    report_summary = parsed.get("ReportSummary") if isinstance(parsed.get("ReportSummary"), dict) else {}
    validation_payload = validation_payload if isinstance(validation_payload, dict) else {}
    validation_summary = (
        validation_payload.get("summary")
        if isinstance(validation_payload.get("summary"), dict)
        else {}
    )
    stage_verdicts = _review_stage_verdicts(parsed, report_summary)
    stage_count = len(stage_verdicts)
    validation_result = _review_verdict_label(validation_payload.get("result"))
    errors = int(validation_summary.get("errors") or 0)
    warnings = int(validation_summary.get("warnings") or 0)
    rule_count = int(validation_summary.get("rule_checks") or validation_summary.get("checks") or 0)
    not_checked_count = int(
        validation_summary.get("not_checked")
        or validation_summary.get("not_checked_rules")
        or validation_summary.get("optional_not_checked")
        or 0
    )
    manual_state = str(
        report_summary.get("ExecutionDetail")
        or parsed.get("ExecutionDetail")
        or report_summary.get("OutcomeClass")
        or ""
    ).strip().lower()
    manual_states = {"manually_aborted", "manual_abort", "aborted", "cancelled", "canceled"}
    if manual_state in manual_states:
        display = _review_verdict_label(manual_state)
        return {
            "FinalVerdict": display or "None",
            "RuleBasedVerdict": "None",
            "EffectiveFinalVerdict": display or "None",
            "EvaluatedStageCount": stage_count,
            "EvaluatedRuleCount": rule_count,
            "NotCheckedRuleCount": not_checked_count,
            "Reason": "manual_or_aborted_state",
        }

    if not stage_verdicts and not rule_count and not validation_result:
        return {
            "FinalVerdict": "None",
            "RuleBasedVerdict": "None",
            "EffectiveFinalVerdict": "None",
            "EvaluatedStageCount": 0,
            "EvaluatedRuleCount": 0,
            "NotCheckedRuleCount": not_checked_count,
            "Reason": "no_evaluated_stages_or_rules",
        }

    if any(verdict == "Fail" for verdict in stage_verdicts) or errors:
        effective = "Fail"
    elif any(verdict == "Warning" for verdict in stage_verdicts) or warnings or validation_result == "Warning":
        effective = "Warning"
    elif stage_verdicts and all(verdict == "Pass" for verdict in stage_verdicts):
        effective = "Pass"
    elif validation_result == "Pass":
        effective = "Pass"
    else:
        effective = _review_verdict_label(report_summary.get("FinalVerdict")) or "None"

    rule_based = "Fail" if errors else "Warning" if warnings else "Pass" if (rule_count or stage_count or validation_result == "Pass") else "None"
    final = _review_verdict_label(report_summary.get("FinalVerdict") or report_summary.get("Verdict"))
    if not final and effective in {"Pass", "Warning", "Fail"}:
        final = effective
    return {
        "FinalVerdict": final or "None",
        "RuleBasedVerdict": rule_based,
        "EffectiveFinalVerdict": effective,
        "EvaluatedStageCount": stage_count,
        "EvaluatedRuleCount": rule_count,
        "NotCheckedRuleCount": not_checked_count,
        "Reason": "evaluated_clean" if effective == "Pass" else "evaluated_with_findings",
    }


def validate_report_summary_mirror(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Validate ReportSummary and Metadata.ReportSummary mirror fields."""

    parsed = parsed if isinstance(parsed, dict) else {}
    issues: List[Dict[str, Any]] = []
    report_summary = parsed.get("ReportSummary")
    metadata = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
    metadata_report_summary = metadata.get("ReportSummary") if isinstance(metadata, dict) else None

    if not isinstance(report_summary, dict):
        issues.append(
            {
                "severity": "warning",
                "category": "report_summary",
                "message": "ReportSummary is missing",
                "details": {},
            }
        )
        report_summary = {}
    if not isinstance(metadata_report_summary, dict):
        issues.append(
            {
                "severity": "warning",
                "category": "report_summary",
                "message": "Metadata.ReportSummary is missing",
                "details": {},
            }
        )
        metadata_report_summary = {}

    report_mirror_mismatches = []
    if report_summary and metadata_report_summary:
        for field in REPORT_SUMMARY_MIRROR_FIELDS:
            if report_summary.get(field) != metadata_report_summary.get(field):
                report_mirror_mismatches.append(field)
        if report_mirror_mismatches:
            issues.append(
                {
                    "severity": "warning",
                    "category": "report_summary",
                    "message": "ReportSummary and Metadata.ReportSummary do not match",
                    "details": {"fields": report_mirror_mismatches},
                }
            )

    return {
        "checks": {
            "report_summary": {
                "top_level_present": bool(report_summary),
                "metadata_present": bool(metadata_report_summary),
                "mirror_mismatches": report_mirror_mismatches,
            }
        },
        "issues": issues,
        "report_summary": report_summary,
        "metadata_report_summary": metadata_report_summary,
    }


def validate_stability_alignment(parsed: Dict[str, Any], report_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Validate StabilityInterpretation mirrors and ReportSummary alignment."""

    parsed = parsed if isinstance(parsed, dict) else {}
    report_summary = report_summary if isinstance(report_summary, dict) else {}
    issues: List[Dict[str, Any]] = []

    stability_interpretation = (
        parsed.get("StabilityInterpretation")
        if isinstance(parsed.get("StabilityInterpretation"), dict)
        else {}
    )
    metadata = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
    metadata_stability = metadata.get("Stability") if isinstance(metadata.get("Stability"), dict) else {}
    metadata_interpretation = (
        metadata_stability.get("InterpretationSummary")
        if isinstance(metadata_stability.get("InterpretationSummary"), dict)
        else {}
    )

    stability_alignment_mismatches = []
    if not stability_interpretation:
        issues.append(
            {
                "severity": "warning",
                "category": "stability_alignment",
                "message": "StabilityInterpretation is missing",
                "details": {},
            }
        )
    if not metadata_interpretation:
        issues.append(
            {
                "severity": "warning",
                "category": "stability_alignment",
                "message": "Metadata.Stability.InterpretationSummary is missing",
                "details": {},
            }
        )
    if stability_interpretation and metadata_interpretation:
        for field in STABILITY_INTERPRETATION_MIRROR_FIELDS:
            if stability_interpretation.get(field) != metadata_interpretation.get(field):
                stability_alignment_mismatches.append(f"Metadata.Stability.InterpretationSummary.{field}")
        if stability_alignment_mismatches:
            issues.append(
                {
                    "severity": "warning",
                    "category": "stability_alignment",
                    "message": "StabilityInterpretation and Metadata.Stability.InterpretationSummary do not match",
                    "details": {"fields": stability_alignment_mismatches},
                }
            )

    report_stability_mismatches = []
    if report_summary and stability_interpretation:
        for report_field, stability_field in REPORT_TO_STABILITY_FIELDS:
            if report_summary.get(report_field) != stability_interpretation.get(stability_field):
                report_stability_mismatches.append(f"{report_field}->{stability_field}")
        if report_stability_mismatches:
            issues.append(
                {
                    "severity": "warning",
                    "category": "stability_alignment",
                    "message": "ReportSummary does not match StabilityInterpretation",
                    "details": {"fields": report_stability_mismatches},
                }
            )

    return {
        "checks": {
            "stability_alignment": {
                "top_level_present": bool(stability_interpretation),
                "metadata_present": bool(metadata_interpretation),
                "metadata_mismatches": stability_alignment_mismatches,
                "report_mismatches": report_stability_mismatches,
            }
        },
        "issues": issues,
        "stability_interpretation": stability_interpretation,
        "metadata_interpretation": metadata_interpretation,
    }


def validate_report_stage_counts(parsed: Dict[str, Any], report_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Validate Segments, SegmentDetails, and ReportSummary.StageOutcomes counts."""

    parsed = parsed if isinstance(parsed, dict) else {}
    report_summary = report_summary if isinstance(report_summary, dict) else {}
    issues: List[Dict[str, Any]] = []
    segments = parsed.get("Segments") if isinstance(parsed.get("Segments"), list) else []
    segment_details = parsed.get("SegmentDetails") if isinstance(parsed.get("SegmentDetails"), dict) else {}
    stage_outcomes = report_summary.get("StageOutcomes") if isinstance(report_summary.get("StageOutcomes"), list) else []

    if not segments:
        issues.append(
            {
                "severity": "error",
                "category": "segments",
                "message": "Segments is missing or empty",
                "details": {},
            }
        )
    if stage_outcomes and len(stage_outcomes) != len(segments):
        issues.append(
            {
                "severity": "warning",
                "category": "report_summary",
                "message": "ReportSummary.StageOutcomes count does not match Segments count",
                "details": {"segments": len(segments), "stage_outcomes": len(stage_outcomes)},
            }
        )

    return {
        "checks": {
            "stage_counts": {
                "segments": len(segments),
                "segment_details": len(segment_details),
                "stage_outcomes": len(stage_outcomes),
            }
        },
        "issues": issues,
        "segments": segments,
        "segment_details": segment_details,
        "stage_outcomes": stage_outcomes,
    }


def validate_report_action_items(report_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Validate ReportSummary action item arrays and count mirrors."""

    report_summary = report_summary if isinstance(report_summary, dict) else {}
    issues: List[Dict[str, Any]] = []
    raw_action_details = report_summary.get("ActionItemDetails")
    raw_action_items = report_summary.get("ActionItems")
    raw_action_category_counts = report_summary.get("ActionItemCategoryCounts")
    raw_action_severity_counts = report_summary.get("ActionItemSeverityCounts")
    action_details: List[Dict[str, Any]] = []
    action_item_messages: List[str] = []
    action_category_counts: Dict[str, int] = {}
    action_severity_counts: Dict[str, int] = {}

    if raw_action_details is None:
        issues.append(
            {
                "severity": "warning",
                "category": "action_items",
                "message": "ReportSummary.ActionItemDetails is missing",
                "details": {},
            }
        )
    elif not isinstance(raw_action_details, list):
        issues.append(
            {
                "severity": "warning",
                "category": "action_items",
                "message": "ReportSummary.ActionItemDetails is not a list",
                "details": {},
            }
        )
    else:
        valid_severities = {"info", "warning", "error", "critical"}
        for item_index, item in enumerate(raw_action_details, start=1):
            if not isinstance(item, dict):
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": f"Action item detail {item_index} is not an object",
                        "details": {},
                    }
                )
                continue
            action_details.append(item)
            severity = str(item.get("Severity") or "").strip().lower()
            if severity == "warn":
                severity = "warning"
            category = str(item.get("Category") or "").strip()
            message = str(item.get("Message") or item.get("Summary") or "").strip()
            if not severity:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": f"Action item detail {item_index} is missing Severity",
                        "details": {},
                    }
                )
                severity = "unknown"
            elif severity not in valid_severities:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": f"Action item detail {item_index} has unknown Severity",
                        "details": {"severity": severity},
                    }
                )
            if not category:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": f"Action item detail {item_index} is missing Category",
                        "details": {},
                    }
                )
                category = "unknown"
            if not message:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": f"Action item detail {item_index} is missing Message",
                        "details": {},
                    }
                )
            else:
                action_item_messages.append(message)
            if item.get("Count") is not None:
                try:
                    if int(item.get("Count")) < 0:
                        issues.append(
                            {
                                "severity": "warning",
                                "category": "action_items",
                                "message": f"Action item detail {item_index} has negative Count",
                                "details": {"count": item.get("Count")},
                            }
                        )
                except Exception:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "action_items",
                            "message": f"Action item detail {item_index} has non-numeric Count",
                            "details": {"count": item.get("Count")},
                        }
                    )
            action_category_counts[category] = action_category_counts.get(category, 0) + 1
            action_severity_counts[severity] = action_severity_counts.get(severity, 0) + 1

    normalized_action_items: List[str] = []
    if raw_action_items is None:
        issues.append(
            {
                "severity": "warning",
                "category": "action_items",
                "message": "ReportSummary.ActionItems is missing",
                "details": {},
            }
        )
    elif not isinstance(raw_action_items, list):
        issues.append(
            {
                "severity": "warning",
                "category": "action_items",
                "message": "ReportSummary.ActionItems is not a list",
                "details": {},
            }
        )
    else:
        for item_index, item in enumerate(raw_action_items, start=1):
            if not isinstance(item, str):
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": f"ActionItems entry {item_index} is not a string",
                        "details": {},
                    }
                )
                continue
            message = item.strip()
            if not message:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": f"ActionItems entry {item_index} is blank",
                        "details": {},
                    }
                )
            else:
                normalized_action_items.append(message)
        if action_item_messages and len(normalized_action_items) != len(action_item_messages):
            issues.append(
                {
                    "severity": "warning",
                    "category": "action_items",
                    "message": "ReportSummary.ActionItems count does not match ActionItemDetails messages",
                    "details": {"action_items": len(normalized_action_items), "action_item_details": len(action_item_messages)},
                }
            )

    if raw_action_category_counts is None:
        issues.append(
            {
                "severity": "warning",
                "category": "action_items",
                "message": "ReportSummary.ActionItemCategoryCounts is missing",
                "details": {},
            }
        )
    elif not isinstance(raw_action_category_counts, dict):
        issues.append(
            {
                "severity": "warning",
                "category": "action_items",
                "message": "ReportSummary.ActionItemCategoryCounts is not an object",
                "details": {},
            }
        )
    else:
        normalized_counts: Dict[str, int] = {}
        for key, value in raw_action_category_counts.items():
            try:
                normalized_counts[str(key)] = int(value)
            except Exception:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": "ReportSummary.ActionItemCategoryCounts has a non-numeric value",
                        "details": {"category": key, "value": value},
                    }
                )
        if action_category_counts and normalized_counts != action_category_counts:
            issues.append(
                {
                    "severity": "warning",
                    "category": "action_items",
                    "message": "ReportSummary.ActionItemCategoryCounts does not match ActionItemDetails",
                    "details": {"summary": normalized_counts, "computed": action_category_counts},
                }
            )

    if raw_action_severity_counts is not None:
        if not isinstance(raw_action_severity_counts, dict):
            issues.append(
                {
                    "severity": "warning",
                    "category": "action_items",
                    "message": "ReportSummary.ActionItemSeverityCounts is not an object",
                    "details": {},
                }
            )
        else:
            normalized_counts = {}
            for key, value in raw_action_severity_counts.items():
                try:
                    severity_key = str(key).strip().lower()
                    if severity_key == "warn":
                        severity_key = "warning"
                    normalized_counts[severity_key] = int(value)
                except Exception:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "action_items",
                            "message": "ReportSummary.ActionItemSeverityCounts has a non-numeric value",
                            "details": {"severity": key, "value": value},
                        }
                    )
            if action_severity_counts and normalized_counts != action_severity_counts:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "action_items",
                        "message": "ReportSummary.ActionItemSeverityCounts does not match ActionItemDetails",
                        "details": {"summary": normalized_counts, "computed": action_severity_counts},
                    }
                )

    return {
        "checks": {
            "action_items": {
                "action_items": len(normalized_action_items),
                "action_item_details": len(action_details),
                "category_counts": action_category_counts,
                "severity_counts": action_severity_counts,
                "category_counts_present": isinstance(raw_action_category_counts, dict),
                "severity_counts_present": isinstance(raw_action_severity_counts, dict),
            }
        },
        "issues": issues,
        "action_details": action_details,
        "action_items": normalized_action_items,
    }


def validate_gpu_worker_summary(parsed: Dict[str, Any], report_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Validate canonical GpuWorkerSummary fields against GpuDetails.validation_details."""

    parsed = parsed if isinstance(parsed, dict) else {}
    report_summary = report_summary if isinstance(report_summary, dict) else {}
    issues: List[Dict[str, Any]] = []
    gpu_details = parsed.get("GpuDetails") if isinstance(parsed.get("GpuDetails"), dict) else {}
    validation_details = gpu_details.get("validation_details") if isinstance(gpu_details.get("validation_details"), list) else []
    worker_summary = report_summary.get("GpuWorkerSummary") if isinstance(report_summary.get("GpuWorkerSummary"), dict) else {}

    expected_worker_count = int(worker_summary.get("WorkerResultCount") or 0)
    if expected_worker_count != len(validation_details):
        issues.append(
            {
                "severity": "warning",
                "category": "gpu_worker_summary",
                "message": "GpuWorkerSummary.WorkerResultCount does not match GpuDetails.validation_details",
                "details": {"summary": expected_worker_count, "validation_details": len(validation_details)},
            }
        )
    successful = sum(
        1
        for detail in validation_details
        if str((detail or {}).get("Status") or "").lower() in {"ok", "pass", "passed", "success"}
    )
    expected_successful = int(worker_summary.get("SuccessfulWorkerResultCount") or 0)
    if validation_details and expected_successful != successful:
        issues.append(
            {
                "severity": "warning",
                "category": "gpu_worker_summary",
                "message": "GpuWorkerSummary.SuccessfulWorkerResultCount does not match validation detail statuses",
                "details": {"summary": expected_successful, "validation_details": successful},
            }
        )
    verification_passes = sum(int((detail or {}).get("VerificationPasses") or 0) for detail in validation_details)
    expected_verification = int(worker_summary.get("VerificationPasses") or 0)
    if validation_details and expected_verification != verification_passes:
        issues.append(
            {
                "severity": "warning",
                "category": "gpu_worker_summary",
                "message": "GpuWorkerSummary.VerificationPasses does not match validation details",
                "details": {"summary": expected_verification, "validation_details": verification_passes},
            }
        )

    for detail in validation_details:
        if not isinstance(detail, dict):
            continue
        mode = str(detail.get("Mode") or detail.get("Workload") or "").strip()
        stage = str(detail.get("Stage") or "")
        if not mode:
            issues.append(
                {
                    "severity": "warning",
                    "category": "gpu_worker_details",
                    "message": f"{stage} GPU worker is missing Mode/Workload",
                    "details": {},
                }
            )
        if not str(detail.get("TargetId") or "").strip():
            issues.append(
                {
                    "severity": "warning",
                    "category": "gpu_worker_details",
                    "message": f"{stage} GPU worker is missing TargetId",
                    "details": {},
                }
            )
        if mode == "vram":
            target_bytes = int(detail.get("TargetVramBytes") or detail.get("ActiveTargetVramBytes") or 0)
            allocated_bytes = int(detail.get("AllocatedVramBytes") or detail.get("BufferAllocationBytes") or 0)
            if target_bytes > 0 and allocated_bytes > 0 and detail.get("AllocationPercent") is None:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "gpu_worker_details",
                        "message": f"{stage} VRAM worker is missing AllocationPercent",
                        "details": {},
                    }
                )
        backend = str(detail.get("Backend") or "")
        compute_variant = str(detail.get("ComputeVariant") or "").strip().lower()
        coverage = detail.get("VerifiedBufferCoveragePercent")
        if backend == "python_vulkan_compute" and compute_variant == "stateful_memory" and coverage is not None:
            try:
                coverage_percent = float(coverage)
            except Exception:
                coverage_percent = -1.0
            buffer_count = int(detail.get("BufferCount") or 0)
            if buffer_count > 1 and coverage_percent < 100.0:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "gpu_worker_details",
                        "message": f"{stage} Vulkan stateful memory worker did not verify every allocated buffer",
                        "details": {
                            "buffer_count": buffer_count,
                            "verified_buffer_count": int(detail.get("VerifiedBufferCount") or 0),
                            "verified_buffer_coverage_percent": coverage,
                        },
                    }
                )
        if backend == "python_vulkan_transfer" and coverage is not None:
            try:
                coverage_percent = float(coverage)
            except Exception:
                coverage_percent = -1.0
            if coverage_percent < 100.0:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "gpu_worker_details",
                        "message": f"{stage} Vulkan transfer worker did not verify its transfer buffer",
                        "details": {
                            "verified_buffer_count": int(detail.get("VerifiedBufferCount") or 0),
                            "verified_buffer_coverage_percent": coverage,
                        },
                    }
                )

    return {
        "issues": issues,
        "validation_details": validation_details,
        "worker_summary": worker_summary,
    }


def build_department_use_summary(
    *,
    overall_result: str,
    execution_detail: str,
    stability_interpretation: Dict[str, Any],
    warning_events: List[Dict[str, Any]],
    error_events: List[Dict[str, Any]],
    skipped_stages: List[Dict[str, Any]],
    worker_result_count: int,
    worker_success_count: int,
    worker_failure_count: int,
    verification_passes: int,
) -> Dict[str, Any]:
    warning_categories = dict(stability_interpretation.get("WarningCategoryCounts") or {})
    error_categories = dict(stability_interpretation.get("ErrorCategoryCounts") or {})
    outcome_class = str(stability_interpretation.get("OutcomeClass") or "").strip()
    result_text = str(overall_result or "").strip().lower()
    execution_text = str(execution_detail or "").strip().lower()
    blocking = bool(error_events or error_categories or worker_failure_count)
    blocking_results = {"aborted", "manually_aborted", "manual_abort", "error", "failed", "fail"}
    if result_text in blocking_results or execution_text in blocking_results:
        blocking = True
    if skipped_stages:
        blocking = True

    worker_verified = worker_result_count > 0 and worker_failure_count == 0 and worker_success_count == worker_result_count
    if blocking:
        status = "not_ready"
        decision = "Do not use as a passing department validation until the blocking item is resolved."
    elif warning_events or warning_categories:
        status = "ready_with_warnings"
        decision = "Usable for department validation with documented non-blocking warnings."
    else:
        status = "ready"
        decision = "Usable for department validation."

    if worker_verified:
        confidence = "worker_verified"
    elif worker_result_count > 0:
        confidence = "worker_results_present_with_caveats"
    else:
        confidence = "telemetry_only_or_cpu_memory"

    caveats: List[str] = []
    if skipped_stages:
        caveats.append(f"{len(skipped_stages)} requested stage(s) were skipped")
    if worker_failure_count:
        caveats.append(f"{worker_failure_count} GPU worker result(s) reported failure")
    for category, count in sorted(warning_categories.items()):
        caveats.append(f"{friendly_report_category(category)} ({count})")
    for category, count in sorted(error_categories.items()):
        caveats.append(f"{friendly_report_category(category)} error ({count})")
    try:
        threshold_count = int(stability_interpretation.get("ReportOnlyThresholdWouldWarnCount") or 0)
    except Exception:
        threshold_count = 0
    if threshold_count:
        caveats.append(f"report-only performance recommendation caveat ({threshold_count})")

    operator_notes: List[str] = []
    if "nvidia_xid" in error_categories:
        operator_notes.append(
            "NVIDIA Xid error detected; this indicates a GPU, driver, power, PCIe, or platform stability fault during the run. If the message says the GPU fell off the bus, treat the result as a system stability failure, not an import or parser issue."
        )
    if "gpu_vram_telemetry_discrepancy" in warning_categories:
        operator_notes.append(
            "VRAM worker allocation/verification passed; OS VRAM telemetry may under-report shared-memory or driver-managed allocations."
        )
    if "gpu_thermal_throttle_zone" in warning_categories:
        operator_notes.append(
            "Thermal warning means the unit reached the configured warning zone; review cooling, airflow, and ambient conditions."
        )
    if "gpu_temperature" in error_categories:
        operator_notes.append(
            "GPU temperature fail threshold was reached; the suite stopped the run to avoid treating an overheated unit as passing."
        )
    if result_text == "manually_aborted" or execution_text == "manually_aborted":
        operator_notes.append(
            "Run was stopped manually by the operator; partial artifacts were saved, but this should not be treated as a completed validation."
        )
    if threshold_count:
        operator_notes.append(
            "Report-only threshold misses are advisory unless strict threshold warnings are configured for the profile."
        )
    if not operator_notes and status == "ready":
        operator_notes.append("No warning or error categories were reported.")

    return {
        "Schema": "linux_validation_suite.department_use_summary.v1",
        "Status": status,
        "Decision": decision,
        "Blocking": blocking,
        "Confidence": confidence,
        "OutcomeClass": outcome_class,
        "WorkerVerified": worker_verified,
        "WorkerResultCount": worker_result_count,
        "SuccessfulWorkerResultCount": worker_success_count,
        "WorkerFailureCount": worker_failure_count,
        "VerificationPasses": verification_passes,
        "WarningCount": len(warning_events),
        "ErrorCount": len(error_events),
        "SkippedStageCount": len(skipped_stages),
        "PrimaryCaveats": caveats,
        "OperatorNotes": operator_notes,
    }


def build_report_action_item_details(
    stability_interpretation: Dict[str, Any],
    warning_events: List[Dict[str, Any]],
    error_events: List[Dict[str, Any]],
    skipped_stages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    def add_item(
        severity: str,
        category: str,
        message: str,
        *,
        source: str = "report_summary",
        count: Optional[int] = None,
    ) -> None:
        item = {
            "Severity": severity,
            "Category": category,
            "Source": source,
            "Message": message,
        }
        if count is not None:
            item["Count"] = count
        items.append(item)

    nvidia_xid_count = sum(
        1 for event in error_events
        if str(event.get("category") or "").strip().lower() == "nvidia_xid"
    )
    gpu_temp_error_count = sum(
        1 for event in error_events
        if str(event.get("category") or "").strip().lower() == "gpu_temperature"
    )
    if nvidia_xid_count:
        add_item(
            "error",
            "nvidia_xid",
            "NVIDIA Xid driver/GPU fault was logged during the run. If the event says the GPU fell off the bus or reset was required, inspect power, PCIe risers/slots, cooling, driver stability, and the physical GPU before treating this unit as passing.",
            count=nvidia_xid_count,
        )
    if gpu_temp_error_count:
        add_item(
            "error",
            "gpu_temperature",
            "GPU temperature fail threshold was reached. Treat this as a cooling, airflow, ambient, fan, paste/contact, or chassis thermal issue before treating the unit as passing.",
            count=gpu_temp_error_count,
        )
    generic_error_count = len(error_events) - nvidia_xid_count - gpu_temp_error_count
    if generic_error_count > 0:
        add_item(
            "error",
            "workload_or_system_error",
            "Review error-level events before treating this run as passing.",
            count=generic_error_count,
        )
    warning_categories = set((stability_interpretation.get("WarningCategoryCounts") or {}).keys())
    if "gpu_thermal_throttle_zone" in warning_categories:
        add_item(
            "warning",
            "gpu_thermal_throttle_zone",
            "Review cooling, airflow, and ambient conditions before sustained production use; at least one GPU reached the configured thermal warning zone.",
            count=int((stability_interpretation.get("WarningCategoryCounts") or {}).get("gpu_thermal_throttle_zone") or 0),
        )
    if "gpu_vram_telemetry_discrepancy" in warning_categories:
        add_item(
            "info",
            "gpu_vram_telemetry_discrepancy",
            "No rerun is required solely for this warning when worker allocation and verification passed; treat worker-verified VRAM allocation as authoritative over under-reporting OS telemetry.",
            count=int((stability_interpretation.get("WarningCategoryCounts") or {}).get("gpu_vram_telemetry_discrepancy") or 0),
        )
    try:
        would_warn_count = int(stability_interpretation.get("ReportOnlyThresholdWouldWarnCount") or 0)
    except Exception:
        would_warn_count = 0
    if would_warn_count > 0:
        add_item(
            "info",
            "report_only_threshold_recommendation",
            "Review advisory performance threshold misses; workload verification passed, but sustained telemetry was below the preferred target.",
            count=would_warn_count,
        )
    if skipped_stages:
        add_item(
            "warning",
            "skipped_stage",
            "Review skipped stages before using this as a complete profile result; at least one requested stage did not run in this environment.",
            count=len(skipped_stages),
        )
    return items


def build_report_intel_gpu_top_summary(sidecar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not sidecar:
        return None
    aggregate = sidecar.get("aggregate_engine_busy") if isinstance(sidecar.get("aggregate_engine_busy"), dict) else {}
    engines = sidecar.get("engines") if isinstance(sidecar.get("engines"), dict) else {}
    active_engines = {
        name: values
        for name, values in engines.items()
        if isinstance(values, dict) and isinstance(values.get("max"), (int, float)) and float(values.get("max") or 0.0) > 1.0
    }
    return {
        "Available": bool(sidecar.get("available")),
        "ObjectCount": sidecar.get("object_count"),
        "AggregateEngineBusy": aggregate,
        "ActiveEngines": active_engines,
        "Reason": sidecar.get("reason") or "",
        "RawPath": sidecar.get("raw_path"),
        "SummaryPath": sidecar.get("summary_path"),
    }


def build_report_stage_summary(segment: Dict[str, Any]) -> Dict[str, Any]:
    """Build one stable report-facing stage outcome."""
    interpretation = segment.get("StabilityInterpretation", {})
    if not isinstance(interpretation, dict):
        interpretation = {}
    threshold_recommendations = interpretation.get("ThresholdRecommendations", {})
    if not isinstance(threshold_recommendations, dict):
        threshold_recommendations = {}
    gpu_metrics = [
        metric for metric in segment.get("GpuMetrics", [])
        if isinstance(metric, dict) and metric.get("Targeted")
    ]
    coverage_notes: List[str] = []
    test_type_text = str(segment.get("TestType") or "").lower()
    if "gpu" in test_type_text and "vram" in test_type_text:
        vram_omitted = [
            str(metric.get("Name") or f"GPU {metric.get('GpuIndex', '?')}")
            for metric in gpu_metrics
            if "gpu_3d" in list(metric.get("Workloads", []) or [])
            and "vram" not in list(metric.get("Workloads", []) or [])
        ]
        if vram_omitted:
            coverage_notes.append(
                "Separate concurrent VRAM worker omitted for "
                + ", ".join(vram_omitted)
                + "; standalone VRAM stage remains the VRAM integrity source for those target(s)."
            )
    intel_sidecar = segment.get("IntelGpuTopSidecar")
    if not isinstance(intel_sidecar, dict):
        gpu_execution = segment.get("GpuExecution")
        intel_sidecar = (
            gpu_execution.get("IntelGpuTopSidecar")
            if isinstance(gpu_execution, dict) and isinstance(gpu_execution.get("IntelGpuTopSidecar"), dict)
            else {}
        )
    return {
        "Label": segment.get("Label") or segment.get("TestDescription") or segment.get("TestType"),
        "TestType": segment.get("TestType"),
        "Verdict": segment.get("Verdict"),
        "OutcomeClass": interpretation.get("OutcomeClass"),
        "OutcomeSummary": interpretation.get("OutcomeSummary"),
        "PrimaryPurpose": interpretation.get("PrimaryPurpose"),
        "BackendConfidence": interpretation.get("BackendConfidence"),
        "WarningCategoryCounts": dict(interpretation.get("WarningCategoryCounts") or {}),
        "ErrorCategoryCounts": dict(interpretation.get("ErrorCategoryCounts") or {}),
        "ReportOnlyThresholdWouldWarnCount": threshold_recommendations.get("WouldWarnCount", 0),
        "TargetedGpuCount": interpretation.get("TargetedGpuCount", 0),
        "TargetedLoadQualityCounts": dict(interpretation.get("TargetedLoadQualityCounts") or {}),
        "CoverageNotes": coverage_notes,
        "IntelGpuTopSidecar": build_report_intel_gpu_top_summary(intel_sidecar),
        "GpuHighlights": [
            {
                "GpuIndex": metric.get("GpuIndex"),
                "Name": metric.get("DisplayName") or metric.get("Name"),
                "DisplayName": metric.get("DisplayName") or metric.get("Name"),
                "LoadQuality": metric.get("LoadQuality"),
                "TargetIds": list(metric.get("TargetIds", [])),
                "Cards": list(metric.get("Cards", [])),
                "Slots": list(metric.get("Slots", [])),
                "Workloads": list(metric.get("Workloads", [])),
                "Backends": list(metric.get("Backends", [])),
                "TelemetryMissing": bool(metric.get("TelemetryMissing")),
                "UsageMin": (metric.get("Usage") or {}).get("Min"),
                "UsageAvg": (metric.get("Usage") or {}).get("Avg"),
                "UsageMax": (metric.get("Usage") or {}).get("Max"),
                "UsageStdDev": (metric.get("UsageSustain") or {}).get("StdDev"),
                "UsageRange": (metric.get("UsageSustain") or {}).get("Range"),
                "UsageSampleCount": (metric.get("UsageSustain") or {}).get("SampleCount"),
                "MemoryBusyAvg": (metric.get("MemoryUsage") or {}).get("Avg"),
                "MemoryBusyMax": (metric.get("MemoryUsage") or {}).get("Max"),
                "MemoryBusyStdDev": (metric.get("MemoryUsageSustain") or {}).get("StdDev"),
                "MemoryBusyRange": (metric.get("MemoryUsageSustain") or {}).get("Range"),
                "PowerAvgW": (metric.get("Power") or {}).get("Avg"),
                "PowerMaxW": (metric.get("Power") or {}).get("Max"),
                "VramUsedAvgGB": (metric.get("VramUsedGB") or {}).get("Avg"),
                "VramUsedMaxGB": (metric.get("VramUsedGB") or {}).get("Max"),
                "AllocationPercent": (metric.get("WorkerEvidence") or {}).get("MaxAllocationPercent"),
                "VerificationPasses": (metric.get("WorkerEvidence") or {}).get("VerificationPasses"),
            }
            for metric in gpu_metrics
        ],
    }


def overall_report_outcome_summary(
    state: str,
    warning_category_counts: Dict[str, int],
    error_category_counts: Dict[str, int],
    interpretations: List[Dict[str, Any]],
    threshold_would_warn_count: int = 0,
) -> Dict[str, str]:
    if state == "manually_aborted":
        return {
            "OutcomeClass": "manually_aborted",
            "Summary": "Run was stopped manually by the operator and partial results were saved.",
        }
    if state == "aborted":
        if "gpu_temperature" in error_category_counts:
            return {
                "OutcomeClass": "thermal_safety_abort",
                "Summary": "Run was stopped because a GPU reached the configured temperature fail threshold.",
            }
        return {
            "OutcomeClass": "aborted",
            "Summary": "Run aborted before all requested workloads completed.",
        }
    if state == "unstable" or error_category_counts:
        return {
            "OutcomeClass": "workload_or_integrity_failure",
            "Summary": "Run contains error-level events or failed workload integrity checks.",
        }
    warning_categories = set(warning_category_counts)
    if not warning_categories:
        if threshold_would_warn_count > 0:
            return {
                "OutcomeClass": "worker_verified_threshold_caveat",
                "Summary": "Run completed with verified worker results, but one or more report-only performance recommendations were missed.",
            }
        return {
            "OutcomeClass": "verified_clean",
            "Summary": "Run completed without warning or error events.",
        }
    segment_classes = {
        str(item.get("OutcomeClass") or "")
        for item in interpretations
        if str(item.get("OutcomeClass") or "")
    }
    non_blocking_categories = {
        "gpu_vram_telemetry_discrepancy",
        "gpu_thermal_throttle_zone",
    }
    if threshold_would_warn_count > 0 and warning_categories <= non_blocking_categories:
        return {
            "OutcomeClass": "worker_verified_non_blocking_warnings",
            "Summary": "Run completed with verified worker results; remaining warnings are thermal, telemetry-accounting, or report-only performance recommendation caveats.",
        }
    if warning_categories <= {"gpu_vram_telemetry_discrepancy"}:
        return {
            "OutcomeClass": "worker_verified_telemetry_limited",
            "Summary": "Run completed with verified worker results, but one or more OS telemetry sources under-reported the workload.",
        }
    if warning_categories <= {"gpu_thermal_throttle_zone"}:
        return {
            "OutcomeClass": "worker_verified_thermal_warning",
            "Summary": "Run completed with verified worker results, but one or more devices reached the configured thermal warning zone.",
        }
    if warning_categories <= non_blocking_categories:
        return {
            "OutcomeClass": "worker_verified_non_blocking_warnings",
            "Summary": "Run completed with verified worker results; remaining warnings are thermal or telemetry-accounting caveats.",
        }
    if segment_classes and segment_classes <= {
        "verified_clean",
        "verified_with_warnings",
        "worker_verified_telemetry_limited",
        "worker_verified_thermal_warning",
        "worker_verified_non_blocking_warnings",
    }:
        return {
            "OutcomeClass": "verified_with_warnings",
            "Summary": "Run completed with warning-level events; review category counts for details.",
        }
    return {
        "OutcomeClass": "warning_review_needed",
        "Summary": "Run completed with warning-level events that need review.",
    }


def build_overall_stability_interpretation(
    overall_result: str,
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate segment interpretations into the run-level interpretation."""
    interpretations = [
        segment.get("StabilityInterpretation", {})
        for segment in segments
        if isinstance(segment.get("StabilityInterpretation", {}), dict)
    ]
    state_counts: Dict[str, int] = {}
    purpose_counts: Dict[str, int] = {}
    confidence_counts: Dict[str, int] = {}
    warning_category_counts: Dict[str, int] = {}
    error_category_counts: Dict[str, int] = {}
    for interpretation in interpretations:
        state = str(interpretation.get("State") or "unknown")
        purpose = str(interpretation.get("PrimaryPurpose") or "unknown")
        confidence = str(interpretation.get("BackendConfidence") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        purpose_counts[purpose] = purpose_counts.get(purpose, 0) + 1
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
        for category, count in (interpretation.get("WarningCategoryCounts") or {}).items():
            warning_category_counts[str(category)] = warning_category_counts.get(str(category), 0) + int(count or 0)
        for category, count in (interpretation.get("ErrorCategoryCounts") or {}).items():
            error_category_counts[str(category)] = error_category_counts.get(str(category), 0) + int(count or 0)

    threshold_would_warn_count = 0
    threshold_unobserved_count = 0
    strict_threshold_enabled = False
    would_warn_details: List[Dict[str, Any]] = []
    unobserved_details: List[Dict[str, Any]] = []
    for segment in segments:
        segment_name = str(segment.get("TestDescription") or segment.get("TestType") or "")
        interpretation = segment.get("StabilityInterpretation", {})
        if not isinstance(interpretation, dict):
            continue
        recommendations = interpretation.get("ThresholdRecommendations", {})
        if not isinstance(recommendations, dict):
            continue
        strict_threshold_enabled = strict_threshold_enabled or bool(recommendations.get("StrictModeEnabled"))
        try:
            threshold_would_warn_count += int(recommendations.get("WouldWarnCount") or 0)
        except Exception:
            pass
        try:
            threshold_unobserved_count += int(recommendations.get("UnobservedCount") or 0)
        except Exception:
            pass
        for check in recommendations.get("Checks", []):
            if not isinstance(check, dict):
                continue
            result = str(check.get("Result") or "")
            entry = {
                "Segment": segment_name,
                "Check": str(check.get("Name") or ""),
                "Metric": str(check.get("Metric") or ""),
                "GpuIndex": check.get("GpuIndex"),
                "Target": check.get("Target"),
                "PrimaryPurpose": interpretation.get("PrimaryPurpose"),
                "BackendConfidence": interpretation.get("BackendConfidence"),
                "RecommendedMinAvgPercent": check.get("RecommendedMinAvgPercent"),
                "RecommendedMinMaxPercent": check.get("RecommendedMinMaxPercent"),
                "RecommendedMinPercent": check.get("RecommendedMinPercent"),
                "RecommendedMinPercentAtOrAbove90": check.get("RecommendedMinPercentAtOrAbove90"),
                "RecommendedMinPercentAtOrAbove25": check.get("RecommendedMinPercentAtOrAbove25"),
                "ObservedAvgPercent": check.get("ObservedAvgPercent"),
                "ObservedMaxPercent": check.get("ObservedMaxPercent"),
                "ObservedMinPercent": check.get("ObservedMinPercent"),
                "ObservedPercentAtOrAbove90": check.get("ObservedPercentAtOrAbove90"),
                "ObservedPercentAtOrAbove25": check.get("ObservedPercentAtOrAbove25"),
                "Result": result,
            }
            if result == "would_warn":
                would_warn_details.append(entry)
            elif result == "unobserved":
                unobserved_details.append(entry)

    result_key = str(overall_result).strip().lower()
    if result_key == "manually_aborted":
        state = "manually_aborted"
    elif result_key == "aborted":
        state = "aborted"
    elif str(overall_result).lower() == "failed":
        state = "unstable"
    elif str(overall_result).lower() == "warning":
        state = "warning"
    elif any(str(item.get("State") or "") == "unstable" for item in interpretations):
        state = "unstable"
    elif any(str(item.get("State") or "") == "warning" for item in interpretations):
        state = "warning"
    elif interpretations:
        state = "stable"
    else:
        state = "unknown"
    outcome_summary = overall_report_outcome_summary(
        state,
        warning_category_counts,
        error_category_counts,
        interpretations,
        threshold_would_warn_count,
    )
    return {
        "State": state,
        "Result": state,
        "OutcomeClass": outcome_summary["OutcomeClass"],
        "OutcomeSummary": outcome_summary["Summary"],
        "OverallResult": overall_result,
        "SegmentCount": len(segments),
        "InterpretedSegmentCount": len(interpretations),
        "StateCounts": dict(sorted(state_counts.items())),
        "PrimaryPurposeCounts": dict(sorted(purpose_counts.items())),
        "BackendConfidenceCounts": dict(sorted(confidence_counts.items())),
        "WarningCategoryCounts": dict(sorted(warning_category_counts.items())),
        "ErrorCategoryCounts": dict(sorted(error_category_counts.items())),
        "SaturationCandidateCount": sum(1 for item in interpretations if item.get("SaturationCandidate")),
        "MemoryPathCandidateCount": sum(1 for item in interpretations if item.get("MemoryPathCandidate")),
        "DiagnosticOnlyCount": sum(1 for item in interpretations if item.get("DiagnosticOnly")),
        "StrictThresholdRecommendationWarningsEnabled": strict_threshold_enabled,
        "ReportOnlyThresholdWouldWarnCount": threshold_would_warn_count,
        "ReportOnlyThresholdUnobservedCount": threshold_unobserved_count,
        "ReportOnlyThresholdWouldWarnDetails": would_warn_details,
        "ReportOnlyThresholdUnobservedDetails": unobserved_details,
    }


def action_item_category_counts(action_items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in action_items:
        category = str(item.get("Category") or "unknown")
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def action_item_severity_counts(action_items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in action_items:
        severity = str(item.get("Severity") or "info").strip().lower()
        if severity == "warn":
            severity = "warning"
        counts[severity or "unknown"] = counts.get(severity or "unknown", 0) + 1
    return dict(sorted(counts.items()))


def build_report_summary(
    *,
    overall_result: str,
    execution_detail: str,
    elapsed: str,
    segments: List[Dict[str, Any]],
    stability_interpretation: Dict[str, Any],
    all_error_events: List[Dict[str, Any]],
    gpu_validation_details: List[Dict[str, Any]],
    skipped_stages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the complete stable compatibility report summary."""
    warning_events = [
        event for event in all_error_events if str(event.get("severity") or "").lower() == "warning"
    ]
    error_events = [
        event for event in all_error_events if str(event.get("severity") or "").lower() == "error"
    ]
    stage_summaries = [build_report_stage_summary(segment) for segment in segments]
    action_item_details = build_report_action_item_details(
        stability_interpretation,
        warning_events,
        error_events,
        skipped_stages,
    )
    action_items = [str(item.get("Message") or "") for item in action_item_details if item.get("Message")]
    worker_failure_count = 0
    worker_success_count = 0
    verification_passes = 0
    for detail in gpu_validation_details:
        status = str(detail.get("Status") or "").lower()
        if status in {"ok", "pass", "passed", "success"}:
            worker_success_count += 1
        if any(
            int(detail.get(key) or 0) > 0
            for key in (
                "ErrorCount",
                "GlErrorCount",
                "DrawMismatchCount",
                "VramMismatchCount",
                "TransferMismatchCount",
            )
        ) or status in {"error", "fail", "failed"}:
            worker_failure_count += 1
        try:
            verification_passes += int(detail.get("VerificationPasses") or 0)
        except Exception:
            pass
    return {
        "Schema": "linux_validation_suite.report_summary.v1",
        "ReferenceContract": "Legacy custom JSON compatible extension",
        "Result": overall_result,
        "ExecutionDetail": execution_detail,
        "Elapsed": elapsed,
        "OutcomeClass": stability_interpretation.get("OutcomeClass"),
        "OutcomeSummary": stability_interpretation.get("OutcomeSummary"),
        "State": stability_interpretation.get("State"),
        "DepartmentUseSummary": build_department_use_summary(
            overall_result=overall_result,
            execution_detail=execution_detail,
            stability_interpretation=stability_interpretation,
            warning_events=warning_events,
            error_events=error_events,
            skipped_stages=skipped_stages,
            worker_result_count=len(gpu_validation_details),
            worker_success_count=worker_success_count,
            worker_failure_count=worker_failure_count,
            verification_passes=verification_passes,
        ),
        "WarningCount": len(warning_events),
        "ErrorCount": len(error_events),
        "WarningCategoryCounts": dict(stability_interpretation.get("WarningCategoryCounts") or {}),
        "ErrorCategoryCounts": dict(stability_interpretation.get("ErrorCategoryCounts") or {}),
        "ReportOnlyThresholdWouldWarnCount": stability_interpretation.get("ReportOnlyThresholdWouldWarnCount", 0),
        "ReportOnlyThresholdUnobservedCount": stability_interpretation.get("ReportOnlyThresholdUnobservedCount", 0),
        "StageCount": len(segments),
        "SkippedStageCount": len(skipped_stages),
        "StageOutcomes": stage_summaries,
        # Canonical report/export contract. Text and comparison helpers may accept
        # older Passed/Failed aliases for compatibility, but new report payloads
        # should keep these explicit worker count field names.
        "GpuWorkerSummary": {
            "WorkerResultCount": len(gpu_validation_details),
            "SuccessfulWorkerResultCount": worker_success_count,
            "WorkerFailureCount": worker_failure_count,
            "VerificationPasses": verification_passes,
        },
        "ActionItems": action_items,
        "ActionItemDetails": action_item_details,
        "ActionItemCategoryCounts": action_item_category_counts(action_item_details),
        "ActionItemSeverityCounts": action_item_severity_counts(action_item_details),
        "ImportNotes": [
            "Existing Beta 8a parser-facing fields remain in Segments, SegmentDetails, GpuDetails, Metadata, and SystemInfo.",
            "ReportSummary is additive and intended for concise human review or future importer columns.",
            "No legacy importer update is required for current imports; new Linux fields are intended to be ignored by existing parsers.",
        ],
    }
