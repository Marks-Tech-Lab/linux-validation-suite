"""Captured profiles use the authored schema; legacy null reading is explicit."""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_models import (
    GpuMetricEvaluationRequirement, ModuleCpu, ModuleGpu3D, ProfileDefaults, StageAnalysis,
    StageConfig, StageGpuEvaluation, StageModules, StageNormalization,
    ValidationProfile,
)
from Modules.lvs_profile_report_artifacts import profile_used_payload, ProfileReportArtifactWriter
from Modules.lvs_run_bootstrap import build_effective_profile_for_run

ROOT = Path(__file__).resolve().parents[1]


def run_captured_profile_checks() -> None:
    loader = ProfileLoader(ROOT / "profiles")
    with TemporaryDirectory(prefix="lvs-captured-profile-") as temporary:
        root = Path(temporary)
        captured = root / "profile_used.json"
        count = 0
        # Includes the SVE functional/sustained and archived NEON profiles.
        for source in sorted((ROOT / "profiles").rglob("*.json")):
            profile = loader.load_profile(source)
            before = asdict(profile)
            payload = loader.profile_payload(profile)
            captured.write_text(json.dumps(payload), encoding="utf-8")
            assert asdict(loader.load_profile(captured)) == before, source
            assert asdict(profile) == before, source
            count += 1

        profile = ValidationProfile(
            profile_name="Effective capture", menu_group="advanced",
            menu_description="Metadata survives", require_all_stages_runnable=True,
            segment_label_source="legacy_labels.txt",
            defaults=ProfileDefaults(telemetry_interval_seconds=3, trim_start_seconds=11, trim_end_seconds=12),
            stages=[
                StageConfig(id="cpu", name="CPU", display_label="Authored CPU", duration_seconds=120,
                            modules=StageModules(cpu=ModuleCpu(enabled=True, backend_preference="native",
                                                               instruction_set="sve_fp32_fma"))),
                StageConfig(id="gpu", name="GPU", display_label="Authored GPU", duration_seconds=600,
                            modules=StageModules(gpu_3d=ModuleGpu3D(enabled=True)),
                            normalization=StageNormalization(trim_start_seconds=60, trim_end_seconds=60),
                            analysis=StageAnalysis(intent="sustained", minimum_usable_seconds=480),
                            gpu_evaluation=StageGpuEvaluation(gpu_busy=GpuMetricEvaluationRequirement(90, 10))),
                StageConfig(id="combined", name="CPU + GPU", display_label="Authored combined", duration_seconds=120, enabled=False,
                            modules=StageModules(cpu=ModuleCpu(enabled=True), gpu_3d=ModuleGpu3D(enabled=True))),
            ])
        labels = ["Runtime CPU", "Runtime GPU", "Disabled combined"]
        effective, skipped, enabled_labels = build_effective_profile_for_run(
            profile, labels, [{"runnable": True}, {"runnable": False, "issues": ["missing backend"]}, {}])
        assert [s.enabled for s in effective.stages] == [True, False, False]
        assert skipped[0]["stage_id"] == "gpu" and enabled_labels == ["Runtime CPU"]
        before = asdict(effective)
        payload = loader.profile_payload(effective, labels)
        assert asdict(effective) == before  # serialization must not mutate the run
        assert [s["display_label"] for s in payload["stages"]] == labels
        assert [s["enabled"] for s in payload["stages"]] == [True, False, False]
        assert "analysis" not in payload["stages"][0] and "gpu_evaluation" not in payload["stages"][0]
        assert payload["stages"][1]["analysis"] == {"intent": "sustained", "minimum_usable_seconds": 480}
        assert payload["stages"][1]["gpu_evaluation"] == {
            "gpu_busy": {"minimum_percent": 90, "minimum_sustain_seconds": 10, "required": True}}
        captured.write_text(json.dumps(payload), encoding="utf-8")
        restored = loader.load_profile(captured)
        expected = copy.deepcopy(effective)
        for stage, label in zip(expected.stages, labels):
            stage.display_label = label
        assert asdict(restored) == asdict(expected)
        # Diagnostics preserve requirements, metadata, all stages and labels too.
        diagnostics = profile_used_payload(effective, labels)
        assert diagnostics == dict(payload, segment_labels=labels)
        ProfileReportArtifactWriter(loader, None).write_profile_used(root, effective, labels)
        assert json.loads(captured.read_text()) == diagnostics
        assert asdict(loader.load_profile(captured)) == asdict(expected)
        for analysis in (None, StageAnalysis(intent="functional")):
            for evaluation in (None, StageGpuEvaluation(memory_busy=GpuMetricEvaluationRequirement(50, 5, False))):
                variant = copy.deepcopy(expected)
                variant.stages[0].analysis = analysis
                variant.stages[0].gpu_evaluation = evaluation
                captured.write_text(json.dumps(loader.profile_payload(variant)), encoding="utf-8")
                assert asdict(loader.load_profile(captured)) == asdict(variant)

        # Historical dataclass dumps (including SVE/NEON layouts) are immutable
        # evidence. Only the explicit captured-profile reader accepts null absence.
        historical = [effective]
        for filename in ("profiles/ARM64 SVE FP32 FMA Functional Confirmation.json",
                         "profiles/ARM64 SVE FP32 FMA Sustained Effectiveness.json",
                         "profiles/Archived/2026 Hardware Validation/07 ARM64 NEON FP32 FMA Acceptance/ARM64 NEON FP32 FMA Sustained Effectiveness.json"):
            historical.append(loader.load_profile(ROOT / filename))
        for profile in historical:
            legacy = asdict(profile)
            captured.write_text(json.dumps(legacy), encoding="utf-8")
            digest = hashlib.sha256(captured.read_bytes()).hexdigest()
            try:
                loader.load_profile(captured)
            except ValueError:
                pass
            else:
                raise AssertionError("strict loader accepted a null optional object")
            assert asdict(loader.load_captured_profile(captured)) == asdict(profile)
            assert hashlib.sha256(captured.read_bytes()).hexdigest() == digest

        # Neither route repairs malformed objects, strings, booleans or numbers.
        rejected = 0
        for field in ("analysis", "gpu_evaluation"):
            for bad in (None, [], "", False, 0, {"unknown": 1}):
                broken = copy.deepcopy(payload)
                broken["stages"][0][field] = bad
                captured.write_text(json.dumps(broken), encoding="utf-8")
                for reader in (loader.load_profile, loader.load_captured_profile):
                    if bad is None and reader == loader.load_captured_profile:
                        reader(captured)
                        continue
                    try:
                        reader(captured)
                    except (TypeError, ValueError):
                        rejected += 1
                    else:
                        raise AssertionError((reader.__name__, field, bad))
        assert rejected == 22
        print(f"PASS captured profiles: {count} normal round trips, effective/diagnostic captures, "
              f"{len(historical)} immutable legacy fixtures, {rejected} malformed-input rejections")
