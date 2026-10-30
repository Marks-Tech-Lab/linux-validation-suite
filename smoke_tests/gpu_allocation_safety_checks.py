"""Adversarial planning -> materialization -> launch ABI -> runtime guard tests.

No GPU library, GPU workload, or physical stress process is executed here.
"""
from __future__ import annotations

import ast
import ctypes
import json
import os
from dataclasses import replace
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Modules.lvs_gpu_allocation_safety import resolve_gpu_allocation_safety, runtime_gpu_allocation_safety, validate_gpu_assignment, ENV_KEY
from Modules.lvs_gpu_worker_plan import bind_gpu_allocation_safety, serialize_gpu_worker_spec
from Modules.lvs_gpu_worker_materializer import materialize_gpu_worker
from Modules.lvs_gpu_worker_planner import build_stage_gpu_worker_specs
from Modules.lvs_gpu_worker_retune import retune_gpu_worker
from Modules.lvs_gpu_retune_process import replace_gpu_process_for_retune
from Modules.lvs_egl_gles_workers import build_python_vram_worker
from Modules.lvs_opencl_workers import build_python_opencl_vram_worker, build_python_opencl_compute_worker
from Modules.lvs_vulkan_workers import build_python_vulkan_compute_worker, build_python_vulkan_transfer_worker
from Modules.lvs_egl_gles_worker import build_egl_gles_workload_script
from Modules.lvs_opencl_vram_worker import build_opencl_vram_workload_script
from Modules.lvs_opencl_compute_worker import build_opencl_compute_workload_script
from Modules.lvs_system_memory_budget import build_stage_system_memory_plan, apply_stage_system_memory_plan
from Modules.lvs_runtime_memory_guard import (initialize_runtime_memory_guard, claim_runtime_allocation_growth,
    release_runtime_allocation_claim, runtime_memory_stop_required, RuntimeMemoryClaims)
from Modules.lvs_vram_policy import cap_gpu_vram_target_bytes
from Modules.lvs_stage_launch_plan import StageLaunchCommand
from Modules.lvs_stage_process_control import launch_stage_processes_from_plan
from Modules.lvs_opencl_allocation_timing import OpenCLAllocationTiming
from Modules.lvs_worker_evidence import apply_worker_entry_context
from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract

MIB, GIB = 1024**2, 1024**3
ROOT = Path(__file__).resolve().parents[1]


class Runner:
    def __init__(self, capability):
        self.capability = capability
        self.target = dict(target_id="fixture", card="card0", slot="0000:82:00.0", gpu_index=0,
                           vendor="nvidia", vendor_id="10de", device="1234", vram_total=0,
                           nvidia_uuid="GPU-11111111-2222-3333-4444-555555555555")
        self._settings = SimpleNamespace(gpu_safe_max_load_scale=1.)
        self._build_python_vram_worker = partial(build_python_vram_worker, self)
        self._build_python_opencl_vram_worker = partial(build_python_opencl_vram_worker, self)
        self._build_python_opencl_compute_worker = partial(build_python_opencl_compute_worker, self)
        self._build_python_vulkan_compute_worker = partial(build_python_vulkan_compute_worker, self)
        self._build_python_vulkan_transfer_worker = partial(build_python_vulkan_transfer_worker, self)
    def _gpu_capability_profile(self, target): return self.capability
    def _gpu_target_by_id(self, target): return self.target
    def _python_runtime(self): return "python3"
    def _gpu_worker_tuned_params(self, *a, **k):
        return dict(surface_size=1024, draw_count=64, shader_iterations=24, texture_side=2048,
                    clear_passes=1, capability=self.capability)
    def _gpu_internal_ramp_params(self): return dict(ramp_step_seconds=15., start_load_fraction=.5)
    def _egl_gpu_backend_for_target(self, target): return {}
    def _opencl_gpu_backend(self): return {}
    def _opencl_device_for_target(self, target): return dict(opencl_index=0, max_alloc_bytes=256*MIB)
    def _opencl_target_env(self, *a): return {}
    def _vulkan_target_env(self, *a): return {}
    def _vulkan_device_for_target(self, target):
        return dict(available=True, ambiguous=False, device=dict(index=0, deviceName="fixture",
                    deviceUUID="11111111-2222-3333-4444-555555555555", vendorID="10de", deviceID="1234"))
    def _wrap_gpu_command(self, command, *a): return command
    def _cap_gpu_vram_target_bytes(self, target, value):
        return cap_gpu_vram_target_bytes(requested_bytes=value, target_total=0, safe_mode_enabled=True, safe_max_vram_percent=90)
    def _gpu_safe_mode_enabled(self): return True
    def _gpu_safe_max_tuning_step(self): return 2
    def _normalize_gpu_3d_intensity(self, value): return value
    def _normalize_opencl_compute_variant(self, value): return value
    def _normalize_vulkan_compute_variant(self, value): return value
    def _vulkan_transfer_buffer_bytes(self, *a): return 128*MIB
    def _vulkan_compute_buffer_bytes(self, *a, **k): return 128*MIB
    def _vulkan_compute_rounds(self, *a): return 16
    def _vulkan_compute_dispatch_repeats(self, *a): return 1
    _egl_gles_workload_script = staticmethod(build_egl_gles_workload_script)
    _opencl_vram_workload_script = staticmethod(build_opencl_vram_workload_script)
    def _opencl_compute_workload_script(self, **kwargs):
        params = kwargs.get("worker_params") or {}
        return build_opencl_compute_workload_script(
            **kwargs, compute_variant=params.get("compute_variant", "baseline"))


def _spec(runner, backend, target=128*MIB):
    if backend == "python_egl_gles2": return runner._build_python_vram_worker(runner.target, target)
    if backend == "python_opencl": return runner._build_python_opencl_vram_worker(runner.target, target)
    if backend == "python_opencl_compute": return runner._build_python_opencl_compute_worker(runner.target)
    if backend == "python_vulkan_compute": return runner._build_python_vulkan_compute_worker(runner.target, buffer_bytes_override=target)
    return runner._build_python_vulkan_transfer_worker(runner.target, buffer_bytes_override=target)


def _annotate(runner, worker, percent=90):
    # Use the actual planner annotation, replacing only provider backend discovery.
    stage = SimpleNamespace(modules=SimpleNamespace(gpu_3d=SimpleNamespace(enabled=worker.workload=="gpu_3d",allocation_percent=percent),
                vram=SimpleNamespace(enabled=worker.workload=="vram",allocation_percent=percent),
                memory=SimpleNamespace(enabled=False)))
    with patch("Modules.lvs_gpu_worker_planner.build_gpu_3d_worker_specs", return_value=[worker]), \
         patch("Modules.lvs_gpu_worker_planner.build_vram_worker_specs", return_value=[worker]):
        return stage, build_stage_gpu_worker_specs(runner, stage)[0]


def run_gpu_allocation_safety_boundary_checks():
    cases = [("shared","integrated","high",False,True), ("shared","discrete","high",False,True),
             ("unknown","discrete","low",False,True), ("dedicated","discrete","high",False,False),
             ("dedicated","integrated","high",False,False), ("dedicated","discrete","low",False,True),
             ("dedicated","discrete","high",True,True), ("unknown","","low",False,True)]
    backends = ("python_egl_gles2","python_opencl","python_opencl_compute","python_vulkan_compute","python_vulkan_transfer")
    for kind, cls, confidence, conflict, protected in cases:
        cap = dict(memory_kind=kind, device_class=cls, classification_source="conflict" if conflict else "explicit_memory_architecture",
                   classification_confidence=confidence, dedicated_vram_capacity_bytes=8*GIB if kind=="dedicated" else 0,
                   shared_addressable_capacity_bytes=8*GIB if kind=="shared" else 0,
                   opencl_global_memory_bytes=8*GIB, opencl_max_single_allocation_bytes=256*MIB,
                   gles_max_texture_object_bytes=16384**2*4)
        for backend in backends:
            runner=Runner(cap);stage,worker=_annotate(runner,_spec(runner,backend))
            assert worker.allocation_safety["device_memory_requires_system_guard"] is protected
            plan=build_stage_system_memory_plan(stage=stage,gpu_workers=[worker],total_bytes=32*GIB,available_bytes=24*GIB)
            assert plan["valid"], (backend,kind,plan)
            assigned=apply_stage_system_memory_plan([worker],plan)[0]
            materialized=materialize_gpu_worker(runner,assigned)
            assert materialized.allocation_safety==assigned.allocation_safety
            assert serialize_gpu_worker_spec(materialized)["allocation_safety"]==assigned.allocation_safety
            if backend.startswith("python_vulkan"):
                encoded=materialized.command[materialized.command.index("--allocation-safety-json")+1]
            else:
                encoded=materialized.env_overrides[ENV_KEY]
                compile(materialized.command[2],"<generated-worker>","exec")
            runtime=runtime_gpu_allocation_safety(encoded)
            assert runtime["device_memory_requires_system_guard"] is protected
            # Test actual Popen environment propagation without starting a process.
            popen=Mock(return_value=SimpleNamespace())
            launch_stage_processes_from_plan([StageLaunchCommand("gpu",materialized.command,materialized)],
                stage_id="safety",command_env={"PRESERVED":"1"},popen_factory=popen)
            assert runtime_gpu_allocation_safety(popen.call_args.kwargs["env"][ENV_KEY])==runtime
            assert popen.call_args.kwargs["env"]["PRESERVED"]=="1"
            bound=apply_worker_entry_context(dict(kind="gpu",mode=worker.workload), SimpleNamespace(kind="gpu",gpu_spec=materialized))
            assert preserve_legacy_worker_evidence_contract(bound)["allocation_safety"]==runtime
            with TemporaryDirectory() as tmp:
                path=Path(tmp)/"guard.json";initialize_runtime_memory_guard(plan,path)
                d=json.loads(path.read_text());d.update(runtime_growth_allowance_bytes=0,stage_termination_required=True);path.write_text(json.dumps(d))
                with patch.dict(os.environ,{"LVS_RUNTIME_MEMORY_GUARD_PATH":str(path)}):
                    result=claim_runtime_allocation_growth(MIB,shared_system_memory=protected)
                    assert result["allowed"] is False, (backend,kind,result)
                    assert runtime_memory_stop_required() is True
                # Dedicated bytes are exempt only from growth, not emergency stop.
                d.update(stage_termination_required=False,runtime_growth_allowance_bytes=0);path.write_text(json.dumps(d))
                result=claim_runtime_allocation_growth(MIB,shared_system_memory=protected,control_path=str(path))
                assert result["allowed"] is (not protected)
                if backend.startswith("python_vulkan"):
                    assert worker.system_memory_budget_participation  # host staging, even dedicated
                    assert not claim_runtime_allocation_growth(MIB,shared_system_memory=True,control_path=str(path))["allowed"]
                d.update(enabled=True,runtime_growth_allowance_bytes=4*MIB,runtime_headroom_bytes=4*MIB);path.write_text(json.dumps(d))
                with patch.dict(os.environ,{"LVS_RUNTIME_MEMORY_GUARD_PATH":str(path)}):
                    ledger=RuntimeMemoryClaims();assert ledger.claim(MIB,shared_system_memory=True)["allowed"]
                    ledger.release(MIB,shared_system_memory=True);ledger.release(MIB,shared_system_memory=True)
                    assert json.loads(path.read_text())["runtime_growth_allowance_bytes"]==4*MIB
                    assert ledger.claim(MIB,shared_system_memory=True)["allowed"]
                    ledger.close();ledger.close();assert ledger.outstanding==0
    for value in (None,"{bad}","{}",json.dumps(dict(contract="gpu_allocation_safety_v1",device_memory_requires_system_guard=False))):
        assert runtime_gpu_allocation_safety(value)["device_memory_requires_system_guard"]
    for extra in (dict(gpu_memory_kind="shared"),dict(classification_source=123),
                  dict(dedicated_vram_capacity_bytes=True),dict(memory_architecture="shared")):
        evidence=dict(memory_kind="dedicated",classification_source="explicit_memory_architecture",
                      classification_confidence="high",dedicated_vram_capacity_bytes=8*GIB)
        evidence.update(extra)
        assert resolve_gpu_allocation_safety(evidence)["device_memory_requires_system_guard"]
    dedicated=Runner(dict(memory_kind="dedicated",device_class="discrete",classification_source="explicit_memory_architecture",
                          classification_confidence="high",dedicated_vram_capacity_bytes=8*GIB))
    w=_spec(dedicated,"python_opencl")
    assert not w.allocation_safety["device_memory_requires_system_guard"]
    # A variable system-memory budget is an additional obligation, not a way
    # for a later capability/class observation to switch off runtime claims.
    assert bind_gpu_allocation_safety(replace(w,system_memory_budget_participation=True)).allocation_safety["device_memory_requires_system_guard"]
    # No runtime still authorizes safety from device_class.
    for path in (ROOT/"Modules/lvs_egl_gles_worker.py",ROOT/"Modules/lvs_opencl_vram_worker.py",ROOT/"Modules/lvs_opencl_compute_worker.py"):
        assert 'shared_system_memory=DEVICE_CLASS != "discrete"' not in path.read_text()
    for path in (ROOT/"native/vulkan_compute_worker.py",ROOT/"native/vulkan_transfer_worker.py"):
        source=path.read_text();assert 'shared_memory_device = str(args.device_class' not in source
        assert '"--allocation-safety-json"' in source and 'shared_system_memory=True' in source
    # Evaluate the actual backend claim expressions against a real guard file.
    # The old discrete-class expressions would authorize the first three calls.
    scripts = [build_egl_gles_workload_script("vram",128*MIB),
               build_opencl_vram_workload_script(128*MIB,"","","","","","",0,0),
               build_opencl_compute_workload_script(target_vendor="",target_vendor_id="",target_name="",
                   target_card="",target_slot="",target_id="",target_gpu_index=0,target_vram_total=0,compute_variant="baseline"),
               (ROOT/"native/vulkan_compute_worker.py").read_text(),
               (ROOT/"native/vulkan_transfer_worker.py").read_text()]
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/"guard.json"
        path.write_text(json.dumps(dict(enabled=True,stage_termination_required=True,runtime_growth_allowance_bytes=0)))
        for script in scripts:
            calls=[n for n in ast.walk(ast.parse(script)) if isinstance(n,ast.Call)
                   and isinstance(n.func,ast.Name) and n.func.id=="claim_runtime_allocation_growth"]
            for call in calls:
                for kind in ("shared","unknown"):
                    policy=resolve_gpu_allocation_safety(dict(memory_kind=kind,device_class="discrete"))
                    env=dict(claim_runtime_allocation_growth=claim_runtime_allocation_growth,
                             ALLOCATION_SAFETY=policy,allocation_safety=policy,DEVICE_CLASS="discrete",
                             state=dict(bytes_per_texture=16*MIB),buffer_bytes=64*MIB,request_size=64*MIB,request_bytes=64*MIB,
                             guard_claim_bytes=128*MIB,shared_memory_device=True,staging_bytes=12288,extra=4096,
                             args=SimpleNamespace(system_memory_fixed_commitment_bytes=MIB))
                    with patch.dict(os.environ,{"LVS_RUNTIME_MEMORY_GUARD_PATH":str(path)}):
                        result=eval(compile(ast.Expression(call),"<actual-backend-claim>","eval"),env)
                    assert not result["allowed"], (kind,ast.unparse(call),result)
        # Run actual generated cleanup branches, not simulated release policy.
        for script in scripts[1:3]:
            tree=ast.parse(script)
            final=next(n.finalbody for n in ast.walk(tree) if isinstance(n,ast.Try)
                       and any(isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="cleanup_ok"
                               for t in x.targets) for x in n.finalbody))
            start=next(i for i,x in enumerate(final) if isinstance(x,ast.Assign)
                       and any(isinstance(t,ast.Name) and t.id=="cleanup_ok" for t in x.targets))
            for release_code in (0,-1):
                path.write_text(json.dumps(dict(enabled=True,stage_termination_required=False,
                                               runtime_growth_allowance_bytes=2*MIB,runtime_headroom_bytes=2*MIB)))
                with patch.dict(os.environ,{"LVS_RUNTIME_MEMORY_GUARD_PATH":str(path)}):
                    ledger=RuntimeMemoryClaims();assert ledger.claim(MIB,shared_system_memory=True)["allowed"]
                    api=SimpleNamespace(**{name:Mock(return_value=release_code) for name in
                        ("clReleaseMemObject","clReleaseKernel","clReleaseProgram","clReleaseCommandQueue","clReleaseContext")})
                    env=dict(cl=api,CL=api,CL_SUCCESS=0,memory_claims=ledger,
                             buffers=[(1,MIB)] if script==scripts[1] else [1],kernel=1,program=1,queue=1,context=1,
                             drain_readbacks=Mock(return_value=True),release_readback_events=Mock(),readback_events=[],record_error=Mock(),
                             state={},write_result=Mock())
                    exec(compile(ast.Module(body=final[start:],type_ignores=[]),"<actual-opencl-cleanup>","exec"),env)
                    assert ledger.outstanding==(0 if release_code==0 else MIB)
                    assert bool(ledger.cleanup_error)==(release_code!=0)


def run_gpu_cleanup_reporting_checks():
    """Execute emitted cleanup and persistence, then the normal export path."""
    from Modules.lvs_worker_integrity import worker_result_successful, worker_cleanup_satisfied
    from Modules.lvs_worker_evidence import worker_result_events_from_payload
    from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
    from Modules.lvs_report_helpers import build_report_summary
    from Modules.lvs_summary_text import SummaryTextBuilder

    script = build_opencl_compute_workload_script(target_vendor="", target_vendor_id="", target_name="",
        target_card="", target_slot="", target_id="", target_gpu_index=0, target_vram_total=0,
        compute_variant="baseline")
    tree = ast.parse(script)
    final = next(n.finalbody for n in tree.body if isinstance(n, ast.Try) and n.finalbody)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"record_error", "write_result"}]
    releases = ("clReleaseMemObject", "clReleaseKernel", "clReleaseProgram",
                "clReleaseCommandQueue", "clReleaseContext")
    cases = ["success", "claim_close", "release_exception", *releases]
    with TemporaryDirectory(dir=ROOT) as tmp:
        for failure in cases:
            state = dict(kind="gpu", mode="gpu_3d", backend="python_opencl_compute", status="ok",
                         error_count=0, verification_passes=7, verification_required=True,
                         compute_mismatch_count=0)
            ledger = RuntimeMemoryClaims()
            ledger.outstanding = 4096  # A previously successful, still charged claim.
            api = SimpleNamespace(**{name: Mock(return_value=-5 if name == failure else 0)
                                     for name in releases})
            if failure == "release_exception":
                api.clReleaseMemObject.side_effect = RuntimeError("release failed")
            env = dict(state=state, memory_claims=ledger, CL=api, buffers=[1], kernel=1,
                       program=1, queue=1, context=1, RESULT_FILE=str(Path(tmp)/"worker.json"),
                       json=json, os=os)
            exec(compile(ast.Module(body=functions, type_ignores=[]), "<emitted-writers>", "exec"), env)
            with patch("Modules.lvs_runtime_memory_guard.release_runtime_allocation_claim",
                       side_effect=OSError("guard update failed") if failure == "claim_close" else None) as release:
                exec(compile(ast.Module(body=final, type_ignores=[]), "<emitted-cleanup>", "exec"), env)
                assert release.call_count == (1 if failure in {"success", "claim_close"} else 0)
                # Atexit repeats publication, not cleanup or claim release.
                env["write_result"]()
                if failure == "success":
                    ledger.close()
                    assert release.call_count == 1
            payload = json.loads(Path(env["RESULT_FILE"]).read_text())
            good = failure == "success"
            assert payload["cleanup_complete"] is good
            assert payload["status"] == ("ok" if good else "error")
            assert payload["error_count"] == (0 if good else 1)
            assert ledger.outstanding == (0 if good else 4096)
            assert bool(payload["allocation_claim_cleanup_error"]) is (not good)
            assert payload["verification_passes"] == 7 and payload["verification_satisfied"] is True
            assert payload["compute_mismatch_count"] == 0
            assert worker_result_successful(payload) is good
            events = worker_result_events_from_payload(payload, "Compute")
            assert any(e["category"] == "worker_cleanup_incomplete" for e in events) is (not good)
            # Normal compatibility WorkerResults filtering cannot erase failure.
            raw = json.loads(json.dumps(preserve_legacy_worker_evidence_contract(payload)))
            assert worker_result_successful(raw) is good
            detail = build_gpu_worker_validation_detail(stage_name="Compute", stage_type="Combined",
                stage_verdict="pass" if good else "fail", payload=raw,
                backend_name="python_opencl_compute", device_name="fixture")
            detail = json.loads(json.dumps(detail))
            assert detail["CleanupComplete"] is good and detail["VerificationPasses"] == 7
            assert detail["VerificationSatisfied"] is True
            assert worker_result_successful(detail) is good
            summary = build_report_summary(overall_result="Pass" if good else "Fail",
                execution_detail="fixture", elapsed="00:00:01", segments=[], stability_interpretation={},
                all_error_events=events, gpu_validation_details=[detail], skipped_stages=[])
            assert summary["GpuWorkerSummary"]["SuccessfulWorkerResultCount"] == int(good)
            assert summary["GpuWorkerSummary"]["WorkerFailureCount"] == int(not good)
            text = SummaryTextBuilder().build({"ReportSummary": summary,
                "Ended": "2026-10-26T12:00:01-04:00",
                "Segments": [{"Verdict": "pass" if good else "fail"}]})
            assert ("Result: Pass" if good else "Result: Fail") in text
    # Shared consumers reject explicit errors even when older workers kept status=ok.
    base = dict(status="ok", verification_required=True, verification_passes=7)
    for error_key in ("allocation_claim_cleanup_error", "AllocationClaimCleanupError"):
        contradictory = {**base, error_key: "guard update failed", "cleanup_complete": True}
        assert not worker_result_successful(contradictory)
    assert worker_result_successful({**base, "outstanding_system_memory_claim_bytes": 4096})
    assert worker_result_successful(base)  # Legacy absence remains compatible.
    assert not worker_cleanup_satisfied({"cleanup_complete": True, "CleanupComplete": False})


def run_vulkan_terminal_publication_checks():
    """Execute the real writer and teardown without launching a GPU worker."""
    import time
    import sys
    sys.path.insert(0, str(ROOT / "native"))
    import vulkan_compute_worker as worker
    from Modules.lvs_worker_integrity import worker_result_successful
    from Modules.lvs_worker_evidence import worker_result_events_from_payload
    from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail

    tree = ast.parse((ROOT / "native/vulkan_compute_worker.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    writer = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "write_result")
    final = next(n.finalbody for n in main.body if isinstance(n, ast.Try) and n.finalbody)
    # Keep nonlocal bindings and finally-return behavior identical to main().
    wrapper = ast.FunctionDef(name="exercise", args=ast.arguments(posonlyargs=[], args=[],
        kwonlyargs=[], kw_defaults=[], defaults=[]), decorator_list=[], body=[
        ast.parse("last_result_write_monotonic = 0.0").body[0], writer,
        *ast.parse('write_result("completed", force=True)').body,
        ast.Try(body=[ast.Return(value=ast.Constant(0))], handlers=[], orelse=[], finalbody=final)])
    code = compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                   "<actual-vulkan-terminal-path>", "exec")
    with TemporaryDirectory(dir=ROOT) as tmp:
        for failure in (None, "destroy", "close", "final_write"):
            path = Path(tmp) / "worker.json"
            state = dict(kind="gpu", backend="python_vulkan_compute", status="ok", error_count=0,
                         verification_required=True, verification_passes=9, compute_mismatch_count=0,
                         initial_verification_completed=True, final_verification_completed=True,
                         result_write_count=0, result_write_elapsed_seconds=0.,
                         result_write_error_count=0, result_write_interval_target_seconds=60.)
            ledger = RuntimeMemoryClaims()
            ledger.outstanding = 4096
            api = Mock()
            if failure == "destroy":
                api.vkDestroyDevice.side_effect = RuntimeError("destroy failure")
            if failure == "close":
                ledger.close = Mock(side_effect=OSError("close failure"))
            recorder = worker.SlowOperationRecorder(state)
            writes = []
            def persist(*args, **kwargs):
                writes.append((state["last_result_write_reason"], kwargs.get("force")))
                if failure == "final_write" and len(writes) == 2:
                    raise OSError("terminal write failure")
                return worker.persist_worker_result(*args, **kwargs)
            env = dict(state=state, dispatch_diagnostic=None, args=SimpleNamespace(result_file=str(path)),
                       handles=dict(device=1, instance=2, buffers=[3], memories=[4]),
                       vk=api, memory_claims=ledger, stalls=recorder, time=time,
                       worker_cpu_started=time.process_time(),
                       timed_action_due=worker.timed_action_due, persist_worker_result=persist)
            exec(code, env)
            with patch("Modules.lvs_runtime_memory_guard.release_runtime_allocation_claim") as release:
                try:
                    result = env["exercise"]()
                except SystemExit as exc:
                    result = exc.code
                assert release.call_count == (1 if failure in (None, "final_write") else 0)
            assert writes == [("completed", True), ("finalize", True)]
            assert result == (0 if failure is None else 13)
            assert state["verification_passes"] == 9 and state["compute_mismatch_count"] == 0
            assert api.vkDestroyDevice.call_count == 1
            if failure == "final_write":
                import io
                terminal = io.StringIO()
                recorder.emit_terminal(terminal)
                diagnostic = json.loads(terminal.getvalue())
                assert diagnostic["result_write_error_count"] == 1
                assert diagnostic["last_result_write_error"] == "OSError"
                assert state["result_write_error_count"] == 1
                assert state["last_result_write_error"] == "OSError"
                assert not worker_result_successful(state)
                # The forced atexit retry can retain the failure without doing
                # resource teardown or claim release a second time.
                callbacks = []
                worker.register_worker_exit_diagnostics(recorder,
                    lambda reason, **kw: persist(str(path), state, recorder, **kw),
                    register=callbacks.append)
                callbacks[-1]()
            payload = json.loads(path.read_text())
            assert payload["cleanup_complete"] is (failure not in ("destroy", "close"))
            assert payload["outstanding_system_memory_claim_bytes"] == (4096 if failure in ("destroy", "close") else 0)
            assert worker_result_successful(payload) is (failure is None)
            compat = preserve_legacy_worker_evidence_contract(payload)
            assert worker_result_successful(compat) is (failure is None)
            detail = build_gpu_worker_validation_detail(stage_name="Vulkan", stage_type="GPU",
                stage_verdict="pass" if failure is None else "fail", payload=compat,
                backend_name="python_vulkan_compute", device_name="fixture")
            assert worker_result_successful(detail) is (failure is None)
            if failure in ("destroy", "close"):
                assert any(e["category"] == "worker_cleanup_incomplete"
                           for e in worker_result_events_from_payload(payload, "Vulkan"))


def run_vulkan_transfer_terminal_checks():
    """Execute the real transfer writer/finalizer, including finally exit codes."""
    import io
    import sys
    from contextlib import redirect_stderr
    from copy import deepcopy
    sys.path.insert(0, str(ROOT / "native"))
    import vulkan_transfer_worker as worker
    from Modules.lvs_worker_integrity import worker_result_successful
    from Modules.lvs_worker_evidence import worker_result_events_from_payload
    from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
    from Modules.lvs_report_data import compile_report_data
    from Modules.lvs_result_report_adapters import result_summary_text
    from Modules.lvs_summary_text import SummaryTextBuilder
    from smoke_tests.standalone_report_checks import _build_fixture

    tree = ast.parse((ROOT / "native/vulkan_transfer_worker.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    functions = [next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == name)
                 for name in ("record_error", "write_result")]
    final = next(n.finalbody for n in main.body if isinstance(n, ast.Try) and n.finalbody)
    wrapper = ast.FunctionDef(name="exercise", args=ast.arguments(posonlyargs=[], args=[],
        kwonlyargs=[], kw_defaults=[], defaults=[]), decorator_list=[], body=[
        *functions, *ast.parse("write_result()\ncallbacks.append(lambda: write_result(force=True))").body,
        ast.Try(body=[ast.Return(value=ast.Constant(0))], handlers=[], orelse=[], finalbody=final)])
    code = compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                   "<actual-transfer-terminal-path>", "exec")
    with TemporaryDirectory(dir=ROOT) as tmp:
        root = Path(tmp)
        run = root / "run"; run.mkdir(); _build_fixture(run, native="pass")
        (run / "run_summary.txt").write_text("Result: Finished\n")
        original = json.loads((run / "run_manifest.json").read_text())
        failures = (None, "destroy", "buffer", "free", "instance", "wait", "wait_result",
                    "close", "claim_release", "publication", "fsync", "outstanding_only", "prior_error")
        for failure in failures:
            path = root / f"{failure}.json"
            state = dict(kind="gpu", backend="python_vulkan_transfer", mode="gpu_3d",
                         suite_verification="transfer_readback", status="ok", error_count=0,
                         verification_passes=9, transfer_mismatch_count=0,
                         initial_verification_completed=True, final_verification_completed=True,
                         result_write_error_count=0, last_result_write_error="")
            if failure == "prior_error":
                state.update(status="error", error_count=1, last_error="earlier transfer failure")
            ledger = RuntimeMemoryClaims(); ledger.outstanding = 4096
            api = Mock(); api.vkDeviceWaitIdle.return_value = 0
            operation = {"destroy": "vkDestroyDevice", "buffer": "vkDestroyBuffer",
                         "free": "vkFreeMemory", "instance": "vkDestroyInstance", "wait": "vkDeviceWaitIdle"}.get(failure)
            if operation:
                getattr(api, operation).side_effect = RuntimeError("injected teardown failure")
            if failure == "wait_result":
                api.vkDeviceWaitIdle.return_value = -4
            if failure == "close":
                ledger.close = Mock(side_effect=OSError("injected close failure"))
            if failure == "outstanding_only":
                # A positive accounting balance alone is not a teardown error.
                ledger.close = Mock()
            callbacks = []
            env = dict(state=state, args=SimpleNamespace(result_file=str(path)),
                       device=1, instance=2, fence=3, command_pool=4,
                       staging_buffer=5, device_buffer=6, staging_memory=7, device_memory=8,
                       vk=api, memory_claims=ledger, check=worker.check,
                       json=json, os=os, sys=sys, callbacks=callbacks,
                       vulkan_failure_reason=worker.vulkan_failure_reason)
            exec(code, env)
            real_replace = os.replace
            replacements = []
            def replace(source, destination):
                replacements.append((source, destination))
                if failure == "publication" and len(replacements) == 2:
                    raise OSError("injected final replacement failure")
                return real_replace(source, destination)
            errors = io.StringIO()
            with patch("Modules.lvs_runtime_memory_guard.release_runtime_allocation_claim") as release, \
                    patch.object(worker.os, "replace", side_effect=replace), \
                    patch.object(worker.os, "fsync") as fsync, redirect_stderr(errors):
                if failure == "claim_release":
                    release.side_effect = OSError("injected accounting failure")
                if failure == "fsync":
                    fsync.side_effect = OSError("injected fsync failure")
                try:
                    exit_code = env["exercise"]()
                except SystemExit as exc:
                    exit_code = exc.code
                cleanup_bad = failure in {"destroy", "buffer", "free", "instance", "wait", "wait_result", "close", "claim_release"}
                publication_bad = failure in {"publication", "fsync"}
                assert exit_code == (13 if cleanup_bad or publication_bad else 0), failure
                assert state["cleanup_complete"] is (not cleanup_bad), failure
                assert bool(state["allocation_claim_cleanup_error"]) is cleanup_bad, failure
                assert ledger.outstanding == (4096 if cleanup_bad or failure == "outstanding_only" else 0), failure
                expected_releases = int(failure in {None, "publication", "fsync", "claim_release", "prior_error"})
                assert release.call_count == expected_releases, failure
                assert api.vkDestroyDevice.call_count == 1
                assert fsync.call_count == 1
                before_retry = json.loads(path.read_text())
                if publication_bad:
                    assert before_retry["status"] == "ok"  # prior intact snapshot, not terminal proof
                    assert state["status"] == "error" and state["result_write_error_count"] == 1
                    assert "publication failed" in errors.getvalue()
                    # A failed atexit attempt remains visibly unsuccessful and
                    # cannot destroy the last complete snapshot or free twice.
                    if failure == "publication":
                        env["os"].replace.side_effect = OSError("persistent publication failure")
                    assert callbacks[0]() is False
                    assert json.loads(path.read_text()) == before_retry
                    assert state["result_write_error_count"] == 2
                    env["os"].replace.side_effect = replace
                fsync.side_effect = None
                assert callbacks[0]() is True  # actual atexit publication retry
                assert release.call_count == expected_releases  # publication never repeats teardown
                assert api.vkDestroyDevice.call_count == 1
            payload = json.loads(path.read_text())
            assert payload["verification_passes"] == 9 and payload["transfer_mismatch_count"] == 0
            assert payload["initial_verification_completed"] and payload["final_verification_completed"]
            good = failure in {None, "outstanding_only"}
            assert worker_result_successful(payload) is good, failure
            compat = preserve_legacy_worker_evidence_contract(payload)
            detail = build_gpu_worker_validation_detail(stage_name="Transfer", stage_type="GPU",
                stage_verdict="pass", payload=compat, backend_name="python_vulkan_transfer", device_name="fixture")
            assert worker_result_successful(compat) is good
            assert worker_result_successful(detail) is good
            events = worker_result_events_from_payload(payload, "Transfer")
            if cleanup_bad:
                assert any(e["category"] == "worker_cleanup_incomplete" for e in events)
            manifest = deepcopy(original)
            manifest["stage_windows"][0]["worker_results"] = [payload]
            (run / "run_manifest.json").write_text(json.dumps(manifest))
            assert compile_report_data(run)["run"]["report_outcome"] == ("PASS" if good else "FAIL")
            assert ("Result: FAIL" in result_summary_text(run, SummaryTextBuilder())) is (not good)


def run_gpu_assignment_invariant_checks():
    cap=dict(memory_kind="shared",device_class="integrated",classification_source="explicit_shared",classification_confidence="high",
             gles_max_texture_object_bytes=16384**2*4)
    for backend in ("python_egl_gles2","python_opencl"):
        runner=Runner(cap)
        for target in (0,30198988,64*MIB-1,64*MIB,64*MIB+4096,24*GIB):
            stage,w=_annotate(runner,_spec(runner,backend,target),percent=0)
            plan=build_stage_system_memory_plan(stage=stage,gpu_workers=[w],total_bytes=64*GIB,available_bytes=50*GIB)
            assert plan["valid"] is (target>=64*MIB)
            assigned=apply_stage_system_memory_plan([w],plan)[0]
            assert assigned.target_vram_bytes==target
            if target<64*MIB:
                assert plan["infeasible_gpu_assignments"][0]["reason"]=="safe_assignment_below_backend_minimum"
                try: materialize_gpu_worker(runner,assigned)
                except ValueError as exc: assert "infeasible" in str(exc)
                else: raise AssertionError("undersized assignment was launched/enlarged")
            else:
                m=materialize_gpu_worker(runner,assigned)
                assert m.target_vram_bytes==target and f"TARGET_VRAM_BYTES = {target}" in m.command[2]
                if backend=="python_opencl":
                    tuned=retune_gpu_worker(runner,assigned);assert tuned.target_vram_bytes<=target
            assert cap_gpu_vram_target_bytes(requested_bytes=target,target_total=0,safe_mode_enabled=True,safe_max_vram_percent=90)<=target
        # Reconcile a small API-addressable request before execution, not by a runtime floor.
        small=replace(w,target_vram_bytes=30198988,requested_gpu_memory_target_bytes=30198988)
        small_plan=build_stage_system_memory_plan(stage=stage,gpu_workers=[small],total_bytes=GIB,available_bytes=768*MIB)
        assert not small_plan["valid"]
    for backend,minimum in (("python_vulkan_compute",8*MIB),("python_vulkan_transfer",16*MIB)):
        for target in (0,minimum-1,minimum):
            try: validate_gpu_assignment(backend,"gpu_3d",target)
            except ValueError: assert target<minimum
            else: assert target==minimum
    # Runtime module initialization rejects these before loading graphics APIs.
    for script in (build_egl_gles_workload_script("vram",30198988),build_opencl_vram_workload_script(30198988,"","","","","","",0,0)):
        tree=ast.parse(script)
        validation=next(n for n in tree.body if isinstance(n,(ast.If,ast.Expr)) and 'validate_gpu_assignment' in ast.unparse(n))
        env=dict(MODE="vram",TARGET_VRAM_BYTES=30198988,validate_gpu_assignment=validate_gpu_assignment)
        try: exec(compile(ast.Module(body=[validation],type_ignores=[]),"<actual-runtime-minimum>","exec"),env)
        except ValueError: pass
        else: raise AssertionError("runtime minimum was silently promoted")


def run_opencl_loop_completion_checks():
    now=[0.];t=OpenCLAllocationTiming({},monotonic=lambda:now[0],wall=lambda:1000.,cpu=lambda:0.)
    t.begin_loop();now[0]+=1;t.finish_loop(completed=True)
    t.begin_loop()
    try:
        with t.measure("blocking_readback"):
            now[0]+=2;raise RuntimeError("driver failure")
    except RuntimeError: pass
    finally: t.finish_loop()
    t.begin_loop();now[0]+=3;t.finish_loop(completed=False)  # cancellation
    t.begin_loop()
    try:
        with t.measure("result_persistence"):
            now[0]+=4;raise OSError("persistence failure")
    except OSError: pass
    finally: t.finish_loop()
    t.finish_loop()  # finally/atexit cannot count twice
    s=t.snapshot()
    assert s["attempted_loop_count"]==4 and s["completed_loop_count"]==1 and s["interrupted_loop_count"]==3
    assert s["completed_loop_seconds"]==1 and s["interrupted_loop_seconds"]==9
    assert s["observed_loop_seconds"]==10
    assert s["operations"]["blocking_readback"]["error_count"]==s["operations"]["result_persistence"]["error_count"]==1
    assert s["attempted_loop_count"]==s["completed_loop_count"]+s["interrupted_loop_count"]+int(s["loop_in_progress"])
    t.begin_loop();assert t.snapshot()["loop_in_progress"]
    for _ in range(80):
        with t.measure("create_buffer"): now[0]+=1
    t.finish_loop()
    assert len(t.snapshot()["slow_events"])==32 and t.snapshot()["slow_events_overwritten"]>0
    # Exercise the generated worker's completion decision, including caught
    # persistence errors (which do not escape write_result()).
    tree=ast.parse(build_opencl_vram_workload_script(128*MIB,"","","","","","",0,0))
    decision=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                  and n.func.attr=="finish_loop" and n.keywords)
    for running,errors,writes,complete in ((True,0,0,True),(False,0,0,False),(True,1,0,False),(True,0,1,False)):
        timing=OpenCLAllocationTiming({});timing.begin_loop()
        eval(compile(ast.Expression(decision),"<actual-loop-completion>","eval"),
             dict(timings=timing,running=running,loop_errors_before=(0,0),
                  state=dict(error_count=errors,result_write_error_count=writes)))
        assert timing.loops==int(complete) and timing.interrupted==int(not complete)
