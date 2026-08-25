#!/usr/bin/env python3
"""Focused, workload-free checks for guided profile authoring and copying."""

from __future__ import annotations

import json
import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory

from Modules.lvs_profile_editor import ProfileEditor, format_profile_duration, parse_profile_duration
from Modules.lvs_profile_cli_editor import ProfileCliEditor
from Modules.lvs_profile_creation import ProfileCreationController
from Modules.lvs_profile_edit_view import profile_copy_selection_rows
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_models import ValidationProfile
from Modules.lvs_service_models import ProfileEditState
from Modules.lvs_service_profiles import SuiteProfileServiceMixin


def run_profile_authoring_ux_checks() -> None:
    editor = ProfileEditor()

    assert parse_profile_duration("90") == 90
    assert parse_profile_duration("90s") == 90
    assert parse_profile_duration("5m") == 300
    assert parse_profile_duration("1h 30m") == 5400
    assert format_profile_duration(90) == "1 minute 30 seconds"
    assert format_profile_duration(3600) == "1 hour"
    assert format_profile_duration(None) == "Completion-based"

    profile = ValidationProfile(profile_name="Authoring")
    expectations = {
        "power_auto": ("Power (CPU + GPU)", "extreme", "extreme", ""),
        "baseline_ram": ("Baseline SIMD (CPU + RAM)", "normal", "", "baseline_vector"),
        "baseline_vram": ("Baseline SIMD (CPU + VRAM)", "normal", "", "baseline_vector"),
        "baseline_ram_vram": ("Baseline SIMD (CPU + RAM/VRAM)", "normal", "", "baseline_vector"),
        "high_throughput_ram": ("High-Throughput SIMD (CPU + RAM)", "normal", "", "high_throughput_vector"),
        "gpu_3d": ("GPU (3D)", "", "extreme", ""),
        "gpu_vram": ("GPU (3D + VRAM)", "", "extreme", ""),
    }
    for key, (label, cpu_mode, gpu_intensity, intent) in expectations.items():
        stage, actual_label = editor.template_stage(profile, key)
        assert actual_label == label
        if cpu_mode:
            assert stage.modules.cpu.mode == cpu_mode
        if gpu_intensity:
            assert stage.modules.gpu_3d.intensity == gpu_intensity
        if intent:
            assert stage.modules.cpu.instruction_intent == intent
            assert stage.modules.cpu.instruction_set == "auto"
    memory, _ = editor.template_stage(profile, "memory")
    vram, _ = editor.template_stage(profile, "vram")
    assert memory.modules.memory.allocation_percent == 90
    assert vram.modules.vram.allocation_percent == 90
    storage, _ = editor.template_stage(profile, "storage_benchmark")
    assert storage.duration_seconds is None

    allocation_templates = {
        "memory": ["memory"],
        "cpu_ram": ["memory"],
        "baseline_ram": ["memory"],
        "baseline_vram": ["vram"],
        "baseline_ram_vram": ["memory", "vram"],
        "gpu_vram": ["vram"],
        "vram": ["vram"],
    }
    for key, fields in allocation_templates.items():
        stage, _label = editor.template_stage(profile, key)
        assert editor.guided_allocation_fields(stage) == fields
        for field in fields:
            assert editor.guided_allocation_percent(stage, field) == 90
            assert editor.apply_guided_allocation_percent(stage, field, "") == 90
            assert editor.apply_guided_allocation_percent(stage, field, "83") == 83
            assert editor.apply_guided_allocation_percent(stage, field, "invalid") == 83
            assert editor.apply_guided_allocation_percent(stage, field, "999") == 95

    # Exact/manual ISA and highest-verified intent remain available from the
    # same catalog used by both frontend presenters.
    assert {"sse", "avx", "avx2", "avx512", "neon"}.issubset(editor.CPU_INSTRUCTION_OPTIONS)
    assert "highest_verified_vector" in editor.CPU_INSTRUCTION_INTENT_OPTIONS
    assert editor.stage_template("cpu_3d")["key"] == "cpu_3d"
    assert editor.stage_template("cpu_vram")["key"] == "cpu_vram"

    labels = []
    for key in ("power_auto", "baseline_ram", "gpu_vram"):
        stage, label = editor.template_stage(profile, key)
        _, labels = editor.add_stage(profile, labels, stage, label)
    profile.stages[1].enabled = False
    profile.stages[2].id = "segment_9"

    copied = editor.copy_profile(profile, "Copy", [0, 2])
    assert [stage.id for stage in copied.stages] == ["segment_1", "segment_2"]
    assert [stage.display_label for stage in copied.stages] == [labels[0], labels[2]]
    assert copied.segment_label_source is None
    assert copied.defaults is not profile.defaults
    assert copied.menu_group == profile.menu_group
    assert copied.menu_description == profile.menu_description
    assert copied.require_all_stages_runnable == profile.require_all_stages_runnable
    assert copied.stages[0] is not profile.stages[0]
    assert copied.stages[0].modules is not profile.stages[0].modules
    assert profile_copy_selection_rows(profile, labels, [0, 2])[:3] == [
        "[x] 1. Power (CPU + GPU) — 5 minutes",
        "[ ] 2. Baseline SIMD (CPU + RAM) — 5 minutes",
        "[x] 3. GPU (3D + VRAM) — 5 minutes",
    ]
    copied.stages[0].modules.cpu.mode = "normal"
    assert profile.stages[0].modules.cpu.mode == "extreme"
    try:
        editor.copy_profile(profile, "Empty", [])
        raise AssertionError("zero-stage copy must be rejected")
    except ValueError:
        pass

    duplicate, labels = editor.duplicate_stage(profile, labels, 0)
    assert duplicate is not profile.stages[0]
    assert duplicate.modules is not profile.stages[0].modules
    assert profile.stages[1] is duplicate
    source_label = profile.stages[0].display_label
    labels = editor.set_stage_label(profile, labels, 1, "Changed duplicate")
    assert profile.stages[0].display_label == source_label
    destination, labels = editor.move_stage(profile, labels, 1, 1)
    assert destination == 2
    assert profile.stages[2].display_label == "Changed duplicate"
    assert editor.move_stage(profile, labels, 0, -1)[0] == 0

    # Exercise the shared Copy/Save-As facade without constructing a second
    # copy engine. Save As sees current unsaved edits.
    class Service(SuiteProfileServiceMixin):
        pass

    with TemporaryDirectory(dir="/tmp") as temporary:
        service = Service()
        service.profile_editor = editor
        service.settings = type("Settings", (), {"profiles_dir": temporary})()
        service.profile_loader = ProfileLoader(Path(temporary))
        guided, _ = editor.template_stage(profile, "baseline_ram_vram")
        assert service.profile_stage_guided_allocation_fields(guided) == ["memory", "vram"]
        assert service.apply_profile_stage_guided_allocation(guided, "memory", "82") == 82
        assert service.apply_profile_stage_guided_allocation(guided, "vram", "76") == 76
        edit = ProfileEditState(Path(temporary) / "Source.json", profile, labels, dirty=True)
        edit.profile.stages[0].display_label = "Unsaved label"
        selection = service.create_profile_copy_selection(edit, mode="save_as")
        service.set_all_profile_copy_stages(selection, False)
        service.toggle_profile_copy_stage(selection, 0)
        saved_as = service.finish_profile_copy_selection(selection, "Destination")
        assert saved_as.profile.stages[0].display_label == "Unsaved label"
        assert saved_as.profile.stages[0] is not edit.profile.stages[0]
        assert not saved_as.profile_path.exists()
        assert saved_as.is_new
        assert not list(Path(temporary).glob("*_info.txt"))

        # A legacy sidecar-backed source is loaded once, then copied into the
        # native JSON-only model. The source sidecar is not deleted.
        legacy_path = Path(temporary) / "Legacy.json"
        sidecar = Path(temporary) / "Legacy_info.txt"
        legacy_path.write_text(json.dumps({
            "profile_name": "Legacy",
            "segment_label_source": sidecar.name,
            "stages": [{
                "id": "segment_4",
                "name": "CPU",
                "duration_seconds": 60,
                "modules": {"cpu": {"enabled": True}},
            }],
        }), encoding="utf-8")
        sidecar.write_text("Recovered legacy label\n", encoding="utf-8")
        legacy = service.profile_loader.load_profile(legacy_path)
        legacy_labels = service.profile_loader.load_segment_labels(legacy_path, legacy)
        assert legacy_labels == ["Recovered legacy label"]
        native_copy = editor.copy_profile(legacy, "Native Copy", [0])
        assert native_copy.segment_label_source is None
        assert native_copy.stages[0].display_label == "Recovered legacy label"
        assert sidecar.exists()

        native_path = Path(temporary) / "Guided Allocations.json"
        native = ValidationProfile(profile_name="Guided Allocations", stages=[guided])
        service.profile_loader.save_profile(native_path, native, ["Baseline SIMD (CPU + RAM/VRAM)"])
        reloaded = service.profile_loader.load_profile(native_path)
        assert reloaded.stages[0].modules.memory.allocation_percent == 82
        assert reloaded.stages[0].modules.vram.allocation_percent == 76

    # The real CLI guided flow asks only the allocation fields enabled by the
    # shared draft and shows the resulting values in Stage Review.
    class GuidedCliHost:
        def __init__(self, responses):
            self.profile_editor = editor
            self.profile_creation = ProfileCreationController(editor)
            self.prompts = []
            self.responses = iter(responses)

        def _input(self, prompt=""):
            self.prompts.append(prompt)
            return next(self.responses)

    cli_cases = [
        ("memory", "2", ["RAM allocation percent [90]: "]),
        ("cpu_ram", "3", ["RAM allocation percent [90]: "]),
        ("baseline_ram", "5", ["RAM allocation percent [90]: "]),
        ("baseline_vram", "6", ["VRAM allocation percent [90]: "]),
        ("baseline_ram_vram", "7", ["RAM allocation percent [90]: ", "VRAM allocation percent [90]: "]),
        ("gpu_vram", "10", ["VRAM allocation percent [90]: "]),
        ("vram", "11", ["VRAM allocation percent [90]: "]),
    ]
    for key, menu_choice, expected_prompts in cli_cases:
        stage_profile = ValidationProfile(profile_name=f"CLI {key}")
        allocation_values = ["" for _ in expected_prompts]
        host = GuidedCliHost(["", menu_choice, "5m", *allocation_values, "", "y"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            labels = ProfileCliEditor(host).add_profile_stage(stage_profile, [])
        assert labels
        assert [prompt for prompt in host.prompts if "allocation percent" in prompt] == expected_prompts
        assert "90%" in output.getvalue()
        assert editor.guided_allocation_fields(stage_profile.stages[0]) == allocation_templates[key]

    custom_profile = ValidationProfile(profile_name="CLI custom allocation")
    custom_host = GuidedCliHost(["", "7", "5m", "81", "74", "", "y"])
    custom_output = io.StringIO()
    with contextlib.redirect_stdout(custom_output):
        ProfileCliEditor(custom_host).add_profile_stage(custom_profile, [])
    assert custom_profile.stages[0].modules.memory.allocation_percent == 81
    assert custom_profile.stages[0].modules.vram.allocation_percent == 74
    assert "RAM: 81%" in custom_output.getvalue()
    assert "VRAM: 74%" in custom_output.getvalue()

    invalid_profile = ValidationProfile(profile_name="CLI invalid allocation")
    invalid_host = GuidedCliHost(["", "5", "5m", "not-a-number", "", "y"])
    invalid_output = io.StringIO()
    with contextlib.redirect_stdout(invalid_output):
        ProfileCliEditor(invalid_host).add_profile_stage(invalid_profile, [])
    assert invalid_profile.stages[0].modules.memory.allocation_percent == 90
    assert "Invalid allocation percent, keeping current." in invalid_output.getvalue()

    # Blank creation is valid only as an in-memory authoring state. The CLI
    # must not offer its generic validation override for an empty draft.
    class BlankPreparation:
        errors = ["profile must contain at least one stage"]
        warnings = []

    class BlankSave:
        saved = False

        def prepare(self, _profile, _labels):
            return BlankPreparation()

        def save(self, *_args, **_kwargs):
            self.saved = True

    responses = iter(["s", "q"])
    blank_host = type("BlankHost", (), {})()
    blank_host.profile_editor = editor
    blank_host.profile_save = BlankSave()
    blank_host._input = lambda _prompt="": next(responses)
    blank_host._profile_menu_group_label = lambda value: value
    blank_host._strict_threshold_override_text = lambda value: "inherit"
    blank = ValidationProfile(profile_name="Blank")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        ProfileCliEditor(blank_host).edit_profile_state(Path("profiles/Blank.json"), blank, [])
    assert not blank_host.profile_save.saved
    assert "Add at least one runnable stage before saving" in output.getvalue()
    assert "Save anyway?" not in output.getvalue()
