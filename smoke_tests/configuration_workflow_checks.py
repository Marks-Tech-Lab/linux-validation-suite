"""Normal TUI/service persistence and run-only configuration regressions.

No native helper, hardware discovery, or workload is launched.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json

from Modules.lvs_profile_editor import ProfileEditor
from Modules.lvs_profile_edit_controller import ProfileEditController
from Modules.lvs_profile_edit_view import ProfileEditPresenter
from Modules.lvs_profile_loader import ProfileLoader
from Modules.lvs_profile_save import ProfileSaveController
from Modules.lvs_profile_validation import ProfileValidator
from Modules.lvs_service_profiles import SuiteProfileServiceMixin
from Modules.lvs_service_run import SuiteRunServiceMixin
from Modules.lvs_service_models import ProfileListEntry
from Modules.lvs_run_setup import RunSetupManager
from Modules.lvs_settings import GlobalSettings

ROOT = Path(__file__).resolve().parents[1]


class Service(SuiteProfileServiceMixin, SuiteRunServiceMixin):
    def __init__(self, root):
        self.settings = GlobalSettings(profiles_dir=str(root / "profiles"), settings_dir=str(root / "settings"))
        self.profile_loader = ProfileLoader(Path(self.settings.profiles_dir))
        self.profile_editor = ProfileEditor()
        self.profile_edit_controller = ProfileEditController(self.profile_editor)
        self.validator = ProfileValidator()
        self.profile_save = ProfileSaveController(self.profile_editor, self.profile_loader, self.validator)
        self.profile_edit_presenter = ProfileEditPresenter(self.profile_editor, self.profile_loader.menu_group_label)
        self.run_setup_manager = RunSetupManager(lambda: self.settings, self.profile_loader, self.environment_mode_label)

    def reload(self):
        pass  # No settings persistence or hardware service is needed in this fixture.

    def environment_mode_label(self):
        return "End User"

    def enhanced_telemetry_label(self):
        return "fixture; no hardware collection"

    def stop_enhanced_telemetry_keepalive(self):
        pass

    def profile_summary_text(self, path):
        edit = self.create_profile_edit(path)
        return self.profile_edit_summary_text(edit)

    def list_profiles(self):
        return [ProfileListEntry(path, self.profile_loader.load_profile(path).profile_name, "advanced", "Advanced")
                for path in self.profile_loader.list_profiles()]


def _source(service):
    original = ROOT / "profiles/ARM64 SVE FP32 FMA Functional Confirmation.json"
    profile = service.profile_loader.load_profile(original)
    path = Path(service.settings.profiles_dir) / "Source.json"
    service.profile_loader.save_profile(path, profile)
    return path


def run_profile_save_completion_checks():
    with TemporaryDirectory(dir=ROOT) as tmp:
        service = Service(Path(tmp)); source = _source(service); before = source.read_bytes()
        edit = service.create_profile_edit(source)
        service.apply_stage_configuration(edit, 0, "cpu_instruction_intent", "highest_verified_vector")
        selection = service.create_profile_copy_selection(edit, mode="save_as")
        saved = service.save_profile_copy_selection(selection, "Saved Copy")
        assert saved.profile_path.exists() and not saved.dirty and not saved.is_new
        assert saved.profile_path in service.profile_loader.list_profiles()
        assert service.profile_loader.load_profile(saved.profile_path).stages[0].modules.cpu.instruction_intent == "highest_verified_vector"
        assert source.read_bytes() == before
        existing = saved.profile_path.read_bytes()
        try: service.save_profile_copy_selection(selection, "Saved Copy")
        except ValueError: pass
        else: raise AssertionError("duplicate profile name was accepted")
        assert saved.profile_path.read_bytes() == existing
        # An exclusive destination collision after drafting must not overwrite.
        draft = service.finish_profile_copy_selection(selection, "Race")
        draft.profile_path.write_text("keep this file", encoding="utf-8")
        try: service.save_profile_edit(draft)
        except FileExistsError: pass
        else: raise AssertionError("new-profile collision overwrote an existing file")
        assert draft.profile_path.read_text() == "keep this file" and draft.dirty and draft.is_new
        for name in ("", "..", "../escape", "bad\\path", "bad\x00name"):
            try: service.save_profile_copy_selection(selection, name)
            except ValueError: pass
            else: raise AssertionError(f"invalid Save As name accepted: {name!r}")
        bad = deepcopy(selection)
        bad.source_edit.profile.stages[0].duration_seconds = 0
        try: service.save_profile_copy_selection(bad, "Invalid Profile")
        except ValueError: pass
        else: raise AssertionError("invalid profile was saved")
        assert not (source.parent / "Invalid Profile.json").exists()
        service.apply_stage_configuration(saved, 0, "cpu_threads", "2")
        assert saved.dirty
        service.save_profile_edit(saved)
        assert not saved.dirty and service.profile_loader.load_profile(saved.profile_path).stages[0].modules.cpu.threads == "2"
        assert source.read_bytes() == before


def run_stage_configuration_execution_checks():
    from Modules.lvs_run_executor import RunExecutor
    from Modules.lvs_run_bootstrap import bootstrap_run_artifacts
    from Modules.lvs_cpu_architecture import resolve_cpu_instruction_intent
    from Modules.lvs_cpu_execution import build_cpu_command
    with TemporaryDirectory(dir=ROOT) as tmp:
        root = Path(tmp); service = Service(root); source = _source(service); before = source.read_bytes()
        setup = service.create_run_setup(source)
        edit = service.run_setup_stage_edit(setup)
        for key, value in (("cpu_instruction_intent", "highest_verified_vector"), ("cpu_threads", "2")):
            service.apply_stage_configuration(edit, 0, key, value)
        setup.profile, setup.labels = edit.profile, edit.labels
        assert setup.profile.stages[0].modules.cpu.instruction_set == "auto"
        unchanged = deepcopy(setup.profile)
        for key, value in (("cpu_backend", "not-a-backend"), ("cpu_threads", "0"),
                           ("cpu_threads", "1.5"), ("memory_allocation", "80"),
                           ("cpu_backend", "python_fallback"), ("cpu_power_auto", "true")):
            try: service.apply_stage_configuration(edit, 0, key, value)
            except ValueError: pass
            else: raise AssertionError(f"invalid/incompatible edit accepted: {key}={value}")
            assert edit.profile == unchanged
        setup.metadata.advanced_debug_logging = True
        commands = []

        def run(path, profile, labels, metadata, **kwargs):
            assert profile is setup.profile and profile.stages[0].modules.cpu.instruction_intent == "highest_verified_vector"
            cpu = profile.stages[0].modules.cpu
            selection = resolve_cpu_instruction_intent("arm64", cpu.instruction_intent,
                                                       ["scalar", "neon", "neon_fp32_fma", "sve_fp32_fma"])
            commands.append(build_cpu_command(worker_count=2, helper_available=True, helper_path="fixture/helper",
                requested_mode="auto", instruction_set=cpu.instruction_set, mode=cpu.mode,
                stress_ng_available=False, python_runtime="fixture/python", target_cpu_ids=[2, 9],
                cpu_kernel_flavor=selection["resolved_kernel_flavor"]))
            with patch("Modules.lvs_run_bootstrap.AdvancedDebugLogger.capture_run_start"):
                result = bootstrap_run_artifacts(app_name="LVS", app_version="fixture", profile_path=path,
                    profile=profile, labels=labels, metadata=metadata,
                    preflight={"plan": [{"runnable": True, "cpu_selection_evidence": selection}], "validation": {}, "telemetry_capabilities": {}},
                    run_dir=root / "execution", started_iso="2026-10-22T00:00:00+00:00", runtime_environment={},
                    backends={}, backend_details={}, abort_on_fail_threshold=False, abort_on_worker_error=False,
                    abort_on_system_fault=False, abort_run_on_stage_abort=False, privileged_helper_enabled=False,
                    recovery_report={}, collect_system_info=lambda *args: {}, print_run_header=lambda *args: None,
                    print_stage_skip=lambda *args: None, print_run_start=lambda *args: None)
            return result.run_dir

        executor = RunExecutor(settings=service.settings, profile_loader=service.profile_loader,
            orchestrator=SimpleNamespace(run=run), default_run_metadata=service.default_run_metadata,
            ensure_enhanced_telemetry_ready=lambda: True, run_heatsoak_if_requested=lambda *a, **kw: True)
        result = executor.run_profile_capture_output(source, setup=setup, metadata=setup.metadata)
        captured = service.profile_loader.load_profile(result.run_dir / "profile_used.json")
        assert captured.stages[0].modules.cpu.instruction_intent == "highest_verified_vector"
        assert captured.stages[0].modules.cpu.threads == "2"
        assert "sve_fp32_fma" in commands[0] and "--cpu-ids" in commands[0]
        manifest = json.loads((result.run_dir / "run_manifest.json").read_text())
        assert manifest["advanced_debug_logging"] and manifest["source_provenance"]["source"]["status"] == "complete"
        assert source.read_bytes() == before
        fresh = service.create_run_setup(source)
        assert fresh.profile.stages[0].modules.cpu.instruction_set == "sve_fp32_fma"
        assert fresh.profile.stages[0].modules.cpu.instruction_intent == ""
        assert fresh.profile.stages[0].modules.cpu.threads == "all"
        assert "highest_verified_vector" in service.run_setup_summary_text(setup)
        assert "overridden" in service.run_setup_overview_text(setup).lower()
        service.set_stage_duration(fresh, 0, "180")
        service.set_all_stage_trim(fresh, 10, 20)
        service.toggle_stage_enabled(fresh, 0)
        service.set_segment_label(fresh, 0, "Temporary label")
        assert fresh.profile.stages[0].duration_seconds == 180 and not fresh.profile.stages[0].enabled
        assert fresh.profile.stages[0].normalization.trim_end_seconds == 20 and fresh.labels == ["Temporary label"]
        assert source.read_bytes() == before


def run_tui_configuration_workflow_checks():
    """Headless real Textual app; real adapter events, service and file writes."""
    try:
        from Modules.lvs_tui_app import LinuxValidationSuiteTui
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print("SKIP optional Textual pilot; service/execution workflow tests still run")
        return

    class App(LinuxValidationSuiteTui):
        def _refresh_live_system_pane(self):
            pass  # No hardware collection in a configuration test.

    async def check():
        with TemporaryDirectory(dir=ROOT) as tmp:
            service = Service(Path(tmp)); source = _source(service); before = source.read_bytes()
            app = App(service)
            async with app.run_test(size=(150, 55)) as pilot:
                await pilot.pause()
                await app.action_edit_profile()
                assert any(item.kind == "cpu_instruction_intent" for item in app.profile_edit_items)
                await app._begin_profile_copy_selection("save_as")
                await app._activate_profile_copy_item(0)
                await pilot.press(*list("TUI Saved"), "enter")
                await pilot.pause()
                saved = source.parent / "TUI Saved.json"
                assert saved.exists() and app.profile_edit.profile_path == saved and not app.profile_edit.dirty
                assert app.selected_profile.path == saved
                await app.action_show_profiles()
                assert app.selected_profile.path == saved
                await app.action_setup_run()
                await app._handle_stage_override_choice("Configure Stage Workloads (this run only)")
                await app._select_setup_picker_option(app.setup_picker_options[0])
                assert app.view_mode == "stage_configuration"
                row = next(i + 1 for i, setting in enumerate(app.stage_configuration_fields) if setting.key == "cpu_instruction_intent")
                await app._activate_stage_configuration_item(row)
                app.query_one("#items").index = app.profile_edit_picker_options.index("highest_verified_vector")
                await pilot.press("enter")
                await pilot.pause()
                assert app.run_setup.profile.stages[0].modules.cpu.instruction_intent == "highest_verified_vector"
                assert app.run_setup.profile.stages[0].modules.cpu.instruction_set == "auto"
                assert app.view_mode == "stage_configuration"
                row = next(i + 1 for i, setting in enumerate(app.stage_configuration_fields) if setting.key == "cpu_threads")
                await app._activate_stage_configuration_item(row)
                await pilot.press("ctrl+a", "0", "enter")
                await pilot.pause()
                assert app.run_setup.profile.stages[0].modules.cpu.threads == "all"
                assert app.view_mode == "stage_configuration"
                await app._activate_stage_configuration_item(row)
                await pilot.press("escape")
                assert app.run_setup.profile.stages[0].modules.cpu.threads == "all"
                await app._leave_stage_configuration()
                assert app.view_mode == "setup"
                assert source.read_bytes() == before
                assert service.profile_loader.load_profile(saved).stages[0].modules.cpu.instruction_intent == ""
                # A finished/failed attempt cannot seed the next setup with its
                # temporary settings. Exercise the real completion adapter.
                app._post_run_operator_text = lambda *args: "fixture completion"
                app._finish_run_from_thread("fixture failure", None)
                assert app.run_setup is None
                await pilot.pause()
                await app.action_setup_run()
                assert app.run_setup.profile.stages[0].modules.cpu.instruction_intent == ""
                # Cancel Save As without creating anything; Copy follows the same saved flow.
                await app.action_show_profiles()
                await app.action_edit_profile()
                await app._begin_profile_copy_selection("save_as")
                await app._activate_profile_copy_item(0)
                files = set(service.profile_loader.list_profiles())
                await pilot.press(*list("../bad"), "enter")
                await pilot.pause()
                assert app.view_mode == "profile_copy" and set(service.profile_loader.list_profiles()) == files
                await pilot.press("escape")
                files = set(service.profile_loader.list_profiles())
                await app._begin_profile_copy_selection("save_as")
                await app._activate_profile_copy_item(0)
                await pilot.press("escape")
                assert set(service.profile_loader.list_profiles()) == files
                await app._begin_profile_copy_selection("copy")
                await app._activate_profile_copy_item(0)
                await pilot.press(*list("TUI Copy"), "enter")
                await pilot.pause()
                assert (source.parent / "TUI Copy.json").exists()
                copied = app.profile_edit.profile_path
                # Existing Save commits edits; cancelling a later dirty edit
                # does not undo the saved file or write the discarded changes.
                service.apply_stage_configuration(app.profile_edit, 0, "cpu_threads", "2")
                await app._save_profile_edit()
                assert service.profile_loader.load_profile(copied).stages[0].modules.cpu.threads == "2"
                service.apply_stage_configuration(app.profile_edit, 0, "cpu_threads", "3")
                await app._cancel_profile_edit()
                assert app.profile_edit is not None
                await app._cancel_profile_edit()
                assert app.profile_edit is None
                assert service.profile_loader.load_profile(copied).stages[0].modules.cpu.threads == "2"
                assert source.read_bytes() == before
    asyncio.run(check())


def run_stage_configuration_module_checks():
    from Modules.lvs_profile_models import ValidationProfile
    from Modules.lvs_service_models import ProfileEditState
    from Modules.lvs_tui_view_models import picker_row_labels
    assert picker_row_labels(["", "highest_verified_vector"])[0][0] == "(none)"
    with TemporaryDirectory(dir=ROOT) as tmp:
        service = Service(Path(tmp))
        p = ValidationProfile(profile_name="All modules")
        stage, label = service.profile_editor.template_stage(p, "cpu_3d")
        stage.modules.memory.enabled = True
        stage.modules.vram.enabled = True
        p.stages = [stage]
        edit = ProfileEditState(Path(tmp) / "not-saved.json", p, [label])
        changes = (("cpu_threads", "3"), ("cpu_mode", "normal"), ("cpu_load", "variable"),
                   ("cpu_backend", "native"), ("cpu_instruction_intent", "highest_verified_vector"),
                   ("memory_instruction", "scalar"), ("memory_allocation", "71"),
                   ("gpu_3d_target", "discrete_all"), ("vram_target", "primary"), ("gpu_backend", "vulkan_compute"),
                   ("gpu_compute_variant", "stateful_memory"), ("gpu_allocation", "25"),
                   ("gpu_mode", "variable"), ("gpu_intensity", "normal"),
                   ("vram_backend", "opencl"), ("vram_allocation", "72"))
        for key, value in changes:
            service.apply_stage_configuration(edit, 0, key, value)
        modules = edit.profile.stages[0].modules
        assert modules.cpu.instruction_set == "auto" and modules.cpu.threads == "3"
        assert modules.gpu_3d.allocation_percent == 25 and modules.vram.allocation_percent == 72
        assert modules.memory.allocation_percent == 71
        assert modules.gpu_3d.gpus == "discrete_all" and modules.vram.gpus == "primary"
        for key, value in (("gpu_allocation", "96"), ("vram_allocation", "0"),
                           ("memory_allocation", "1.5"), ("gpu_compute_variant", "bad"),
                           ("gpu_3d_target", "not-a-target")):
            before = deepcopy(edit.profile)
            try: service.apply_stage_configuration(edit, 0, key, value)
            except ValueError: pass
            else: raise AssertionError(f"invalid module override accepted: {key}={value}")
            assert edit.profile == before
        edit.profile.stages[0].modules.cpu.enabled = False
        keys = {s.key for s in service.stage_configuration_settings(edit, 0)}
        assert not any(key.startswith("cpu_") for key in keys)
        # Visible help and Enter-accessible settings cover the formerly hidden intent.
        edit.profile.stages[0].modules.cpu.enabled = True
        assert "O edits selected CPU Instruction Intent" in service.profile_edit_summary_text(edit)
        assert any(item.kind == "configure_stage" for item in service.profile_edit_items(edit))
        assert not edit.profile_path.exists()
