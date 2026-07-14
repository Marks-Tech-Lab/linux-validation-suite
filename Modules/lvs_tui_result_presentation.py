"""Textual-free result presentation helpers for the optional TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def result_selection_required_presentation() -> str:
    return (
        "Select a result folder first.\n\n"
        "Use the result list to highlight a folder, then choose a result action."
    )


def result_summary_presentation(overview_text: str, summary_text: str, action_help_text: str) -> str:
    return (
        str(overview_text)
        + "\n"
        "Run Summary\n"
        "===========\n\n"
        + str(summary_text)
        + "\n\n"
        + str(action_help_text)
        + "\n"
    )


def result_stage_details_presentation(stage_details_text: str, action_help_text: str) -> str:
    return str(stage_details_text) + "\n" + str(action_help_text) + "\n"


def _artifact_category_paths(result_dir: Path, artifact_names: set[str]) -> Dict[str, list[Path]]:
    categories = {
        "Core result": [
            "parsed_results_custom.json",
            "run_summary.txt",
            "run_manifest.json",
            "run_metadata.json",
            "profile_used.json",
            "system_info.json",
        ],
        "Telemetry / source evidence": [
            "raw_telemetry.csv",
            "telemetry_source_map.json",
            "telemetry_capabilities.json",
        ],
        "Reports / review": [
            "result_validation.json",
            "result_validation.txt",
            "pre_import_sanity.json",
            "pre_import_sanity.txt",
            "artifact_details.json",
            "artifact_details.txt",
        ],
        "Preflight / diagnostics": [
            "preflight_report.json",
            "preflight_summary.txt",
            "diagnostics.json",
            "diagnostics_summary.txt",
            "dependency_check.json",
            "dependency_check.txt",
            "dependency_check_summary.txt",
            "profile_audit.json",
            "profile_audit.txt",
        ],
    }
    grouped: Dict[str, list[Path]] = {}
    for label, names in categories.items():
        paths = [result_dir / name for name in names if name in artifact_names or (result_dir / name).exists()]
        if paths:
            grouped[label] = paths

    comparison_paths = [
        path
        for pattern in ("result_comparison_vs_*.json", "result_comparison_vs_*.txt")
        for path in sorted(result_dir.glob(pattern))
        if path.is_file()
    ]
    comparison_paths.extend(
        result_dir / name
        for name in sorted(artifact_names)
        if name.startswith("result_comparison_vs_") and name not in {path.name for path in comparison_paths}
    )
    if comparison_paths:
        grouped["Comparisons"] = comparison_paths

    debug_paths = [
        result_dir / "advanced_debug" / "advanced_debug_log.txt",
        result_dir / "advanced_debug" / "advanced_debug_manifest.json",
        result_dir / "advanced_debug" / "heatsoak" / "heatsoak_debug_log.txt",
        result_dir / "advanced_debug" / "heatsoak" / "heatsoak_debug_manifest.json",
    ]
    existing_debug_paths = [path for path in debug_paths if path.exists()]
    if existing_debug_paths:
        grouped["Debug logs"] = existing_debug_paths
    return grouped


def result_artifact_browser_presentation(
    result_dir: Path,
    inventory_item: Dict[str, Any],
    detail_text: str,
    action_help_text: str,
) -> str:
    artifact_names = {str(name) for name in inventory_item.get("artifacts") or [] if str(name)}
    grouped_paths = _artifact_category_paths(result_dir, artifact_names)
    shown_names = {path.name for paths in grouped_paths.values() for path in paths}
    other_paths = [result_dir / name for name in sorted(artifact_names - shown_names)]

    lines = [
        "Selected Result Artifacts",
        "=========================",
        f"Folder: {result_dir}",
        f"Kind: {inventory_item.get('kind') or 'unknown'}",
        f"Result: {inventory_item.get('result') or 'unknown'}",
        "",
        "Artifact Map",
        "------------",
    ]
    if not grouped_paths and not other_paths:
        lines.append("No known artifacts were found for this selected result.")
    for label, paths in grouped_paths.items():
        lines.append(f"{label}:")
        lines.extend(f"  - {path.name} -> {path}" for path in paths)
    if other_paths:
        lines.append("Other artifacts:")
        lines.extend(f"  - {path.name} -> {path}" for path in other_paths)
    lines.extend(
        [
            "",
            "Detailed Artifact Report",
            "------------------------",
            str(detail_text).strip(),
            "",
            "Operator Next Steps",
            "-------------------",
            "- Use E to return to QA review after checking artifact availability.",
            "- Use V or M if validation or pre-import status still needs review.",
            "",
            str(action_help_text),
            "",
        ]
    )
    return "\n".join(lines)


def _qa_operator_next_steps(payload: Dict[str, Any], operator_action_hint: str = "") -> list[str]:
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    review = decisions.get("review") if isinstance(decisions.get("review"), dict) else {}
    import_status = decisions.get("import") if isinstance(decisions.get("import"), dict) else {}
    compare = decisions.get("compare") if isinstance(decisions.get("compare"), dict) else {}
    escalate = decisions.get("escalate") if isinstance(decisions.get("escalate"), dict) else {}
    validation = payload.get("validation_status") if isinstance(payload.get("validation_status"), dict) else {}
    worker = payload.get("worker_failure_evidence") if isinstance(payload.get("worker_failure_evidence"), dict) else {}

    review_status = str(review.get("status") or "").lower()
    import_blocking = bool(import_status.get("blocking"))
    import_result = str(import_status.get("status") or "").lower()
    compare_status = str(compare.get("status") or "").lower()
    validation_errors = int(validation.get("errors") or 0)
    worker_failures = int(worker.get("worker_failure_count") or 0)

    steps: list[str] = []
    if review_status in {"blocked", "failed", "missing", "error"}:
        steps.append("- Review is blocked; inspect validation and artifacts before escalating.")
    if validation_errors or worker_failures or escalate.get("needed"):
        steps.append("- Escalate or troubleshoot before treating this result as clean.")
    if import_blocking or import_result in {"fail", "failed", "blocked", "error"}:
        steps.append("- Do not import yet; run or review pre-import sanity details.")
    if compare_status in {"ready", "ready_no_baseline_selected", "not_compared"}:
        steps.append("- Compare against a known-good baseline when comparison is required.")
    if not steps:
        steps.append("- Review artifacts, compare if needed, then follow the established import/sign-off path.")
    steps.append(operator_action_hint or "- Use F for artifacts, V for validation, M for pre-import, or O for comparison.")
    return steps


def result_workflow_followup_presentation(workflow_text: str, action_help_text: str, *, context: str) -> str:
    context_steps = {
        "artifact": [
            "- Use E to return to QA review after checking artifact availability.",
            "- Use V or M if validation or pre-import status still needs review.",
        ],
        "comparison": [
            "- Use E to review the comparison result readiness after comparing.",
            "- Use M for pre-import sanity if the comparison supports review/sign-off.",
        ],
        "validation": [
            "- Use E to refresh QA review after reading validation output.",
            "- Use F for artifacts or M for pre-import sanity if blockers remain.",
        ],
        "validation_batch": [
            "- Select a result folder, then use E for QA review or F for artifacts.",
            "- Use M for selected pre-import sanity when a result needs import review.",
        ],
        "pre_import": [
            "- Use E to return to QA review after reading pre-import status.",
            "- Use O to compare against a baseline if import review needs comparison evidence.",
        ],
        "pre_import_batch": [
            "- Select a result folder, then use E for QA review or M for selected pre-import detail.",
            "- Use O to compare a selected result against a baseline when needed.",
        ],
    }
    steps = context_steps.get(context, ["- Use E for QA review, F for artifacts, V for validation, or M for pre-import."])
    return (
        str(workflow_text).rstrip()
        + "\n\n"
        "Operator Next Steps\n"
        "-------------------\n"
        + "\n".join(steps)
        + "\n\n"
        + str(action_help_text)
        + "\n"
    )


def qa_result_review_presentation(
    payload: Dict[str, Any],
    action_help_text: str,
    *,
    operator_action_hint: str = "",
) -> str:
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    review = decisions.get("review") if isinstance(decisions.get("review"), dict) else {}
    import_status = decisions.get("import") if isinstance(decisions.get("import"), dict) else {}
    compare = decisions.get("compare") if isinstance(decisions.get("compare"), dict) else {}
    escalate = decisions.get("escalate") if isinstance(decisions.get("escalate"), dict) else {}
    validation = payload.get("validation_status") if isinstance(payload.get("validation_status"), dict) else {}
    worker = payload.get("worker_failure_evidence") if isinstance(payload.get("worker_failure_evidence"), dict) else {}
    action_items = payload.get("action_item_summary") if isinstance(payload.get("action_item_summary"), dict) else {}
    telemetry = (
        payload.get("telemetry_stability_warning_summary")
        if isinstance(payload.get("telemetry_stability_warning_summary"), dict)
        else {}
    )
    artifacts = payload.get("artifact_availability") if isinstance(payload.get("artifact_availability"), dict) else {}

    lines = [
        "QA Review",
        "=========",
        f"Folder: {identity.get('folder_name') or payload.get('result_folder') or '-'}",
        f"Result: {identity.get('result') or '-'}",
        f"Outcome: {identity.get('outcome_class') or '-'}",
        f"Review: {review.get('status') or '-'}",
        f"Import: {import_status.get('status') or '-'} (blocking={bool(import_status.get('blocking'))})",
        f"Compare: {compare.get('status') or '-'}",
        f"Escalate: {'yes' if escalate.get('needed') else 'no'}",
    ]
    if escalate.get("reasons"):
        lines.append(f"Escalation reasons: {', '.join(str(item) for item in escalate.get('reasons') or [])}")
    lines.extend(
        [
            "",
            "Operator Next Steps",
            "-------------------",
            *_qa_operator_next_steps(payload, operator_action_hint),
            "",
            "Validation",
            "----------",
            f"Result: {validation.get('result') or '-'}",
            f"Errors: {int(validation.get('errors') or 0)}",
            f"Warnings: {int(validation.get('warnings') or 0)}",
            f"Issue categories: {dict(validation.get('issue_category_counts') or {})}",
            "",
            "Worker Evidence",
            "---------------",
            "GPU workers: "
            + f"{int(worker.get('successful_worker_result_count') or 0)}/"
            + f"{int(worker.get('worker_result_count') or 0)} successful, "
            + f"{int(worker.get('worker_failure_count') or 0)} failed",
            f"Verification passes: {int(worker.get('verification_passes') or 0)}",
            "",
            "Action Items",
            "------------",
            f"Total: {int(action_items.get('total') or 0)}",
            f"Severity counts: {dict(action_items.get('severity_counts') or {})}",
            f"Category counts: {dict(action_items.get('category_counts') or {})}",
            "",
            "Telemetry / Stability",
            "---------------------",
            f"Warnings: {dict(telemetry.get('warning_categories') or {})}",
            f"Errors: {dict(telemetry.get('error_categories') or {})}",
            f"Backend confidence: {dict(telemetry.get('backend_confidence_counts') or {})}",
            f"Worker-verified no telemetry: {int(telemetry.get('worker_verified_no_telemetry_count') or 0)}",
            "",
            "Artifacts",
            "---------",
            f"Kind: {artifacts.get('kind') or '-'}",
            f"Parsed results: {bool(artifacts.get('has_parsed_results'))}",
            f"Validation report: {bool(artifacts.get('has_validation_report'))}",
            f"Pre-import sanity: {bool(artifacts.get('has_pre_import_sanity'))}",
            "",
            str(action_help_text),
            "",
        ]
    )
    return "\n".join(lines)
