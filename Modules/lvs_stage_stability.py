from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .lvs_gpu_backend_catalog import GPU_3D_BACKEND_CATALOG


WindowPredicateFn = Callable[[Any], bool]
WorkerErrorCountFn = Callable[[List[Dict[str, Any]]], int]
LoadQualityCountsFn = Callable[[List[Dict[str, Any]]], Dict[str, int]]


class StageStabilityInterpreter:
    """Build parsed stage stability reasoning from worker, GPU, and event evidence."""

    def __init__(
        self,
        *,
        window_has_operator_stop: WindowPredicateFn,
        worker_integrity_error_count: WorkerErrorCountFn,
        gpu_load_quality_counts: LoadQualityCountsFn,
    ) -> None:
        self._window_has_operator_stop = window_has_operator_stop
        self._worker_integrity_error_count = worker_integrity_error_count
        self._gpu_load_quality_counts = gpu_load_quality_counts

    def interpret(
        self,
        window: Any,
        gpu_targeting: List[Dict[str, Any]],
        gpu_metrics: List[Dict[str, Any]],
        worker_state_summary: Dict[str, Any],
        *,
        strict_threshold_enabled: bool,
    ) -> Dict[str, Any]:
        backend_profiles: List[Dict[str, Any]] = []
        if window.gpu_3d_backend_resolved:
            backend_profiles.append(GPU_3D_BACKEND_CATALOG.get(window.gpu_3d_backend_resolved, {}))
        load_classes = sorted(
            {
                str(profile.get("load_class", "") or "")
                for profile in backend_profiles
                if profile and str(profile.get("load_class", "") or "")
            }
        )
        recommended_for_saturation = any(
            bool(profile.get("recommended_for_saturation"))
            for profile in backend_profiles
            if profile
        )
        targeted_gpu_results = self._targeted_gpu_interpretations(gpu_metrics)
        targeted_quality_counts = self._gpu_load_quality_counts(
            [metric for metric in gpu_metrics if metric.get("Targeted")]
        )
        worker_results = list(window.worker_results or [])
        integrity_error_count = self._worker_integrity_error_count(worker_results)
        aggregate = worker_state_summary.get("Aggregate", {}) if isinstance(worker_state_summary, dict) else {}
        reasons: List[str] = []
        compute_variants = sorted(
            {
                str(payload.get("compute_variant") or payload.get("kernel_variant") or "").strip()
                for payload in worker_results
                if str(payload.get("compute_variant") or payload.get("kernel_variant") or "").strip()
            }
        )
        is_vulkan_hash_baseline = window.gpu_3d_backend_resolved == "python_vulkan_compute" and (
            not compute_variants or compute_variants == ["hash"]
        )
        is_vulkan_stateful_memory = (
            window.gpu_3d_backend_resolved == "python_vulkan_compute"
            and "stateful_memory" in compute_variants
        )

        has_gpu_3d = bool(window.gpu_3d_backend_resolved)
        has_vram = bool(window.vram_backend_resolved) or any(
            str(payload.get("mode") or payload.get("workload") or "").lower() == "vram"
            for payload in worker_results
        )
        diagnostic_only = False
        if has_gpu_3d and load_classes and set(load_classes) <= {"compatibility", "diagnostic", "external_smoke"}:
            diagnostic_only = True
            reasons.append("3D backend is diagnostic/smoke oriented, not a suite stress result")

        if window.verdict == "aborted":
            state = "manually_aborted" if self._window_has_operator_stop(window) else "aborted"
            result = state
            reasons.extend(window.failure_reasons or ["stage aborted"])
        elif window.verdict == "fail" or integrity_error_count > 0:
            state = "unstable"
            result = "unstable"
            if integrity_error_count > 0:
                reasons.append(f"worker integrity/API error count is {integrity_error_count}")
            reasons.extend(window.failure_reasons)
        elif window.verdict == "warning":
            state = "warning"
            result = "warning"
            if window.error_events or window.system_faults:
                reasons.extend(
                    str(event.get("message") or "")
                    for event in [*window.error_events, *window.system_faults]
                    if str(event.get("message") or "")
                )
            if not reasons:
                reasons.append("stage completed with non-blocking warnings")
        elif diagnostic_only:
            state = "diagnostic_only"
            result = "diagnostic_only"
        else:
            state = "stable"
            result = "stable"

        if has_gpu_3d and targeted_gpu_results:
            if recommended_for_saturation:
                weak_targets = [
                    entry
                    for entry in targeted_gpu_results
                    if str(entry.get("LoadQuality") or "") not in {"sustained_extreme", "sustained_high"}
                ]
                if weak_targets:
                    reasons.append(
                        "one or more targeted GPUs showed variable load quality; this is informational unless explicit thresholds are enabled"
                    )
            elif not diagnostic_only:
                reasons.append("3D backend is not marked as a preferred saturation backend")

        if has_vram:
            min_allocation_percent = aggregate.get("MinVramAllocationPercent")
            if isinstance(min_allocation_percent, (int, float)):
                if min_allocation_percent >= 95.0:
                    reasons.append("VRAM allocation target was effectively met")
                elif min_allocation_percent >= 85.0:
                    reasons.append("VRAM allocation target was mostly met")
                else:
                    reasons.append("VRAM allocation target was not fully met")

        if not reasons and result == "stable":
            reasons.append("stage completed without worker errors, system faults, or threshold events")

        backend_confidence = self._stage_backend_confidence(window, backend_profiles, integrity_error_count)
        primary_purpose = "general_validation"
        if diagnostic_only:
            primary_purpose = "diagnostic_or_smoke"
        elif has_vram and has_gpu_3d:
            primary_purpose = "gpu_plus_vram_saturation"
        elif has_vram:
            primary_purpose = "vram_integrity_and_allocation"
        elif is_vulkan_stateful_memory:
            primary_purpose = "vulkan_memory_path_validation"
        elif is_vulkan_hash_baseline:
            primary_purpose = "vulkan_compute_correctness_baseline"
        elif has_gpu_3d and recommended_for_saturation:
            primary_purpose = "gpu_saturation"
        elif has_gpu_3d:
            primary_purpose = "gpu_backend_validation"
        saturation_candidate = bool(
            recommended_for_saturation
            and has_gpu_3d
            and not diagnostic_only
            and not is_vulkan_hash_baseline
            and not is_vulkan_stateful_memory
        )
        memory_path_candidate = bool(has_vram or is_vulkan_stateful_memory)
        if is_vulkan_hash_baseline:
            reasons.append("Vulkan hash variant is treated as a compute/readback correctness baseline, not a memory-path saturation result")
        if is_vulkan_stateful_memory:
            reasons.append("Vulkan stateful_memory variant is treated as a memory-path validation result")
        threshold_recommendations = self._stage_threshold_recommendations(
            primary_purpose,
            targeted_gpu_results,
            aggregate,
            compute_variants,
            strict_threshold_enabled=strict_threshold_enabled,
        )
        strict_threshold_warning = (
            threshold_recommendations.get("StrictModeEnabled")
            and state == "stable"
            and int(threshold_recommendations.get("WouldWarnCount") or 0) > 0
        )
        if strict_threshold_warning:
            state = "warning"
            result = "warning"
            reasons.append(
                "strict threshold recommendation mode is enabled and one or more report-only checks would warn"
            )
            threshold_recommendations["StrictModeApplied"] = True
            threshold_recommendations["StrictModeEffect"] = "warning"
        else:
            threshold_recommendations["StrictModeApplied"] = False
            threshold_recommendations["StrictModeEffect"] = "none"
        warning_category_counts: Dict[str, int] = {}
        error_category_counts: Dict[str, int] = {}
        for event in [*window.error_events, *window.system_faults]:
            category = str(event.get("category") or "uncategorized")
            severity = str(event.get("severity") or "").lower()
            if severity == "warning":
                warning_category_counts[category] = warning_category_counts.get(category, 0) + 1
            elif severity == "error":
                error_category_counts[category] = error_category_counts.get(category, 0) + 1
        outcome_summary = self._stage_outcome_summary(
            window,
            warning_category_counts,
            error_category_counts,
            integrity_error_count,
            threshold_recommendations,
        )
        return {
            "State": state,
            "Result": result,
            "OutcomeClass": outcome_summary["OutcomeClass"],
            "OutcomeSummary": outcome_summary["Summary"],
            "PrimaryPurpose": primary_purpose,
            "BackendConfidence": backend_confidence,
            "DiagnosticOnly": diagnostic_only,
            "SaturationCandidate": saturation_candidate,
            "MemoryPathCandidate": memory_path_candidate,
            "ComputeVariants": compute_variants,
            "BackendLoadClasses": load_classes,
            "BackendRecommendedForSaturation": recommended_for_saturation,
            "IntegrityErrorCount": integrity_error_count,
            "FailureReasonCount": len(window.failure_reasons or []),
            "WarningEventCount": sum(1 for event in [*window.error_events, *window.system_faults] if event.get("severity") == "warning"),
            "ErrorEventCount": sum(1 for event in [*window.error_events, *window.system_faults] if event.get("severity") == "error"),
            "WarningCategoryCounts": dict(sorted(warning_category_counts.items())),
            "ErrorCategoryCounts": dict(sorted(error_category_counts.items())),
            "TargetedGpuCount": sum(1 for entry in gpu_targeting if entry.get("Targeted")),
            "ObservedOnlyGpuCount": sum(1 for entry in gpu_targeting if not entry.get("Targeted")),
            "TargetedLoadQualityCounts": targeted_quality_counts,
            "TargetedGpuResults": targeted_gpu_results,
            "ThresholdRecommendations": threshold_recommendations,
            "WorkerStateAggregate": aggregate,
            "Reasons": list(dict.fromkeys(reason for reason in reasons if reason)),
        }

    def _targeted_gpu_interpretations(self, gpu_metrics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for metric in gpu_metrics:
            if not metric.get("Targeted"):
                continue
            results.append(
                {
                    "GpuIndex": metric.get("GpuIndex"),
                    "Name": metric.get("Name", ""),
                    "TargetIds": list(metric.get("TargetIds", [])),
                    "Workloads": list(metric.get("Workloads", [])),
                    "Backends": list(metric.get("Backends", [])),
                    "LoadQuality": str(metric.get("LoadQuality") or "unknown"),
                    "WorkerEvidence": dict(metric.get("WorkerEvidence") or {}),
                    "UsageMin": (metric.get("Usage") or {}).get("Min"),
                    "UsageAvg": (metric.get("Usage") or {}).get("Avg"),
                    "UsageMax": (metric.get("Usage") or {}).get("Max"),
                    "UsageSustain": metric.get("UsageSustain") or {},
                    "MemoryBusyAvg": (metric.get("MemoryUsage") or {}).get("Avg"),
                    "MemoryBusyMax": (metric.get("MemoryUsage") or {}).get("Max"),
                    "MemoryBusySustain": metric.get("MemoryUsageSustain") or {},
                    "PowerAvgW": (metric.get("Power") or {}).get("Avg"),
                    "PowerMaxW": (metric.get("Power") or {}).get("Max"),
                    "VramUsedMaxGB": (metric.get("VramUsedGB") or {}).get("Max"),
                }
            )
        return results

    def _stage_backend_confidence(
        self,
        window: Any,
        backend_profiles: List[Dict[str, Any]],
        integrity_error_count: int,
    ) -> str:
        if window.verdict == "aborted":
            return "none"
        if integrity_error_count > 0 or window.verdict == "fail":
            return "failed"
        load_classes = {
            str(profile.get("load_class", "") or "")
            for profile in backend_profiles
            if profile
        }
        if not load_classes:
            return "not_applicable"
        if load_classes <= {"compatibility", "diagnostic", "external_smoke"}:
            return "diagnostic"
        if "experimental" in load_classes:
            return "experimental"
        if any(bool(profile.get("recommended_for_saturation")) for profile in backend_profiles):
            if window.gpu_3d_backend_resolved == "python_vulkan_compute":
                return "validated_explicit"
            return "high"
        if "mixed" in load_classes:
            return "medium"
        return "medium"

    def _sustain_percent_from_entry(self, entry: Dict[str, Any], sustain_key: str, threshold: float) -> Optional[float]:
        sustain = entry.get(sustain_key)
        if not isinstance(sustain, dict):
            return None
        for threshold_entry in sustain.get("Thresholds", []):
            if not isinstance(threshold_entry, dict):
                continue
            entry_threshold = threshold_entry.get("Threshold")
            if not isinstance(entry_threshold, (int, float)):
                continue
            if abs(float(entry_threshold) - float(threshold)) > 0.001:
                continue
            percent = threshold_entry.get("PercentAtOrAbove")
            return float(percent) if isinstance(percent, (int, float)) else None
        return None

    def _worker_verified_without_telemetry(self, entry: Dict[str, Any]) -> bool:
        evidence = entry.get("WorkerEvidence")
        if not isinstance(evidence, dict):
            return False
        try:
            worker_count = int(evidence.get("WorkerResultCount") or 0)
            successful_workers = int(evidence.get("SuccessfulWorkerResultCount") or 0)
            worker_errors = int(evidence.get("WorkerErrorCount") or 0)
            verification_passes = int(evidence.get("VerificationPasses") or 0)
        except Exception:
            return False
        return worker_count > 0 and successful_workers == worker_count and worker_errors == 0 and verification_passes > 0

    def _threshold_evaluation_result(
        self,
        observed_avg: Optional[float],
        observed_max: Optional[float],
        sustain_percent: Optional[float],
        *,
        min_avg: Optional[float] = None,
        min_max: Optional[float] = None,
        min_sustain_percent: Optional[float] = None,
    ) -> str:
        if observed_avg is None and observed_max is None and sustain_percent is None:
            return "unobserved"
        misses: List[str] = []
        if min_avg is not None and (observed_avg is None or observed_avg < min_avg):
            misses.append("avg")
        if min_max is not None and (observed_max is None or observed_max < min_max):
            misses.append("max")
        if min_sustain_percent is not None and (sustain_percent is None or sustain_percent < min_sustain_percent):
            misses.append("sustain")
        return "would_warn" if misses else "meets_recommendation"

    def _stage_threshold_recommendations(
        self,
        primary_purpose: str,
        targeted_gpu_results: List[Dict[str, Any]],
        aggregate: Dict[str, Any],
        compute_variants: List[str],
        *,
        strict_threshold_enabled: bool,
    ) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        mode = "report_only"
        strict_enabled = bool(strict_threshold_enabled)
        for entry in targeted_gpu_results:
            gpu_index = entry.get("GpuIndex")
            target_ids = entry.get("TargetIds") or []
            gpu_label = ", ".join(str(item) for item in target_ids) or str(entry.get("Name") or f"gpu{gpu_index}")
            if primary_purpose in {"gpu_saturation", "gpu_plus_vram_saturation"}:
                sustain_90 = self._sustain_percent_from_entry(entry, "UsageSustain", 90.0)
                busy_result = self._threshold_evaluation_result(
                    entry.get("UsageAvg"),
                    entry.get("UsageMax"),
                    sustain_90,
                    min_avg=85.0,
                    min_max=95.0,
                    min_sustain_percent=75.0,
                )
                if busy_result == "unobserved" and self._worker_verified_without_telemetry(entry):
                    busy_result = "telemetry_unobserved_worker_verified"
                checks.append(
                    {
                        "Name": "target_gpu_busy_saturation",
                        "Metric": "gpu_busy_percent",
                        "GpuIndex": gpu_index,
                        "Target": gpu_label,
                        "RecommendedMinAvgPercent": 85.0,
                        "RecommendedMinMaxPercent": 95.0,
                        "RecommendedMinPercentAtOrAbove90": 75.0,
                        "ObservedAvgPercent": entry.get("UsageAvg"),
                        "ObservedMaxPercent": entry.get("UsageMax"),
                        "ObservedPercentAtOrAbove90": sustain_90,
                        "WorkerEvidence": dict(entry.get("WorkerEvidence") or {}),
                        "Result": busy_result,
                    }
                )
            if primary_purpose in {"vulkan_memory_path_validation", "gpu_plus_vram_saturation"}:
                mem_sustain_25 = self._sustain_percent_from_entry(entry, "MemoryBusySustain", 25.0)
                min_mem_max = 25.0 if primary_purpose == "vulkan_memory_path_validation" else None
                min_mem_sustain = 30.0 if primary_purpose == "vulkan_memory_path_validation" else None
                memory_result = self._threshold_evaluation_result(
                    entry.get("MemoryBusyAvg"),
                    entry.get("MemoryBusyMax"),
                    mem_sustain_25,
                    min_max=min_mem_max,
                    min_sustain_percent=min_mem_sustain,
                ) if min_mem_max is not None else "observed_only"
                if memory_result == "unobserved" and self._worker_verified_without_telemetry(entry):
                    memory_result = "telemetry_unobserved_worker_verified"
                checks.append(
                    {
                        "Name": "target_gpu_memory_path_activity",
                        "Metric": "gpu_memory_busy_percent",
                        "GpuIndex": gpu_index,
                        "Target": gpu_label,
                        "RecommendedMinMaxPercent": min_mem_max,
                        "RecommendedMinPercentAtOrAbove25": min_mem_sustain,
                        "ObservedAvgPercent": entry.get("MemoryBusyAvg"),
                        "ObservedMaxPercent": entry.get("MemoryBusyMax"),
                        "ObservedPercentAtOrAbove25": mem_sustain_25,
                        "WorkerEvidence": dict(entry.get("WorkerEvidence") or {}),
                        "Result": memory_result,
                    }
                )
        min_vram_allocation = aggregate.get("MinVramAllocationPercent")
        if primary_purpose in {"gpu_plus_vram_saturation", "vram_integrity_and_allocation"}:
            checks.append(
                {
                    "Name": "vram_allocation_attainment",
                    "Metric": "allocated_vram_percent",
                    "RecommendedMinPercent": 95.0,
                    "ObservedMinPercent": min_vram_allocation,
                    "Result": "unobserved"
                    if not isinstance(min_vram_allocation, (int, float))
                    else ("meets_recommendation" if min_vram_allocation >= 95.0 else "would_warn"),
                }
            )
        if primary_purpose == "vulkan_compute_correctness_baseline":
            checks.append(
                {
                    "Name": "vulkan_hash_correctness_baseline",
                    "Metric": "worker_integrity",
                    "ComputeVariants": compute_variants,
                    "Result": "informational",
                    "Note": "Vulkan hash validates compute dispatch/readback correctness. It is not judged by saturation thresholds.",
                }
            )
        would_warn_count = sum(1 for check in checks if check.get("Result") == "would_warn")
        unobserved_count = sum(1 for check in checks if check.get("Result") == "unobserved")
        worker_verified_no_telemetry_count = sum(
            1
            for check in checks
            if check.get("Result") == "telemetry_unobserved_worker_verified"
        )
        return {
            "Mode": mode,
            "StrictModeDefault": False,
            "StrictModeEnabled": strict_enabled,
            "WouldWarnCount": would_warn_count,
            "UnobservedCount": unobserved_count,
            "WorkerVerifiedNoTelemetryCount": worker_verified_no_telemetry_count,
            "Checks": checks,
        }

    def _stage_outcome_summary(
        self,
        window: Any,
        warning_category_counts: Dict[str, int],
        error_category_counts: Dict[str, int],
        integrity_error_count: int,
        threshold_recommendations: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        threshold_would_warn_count = 0
        if isinstance(threshold_recommendations, dict):
            try:
                threshold_would_warn_count = int(threshold_recommendations.get("WouldWarnCount") or 0)
            except Exception:
                threshold_would_warn_count = 0
        if window.verdict == "aborted":
            if self._window_has_operator_stop(window):
                return {
                    "OutcomeClass": "manually_aborted",
                    "Summary": "Stage was stopped by the operator and partial results were saved.",
                }
            if "gpu_temperature" in error_category_counts:
                return {
                    "OutcomeClass": "thermal_safety_abort",
                    "Summary": "Stage was stopped because a GPU reached the configured temperature fail threshold.",
                }
            return {
                "OutcomeClass": "aborted",
                "Summary": "Stage aborted before completing the planned workload.",
            }
        if error_category_counts or integrity_error_count > 0 or window.verdict == "fail":
            return {
                "OutcomeClass": "workload_or_integrity_failure",
                "Summary": "Stage completed with error-level events or worker integrity failures.",
            }
        warning_categories = set(warning_category_counts)
        if not warning_categories:
            if threshold_would_warn_count > 0:
                return {
                    "OutcomeClass": "worker_verified_threshold_caveat",
                    "Summary": "Worker verification succeeded, but one or more report-only performance recommendations were missed.",
                }
            return {
                "OutcomeClass": "verified_clean",
                "Summary": "Stage completed without warning or error events.",
            }
        non_blocking_categories = {
            "gpu_vram_telemetry_discrepancy",
            "gpu_thermal_throttle_zone",
        }
        if threshold_would_warn_count > 0 and warning_categories <= non_blocking_categories:
            return {
                "OutcomeClass": "worker_verified_non_blocking_warnings",
                "Summary": "Worker verification succeeded with thermal, telemetry-accounting, or report-only performance recommendation warnings.",
            }
        if warning_categories <= {"gpu_vram_telemetry_discrepancy"}:
            return {
                "OutcomeClass": "worker_verified_telemetry_limited",
                "Summary": "Worker allocation and verification succeeded, but OS telemetry did not fully reflect the observed workload.",
            }
        if warning_categories <= {"gpu_thermal_throttle_zone"}:
            return {
                "OutcomeClass": "worker_verified_thermal_warning",
                "Summary": "Worker verification succeeded, but thermal readings reached the configured throttle-warning zone.",
            }
        if warning_categories <= non_blocking_categories:
            return {
                "OutcomeClass": "worker_verified_non_blocking_warnings",
                "Summary": "Worker verification succeeded with thermal or telemetry-accounting warnings.",
            }
        return {
            "OutcomeClass": "verified_with_warnings",
            "Summary": "Stage completed with warning-level events; review warning categories for details.",
        }
