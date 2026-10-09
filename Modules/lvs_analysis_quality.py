#!/usr/bin/env python3
"""Shared planned and observed normalized-analysis quality policy."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional


ANALYSIS_INTENTS = {"functional", "telemetry", "threshold", "sustained"}
LEGACY_ANALYSIS_INTENT = "legacy_unspecified"
NONFUNCTIONAL_ANALYSIS_INTENTS = {"telemetry", "threshold", "sustained"}
THRESHOLD_ANALYSIS_INTENTS = {"threshold", "sustained"}


def normalized_analysis_intent(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in ANALYSIS_INTENTS else LEGACY_ANALYSIS_INTENT


def planned_analysis_evidence(stage: Any, telemetry_interval_seconds: float) -> Dict[str, Any]:
    analysis = getattr(stage, "analysis", None)
    intent = normalized_analysis_intent(getattr(analysis, "intent", None))
    duration = getattr(stage, "duration_seconds", None)
    trim_start = float(getattr(getattr(stage, "normalization", None), "trim_start_seconds", 0) or 0)
    trim_end = float(getattr(getattr(stage, "normalization", None), "trim_end_seconds", 0) or 0)
    expected = None if duration is None else max(0.0, float(duration) - trim_start - trim_end)
    minimum = _positive_number(getattr(analysis, "minimum_usable_seconds", None))
    minimum_samples = _derived_minimum_samples(minimum, telemetry_interval_seconds)
    quality = "not_assessed"
    reasons: list[str] = []
    if intent == "functional":
        quality = "sufficient"
    elif intent in NONFUNCTIONAL_ANALYSIS_INTENTS:
        if minimum is None:
            quality = "invalid"
            reasons.append("minimum_usable_seconds is required for nonfunctional analysis intent")
        elif expected is not None and expected < minimum:
            quality = "insufficient"
            reasons.append(
                f"planned usable analysis window {expected:.2f}s is below the authored minimum {minimum:.2f}s"
            )
        else:
            quality = "sufficient"
    return {
        "intent": intent,
        "quality": quality,
        "expected_usable_seconds": _rounded(expected),
        "minimum_usable_seconds": _rounded(minimum),
        "minimum_samples": minimum_samples,
        "telemetry_interval_seconds": _rounded(_positive_number(telemetry_interval_seconds)),
        "reasons": reasons,
    }


def evaluate_analysis_evidence(
    window: Any,
    samples: Iterable[Any],
    telemetry_interval_seconds: float,
) -> Dict[str, Any]:
    intent = normalized_analysis_intent(getattr(window, "analysis_intent", None))
    minimum = _positive_number(getattr(window, "analysis_minimum_usable_seconds", None))
    start = float(getattr(window, "started_monotonic", 0.0)) + float(
        getattr(window, "trim_start_seconds", 0) or 0
    )
    raw_end = float(getattr(window, "ended_monotonic", start)) - float(
        getattr(window, "trim_end_seconds", 0) or 0
    )
    valid = raw_end >= start
    end = max(start, raw_end)
    rows = sorted(
        (sample for sample in samples if start <= float(getattr(sample, "timestamp", -math.inf)) <= end),
        key=lambda sample: float(getattr(sample, "timestamp", 0.0)),
    ) if valid else []
    timestamps = [float(getattr(sample, "timestamp", 0.0)) for sample in rows]
    duration = max(0.0, raw_end - start) if valid else 0.0
    sample_span = max(0.0, timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0
    max_gap = max(
        (right - left for left, right in zip(timestamps, timestamps[1:])),
        default=None,
    )
    cadence = _positive_number(telemetry_interval_seconds)
    minimum_samples = _derived_minimum_samples(minimum, cadence)
    quality = "not_assessed"
    reasons: list[str] = []
    coverage = None
    if duration > 0 and len(timestamps) > 1:
        coverage = min(1.0, sample_span / duration)

    if not valid:
        quality = "invalid"
        reasons.append("actual trims invert the recorded stage interval")
    elif str(getattr(window, "verdict", "")).strip().lower() in {"aborted", "manually_aborted"}:
        quality = "insufficient" if intent != LEGACY_ANALYSIS_INTENT else "not_assessed"
        reasons.append("stage did not complete normally")
    elif intent == "functional":
        quality = "sufficient"
    elif intent in NONFUNCTIONAL_ANALYSIS_INTENTS:
        if minimum is None:
            quality = "invalid"
            reasons.append("minimum_usable_seconds is required for nonfunctional analysis intent")
        else:
            if duration < minimum:
                reasons.append(
                    f"actual usable analysis window {duration:.2f}s is below the authored minimum {minimum:.2f}s"
                )
            if minimum_samples is not None and len(rows) < minimum_samples:
                reasons.append(
                    f"usable telemetry row count {len(rows)} is below the derived minimum {minimum_samples}"
                )
            if cadence is None:
                reasons.append("telemetry cadence is unknown; coverage cannot be established")
            required_span = minimum * 0.8
            if sample_span < required_span:
                reasons.append(
                    f"usable telemetry sample span {sample_span:.2f}s is below the required coverage span {required_span:.2f}s"
                )
            if cadence is not None and max_gap is not None and max_gap > cadence * 3.0:
                reasons.append(
                    f"maximum telemetry gap {max_gap:.2f}s exceeds three times the known {cadence:.2f}s cadence"
                )
            quality = "insufficient" if reasons else "sufficient"

    return {
        "intent": intent,
        "quality": quality,
        "window_valid": valid,
        "usable_duration_seconds": _rounded(duration),
        "usable_sample_count": len(rows),
        "sample_span_seconds": _rounded(sample_span),
        "maximum_gap_seconds": _rounded(max_gap),
        "coverage_ratio": _rounded(coverage),
        "coverage_known": cadence is not None,
        "minimum_usable_seconds": _rounded(minimum),
        "minimum_samples": minimum_samples,
        "telemetry_interval_seconds": _rounded(cadence),
        "stage_completed": str(getattr(window, "verdict", "")).strip().lower() not in {
            "aborted", "manually_aborted",
        },
        "reasons": reasons,
    }


def telemetry_recommendation_suppression_reason(
    analysis_evidence: Dict[str, Any],
    metric_summary: Optional[Dict[str, Any]] = None,
) -> str:
    intent = normalized_analysis_intent(analysis_evidence.get("intent"))
    if intent == LEGACY_ANALYSIS_INTENT:
        return ""
    if intent not in THRESHOLD_ANALYSIS_INTENTS:
        return f"analysis intent '{intent}' does not authorize threshold conclusions"
    if analysis_evidence.get("quality") != "sufficient":
        reasons = analysis_evidence.get("reasons") or []
        return str(reasons[0]) if reasons else "normalized telemetry analysis quality is insufficient"
    if metric_summary is None:
        return ""
    count = int(metric_summary.get("SampleCount") or 0)
    minimum_samples = analysis_evidence.get("minimum_samples")
    if minimum_samples is not None and count < int(minimum_samples):
        return f"required metric has {count} samples; {int(minimum_samples)} are required"
    required_span = float(analysis_evidence.get("minimum_usable_seconds") or 0.0) * 0.8
    span = float(metric_summary.get("SampleSpanSeconds") or 0.0)
    if span < required_span:
        return f"required metric spans {span:.2f}s; at least {required_span:.2f}s of coverage is required"
    cadence = _positive_number(analysis_evidence.get("telemetry_interval_seconds"))
    max_gap = _positive_number(metric_summary.get("MaxGapSeconds"))
    if cadence is not None and max_gap is not None and max_gap > cadence * 3.0:
        return f"required metric maximum gap {max_gap:.2f}s exceeds three times the known cadence"
    return ""


def impossible_runtime_sustain_requirements(
    stage: Any,
    expected_usable_seconds: Optional[float],
    settings: Any,
) -> list[str]:
    if expected_usable_seconds is None:
        return []
    issues: list[str] = []
    busy_sustain = float(getattr(settings, "target_gpu_busy_sustain_seconds", 0.0) or 0.0)
    memory_sustain = float(getattr(settings, "target_gpu_memory_busy_sustain_seconds", 0.0) or 0.0)
    busy_enabled = float(getattr(settings, "target_gpu_busy_min_percent", 0.0) or 0.0) > 0 and busy_sustain > 0
    memory_enabled = float(getattr(settings, "target_gpu_memory_busy_min_percent", 0.0) or 0.0) > 0 and memory_sustain > 0
    modules = getattr(stage, "modules", None)
    if bool(getattr(getattr(modules, "gpu_3d", None), "enabled", False)) and busy_enabled and busy_sustain > expected_usable_seconds:
        issues.append(
            f"Configured target GPU busy sustain requirement ({busy_sustain:.1f}s) exceeds the planned usable analysis window ({expected_usable_seconds:.1f}s)."
        )
    if bool(getattr(getattr(modules, "vram", None), "enabled", False)) and memory_enabled and memory_sustain > expected_usable_seconds:
        issues.append(
            f"Configured target GPU memory-busy sustain requirement ({memory_sustain:.1f}s) exceeds the planned usable analysis window ({expected_usable_seconds:.1f}s)."
        )
    return issues


def _derived_minimum_samples(minimum_seconds: Optional[float], cadence: Any) -> Optional[int]:
    cadence_value = _positive_number(cadence)
    if minimum_seconds is None:
        return None
    if cadence_value is None:
        return 3
    return max(3, int(math.floor(float(minimum_seconds) / cadence_value * 0.75)))


def _positive_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _rounded(value: Optional[float]) -> Optional[float]:
    return round(float(value), 3) if value is not None else None
