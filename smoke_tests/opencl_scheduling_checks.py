"""Execute emitted OpenCL scheduling with a deferred fake queue, never a GPU."""
from __future__ import annotations

import ast
import ctypes
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Modules.lvs_opencl_vram_worker import build_opencl_vram_workload_script
from Modules.lvs_opencl_allocation_timing import OpenCLAllocationTiming
from Modules.lvs_gpu_allocation_geometry import OPENCL_READBACK_STAGING_LIMIT_BYTES


def _tree():
    return ast.parse(build_opencl_vram_workload_script(2**30, "", "", "", "", "", "gpu", 0, 0))


def _functions(tree, names):
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    return compile(ast.Module(body=nodes, type_ignores=[]), "<emitted-opencl-functions>", "exec")


def _batch_fixture(failure="", corrupt=None, words=16):
    state = dict(readback_pending=False, readback_enqueued_sample_count=0, readback_batch_count=0,
                 error_count=0, vram_mismatch_count=0, verification_passes=0, verification_satisfied=False)
    env = dict(state=state, running=True, readback_events=[], timings=OpenCLAllocationTiming({}),
               buffers=[(100+i, 4*words) for i in range(9)], buffer_has_data=[True]*9,
               buffer_last_seed=[71+i for i in range(9)], sample_words=words,
               sample_array=(ctypes.c_uint * (3*words))(), ctypes=ctypes, queue=1,
               cl_int=ctypes.c_int, cl_event=ctypes.c_void_p, CL_SUCCESS=0, CL_COMPLETE=0,
               CL_FALSE=0, CL_EVENT_COMMAND_EXECUTION_STATUS=0x11D3)
    exec(_functions(_tree(), {"check", "record_error", "pattern_value", "drain_readbacks",
                              "release_readback_events", "verify_buffer_samples"}), env)
    pending, events, order = [], {}, []
    def enqueue(queue, handle, blocking, offset, size, pointer, wait_count, waits, event):
        order.append("enqueue")
        assert blocking == 0 and offset == 0 and wait_count == 0
        assert state["verification_passes"] == 0 or not pending
        index = handle-100
        if failure == "enqueue" and index == 4: return -5
        identity = index+1
        event._obj.value = None if failure == "missing_event" else identity
        events[identity] = 3
        pending.append((index, size, pointer, identity))
        if failure == "cancel": env["running"] = False
        return 0
    def finish(queue):
        order.append("finish")
        if failure == "finish": return -5
        for index, size, pointer, identity in pending:
            target = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint))
            for word in range(size//4):
                target[word] = env["pattern_value"](word, env["buffer_last_seed"][index], index)
                if corrupt == (index, word): target[word] ^= 1
            events[identity] = -14 if failure == "async_error" else 1 if failure == "pending" else 0
        pending.clear()
        return 0
    def status(event, field, size, pointer, returned_size):
        order.append("status")
        if failure == "event_query": return -30
        pointer._obj.value = events[event.value]
        return 0
    cl = SimpleNamespace(clEnqueueReadBuffer=Mock(side_effect=enqueue), clFinish=Mock(side_effect=finish),
                         clGetEventInfo=Mock(side_effect=status), clReleaseEvent=Mock(return_value=-5 if failure=="release" else 0))
    env.update(cl=cl, order=order)
    return env


def run_opencl_readback_batch_checks():
    for words in (16, 1024):
        for indices in ([0], [0,4,8]):
            env = _batch_fixture(words=words)
            env["verify_buffer_samples"](indices)
            assert env["state"]["verification_passes"] == len(indices)
            assert env["state"]["verification_satisfied"]
            assert env["order"] == ["enqueue"]*len(indices) + ["finish"] + ["status"]*len(indices)
            assert env["cl"].clReleaseEvent.call_count == len(indices)
            assert not env["readback_events"] and not env["state"]["readback_pending"]
            assert ctypes.sizeof(env["sample_array"]) <= OPENCL_READBACK_STAGING_LIMIT_BYTES
    for index in (0,4,8):
        for word in (0,15):
            env = _batch_fixture(corrupt=(index,word))
            env["verify_buffer_samples"]([0,4,8])
            assert env["state"]["vram_mismatch_count"] == 1
            assert env["state"]["error_count"] == 1 and not env["state"]["verification_satisfied"]
            assert f"buffer {index} word {word}" in env["state"]["last_error"]
    for failure in ("enqueue", "missing_event", "finish", "async_error", "pending", "event_query"):
        env = _batch_fixture(failure)
        try: env["verify_buffer_samples"]([0,4,8])
        except RuntimeError: pass
        else: raise AssertionError(f"failed readback accepted: {failure}")
        assert env["state"]["verification_passes"] == 0
        assert not env["state"]["verification_satisfied"]
        if failure in {"finish", "pending", "event_query"}:
            assert env["state"]["readback_pending"] and env["readback_events"]
            assert not env["cl"].clReleaseEvent.called
            assert not env["drain_readbacks"]()
            # Execute actual cleanup: unconfirmed DMA must retain host claims.
            final = next(n.finalbody for n in _tree().body if isinstance(n, ast.Try) and n.finalbody)
            start = next(i for i,n in enumerate(final) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "cleanup_ok")
            for key in ("clReleaseMemObject", "clReleaseKernel", "clReleaseProgram", "clReleaseCommandQueue", "clReleaseContext"):
                setattr(env["cl"],key,Mock(return_value=0))
            env.update(context=1, program=1, kernel=1, memory_claims=SimpleNamespace(close=Mock(), cleanup_error=""))
            exec(compile(ast.Module(body=final[start:],type_ignores=[]),"<emitted-cleanup>","exec"),env)
            assert not env["memory_claims"].close.called and env["memory_claims"].cleanup_error
        else:
            assert not env["state"]["readback_pending"]
            assert not env["readback_events"]
    for failure in ("cancel", "release"):
        env = _batch_fixture(failure)
        env["verify_buffer_samples"]([0,4,8])
        assert not env["running"] and not env["state"]["readback_pending"]
        if failure == "release":
            assert env["readback_events"] and not env["state"]["verification_satisfied"]
    env = _batch_fixture()
    for indices in ([], [0,0], [0,1,2,3], [9]):
        try: env["verify_buffer_samples"](indices)
        except RuntimeError: pass
        else: raise AssertionError("invalid batch accepted")
    env["buffer_has_data"][4] = False
    try: env["verify_buffer_samples"]([0,4,8])
    except RuntimeError: pass
    else: raise AssertionError("uninitialized buffer accepted")
    assert not env["cl"].clEnqueueReadBuffer.called
    # Reuse one fixed pool; no pending work survives between successful batches.
    env = _batch_fixture()
    identity = id(env["sample_array"])
    for _ in range(40): env["verify_buffer_samples"]([0])
    assert id(env["sample_array"]) == identity and not env["readback_events"]
    assert env["state"]["verification_passes"] == 40


def run_opencl_publication_and_staging_checks():
    from smoke_tests.gpu_allocation_safety_checks import Runner, _annotate, _spec
    from Modules.lvs_system_memory_budget import build_stage_system_memory_plan, apply_stage_system_memory_plan
    from Modules.lvs_runtime_memory_guard import initialize_runtime_memory_guard, RuntimeMemoryClaims
    from Modules.lvs_gpu_worker_materializer import materialize_gpu_worker
    tree = _tree()
    with TemporaryDirectory() as tmp:
        root = Path(tmp); now=[0.]
        timing=OpenCLAllocationTiming({},monotonic=lambda:now[0], wall=lambda:1000.,cpu=lambda:0.)
        env=dict(RESULT_FILE=str(root/"worker.json"), state={}, timings=timing, os=os, json=json,
                 time=SimpleNamespace(monotonic=lambda:now[0]), memory_claims=RuntimeMemoryClaims(),
                 last_result_write_monotonic=None)
        exec(_functions(tree,{"write_result"}),env)
        env["write_result"]()
        for _ in range(100): env["write_result"](force=False)
        assert env["state"]["result_write_count"]==1
        now[0]=2.; env["write_result"](force=False)
        assert env["state"]["result_write_count"]==2
        # Error and final evidence are forced even when no time has elapsed.
        env["state"]["last_error"]="fixture error"; env["write_result"]()
        assert json.loads((root/"worker.json").read_text())["last_error"]=="fixture error"
        with patch("os.replace",side_effect=OSError("replace failed")):
            env["write_result"]()
        assert env["state"]["result_write_error_count"]==1
        assert json.loads((root/"worker.json").read_text())["last_error"]=="fixture error"
        with patch("os.fsync",side_effect=OSError("fsync failed")):
            env["write_result"]()
        assert env["state"]["result_fsync_error_count"]==1
        for kind in ("shared","unknown","dedicated"):
            cap=dict(memory_kind=kind,device_class="discrete",classification_source="independent_provider",
                     classification_confidence="high",dedicated_vram_capacity_bytes=8*2**30 if kind=="dedicated" else 0,
                     opencl_global_memory_bytes=8*2**30,opencl_max_single_allocation_bytes=256*2**20)
            runner=Runner(cap);stage,worker=_annotate(runner,_spec(runner,"python_opencl"))
            assert worker.system_memory_fixed_commitment_bytes==OPENCL_READBACK_STAGING_LIMIT_BYTES
            plan=build_stage_system_memory_plan(stage=stage,gpu_workers=[worker],total_bytes=4*2**30,available_bytes=3*2**30)
            assert plan["valid"],plan
            assigned=apply_stage_system_memory_plan([worker],plan)[0]
            materialized=materialize_gpu_worker(runner,assigned)
            assert materialized.allocation_safety["device_memory_requires_system_guard"] is (kind!="dedicated")
            if kind=="dedicated":
                assert list(plan["allocations"].values())==[OPENCL_READBACK_STAGING_LIMIT_BYTES]
                assert materialized.target_vram_bytes==worker.target_vram_bytes
            guard=root/"guard.json"; initialize_runtime_memory_guard(plan,guard)
            assert json.loads(guard.read_text())["enabled"]
            with patch.dict(os.environ,{"LVS_RUNTIME_MEMORY_GUARD_PATH":str(guard)}):
                ledger=RuntimeMemoryClaims()
                # Execute the real runtime staging allocation, including its
                # mandatory host claim, even when device bytes are dedicated.
                body=next(n.body for n in tree.body if isinstance(n,ast.Try) and n.finalbody)
                first=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=="staging_bytes")
                last=next(i for i,n in enumerate(body[first:],first) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=="started_monotonic")
                staging=compile(ast.Module(body=body[first:last],type_ignores=[]),"<emitted-host-staging>","exec")
                runtime=dict(sample_words=1024, OPENCL_READBACK_STAGING_LIMIT_BYTES=OPENCL_READBACK_STAGING_LIMIT_BYTES,
                             claim_runtime_allocation_growth=ledger.claim, ctypes=ctypes,cl_uint=ctypes.c_uint,state={})
                exec(staging,runtime)
                assert ledger.outstanding==OPENCL_READBACK_STAGING_LIMIT_BYTES
                assert ctypes.sizeof(runtime["sample_array"])==OPENCL_READBACK_STAGING_LIMIT_BYTES
                ledger.close()
                assert json.loads(guard.read_text())["total_runtime_growth_claimed_bytes"]==0
                state=json.loads(guard.read_text()); state.update(stage_termination_required=True,runtime_growth_allowance_bytes=0)
                guard.write_text(json.dumps(state))
                runtime.pop("sample_array")
                try:exec(staging,runtime)
                except RuntimeError:pass
                else:raise AssertionError("zero-allowance staging claim bypassed")
                assert "sample_array" not in runtime and runtime["state"]["runtime_memory_guard_triggered"]
    # Actual queue creation stays in-order; final and recovery writes stay forced.
    creation=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="clCreateCommandQueue")
    assert ast.literal_eval(creation.args[2])==0
    loop=next(n for n in ast.walk(tree) if isinstance(n,ast.While) and ast.unparse(n.test)=="running")
    publication=[n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=="write_result"]
    assert len(publication)==1
    decision=publication[0].value.keywords[0].value
    for before,after,forced in ((0,0,False),(0,1,True),(1,1,False)):
        assert eval(compile(ast.Expression(decision),"<publication-decision>","eval"),
                    dict(state={"error_count":after},loop_errors_before=(before,0))) is forced
