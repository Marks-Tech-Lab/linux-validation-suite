#!/usr/bin/env python3
"""Payload and text workflow helpers for result report operations."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List

from .lvs_core import APP_NAME, APP_VERSION, now_local_iso
from .lvs_result_report_text import pre_import_batch_line, result_validation_batch_line, result_validation_issue_line
from .lvs_service_models import ResultListEntry


def build_results_inventory_payload(results_dir: Path, entries: List[ResultListEntry], count_by: Callable[[List[ResultListEntry], str], Dict[str, int]]) -> Dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "kind": "results_inventory",
        "started": now_local_iso(),
        "results_dir": str(results_dir),
        "excluded_root_dirs": ["Archived", "Uploaded"],
        "counts": {
            "total": len(entries),
            "by_result": count_by(entries, "verdict"),
        },
        "items": [asdict(entry) | {"path": str(entry.path)} for entry in entries],
        "ended": now_local_iso(),
    }


def results_inventory_text_from_payload(payload: Dict[str, Any], entries: List[ResultListEntry]) -> str:
    lines = [
        "Results Inventory",
        "=================",
        f"Results folder: {payload['results_dir']}",
        "Excluded root folders: Archived, Uploaded",
        f"Folders found: {len(entries)}",
        f"By result: {payload['counts']['by_result']}",
        "",
    ]
    for entry in entries[:80]:
        lines.append(f"- {entry.name}: {entry.verdict} | {entry.profile_name} | {entry.started}")
    if len(entries) > 80:
        lines.append(f"... {len(entries) - 80} more result folder(s)")
    return "\n".join(lines) + "\n"


def build_result_validation_batch_payload(results_dir: Path, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    errors = sum(int((item.get("summary") or {}).get("errors") or 0) for item in items)
    warnings = sum(int((item.get("summary") or {}).get("warnings") or 0) for item in items)
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "kind": "result_validation_batch",
        "started": now_local_iso(),
        "results_dir": str(results_dir),
        "excluded_root_dirs": ["Archived", "Uploaded"],
        "result": "fail" if errors else "warning" if warnings else "pass",
        "counts": {"total": len(items), "errors": errors, "warnings": warnings},
        "items": items,
        "ended": now_local_iso(),
    }


def manager_result_validation_batch_text(payload: Dict[str, Any]) -> str:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines = [
        "Batch Result Validation",
        "=======================",
        f"Folders checked: {counts.get('total', len(items))}",
        f"Validation: {counts.get('errors', 0)} error(s), {counts.get('warnings', 0)} warning(s)",
        f"Result: {str(payload.get('result') or 'unknown').upper()}",
        "",
    ]
    for item in items[:80]:
        if isinstance(item, dict):
            lines.append(result_validation_batch_line(item))
    if len(items) > 80:
        lines.append(f"... {len(items) - 80} more result folder(s)")
    return "\n".join(lines) + "\n"


def build_pre_import_sanity_payload(result_dir: Path, validation_payload: Dict[str, Any], refresh_status: Dict[str, Any]) -> Dict[str, Any]:
    summary = validation_payload.get("summary") if isinstance(validation_payload.get("summary"), dict) else {}
    errors = int(summary.get("errors") or 0)
    warnings = int(summary.get("warnings") or 0)
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "kind": "pre_import_sanity",
        "started": now_local_iso(),
        "result_folder": str(result_dir),
        "result": "fail" if errors or not refresh_status.get("refreshed") else "warning" if warnings else "pass",
        "validation": validation_payload,
        "summary_refresh": refresh_status,
        "ended": now_local_iso(),
    }


def build_pre_import_sanity_batch_payload(results_dir: Path, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    errors = 0
    warnings = 0
    refresh_failed = 0
    for item in items:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        errors += int(summary.get("errors") or 0)
        warnings += int(summary.get("warnings") or 0)
        refresh = item.get("summary_refresh") if isinstance(item.get("summary_refresh"), dict) else {}
        if not refresh.get("refreshed"):
            refresh_failed += 1
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "kind": "pre_import_sanity_batch",
        "started": now_local_iso(),
        "results_dir": str(results_dir),
        "excluded_root_dirs": ["Archived", "Uploaded"],
        "result": "fail" if errors or refresh_failed else "warning" if warnings else "pass",
        "counts": {"total": len(items), "errors": errors, "warnings": warnings},
        "summary_refresh": {
            "total": len(items),
            "refreshed": len(items) - refresh_failed,
            "failed": refresh_failed,
        },
        "items": items,
        "ended": now_local_iso(),
    }


def manager_pre_import_sanity_batch_text(payload: Dict[str, Any]) -> str:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    refresh = payload.get("summary_refresh") if isinstance(payload.get("summary_refresh"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines = [
        "Batch Pre-Import Sanity Check",
        "=============================",
        f"Folders checked: {counts.get('total', len(items))}",
        f"Validation: {counts.get('errors', 0)} error(s), {counts.get('warnings', 0)} warning(s)",
        f"Run summaries: {refresh.get('refreshed', 0)} refreshed, {refresh.get('failed', 0)} failed",
        f"Result: {str(payload.get('result') or 'unknown').upper()}",
        "",
    ]
    for item in items[:80]:
        if isinstance(item, dict):
            lines.append(pre_import_batch_line(item))
    if len(items) > 80:
        lines.append(f"... {len(items) - 80} more result folder(s)")
    return "\n".join(lines) + "\n"


def build_result_validation_payload(result_dir: Path, parsed: Dict[str, Any], parsed_exists: bool, file_exists: Callable[[str], bool]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    required = [
        "parsed_results_custom.json",
        "run_summary.txt",
        "run_manifest.json",
        "run_metadata.json",
        "profile_used.json",
        "system_info.json",
    ]
    missing = [name for name in required if not file_exists(name)]
    for name in missing:
        severity = "error" if name == "parsed_results_custom.json" else "warning"
        issues.append({"severity": severity, "category": "support_files", "message": f"{name} is missing"})
    segments = parsed.get("Segments") if isinstance(parsed.get("Segments"), list) else []
    if parsed_exists and not parsed:
        issues.append({"severity": "error", "category": "json_parse", "message": "parsed_results_custom.json could not be read as an object"})
    if parsed and not segments:
        issues.append({"severity": "warning", "category": "export_shape", "message": "parsed result contains no Segments"})
    report = parsed.get("ReportSummary") if isinstance(parsed.get("ReportSummary"), dict) else {}
    worker_summary = report.get("GpuWorkerSummary") if isinstance(report.get("GpuWorkerSummary"), dict) else {}
    failed_workers = int(worker_summary.get("Failed") or worker_summary.get("failed") or worker_summary.get("WorkerFailureCount") or 0)
    if failed_workers:
        issues.append({"severity": "error", "category": "worker_results", "message": f"{failed_workers} GPU worker(s) failed"})
    action_items = report.get("ActionItemDetails") if isinstance(report.get("ActionItemDetails"), list) else []
    for action in action_items[:20]:
        if not isinstance(action, dict):
            continue
        severity = str(action.get("Severity") or action.get("severity") or "warning").lower()
        category = str(action.get("Category") or action.get("category") or "action_item")
        message = str(action.get("Message") or action.get("message") or action.get("Summary") or "")
        if severity in {"error", "fail", "critical", "warning"}:
            issues.append({"severity": "error" if severity in {"error", "fail", "critical"} else "warning", "category": category, "message": message})
    errors = sum(1 for issue in issues if issue.get("severity") == "error")
    warnings = sum(1 for issue in issues if issue.get("severity") == "warning")
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "kind": "result_validation",
        "started": now_local_iso(),
        "result_folder": str(result_dir),
        "result": "fail" if errors else "warning" if warnings else "pass",
        "profile_name": str(report.get("ProfileName") or (parsed.get("Metadata") or {}).get("ProfileName") or ""),
        "checks": {
            "support_files": {"required": required, "missing": missing, "ok": not missing},
            "segments": {"count": len(segments), "ok": bool(segments)},
            "gpu_worker_summary": worker_summary,
        },
        "summary": {"errors": errors, "warnings": warnings, "segments": len(segments)},
        "issues": issues,
        "ended": now_local_iso(),
    }


def manager_validation_text(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "Result Folder Validation",
        "========================",
        f"Folder: {payload.get('result_folder')}",
        f"Result: {str(payload.get('result') or 'unknown').upper()}",
        f"Validation: {summary.get('errors', 0)} error(s), {summary.get('warnings', 0)} warning(s)",
        f"Segments: {summary.get('segments', 0)}",
        "",
    ]
    for issue in payload.get("issues") or []:
        if isinstance(issue, dict):
            lines.append(result_validation_issue_line(issue))
    if not payload.get("issues"):
        lines.append("No validation issues found.")
    return "\n".join(lines) + "\n"


def manager_pre_import_text(payload: Dict[str, Any], validation_text: str) -> str:
    refresh = payload.get("summary_refresh") if isinstance(payload.get("summary_refresh"), dict) else {}
    return (
        "Pre-Import Sanity Check\n"
        "=======================\n"
        f"Folder: {payload.get('result_folder')}\n"
        f"Result: {str(payload.get('result') or 'unknown').upper()}\n\n"
        + validation_text
        + "\nRun Summary\n-----------\n"
        + f"Refreshed: {bool(refresh.get('refreshed'))}\n"
        + (f"Error: {refresh.get('error')}\n" if refresh.get("error") else "")
    )
