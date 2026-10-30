"""CPU-only execution-geometry, emitted-worker and bounded-diagnostic checks."""
from __future__ import annotations

import ast
import ctypes
import io
import json
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import os

from Modules.lvs_gpu_allocation_geometry import egl_texture_geometry, opencl_buffer_geometry, opencl_buffer_count
from Modules.lvs_gpu_allocation_plan import plan_gpu_allocation_chunks, allocation_attainment
from Modules.lvs_gpu_worker_plan import GpuWorkerSpec, serialize_gpu_worker_spec
from Modules.lvs_system_memory_budget import build_stage_system_memory_plan, apply_stage_system_memory_plan
from Modules.lvs_profile_models import StageConfig, StageModules, ModuleMemory
from Modules.lvs_runtime_memory_guard import initialize_runtime_memory_guard, claim_runtime_allocation_growth
from Modules.lvs_egl_gles_worker import build_egl_gles_workload_script
from Modules.lvs_opencl_vram_worker import build_opencl_vram_workload_script
from Modules.lvs_opencl_allocation_timing import OpenCLAllocationTiming
from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
from Modules.lvs_report_data import compile_report_data
from Modules.lvs_report_html import _stage_card
from Modules.lvs_summary_text import SummaryTextBuilder
from smoke_tests.neon_fp32_fma_checks import _worker_export_round_trip

MIB, GIB = 1024**2, 1024**3


def run_gpu_allocation_geometry_checks():
    target = 26410707763  # Historical laptop assignment, not a model-specific policy.
    old = 512 * 2048**2 * 4
    assert old == 8*GIB and old/target < .60
    geometry = egl_texture_geometry(target, 2048, 16384)
    assert geometry["texture_side"] == 4096 and geometry["planned_object_count"] == 393
    assert geometry["planned_nominal_bytes"] <= target
    assert geometry["planned_nominal_bytes"]/target > .99
    small = egl_texture_geometry(target, 2048, 2048)
    assert small["status"] == "limited_by_software_object_budget"
    assert small["planned_nominal_bytes"] == old
    assert allocation_attainment(assigned_target_bytes=target, achieved_bytes=old)["allocation_valid"] is False
    for max_side in (256, 1024, 2048, 3072, 4096, 8192, 16384):
        for request in (64*MIB, 5*GIB, target, 256*GIB):
            geo = egl_texture_geometry(request, 2048, max_side)
            assert 0 < geo["texture_side"] <= max_side
            assert geo["planned_object_count"] <= 512
            assert geo["planned_nominal_bytes"] <= request
            assert geo["shortfall_bytes"] == request - geo["planned_nominal_bytes"]
    unknown = egl_texture_geometry(target, 2048, 0)
    assert unknown["status"] == "conditional_runtime_gl_query"
    assert unknown["physical_residency_established"] is False
    cl = opencl_buffer_geometry(int(78.91*GIB), 4294959104, "integrated", True)
    assert cl["object_bytes"] > 64*MIB and cl["max_allocation_count"] == 1024
    assert cl["planned_nominal_bytes"] >= int(78.91*GIB) - 4095
    limited = opencl_buffer_geometry(80*GIB, 64*MIB, "integrated", True)
    assert limited["backend_nominal_limit_bytes"] == 64*GIB
    assert limited["status"] == "limited_by_software_object_budget"
    odd = opencl_buffer_geometry(3*GIB + 123, 4*GIB, "integrated", True)
    assert odd["planned_nominal_bytes"] == 3*GIB and odd["shortfall_bytes"] == 123
    tiny = opencl_buffer_geometry(64*MIB, 2048, "integrated", True)
    assert tiny["planned_nominal_bytes"] == 0 and tiny["status"] == "limited_by_worker_allocation_granularity"
    # Small-target geometry stays unchanged; large targets may grow only with
    # a positive API limit and never beyond it or beyond bounded object counts.
    for safe in (True, False):
        for kind in ("discrete", "integrated", "unknown"):
            for target_bytes in (64*MIB, 128*MIB, 3*GIB, 80*GIB, 512*GIB):
                for maximum in (0, 16*MIB, 4294959104):
                    g = opencl_buffer_geometry(target_bytes, maximum, kind, safe)
                    cap = (128 if safe else 512)*MIB if kind == "discrete" else (64 if safe else 128)*MIB
                    chunk = min(maximum or target_bytes, cap, target_bytes)
                    chunk -= chunk % 4096
                    count = max(32, (target_bytes + chunk - 1)//chunk + 8)
                    count = min(2048, max(512, count)) if safe and kind == "discrete" else min(1024, max(128, count)) if safe else min(4096, count)
                    budget = 2048 if safe and kind == "discrete" else 1024 if safe else 4096
                    if target_bytes <= chunk * budget or not maximum:
                        assert (g["object_bytes"], g["max_allocation_count"]) == (chunk, count)
                    assert g["object_bytes"] <= (maximum or chunk)
                    assert g["object_bytes"] <= target_bytes and g["max_allocation_count"] <= budget
                    assert opencl_buffer_count(target_bytes, g["object_bytes"], kind, safe) == g["max_allocation_count"]
    spec = GpuWorkerSpec("vram", "python_egl_gles2", 0, "card0", "", "gpu0", [],
                         target_vram_bytes=target, texture_side=2048, max_buffer_or_object_bytes=16384**2*4,
                         max_allocation_count=512, gpu_memory_kind="shared", system_memory_budget_participation=True,
                         memory_budget_consumer_id="gpu0", minimum_viable_allocation_bytes=64*MIB)
    stage = StageConfig("segment_1", "Combined", 600, modules=StageModules(memory=ModuleMemory(enabled=True, allocation_percent=90)))
    # One pool and reserve, also for multiple consumers of the same device.
    for total, available in ((GIB, 768*MIB), (32*GIB, 28*GIB), (96*GIB, 90*GIB)):
        workers = [replace(spec, shared_addressable_capacity_bytes=12*GIB, backend_addressable_capacity_bytes=12*GIB),
                   replace(spec, memory_budget_consumer_id="gpu1", shared_addressable_capacity_bytes=12*GIB,
                           backend_addressable_capacity_bytes=12*GIB)]
        plan = build_stage_system_memory_plan(stage=stage, gpu_workers=workers, total_bytes=total, available_bytes=available)
        assert sum(plan["allocations"].values()) <= plan["system_memory_budget_bytes"]
        resolved = apply_stage_system_memory_plan(workers, plan)
        assert sum(w.target_vram_bytes for w in resolved) <= 12*GIB
        for w in resolved:
            assert sum(w.planned_allocation_chunks) <= w.target_vram_bytes
            assert sum(w.planned_allocation_chunks) == w.allocation_feasibility["planned_nominal_bytes"]
            assert serialize_gpu_worker_spec(w)["allocation_feasibility"] == w.allocation_feasibility
        with TemporaryDirectory() as tmp:
            guard = str(Path(tmp)/"guard.json")
            initialize_runtime_memory_guard(plan, guard)
            assert not claim_runtime_allocation_growth(total, shared_system_memory=True, control_path=guard)["allowed"]
    # Dedicated targets stay outside the shared pool; feasibility doesn't cap assignment.
    dedicated = replace(spec, system_memory_budget_participation=False, gpu_memory_kind="dedicated")
    assert apply_stage_system_memory_plan([dedicated], {})[0].target_vram_bytes == target
    impossible = plan_gpu_allocation_chunks(target_bytes=80*GIB, practical_chunk_bytes=64*MIB, max_allocation_count=1024)
    assert not impossible["complete"] and impossible["shortfall_bytes"] == 16*GIB
    unknown_spec = replace(spec, max_buffer_or_object_bytes=0, backend_addressable_capacity_bytes=0)
    assert apply_stage_system_memory_plan([unknown_spec], {})[0].allocation_feasibility["max_texture_size"] == 0


def run_egl_allocation_execution_checks():
    tree = ast.parse(build_egl_gles_workload_script("vram", 64*MIB))
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.While) and
                "len(textures) < desired_texture_count" in ast.unparse(n.test))
    def execute(errors, allowed=True, running=True):
        geometry = egl_texture_geometry(64*MIB, 2048, 4096)
        state = dict(bytes_per_texture=16*MIB, allocation_attempts=0, allocation_failures=0,
                     allocation_backoff_attempts=[], allocation_feasibility=geometry, target_texture_count=4)
        gl = Mock(); gl.glCheckFramebufferStatus.return_value = 1
        env = dict(running=running, textures=[], desired_texture_count=4, state=state, GLES=gl,
                   claim_runtime_allocation_growth=Mock(return_value={"allowed":allowed}),
                   release_runtime_allocation_claim=Mock(), DEVICE_CLASS="integrated", GLuint=ctypes.c_uint,
                   ctypes=ctypes, vram_framebuffer=1, drain_gl_errors=Mock(side_effect=errors),
                   tex_side=2048, bytes_per_texture=16*MIB, target=64*MIB, TARGET_VRAM_BYTES=64*MIB,
                   EGL_TEXTURE_OBJECT_BUDGET=512, load_fraction=1., record_gl_errors=Mock(),
                   phase=.7, vram_clear_color=lambda *_: (.25,.5,.75,1.), verify_vram_texture=Mock())
        env["ALLOCATION_SAFETY"] = {"device_memory_requires_system_guard": True}
        for key in ("GL_FRAMEBUFFER", "GL_FRAMEBUFFER_COMPLETE", "GL_TEXTURE_2D", "GL_TEXTURE_MIN_FILTER",
                    "GL_TEXTURE_MAG_FILTER", "GL_LINEAR", "GL_TEXTURE_WRAP_S", "GL_TEXTURE_WRAP_T",
                    "GL_CLAMP_TO_EDGE", "GL_RGBA", "GL_UNSIGNED_BYTE", "GL_COLOR_ATTACHMENT0", "GL_COLOR_BUFFER_BIT"):
            env[key] = 1
        exec(compile(ast.Module(body=[loop], type_ignores=[]), "<actual-egl-allocation-loop>", "exec"), env)
        return env
    success = execute([[]]*4)
    assert success["state"]["allocated_vram_bytes"] == 64*MIB
    assert [call.args[2] for call in success["verify_vram_texture"].call_args_list] == [0,1,2,3]
    denied = execute([], allowed=False)
    assert denied["state"]["runtime_memory_guard_triggered"] and not denied["textures"]
    cancelled = execute([], running=False)
    assert not cancelled["textures"] and not cancelled["claim_runtime_allocation_growth"].called
    assert not cancelled["verify_vram_texture"].called
    # First allocation fails, releases claim, halves geometry and then succeeds.
    backed = execute([[1285]] + [[]]*16)
    assert backed["state"]["allocation_failures"] == 1
    assert backed["state"]["bytes_per_texture"] == 4*MIB
    assert len(backed["textures"]) == 16 and backed["release_runtime_allocation_claim"].call_count == 1
    failed = execute([[1285]]*4)
    assert failed["state"]["allocation_exhausted"] and not failed["textures"]


def run_opencl_allocation_diagnostic_checks():
    class Clock:
        value = 10.
        def __call__(self): return self.value
    clock = Clock()
    timing = OpenCLAllocationTiming({"target_id":"gpu0"}, monotonic=clock, wall=lambda:1000., cpu=lambda:0.)
    timing.begin_loop()
    for i in range(100):
        with timing.measure("create_buffer"):
            clock.value += 1.
    clock.value += 2.
    timing.finish_loop()
    snapshot = timing.snapshot()
    assert snapshot["operations"]["create_buffer"]["count"] == 100
    assert snapshot["operations"]["create_buffer"]["elapsed_seconds"] == 100.
    assert snapshot["unaccounted_loop_seconds"] == 2.
    assert len(snapshot["slow_events"]) == 32 and snapshot["slow_events_overwritten"] == 68
    assert snapshot["slow_events"][0]["start_unix_seconds"] == 1068.
    try:
        with timing.measure("blocking_readback"):
            raise RuntimeError("driver error fixture")
    except RuntimeError:
        pass
    assert timing.snapshot()["operations"]["blocking_readback"]["error_count"] == 1
    tree = ast.parse(build_opencl_vram_workload_script(80*GIB,"","","","","","gpu0",0,0))
    compile(tree, "<emitted-opencl>", "exec")
    names = {n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and
             isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and
             n.func.value.id == "timings" and n.func.attr in {"call", "measure"}}
    assert names == OpenCLAllocationTiming.OPERATIONS - {"blocking_readback"}  # Historical timing key remains readable.
    # Execute real generated persistence functions without loading OpenCL.
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"write_result","terminal_result"}]
    with TemporaryDirectory() as tmp:
        path = Path(tmp)/"worker.json"
        from Modules.lvs_runtime_memory_guard import RuntimeMemoryClaims
        env = dict(state={}, RESULT_FILE=str(path), timings=timing, os=os, json=json,
                   memory_claims=RuntimeMemoryClaims(), sys=__import__('sys'),
                   time=SimpleNamespace(monotonic=clock),last_result_write_monotonic=None)
        exec(compile(ast.Module(body=funcs, type_ignores=[]), "<actual-opencl-persistence>", "exec"), env)
        env["write_result"]()
        assert json.loads(path.read_text())["allocation_timing_evidence"]["slow_events_overwritten"] == 68
        stderr = io.StringIO()
        with redirect_stderr(stderr): env["terminal_result"]()
        terminal = json.loads(stderr.getvalue().split("LVS_OPENCL_ALLOCATION_TIMING ")[1])
        assert terminal["operations"]["result_persistence"]["count"] == 2
        env["RESULT_FILE"] = str(Path(tmp)/"missing"/"worker.json")
        env["write_result"]()
        assert env["state"]["result_write_error_count"] == 1
        assert timing.snapshot()["operations"]["result_persistence"]["error_count"] == 1
    worker = dict(kind="gpu", mode="vram", backend="python_opencl", status="ok", error_count=0,
                  vram_mismatch_count=0, verification_required=True, verification_passes=724,
                  verification_satisfied=True, suite_verification="memory_readback", target_id="gpu0", gpu_index=0,
                  target_vram_bytes=int(78.91*GIB), allocated_vram_bytes=18*GIB, allocation_valid=False,
                  allocation_feasibility=opencl_buffer_geometry(80*GIB,64*MIB,"integrated",True),
                  allocation_timing_evidence=snapshot, allocation_progress_evidence=dict(contract="opencl_allocation_progress_v1",
                      loop_iterations=288, successful_objects=288, api_allocation_failure_count=0,
                      object_count_limit_reached=False, runtime_guard_intervened=False))
    preserved = preserve_legacy_worker_evidence_contract(worker)
    assert preserved["allocation_timing_evidence"] == snapshot
    assert preserved["allocation_feasibility"] == worker["allocation_feasibility"]
    assert allocation_attainment(assigned_target_bytes=worker["target_vram_bytes"], achieved_bytes=18*GIB)["allocation_valid"] is False
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        exported = _worker_export_round_trip(worker, root, legacy_projection=True)
        detail = exported["GpuDetails"]["validation_details"][0]
        assert detail["AllocationTimingEvidence"] == snapshot
        assert detail["AllocationProgressEvidence"]["loop_iterations"] == 288
        assert detail["AllocationFeasibility"] == worker["allocation_feasibility"]
        assert exported["Segments"][0]["WorkerResults"][0]["allocation_timing_evidence"] == snapshot
        report = compile_report_data(root)
        assert report["stages"][0]["gpu_vram_allocation_evidence"][0]["allocation_timing_evidence"] == snapshot
        assert "limited_by_software_object_budget" in _stage_card(report["stages"][0], {})
        assert "limited_by_software_object_budget" in SummaryTextBuilder().build(exported)
    legacy = {"kind":"gpu", "backend":"python_opencl", "verification_passes":1}
    assert "allocation_timing_evidence" not in preserve_legacy_worker_evidence_contract(legacy)


def run_opencl_growth_scheduling_checks():
    """Execute the emitted refill block, preserving synchronization and readback."""
    tree = ast.parse(build_opencl_vram_workload_script(80*GIB,"","","","","","gpu0",0,0))
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.While) and ast.unparse(n.test) == "running")
    start = next(i for i,n in enumerate(loop.body) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "fill_count")
    end = next(i for i,n in enumerate(loop.body[start:], start) if isinstance(n, ast.If) and "last_verify_monotonic" in ast.unparse(n.test))
    # Exclude only the second clock read; the real enqueue/finish block executes.
    body = loop.body[start:end]
    fill_function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fill_buffer_count")
    for kind in ("integrated", "discrete", "unknown"):
        for count in (1, 24, 1024):
            for grew in (0, 1):
                timing = OpenCLAllocationTiming({})
                enqueue = Mock()
                cl = Mock(); cl.clFinish.return_value = 0
                env = dict(allocations_this_frame=grew, buffers=[None]*count, state={"frames":0},
                           load_fraction=1., phase_name="verify", DEVICE_CLASS=kind, SAFE_MODE_ENABLED=True,
                           TARGET_VRAM_TOTAL=80*GIB, TARGET_VRAM_BYTES=80*GIB,
                           now_monotonic=10., last_fill_monotonic=0., fill_interval_seconds=0.,
                           timings=timing, enqueue_fill=enqueue, cl=cl, queue=1,
                           check=lambda code, _: (_ for _ in ()).throw(RuntimeError()) if code else None,
                           time=SimpleNamespace(monotonic=lambda:10.))
                exec(compile(ast.Module(body=[fill_function, *body], type_ignores=[]), "<actual-opencl-refill>", "exec"), env)
                if grew:
                    assert not enqueue.called and not cl.clFinish.called
                    assert env["state"]["active_fill_buffer_count"] == 0
                else:
                    assert 0 < enqueue.call_count <= min(count,24)
                    cl.clFinish.assert_called_once_with(1)
                assert env["state"]["allocation_initialization_replaced_refill"] == bool(grew)
    # Verification still executes after the completed initial touch and retains
    # its original interval and 0/mid/end samples. No additional allocation batch.
    allocation = next(n for n in loop.body if isinstance(n, ast.While))
    assert "allocations_this_frame < allocation_budget" in ast.unparse(allocation.test)
    touch = next(i for i,n in enumerate(allocation.body) if "allocation_touch_finish" in ast.unparse(n))
    assert "clFinish" in ast.unparse(allocation.body[touch])
    verify = loop.body[end]
    assert "verify_interval_seconds" in ast.unparse(verify.test)
    assert "len(buffers) // 2" in ast.unparse(verify) and "verify_buffer_samples(verify_indices)" in ast.unparse(verify)
    # Run the real growth loop using fake API calls: exactly one bounded object,
    # initial GPU write and completion, guard denial, and cancellation in finish.
    for allowed, cancel in ((True,False), (False,False), (True,True)):
        geo = opencl_buffer_geometry(80*GIB,4*GIB,"integrated",True)
        size = geo["object_bytes"]
        cl = Mock(); cl.clCreateBuffer.return_value = 123
        timing = OpenCLAllocationTiming({})
        state = dict(allocation_exhausted=False, allocated_vram_bytes=0, allocation_attempts=0,
                     allocation_failures=0, frames=0, allocation_touch_count=0)
        env = dict(running=True, state=state, buffers=[], buffer_last_seed=[], buffer_has_data=[],
                   desired_target_bytes=80*GIB, runtime_target_bytes=80*GIB, chunk_bytes=size,
                   max_buffer_count=1024, allocations_this_frame=0, allocation_budget=1,
                   claim_runtime_allocation_growth=Mock(return_value={"allowed":allowed}),
                   ALLOCATION_SAFETY={"device_memory_requires_system_guard":True},
                   release_runtime_allocation_claim=Mock(), timings=timing, cl=cl, context=1,
                   CL_MEM_READ_WRITE=1, err=ctypes.c_int(0), CL_SUCCESS=0, cl_mem=int,
                   ctypes=ctypes, enqueue_fill=Mock(), queue=1, check=Mock(), write_result=Mock(),
                   time=SimpleNamespace(monotonic=lambda:10.))
        def finish(_):
            if cancel: env["running"] = False
            return 0
        cl.clFinish.side_effect = finish
        exec(compile(ast.Module(body=[allocation], type_ignores=[]), "<actual-opencl-growth>", "exec"), env)
        env["claim_runtime_allocation_growth"].assert_called_once_with(size, shared_system_memory=True)
        if allowed:
            assert state["allocated_vram_bytes"] == size <= 80*GIB
            assert len(env["buffers"]) == 1 and env["allocations_this_frame"] == 1
            env["enqueue_fill"].assert_called_once()
            cl.clFinish.assert_called_once()
            assert state["allocation_touch_count"] == 1
            assert env["running"] is not cancel
        else:
            assert state["runtime_memory_guard_triggered"] and state["allocation_exhausted"]
            assert state["allocated_vram_bytes"] == 0 and not cl.clCreateBuffer.called
    for safe in (False, True):
        for kind in ("discrete", "integrated", "unknown"):
            for maximum in (0, 32*MIB, 4*GIB):
                g = opencl_buffer_geometry(80*GIB, maximum, kind, safe)
                assert g["planned_nominal_bytes"] <= 80*GIB
                assert g["max_allocation_count"] <= (2048 if safe and kind=="discrete" else 1024 if safe else 4096)
                if maximum: assert g["object_bytes"] <= maximum
                if maximum == 4*GIB: assert g["shortfall_bytes"] == 0
