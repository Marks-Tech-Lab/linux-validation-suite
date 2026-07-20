#!/usr/bin/env python3
"""Pure text renderers for result report payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_core import APP_NAME
from .lvs_report_helpers import clean_review_verdict_from_payload
from .lvs_summary_text import SummaryTextBuilder


def format_result_metric_number(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    number = float(value)
    return f"{number:.2f}".rstrip("0").rstrip(".")


def format_result_metric_triplet(minimum: Any, average: Any, maximum: Any, unit: str) -> str:
    values = [format_result_metric_number(value) for value in (minimum, average, maximum)]
    if not any(values):
        return ""
    return f"{values[0] or '-'} / {values[1] or '-'} / {values[2] or '-'}{unit}"


def format_result_metric_pair(average: Any, maximum: Any, unit: str) -> str:
    avg = format_result_metric_number(average)
    max_value = format_result_metric_number(maximum)
    if not avg and not max_value:
        return ""
    return f"avg {avg or '-'}, max {max_value or '-'}{unit}"


def result_gpu_highlight_line(gpu: Dict[str, Any]) -> str:
    name = str(gpu.get("DisplayName") or gpu.get("Name") or f"GPU {gpu.get('GpuIndex', '?')}")
    target_ids = ", ".join(str(item) for item in gpu.get("TargetIds", []) or [])
    workloads = ", ".join(str(item) for item in gpu.get("Workloads", []) or [])
    backends = ", ".join(str(item) for item in gpu.get("Backends", []) or [])
    usage = format_result_metric_triplet(gpu.get("UsageMin"), gpu.get("UsageAvg"), gpu.get("UsageMax"), "%")
    power = format_result_metric_pair(gpu.get("PowerAvgW"), gpu.get("PowerMaxW"), "W")
    vram = format_result_metric_pair(gpu.get("VramUsedAvgGB"), gpu.get("VramUsedMaxGB"), "GiB")
    verification = gpu.get("VerificationPasses")
    allocation = gpu.get("AllocationPercent")
    parts = [f"load={gpu.get('LoadQuality') or '-'}"]
    if target_ids:
        parts.append(f"target={target_ids}")
    if workloads:
        parts.append(f"workloads={workloads}")
    if backends:
        parts.append(f"backends={backends}")
    if usage:
        parts.append(f"usage={usage}")
    if power:
        parts.append(f"power={power}")
    if vram:
        parts.append(f"vram={vram}")
    if allocation is not None:
        parts.append(f"alloc={allocation}%")
    if verification is not None:
        parts.append(f"verify={verification}")
    if bool(gpu.get("TelemetryMissing")):
        parts.append("telemetry=missing")
    return f"  - {name}: " + "; ".join(parts)


def result_overview_stage_line(index: int, stage: Dict[str, Any]) -> str:
    label = str(stage.get("Label") or stage.get("TestDescription") or f"Stage {index}")
    verdict = str(stage.get("Verdict") or stage.get("Result") or "-")
    test_type = str(stage.get("TestType") or stage.get("TestTypeDetails") or "-")
    highlights = stage.get("GpuHighlights") if isinstance(stage.get("GpuHighlights"), list) else []
    gpu_note = f", GPUs={len(highlights)}" if highlights else ""
    return f"{index}. {label}: {verdict} ({test_type}{gpu_note})"


def result_action_item_line(item: Dict[str, Any], *, include_stage: bool = False) -> str:
    severity = str(item.get("Severity") or item.get("severity") or "warning")
    category = str(item.get("Category") or item.get("category") or "action_item")
    message = str(item.get("Message") or item.get("message") or item.get("Summary") or "")
    stage_text = ""
    if include_stage:
        stage = str(item.get("Stage") or item.get("stage") or "")
        stage_text = f" [{stage}]" if stage else ""
    return f"- [{severity}] {category}{stage_text}: {message}"


def missing_result_overview_text(result_name: str) -> str:
    return (
        "Result Overview\n"
        "===============\n"
        f"Folder: {result_name}\n"
        "Parsed JSON: missing or unreadable\n"
    )


def missing_result_stage_details_text(result_name: str) -> str:
    return (
        "Result Stage Details\n"
        "====================\n"
        f"Folder: {result_name}\n"
        "Parsed JSON: missing or unreadable\n"
    )


def result_overview_text_from_payload(folder_name: str, parsed: Dict[str, Any]) -> str:
    metadata = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
    report = parsed.get("ReportSummary") if isinstance(parsed.get("ReportSummary"), dict) else {}
    department = report.get("DepartmentUseSummary") if isinstance(report.get("DepartmentUseSummary"), dict) else {}
    worker_summary = report.get("GpuWorkerSummary") if isinstance(report.get("GpuWorkerSummary"), dict) else {}
    action_items = report.get("ActionItemDetails") if isinstance(report.get("ActionItemDetails"), list) else []
    stages = report.get("StageOutcomes") if isinstance(report.get("StageOutcomes"), list) else []
    if not stages:
        stages = parsed.get("Segments") if isinstance(parsed.get("Segments"), list) else []
    review_verdict = clean_review_verdict_from_payload(parsed)

    result = str(parsed.get("Result") or metadata.get("Result") or report.get("Result") or "-")
    profile = str(
        metadata.get("ProfileName")
        or parsed.get("ProfileName")
        or parsed.get("profile_name")
        or "-"
    )
    description = str(metadata.get("Description") or metadata.get("CombinedDescription") or "-")
    status = str(department.get("Status") or "-")
    decision = str(department.get("Decision") or "-")
    workers_total = worker_summary.get("WorkerResultCount", worker_summary.get("Total", "-"))
    workers_success = worker_summary.get(
        "Successful",
        worker_summary.get("Passed", worker_summary.get("SuccessfulWorkerResultCount", "-")),
    )
    workers_failed = worker_summary.get("Failed", worker_summary.get("WorkerFailureCount", "-"))

    lines = [
        "Result Overview",
        "===============",
        f"Folder: {folder_name}",
        f"Result: {result}",
        f"Final verdict: {review_verdict.get('FinalVerdict') or 'None'}",
        f"Rule-based verdict: {review_verdict.get('RuleBasedVerdict') or 'None'}",
        f"Effective final verdict: {review_verdict.get('EffectiveFinalVerdict') or 'None'}",
        f"Profile: {profile}",
        f"Description: {description}",
        f"Department status: {status}",
        f"Decision: {decision}",
        f"GPU workers: {workers_success}/{workers_total} successful, {workers_failed} failed",
        f"Action items: {len(action_items)}",
        "",
        "Stages",
        "------",
    ]
    if stages:
        for index, stage in enumerate(stages[:12], start=1):
            if not isinstance(stage, dict):
                continue
            lines.append(result_overview_stage_line(index, stage))
        if len(stages) > 12:
            lines.append(f"... {len(stages) - 12} more stage(s)")
    else:
        lines.append("No stage outcomes found.")
    if action_items:
        lines.extend(["", "Top Action Items", "----------------"])
        for item in action_items[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(result_action_item_line(item))
        if len(action_items) > 5:
            lines.append(f"... {len(action_items) - 5} more action item(s)")
    return "\n".join(lines) + "\n"


def result_stage_details_text_from_payload(folder_name: str, parsed: Dict[str, Any]) -> str:
    report = parsed.get("ReportSummary") if isinstance(parsed.get("ReportSummary"), dict) else {}
    stages = report.get("StageOutcomes") if isinstance(report.get("StageOutcomes"), list) else []
    action_items = report.get("ActionItemDetails") if isinstance(report.get("ActionItemDetails"), list) else []
    lines = [
        "Result Stage Details",
        "====================",
        f"Folder: {folder_name}",
        "",
    ]
    if not stages:
        lines.append("No ReportSummary.StageOutcomes entries found.")
        return "\n".join(lines) + "\n"

    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            continue
        label = str(stage.get("Label") or stage.get("TestDescription") or f"Stage {index}")
        verdict = str(stage.get("Verdict") or stage.get("Result") or "-")
        test_type = str(stage.get("TestType") or stage.get("TestTypeDetails") or "-")
        outcome = str(stage.get("OutcomeClass") or "-")
        summary = str(stage.get("OutcomeSummary") or "")
        lines.extend(
            [
                f"{index}. {label}",
                "-" * (len(str(index)) + len(label) + 2),
                f"Verdict: {verdict}",
                f"Type: {test_type}",
                f"Outcome: {outcome}",
            ]
        )
        if summary:
            lines.append(f"Summary: {summary}")
        warning_counts = stage.get("WarningCategoryCounts") if isinstance(stage.get("WarningCategoryCounts"), dict) else {}
        error_counts = stage.get("ErrorCategoryCounts") if isinstance(stage.get("ErrorCategoryCounts"), dict) else {}
        if warning_counts:
            lines.append(f"Warnings: {warning_counts}")
        if error_counts:
            lines.append(f"Errors: {error_counts}")
        coverage_notes = stage.get("CoverageNotes") if isinstance(stage.get("CoverageNotes"), list) else []
        for note in coverage_notes[:4]:
            lines.append(f"Coverage: {note}")

        highlights = stage.get("GpuHighlights") if isinstance(stage.get("GpuHighlights"), list) else []
        if highlights:
            lines.append("GPU Highlights:")
            for gpu in highlights:
                if not isinstance(gpu, dict):
                    continue
                lines.append(result_gpu_highlight_line(gpu))
        else:
            lines.append("GPU Highlights: none")
        lines.append("")

    stage_labels = {
        str(stage.get("Label") or "")
        for stage in stages
        if isinstance(stage, dict) and str(stage.get("Label") or "")
    }
    related_items = [
        item for item in action_items
        if isinstance(item, dict)
        and (not item.get("Stage") or str(item.get("Stage")) in stage_labels)
    ]
    if related_items:
        lines.extend(["Action Items", "------------"])
        for item in related_items[:12]:
            lines.append(result_action_item_line(item, include_stage=True))
        if len(related_items) > 12:
            lines.append(f"... {len(related_items) - 12} more action item(s)")
    return "\n".join(lines).rstrip() + "\n"


def result_validation_batch_line(item: Dict[str, Any]) -> str:
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    return (
        f"- {Path(str(item.get('result_folder'))).name}: "
        f"{str(item.get('result')).upper()} ({summary.get('errors', 0)}e/{summary.get('warnings', 0)}w)"
    )


def pre_import_batch_line(item: Dict[str, Any]) -> str:
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    refresh = item.get("summary_refresh") if isinstance(item.get("summary_refresh"), dict) else {}
    return (
        f"- {item.get('folder_name')}: {str(item.get('result')).upper()} "
        f"({summary.get('errors', 0)}e/{summary.get('warnings', 0)}w, "
        f"summary_refreshed={bool(refresh.get('refreshed'))})"
    )


def artifact_value_text(value: Any, suffix: str) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except Exception:
        return str(value)
    if numeric != numeric:
        return "-"
    if abs(numeric - round(numeric)) < 0.005:
        rendered = str(int(round(numeric)))
    else:
        rendered = f"{numeric:.2f}".rstrip("0").rstrip(".")
    return f"{rendered}{suffix}"


def artifact_range_text(avg_value: Any, max_value: Any, suffix: str) -> str:
    avg_text = artifact_value_text(avg_value, suffix)
    max_text = artifact_value_text(max_value, suffix)
    if avg_text == "-" and max_text == "-":
        return "-"
    return f"avg {avg_text}, max {max_text}"


def artifact_gpu_highlight_text(highlight: Dict[str, Any]) -> str:
    name = highlight.get("Name") or f"GPU {highlight.get('GpuIndex', '?')}"
    parts = [f"busy {artifact_range_text(highlight.get('UsageAvg'), highlight.get('UsageMax'), '%')}"]
    power = artifact_range_text(highlight.get("PowerAvgW"), highlight.get("PowerMaxW"), "W")
    if power != "-":
        parts.append(f"power {power}")
    memory_busy = artifact_range_text(highlight.get("MemoryBusyAvg"), highlight.get("MemoryBusyMax"), "%")
    if memory_busy != "-":
        parts.append(f"mem busy {memory_busy}")
    vram = artifact_value_text(highlight.get("VramUsedMaxGB"), "GiB")
    if vram != "-":
        parts.append(f"vram max {vram}")
    allocation = artifact_value_text(highlight.get("AllocationPercent"), "%")
    if allocation != "-":
        parts.append(f"allocation {allocation}")
    verification = highlight.get("VerificationPasses")
    if verification:
        parts.append(f"verify {verification}")
    backends = highlight.get("Backends") if isinstance(highlight.get("Backends"), list) else []
    if backends:
        parts.append("backend " + ",".join(str(item) for item in backends if str(item)))
    target_ids = highlight.get("TargetIds") if isinstance(highlight.get("TargetIds"), list) else []
    if target_ids:
        parts.append("target " + ",".join(str(item) for item in target_ids if str(item)))
    return f"{name}: " + "; ".join(parts)


def artifact_detail_text(
    prepared: Dict[str, Any],
    dependency_summary_builder: Optional[Callable[[Dict[str, Any], Optional[Path]], str]] = None,
) -> str:
    report_envelope = prepared.get("report") if isinstance(prepared.get("report"), dict) else {}
    detail_payload = prepared.get("detail_payload") if isinstance(prepared.get("detail_payload"), dict) else {}
    item = report_envelope.get("inventory_item") if isinstance(report_envelope.get("inventory_item"), dict) else {}
    result_dir = Path(str(report_envelope.get("result_folder") or ""))
    kind = str(item.get("kind") or detail_payload.get("kind") or "")
    lines = [
        "",
        "Result Artifact Details",
        "=======================",
        f"Folder: {result_dir}",
        f"Kind: {item.get('kind')}",
    ]
    if item.get("profile_name"):
        lines.append(f"Profile: {item.get('profile_name')}")
    lines.append(f"Result: {item.get('result') or 'unknown'}")
    if item.get("outcome_class"):
        lines.append(f"Outcome class: {item.get('outcome_class')}")
    if item.get("stage_count"):
        lines.append(f"Stages: {item.get('stage_count')}")
    if item.get("validation_errors") or item.get("validation_warnings"):
        lines.append(
            f"Validation: {item.get('validation_errors', 0)} error(s), "
            + f"{item.get('validation_warnings', 0)} warning(s)"
        )
    if item.get("validation_issue_category_counts"):
        lines.append(f"Validation categories: {item.get('validation_issue_category_counts')}")
    if item.get("action_items"):
        lines.append(f"Action items: {item.get('action_items')}")
    lines.extend([f"Modified: {item.get('modified')}", "Artifacts:"])
    lines.extend(f"  - {artifact}" for artifact in item.get("artifacts") or [])
    lines.extend(f"  [note] {note}" for note in item.get("notes") or [])

    if kind == "run_result":
        _append_run_artifact_detail_lines(lines, detail_payload)
    elif kind in {"preflight", "diagnostics"}:
        _append_plan_artifact_detail_lines(lines, detail_payload)
    elif kind == "dependency_check":
        _append_dependency_artifact_detail_lines(lines, detail_payload, result_dir, dependency_summary_builder)
    elif kind == "profile_audit":
        _append_profile_audit_artifact_detail_lines(lines, detail_payload)
    elif kind == "results_inventory":
        _append_results_inventory_artifact_detail_lines(lines, detail_payload)
    elif kind == "result_validation_batch":
        _append_result_validation_batch_artifact_detail_lines(lines, detail_payload)
    elif kind == "pre_import_sanity_batch":
        _append_pre_import_sanity_batch_artifact_detail_lines(lines, detail_payload)
    else:
        lines.append("No specialized detail parser is available for this artifact kind.")
    return "\n".join(lines) + "\n"


def _append_run_artifact_detail_lines(lines: List[str], payload: Dict[str, Any]) -> None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    department = payload.get("department") if isinstance(payload.get("department"), dict) else {}
    stage_outcomes = payload.get("stage_outcomes") if isinstance(payload.get("stage_outcomes"), list) else []
    action_items = payload.get("action_items") if isinstance(payload.get("action_items"), list) else []
    lines.extend(["", "Run Summary", "-----------"])
    if department:
        lines.append(f"Department use: {SummaryTextBuilder(APP_NAME)._format_department_status(department.get('Status'))}")
        lines.append(f"Decision: {department.get('Decision') or '-'}")
        lines.append(f"Blocking: {bool(department.get('Blocking'))}")
    if report.get("OutcomeSummary"):
        lines.append(f"Outcome: {report.get('OutcomeSummary')}")
    for label, key in (
        ("Warnings by category", "warning_categories"),
        ("Errors by category", "error_categories"),
        ("GPU worker summary", "gpu_worker_summary"),
        ("Action item severities", "action_item_severity_counts"),
        ("Action item categories", "action_item_category_counts"),
    ):
        if details.get(key):
            lines.append(f"{label}: {details.get(key)}")
    if stage_outcomes:
        lines.append("Stages:")
        for stage in stage_outcomes[:12]:
            if not isinstance(stage, dict):
                continue
            label = stage.get("Label") or stage.get("Stage") or "stage"
            verdict = stage.get("Verdict") or stage.get("Result") or "-"
            outcome = stage.get("OutcomeClass") or "-"
            targeted = stage.get("TargetedGpuCount")
            suffix = f", targeted_gpus={targeted}" if targeted is not None else ""
            lines.append(f"  - {label}: {verdict}, outcome={outcome}{suffix}")
            highlights = stage.get("GpuHighlights") if isinstance(stage.get("GpuHighlights"), list) else []
            for highlight in highlights[:4]:
                if isinstance(highlight, dict):
                    lines.append(f"    GPU: {artifact_gpu_highlight_text(highlight)}")
            if len(highlights) > 4:
                lines.append(f"    ... {len(highlights) - 4} more GPU highlight(s)")
        if len(stage_outcomes) > 12:
            lines.append(f"  ... {len(stage_outcomes) - 12} more stage(s)")
    if action_items:
        lines.append("Action items:")
        for action in action_items[:12]:
            if not isinstance(action, dict):
                continue
            severity = action.get("Severity") or action.get("severity") or "info"
            category = action.get("Category") or action.get("category") or "general"
            message = action.get("Message") or action.get("message") or action.get("Summary") or ""
            lines.append(f"  - [{severity}] {category}: {message}")
        if len(action_items) > 12:
            lines.append(f"  ... {len(action_items) - 12} more action item(s)")


def _append_plan_artifact_detail_lines(lines: List[str], payload: Dict[str, Any]) -> None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    plan = payload.get("plan") if isinstance(payload.get("plan"), list) else []
    lines.extend(["", "Plan Summary", "------------", f"Runnable: {details.get('runnable')}"])
    if details.get("enabled_stage_count") is not None:
        lines.append(f"Runnable stages: {details.get('runnable_stage_count', 0)}/{details.get('enabled_stage_count', 0)}")
    lines.append(f"Validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    lines.extend(f"  [error] {error}" for error in errors[:8])
    if len(errors) > 8:
        lines.append(f"  ... {len(errors) - 8} more error(s)")
    lines.extend(f"  [warn] {warning}" for warning in warnings[:8])
    if len(warnings) > 8:
        lines.append(f"  ... {len(warnings) - 8} more warning(s)")
    if plan:
        lines.append("Stages:")
        for stage in plan[:12]:
            if not isinstance(stage, dict):
                continue
            label = stage.get("label") or stage.get("stage_id") or "stage"
            status = "disabled" if not stage.get("enabled") else "runnable" if stage.get("runnable") else "blocked"
            workloads = ", ".join(stage.get("workloads") or []) or "-"
            backend_usage = stage.get("backend_usage") if isinstance(stage.get("backend_usage"), dict) else {}
            backend_bits = [
                f"{key}={backend_usage[key]}"
                for key in ("cpu", "memory", "gpu_3d", "vram")
                if backend_usage.get(key)
            ]
            backend_text = f" | {'; '.join(backend_bits)}" if backend_bits else ""
            lines.append(f"  - {label}: {status}, workloads={workloads}{backend_text}")
        if len(plan) > 12:
            lines.append(f"  ... {len(plan) - 12} more stage(s)")
    lines.append(f"Full details: {payload.get('full_detail_name')}")


def _append_dependency_artifact_detail_lines(
    lines: List[str],
    payload: Dict[str, Any],
    result_dir: Path,
    dependency_summary_builder: Optional[Callable[[Dict[str, Any], Optional[Path]], str]],
) -> None:
    dependency = payload.get("dependency") if isinstance(payload.get("dependency"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    lines.extend(["", "Dependency Summary", "------------------"])
    summary_path = result_dir / "dependency_check_summary.txt"
    if summary_path.exists():
        try:
            lines.append(summary_path.read_text(encoding="utf-8").strip())
            return
        except Exception as exc:
            lines.append(f"dependency_check_summary.txt could not be read: {exc}")
    if dependency and not dependency.get("_read_error") and dependency_summary_builder is not None:
        lines.append(dependency_summary_builder(dependency, result_dir).strip())
        return
    if not checks:
        lines.append("Structured dependency checks were not found; see dependency_check.txt for details.")
        return
    lines.append(f"Checks: {len(checks)}")
    for name, detail in list(checks.items())[:20]:
        if isinstance(detail, dict):
            available = detail.get("available")
            reason = detail.get("reason") or detail.get("detail") or ""
            suffix = f" ({reason})" if reason else ""
            lines.append(f"  - {name}: available={available}{suffix}")
        else:
            lines.append(f"  - {name}: {detail}")
    if len(checks) > 20:
        lines.append(f"  ... {len(checks) - 20} more check(s)")


def _append_profile_audit_artifact_detail_lines(lines: List[str], payload: Dict[str, Any]) -> None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    profiles = payload.get("profiles") if isinstance(payload.get("profiles"), list) else []
    lines.extend(
        [
            "",
            "Profile Audit Summary",
            "---------------------",
            f"Profiles: {details.get('profile_count')} total, "
            + f"{details.get('runnable_profile_count')} runnable, {details.get('blocked_profile_count')} blocked",
            f"Validation: {details.get('validation_errors')} error(s), {details.get('validation_warnings')} warning(s)",
        ]
    )
    for profile in profiles[:20]:
        if not isinstance(profile, dict):
            continue
        name = profile.get("profile_name") or profile.get("profile_file") or "profile"
        status = "runnable" if profile.get("runnable") else "blocked"
        if not profile.get("loaded"):
            status = "load_failed"
        lines.append(f"  - {name}: {status}, stages={profile.get('runnable_stage_count', 0)}/{profile.get('enabled_stage_count', 0)}")
        lines.extend(f"    [error] {error}" for error in list(profile.get("errors") or [])[:2])
        lines.extend(f"    [warn] {warning}" for warning in list(profile.get("warnings") or [])[:2])
    if len(profiles) > 20:
        lines.append(f"  ... {len(profiles) - 20} more profile(s)")


def _append_results_inventory_artifact_detail_lines(lines: List[str], payload: Dict[str, Any]) -> None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines.extend(
        [
            "",
            "Results Inventory Summary",
            "-------------------------",
            f"Artifacts: {details.get('artifact_count')}",
            f"By kind: {details.get('by_kind')}",
            f"By result: {details.get('by_result')}",
        ]
    )
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        folder = item.get("folder_name") or Path(str(item.get("folder") or "")).name or "artifact"
        kind = item.get("kind") or "unknown"
        descriptor = item.get("profile_name") or kind
        result = item.get("result") or "unknown"
        lines.append(f"  - {folder}: {kind}, {descriptor}, {result}")
    if len(items) > 20:
        lines.append(f"  ... {len(items) - 20} more artifact(s)")


def _append_result_validation_batch_artifact_detail_lines(lines: List[str], payload: Dict[str, Any]) -> None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines.extend(
        [
            "",
            "Batch Validation Summary",
            "------------------------",
            f"Results checked: {details.get('result_count')}",
            f"Validation: {details.get('errors')} error(s), {details.get('warnings')} warning(s)",
            f"By result: {details.get('by_result')}",
        ]
    )
    if details.get("issue_category_counts"):
        lines.append(f"Issue categories: {details.get('issue_category_counts')}")
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        folder = item.get("folder_name") or Path(str(item.get("folder") or "")).name or "result"
        result = item.get("result") or "unknown"
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        errors = int(summary.get("errors") or 0)
        warnings = int(summary.get("warnings") or 0)
        categories = summary.get("issue_category_counts") if isinstance(summary.get("issue_category_counts"), dict) else {}
        suffix = f", categories={categories}" if categories else ""
        lines.append(f"  - {folder}: {result}, {errors}e/{warnings}w{suffix}")
    if len(items) > 20:
        lines.append(f"  ... {len(items) - 20} more validation result(s)")


def _append_pre_import_sanity_batch_artifact_detail_lines(lines: List[str], payload: Dict[str, Any]) -> None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines.extend(
        [
            "",
            "Batch Pre-Import Sanity Summary",
            "-------------------------------",
            f"Results checked: {details.get('result_count')}",
            f"Validation: {details.get('errors')} error(s), {details.get('warnings')} warning(s)",
            f"Run summaries: {details.get('summary_refreshed')} refreshed, {details.get('summary_refresh_failed')} failed",
            f"By result: {details.get('by_result')}",
        ]
    )
    if details.get("issue_category_counts"):
        lines.append(f"Issue categories: {details.get('issue_category_counts')}")
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        folder = item.get("folder_name") or Path(str(item.get("folder") or "")).name or "result"
        result = item.get("result") or "unknown"
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        refreshed = bool((item.get("summary_refresh") or {}).get("refreshed")) if isinstance(item.get("summary_refresh"), dict) else False
        errors = int(summary.get("errors") or 0)
        warnings = int(summary.get("warnings") or 0)
        lines.append(f"  - {folder}: {result}, {errors}e/{warnings}w, summary_refreshed={refreshed}")
    if len(items) > 20:
        lines.append(f"  ... {len(items) - 20} more sanity result(s)")


def result_validation_issue_line(issue: Dict[str, Any]) -> str:
    return f"[{issue.get('severity', 'info')}] {issue.get('category', 'general')}: {issue.get('message', '')}"


def result_validation_text(payload: Dict[str, Any]) -> str:
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "",
        "Result Folder Validation",
        f"Folder: {payload.get('result_folder')}",
    ]
    early_categories = {"missing_file", "json_parse", "json_shape"}
    if not summary or (
        not payload.get("checks")
        and len(issues) == 1
        and str(issues[0].get("category") or "") in early_categories
    ):
        if issues:
            first_issue = issues[0]
            lines.append(f"  [{first_issue.get('severity')}] {first_issue.get('message')}")
        return "\n".join(lines) + "\n"

    error_count = int(summary.get("errors") or 0)
    warning_count = int(summary.get("warnings") or 0)
    result = str(payload.get("result") or "unknown")
    issue_category_counts = summary.get("issue_category_counts") if isinstance(summary.get("issue_category_counts"), dict) else {}
    lines.extend(
        [
            f"Result: {result.upper()} ({error_count} error(s), {warning_count} warning(s))",
            f"Segments: {int(summary.get('segments') or 0)}",
            f"GPU worker details: {int(summary.get('gpu_worker_details') or 0)}",
            f"GPU highlights: {int(summary.get('gpu_highlights') or 0)}",
            f"Action items: {int(summary.get('action_items') or 0)}",
        ]
    )
    if issue_category_counts:
        lines.append(f"Issue categories: {dict(sorted(issue_category_counts.items()))}")
    if issues:
        lines.append("")
        lines.append("Issues:")
        for issue in issues:
            if isinstance(issue, dict):
                lines.append(f"  [{issue['severity']}] {issue['category']}: {issue['message']}")
    else:
        lines.append("No compatibility/report consistency issues found.")
    return "\n".join(lines) + "\n"


def batch_result_validation_text(payload: Dict[str, Any]) -> str:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines = [
        "",
        "Batch Result Validation",
        "=======================",
        f"Results folder: {payload.get('results_dir')}",
        "Excluded root folders: Archived, Uploaded",
        f"Result: {str(payload.get('result') or 'unknown').upper()}",
        f"Folders checked: {counts.get('total', 0)}",
        f"Validation: {counts.get('errors', 0)} error(s), {counts.get('warnings', 0)} warning(s)",
        f"By result: {counts.get('by_result') or {}}",
    ]
    if counts.get("issue_category_counts"):
        lines.append(f"Issue categories: {counts.get('issue_category_counts')}")
    if not items:
        lines.append("No completed result folders were checked.")
        return "\n".join(lines) + "\n"
    lines.extend(["", "Checked folders", "---------------"])
    for item in items[:80]:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        categories = summary.get("issue_category_counts") if isinstance(summary.get("issue_category_counts"), dict) else {}
        suffix = f", categories={categories}" if categories else ""
        lines.append(
            f"- {item.get('folder_name')}: {str(item.get('result') or 'unknown').upper()} "
            + f"({int(summary.get('errors') or 0)}e/{int(summary.get('warnings') or 0)}w{suffix})"
        )
    if len(items) > 80:
        lines.append(f"... {len(items) - 80} more folder(s) in saved JSON.")
    lines.append("")
    return "\n".join(lines) + "\n"


def result_comparison_text(payload: Dict[str, Any]) -> str:
    baseline_summary = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else {}
    comparison_summary = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    deltas = payload.get("deltas") if isinstance(payload.get("deltas"), dict) else {}
    lines = [
        "",
        "Result Folder Comparison",
        f"Baseline:   {payload.get('baseline_folder')}",
        f"Comparison: {payload.get('comparison_folder')}",
        "",
        "Overall",
        "-------",
        f"Result: {baseline_summary.get('result')} -> {comparison_summary.get('result')}",
        f"Outcome: {baseline_summary.get('outcome_class')} -> {comparison_summary.get('outcome_class')}",
        f"Elapsed: {baseline_summary.get('elapsed')} -> {comparison_summary.get('elapsed')}",
        "",
        "Category Deltas",
        "---------------",
    ]
    lines.extend(_comparison_delta_lines("Warning", deltas.get("warning_categories")))
    lines.extend(_comparison_delta_lines("Error", deltas.get("error_categories")))
    lines.extend(["", "GPU Worker Deltas", "-----------------"])
    lines.extend(_comparison_delta_lines("Worker", deltas.get("gpu_worker_summary")))
    lines.extend(["", "Action Item Deltas", "------------------"])
    lines.extend(_comparison_delta_lines("Action category", deltas.get("action_item_categories")))
    lines.extend(_comparison_delta_lines("Action severity", deltas.get("action_item_severities")))
    lines.extend(["", "Stages", "------"])

    stage_deltas = deltas.get("stages") if isinstance(deltas.get("stages"), list) else []
    if not stage_deltas:
        lines.append("No stage differences found.")
    for stage in stage_deltas:
        if not isinstance(stage, dict):
            continue
        lines.append(f"- {stage['label']}")
        if stage.get("status") != "common":
            lines.append(f"  status: {stage.get('status')}")
            continue
        for change in stage.get("changes", []):
            lines.append(f"  {change}")
        for gpu in stage.get("gpu_highlight_deltas", []):
            if not isinstance(gpu, dict):
                continue
            lines.append(f"  GPU {gpu.get('name')}:")
            if gpu.get("status") != "common":
                lines.append(f"    status: {gpu.get('status')}")
                continue
            for change in gpu.get("changes", []):
                lines.append(f"    {change}")
            gpu_deltas = gpu.get("deltas") if isinstance(gpu.get("deltas"), dict) else {}
            for metric, delta in gpu_deltas.items():
                delta = delta if isinstance(delta, dict) else {}
                lines.append(
                    f"    {metric}: {delta.get('baseline')} -> {delta.get('comparison')} "
                    + f"(delta {delta.get('delta')})"
                )
    return "\n".join(lines) + "\n"


def selected_pre_import_sanity_text(
    payload: Dict[str, Any],
    comparison_status_text: str = "",
) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    summary_status = payload.get("summary_refresh") if isinstance(payload.get("summary_refresh"), dict) else {}
    comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    comparison_text = comparison_status_text or (result_comparison_text(comparison) if comparison else "")
    lines = [
        "",
        "Pre-Import Sanity Check",
        "=======================",
        f"Folder: {payload.get('result_folder')}",
        "",
        "Validation",
        "----------",
        result_validation_text(validation).strip() or "(validation produced no output)",
        "",
        "Run Summary",
        "-----------",
    ]
    if summary_status.get("refreshed"):
        lines.append(f"Refreshed: {summary_status.get('summary_path')}")
    else:
        lines.append(f"Refresh failed: {summary_status.get('error') or 'unknown error'}")
    if comparison_text:
        lines.extend(["", "Comparison", "----------", comparison_text.strip()])
    else:
        lines.extend(["", "Comparison", "----------", "Skipped"])
    lines.append("")
    return "\n".join(lines)


def batch_pre_import_sanity_text(payload: Dict[str, Any]) -> str:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    refresh = payload.get("summary_refresh") if isinstance(payload.get("summary_refresh"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines = [
        "",
        "Batch Pre-Import Sanity Check",
        "=============================",
        f"Results folder: {payload.get('results_dir')}",
        "Excluded root folders: Archived, Uploaded",
        f"Result: {str(payload.get('result') or 'unknown').upper()}",
        f"Folders checked: {counts.get('total', 0)}",
        f"Validation: {counts.get('errors', 0)} error(s), {counts.get('warnings', 0)} warning(s)",
        f"Run summaries: {refresh.get('refreshed', 0)} refreshed, {refresh.get('failed', 0)} failed",
        f"By result: {counts.get('by_result') or {}}",
    ]
    if counts.get("issue_category_counts"):
        lines.append(f"Issue categories: {counts.get('issue_category_counts')}")
    if not items:
        lines.append("No completed result folders were checked.")
        return "\n".join(lines) + "\n"
    lines.extend(["", "Checked folders", "---------------"])
    for item in items[:80]:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        refresh_status = item.get("summary_refresh") if isinstance(item.get("summary_refresh"), dict) else {}
        error_text = f", refresh_error={refresh_status.get('error')}" if refresh_status.get("error") else ""
        lines.append(
            f"- {item.get('folder_name')}: {str(item.get('result') or 'unknown').upper()} "
            + f"({int(summary.get('errors') or 0)}e/{int(summary.get('warnings') or 0)}w, "
            + f"summary_refreshed={bool(refresh_status.get('refreshed'))}{error_text})"
        )
    if len(items) > 80:
        lines.append(f"... {len(items) - 80} more folder(s) in saved JSON.")
    lines.append("")
    return "\n".join(lines) + "\n"


def _comparison_delta_lines(label: str, deltas: Any) -> List[str]:
    if not isinstance(deltas, dict) or not deltas:
        return [f"{label}: no changes"]
    return [
        f"{label} {key}: {delta.get('baseline')} -> {delta.get('comparison')} "
        + f"(delta {delta.get('delta')})"
        for key, raw_delta in deltas.items()
        for delta in [raw_delta if isinstance(raw_delta, dict) else {}]
    ]
