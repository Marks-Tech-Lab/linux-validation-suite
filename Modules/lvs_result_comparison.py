#!/usr/bin/env python3
"""Frontend-neutral completed result comparison service."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lvs_core import APP_NAME, APP_VERSION, JsonStore, now_local_iso


class ResultComparisonFacade:
    """Build structured comparisons between completed result folders."""

    def compare_result_folders(self, baseline_dir: Path, comparison_dir: Path) -> Dict[str, Any]:
        baseline = self.load_custom_result(baseline_dir)
        comparison = self.load_custom_result(comparison_dir)
        baseline_summary = self.comparison_summary(baseline)
        comparison_summary = self.comparison_summary(comparison)
        payload: Dict[str, Any] = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "kind": "result_comparison",
            "started": now_local_iso(),
            "baseline_folder": str(baseline_dir),
            "comparison_folder": str(comparison_dir),
            "baseline": baseline_summary,
            "comparison": comparison_summary,
            "deltas": {},
        }
        payload["deltas"]["warning_categories"] = self.dict_numeric_delta(
            baseline_summary.get("warning_categories", {}),
            comparison_summary.get("warning_categories", {}),
        )
        payload["deltas"]["error_categories"] = self.dict_numeric_delta(
            baseline_summary.get("error_categories", {}),
            comparison_summary.get("error_categories", {}),
        )
        payload["deltas"]["gpu_worker_summary"] = self.dict_numeric_delta(
            baseline_summary.get("gpu_worker_summary", {}),
            comparison_summary.get("gpu_worker_summary", {}),
        )
        payload["deltas"]["action_item_categories"] = self.dict_numeric_delta(
            baseline_summary.get("action_item_category_counts", {}),
            comparison_summary.get("action_item_category_counts", {}),
        )
        payload["deltas"]["action_item_severities"] = self.dict_numeric_delta(
            baseline_summary.get("action_item_severity_counts", {}),
            comparison_summary.get("action_item_severity_counts", {}),
        )
        payload["deltas"]["stages"] = self.stage_comparison_deltas(
            baseline_summary.get("stages", {}),
            comparison_summary.get("stages", {}),
        )
        payload["ended"] = now_local_iso()
        return payload

    def load_custom_result(self, result_dir: Path) -> Dict[str, Any]:
        path = result_dir / "parsed_results_custom.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path} root is not a JSON object")
        return payload

    @staticmethod
    def comparison_report_slug(baseline_dir: Path) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", baseline_dir.name).strip("_") or "baseline"

    def write_comparison_report(
        self,
        baseline_dir: Path,
        comparison_dir: Path,
        text: str,
        payload: Dict[str, Any],
    ) -> Path:
        slug = self.comparison_report_slug(baseline_dir)
        JsonStore.write(comparison_dir / f"result_comparison_vs_{slug}.json", payload)
        (comparison_dir / f"result_comparison_vs_{slug}.txt").write_text(text, encoding="utf-8")
        return comparison_dir

    def comparison_summary(self, result: Dict[str, Any]) -> Dict[str, Any]:
        report = result.get("ReportSummary") if isinstance(result.get("ReportSummary"), dict) else {}
        stages: Dict[str, Any] = {}
        for stage in report.get("StageOutcomes", []) if isinstance(report.get("StageOutcomes"), list) else []:
            if not isinstance(stage, dict):
                continue
            label = str(stage.get("Label") or f"stage_{len(stages) + 1}")
            stages[label] = {
                "verdict": stage.get("Verdict"),
                "outcome_class": stage.get("OutcomeClass"),
                "targeted_gpu_count": stage.get("TargetedGpuCount"),
                "warning_categories": dict(stage.get("WarningCategoryCounts") or {}),
                "error_categories": dict(stage.get("ErrorCategoryCounts") or {}),
                "report_only_threshold_would_warn_count": stage.get("ReportOnlyThresholdWouldWarnCount", 0),
                "gpu_highlights": {
                    self.gpu_highlight_comparison_key(item): item
                    for item in stage.get("GpuHighlights", [])
                    if isinstance(item, dict)
                },
            }
        return {
            "result": report.get("Result") or result.get("Result") or result.get("result"),
            "outcome_class": report.get("OutcomeClass"),
            "outcome_summary": report.get("OutcomeSummary"),
            "elapsed": report.get("Elapsed") or result.get("Elapsed") or result.get("elapsed"),
            "warning_categories": dict(report.get("WarningCategoryCounts") or {}),
            "error_categories": dict(report.get("ErrorCategoryCounts") or {}),
            "gpu_worker_summary": self.normalized_gpu_worker_summary(report.get("GpuWorkerSummary") or {}),
            "action_item_category_counts": dict(report.get("ActionItemCategoryCounts") or {}),
            "action_item_severity_counts": dict(report.get("ActionItemSeverityCounts") or {}),
            "stages": stages,
        }

    def dict_numeric_delta(self, baseline: Dict[str, Any], comparison: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        delta: Dict[str, Dict[str, Any]] = {}
        for key in sorted({*baseline.keys(), *comparison.keys()}):
            old = baseline.get(key, 0)
            new = comparison.get(key, 0)
            if old == new:
                continue
            delta[key] = {
                "baseline": old,
                "comparison": new,
                "delta": self.numeric_delta(old, new),
            }
        return delta

    def numeric_delta(self, old: Any, new: Any) -> Optional[float]:
        try:
            return round(float(new or 0) - float(old or 0), 4)
        except Exception:
            return None

    def normalized_gpu_worker_summary(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(summary, dict):
            return {}
        normalized = {
            key: value
            for key, value in summary.items()
            if key not in {
                "Total",
                "WorkerResultCount",
                "Passed",
                "SuccessfulWorkerResultCount",
                "Failed",
                "WorkerFailureCount",
            }
        }
        if "Passed" in summary or "SuccessfulWorkerResultCount" in summary:
            normalized["Passed"] = summary.get("Passed", summary.get("SuccessfulWorkerResultCount"))
        if "Failed" in summary or "WorkerFailureCount" in summary:
            normalized["Failed"] = summary.get("Failed", summary.get("WorkerFailureCount"))
        return normalized

    def stage_comparison_deltas(
        self,
        baseline_stages: Dict[str, Any],
        comparison_stages: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for label in sorted({*baseline_stages.keys(), *comparison_stages.keys()}):
            if label not in baseline_stages:
                results.append({"label": label, "status": "added"})
                continue
            if label not in comparison_stages:
                results.append({"label": label, "status": "removed"})
                continue
            old = baseline_stages[label]
            new = comparison_stages[label]
            changes: List[str] = []
            for key, display in (
                ("verdict", "verdict"),
                ("outcome_class", "outcome"),
                ("targeted_gpu_count", "targeted GPUs"),
                ("report_only_threshold_would_warn_count", "report-only threshold caveats"),
            ):
                if old.get(key) != new.get(key):
                    changes.append(f"{display}: {old.get(key)} -> {new.get(key)}")
            warning_delta = self.dict_numeric_delta(old.get("warning_categories", {}), new.get("warning_categories", {}))
            error_delta = self.dict_numeric_delta(old.get("error_categories", {}), new.get("error_categories", {}))
            for key, delta in warning_delta.items():
                changes.append(f"warning {key}: {delta.get('baseline')} -> {delta.get('comparison')} (delta {delta.get('delta')})")
            for key, delta in error_delta.items():
                changes.append(f"error {key}: {delta.get('baseline')} -> {delta.get('comparison')} (delta {delta.get('delta')})")
            gpu_deltas = self.gpu_highlight_deltas(
                old.get("gpu_highlights", {}),
                new.get("gpu_highlights", {}),
            )
            if changes or gpu_deltas:
                results.append(
                    {
                        "label": label,
                        "status": "common",
                        "changes": changes or ["stage status unchanged"],
                        "gpu_highlight_deltas": gpu_deltas,
                    }
                )
        return results

    def gpu_highlight_deltas(
        self,
        baseline: Dict[str, Dict[str, Any]],
        comparison: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        metrics = (
            "UsageAvg",
            "UsageMax",
            "MemoryBusyAvg",
            "MemoryBusyMax",
            "PowerAvgW",
            "PowerMaxW",
            "VramUsedAvgGB",
            "VramUsedMaxGB",
            "AllocationPercent",
            "VerificationPasses",
        )
        mapping_fields = (
            "LoadQuality",
            "TelemetryMissing",
            "TargetIds",
            "Cards",
            "Slots",
            "Workloads",
            "Backends",
        )
        for name in sorted({*baseline.keys(), *comparison.keys()}):
            if name not in baseline:
                results.append({"name": name, "status": "added", "deltas": {}})
                continue
            if name not in comparison:
                results.append({"name": name, "status": "removed", "deltas": {}})
                continue
            deltas: Dict[str, Dict[str, Any]] = {}
            changes: List[str] = []
            for metric in metrics:
                old = baseline[name].get(metric)
                new = comparison[name].get(metric)
                if old == new:
                    continue
                deltas[metric] = {
                    "baseline": old,
                    "comparison": new,
                    "delta": self.numeric_delta(old, new),
                }
            for field in mapping_fields:
                old = self.normalized_comparison_value(baseline[name].get(field))
                new = self.normalized_comparison_value(comparison[name].get(field))
                if old != new:
                    changes.append(f"{field}: {old} -> {new}")
            if deltas or changes:
                results.append({"name": name, "status": "common", "changes": changes, "deltas": deltas})
        return results

    def gpu_highlight_comparison_key(self, highlight: Dict[str, Any]) -> str:
        gpu_index = highlight.get("GpuIndex")
        name = str(highlight.get("Name") or "").strip()
        target_ids = highlight.get("TargetIds") if isinstance(highlight.get("TargetIds"), list) else []
        target = str(target_ids[0]) if target_ids else ""
        if gpu_index is not None:
            return f"gpu_{gpu_index}:{name or target or 'unknown'}"
        if target:
            return f"target:{target}:{name or 'unknown'}"
        return name or "GPU ?"

    def normalized_comparison_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return sorted(str(item) for item in value)
        if isinstance(value, dict):
            return {str(key): self.normalized_comparison_value(value[key]) for key in sorted(value)}
        return value
