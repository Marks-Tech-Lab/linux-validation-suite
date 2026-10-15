#!/usr/bin/env python3
"""Authoritative GPU performance-evaluation eligibility and evidence policy."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
from typing import Any, Dict, Iterable, Optional

from .lvs_analysis_quality import (
    LEGACY_ANALYSIS_INTENT,
    THRESHOLD_ANALYSIS_INTENTS,
    evaluate_analysis_evidence,
    normalized_analysis_intent,
)
from .lvs_gpu_stage_targets import telemetry_gpu_index
from .lvs_worker_integrity import worker_verification_required, worker_verification_satisfied


GPU_EVALUATION_METRICS = {
    "gpu_busy": {
        "suffix": "busy_percent",
        "semantic": "gpu_engine_busy_percent",
    },
    "memory_busy": {
        "suffix": "memory_busy_percent",
        "semantic": "memory_controller_busy_percent",
    },
}


def normalized_gpu_evaluation_requirements(value: Any) -> Dict[str, Dict[str, Any]]:
    if value is None:
        return {}
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for metric in GPU_EVALUATION_METRICS:
        raw = value.get(metric)
        if raw is None:
            continue
        if is_dataclass(raw):
            raw = asdict(raw)
        if not isinstance(raw, dict):
            continue
        result[metric] = {
            "minimum_percent": _number(raw.get("minimum_percent")),
            "minimum_sustain_seconds": _number(raw.get("minimum_sustain_seconds")),
            "required": bool(raw.get("required", True)),
            "source": str(raw.get("source") or "stage"),
        }
    return result


def resolve_gpu_evaluation_requirements(stage_or_window: Any, settings: Any = None) -> Dict[str, Dict[str, Any]]:
    authored = getattr(stage_or_window, "gpu_evaluation", None)
    if authored is None:
        authored = getattr(stage_or_window, "gpu_evaluation_requirements", None)
    result = normalized_gpu_evaluation_requirements(authored)
    if settings is None:
        return result
    global_fields = {
        "gpu_busy": ("target_gpu_busy_min_percent", "target_gpu_busy_sustain_seconds"),
        "memory_busy": ("target_gpu_memory_busy_min_percent", "target_gpu_memory_busy_sustain_seconds"),
    }
    for metric, (percent_field, sustain_field) in global_fields.items():
        if metric in result:
            continue
        percent = _number(getattr(settings, percent_field, None))
        sustain = _number(getattr(settings, sustain_field, None))
        if percent is not None and percent > 0 and sustain is not None and sustain > 0:
            result[metric] = {
                "minimum_percent": percent,
                "minimum_sustain_seconds": sustain,
                "required": True,
                "source": "global_settings",
            }
    return result


def planned_gpu_evaluation(stage: Any, settings: Any, expected_usable_seconds: Optional[float]) -> Dict[str, Any]:
    intent = normalized_analysis_intent(getattr(getattr(stage, "analysis", None), "intent", None))
    requirements = resolve_gpu_evaluation_requirements(stage, settings)
    warnings: list[str] = []
    issues: list[str] = []
    if requirements and intent not in THRESHOLD_ANALYSIS_INTENTS:
        warnings.append(
            f"GPU performance requirements are not evaluated for analysis intent '{intent}'"
        )
    for metric, requirement in requirements.items():
        sustain = requirement.get("minimum_sustain_seconds")
        if (
            intent in THRESHOLD_ANALYSIS_INTENTS
            and expected_usable_seconds is not None
            and isinstance(sustain, (int, float))
            and sustain > expected_usable_seconds
        ):
            issues.append(
                f"{metric} sustain requirement ({sustain:.1f}s) exceeds the planned usable analysis window ({expected_usable_seconds:.1f}s)"
            )
    return {
        "intent": intent,
        "requirements": requirements,
        "issues": issues,
        "warnings": warnings,
    }


def evaluate_gpu_stage_policy(
    *,
    window: Any,
    target_gpus: Dict[int, Dict[str, Any]],
    samples: Iterable[Any],
    telemetry_interval_seconds: float,
    settings: Any = None,
    source_fields: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    start = float(getattr(window, "started_monotonic", 0.0)) + float(
        getattr(window, "trim_start_seconds", 0.0) or 0.0
    )
    end = float(getattr(window, "ended_monotonic", start)) - float(
        getattr(window, "trim_end_seconds", 0.0) or 0.0
    )
    sample_list = [
        sample for sample in samples
        if start <= float(getattr(sample, "timestamp", -math.inf)) <= end
    ] if end >= start else []
    analysis = dict(getattr(window, "analysis_evidence", {}) or {})
    if not analysis:
        analysis = evaluate_analysis_evidence(window, sample_list, telemetry_interval_seconds)
    intent = normalized_analysis_intent(analysis.get("intent"))
    requirements = resolve_gpu_evaluation_requirements(window, settings)
    worker_results = list(getattr(window, "worker_results", []) or [])
    evaluations: list[Dict[str, Any]] = []
    for gpu_index, target in sorted(target_gpus.items()):
        for metric in GPU_EVALUATION_METRICS:
            requirement = requirements.get(metric)
            evaluations.append(
                _evaluate_metric(
                    gpu_index=int(gpu_index),
                    target=target,
                    metric=metric,
                    requirement=requirement,
                    intent=intent,
                    analysis=analysis,
                    samples=sample_list,
                    cadence=telemetry_interval_seconds,
                    worker_results=worker_results,
                    source_fields=source_fields or {},
                    window=window,
                )
            )
    status_counts: Dict[str, int] = {}
    for entry in evaluations:
        status = str(entry.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "policy_version": 1,
        "intent": intent,
        "analysis_quality": analysis.get("quality", "not_assessed"),
        "requirements": requirements,
        "target_count": len(target_gpus),
        "status_counts": dict(sorted(status_counts.items())),
        "evaluations": evaluations,
    }


def _evaluate_metric(
    *,
    gpu_index: int,
    target: Dict[str, Any],
    metric: str,
    requirement: Optional[Dict[str, Any]],
    intent: str,
    analysis: Dict[str, Any],
    samples: list[Any],
    cadence: float,
    worker_results: list[Dict[str, Any]],
    source_fields: Dict[str, Dict[str, Any]],
    window: Any,
) -> Dict[str, Any]:
    spec = GPU_EVALUATION_METRICS[metric]
    key = f"gpu_{gpu_index}_{spec['suffix']}"
    source = dict(source_fields.get(key) or {})
    rows = _metric_rows(samples, key)
    timeline = _metric_timeline(samples, key)
    sample_span, maximum_gap = _span_and_gap(rows)
    threshold = requirement.get("minimum_percent") if requirement else None
    required_seconds = requirement.get("minimum_sustain_seconds") if requirement else None
    qualifying_seconds = (
        maximum_qualifying_seconds(timeline, float(threshold), cadence)
        if isinstance(threshold, (int, float))
        else None
    )
    eligible, eligibility_reason = _workload_eligibility(metric, gpu_index, target, window, worker_results)
    completion_ok, completion_reason = _worker_integrity(gpu_index, worker_results)
    status = "not_applicable"
    reason = "no authored or applicable GPU performance requirement"
    if intent == LEGACY_ANALYSIS_INTENT:
        status = "not_assessed_legacy"
        reason = "legacy stage has no explicit analysis intent"
    elif intent == "functional":
        status = "not_applicable"
        reason = "functional analysis does not authorize performance-threshold conclusions"
    elif requirement is None:
        status = "not_applicable"
        reason = "no GPU performance requirement was authored or enabled"
    elif intent not in THRESHOLD_ANALYSIS_INTENTS:
        status = "not_applicable"
        reason = f"analysis intent '{intent}' does not authorize performance-threshold conclusions"
    elif not eligible:
        status = "not_applicable"
        reason = eligibility_reason
    elif analysis.get("quality") != "sufficient":
        status = "insufficient_evidence"
        reasons = analysis.get("reasons") or []
        reason = str(reasons[0]) if reasons else "analysis-window quality is insufficient"
    elif not completion_ok:
        status = "insufficient_evidence"
        reason = completion_reason
    elif not rows:
        status = "insufficient_evidence"
        reason = "required telemetry metric is unavailable"
    elif _has_excessive_gap(rows, cadence):
        status = "insufficient_evidence"
        reason = "required telemetry contains a gap exceeding three times the known cadence"
    elif not isinstance(required_seconds, (int, float)) or not isinstance(threshold, (int, float)):
        status = "invalid"
        reason = "GPU evaluation requirement is incomplete"
    elif float(qualifying_seconds or 0.0) >= float(required_seconds):
        status = "met"
        reason = "measured qualifying interval meets the authored requirement"
    else:
        status = "missed"
        reason = "measured qualifying interval is shorter than the authored requirement"
    return {
        "gpu_index": gpu_index,
        "physical_gpu_id": str(target.get("target_id") or f"gpu{gpu_index}"),
        "metric": metric,
        "metric_key": key,
        "metric_semantics": spec["semantic"],
        "status": status,
        "required": bool(requirement and requirement.get("required", True)),
        "threshold_source": str(requirement.get("source") or "") if requirement else "",
        "minimum_percent": threshold,
        "minimum_sustain_seconds": required_seconds,
        "measured_qualifying_seconds": _rounded(qualifying_seconds),
        "observed_sample_count": len(rows),
        "observed_span_seconds": _rounded(sample_span),
        "maximum_gap_seconds": _rounded(maximum_gap),
        "measurement_available": bool(rows),
        "provider": source.get("provider") or source.get("kind") or source.get("source") or None,
        "source_available": source.get("available") if source else None,
        "workload_eligible": eligible,
        "analysis_quality": analysis.get("quality", "not_assessed"),
        "worker_completion_verified": completion_ok,
        "reason": reason,
    }


def _workload_eligibility(
    metric: str,
    gpu_index: int,
    target: Dict[str, Any],
    window: Any,
    worker_results: list[Dict[str, Any]],
) -> tuple[bool, str]:
    workloads = {str(value or "").strip().lower() for value in target.get("workloads", [])}
    backends = {str(value or "").strip().lower() for value in target.get("backends", [])}
    if metric == "memory_busy":
        if not ({"gpu_3d", "vram"} & workloads):
            return False, "memory-busy evaluation is not applicable to this workload"
        return True, ""
    if "gpu_3d" not in workloads or "python_vulkan_compute" not in backends:
        return False, "workload/backend is not an eligible sustained GPU-compute workload"
    variants = {
        str(payload.get("compute_variant") or payload.get("kernel_variant") or "").strip().lower()
        for payload in worker_results
        if telemetry_gpu_index(payload) == gpu_index
    }
    variants.discard("")
    if not variants:
        variants = {
            str(worker.get("compute_variant") or "").strip().lower()
            for worker in (getattr(window, "gpu_workers_final", None) or getattr(window, "gpu_workers_initial", None) or [])
            if telemetry_gpu_index(worker) == gpu_index
        }
        variants.discard("")
    if "stress_hash" not in variants:
        return False, "only the Vulkan stress_hash variant is eligible for GPU-busy performance evaluation"
    return True, ""


def _worker_integrity(gpu_index: int, results: list[Dict[str, Any]]) -> tuple[bool, str]:
    relevant = [
        payload for payload in results
        if str(payload.get("kind") or "").lower() == "gpu" and telemetry_gpu_index(payload) == gpu_index
    ]
    if not relevant:
        return False, "target worker completion evidence is unavailable"
    for payload in relevant:
        if int(payload.get("error_count") or 0) > 0 or str(payload.get("status") or "").lower() in {"error", "crashed", "aborted"}:
            return False, "target worker did not complete cleanly"
        if worker_verification_required(payload) and not worker_verification_satisfied(payload):
            return False, "target worker did not satisfy required readback verification"
    return True, ""


def _metric_rows(samples: list[Any], key: str) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for sample in samples:
        values = getattr(sample, "values", {})
        value = values.get(key) if isinstance(values, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        timestamp = _number(getattr(sample, "timestamp", None))
        if timestamp is not None and math.isfinite(float(value)):
            rows.append((timestamp, float(value)))
    return sorted(rows)


def _metric_timeline(samples: list[Any], key: str) -> list[tuple[float, Optional[float]]]:
    timeline: list[tuple[float, Optional[float]]] = []
    for sample in samples:
        timestamp = _number(getattr(sample, "timestamp", None))
        if timestamp is None:
            continue
        values = getattr(sample, "values", {})
        value = values.get(key) if isinstance(values, dict) else None
        numeric = _number(value)
        timeline.append((timestamp, numeric))
    return sorted(timeline, key=lambda item: item[0])


def maximum_qualifying_seconds(rows: list[tuple[float, Optional[float]]], threshold: float, cadence: float) -> float:
    maximum = 0.0
    run_start: Optional[float] = None
    previous: Optional[float] = None
    cadence_value = _number(cadence)
    max_gap = cadence_value * 3.0 if cadence_value and cadence_value > 0 else None
    for timestamp, value in rows:
        interrupted = previous is not None and max_gap is not None and timestamp - previous > max_gap
        if value is None or value < threshold or interrupted:
            if run_start is not None and previous is not None:
                maximum = max(maximum, previous - run_start)
            run_start = timestamp if value is not None and value >= threshold else None
        elif run_start is None:
            run_start = timestamp
        previous = timestamp
    if run_start is not None and previous is not None:
        maximum = max(maximum, previous - run_start)
    return max(0.0, maximum)


def _span_and_gap(rows: list[tuple[float, float]]) -> tuple[float, Optional[float]]:
    if len(rows) < 2:
        return 0.0, None
    gaps = [right[0] - left[0] for left, right in zip(rows, rows[1:])]
    return max(0.0, rows[-1][0] - rows[0][0]), max(gaps)


def _has_excessive_gap(rows: list[tuple[float, float]], cadence: float) -> bool:
    cadence_value = _number(cadence)
    if cadence_value is None or len(rows) < 2:
        return False
    return any(right[0] - left[0] > cadence_value * 3.0 for left, right in zip(rows, rows[1:]))


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: Optional[float]) -> Optional[float]:
    return round(float(value), 3) if value is not None else None
