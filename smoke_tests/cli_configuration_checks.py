"""Scripted normal CLI flows, shared TUI parity and execution capture; no workloads."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from Modules.lvs_cli_compat import BackRequested
from Modules.lvs_cli_profile import ProfileCliAdapter
from Modules.lvs_cli_run_setup import RunSetupCliAdapter
from Modules.lvs_profile_creation import ProfileCreationController
from Modules.lvs_service_models import ProfileEditState
from Modules.lvs_stage_configuration import stage_settings
from smoke_tests.configuration_workflow_checks import ROOT, Service, _source


class Host:
    def __init__(self, service, answers):
        self.service = service
        self.answers = iter(answers)
        self.settings_manager = SimpleNamespace(settings=service.settings)
        self.profile_cli = ProfileCliAdapter(self)
        self.profile_creation = ProfileCreationController(service.profile_editor)
        self._pending_heatsoak_minutes = 0.

    def __getattr__(self, key):
        return getattr(self.service, key)

    def _input(self, prompt):
        answer = next(self.answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def _feature_enabled(self, key):
        return False


def run_cli_profile_persistence_checks():
    with TemporaryDirectory(dir=ROOT) as tmp, contextlib.redirect_stdout(io.StringIO()) as output:
        service = Service(Path(tmp)); source = _source(service); before = source.read_bytes()
        profile = service.profile_loader.load_profile(source)
        labels = service.profile_loader.load_segment_labels(source, profile)
        profile.stages[0].modules.cpu.threads = "2"  # An unsaved edit included by Save As.
        host = Host(service, ["f", "c", "CLI Saved"])
        host.profile_cli.editor.edit_profile_state(source, profile, labels)
        saved = source.parent / "CLI Saved.json"
        assert saved.exists() and "Profile saved: CLI Saved" in output.getvalue()
        assert service.profile_loader.load_profile(saved).stages[0].modules.cpu.threads == "2"
        assert saved in service.profile_loader.list_profiles() and source.read_bytes() == before

        def copy(answers):
            index = service.profile_loader.list_profiles().index(source) + 1
            Host(service, [str(index), *answers]).profile_cli.editor.copy_profile()

        copy(["c", "CLI Copy"])
        assert (source.parent / "CLI Copy.json").exists()
        existing = saved.read_bytes()
        copy(["c", "CLI Saved"])
        assert saved.read_bytes() == existing
        assert "already exists" in output.getvalue()
        files = set(service.profile_loader.list_profiles())
        for answers in (["q"], ["c", ""], ["c", BackRequested()], ["c", "../invalid"]):
            copy(answers)
            assert set(service.profile_loader.list_profiles()) == files
        # Escape from Save As retains the original draft and returns to its editor.
        Host(service, ["f", "c", BackRequested(), "q"]).profile_cli.editor.edit_profile_state(source, profile, labels)
        invalid = deepcopy(profile); invalid.stages[0].duration_seconds = 0
        Host(service, ["f", "c", "Invalid Copy", "q"]).profile_cli.editor.edit_profile_state(source, invalid, labels)
        assert not (source.parent / "Invalid Copy.json").exists()
        with patch.object(service.profile_save, "copy_and_save", side_effect=OSError("write denied")):
            copy(["c", "Write Failure"])
        assert not (source.parent / "Write Failure.json").exists()
        # Deliberate Create remains an unsaved draft until Save, unlike Copy/Save As.
        Host(service, ["New Draft", "", "q"]).profile_cli.editor.create_profile()
        assert not (source.parent / "New Draft.json").exists()
        assert source.read_bytes() == before


def run_cli_workload_override_parity_checks():
    from Modules.lvs_run_executor import RunExecutor
    from Modules.lvs_run_bootstrap import bootstrap_run_artifacts
    from Modules.lvs_cpu_architecture import resolve_cpu_instruction_intent
    from Modules.lvs_cpu_execution import build_cpu_command
    with TemporaryDirectory(dir=ROOT) as tmp, contextlib.redirect_stdout(io.StringIO()) as output:
        root = Path(tmp); service = Service(root); source = _source(service)
        profile = service.profile_loader.load_profile(source)
        other, _ = service.profile_editor.template_stage(profile, "gpu_vram")
        profile.stages[0].modules.gpu_3d = other.modules.gpu_3d
        profile.stages[0].modules.vram = other.modules.vram
        profile.stages[0].modules.memory.enabled = True
        service.profile_loader.save_profile(source, profile)
        before = source.read_bytes()
        labels = service.profile_loader.load_segment_labels(source, profile)
        changes = [("cpu_instruction_intent", "highest_verified_vector"), ("cpu_threads", "2"),
                   ("cpu_mode", "normal"), ("cpu_load", "variable"),
                   ("memory_instruction", "scalar"), ("memory_allocation", "60"),
                   ("gpu_backend", "vulkan_compute"), ("gpu_compute_variant", "stateful_memory"),
                   ("gpu_allocation", "25"), ("gpu_mode", "variable"), ("gpu_intensity", "normal"),
                   ("gpu_3d_target", "primary"), ("vram_target", "all"),
                   ("vram_backend", "opencl"), ("vram_allocation", "65")]
        tui = service.create_run_setup(source)
        tui_edit = service.run_setup_stage_edit(tui)
        answers = ["o", "5", "1"]
        for key, value in changes:
            fields = service.stage_configuration_settings(tui_edit, 0)
            answers.extend([str(next(i + 1 for i, setting in enumerate(fields) if setting.key == key)), value])
            service.apply_stage_configuration(tui_edit, 0, key, value)
        answers.extend(["", "4", "d", "u"])
        host = Host(service, answers)
        adapter = RunSetupCliAdapter(host)
        setup = adapter._create_run_setup_state(source, profile, labels)
        metadata = adapter._run_setup_review_loop(adapter._build_run_setup_review_controller(setup), setup, profile, labels)
        assert metadata is not None and metadata.advanced_debug_logging
        assert service.profile_loader.profile_payload(profile) == service.profile_loader.profile_payload(tui_edit.profile)
        assert profile.stages[0].modules.cpu.instruction_set == "auto"
        assert "highest_verified_vector" in output.getvalue() and "this run only" in output.getvalue()
        assert source.read_bytes() == before

        def run(path, effective, effective_labels, run_metadata, **kwargs):
            assert effective is profile and effective.stages[0].modules.vram.allocation_percent == 65
            cpu = effective.stages[0].modules.cpu
            decision = resolve_cpu_instruction_intent("arm64", cpu.instruction_intent,
                ["scalar", "neon", "neon_fp32_fma", "sve_fp32_fma"])
            command = build_cpu_command(worker_count=2, helper_available=True, helper_path="fixture/helper",
                requested_mode="auto", instruction_set=cpu.instruction_set, mode=cpu.mode,
                stress_ng_available=False, python_runtime="fixture/python", target_cpu_ids=[2, 9],
                cpu_kernel_flavor=decision["resolved_kernel_flavor"])
            assert "sve_fp32_fma" in command
            with patch("Modules.lvs_run_bootstrap.AdvancedDebugLogger.capture_run_start"):
                boot = bootstrap_run_artifacts(app_name="LVS", app_version="fixture", profile_path=path,
                    profile=effective, labels=effective_labels, metadata=run_metadata,
                    preflight={"plan": [{"runnable": True, "cpu_selection_evidence": decision}], "validation": {}, "telemetry_capabilities": {}},
                    run_dir=root / "execution", started_iso="2026-10-23T00:00:00+00:00", runtime_environment={},
                    backends={}, backend_details={}, abort_on_fail_threshold=False, abort_on_worker_error=False,
                    abort_on_system_fault=False, abort_run_on_stage_abort=False, privileged_helper_enabled=False,
                    recovery_report={}, collect_system_info=lambda *args: {}, print_run_header=lambda *args: None,
                    print_stage_skip=lambda *args: None, print_run_start=lambda *args: None)
            return boot.run_dir

        executor = RunExecutor(settings=service.settings, profile_loader=service.profile_loader,
            orchestrator=SimpleNamespace(run=run), default_run_metadata=service.default_run_metadata,
            ensure_enhanced_telemetry_ready=lambda: True, run_heatsoak_if_requested=lambda *args, **kw: True)
        result = executor.run_profile_capture_output(source, setup=setup, metadata=metadata)
        captured = service.profile_loader.load_profile(result.run_dir / "profile_used.json")
        assert service.profile_loader.profile_payload(captured) == service.profile_loader.profile_payload(profile)
        manifest = json.loads((result.run_dir / "run_manifest.json").read_text())
        assert manifest["advanced_debug_logging"] and manifest["source_provenance"]
        fresh = service.create_run_setup(source)
        assert fresh.profile.stages[0].modules.cpu.instruction_set == "sve_fp32_fma"
        assert fresh.profile.stages[0].modules.cpu.threads == "all"
        fresh_cli = adapter._create_run_setup_state(source, service.profile_loader.load_profile(source), labels)
        assert fresh_cli.profile.stages[0].modules.cpu.instruction_intent == ""
        assert fresh_cli.profile.stages[0].modules.vram.allocation_percent == other.modules.vram.allocation_percent
        assert source.read_bytes() == before
        # Invalid/incompatible input and Escape are transactional in the CLI too.
        fields = stage_settings(profile.stages[0], service.profile_editor)
        index = next(i + 1 for i, field in enumerate(fields) if field.key == "cpu_threads")
        Host(service, [str(index), "0", str(index), BackRequested(), ""]).profile_cli.configure_stage_workloads(profile, 0, labels, run_only=True)
        assert profile.stages[0].modules.cpu.threads == "2"
        assert "Setting unchanged" in output.getvalue()
        cancelled = RunSetupCliAdapter(Host(service, ["b"]))
        cancel_profile = service.profile_loader.load_profile(source)
        assert cancelled._run_setup_review(source, cancel_profile, labels) is None


def run_cli_instruction_catalog_checks():
    from Modules.lvs_profile_editor import ProfileEditor
    with TemporaryDirectory(dir=ROOT) as tmp, contextlib.redirect_stdout(io.StringIO()):
        service = Service(Path(tmp))
        for value in ProfileEditor.CPU_INSTRUCTION_OPTIONS:
            assert Host(service, [value]).profile_cli._choose_cpu_instruction_set() == value
        for value in ProfileEditor.MEMORY_INSTRUCTION_OPTIONS:
            assert Host(service, [value]).profile_cli._choose_memory_instruction_set() == value
        assert Host(service, ["0"]).profile_cli._choose_cpu_instruction_set("scalar") == "scalar"
        assert Host(service, ["-1"]).profile_cli._choose_memory_instruction_set("scalar") == "scalar"
