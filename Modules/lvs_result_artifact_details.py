#!/usr/bin/env python3
"""Shared result-artifact detail payload construction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .lvs_core import APP_NAME
from .lvs_summary_text import SummaryTextBuilder


def safe_json_read(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {
                "_read_error": f"{path.name} root is not a JSON object",
                "_json_type": type(payload).__name__,
            }
        return payload
    except Exception as exc:
        return {"_read_error": str(exc)}


def plan_detail_payload(report: Dict[str, Any], full_detail_name: str) -> Dict[str, Any]:
    validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
    errors = list(validation.get("errors") or [])
    warnings = list(validation.get("warnings") or [])
    plan = report.get("plan") if isinstance(report.get("plan"), list) else []
    details = {
        "profile_name": report.get("profile_name"),
        "runnable": bool(report.get("runnable")),
        "validation_errors": len(errors),
        "validation_warnings": len(warnings),
        "stage_count": len(plan),
        "runnable_stage_count": report.get("runnable_stage_count"),
        "enabled_stage_count": report.get("enabled_stage_count"),
    }
    return {
        "details": details,
        "errors": errors,
        "warnings": warnings,
        "plan": plan,
        "full_detail_name": full_detail_name,
    }


class ResultArtifactDetailBuilder:
    """Build frontend-neutral detail payloads for known artifact kinds."""

    def run_result_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        parsed = safe_json_read(result_dir / "parsed_results_custom.json")
        report = parsed.get("ReportSummary") if isinstance(parsed.get("ReportSummary"), dict) else {}
        department = report.get("DepartmentUseSummary") if isinstance(report.get("DepartmentUseSummary"), dict) else {}
        if not department and report:
            department = SummaryTextBuilder(APP_NAME)._synthesize_department_use_summary(report)
        stage_outcomes = report.get("StageOutcomes") if isinstance(report.get("StageOutcomes"), list) else []
        action_items = report.get("ActionItemDetails") if isinstance(report.get("ActionItemDetails"), list) else []
        details = {
            "result": report.get("Result") or parsed.get("Result") or parsed.get("result"),
            "outcome_class": report.get("OutcomeClass"),
            "department_status": department.get("Status"),
            "department_blocking": department.get("Blocking"),
            "department_decision": department.get("Decision"),
            "stage_count": len(stage_outcomes),
            "action_item_count": len(action_items),
            "action_item_severity_counts": dict(report.get("ActionItemSeverityCounts") or {}),
            "action_item_category_counts": dict(report.get("ActionItemCategoryCounts") or {}),
            "gpu_highlight_count": sum(
                len(stage.get("GpuHighlights") or [])
                for stage in stage_outcomes
                if isinstance(stage, dict) and isinstance(stage.get("GpuHighlights"), list)
            ),
            "warning_categories": dict(report.get("WarningCategoryCounts") or {}),
            "error_categories": dict(report.get("ErrorCategoryCounts") or {}),
            "gpu_worker_summary": dict(report.get("GpuWorkerSummary") or {}),
        }
        return {
            "details": details,
            "report": report,
            "department": department,
            "stage_outcomes": stage_outcomes,
            "action_items": action_items,
        }

    def preflight_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "preflight_report.json")
        preflight = payload.get("preflight") if isinstance(payload.get("preflight"), dict) else {}
        detail_payload = plan_detail_payload(preflight, full_detail_name="preflight_report.json")
        detail_payload["details"]["result"] = payload.get("result")
        return detail_payload

    def diagnostics_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        diagnostics = safe_json_read(result_dir / "diagnostics.json")
        return plan_detail_payload(diagnostics, full_detail_name="diagnostics.json")

    def dependency_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        dependency = safe_json_read(result_dir / "dependency_check.json")
        checks = dependency.get("checks") if isinstance(dependency.get("checks"), dict) else {}
        return {
            "details": {
                "result": dependency.get("result"),
                "check_count": len(checks),
            },
            "dependency": dependency,
            "checks": checks,
        }

    def storage_benchmark_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        benchmark = safe_json_read(result_dir / "storage_benchmark.json")
        rows = benchmark.get("rows") if isinstance(benchmark.get("rows"), list) else []
        return {
            "details": {
                "result": benchmark.get("verdict"),
                "status": benchmark.get("status"),
                "profile_name": benchmark.get("profile_name"),
                "row_count": len(rows),
                "backend": benchmark.get("backend"),
            },
            "rows": rows,
            "warnings": list(benchmark.get("warnings") or []),
            "errors": list(benchmark.get("errors") or []),
        }

    def profile_audit_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        audit = safe_json_read(result_dir / "profile_audit.json")
        counts = audit.get("counts") if isinstance(audit.get("counts"), dict) else {}
        profiles = audit.get("profiles") if isinstance(audit.get("profiles"), list) else []
        return {
            "details": {
                "profile_count": int(counts.get("profiles") or len(profiles)),
                "runnable_profile_count": int(counts.get("runnable") or 0),
                "blocked_profile_count": int(counts.get("blocked") or 0),
                "validation_errors": int(counts.get("validation_errors") or 0),
                "validation_warnings": int(counts.get("validation_warnings") or 0),
            },
            "profiles": profiles,
        }

    def results_inventory_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        inventory = safe_json_read(result_dir / "results_inventory.json")
        counts = inventory.get("counts") if isinstance(inventory.get("counts"), dict) else {}
        items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
        return {
            "details": {
                "artifact_count": int(counts.get("total") or len(items)),
                "by_kind": dict(counts.get("by_kind") or {}),
                "by_result": dict(counts.get("by_result") or {}),
            },
            "items": items,
        }

    def result_validation_batch_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        batch = safe_json_read(result_dir / "result_validation_batch.json")
        counts = batch.get("counts") if isinstance(batch.get("counts"), dict) else {}
        items = batch.get("items") if isinstance(batch.get("items"), list) else []
        return {
            "details": {
                "result_count": int(counts.get("total") or len(items)),
                "errors": int(counts.get("errors") or 0),
                "warnings": int(counts.get("warnings") or 0),
                "by_result": dict(counts.get("by_result") or {}),
                "issue_category_counts": dict(counts.get("issue_category_counts") or {}),
                "issue_severity_category_counts": dict(counts.get("issue_severity_category_counts") or {}),
            },
            "items": items,
        }

    def pre_import_sanity_batch_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        batch = safe_json_read(result_dir / "pre_import_sanity_batch.json")
        counts = batch.get("counts") if isinstance(batch.get("counts"), dict) else {}
        refresh = batch.get("summary_refresh") if isinstance(batch.get("summary_refresh"), dict) else {}
        items = batch.get("items") if isinstance(batch.get("items"), list) else []
        return {
            "details": {
                "result_count": int(counts.get("total") or len(items)),
                "errors": int(counts.get("errors") or 0),
                "warnings": int(counts.get("warnings") or 0),
                "by_result": dict(counts.get("by_result") or {}),
                "issue_category_counts": dict(counts.get("issue_category_counts") or {}),
                "summary_refreshed": int(refresh.get("refreshed") or 0),
                "summary_refresh_failed": int(refresh.get("failed") or 0),
            },
            "items": items,
        }

    def detail_payload(self, result_dir: Path, artifact_kind: str) -> Dict[str, Any]:
        builders = {
            "run_result": self.run_result_detail_payload,
            "preflight": self.preflight_detail_payload,
            "diagnostics": self.diagnostics_detail_payload,
            "dependency_check": self.dependency_detail_payload,
            "storage_benchmark": self.storage_benchmark_detail_payload,
            "profile_audit": self.profile_audit_detail_payload,
            "results_inventory": self.results_inventory_detail_payload,
            "result_validation_batch": self.result_validation_batch_detail_payload,
            "pre_import_sanity_batch": self.pre_import_sanity_batch_detail_payload,
        }
        builder = builders.get(artifact_kind)
        if builder is None:
            return {"details": {}, "kind": artifact_kind}
        payload = builder(result_dir)
        payload["kind"] = artifact_kind
        return payload
