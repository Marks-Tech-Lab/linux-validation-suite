#!/usr/bin/env python3
"""Deterministic GPU evaluation-policy regression matrix."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from Modules.lvs_gpu_evaluation_policy import (
    evaluate_gpu_stage_policy,
    normalized_gpu_evaluation_requirements,
    planned_gpu_evaluation,
)
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_editor import ProfileEditor
from Modules.lvs_profile_edit_view import profile_stage_summary_lines
from Modules.lvs_profile_models import (
    GpuMetricEvaluationRequirement,
    ModuleGpu3D,
    ModuleVram,
    ProfileDefaults,
    StageAnalysis,
    StageConfig,
    StageGpuEvaluation,
    StageModules,
    StageNormalization,
    ValidationProfile,
)
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_orchestrator_stage_callbacks import stage_target_gpu_utilization_events
from Modules.lvs_run_models import StageWindow
from Modules.lvs_segment_gpu_metrics import GpuMetricSectionBuilder
from Modules.lvs_stage_stability import StageStabilityInterpreter
from Modules.lvs_telemetry_samples import Sample


def _window(intent: str, *, quality: str = "sufficient", requirement: dict | None = None) -> StageWindow:
    window = StageWindow(
        stage_id="gpu", stage_type="3D Adaptive", display_name="GPU",
        started_iso="", ended_iso="", started_monotonic=0.0, ended_monotonic=80.0,
        duration_seconds=80.0, trim_start_seconds=10, trim_end_seconds=10,
        gpu_3d_backend_resolved="python_vulkan_compute",
        gpu_workers_final=[{
            "telemetry_gpu_index": 1, "target_id": "pci:000f:01:00.0", "workload": "gpu_3d",
            "backend": "python_vulkan_compute", "compute_variant": "stress_hash",
        }],
        worker_results=[{
            "kind": "gpu", "telemetry_gpu_index": 1, "target_id": "pci:000f:01:00.0",
            "status": "ok", "error_count": 0, "suite_verification": "readback",
            "verification_passes": 4, "compute_variant": "stress_hash",
        }],
        analysis_intent=intent, analysis_minimum_usable_seconds=50.0,
        analysis_evidence={
            "intent": intent, "quality": quality, "minimum_usable_seconds": 50.0,
            "reasons": [] if quality == "sufficient" else ["window too short"],
        },
        gpu_evaluation_requirements=requirement or {},
    )
    return window


def _targets(*, second: bool = False) -> dict:
    targets = {1: {
        "gpu_index": 1, "target_id": "pci:000f:01:00.0", "workloads": ["gpu_3d"],
        "backends": ["python_vulkan_compute"], "device_class": "integrated",
    }}
    if second:
        targets[2] = {
            "gpu_index": 2, "target_id": "pci:0001:02:00.0", "workloads": ["gpu_3d"],
            "backends": ["python_vulkan_compute"], "device_class": "discrete",
        }
    return targets


def _samples(values: list[tuple[float, float | None]], *, gpu_index: int = 1, metric: str = "busy_percent") -> list[Sample]:
    return [
        Sample(timestamp, {} if value is None else {f"gpu_{gpu_index}_{metric}": value})
        for timestamp, value in values
    ]


def _requirement(metric: str = "gpu_busy", percent: float = 80.0, seconds: float = 20.0, required: bool = True) -> dict:
    return {metric: {
        "minimum_percent": percent, "minimum_sustain_seconds": seconds,
        "required": required, "source": "stage",
    }}


def _evaluate(window: StageWindow, samples: list[Sample], targets: dict | None = None) -> dict:
    return evaluate_gpu_stage_policy(
        window=window, target_gpus=targets or _targets(), samples=samples,
        telemetry_interval_seconds=1.0,
        source_fields={"gpu_1_busy_percent": {"available": True, "provider": "nvidia"}},
    )


def run_gpu_evaluation_policy_checks() -> None:
    dense = _samples([(float(t), 90.0) for t in range(10, 71)])

    # 1: successful functional work is not judged by a saturation heuristic.
    result = _evaluate(_window("functional", requirement=_requirement()), dense)
    assert result["evaluations"][0]["status"] == "not_applicable"

    # 2: eligible sustained stress with sufficient timestamp evidence can meet an authored target.
    result = _evaluate(_window("sustained", requirement=_requirement()), dense)
    assert result["evaluations"][0]["status"] == "met"

    # 3: legacy stages preserve observations without a performance verdict.
    result = _evaluate(_window("legacy_unspecified", requirement=_requirement()), dense)
    assert result["evaluations"][0]["status"] == "not_assessed_legacy"

    # 4: insufficient analysis quality suppresses evaluation.
    result = _evaluate(_window("sustained", quality="insufficient", requirement=_requirement()), dense)
    assert result["evaluations"][0]["status"] == "insufficient_evidence"

    # 5: sparse samples do not manufacture sustained time.
    sparse = _samples([(10.0, 90.0), (30.0, 90.0), (70.0, 90.0)])
    result = _evaluate(_window("sustained", requirement=_requirement()), sparse)
    assert result["evaluations"][0]["status"] == "insufficient_evidence"

    # 6: a gap interrupts the qualifying run.
    gapped = _samples([(10.0, 90.0), (11.0, 90.0), (30.0, 90.0), (31.0, 90.0)])
    result = _evaluate(_window("sustained", requirement=_requirement(seconds=3.0)), gapped)
    assert result["evaluations"][0]["status"] == "insufficient_evidence"

    # 7/8: genuine zero is measured; missing/N/A rows are unavailable.
    zero = _evaluate(_window("sustained", requirement=_requirement(percent=0.0, seconds=2.0)), _samples([(10, 0), (11, 0), (12, 0)]))
    assert zero["evaluations"][0]["status"] == "met" and zero["evaluations"][0]["observed_sample_count"] == 3
    missing = _evaluate(_window("sustained", requirement=_requirement()), _samples([(10, None), (11, None)]))
    assert missing["evaluations"][0]["status"] == "insufficient_evidence"
    interrupted = _evaluate(
        _window("sustained", requirement=_requirement(percent=80, seconds=3)),
        _samples([(10, 90), (11, 90), (12, None), (13, 90), (14, 90)]),
    )
    assert interrupted["evaluations"][0]["status"] == "missed"

    # 9/10/11: provider naming is preserved without changing NVIDIA/AMD/Intel metric semantics.
    for provider in ("nvidia", "amd_sysfs", "intel_gpu_top"):
        evidence = evaluate_gpu_stage_policy(
            window=_window("sustained", requirement=_requirement()), target_gpus=_targets(), samples=dense,
            telemetry_interval_seconds=1.0,
            source_fields={"gpu_1_busy_percent": {"available": True, "provider": provider}},
        )
        assert evidence["evaluations"][0]["provider"] == provider
        assert evidence["evaluations"][0]["metric_semantics"] == "gpu_engine_busy_percent"

    # 12/13: explicit stage settings override global fallback; global values apply only when absent.
    settings = type("Settings", (), {
        "target_gpu_busy_min_percent": 70.0, "target_gpu_busy_sustain_seconds": 15.0,
        "target_gpu_memory_busy_min_percent": 0.0, "target_gpu_memory_busy_sustain_seconds": 0.0,
    })()
    authored = StageConfig(
        "gpu", "GPU", 100, modules=StageModules(gpu_3d=ModuleGpu3D(enabled=True, compute_variant="stress_hash")),
        analysis=StageAnalysis("sustained", 40),
        gpu_evaluation=StageGpuEvaluation(gpu_busy=GpuMetricEvaluationRequirement(80, 20)),
    )
    plan = planned_gpu_evaluation(authored, settings, 40)
    assert plan["requirements"]["gpu_busy"]["minimum_percent"] == 80
    authored.gpu_evaluation = None
    assert planned_gpu_evaluation(authored, settings, 40)["requirements"]["gpu_busy"]["source"] == "global_settings"

    # 14/15: invalid percentages and impossible sustain windows fail validation.
    authored.gpu_evaluation = StageGpuEvaluation(gpu_busy=GpuMetricEvaluationRequirement(101, 20))
    profile = ValidationProfile("bad", defaults=ProfileDefaults(1, 10, 10), stages=[authored])
    validation = ProfileValidator().validate(profile, ["GPU"])
    assert any("from 0 through 100" in item for item in validation["errors"])
    authored.gpu_evaluation = StageGpuEvaluation(gpu_busy=GpuMetricEvaluationRequirement(80, 81))
    validation = ProfileValidator().validate(profile, ["GPU"])
    assert any("exceeds the planned usable analysis window" in item for item in validation["errors"])

    # 16: suppressed checks cannot become a strict-mode warning result.
    suppressed = _evaluate(_window("sustained", quality="insufficient", requirement=_requirement(required=False)), dense)
    assert suppressed["evaluations"][0]["status"] == "insufficient_evidence"
    suppressed_window = _window("sustained", quality="insufficient", requirement=_requirement(required=False))
    suppressed_window.gpu_evaluation_evidence = suppressed
    recommendations = StageStabilityInterpreter(
        window_has_operator_stop=lambda _window: False,
        worker_integrity_error_count=lambda _results: 0,
        gpu_load_quality_counts=lambda _entries: {},
    )._stage_threshold_recommendations(
        "gpu_saturation", [], {}, [], strict_threshold_enabled=True,
        analysis_evidence=suppressed_window.analysis_evidence, window=suppressed_window,
    )
    assert recommendations["WouldWarnCount"] == 0 and recommendations["StrictModeEnabled"] is True

    # 17: GPUs are evaluated independently.
    multi_window = _window("sustained", requirement=_requirement(seconds=5))
    multi_window.gpu_workers_final.append({
        "telemetry_gpu_index": 2, "target_id": "pci:0001:02:00.0", "workload": "gpu_3d",
        "backend": "python_vulkan_compute", "compute_variant": "stress_hash",
    })
    multi_window.worker_results.append({
        "kind": "gpu", "telemetry_gpu_index": 2, "status": "ok", "error_count": 0,
        "suite_verification": "readback", "verification_passes": 0, "compute_variant": "stress_hash",
    })
    mixed_samples = [
        Sample(float(t), {"gpu_1_busy_percent": 90.0, "gpu_2_busy_percent": 20.0})
        for t in range(10, 71)
    ]
    multi = _evaluate(multi_window, mixed_samples, _targets(second=True))
    statuses = {(item["gpu_index"], item["metric"]): item["status"] for item in multi["evaluations"]}
    assert statuses[(1, "gpu_busy")] == "met" and statuses[(2, "gpu_busy")] == "insufficient_evidence"

    # 18: shared-memory device class does not change the busy policy or invent framebuffer requirements.
    shared = _evaluate(_window("sustained", requirement=_requirement()), dense)
    assert shared["evaluations"][0]["physical_gpu_id"] == "pci:000f:01:00.0"
    assert all(item["metric"] != "allocation" for item in shared["evaluations"])

    # 19: memory allocation/readback has no implicit memory-busy requirement.
    no_requirement = _window("functional")
    assert _evaluate(no_requirement, dense)["evaluations"][1]["status"] == "not_applicable"

    # 20: explicit memory-busy is distinct and uses its own metric.
    memory_window = _window("threshold", requirement=_requirement("memory_busy", 25, 2))
    memory = _evaluate(memory_window, _samples([(10, 30), (11, 30), (12, 30)], metric="memory_busy_percent"))
    memory_entry = next(item for item in memory["evaluations"] if item["metric"] == "memory_busy")
    assert memory_entry["status"] == "met" and memory_entry["metric_semantics"] == "memory_controller_busy_percent"

    # 21: missing mandatory telemetry is unverifiable, not a measured miss.
    missing_required = _evaluate(_window("sustained", requirement=_requirement()), [])
    assert missing_required["evaluations"][0]["status"] == "insufficient_evidence"
    telemetry = SimpleNamespace(
        samples=[], interval_seconds=1.0,
        source_map=lambda: {"fields": {"gpu_1_busy_percent": {"available": False, "provider": "nvidia"}}},
    )
    events = stage_target_gpu_utilization_events(
        SimpleNamespace(settings=SimpleNamespace(
            target_gpu_busy_min_percent=0.0, target_gpu_busy_sustain_seconds=0.0,
            target_gpu_memory_busy_min_percent=0.0, target_gpu_memory_busy_sustain_seconds=0.0,
        )),
        _window("sustained", requirement=_requirement()), telemetry,
    )
    assert len(events) == 1 and events[0]["category"] == "gpu_performance_evidence_insufficient"

    # 22: worker verification is an independent eligibility input.
    bad_worker = _window("sustained", requirement=_requirement())
    bad_worker.worker_results[0]["verification_passes"] = 0
    assert _evaluate(bad_worker, dense)["evaluations"][0]["status"] == "insufficient_evidence"

    # 23: a transfer backend is inapplicable even with high observed busy.
    transfer = _window("sustained", requirement=_requirement())
    transfer.gpu_workers_final[0]["backend"] = "python_vulkan_transfer"
    transfer.worker_results[0]["compute_variant"] = "baseline"
    targets = _targets()
    targets[1]["backends"] = ["python_vulkan_transfer"]
    assert _evaluate(transfer, dense, targets)["evaluations"][0]["status"] == "not_applicable"

    # 24: stateful memory correctness is not GPU-busy saturation.
    stateful = _window("sustained", requirement=_requirement())
    stateful.worker_results[0]["compute_variant"] = "stateful_memory"
    stateful.gpu_workers_final[0]["compute_variant"] = "stateful_memory"
    assert _evaluate(stateful, dense)["evaluations"][0]["status"] == "not_applicable"

    # 25: the optional profile schema round-trips without affecting legacy profiles.
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        loader = ProfileLoader(root)
        authored.gpu_evaluation = StageGpuEvaluation(gpu_busy=GpuMetricEvaluationRequirement(80, 20, False))
        saved = root / "gpu.json"
        loader.save_profile(saved, ValidationProfile("gpu", stages=[authored]))
        loaded = loader.load_profile(saved)
        assert loaded.stages[0].gpu_evaluation.gpu_busy.required is False
        editor = ProfileEditor()
        editor.set_stage_gpu_evaluation_requirement(loaded.stages[0], "memory_busy", 25, 10)
        assert any("Memory-controller busy" in line for line in profile_stage_summary_lines(loaded.stages[0], "GPU", 1))
        editor.clear_stage_gpu_evaluation_requirement(loaded.stages[0], "memory_busy")
        assert loaded.stages[0].gpu_evaluation.memory_busy is None
        invalid_required = json.loads(saved.read_text(encoding="utf-8"))
        invalid_required["stages"][0]["gpu_evaluation"]["gpu_busy"]["required"] = "yes"
        invalid_path = root / "invalid-required.json"
        invalid_path.write_text(json.dumps(invalid_required), encoding="utf-8")
        try:
            loader.load_profile(invalid_path)
        except ValueError as exc:
            assert "required must be true or false" in str(exc)
        else:
            raise AssertionError("non-boolean GPU requirement policy must fail loading")
        legacy_path = root / "legacy.json"
        legacy_path.write_text(json.dumps({
            "profile_name": "legacy", "stages": [{
                "id": "gpu", "name": "GPU", "duration_seconds": 90,
                "modules": {"gpu_3d": {"enabled": True}},
                "normalization": {"trim_start_seconds": 10, "trim_end_seconds": 10},
            }],
        }), encoding="utf-8")
        assert loader.load_profile(legacy_path).stages[0].gpu_evaluation is None

    # 26: direct allocation thresholds remain outside this telemetry policy.
    assert "allocation" not in normalized_gpu_evaluation_requirements(_requirement())

    # 27: immediate thermal safety fields are neither consumed nor rewritten here.
    thermal_sample = Sample(20.0, {"gpu_1_temp_c": 110.0, "gpu_1_busy_percent": 90.0})
    thermal = _evaluate(_window("sustained", requirement=_requirement(seconds=0.1)), [thermal_sample])
    assert thermal_sample.values["gpu_1_temp_c"] == 110.0

    # 28: descriptive load quality never assesses legacy or functional stages.
    builder = GpuMetricSectionBuilder(
        metric_stats=lambda _s, _k: {"Min": 90.0, "Avg": 90.0, "Max": 90.0},
        metric_sustain_summary=lambda *_a, **_k: {"SampleCount": 3, "Thresholds": []},
        gpu_display_name=lambda index, _names: f"gpu{index}",
        duplicate_safe_gpu_name=lambda name, _index, _order: name,
        should_blank_gpu_power_stats=lambda *_a: False,
    )
    assert builder._gpu_load_quality({"Max": 90.0}, {"SampleCount": 3}, {"intent": "legacy_unspecified"}) == "not_assessed_legacy"
    assert builder._gpu_load_quality({"Max": 90.0}, {"SampleCount": 3}, {"intent": "functional"}) == "not_assessed_functional"


if __name__ == "__main__":
    run_gpu_evaluation_policy_checks()
    print("gpu evaluation policy checks: PASS")
