#!/usr/bin/env python3
"""Shared result-artifact inventory item classification."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .lvs_core import APP_NAME
from .lvs_result_artifact_details import safe_json_read
from .lvs_summary_text import SummaryTextBuilder


EXACT_ARTIFACT_NAMES = (
    "parsed_results_custom.json",
    "run_summary.txt",
    "preflight_report.json",
    "preflight_summary.txt",
    "diagnostics.json",
    "diagnostics_summary.txt",
    "dependency_check.json",
    "dependency_check.txt",
    "dependency_check_summary.txt",
    "profile_audit.json",
    "profile_audit.txt",
    "results_inventory.json",
    "results_inventory.txt",
    "result_validation.json",
    "result_validation.txt",
    "result_validation_batch.json",
    "result_validation_batch.txt",
    "pre_import_sanity_batch.json",
    "pre_import_sanity_batch.txt",
    "pre_import_sanity.json",
    "pre_import_sanity.txt",
    "artifact_details.json",
    "artifact_details.txt",
    "storage_benchmark.json",
    "storage_benchmark_summary.txt",
    "storage_benchmark_manifest.json",
    "storage_health_before.json",
    "storage_health_after.json",
    "storage_telemetry.csv",
)


class ResultArtifactInventoryBuilder:
    """Classify result artifact folders into frontend-neutral inventory items."""

    def __init__(self, exact_artifact_names: Iterable[str] = EXACT_ARTIFACT_NAMES) -> None:
        self.exact_artifact_names = tuple(exact_artifact_names)

    def artifact_file_names(self, result_dir: Path) -> List[str]:
        names: List[str] = [name for name in self.exact_artifact_names if (result_dir / name).exists()]
        for pattern in ("result_comparison_vs_*.json", "result_comparison_vs_*.txt"):
            names.extend(path.name for path in sorted(result_dir.glob(pattern)) if path.is_file())
        seen: set[str] = set()
        unique_names: List[str] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            unique_names.append(name)
        return unique_names

    def inventory_item(self, result_dir: Path) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "folder": str(result_dir),
            "folder_name": result_dir.name,
            "modified": datetime.fromtimestamp(result_dir.stat().st_mtime).astimezone().isoformat(),
            "artifacts": self.artifact_file_names(result_dir),
            "kind": "unknown",
            "profile_name": "",
            "result": "",
            "outcome_class": "",
            "stage_count": 0,
            "validation_errors": 0,
            "validation_warnings": 0,
            "action_items": 0,
            "notes": [],
        }
        if (result_dir / "parsed_results_custom.json").exists():
            return self._run_result_inventory_item(result_dir, item)
        if (result_dir / "storage_benchmark.json").exists():
            payload = safe_json_read(result_dir / "storage_benchmark.json")
            item.update({
                "kind": "storage_benchmark",
                "profile_name": str(payload.get("profile_name") or ""),
                "result": str(payload.get("verdict") or payload.get("status") or ""),
                "stage_count": len(payload.get("rows") or []),
            })
            if payload.get("_read_error"):
                item["notes"].append(f"storage_benchmark.json read error: {payload.get('_read_error')}")
            return item
        if (result_dir / "preflight_report.json").exists():
            return self._preflight_inventory_item(result_dir, item)
        if (result_dir / "diagnostics.json").exists():
            return self._diagnostics_inventory_item(result_dir, item)
        if (result_dir / "dependency_check.json").exists():
            return self._dependency_inventory_item(result_dir, item)
        if (result_dir / "profile_audit.json").exists():
            return self._profile_audit_inventory_item(result_dir, item)
        if (result_dir / "results_inventory.json").exists():
            return self._results_inventory_item(result_dir, item)
        if (result_dir / "result_validation_batch.json").exists():
            return self._result_validation_batch_inventory_item(result_dir, item)
        if (result_dir / "pre_import_sanity_batch.json").exists():
            return self._pre_import_sanity_batch_inventory_item(result_dir, item)
        return item

    def _run_result_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        parsed = safe_json_read(result_dir / "parsed_results_custom.json")
        report = parsed.get("ReportSummary") if isinstance(parsed.get("ReportSummary"), dict) else {}
        department = report.get("DepartmentUseSummary") if isinstance(report.get("DepartmentUseSummary"), dict) else {}
        if not department and report:
            department = SummaryTextBuilder(APP_NAME)._synthesize_department_use_summary(report)
        metadata = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}
        stage_outcomes = report.get("StageOutcomes") if isinstance(report.get("StageOutcomes"), list) else []
        gpu_highlight_count = sum(
            len(stage.get("GpuHighlights") or [])
            for stage in stage_outcomes
            if isinstance(stage, dict) and isinstance(stage.get("GpuHighlights"), list)
        )
        item.update(
            {
                "kind": "run_result",
                "profile_name": str(report.get("ProfileName") or metadata.get("ProfileName") or metadata.get("Profile") or ""),
                "result": str(report.get("Result") or parsed.get("Result") or parsed.get("result") or ""),
                "outcome_class": str(report.get("OutcomeClass") or ""),
                "department_status": str(department.get("Status") or ""),
                "department_blocking": bool(department.get("Blocking")) if department else None,
                "stage_count": len(parsed.get("Segments") or []) if isinstance(parsed.get("Segments"), list) else 0,
                "gpu_highlights": gpu_highlight_count,
                "action_items": len(report.get("ActionItemDetails") or []) if isinstance(report.get("ActionItemDetails"), list) else 0,
                "action_item_severity_counts": dict(report.get("ActionItemSeverityCounts") or {}),
                "action_item_category_counts": dict(report.get("ActionItemCategoryCounts") or {}),
                "warning_categories": dict(report.get("WarningCategoryCounts") or {}),
                "error_categories": dict(report.get("ErrorCategoryCounts") or {}),
            }
        )
        if parsed.get("_read_error"):
            item["notes"].append(f"parsed_results_custom.json read error: {parsed.get('_read_error')}")
        validation_path = result_dir / "result_validation.json"
        if validation_path.exists():
            validation_payload = safe_json_read(validation_path)
            validation_summary = validation_payload.get("summary") if isinstance(validation_payload.get("summary"), dict) else {}
            if validation_summary:
                item["validation_errors"] = int(validation_summary.get("errors") or 0)
                item["validation_warnings"] = int(validation_summary.get("warnings") or 0)
                item["validation_issue_category_counts"] = dict(validation_summary.get("issue_category_counts") or {})
                item["validation_issue_severity_category_counts"] = dict(validation_summary.get("issue_severity_category_counts") or {})
            if validation_payload.get("_read_error"):
                item["notes"].append(f"result_validation.json read error: {validation_payload.get('_read_error')}")
        return item

    def _preflight_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "preflight_report.json")
        preflight = payload.get("preflight") if isinstance(payload.get("preflight"), dict) else {}
        validation = preflight.get("validation") if isinstance(preflight.get("validation"), dict) else {}
        item.update(
            {
                "kind": "preflight",
                "profile_name": str(payload.get("profile_name") or preflight.get("profile_name") or ""),
                "result": str(payload.get("result") or "Blocked"),
                "stage_count": len(preflight.get("plan") or []) if isinstance(preflight.get("plan"), list) else 0,
                "validation_errors": len(validation.get("errors") or []),
                "validation_warnings": len(validation.get("warnings") or []),
                "runnable": bool(preflight.get("runnable")),
            }
        )
        if payload.get("_read_error"):
            item["notes"].append(f"preflight_report.json read error: {payload.get('_read_error')}")
        return item

    def _diagnostics_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "diagnostics.json")
        validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
        item.update(
            {
                "kind": "diagnostics",
                "profile_name": str(payload.get("profile_name") or ""),
                "result": "Runnable" if payload.get("runnable") else "Blocked",
                "stage_count": len(payload.get("plan") or []) if isinstance(payload.get("plan"), list) else 0,
                "validation_errors": len(validation.get("errors") or []),
                "validation_warnings": len(validation.get("warnings") or []),
                "runnable": bool(payload.get("runnable")),
            }
        )
        if payload.get("_read_error"):
            item["notes"].append(f"diagnostics.json read error: {payload.get('_read_error')}")
        return item

    def _dependency_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "dependency_check.json")
        item.update({"kind": "dependency_check", "profile_name": "", "result": str(payload.get("result") or "Saved")})
        if payload.get("_read_error"):
            item["notes"].append(f"dependency_check.json read error: {payload.get('_read_error')}")
        return item

    def _profile_audit_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "profile_audit.json")
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        item.update(
            {
                "kind": "profile_audit",
                "profile_name": "all profiles",
                "result": "Saved",
                "stage_count": int(counts.get("profiles") or 0),
                "validation_errors": int(counts.get("validation_errors") or 0),
                "validation_warnings": int(counts.get("validation_warnings") or 0),
                "runnable_profile_count": int(counts.get("runnable") or 0),
                "blocked_profile_count": int(counts.get("blocked") or 0),
            }
        )
        if payload.get("_read_error"):
            item["notes"].append(f"profile_audit.json read error: {payload.get('_read_error')}")
        return item

    def _results_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "results_inventory.json")
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        item.update(
            {
                "kind": "results_inventory",
                "profile_name": "results inventory",
                "result": "Saved",
                "stage_count": int(counts.get("total") or 0),
                "inventory_kind_counts": dict(counts.get("by_kind") or {}),
                "inventory_result_counts": dict(counts.get("by_result") or {}),
            }
        )
        if payload.get("_read_error"):
            item["notes"].append(f"results_inventory.json read error: {payload.get('_read_error')}")
        return item

    def _result_validation_batch_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "result_validation_batch.json")
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        item.update(
            {
                "kind": "result_validation_batch",
                "profile_name": "batch validation",
                "result": str(payload.get("result") or "Saved"),
                "stage_count": int(counts.get("total") or 0),
                "validation_errors": int(counts.get("errors") or 0),
                "validation_warnings": int(counts.get("warnings") or 0),
                "validation_issue_category_counts": dict(counts.get("issue_category_counts") or {}),
                "validation_issue_severity_category_counts": dict(counts.get("issue_severity_category_counts") or {}),
                "batch_result_counts": dict(counts.get("by_result") or {}),
            }
        )
        if payload.get("_read_error"):
            item["notes"].append(f"result_validation_batch.json read error: {payload.get('_read_error')}")
        return item

    def _pre_import_sanity_batch_inventory_item(self, result_dir: Path, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = safe_json_read(result_dir / "pre_import_sanity_batch.json")
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        refresh = payload.get("summary_refresh") if isinstance(payload.get("summary_refresh"), dict) else {}
        item.update(
            {
                "kind": "pre_import_sanity_batch",
                "profile_name": "pre-import sanity batch",
                "result": str(payload.get("result") or "Saved"),
                "stage_count": int(counts.get("total") or 0),
                "validation_errors": int(counts.get("errors") or 0),
                "validation_warnings": int(counts.get("warnings") or 0),
                "validation_issue_category_counts": dict(counts.get("issue_category_counts") or {}),
                "validation_issue_severity_category_counts": dict(counts.get("issue_severity_category_counts") or {}),
                "batch_result_counts": dict(counts.get("by_result") or {}),
                "summary_refreshed": int(refresh.get("refreshed") or 0),
                "summary_refresh_failed": int(refresh.get("failed") or 0),
            }
        )
        if payload.get("_read_error"):
            item["notes"].append(f"pre_import_sanity_batch.json read error: {payload.get('_read_error')}")
        return item
