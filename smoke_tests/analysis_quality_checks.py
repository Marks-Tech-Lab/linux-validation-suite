#!/usr/bin/env python3
"""Deterministic effective analysis-window policy regression checks."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from Modules.lvs_analysis_quality import (
    evaluate_analysis_evidence,
    impossible_runtime_sustain_requirements,
    planned_analysis_evidence,
    telemetry_recommendation_suppression_reason,
)
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_models import (
    ModuleGpu3D,
    ModuleVram,
    ProfileDefaults,
    StageAnalysis,
    StageConfig,
    StageModules,
    StageNormalization,
    ValidationProfile,
)
from Modules.lvs_profile_report_text import profile_execution_summary_lines
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_report_helpers import build_report_stage_summary
from Modules.lvs_report_html import _stage_card
from Modules.lvs_run_models import StageWindow
from Modules.lvs_segment_metric_helpers import SegmentMetricHelper
from Modules.lvs_sensor_events import stage_sensor_events
from Modules.lvs_stage_stability import StageStabilityInterpreter
from Modules.lvs_summary_text import SummaryTextBuilder
from Modules.lvs_telemetry_samples import Sample
from Modules.lvs_worker_integrity import worker_integrity_error_count


def _stage(intent: str | None, minimum: float | None, *, duration: int = 30) -> StageConfig:
    return StageConfig(
        id="quality",
        name="GPU",
        duration_seconds=duration,
        modules=StageModules(gpu_3d=ModuleGpu3D(enabled=True)),
        normalization=StageNormalization(5, 5),
        analysis=StageAnalysis(intent, minimum) if intent is not None else None,
    )


def _window(intent: str, minimum: float | None, *, end: float = 40.0, verdict: str = "pass") -> StageWindow:
    return StageWindow(
        stage_id="quality", stage_type="GPU", display_name="GPU",
        started_iso="", ended_iso="", started_monotonic=0.0, ended_monotonic=end,
        duration_seconds=end, trim_start_seconds=5, trim_end_seconds=5,
        verdict=verdict, analysis_intent=intent,
        analysis_minimum_usable_seconds=minimum,
    )


def _samples(timestamps: list[float], *, field: str = "gpu_0_busy_percent") -> list[Sample]:
    return [Sample(timestamp, {field: 95.0}) for timestamp in timestamps]


def run_analysis_quality_checks() -> None:
    validator = ProfileValidator()

    # A: impossible planned window remains a hard validation failure.
    impossible = _stage("functional", None, duration=10)
    profile = ValidationProfile("impossible", stages=[impossible])
    validation = validator.validate(profile, ["impossible"])
    assert any("trim window is impossible" in item for item in validation["errors"])

    # B/G: a short functional stage remains valid regardless of telemetry density.
    functional = _window("functional", None, end=30.0)
    functional_evidence = evaluate_analysis_evidence(functional, _samples([5.0, 20.0, 25.0]), 1.0)
    assert functional_evidence["quality"] == "sufficient"
    dense_functional = evaluate_analysis_evidence(functional, _samples([5.0 + index * 0.1 for index in range(201)]), 0.1)
    assert dense_functional["quality"] == "sufficient"

    # C: an undersized authored threshold window warns without invalidating the profile.
    short_threshold = _stage("threshold", 30.0, duration=30)
    threshold_profile = ValidationProfile(
        "threshold", defaults=ProfileDefaults(telemetry_interval_seconds=1.0), stages=[short_threshold]
    )
    validation = validator.validate(threshold_profile, ["threshold"])
    assert not validation["errors"] and any("below the authored minimum" in item for item in validation["warnings"])
    assert planned_analysis_evidence(short_threshold, 1.0)["quality"] == "insufficient"

    # D: adequate duration, samples, span, and cadence evaluate normally.
    adequate_window = _window("threshold", 20.0, end=35.0)
    adequate = evaluate_analysis_evidence(adequate_window, _samples(list(range(5, 31))), 1.0)
    assert adequate["quality"] == "sufficient"
    metric = SegmentMetricHelper().metric_sustain_summary(_samples(list(range(5, 31))), "gpu_0_busy_percent")
    assert not telemetry_recommendation_suppression_reason(adequate, metric)

    # E: an early/aborted stage records insufficiency independently of execution state.
    aborted = evaluate_analysis_evidence(_window("threshold", 20.0, end=12.0, verdict="aborted"), _samples([5, 6, 7]), 1.0)
    assert aborted["quality"] == "insufficient" and not aborted["stage_completed"]

    # F/P: long but sparse or badly gapped telemetry is insufficient.
    sparse = evaluate_analysis_evidence(_window("sustained", 20.0), _samples([5.0, 15.0, 35.0]), 1.0)
    assert sparse["quality"] == "insufficient"
    assert any("row count" in reason or "gap" in reason for reason in sparse["reasons"])

    # H/I: missing analysis metadata remains valid and is not retroactively assessed.
    legacy = _stage(None, None, duration=90)
    legacy_profile = ValidationProfile("legacy", stages=[legacy])
    assert not validator.validate(legacy_profile, ["legacy"])["errors"]
    legacy_evidence = evaluate_analysis_evidence(_window("legacy_unspecified", None), _samples([5, 10, 20]), 1.0)
    assert legacy_evidence["quality"] == "not_assessed"
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "legacy.json"
        source.write_text(json.dumps({
            "profile_name": "legacy", "stages": [{
                "id": "one", "name": "CPU", "duration_seconds": 90,
                "modules": {"cpu": {"enabled": True}},
                "normalization": {"trim_start_seconds": 5, "trim_end_seconds": 5},
            }],
        }), encoding="utf-8")
        loader = ProfileLoader(root)
        loaded = loader.load_profile(source)
        assert loaded.stages[0].analysis is None
        saved = root / "saved.json"
        loader.save_profile(saved, loaded)
        assert "analysis" not in json.loads(saved.read_text(encoding="utf-8"))["stages"][0]
        invalid = root / "invalid.json"
        invalid.write_text(source.read_text(encoding="utf-8").replace(
            '"normalization": {"trim_start_seconds": 5, "trim_end_seconds": 5}',
            '"analysis": [], "normalization": {"trim_start_seconds": 5, "trim_end_seconds": 5}',
        ), encoding="utf-8")
        try:
            loader.load_profile(invalid)
        except ValueError as exc:
            assert "analysis must be an object" in str(exc)
        else:
            raise AssertionError("invalid analysis structure must fail profile loading")

    # J: shared presentation exposes the same planned state and expected duration.
    plan = planned_analysis_evidence(short_threshold, 1.0)
    lines = profile_execution_summary_lines({
        "profile_name": "threshold", "runnable": True, "enabled_stage_count": 1,
        "runnable_stage_count": 1, "plan": [{
            "stage_id": "quality", "label": "quality", "type": "GPU", "duration_seconds": 30,
            "enabled": True, "runnable": True, "workloads": ["gpu_3d"],
            "trim_start_seconds": 5, "trim_end_seconds": 5,
            "expected_usable_seconds": 20.0, "analysis_evidence": plan,
        }],
    })
    rendered = "\n".join(lines)
    assert "expected analysis=20.0s" in rendered and "intent=threshold" in rendered

    # K: one sample cannot establish threshold or sustained quality.
    one = evaluate_analysis_evidence(_window("sustained", 20.0), _samples([20.0]), 1.0)
    assert one["quality"] == "insufficient"

    # J/K: structured report, text summary, HTML, and shared CLI/TUI state agree.
    stage_summary = build_report_stage_summary({
        "Label": "Sustained GPU", "TestType": "GPU", "Verdict": "pass",
        "AnalysisEvidence": one,
        "StabilityInterpretation": {
            "ThresholdRecommendations": {"WouldWarnCount": 0, "InsufficientEvidenceCount": 1},
        },
    })
    assert stage_summary["AnalysisEvidence"] == one
    assert stage_summary["ReportOnlyThresholdInsufficientEvidenceCount"] == 1
    summary_text = SummaryTextBuilder().build({"ReportSummary": {"StageOutcomes": [stage_summary]}})
    assert "Verdict: pass" in summary_text
    assert "Analysis: sustained / insufficient" in summary_text
    assert "Suppressed threshold recommendations: 1" in summary_text
    stage_html = _stage_card({
        "index": 0, "display_name": "Sustained GPU", "native_outcome": "pass",
        "duration_seconds": 30, "analysis_evidence": one, "metrics": [],
    }, {})
    assert ">PASS<" in stage_html and "Analysis insufficient" in stage_html

    # L: an inverted actual window is explicit rather than silently usable.
    inverted_window = _window("threshold", 1.0, end=8.0)
    inverted_window.trim_start_seconds = 5
    inverted_window.trim_end_seconds = 5
    inverted = evaluate_analysis_evidence(inverted_window, _samples([5.0]), 1.0)
    assert inverted["quality"] == "invalid" and inverted["window_valid"] is False

    # M/Q: direct worker allocation survives telemetry suppression and missing series.
    interpreter = StageStabilityInterpreter(
        window_has_operator_stop=lambda window: False,
        worker_integrity_error_count=worker_integrity_error_count,
        gpu_load_quality_counts=lambda entries: {},
    )
    targeted = [{
        "GpuIndex": 0, "Name": "GPU", "TargetIds": ["pci:0"],
        "UsageAvg": 95.0, "UsageMax": 100.0,
        "UsageSustain": {"SampleCount": 1, "SampleSpanSeconds": 0.0, "Thresholds": []},
        "MemoryBusyAvg": None, "MemoryBusyMax": None,
        "MemoryBusySustain": {"SampleCount": 0, "SampleSpanSeconds": 0.0, "Thresholds": []},
        "WorkerEvidence": {},
    }]
    recommendations = interpreter._stage_threshold_recommendations(
        "gpu_plus_vram_saturation", targeted, {"MinVramAllocationPercent": 100.0}, [],
        strict_threshold_enabled=True, analysis_evidence={**one, "intent": "sustained"},
    )
    checks = {item["Name"]: item for item in recommendations["Checks"]}
    assert checks["target_gpu_busy_saturation"]["Result"] == "insufficient_evidence"
    assert checks["target_gpu_busy_saturation"]["EvidenceBasis"] == "normalized_telemetry"
    assert checks["vram_allocation_attainment"]["Result"] == "meets_recommendation"
    assert checks["vram_allocation_attainment"]["EvidenceBasis"] == "worker_direct"
    assert recommendations["WouldWarnCount"] == 0 and recommendations["InsufficientEvidenceCount"] >= 1

    # N: an observed dangerous temperature remains an immediate safety event.
    thermal = stage_sensor_events(
        samples=[Sample(1.0, {"gpu_0_temp_core_c": 105.0})], stage_name="hot",
        metric_thresholds=lambda key: {"warn_c": 90.0, "fail_c": 100.0, "source": "test"},
        abort_on_fail_threshold=True, gpu_thermal_throttle_hint_c=85.0,
        gpu_hotspot_warn_c=100.0, gpu_hotspot_fail_c=110.0,
        gpu_memory_temp_warn_c=95.0, gpu_memory_temp_fail_c=105.0,
    )
    assert thermal and thermal[0]["severity"] == "error"

    # O: impossible configured sustain assertions are caught before execution.
    settings = SimpleNamespace(
        target_gpu_busy_min_percent=90.0, target_gpu_busy_sustain_seconds=30.0,
        target_gpu_memory_busy_min_percent=0.0, target_gpu_memory_busy_sustain_seconds=0.0,
    )
    issues = impossible_runtime_sustain_requirements(short_threshold, 20.0, settings)
    assert issues and "exceeds" in issues[0]

    # Q plus explicit multi-worker integrity: success cannot mask missing verification.
    workers = [
        {"status": "ok", "verification_required": True, "verification_passes": 2},
        {"status": "ok", "verification_required": True, "verification_passes": 0},
    ]
    assert worker_integrity_error_count(workers) == 1


if __name__ == "__main__":
    run_analysis_quality_checks()
    print("analysis quality checks passed")
