#!/usr/bin/env python3
"""Plain-text run summary rendering for Linux Validation Suite results."""

from __future__ import annotations

from typing import Any, Dict, List


class SummaryTextBuilder:
    def __init__(self, app_name: str = "Linux Validation Suite") -> None:
        self.app_name = app_name

    def build(self, result: Dict[str, Any]) -> str:
        report = result.get("ReportSummary") if isinstance(result.get("ReportSummary"), dict) else {}
        metadata = result.get("Metadata") if isinstance(result.get("Metadata"), dict) else {}
        lines: List[str] = []
        title = str(metadata.get("TestName") or result.get("SourceEngine") or self.app_name)
        lines.append("Linux Validation Suite Run Summary")
        lines.append("=" * 34)
        lines.append("")
        lines.append(f"Test: {title}")
        lines.append(f"Result: {report.get('Result') or result.get('Result') or result.get('result') or '-'}")
        if report.get("OutcomeClass"):
            lines.append(f"Outcome: {report.get('OutcomeClass')}")
        if report.get("OutcomeSummary"):
            lines.append(f"Summary: {report.get('OutcomeSummary')}")
        lines.append(f"Started: {result.get('Started') or result.get('started') or '-'}")
        lines.append(f"Ended: {result.get('Ended') or result.get('ended') or '-'}")
        lines.append(f"Elapsed: {report.get('Elapsed') or result.get('Elapsed') or result.get('elapsed') or '-'}")
        lines.append("")

        self._append_department_use_summary(lines, report)
        self._append_issue_categories(lines, report)
        self._append_worker_summary(lines, report)
        self._append_stage_summaries(lines, report)
        self._append_action_items(lines, report)
        self._append_export_contract(lines, result)
        return "\n".join(lines).rstrip() + "\n"

    def _append_department_use_summary(self, lines: List[str], report: Dict[str, Any]) -> None:
        summary = report.get("DepartmentUseSummary") if isinstance(report.get("DepartmentUseSummary"), dict) else {}
        if not summary:
            summary = self._synthesize_department_use_summary(report)
        lines.append("Department Use")
        lines.append("--------------")
        lines.append(f"Status: {self._format_department_status(summary.get('Status'))}")
        lines.append(f"Decision: {summary.get('Decision') or '-'}")
        lines.append(f"Blocking: {bool(summary.get('Blocking'))}")
        lines.append(f"Confidence: {self._format_stage_purpose(summary.get('Confidence'))}")
        if summary.get("WorkerResultCount") is not None:
            lines.append(
                "GPU workers: "
                + f"{summary.get('SuccessfulWorkerResultCount', 0)}/{summary.get('WorkerResultCount', 0)} successful, "
                + f"{summary.get('VerificationPasses', 0)} verification passes"
            )
        caveats = summary.get("PrimaryCaveats") if isinstance(summary.get("PrimaryCaveats"), list) else []
        if caveats:
            lines.append("Caveats:")
            for item in caveats[:10]:
                lines.append(f"- {item}")
            if len(caveats) > 10:
                lines.append(f"... {len(caveats) - 10} more caveat(s)")
        notes = summary.get("OperatorNotes") if isinstance(summary.get("OperatorNotes"), list) else []
        if notes:
            lines.append("Operator notes:")
            for item in notes[:10]:
                lines.append(f"- {item}")
            if len(notes) > 10:
                lines.append(f"... {len(notes) - 10} more note(s)")
        lines.append("")

    def _synthesize_department_use_summary(self, report: Dict[str, Any]) -> Dict[str, Any]:
        warnings = report.get("WarningCategoryCounts") if isinstance(report.get("WarningCategoryCounts"), dict) else {}
        errors = report.get("ErrorCategoryCounts") if isinstance(report.get("ErrorCategoryCounts"), dict) else {}
        worker = report.get("GpuWorkerSummary") if isinstance(report.get("GpuWorkerSummary"), dict) else {}
        worker_count = int(worker.get("WorkerResultCount") or 0)
        worker_success = int(worker.get("SuccessfulWorkerResultCount") or 0)
        worker_failures = int(worker.get("WorkerFailureCount") or 0)
        skipped = int(report.get("SkippedStageCount") or 0)
        result = str(report.get("Result") or "").strip().lower()
        blocking = bool(errors or worker_failures or skipped or result in {"aborted", "manually_aborted", "manual_abort", "error", "failed", "fail"})
        if blocking:
            status = "not_ready"
            decision = "Do not use as a passing department validation until the blocking item is resolved."
        elif warnings:
            status = "ready_with_warnings"
            decision = "Usable for department validation with documented non-blocking warnings."
        else:
            status = "ready"
            decision = "Usable for department validation."
        caveats = [f"{self._format_issue_category(key)} ({value})" for key, value in sorted(warnings.items())]
        if skipped:
            caveats.append(f"{skipped} requested stage(s) were skipped")
        notes = []
        if "gpu_vram_telemetry_discrepancy" in warnings:
            notes.append(
                "VRAM worker allocation/verification passed; OS VRAM telemetry may under-report shared-memory or driver-managed allocations."
            )
        if "gpu_thermal_throttle_zone" in warnings or "gpu_temperature" in warnings:
            notes.append("Review cooling, airflow, and ambient conditions for thermal warnings.")
        if not notes and status == "ready":
            notes.append("No warning or error categories were reported.")
        return {
            "Status": status,
            "Decision": decision,
            "Blocking": blocking,
            "Confidence": "worker_verified" if worker_count and worker_count == worker_success and not worker_failures else "telemetry_only_or_cpu_memory",
            "WorkerResultCount": worker_count,
            "SuccessfulWorkerResultCount": worker_success,
            "WorkerFailureCount": worker_failures,
            "VerificationPasses": int(worker.get("VerificationPasses") or 0),
            "PrimaryCaveats": caveats,
            "OperatorNotes": notes,
        }

    def _append_issue_categories(self, lines: List[str], report: Dict[str, Any]) -> None:
        warnings = report.get("WarningCategoryCounts") if isinstance(report.get("WarningCategoryCounts"), dict) else {}
        errors = report.get("ErrorCategoryCounts") if isinstance(report.get("ErrorCategoryCounts"), dict) else {}
        lines.append("Issue Categories")
        lines.append("----------------")
        if warnings:
            lines.append("Warnings:")
            for key, value in sorted(warnings.items()):
                lines.append(f"- {self._format_issue_category(key)}: {value}")
        else:
            lines.append("Warnings: none")
        if errors:
            lines.append("Errors:")
            for key, value in sorted(errors.items()):
                lines.append(f"- {self._format_issue_category(key)}: {value}")
        else:
            lines.append("Errors: none")
        threshold_count = int(report.get("ReportOnlyThresholdWouldWarnCount") or 0)
        if threshold_count:
            lines.append(f"Report-only threshold caveats: {threshold_count}")
        lines.append("")

    def _append_worker_summary(self, lines: List[str], report: Dict[str, Any]) -> None:
        worker_summary = report.get("GpuWorkerSummary") if isinstance(report.get("GpuWorkerSummary"), dict) else {}
        if not worker_summary:
            return
        lines.append("GPU Worker Summary")
        lines.append("------------------")
        lines.append(f"Workers: {worker_summary.get('WorkerResultCount', 0)}")
        lines.append(f"Successful workers: {worker_summary.get('SuccessfulWorkerResultCount', 0)}")
        lines.append(f"Worker failures: {worker_summary.get('WorkerFailureCount', 0)}")
        lines.append(f"Verification passes: {worker_summary.get('VerificationPasses', 0)}")
        lines.append("")

    def _append_stage_summaries(self, lines: List[str], report: Dict[str, Any]) -> None:
        stage_outcomes = report.get("StageOutcomes") if isinstance(report.get("StageOutcomes"), list) else []
        if not stage_outcomes:
            return
        lines.append("Stages")
        lines.append("------")
        for index, stage in enumerate(stage_outcomes, start=1):
            if not isinstance(stage, dict):
                continue
            label = stage.get("Label") or f"Stage {index}"
            lines.append(f"{index}. {label}")
            lines.append(f"   Verdict: {stage.get('Verdict') or '-'}")
            lines.append(f"   Outcome: {stage.get('OutcomeClass') or '-'}")
            purpose = self._format_stage_purpose(stage.get("PrimaryPurpose"))
            confidence = self._format_stage_purpose(stage.get("BackendConfidence"))
            if purpose != "-":
                confidence_suffix = f"; confidence: {confidence}" if confidence != "-" else ""
                lines.append(f"   Purpose: {purpose}{confidence_suffix}")
            lines.append(f"   Targeted GPUs: {stage.get('TargetedGpuCount', 0)}")
            caveats = int(stage.get("ReportOnlyThresholdWouldWarnCount") or 0)
            if caveats:
                lines.append(f"   Report-only threshold caveats: {caveats}")
            self._append_stage_category_line(lines, "Warning", stage.get("WarningCategoryCounts"))
            self._append_stage_category_line(lines, "Error", stage.get("ErrorCategoryCounts"))
            coverage_notes = stage.get("CoverageNotes") if isinstance(stage.get("CoverageNotes"), list) else []
            if not coverage_notes:
                coverage_notes = self._synthesize_stage_coverage_notes(stage)
            for note in coverage_notes:
                note_text = str(note or "").strip()
                if note_text:
                    lines.append(f"   Coverage note: {note_text}")
            sidecar_line = self._format_intel_gpu_top_sidecar(stage.get("IntelGpuTopSidecar"))
            if sidecar_line:
                lines.append(f"   Intel sidecar: {sidecar_line}")
            highlights = stage.get("GpuHighlights") if isinstance(stage.get("GpuHighlights"), list) else []
            for highlight in highlights:
                if isinstance(highlight, dict):
                    lines.append(f"   - {self._format_gpu_highlight(highlight)}")
        lines.append("")

    def _append_stage_category_line(self, lines: List[str], label: str, counts: Any) -> None:
        if not isinstance(counts, dict) or not counts:
            return
        rendered = ", ".join(f"{self._format_issue_category(key)}={value}" for key, value in sorted(counts.items()))
        lines.append(f"   {label} categories: {rendered}")

    def _synthesize_stage_coverage_notes(self, stage: Dict[str, Any]) -> List[str]:
        purpose = str(stage.get("PrimaryPurpose") or "").strip().lower()
        label = str(stage.get("Label") or "").strip().lower()
        if purpose != "gpu_plus_vram_saturation" and not ("gpu" in label and "vram" in label):
            return []
        highlights = stage.get("GpuHighlights") if isinstance(stage.get("GpuHighlights"), list) else []
        vram_omitted = []
        for highlight in highlights:
            if not isinstance(highlight, dict):
                continue
            workloads = list(highlight.get("Workloads", []) or [])
            if "gpu_3d" not in workloads or "vram" in workloads:
                continue
            vram_omitted.append(str(highlight.get("Name") or f"GPU {highlight.get('GpuIndex', '?')}"))
        if not vram_omitted:
            return []
        return [
            "Separate concurrent VRAM worker omitted for "
            + ", ".join(vram_omitted)
            + "; standalone VRAM stage remains the VRAM integrity source for those target(s)."
        ]

    def _format_gpu_highlight(self, highlight: Dict[str, Any]) -> str:
        name = highlight.get("Name") or f"GPU {highlight.get('GpuIndex', '?')}"
        parts = [
            f"busy {self._format_range(highlight.get('UsageAvg'), highlight.get('UsageMax'), '%')}"
        ]
        power = self._format_range(highlight.get("PowerAvgW"), highlight.get("PowerMaxW"), "W")
        if power != "-":
            parts.append(f"power {power}")
        memory_busy = self._format_range(highlight.get("MemoryBusyAvg"), highlight.get("MemoryBusyMax"), "%")
        if memory_busy != "-":
            parts.append(f"mem busy {memory_busy}")
        vram = self._format_value(highlight.get("VramUsedMaxGB"), "GB")
        if vram != "-":
            parts.append(f"vram max {vram}")
        allocation = self._format_value(highlight.get("AllocationPercent"), "%")
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

    def _format_stage_purpose(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return "-"
        labels = {
            "gpu_saturation": "GPU saturation/stress",
            "gpu_plus_vram_saturation": "GPU + VRAM saturation/stress",
            "vram_integrity_and_allocation": "VRAM allocation/integrity",
            "vulkan_memory_path_validation": "Vulkan memory-path validation",
            "vulkan_compute_correctness_baseline": "Vulkan compute correctness baseline",
            "gpu_backend_validation": "GPU backend validation",
            "diagnostic_or_smoke": "diagnostic/smoke only",
            "general_validation": "general validation",
            "preferred": "preferred",
            "validated": "validated",
            "validated_explicit": "validated explicit",
            "limited": "limited",
            "diagnostic": "diagnostic",
            "worker_verified": "worker verified",
            "worker_results_present_with_caveats": "worker results present with caveats",
            "telemetry_only_or_cpu_memory": "telemetry only or CPU/memory",
            "not_applicable": "not applicable",
            "none": "none",
            "failed": "failed",
            "high": "high",
            "medium": "medium",
            "experimental": "experimental",
            "unknown": "unknown",
        }
        return labels.get(text, text.replace("_", " "))

    def _format_department_status(self, value: Any) -> str:
        text = str(value or "").strip()
        labels = {
            "ready": "Ready",
            "ready_with_warnings": "Ready with documented warnings",
            "not_ready": "Not ready",
        }
        return labels.get(text, text.replace("_", " ") if text else "-")

    def _format_issue_category(self, value: Any) -> str:
        text = str(value or "").strip()
        labels = {
            "gpu_thermal_throttle_zone": "GPU thermal warning zone",
            "gpu_temperature": "GPU temperature threshold",
            "gpu_vram_telemetry_discrepancy": "OS VRAM telemetry under-report",
            "gpu_vram_target_attainment": "VRAM allocation target miss",
            "gpu_backend_effectiveness": "GPU backend effectiveness",
            "nvidia_xid": "NVIDIA Xid driver/GPU fault",
            "report_only_threshold_recommendation": "report-only performance recommendation",
            "workload_or_system_error": "workload/system error",
            "skipped_stage": "skipped stage",
        }
        return labels.get(text, text.replace("_", " ") if text else "uncategorized")

    def _format_intel_gpu_top_sidecar(self, sidecar: Any) -> str:
        if not isinstance(sidecar, dict) or not sidecar:
            return ""
        if sidecar.get("Available") is False:
            reason = str(sidecar.get("Reason") or "not available")
            return f"unavailable ({reason})"
        aggregate = sidecar.get("AggregateEngineBusy") if isinstance(sidecar.get("AggregateEngineBusy"), dict) else {}
        if not aggregate:
            return ""
        parts = [
            f"samples {aggregate.get('sample_count', 0)}",
            f"busy {self._format_min_avg_max(aggregate.get('min'), aggregate.get('avg'), aggregate.get('max'), '%')}",
        ]
        below_75 = aggregate.get("samples_below_75_percent")
        below_50 = aggregate.get("samples_below_50_percent")
        idle = aggregate.get("samples_at_or_below_1_percent")
        transitions = aggregate.get("zero_crossing_transitions")
        parts.append(f"lows <75%/{below_75 or 0}, <50%/{below_50 or 0}, <=1%/{idle or 0}")
        if transitions not in (None, ""):
            parts.append(f"zero-cross {transitions}")
        active_engines = sidecar.get("ActiveEngines") if isinstance(sidecar.get("ActiveEngines"), dict) else {}
        if active_engines:
            parts.append("active engines " + ",".join(str(name) for name in sorted(active_engines)))
        return "; ".join(parts)

    def _append_action_items(self, lines: List[str], report: Dict[str, Any]) -> None:
        action_details = report.get("ActionItemDetails") if isinstance(report.get("ActionItemDetails"), list) else []
        action_items = report.get("ActionItems") if isinstance(report.get("ActionItems"), list) else []
        lines.append("Action Items")
        lines.append("------------")
        self._append_action_item_counts(lines, report)
        if action_details:
            severity_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for item in action_details:
                if not isinstance(item, dict):
                    continue
                severity = str(item.get("Severity") or "info").strip().lower()
                if severity == "warn":
                    severity = "warning"
                grouped.setdefault(severity, []).append(item)
            for severity in sorted(grouped, key=lambda key: severity_order.get(key, 99)):
                lines.append(f"{severity.upper()}:")
                for item in grouped[severity]:
                    category = str(item.get("Category") or "uncategorized")
                    count = item.get("Count")
                    count_text = f" ({count})" if count not in (None, "") else ""
                    message = str(item.get("Message") or "")
                    message = self._format_action_message(category, message)
                    lines.append(f"- [{self._format_issue_category(category)}{count_text}] {message}")
            lines.append("")
            return
        if action_items:
            for item in action_items:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")

    def _format_action_message(self, category: str, message: str) -> str:
        key = str(category or "").strip()
        overrides = {
            "gpu_vram_telemetry_discrepancy": (
                "No rerun is required solely for this warning when worker allocation and verification passed; "
                + "treat worker-verified VRAM allocation as authoritative over under-reporting OS telemetry."
            ),
            "gpu_thermal_throttle_zone": (
                "Review cooling, airflow, and ambient conditions before sustained production use; "
                + "at least one GPU reached the configured thermal warning zone."
            ),
            "gpu_temperature": (
                "GPU temperature fail threshold was reached. Treat this as a cooling, airflow, ambient, "
                + "fan, paste/contact, or chassis thermal issue before treating the unit as passing."
            ),
            "report_only_threshold_recommendation": (
                "Review advisory performance threshold misses; workload verification passed, "
                + "but sustained telemetry was below the preferred target."
            ),
            "skipped_stage": (
                "Review skipped stages before using this as a complete profile result; "
                + "at least one requested stage did not run in this environment."
            ),
        }
        return overrides.get(key, message)

    def _append_action_item_counts(self, lines: List[str], report: Dict[str, Any]) -> None:
        severity_counts = report.get("ActionItemSeverityCounts") if isinstance(report.get("ActionItemSeverityCounts"), dict) else {}
        category_counts = report.get("ActionItemCategoryCounts") if isinstance(report.get("ActionItemCategoryCounts"), dict) else {}
        if not severity_counts and not category_counts:
            return
        if severity_counts:
            rendered = ", ".join(f"{key}={value}" for key, value in sorted(severity_counts.items()))
            lines.append(f"Severity counts: {rendered}")
        if category_counts:
            rendered = ", ".join(f"{key}={value}" for key, value in sorted(category_counts.items()))
            lines.append(f"Category counts: {rendered}")
        lines.append("")

    def _append_export_contract(self, lines: List[str], result: Dict[str, Any]) -> None:
        contract = result.get("ExportContract") if isinstance(result.get("ExportContract"), dict) else {}
        if not contract:
            return
        lines.append("Export Contract")
        lines.append("---------------")
        lines.append(f"Schema: {contract.get('Schema') or '-'}")
        lines.append(f"Compatibility mode: {contract.get('CompatibilityMode') or '-'}")
        lines.append(f"Requires legacy importer update: {contract.get('RequiresLegacyImporterUpdate')}")
        lines.append("")

    def _format_value(self, value: Any, suffix: str) -> str:
        if value is None:
            return "-"
        try:
            return f"{float(value):.2f}{suffix}"
        except Exception:
            return f"{value}{suffix}"

    def _format_range(self, avg: Any, max_value: Any, suffix: str) -> str:
        if avg is None and max_value is None:
            return "-"
        avg_text = self._format_value(avg, suffix) if avg is not None else "-"
        max_text = self._format_value(max_value, suffix) if max_value is not None else "-"
        return f"avg {avg_text} / max {max_text}"

    def _format_min_avg_max(self, min_value: Any, avg: Any, max_value: Any, suffix: str) -> str:
        min_text = self._format_value(min_value, suffix) if min_value is not None else "-"
        avg_text = self._format_value(avg, suffix) if avg is not None else "-"
        max_text = self._format_value(max_value, suffix) if max_value is not None else "-"
        return f"min {min_text} / avg {avg_text} / max {max_text}"
