"""Deterministic diagnostic clocks, journal, persistence and real command ABI."""
import ast
import ctypes
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys

from Modules import lvs_vulkan_dispatch_timing as d
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'native'))
import vulkan_compute_worker as w


def run_vulkan_dispatch_timing_checks():
    assert d.timestamp_seconds(250, 5, 1, 8) == 11e-9
    geometry = [dict(buffer_index=i, logical_words=100, groups=[1,1,1]) for i in range(9)]
    ticks = [100, 1000] + [v for i in range(9) for v in (100+100*i, 190+100*i)]
    decoded = d.decode_cycle(ticks, geometry, 1, 64, .01)
    assert len(decoded['dispatches']) == 9
    assert abs(sum(r['gpu_compute_stage_seconds'] for r in decoded['dispatches']) - 810e-9) < 1e-18
    for values, period, bits, host in ((ticks[:-1],1,64,.01), (ticks,float('nan'),64,.01),
                                      (ticks,1,0,.01), (ticks,1,8,1), (ticks,1,64,-1)):
        try: d.decode_cycle(values, geometry, period, bits, host)
        except (ValueError, TypeError): pass
        else: raise AssertionError('invalid timestamp observation accepted')

    with TemporaryDirectory(dir=ROOT) as tmp:
        path=Path(tmp)/'worker.json';state={};diag=d.DispatchTimingDiagnostic(state,path,'0000:07:00.0')
        for cycle in range(1,70):
            diag.record(cycle,ticks,geometry,1,64,.01,.009)
        assert len(diag.evidence['records']) == 64 and diag.evidence['overwritten_records'] == 5
        # Actual bounded atomic writer retains prior timing if a later write fails.
        d._write_json_atomic(path,state);before=path.read_bytes()
        with patch.object(d.os,'replace',side_effect=OSError('persistence failure')):
            try: d._write_json_atomic(path,{'broken':True})
            except OSError: pass
            else: raise AssertionError('failed publication hidden')
        assert path.read_bytes()==before
        api=Mock();api.vkWaitForFences.side_effect=[2,2,0]
        assert diag.wait(api,1,[2]) == 0 and api.vkWaitForFences.call_count == 3
        assert api.vkWaitForFences.call_args.args[-1] == 50_000_000
        api.vkWaitForFences.return_value=-4;api.vkWaitForFences.side_effect=None
        try:diag.wait(api,1,[2])
        except RuntimeError as exc: assert 'API error' in str(exc)
        else:raise AssertionError('API failure credited')
        event={'_TRANSPORT':'kernel','MESSAGE':'amdgpu 0000:07:00.0: ring comp_1.1.0 timeout'}
        assert diag.kernel_fault(event)
        assert not diag.kernel_fault(dict(event,MESSAGE='amdgpu 0000:08:00.0: reset'))
        assert not diag.kernel_fault(dict(event,_TRANSPORT='stdout'))
        with patch.object(d.threading,'Timer') as timer:
            diag.stop('amdgpu_kernel_fault',event)
            assert timer.call_args.args[0] == 5
            stop=json.loads(Path(str(path)+'.diagnostic-stop.json').read_text())
            assert stop['cleanup_complete'] is None
            try:diag.check()
            except RuntimeError:pass
            else:raise AssertionError('reset not blocking')
            previous=list(diag.evidence['records'])
            try:diag.record(70,ticks,geometry,1,64,.01,.009)
            except RuntimeError:pass
            else:raise AssertionError('post-reset measurement credited')
            assert diag.evidence['records']==previous
            diag.close();assert timer.return_value.cancel.called
        diag=d.DispatchTimingDiagnostic({},path,'0000:07:00.0');api.vkWaitForFences.return_value=2
        with patch.object(d.time,'monotonic',side_effect=[0,11]),patch.object(d.threading,'Timer'):
            try:diag.wait(api,1,[2])
            except RuntimeError:pass
            else:raise AssertionError('fence deadline ignored')
            assert diag.stop_reason=='fence_deadline'
            diag.close()
        with patch.object(d.subprocess,'run',return_value=SimpleNamespace(stdout=b'')):
            try:d.read_kernel_cursor()
            except ValueError:pass
            else:raise AssertionError('missing kernel evidence accepted')
        # Force-kill fallback never reports cleanup and never kills after close.
        diag=d.DispatchTimingDiagnostic({},path,'0000:07:00.0')
        diag.kernel=Mock()
        with patch.object(d.os,'_exit') as terminate:
            diag._hard_stop();terminate.assert_called_once_with(124)
            diag.kernel.kill.assert_called_once()
            diag.close();diag._hard_stop();assert terminate.call_count==1

    with TemporaryDirectory(dir=ROOT) as tmp:
        path=Path(tmp)/"worker.json"
        diag=d.DispatchTimingDiagnostic({},path,"0000:07:00.0")
        event={"_TRANSPORT":"kernel", "MESSAGE":"amdgpu 0000:07:00.0: ring timeout"}
        diag.kernel=Mock();diag.kernel.poll.return_value=None
        selector=Mock();selector.select.return_value=[(None,None)]
        context=Mock();context.__enter__=Mock(return_value=selector);context.__exit__=Mock(return_value=False)
        with patch.object(d.selectors,"DefaultSelector",return_value=context), \
             patch.object(d.os,"read",return_value=json.dumps(event).encode()+b"\n"), \
             patch.object(d.threading,"Timer"):
            diag._monitor()
            assert diag.stop_reason=="amdgpu_kernel_fault"
            diag.close();diag.kernel.terminate.assert_called_once()
        # Unsupported journal access blocks before a follow process is created.
        diag=d.DispatchTimingDiagnostic({},path,"0000:07:00.0")
        with patch.object(d,"read_kernel_cursor",side_effect=RuntimeError("journal unavailable")), \
             patch.object(d.subprocess,"Popen") as launch:
            try:diag.start()
            except RuntimeError:pass
            else:raise AssertionError("unobservable kernel accepted")
            launch.assert_not_called()
        with patch.object(d.subprocess,"run",return_value=SimpleNamespace(stdout=json.dumps(
            {"_TRANSPORT":"kernel", "_BOOT_ID":"abc", "__CURSOR":"cursor"}).encode())), \
             patch.object(d.Path,"read_text",return_value="abc"):
            assert d.read_kernel_cursor()=="cursor"

    tree=ast.parse((ROOT/'native/vulkan_compute_worker.py').read_text())
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    loop=next(n for n in ast.walk(main) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple)
              and any(isinstance(c,ast.Attribute) and c.attr=='vkCmdDispatch' for c in ast.walk(n)))
    # Execute the real production recording loop, rather than a parallel mock
    # algorithm. GPU work/descriptor arguments remain identical when opted in.
    for diagnostic in (None,object()):
        api=Mock();env=dict(vars(w));env.update(vk=api,dispatch_diagnostic=diagnostic,
            active_infos=[({'buffer':i+1,'size':3221225472},100*4,100,(1,1,1)) for i in range(9)],
            command_buffer=1,pipeline_layout=2,query_pool=3,verify_buffer_index=-1,kernel_variant="stateful_memory",
            submission_infos=[(i, ({"buffer":i+1,"size":3221225472},400,100,(1,1,1))) for i in range(9)],
            sample_words=256,descriptor_sets_by_buffer=[(ctypes.c_void_p*1)(i+10) for i in range(9)],
            dispatches_per_buffer=1)
        exec(compile(ast.Module(body=[loop],type_ignores=[]),'<actual-dispatch-recording>','exec'),env)
        assert api.vkCmdDispatch.call_count==9
        assert api.vkCmdWriteTimestamp.call_count == (18 if diagnostic else 0)
        if diagnostic:
            assert [c.args[-1] for c in api.vkCmdWriteTimestamp.call_args_list] == list(range(2,20))
    # Capability rejection and query-count selection execute the actual branch.
    assignment=next(n for n in ast.walk(main) if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='query_count' for t in n.targets))
    branch=next(n for n in ast.walk(main) if isinstance(n,ast.If)
                and 'requires supported compute timestamps' in ast.unparse(n))
    for bits,period,functions,capable,count in ((64,1,True,True,9),(0,1,True,True,9),
        (64,0,True,True,9),(64,1,False,True,9),(64,1,True,False,9),(64,1,True,True,65)):
        env=dict(dispatch_diagnostic=SimpleNamespace(evidence={}),buffer_records=[{}]*count,MAX_DISPATCHES=64,
            timestamp_valid_bits=bits,timestamp_period_ns=period,timestamp_functions_available=functions,
            timestamp_compute_supported=capable,math=__import__('math'))
        try:exec(compile(ast.Module(body=[assignment,branch],type_ignores=[]),'<actual-capability-check>','exec'),env)
        except RuntimeError:assert (bits,period,functions,capable,count)!=(64,1,True,True,9)
        else:assert env['query_count']==20 and (bits,period,functions,capable,count)==(64,1,True,True,9)
