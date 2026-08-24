#!/usr/bin/env python3
"""Focused native profile-label and legacy bucket regression checks."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from Modules.lvs_profile_editor import ProfileEditor
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_metadata import derive_legacy_bucket_category
from Modules.lvs_profile_models import (
    ModuleCpu,
    ModuleGpu3D,
    ModuleMemory,
    ModuleStorageBenchmark,
    ModuleVram,
    StageConfig,
    StageModules,
    ValidationProfile,
)
from Modules.lvs_run_models import StageWindow
from Modules.lvs_stage_completion import build_stage_check_window


def _stage(
    *,
    cpu: ModuleCpu | None = None,
    memory: bool = False,
    gpu: bool = False,
    vram: bool = False,
    storage: bool = False,
    label: str = "Stage",
) -> StageConfig:
    return StageConfig(
        id="segment_1",
        name="Combined",
        duration_seconds=None if storage else 60,
        display_label=label,
        modules=StageModules(
            cpu=cpu or ModuleCpu(),
            memory=ModuleMemory(enabled=memory),
            gpu_3d=ModuleGpu3D(enabled=gpu),
            vram=ModuleVram(enabled=vram),
            storage_benchmark=ModuleStorageBenchmark(enabled=storage),
        ),
    )


def _write_profile(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_profile_metadata_checks() -> None:
    editor = ProfileEditor()

    # Structured precedence and compatibility semantics.
    power = _stage(cpu=ModuleCpu(enabled=True, power_auto=True), gpu=True)
    assert derive_legacy_bucket_category(power) == "Power"
    legacy_power = _stage(cpu=ModuleCpu(enabled=True, mode="extreme", load="steady"), gpu=True)
    assert derive_legacy_bucket_category(legacy_power) == "Power"
    assert derive_legacy_bucket_category(_stage(cpu=ModuleCpu(enabled=True, instruction_intent="baseline_vector"), memory=True)) == "SSE"
    assert derive_legacy_bucket_category(_stage(cpu=ModuleCpu(enabled=True, instruction_intent="high_throughput_vector"), memory=True)) == "AVX"
    assert derive_legacy_bucket_category(_stage(cpu=ModuleCpu(enabled=True, instruction_intent="highest_verified_vector"), memory=True)) == "AVX"
    assert derive_legacy_bucket_category(_stage(cpu=ModuleCpu(enabled=True, instruction_set="sse"))) == "SSE"
    for instruction_set in ("avx", "avx2", "avx512"):
        assert derive_legacy_bucket_category(_stage(cpu=ModuleCpu(enabled=True, instruction_set=instruction_set))) == "AVX"
    assert derive_legacy_bucket_category(_stage(gpu=True, vram=True)) == "3D"
    assert derive_legacy_bucket_category(_stage(vram=True)) == "3D"
    assert derive_legacy_bucket_category(_stage(storage=True)) is None
    assert derive_legacy_bucket_category(_stage(cpu=ModuleCpu(enabled=True), gpu=True)) is None
    assert derive_legacy_bucket_category(_stage(cpu=ModuleCpu(enabled=True, instruction_set="neon"))) is None
    conflicting = _stage(cpu=ModuleCpu(enabled=True, instruction_set="sse"), memory=True)
    conflicting.modules.memory.instruction_set = "avx2"
    assert derive_legacy_bucket_category(conflicting) is None
    # Compatibility naming does not mutate architecture-neutral execution intent.
    arm_baseline = _stage(cpu=ModuleCpu(enabled=True, instruction_intent="baseline_vector"))
    assert derive_legacy_bucket_category(arm_baseline) == "SSE"
    assert arm_baseline.modules.cpu.instruction_set == "auto"
    assert arm_baseline.modules.cpu.instruction_intent == "baseline_vector"

    # The frontend adapter writes through to the canonical stage field.
    profile = ValidationProfile(profile_name="Edit", stages=[_stage(label="Original")])
    labels = editor.set_stage_label(profile, ["Original"], 0, "Edited label")
    assert labels == ["Edited label"]
    assert profile.stages[0].display_label == "Edited label"

    # Native and legacy profile contracts, including non-destructive migration.
    with TemporaryDirectory(dir="/tmp") as temporary:
        root = Path(temporary)
        loader = ProfileLoader(root)
        native_path = root / "Native.json"
        _write_profile(native_path, {
            "profile_name": "Native",
            "stages": [{
                "id": "segment_1",
                "name": "CPU",
                "display_label": "Baseline SIMD (CPU)",
                "duration_seconds": 60,
                "modules": {"cpu": {"enabled": True, "instruction_intent": "baseline_vector"}},
            }],
        })
        native = loader.load_profile(native_path)
        assert loader.load_segment_labels(native_path, native) == ["Baseline SIMD (CPU)"]
        assert native.segment_label_source is None

        legacy_path = root / "Legacy.json"
        sidecar_path = root / "Legacy_info.txt"
        _write_profile(legacy_path, {
            "profile_name": "Legacy",
            "segment_label_source": "Legacy_info.txt",
            "stages": [
                {"id": "segment_1", "name": "CPU", "duration_seconds": 60, "modules": {"cpu": {"enabled": True}}},
                {"id": "segment_2", "name": "VRAM", "duration_seconds": 60, "modules": {"vram": {"enabled": True}}},
            ],
        })
        sidecar_path.write_text("Legacy CPU\nLegacy VRAM\n", encoding="utf-8")
        legacy = loader.load_profile(legacy_path)
        assert [stage.display_label for stage in legacy.stages] == ["Legacy CPU", "Legacy VRAM"]
        loader.save_profile(legacy_path, legacy, loader.load_segment_labels(legacy_path, legacy))
        saved = json.loads(legacy_path.read_text(encoding="utf-8"))
        assert "segment_label_source" not in saved
        assert [stage["display_label"] for stage in saved["stages"]] == ["Legacy CPU", "Legacy VRAM"]
        assert sidecar_path.read_text(encoding="utf-8") == "Legacy CPU\nLegacy VRAM\n"

        mismatch_path = root / "Mismatch.json"
        _write_profile(mismatch_path, {
            "profile_name": "Mismatch",
            "segment_label_source": "Mismatch_info.txt",
            "stages": [
                {"id": "segment_1", "name": "CPU", "duration_seconds": 60, "modules": {"cpu": {"enabled": True}}},
                {"id": "segment_2", "name": "VRAM", "duration_seconds": 60, "modules": {"vram": {"enabled": True}}},
            ],
        })
        (root / "Mismatch_info.txt").write_text("Only one\n", encoding="utf-8")
        mismatch = loader.load_profile(mismatch_path)
        assert [stage.display_label for stage in mismatch.stages] == ["CPU", "VRAM"]
        assert "label count mismatch" in loader.inspect_segment_label_source(mismatch_path, mismatch)["issues"][0]

    # Every active bundled profile is native and every stage has a derivable or
    # explicitly unavailable category. Archived compatibility material is out of scope.
    profiles_dir = Path(__file__).resolve().parents[1] / "profiles"
    active_paths = sorted(profiles_dir.glob("*.json"))
    assert active_paths
    assert not list(profiles_dir.glob("*_info.txt"))
    active_loader = ProfileLoader(profiles_dir)
    for path in active_paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "segment_label_source" not in raw
        loaded = active_loader.load_profile(path)
        assert len(loaded.stages) == len(raw["stages"])
        for stage, stage_raw in zip(loaded.stages, raw["stages"]):
            assert stage_raw.get("display_label")
            category = derive_legacy_bucket_category(stage)
            assert category in {None, "Power", "SSE", "AVX", "3D"}
            if stage.modules.storage_benchmark.enabled:
                assert stage.display_label == "Storage Benchmark"
                assert category is None

    # The executed-stage native result surface freezes both fields while
    # retaining the existing display_name compatibility member.
    result_stage = _stage(
        cpu=ModuleCpu(enabled=True, instruction_intent="baseline_vector"),
        memory=True,
        label="Baseline SIMD (CPU + RAM)",
    )
    window = build_stage_check_window(
        stage_window_cls=StageWindow,
        stage=result_stage,
        display_name=result_stage.display_label,
        started_iso="2026-08-24T00:00:00-04:00",
        ended_iso="2026-08-24T00:01:00-04:00",
        started_monotonic=1.0,
        ended_monotonic=61.0,
        duration_seconds=60.0,
    )
    serialized = asdict(window)
    assert serialized["display_name"] == "Baseline SIMD (CPU + RAM)"
    assert serialized["display_label"] == "Baseline SIMD (CPU + RAM)"
    assert serialized["legacy_bucket_category"] == "SSE"
    assert serialized["legacy_bucket_category_source"] == "lvs_derived"
