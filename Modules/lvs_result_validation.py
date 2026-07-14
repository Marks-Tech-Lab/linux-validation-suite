#!/usr/bin/env python3
"""Shared result-folder validation facade logic."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .lvs_core import APP_NAME, APP_VERSION, JsonStore, now_local_iso
from .lvs_result_validation_checks import (
    EXPECTED_SUPPORT_FILES,
    OPTIONAL_SUPPORT_FILES,
    profile_name_matches_result as check_profile_name_matches_result,
    result_profile_name_candidates as check_result_profile_name_candidates,
    validate_profile_used as check_validate_profile_used,
    validate_run_manifest as check_validate_run_manifest,
    validate_run_metadata as check_validate_run_metadata,
    validate_support_files as check_validate_support_files,
    validate_system_info as check_validate_system_info,
)
from .lvs_result_validation_payload import validate_parsed_report_payload as check_validate_parsed_report_payload


ValidationCallable = Callable[[Path], Dict[str, Any]]

class ResultValidationFacade:
    """Frontend-neutral result validation entrypoints."""

    def __init__(self, results_dir: Path | str) -> None:
        self.results_dir = Path(results_dir)

    def result_candidates(self, include_archived: bool = False) -> List[Path]:
        excluded_root_dirs = {"archived", "uploaded"}
        candidates: List[Path] = []
        if not self.results_dir.exists():
            return candidates
        for path in self.results_dir.iterdir():
            if not path.is_dir():
                continue
            if path.name.strip().lower() in excluded_root_dirs:
                continue
            if (path / "parsed_results_custom.json").exists():
                candidates.append(path)
        if include_archived:
            archived_root = self.results_dir / "Archived"
            if archived_root.exists():
                for path in archived_root.iterdir():
                    if path.is_dir() and (path / "parsed_results_custom.json").exists():
                        candidates.append(path)
        return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)

    def validate_batch(
        self,
        candidates: List[Path],
        *,
        validate_one: ValidationCallable,
        write_one: Optional[ValidationCallable] = None,
        save_individual: bool = False,
    ) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        result_counts: Dict[str, int] = {}
        issue_category_counts: Dict[str, int] = {}
        issue_severity_category_counts: Dict[str, Dict[str, int]] = {}
        total_errors = 0
        total_warnings = 0

        for result_dir in candidates:
            try:
                if save_individual:
                    validation_payload = (write_one or validate_one)(result_dir)
                else:
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        validation_payload = validate_one(result_dir)
            except Exception as exc:
                validation_payload = self.validation_runtime_payload(result_dir, exc)

            summary = validation_payload.get("summary") if isinstance(validation_payload.get("summary"), dict) else {}
            result = str(validation_payload.get("result") or "unknown")
            errors = int(summary.get("errors") or 0)
            warnings = int(summary.get("warnings") or 0)
            total_errors += errors
            total_warnings += warnings
            result_counts[result] = result_counts.get(result, 0) + 1
            for category, value in dict(summary.get("issue_category_counts") or {}).items():
                try:
                    category_key = str(category)
                    issue_category_counts[category_key] = issue_category_counts.get(category_key, 0) + int(value)
                except Exception:
                    continue
            severity_categories = summary.get("issue_severity_category_counts")
            if isinstance(severity_categories, dict):
                self._merge_severity_category_counts(issue_severity_category_counts, severity_categories)
            elif summary.get("issue_category_counts"):
                severity_key = "error" if errors else "warning"
                issue_severity_category_counts.setdefault(severity_key, {})
                for category, value in dict(summary.get("issue_category_counts") or {}).items():
                    try:
                        category_key = str(category)
                        issue_severity_category_counts[severity_key][category_key] = (
                            issue_severity_category_counts[severity_key].get(category_key, 0) + int(value)
                        )
                    except Exception:
                        continue
            items.append(
                {
                    "folder": str(result_dir),
                    "folder_name": result_dir.name,
                    "result": result,
                    "summary": summary,
                    "issues": list(validation_payload.get("issues") or []),
                }
            )

        overall_result = "fail" if total_errors else "warning" if total_warnings else "pass"
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "result_validation_batch",
            "started": now_local_iso(),
            "results_dir": str(self.results_dir),
            "excluded_root_dirs": ["Archived", "Uploaded"],
            "result": overall_result,
            "counts": {
                "total": len(items),
                "errors": total_errors,
                "warnings": total_warnings,
                "by_result": dict(sorted(result_counts.items())),
                "issue_category_counts": dict(sorted(issue_category_counts.items())),
                "issue_severity_category_counts": {
                    severity: dict(sorted(categories.items()))
                    for severity, categories in sorted(issue_severity_category_counts.items())
                },
            },
            "items": items,
            "ended": now_local_iso(),
        }

    @staticmethod
    def write_validation_report(result_dir: Path, text: str, payload: Dict[str, Any]) -> Path:
        JsonStore.write(result_dir / "result_validation.json", payload)
        (result_dir / "result_validation.txt").write_text(text, encoding="utf-8")
        return result_dir

    def write_batch_validation_report(self, text: str, payload: Dict[str, Any], timestamp_name: str = "") -> Path:
        timestamp = timestamp_name or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = self.results_dir / f"{timestamp}_Result_Validation_Batch"
        report_dir.mkdir(parents=True, exist_ok=True)
        JsonStore.write(report_dir / "result_validation_batch.json", payload)
        (report_dir / "result_validation_batch.txt").write_text(text, encoding="utf-8")
        return report_dir

    def validate_result_folder(self, result_dir: Path, summary_exporter: Any) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        parsed_path = result_dir / "parsed_results_custom.json"
        payload: Dict[str, Any] = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "result_validation",
            "started": now_local_iso(),
            "result_folder": str(result_dir),
            "parsed_results_custom": str(parsed_path),
            "checks": {},
            "issues": issues,
        }

        if not parsed_path.exists():
            self._add_issue(issues, "error", "missing_file", "parsed_results_custom.json was not found")
            payload["result"] = "fail"
            return payload

        try:
            parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._add_issue(issues, "error", "json_parse", f"parsed_results_custom.json could not be parsed: {exc}")
            payload["result"] = "fail"
            return payload
        if not isinstance(parsed, dict):
            self._add_issue(
                issues,
                "error",
                "json_shape",
                "parsed_results_custom.json root is not a JSON object",
                {"json_type": type(parsed).__name__},
            )
            payload["result"] = "fail"
            payload["summary"] = {
                "errors": 1,
                "warnings": 0,
                "issue_category_counts": {"json_shape": 1},
                "issue_severity_category_counts": {"error": {"json_shape": 1}},
                "segments": 0,
                "gpu_worker_details": 0,
                "gpu_highlights": 0,
                "action_items": 0,
            }
            payload["ended"] = now_local_iso()
            return payload

        support_file_validation = self.validate_support_files(
            result_dir,
            parsed,
            summary_exporter,
        )
        payload["checks"].update(support_file_validation.get("checks", {}))
        issues.extend(support_file_validation.get("issues", []))

        profile_used_validation = self.validate_profile_used(result_dir, parsed)
        payload["checks"].update(profile_used_validation.get("checks", {}))
        issues.extend(profile_used_validation.get("issues", []))

        run_manifest_validation = self.validate_run_manifest(result_dir, parsed)
        payload["checks"].update(run_manifest_validation.get("checks", {}))
        issues.extend(run_manifest_validation.get("issues", []))

        run_metadata_validation = self.validate_run_metadata(result_dir, parsed)
        payload["checks"].update(run_metadata_validation.get("checks", {}))
        issues.extend(run_metadata_validation.get("issues", []))

        system_info_validation = self.validate_system_info(result_dir, parsed)
        payload["checks"].update(system_info_validation.get("checks", {}))
        issues.extend(system_info_validation.get("issues", []))

        parsed_report_validation = self.validate_parsed_report_payload(parsed)
        payload["checks"].update(parsed_report_validation.get("checks", {}))
        issues.extend(parsed_report_validation.get("issues", []))
        segments = parsed_report_validation.get("segments", [])
        validation_details = parsed_report_validation.get("validation_details", [])
        gpu_highlight_count = int(parsed_report_validation.get("gpu_highlight_count") or 0)
        action_details = parsed_report_validation.get("action_details", [])

        error_count = sum(1 for issue in issues if issue["severity"] == "error")
        warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
        issue_category_counts: Dict[str, int] = {}
        issue_severity_category_counts: Dict[str, Dict[str, int]] = {}
        for issue in issues:
            severity = str(issue.get("severity") or "unknown")
            category = str(issue.get("category") or "unknown")
            issue_category_counts[category] = issue_category_counts.get(category, 0) + 1
            issue_severity_category_counts.setdefault(severity, {})
            issue_severity_category_counts[severity][category] = issue_severity_category_counts[severity].get(category, 0) + 1
        result = "fail" if error_count else "warning" if warning_count else "pass"
        payload["result"] = result
        payload["ended"] = now_local_iso()
        payload["summary"] = {
            "errors": error_count,
            "warnings": warning_count,
            "issue_category_counts": dict(sorted(issue_category_counts.items())),
            "issue_severity_category_counts": {
                severity: dict(sorted(counts.items()))
                for severity, counts in sorted(issue_severity_category_counts.items())
            },
            "segments": len(segments),
            "gpu_worker_details": len(validation_details),
            "gpu_highlights": gpu_highlight_count,
            "action_items": len(action_details),
        }
        return payload

    def validate_support_files(
        self,
        result_dir: Path,
        parsed: Dict[str, Any],
        summary_exporter: Any,
    ) -> Dict[str, Any]:
        return check_validate_support_files(result_dir, parsed, summary_exporter)

    def validate_profile_used(self, result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
        return check_validate_profile_used(result_dir, parsed)

    def validate_run_manifest(self, result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
        return check_validate_run_manifest(result_dir, parsed)

    def validate_run_metadata(self, result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
        return check_validate_run_metadata(result_dir, parsed)

    def validate_system_info(self, result_dir: Path, parsed: Dict[str, Any]) -> Dict[str, Any]:
        return check_validate_system_info(result_dir, parsed)

    def validate_parsed_report_payload(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        return check_validate_parsed_report_payload(parsed)

    def result_profile_name_candidates(self, parsed: Dict[str, Any]) -> List[str]:
        return check_result_profile_name_candidates(parsed)

    def profile_name_matches_result(self, profile_name: str, result_candidates: List[str]) -> bool:
        return check_profile_name_matches_result(profile_name, result_candidates)

    def validation_runtime_payload(self, result_dir: Path, exc: Exception) -> Dict[str, Any]:
        return {
            "kind": "result_validation",
            "result_folder": str(result_dir),
            "result": "fail",
            "summary": {"errors": 1, "warnings": 0, "issue_category_counts": {"validation_runtime": 1}},
            "issues": [
                {
                    "severity": "error",
                    "category": "validation_runtime",
                    "message": f"Result validation crashed: {exc}",
                    "details": {},
                }
            ],
        }

    def _add_issue(
        self,
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

    def _merge_severity_category_counts(
        self,
        target: Dict[str, Dict[str, int]],
        source: Dict[str, Any],
    ) -> None:
        for severity, categories in source.items():
            if not isinstance(categories, dict):
                continue
            severity_key = str(severity)
            target.setdefault(severity_key, {})
            for category, value in categories.items():
                try:
                    category_key = str(category)
                    target[severity_key][category_key] = target[severity_key].get(category_key, 0) + int(value)
                except Exception:
                    continue
