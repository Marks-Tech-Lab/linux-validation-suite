from __future__ import annotations

"""Result/report facade methods for shared frontend services."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_core import APP_NAME, APP_VERSION, JsonStore, now_local_iso
from .lvs_result_report_rendering import ResultReportRenderService
from .lvs_result_report_text import (
    batch_pre_import_sanity_text,
    result_comparison_text,
    result_validation_text,
    selected_pre_import_sanity_text,
)
from .lvs_report_helpers import clean_review_verdict_from_payload
from .lvs_result_artifact_view import (
    result_artifact_choice_label as build_result_artifact_choice_label,
    result_artifact_choice_text as build_result_artifact_choice_text,
)
from .lvs_service_models import FrontendActionSpec, ResultListEntry


QA_REVIEW_CONTRACT_ID = "linux_validation_suite.qa_review"
QA_REVIEW_CONTRACT_VERSION = 1


class SuiteResultServiceMixin:
    """Prompt-free result/report methods shared by TUI, GUI, and QA callers."""

    def result_report_renderer(self) -> ResultReportRenderService:
        return ResultReportRenderService(
            result_artifacts=self.result_artifacts,
            result_validation=self.result_validation,
            result_comparison=self.result_comparison,
            pre_import_sanity=self.pre_import_sanity,
            dependency_summary_builder=self.dependency_reports.dependency_check_summary_text,
            summary_exporter=self.summary_exporter,
        )

    def list_results(self) -> List[ResultListEntry]:
        return self.result_reports.list_results()

    def result_action_for_key(self, key: str) -> FrontendActionSpec:
        return self.result_reports.result_action_for_key(key)

    def result_action_help_text(self) -> str:
        return self.result_reports.result_action_help_text()

    def result_summary_text(self, result_dir: Path) -> str:
        return self.result_reports.result_summary_text(result_dir)

    def result_overview_text(self, result_dir: Path) -> str:
        return self.result_reports.result_overview_text(result_dir)

    def result_stage_details_text(self, result_dir: Path) -> str:
        return self.result_reports.result_stage_details_text(result_dir)

    def results_inventory_text(self, save: bool = True) -> str:
        return self.result_reports.results_inventory_text(save=save)

    def result_artifact_candidates(self) -> List[Path]:
        return self.result_artifacts.candidates()

    def result_artifact_inventory_payload(self) -> Dict[str, Any]:
        return self.result_artifacts.inventory_payload()

    def result_artifact_inventory_text(self) -> str:
        return self.result_report_renderer().inventory().text

    def result_artifact_choice_label(self, result_dir: Path) -> str:
        return build_result_artifact_choice_label(result_dir, self.result_artifact_inventory_item(result_dir))

    def result_artifact_choice_text(
        self,
        candidates: List[Path],
        heading: str = "Available result folders",
    ) -> str:
        return build_result_artifact_choice_text(
            candidates,
            item_for_path=self.result_artifact_inventory_item,
            heading=heading,
        )

    def write_result_artifact_inventory_report(
        self,
        text: str,
        payload: Dict[str, Any],
        timestamp_name: str = "",
    ) -> Path:
        return self.result_artifacts.write_inventory_report(text, payload, timestamp_name)

    def result_artifact_inventory_item(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_artifacts.inventory_item(result_dir)

    def run_result_artifact_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_artifacts.run_result_detail_payload(result_dir)

    def preflight_artifact_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_artifacts.preflight_detail_payload(result_dir)

    def diagnostics_artifact_detail_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_artifacts.diagnostics_detail_payload(result_dir)

    def result_artifact_detail_payload(self, result_dir: Path, kind: str = "") -> Dict[str, Any]:
        return self.result_artifacts.detail_payload(result_dir, kind)

    def result_artifact_detail_report_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_artifacts.detail_report_payload(result_dir)

    def result_artifact_detail_text(self, result_dir: Path) -> str:
        return self.result_report_renderer().artifact_detail(result_dir).text

    def write_result_artifact_detail_report(self, result_dir: Path, text: str, payload: Dict[str, Any]) -> Path:
        return self.result_artifacts.write_detail_report(result_dir, text, payload)

    def validate_result_text(self, result_dir: Path, save: bool = True) -> str:
        rendered = self.result_report_renderer().validation(result_dir)
        payload = rendered.payload
        text = rendered.text
        if save:
            self.result_validation.write_validation_report(result_dir, text, payload)
            text += f"\nSaved: {result_dir / 'result_validation.txt'}\n"
        return text

    def validate_all_results_text(self, save: bool = True) -> str:
        candidates = self.result_validation.result_candidates()
        rendered = self.result_report_renderer().validation_batch(candidates)
        payload = rendered.payload
        text = rendered.text
        if save:
            report_dir = self.result_validation.write_batch_validation_report(text, payload)
            text += f"\nSaved: {report_dir}\n"
        return text

    def pre_import_sanity_text(self, result_dir: Path, save: bool = True) -> str:
        renderer = self.result_report_renderer()
        prepared = renderer.prepare_selected_pre_import(result_dir)
        rendered = renderer.selected_pre_import(prepared)
        payload = rendered.payload
        text = rendered.text
        if save:
            validation_payload = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
            self.pre_import_sanity.write_selected_report(
                result_dir,
                validation_text=result_validation_text(validation_payload),
                validation_payload=validation_payload,
                pre_import_text=text,
                pre_import_payload=payload,
                save_validation=False,
            )
            text += f"\nSaved: {result_dir / 'pre_import_sanity.txt'}\n"
        return text

    def pre_import_sanity_all_text(self, save: bool = True) -> str:
        rendered = self.result_report_renderer().pre_import_batch(save_individual_validation=save)
        payload = rendered.payload
        text = rendered.text
        if save:
            report_dir = self.pre_import_sanity.write_batch_report(text, payload)
            text += f"\nSaved: {report_dir}\n"
        return text

    def refresh_run_summary(self, result_dir: Path) -> Dict[str, Any]:
        return self.pre_import_sanity.refresh_run_summary(result_dir)

    def prepare_pre_import_sanity(self, result_dir: Path) -> Dict[str, Any]:
        return self.pre_import_sanity.prepare_selected(result_dir)

    def complete_pre_import_sanity(
        self,
        prepared: Dict[str, Any],
        comparison: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.pre_import_sanity.complete_selected(prepared, comparison)

    def selected_pre_import_sanity_text(
        self,
        payload: Dict[str, Any],
        comparison_status_text: str = "",
    ) -> str:
        return selected_pre_import_sanity_text(payload, comparison_status_text)

    def batch_pre_import_sanity_text(self, payload: Dict[str, Any]) -> str:
        return batch_pre_import_sanity_text(payload)

    def pre_import_sanity_batch_payload(self, candidates: Optional[List[Path]] = None) -> Dict[str, Any]:
        return self.pre_import_sanity.run_batch(candidates)

    def compare_result_payload(self, baseline_dir: Path, comparison_dir: Path) -> Dict[str, Any]:
        return self.result_comparison.compare_result_folders(baseline_dir, comparison_dir)

    def result_comparison_text(self, payload: Dict[str, Any]) -> str:
        return result_comparison_text(payload)

    def qa_result_review_payload(
        self,
        result_dir: Path,
        comparison_dir: Optional[Path] = None,
        *,
        refresh_summary: bool = True,
    ) -> Dict[str, Any]:
        """Build one prompt-free QA review payload for a result folder."""

        result_dir = Path(result_dir)
        started = now_local_iso()
        parsed_path = result_dir / "parsed_results_custom.json"
        parsed_exists = parsed_path.exists()
        parsed = JsonStore.read(parsed_path, {}) if parsed_exists else {}
        if not isinstance(parsed, dict):
            parsed = {}
        report = parsed.get("ReportSummary") if isinstance(parsed.get("ReportSummary"), dict) else {}
        metadata = parsed.get("Metadata") if isinstance(parsed.get("Metadata"), dict) else {}

        validation = self.result_validation.validate_result_folder(result_dir, self.summary_exporter)
        comparison_readiness, comparison_payload = self._qa_comparison_status(result_dir, comparison_dir, parsed_exists)
        summary_refresh = (
            self.pre_import_sanity.refresh_run_summary(result_dir)
            if refresh_summary
            else {
                "summary_path": str(result_dir / "run_summary.txt"),
                "refreshed": False,
                "skipped": True,
                "error": "",
            }
        )
        pre_import_payload = self.pre_import_sanity.complete_selected(
            {
                "result_folder": str(result_dir),
                "validation": validation,
                "summary_refresh": summary_refresh,
            },
            comparison_payload,
        )
        import_readiness = self._qa_import_readiness(validation, summary_refresh, refresh_summary)
        worker_evidence = self._qa_worker_failure_evidence(report, validation)
        action_summary = self._qa_action_item_summary(report)
        telemetry_stability = self._qa_telemetry_stability_summary(parsed, report)
        review_verdict = clean_review_verdict_from_payload(parsed, validation)
        decisions = self._qa_review_decisions(
            parsed_exists=parsed_exists,
            parsed_is_object=bool(parsed),
            validation=validation,
            import_readiness=import_readiness,
            comparison_readiness=comparison_readiness,
            worker_evidence=worker_evidence,
            action_summary=action_summary,
        )

        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "contract_id": QA_REVIEW_CONTRACT_ID,
            "contract_version": QA_REVIEW_CONTRACT_VERSION,
            "kind": "qa_result_review",
            "started": started,
            "ended": now_local_iso(),
            "result_folder": str(result_dir),
            "identity": self._qa_result_identity(result_dir, parsed_exists, parsed, report, metadata),
            "decisions": decisions,
            "validation_status": self._qa_validation_status(validation),
            "validation": validation,
            "import_readiness": import_readiness,
            "pre_import_sanity": pre_import_payload,
            "summary_refresh": summary_refresh,
            "comparison_readiness": comparison_readiness,
            "comparison": comparison_payload,
            "artifact_availability": self._qa_artifact_availability(result_dir),
            "worker_failure_evidence": worker_evidence,
            "action_item_summary": action_summary,
            "review_verdict": review_verdict,
            "telemetry_stability_warning_summary": telemetry_stability,
        }

    def qa_batch_review_payload(
        self,
        candidates: Optional[List[Path]] = None,
        *,
        refresh_summary: bool = False,
    ) -> Dict[str, Any]:
        """Build compact QA review payloads for multiple result folders."""

        result_dirs = list(candidates) if candidates is not None else self.result_validation.result_candidates()
        items = [
            self.qa_result_review_payload(result_dir, refresh_summary=refresh_summary)
            for result_dir in result_dirs
        ]
        import_counts: Dict[str, int] = {}
        validation_counts: Dict[str, int] = {}
        review_counts: Dict[str, int] = {}
        escalation_needed = 0
        for item in items:
            validation_result = str((item.get("validation_status") or {}).get("result") or "unknown")
            import_result = str((item.get("import_readiness") or {}).get("status") or "unknown")
            review_status = str(((item.get("decisions") or {}).get("review") or {}).get("status") or "unknown")
            validation_counts[validation_result] = validation_counts.get(validation_result, 0) + 1
            import_counts[import_result] = import_counts.get(import_result, 0) + 1
            review_counts[review_status] = review_counts.get(review_status, 0) + 1
            if (((item.get("decisions") or {}).get("escalate") or {}).get("needed")):
                escalation_needed += 1
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "contract_id": QA_REVIEW_CONTRACT_ID,
            "contract_version": QA_REVIEW_CONTRACT_VERSION,
            "kind": "qa_result_review_batch",
            "started": now_local_iso(),
            "ended": now_local_iso(),
            "results_dir": str(self.result_validation.results_dir),
            "counts": {
                "total": len(items),
                "validation_by_result": dict(sorted(validation_counts.items())),
                "import_by_status": dict(sorted(import_counts.items())),
                "review_by_status": dict(sorted(review_counts.items())),
                "escalation_needed": escalation_needed,
            },
            "items": items,
        }

    def write_result_comparison_report(
        self,
        baseline_dir: Path,
        comparison_dir: Path,
        text: str,
        payload: Dict[str, Any],
    ) -> Path:
        return self.result_comparison.write_comparison_report(baseline_dir, comparison_dir, text, payload)

    def _completed_result_dirs(self) -> List[Path]:
        return self.result_reports.completed_result_dirs()

    def _validate_result_payload(self, result_dir: Path) -> Dict[str, Any]:
        return self.result_validation.validate_result_folder(result_dir, self.summary_exporter)

    def _validation_text(self, payload: Dict[str, Any]) -> str:
        return result_validation_text(payload)

    def _pre_import_text(self, payload: Dict[str, Any]) -> str:
        return selected_pre_import_sanity_text(payload)

    def _new_report_dir(self, suffix: str) -> Path:
        return self.result_reports.new_report_dir(suffix)

    def _count_by(self, entries: List[ResultListEntry], field: str) -> Dict[str, int]:
        return self.result_reports._count_by(entries, field)

    def _read_json(self, path: Path) -> Dict[str, Any]:
        payload = JsonStore.read(path, {})
        return payload if isinstance(payload, dict) else {}

    def _qa_result_identity(
        self,
        result_dir: Path,
        parsed_exists: bool,
        parsed: Dict[str, Any],
        report: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        department = report.get("DepartmentUseSummary") if isinstance(report.get("DepartmentUseSummary"), dict) else {}
        return {
            "folder": str(result_dir),
            "folder_name": result_dir.name,
            "exists": result_dir.exists(),
            "parsed_results_custom_exists": parsed_exists,
            "profile_name": str(report.get("ProfileName") or metadata.get("ProfileName") or metadata.get("Profile") or ""),
            "result": str(report.get("Result") or parsed.get("Result") or parsed.get("result") or ""),
            "outcome_class": str(report.get("OutcomeClass") or ""),
            "outcome_summary": str(report.get("OutcomeSummary") or ""),
            "department_status": str(department.get("Status") or ""),
            "department_blocking": bool(department.get("Blocking")) if department else None,
            "stage_count": int(report.get("StageCount") or (len(parsed.get("Segments") or []) if isinstance(parsed.get("Segments"), list) else 0)),
            "elapsed": str(report.get("Elapsed") or parsed.get("Elapsed") or parsed.get("elapsed") or ""),
        }

    def _qa_validation_status(self, validation: Dict[str, Any]) -> Dict[str, Any]:
        summary = validation.get("summary") if isinstance(validation.get("summary"), dict) else {}
        return {
            "result": str(validation.get("result") or "unknown"),
            "errors": int(summary.get("errors") or 0),
            "warnings": int(summary.get("warnings") or 0),
            "issue_category_counts": dict(summary.get("issue_category_counts") or {}),
            "issue_severity_category_counts": dict(summary.get("issue_severity_category_counts") or {}),
        }

    def _qa_import_readiness(
        self,
        validation: Dict[str, Any],
        summary_refresh: Dict[str, Any],
        require_summary_refresh: bool,
    ) -> Dict[str, Any]:
        validation_status = self._qa_validation_status(validation)
        validation_result = validation_status["result"]
        refresh_failed = (
            require_summary_refresh
            and summary_refresh.get("refreshed") is False
            and not summary_refresh.get("skipped")
        )
        status = "fail" if validation_result == "fail" or refresh_failed else "warning" if validation_result == "warning" else "pass"
        reasons: List[str] = []
        if validation_result == "fail":
            reasons.append("validation_failed")
        elif validation_result == "warning":
            reasons.append("validation_warnings")
        if refresh_failed:
            reasons.append("summary_refresh_failed")
        if summary_refresh.get("skipped"):
            reasons.append("summary_refresh_skipped")
        return {
            "status": status,
            "blocking": status == "fail",
            "summary_refresh_checked": bool(summary_refresh),
            "summary_refresh_required": require_summary_refresh,
            "summary_refreshed": bool(summary_refresh.get("refreshed")),
            "reasons": reasons,
        }

    def _qa_comparison_status(
        self,
        result_dir: Path,
        comparison_dir: Optional[Path],
        parsed_exists: bool,
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        if not parsed_exists:
            return {
                "ready": False,
                "status": "blocked",
                "reason": "parsed_results_custom.json missing for result",
                "comparison_folder": str(comparison_dir) if comparison_dir else "",
            }, None
        if comparison_dir is None:
            return {
                "ready": True,
                "status": "ready_no_baseline_selected",
                "reason": "result has parsed_results_custom.json; provide comparison_dir to build a comparison",
                "comparison_folder": "",
            }, None
        comparison_dir = Path(comparison_dir)
        if not (comparison_dir / "parsed_results_custom.json").exists():
            return {
                "ready": False,
                "status": "blocked",
                "reason": "parsed_results_custom.json missing for comparison folder",
                "comparison_folder": str(comparison_dir),
            }, None
        try:
            payload = self.result_comparison.compare_result_folders(comparison_dir, result_dir)
        except Exception as exc:
            return {
                "ready": False,
                "status": "error",
                "reason": str(exc),
                "comparison_folder": str(comparison_dir),
            }, None
        return {
            "ready": True,
            "status": "compared",
            "reason": "",
            "comparison_folder": str(comparison_dir),
        }, payload

    def _qa_artifact_availability(self, result_dir: Path) -> Dict[str, Any]:
        if not result_dir.exists():
            return {
                "folder": str(result_dir),
                "exists": False,
                "kind": "missing",
                "artifacts": [],
                "has_parsed_results": False,
                "has_validation_report": False,
                "has_pre_import_sanity": False,
            }
        item = self.result_artifacts.inventory_item(result_dir)
        artifacts = list(item.get("artifacts") or [])
        return {
            "folder": str(result_dir),
            "exists": True,
            "kind": str(item.get("kind") or "unknown"),
            "artifacts": artifacts,
            "has_parsed_results": "parsed_results_custom.json" in artifacts,
            "has_validation_report": "result_validation.json" in artifacts,
            "has_pre_import_sanity": "pre_import_sanity.json" in artifacts,
            "inventory_item": item,
        }

    def _qa_worker_failure_evidence(self, report: Dict[str, Any], validation: Dict[str, Any]) -> Dict[str, Any]:
        summary = report.get("GpuWorkerSummary") if isinstance(report.get("GpuWorkerSummary"), dict) else {}
        total = summary.get("WorkerResultCount", summary.get("Total", 0))
        successful = summary.get(
            "SuccessfulWorkerResultCount",
            summary.get("Successful", summary.get("Passed", 0)),
        )
        failed = summary.get("WorkerFailureCount", summary.get("Failed", 0))
        issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
        worker_issues = [
            issue
            for issue in issues
            if isinstance(issue, dict)
            and str(issue.get("category") or "") in {"worker_results", "gpu_worker_summary", "gpu_worker_details"}
        ]
        return {
            "worker_result_count": int(total or 0),
            "successful_worker_result_count": int(successful or 0),
            "worker_failure_count": int(failed or 0),
            "verification_passes": int(summary.get("VerificationPasses") or 0),
            "has_worker_failures": int(failed or 0) > 0,
            "validation_worker_issue_count": len(worker_issues),
            "validation_worker_issues": worker_issues,
            "raw_summary": dict(summary),
        }

    def _qa_action_item_summary(self, report: Dict[str, Any]) -> Dict[str, Any]:
        details = report.get("ActionItemDetails") if isinstance(report.get("ActionItemDetails"), list) else []
        severity_counts = dict(report.get("ActionItemSeverityCounts") or {})
        category_counts = dict(report.get("ActionItemCategoryCounts") or {})
        error_count = int(severity_counts.get("error") or severity_counts.get("Error") or 0)
        raw_total = report.get("ActionItems")
        if isinstance(raw_total, list):
            total = len(raw_total)
        else:
            total = int(raw_total or len(details))
        return {
            "total": total,
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "has_error_actions": error_count > 0,
            "details": details,
        }

    def _qa_telemetry_stability_summary(self, parsed: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
        stages = report.get("StageOutcomes") if isinstance(report.get("StageOutcomes"), list) else []
        backend_confidence_counts: Dict[str, int] = {}
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            confidence = str(stage.get("BackendConfidence") or "")
            if not confidence:
                continue
            backend_confidence_counts[confidence] = backend_confidence_counts.get(confidence, 0) + 1

        worker_verified_no_telemetry = 0
        segments = parsed.get("Segments") if isinstance(parsed.get("Segments"), list) else []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            stability = segment.get("StabilityInterpretation") if isinstance(segment.get("StabilityInterpretation"), dict) else {}
            thresholds = stability.get("ThresholdRecommendations") if isinstance(stability.get("ThresholdRecommendations"), dict) else {}
            try:
                worker_verified_no_telemetry += int(thresholds.get("WorkerVerifiedNoTelemetryCount") or 0)
            except Exception:
                continue
        return {
            "outcome_class": str(report.get("OutcomeClass") or ""),
            "warning_categories": dict(report.get("WarningCategoryCounts") or {}),
            "error_categories": dict(report.get("ErrorCategoryCounts") or {}),
            "warning_count": int(report.get("WarningCount") or 0),
            "error_count": int(report.get("ErrorCount") or 0),
            "backend_confidence_counts": dict(sorted(backend_confidence_counts.items())),
            "worker_verified_no_telemetry_count": worker_verified_no_telemetry,
            "report_only_threshold_would_warn_count": int(report.get("ReportOnlyThresholdWouldWarnCount") or 0),
            "report_only_threshold_unobserved_count": int(report.get("ReportOnlyThresholdUnobservedCount") or 0),
        }

    def _qa_review_decisions(
        self,
        *,
        parsed_exists: bool,
        parsed_is_object: bool,
        validation: Dict[str, Any],
        import_readiness: Dict[str, Any],
        comparison_readiness: Dict[str, Any],
        worker_evidence: Dict[str, Any],
        action_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        validation_status = self._qa_validation_status(validation)
        review_reasons: List[str] = []
        if not parsed_exists:
            review_reasons.append("parsed_results_custom_missing")
        elif not parsed_is_object:
            review_reasons.append("parsed_results_custom_invalid")
        review_status = "blocked" if review_reasons else "ready"

        escalate_reasons: List[str] = []
        if validation_status["errors"]:
            escalate_reasons.append("validation_errors")
        if worker_evidence.get("has_worker_failures"):
            escalate_reasons.append("worker_failures")
        if action_summary.get("has_error_actions"):
            escalate_reasons.append("error_action_items")
        if review_status == "blocked":
            escalate_reasons.append("review_blocked")
        return {
            "review": {
                "status": review_status,
                "ready": review_status == "ready",
                "reasons": review_reasons,
            },
            "import": import_readiness,
            "compare": comparison_readiness,
            "escalate": {
                "needed": bool(escalate_reasons),
                "reasons": escalate_reasons,
            },
        }
