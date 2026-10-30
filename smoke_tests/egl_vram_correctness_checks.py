"""CPU-only checks of the emitted EGL code and normal GPU evidence consumers."""
from __future__ import annotations

import ast
import copy
import json
import math
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Modules.lvs_egl_gles_worker import build_egl_gles_workload_script
from Modules.lvs_gpu_stage_events import vram_target_attainment_events
from Modules.lvs_gpu_vram_evidence import vram_allocation_evidence, vram_readback_status
from Modules.lvs_worker_evidence import apply_worker_entry_context, worker_result_events_from_payload
from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
from Modules.lvs_report_data import _stage_shell, compile_report_data
from Modules.lvs_report_html import _stage_card
from Modules.lvs_stability_events import dedupe_events
from Modules.lvs_summary_text import SummaryTextBuilder
from smoke_tests.neon_fp32_fma_checks import _worker_export_round_trip


def run_egl_vram_pattern_checks() -> None:
    # Execute only the actual generated pure/checking functions, with fake GL.
    # Never load EGL/GLES libraries or launch a hardware workload in regression.
    tree = ast.parse(build_egl_gles_workload_script("vram"))
    names = {"clamp_byte", "approx_channel", "vram_clear_color", "verify_vram_texture"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    writer = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and node.func.attr == "glClearColor"
              and any(isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Call)
                      and isinstance(arg.value.func, ast.Name) and arg.value.func.id == "vram_clear_color"
                      for arg in node.args)]
    assert len(writer) == 2, "initial and recurring texture writes must share the checking contract"
    state = dict(verification_passes=0, vram_verification_passes=0, vram_mismatch_count=0, error_count=0)
    def error(message):
        state["error_count"] += 1
        state["last_error"] = message
    env = dict(math=math, GLES=Mock(), GL_FRAMEBUFFER=1, GL_COLOR_ATTACHMENT0=2,
               GL_TEXTURE_2D=3, vram_framebuffer=4, state=state,
               record_error=error, record_gl_errors=lambda _: None)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<emitted-egl-verification>", "exec"), env)
    def authored(phase, index):
        return [abs(math.sin(phase + index * .1)), abs(math.sin(phase + 1)),
                abs(math.sin(phase + 2)), 1.0]
    def pixels(values):
        return [int(round(max(0., min(1., x)) * 255)) for x in values]
    def check(phase, index, actual, good):
        before = state["vram_mismatch_count"]
        env["read_rgba_sample"] = lambda *_: actual
        env["verify_vram_texture"](phase, 7, index, 2048, 2048)
        assert state["vram_mismatch_count"] - before == (0 if good else 1)
    for phase in (0., .03, .7, 27., 291.6, 486.):
        for index in (0, 2, 85, 141, 255, 256, 282, 457, 511):
            assert list(env["vram_clear_color"](phase, index)) == authored(phase, index)
            env.update(phase=phase, index=index)
            env["texture_index"] = index
            for call in writer:
                exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(value=call)], type_ignores=[])), "<emitted-egl-write>", "exec"), env)
            written = env["GLES"].glClearColor.call_args.args
            correct = pixels(authored(phase, index))
            assert pixels(written) == correct
            check(phase, index, correct, True)
            for channel in range(4):
                sign = -1 if correct[channel] > 127 else 1
                for delta, good in ((4, True), (5, False)):
                    corrupted = correct.copy()
                    corrupted[channel] += sign * delta
                    check(phase, index, corrupted, good)
    assert env["clamp_byte"](-.2) == 0 and env["clamp_byte"](1.2) == 255
    assert env["clamp_byte"](.5) == 128
    for phase, index in ((.7, 85), (27., 457), (291.6, 511)):
        check(phase, index, pixels(authored(phase + .7, index)), False)
        check(phase, index, pixels(authored(phase, index + 17)), False)
    # Nine immutable October 21 signatures, reproduced without needing results/.
    signatures = [(9720, 511, [67,107,253,255]), (900,457,[109,69,169,255]),
                  (9720,511,[67,107,253,255]), (900,457,[109,69,169,255]),
                  (17460,85,[250,39,233,255]), (9180,511,[57,15,206,255]),
                  (540,85,[107,254,154,255]), (1620,511,[188,157,84,255]),
                  (13140,282,[252,152,90,255])]
    for frame, index, actual in signatures:
        assert pixels(authored(frame * .03, index)) == actual
        check(frame * .03, index, actual, True)


def run_gpu_vram_reporting_checks() -> None:
    gib = 1024 ** 3
    valid = dict(kind="gpu", mode="vram", backend="python_opencl", status="ok",
                 error_count=0, vram_mismatch_count=0, last_error="", verification_required=True,
                 suite_verification="memory_readback", verification_passes=3,
                 verification_complete=True, observed_exit_code=0, target_id="fixture-gpu",
                 gpu_index=0, target_vram_bytes=10*gib, active_target_vram_bytes=8*gib,
                 allocated_vram_bytes=10*gib, actual_allocated_bytes=10*gib,
                 allocation_valid=True, device_class="discrete", gpu_memory_kind="dedicated")
    def detail(worker):
        return build_gpu_worker_validation_detail(stage_name="VRAM", stage_type="Combined",
            stage_verdict="pass", payload=worker, backend_name=worker.get("backend", ""), device_name="fixture")
    def attainment(worker):
        return vram_target_attainment_events(worker_results=[worker],
            samples=[SimpleNamespace(values={"gpu_0_vram_used_gb": 1.0})],
            stage_name="VRAM", stage_duration_seconds=600)
    assert vram_readback_status(valid) == "verified"
    info = attainment(valid)[0]
    assert info["category"] == "gpu_vram_telemetry_discrepancy"
    assert info["details"]["allocation_verified"] is True
    assert info["details"]["target_vram_bytes"] == 10*gib
    assert info["details"]["active_target_bytes"] == 8*gib
    assert info["details"]["verified_coverage_bytes"] is None
    assert "sampled readback" in info["message"] and "allocated and verified" not in info["message"]
    assert detail(valid)["TargetVramBytes"] == 10*gib
    failures = []
    for update in (dict(error_count=1), dict(vram_mismatch_count=1), dict(status="error"),
                   dict(verification_complete=False), dict(verification_satisfied=False),
                   dict(vram_verification_satisfied=False),
                   dict(last_error="readback mismatch"), dict(observed_exit_code=-9),
                   dict(error_count="0"), dict(error_count=False)):
        failed = {**valid, **update}
        failures.append(failed)
        assert vram_readback_status(failed) == "failed_or_incomplete"
        assert detail(failed)["VerificationSatisfied"] is False
        assert attainment(failed)[0]["details"]["allocation_verified"] is False
        assert "successful readback verification is not established" in attainment(failed)[0]["message"]
        bound = apply_worker_entry_context(copy.deepcopy(failed), SimpleNamespace(kind="gpu"))
        assert bound["verification_satisfied"] is False
    for key in ("error_count", "status", "verification_passes"):
        old = dict(valid); old.pop(key)
        assert vram_readback_status(old) != "verified"
        assert detail(old)["VerificationSatisfied"] is False
    old = dict(kind="gpu", mode="vram", verification_passes=10)
    assert vram_readback_status(old) == "insufficient_evidence"
    assert detail(old)["VerificationSatisfied"] is False
    clean_shortfall = {**valid, "allocated_vram_bytes": 3*gib, "actual_allocated_bytes": 3*gib, "allocation_valid": False}
    events = worker_result_events_from_payload(clean_shortfall, "VRAM")
    assert [e["category"] for e in events] == ["allocation_insufficient"]
    assert attainment(clean_shortfall)[0]["severity"] == "error"
    both = {**clean_shortfall, "error_count": 1, "vram_mismatch_count": 1, "status": "error"}
    events = worker_result_events_from_payload(both, "VRAM")
    assert [e["category"] for e in events] == ["allocation_insufficient", "verification_error"]
    assert len(dedupe_events(events + events)) == 2
    assert all(e["severity"] == "error" for e in events)
    assert worker_result_events_from_payload({**valid, "vram_mismatch_count": 1}, "VRAM")[0]["category"] == "verification_error"
    shared = {**valid, "device_class": "integrated", "gpu_memory_kind": "shared",
              "backend": "python_egl_gles2", "suite_verification": "render_readback",
              "vram_verification_passes": 3,
              "nominal_allocated_texture_bytes": 10*gib, "actual_allocated_bytes": None,
              "physical_commitment_known": False}
    assert attainment(shared) == [], "shared allocations are not dedicated-VRAM telemetry"
    assert vram_allocation_evidence(shared)["physical_committed_bytes"] is None
    assert detail(shared)["ActualAllocatedBytes"] is None
    assert detail(shared)["PhysicalCommitmentKnown"] is False
    for count in (None, 0, False, "3"):
        assert vram_readback_status({**shared, "vram_verification_passes": count}) != "verified"
        thin = attainment({**shared, "vram_verification_passes": count})
        assert thin[0]["category"] == "gpu_vram_verification_coverage"
        assert thin[0]["details"]["readback_verification_passes"] == (0 if type(count) is int else None)
    ramped = {**shared, "allocated_vram_bytes": 8*gib, "nominal_allocated_texture_bytes": 8*gib}
    assert attainment(ramped)[0]["details"]["allocation_ratio"] == .8
    assert attainment(ramped)[0]["severity"] == "warning"
    # Real artifact/extended/compatibility/report path, no historical mutations.
    for worker in (valid, shared, both):
        with TemporaryDirectory(prefix="lvs-vram-evidence-") as temporary:
            root = Path(temporary)
            exported = _worker_export_round_trip(worker, root, legacy_projection=True)
            normalized = exported["GpuDetails"]["validation_details"][0]
            assert normalized["VerificationSatisfied"] is (worker is not both)
            assert normalized["VerifiedCoverageBytes"] is None
            report = compile_report_data(root)
            evidence = report["stages"][0]["gpu_vram_allocation_evidence"][0]
            assert evidence["readback_verification_status"] == vram_readback_status(worker)
            html = _stage_card(report["stages"][0], {})
            assert vram_readback_status(worker) in html and "physical commitment" in html
            text = SummaryTextBuilder().build(exported)
            assert vram_readback_status(worker) in text and "physical committed bytes" in text
            assert json.loads(json.dumps(normalized))["VerificationSatisfied"] == normalized["VerificationSatisfied"]


def run_egl_slow_frame_checks() -> None:
    """Execute emitted scheduling and finalization, without creating a GL context."""
    tree = ast.parse(build_egl_gles_workload_script("vram"))
    main = next(n for n in tree.body if isinstance(n, ast.While) and ast.unparse(n.test) == "running")
    clear = next(n for n in main.body if isinstance(n, ast.If) and ast.unparse(n.test) == "MODE == 'vram' and textures")
    final = tree.body[tree.body.index(main) + 1:]
    for size in (1, 5, 512):
        checks = Mock()
        clock = [0.]
        gl = Mock()
        def slow_clear(*_): clock[0] += 2.
        gl.glClear.side_effect = slow_clear
        env = dict(MODE="vram", textures=list(range(size)), phase=.7, last_written_phase=None,
                   current_clear_passes=1, GLES=gl, vram_framebuffer=1, tex_side=4096,
                   vram_clear_color=lambda *_: (.2,.4,.6,1.), record_gl_errors=Mock(),
                   verify_vram_texture=checks, last_vram_check=0.,
                   time=SimpleNamespace(monotonic=lambda:clock[0]),
                   state=dict(error_count=0, runtime_memory_guard_triggered=False,
                              vram_verification_passes=3), record_error=Mock())
        for key in ("GL_FRAMEBUFFER", "GL_COLOR_ATTACHMENT0", "GL_TEXTURE_2D", "GL_COLOR_BUFFER_BIT"):
            env[key] = 1
        exec(compile(ast.Module(body=[clear], type_ignores=[]), "<slow-egl-frame>", "exec"), env)
        assert [c.args[2] for c in checks.call_args_list] == list(range(size))
        expected = sorted({0, size//2, size-1})
        # A normal early stop before frame 180 still receives a final sample.
        checks.reset_mock()
        exec(compile(ast.Module(body=final, type_ignores=[]), "<early-egl-stop>", "exec"), env)
        assert [c.args[2] for c in checks.call_args_list] == expected
        checks.reset_mock(); env["state"]["runtime_memory_guard_triggered"] = True
        exec(compile(ast.Module(body=final, type_ignores=[]), "<guard-egl-stop>", "exec"), env)
        assert not checks.called, "emergency termination must not add final GPU work"
        env["textures"] = []; env["state"]["vram_verification_passes"] = 0
        exec(compile(ast.Module(body=final, type_ignores=[]), "<empty-egl-stop>", "exec"), env)
        env["record_error"].assert_called_once_with("EGL VRAM ended without a texture readback verification")


def run_gpu_capture_reporting_checks() -> None:
    from Modules.lvs_advanced_debug import AdvancedDebugLogger
    from Modules.lvs_segment_gpu_worker_summary import GpuWorkerStateSummaryBuilder
    from Modules.lvs_segment_gpu_targeting import GpuTargetingResolver
    # No render count or active/ramped target can masquerade as texture coverage.
    worker = dict(kind="gpu", mode="vram", backend="python_egl_gles2", gpu_index=0,
                  target_vram_bytes=1000, active_target_vram_bytes=500, allocated_vram_bytes=500,
                  verification_passes=6, render_verification_passes=6, vram_verification_passes=0,
                  status="ok", error_count=0)
    window = SimpleNamespace(worker_results=[worker], gpu_workers_initial=[], gpu_workers_final=[])
    summary = GpuWorkerStateSummaryBuilder().summary(window)
    row = summary["Workers"][0]
    assert row["VramAllocationPercent"] == 50. and row["ActiveNominalAllocationPercent"] == 100.
    assert row["TextureVerificationPasses"] == 0 and row["RenderVerificationPasses"] == 6
    for active in (None, 0):
        thin = SimpleNamespace(worker_results=[{**worker, "active_target_vram_bytes":active, "allocated_vram_bytes":0}])
        observed = GpuWorkerStateSummaryBuilder().summary(thin)["Workers"][0]
        assert observed["ActiveTargetVramGB"] == active
        assert observed["VramAllocationPercent"] == 0.
        assert observed["ActiveNominalAllocationPercent"] is None
    target = GpuTargetingResolver(worker_integrity_error_count=lambda _:0).targeting_details(window, {}, {}, [])[0]
    assert target["WorkerEvidence"]["MaxAllocationPercent"] == 50.
    assert target["WorkerEvidence"]["TextureVerificationPasses"] == 0
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        logger = AdvancedDebugLogger(root, enabled=True)
        with patch("Modules.lvs_advanced_debug.shutil.which", return_value="fixture"), patch(
                "Modules.lvs_advanced_debug.subprocess.run", return_value=SimpleNamespace(
                    returncode=1, stdout="unrelated log\nGPU reset\n", stderr="Permission denied\n")):
            logger._capture_command("fixture", ["fixture"], timeout=1, filter_terms=["gpu"])
        text = (root/"advanced_debug"/"fixture.txt").read_text()
        assert "returncode: 1" in text and "Permission denied" in text and "GPU reset" in text
        assert "unrelated log" not in text
        with patch("Modules.lvs_advanced_debug.shutil.which", return_value="fixture"), patch(
                "Modules.lvs_advanced_debug.subprocess.run", side_effect=TimeoutError("timed out")):
            logger._capture_command("timeout", ["fixture"], timeout=1, filter_terms=["gpu"])
        assert "error: timed out" in (root/"advanced_debug"/"timeout.txt").read_text()
        worker.update(egl_selected_device={"selection":"egl_device", "drm_device":"/dev/dri/renderD129"},
                      egl_device_exact_match=True, verification_required=True, suite_verification="render_readback",
                      vram_verification_passes=1, verification_passes=7)
        exported = _worker_export_round_trip(worker, root, legacy_projection=True)
        persisted = exported["Segments"][0]["WorkerResults"][0]
        assert persisted["egl_selected_device"] == worker["egl_selected_device"]
        assert persisted["egl_device_exact_match"] is True
        assert exported["GpuDetails"]["validation_details"][0]["EglDeviceExactMatch"] is True
        # Exercise the actual generated writer, not just a hand-built fixture.
        tree = ast.parse(build_egl_gles_workload_script("vram"))
        writer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "write_result")
        path = root/"emitted.json"
        state = defaultdict(int, egl_selected_device=worker["egl_selected_device"], egl_device_exact_match=True)
        env = {n.id:0 for n in ast.walk(writer) if isinstance(n, ast.Name) and n.id.isupper()}
        env.update(RESULT_FILE=str(path), MODE="vram", state=state, json=json, renderer="fixture",
                   memory_claims=SimpleNamespace(outstanding=0, cleanup_error=""))
        exec(compile(ast.Module(body=[writer], type_ignores=[]), "<actual-egl-writer>", "exec"), env)
        env["write_result"]()
        observed = json.loads(path.read_text())
        assert observed["egl_device_exact_match"] is True
        assert observed["egl_selected_device"] == worker["egl_selected_device"]
        assert observed["vram_verification_satisfied"] is False
        state["vram_verification_passes"] = 1
        env["write_result"]()
        assert json.loads(path.read_text())["vram_verification_satisfied"] is True
        state["error_count"] = 1
        env["write_result"]()
        assert json.loads(path.read_text())["vram_verification_satisfied"] is False
