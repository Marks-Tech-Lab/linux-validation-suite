"""Software-only execution of diagnostic shader and host ABI; no GPU calls."""
import ctypes as C
import ctypes.util
import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT/"native") not in sys.path:
    sys.path.insert(0, str(ROOT/"native"))
import vulkan_bounds_diagnostic as d


def emulate(blob, local, logical, large_length, small_length):
    """Execute the emitted diagnostic AND retained production arithmetic."""
    _, ops = d.instructions(blob)
    bindings = {a[0]: a[2] for op, a in ops if op == 71 and a[1] == 33}
    builtins = {a[0]: a[2] for op, a in ops if op == 71 and a[1] == 11}
    labels = {a[0]: i for i,(op,a) in enumerate(ops) if op == 248}
    output = [0xCDCDCDCD]*(d.OUTPUT_BYTES//4)
    data = {}
    for invocation in range(local):
        values = {}
        for i,(op,a) in enumerate(ops):
            if op == 43: values[a[1]] = a[2]
            if op == 59:
                values[a[1]] = ("input", builtins[a[1]]) if a[2] == 1 else (
                    ("buffer", bindings[a[1]]) if a[2] == 2 else ("push",))
            if op == 54: pc = i+1; break
        while True:
            op,a = ops[pc]; pc += 1
            if op in (248,247): continue
            if op == 253: break
            if op == 249: pc = labels[a[0]]; continue
            if op == 250: pc = labels[a[1] if values[a[0]] else a[2]]; continue
            if op == 61:
                ptr = values[a[2]]
                if ptr[0] == "input": value = (invocation,0,0) if ptr[1] == 28 else (1,1,1)
                elif ptr[0] == "push": value = logical
                else:
                    assert ptr[1] in (0,1)
                    value = data.get(ptr[2],0)
                values[a[1]] = value
            elif op == 81: values[a[1]] = values[a[2]][a[3]]
            elif op == 65:
                base = values[a[2]]
                assert values[a[3]] in ((0, 1) if base[0] == "push" else (0,))
                if base[0] == "push": values[a[1]] = ("push",)
                else:
                    index = values[a[4]]
                    size = [d.LARGE_BYTES//4,d.SMALL_BYTES//4,d.OUTPUT_BYTES//4][base[1]]
                    assert 0 <= index < size, "diagnostic formed out-of-range pointer"
                    values[a[1]] = ("buffer",base[1],index)
            elif op == 68:
                assert a[3] == 0
                values[a[1]] = [large_length,small_length,len(output)][values[a[2]][1]]
            elif op == 169: values[a[1]] = values[a[3] if values[a[2]] else a[4]]
            elif op in (128,132,194,198,176,167):
                x,y = values[a[2]],values[a[3]]
                v = {128:lambda:x+y,132:lambda:x*y,194:lambda:x>>y,198:lambda:x^y,
                     176:lambda:x<y,167:lambda:x and y}[op]()
                values[a[1]] = v if op in (176,167) else v & 0xFFFFFFFF
            elif op == 62:
                ptr=values[a[0]]
                if ptr[1] == 2: output[ptr[2]] = values[a[1]]
                else:
                    assert ptr[1] == 0
                    data[ptr[2]] = values[a[1]]
            else: raise AssertionError(f"unknown emitted instruction {op}")
    output[-1] = data.get(1,0)  # The production host copy of data[1].
    return struct.pack(f"<{len(output)}I",*output)


def run_vulkan_bounds_diagnostic_checks():
    from Modules.lvs_runtime_memory_guard import initialize_runtime_memory_guard
    from Modules.lvs_worker_integrity import worker_result_successful
    local = 256
    blob = d.diagnostic_shader(local)
    cases = [(d.LOGICAL_WORDS,d.LARGE_BYTES//4,d.SMALL_BYTES//4,"expected_values_observed"),
             (d.LOGICAL_WORDS,0,d.SMALL_BYTES//4,"large_range_array_length_discrepancy"),
             (0,d.LARGE_BYTES//4,d.SMALL_BYTES//4,"push_constant_discrepancy"),
             (d.LOGICAL_WORDS,0,0,"descriptor_array_length_discrepancy")]
    for logical,large,small,conclusion in cases:
        raw=emulate(blob,local,logical,large,small)
        observed=d.decode_observations(raw,local)
        assert observed["conclusion"] == conclusion
        assert len(observed["invocation_records"]) == local
        assert observed["word1"]["production_value"] == (1003605230 if conclusion == "expected_values_observed" else 0)
    valid=emulate(blob,local,d.LOGICAL_WORDS,d.LARGE_BYTES//4,d.SMALL_BYTES//4)
    corrupt=bytearray(valid);struct.pack_into('<I',corrupt,d.OUTPUT_BYTES-4,0)
    assert d.decode_observations(corrupt,local)["conclusion"] == "execution_or_visibility_mismatch"
    for invalid in (bytes(d.OUTPUT_BYTES),valid[:-4]):
        try:d.decode_observations(invalid,local)
        except ValueError:pass
        else:raise AssertionError("missing independent observations accepted")

    # Independent validator, when installed, executes on CPU only. The runtime
    # diagnostic has no dependency on SPIRV-Tools or optional Python packages.
    library=C.util.find_library('SPIRV-Tools-shared')
    if library:
        lib=C.CDLL(library)
        lib.spvContextCreate.argtypes=[C.c_int];lib.spvContextCreate.restype=C.c_void_p
        lib.spvContextDestroy.argtypes=[C.c_void_p]
        lib.spvValidateBinary.argtypes=[C.c_void_p,C.POINTER(C.c_uint32),C.c_size_t,C.POINTER(C.c_void_p)]
        lib.spvValidateBinary.restype=C.c_int
        lib.spvDiagnosticDestroy.argtypes=[C.c_void_p]
        context=lib.spvContextCreate(1)
        try:
            for size in (128,256):
                code=d.diagnostic_shader(size);words=(C.c_uint32*(len(code)//4)).from_buffer_copy(code);error=C.c_void_p()
                result=lib.spvValidateBinary(context,words,len(words),C.byref(error))
                if error:lib.spvDiagnosticDestroy(error)
                assert result == 0, "diagnostic shader failed Vulkan SPIR-V validation"
        finally:lib.spvContextDestroy(context)

    class FakeVk:
        def __init__(self,failure=None):
            self.failure=failure;self.calls=[];self.bindings=[];self.next_handle=10
            self.raw=C.create_string_buffer(bytes(d.OUTPUT_BYTES) if failure=='invalid_output' else valid)
        def __getattr__(self,name):
            def call(*args):
                self.calls.append(name)
                if name == self.failure:raise RuntimeError("injected API failure")
                if name.startswith('vkCreate') or name == 'vkAllocateCommandBuffers':
                    self.next_handle+=1
                    C.cast(args[-1],C.POINTER(C.c_void_p)).contents.value=self.next_handle
                if name == 'vkAllocateDescriptorSets':args[-1][0]=55
                elif name == 'vkUpdateDescriptorSets':
                    w=C.cast(args[2],C.POINTER(d.p.VkWriteDescriptorSet)).contents
                    bi=w.pBufferInfo.contents;self.bindings.append((w.dstBinding,bi.buffer,bi.offset,bi.range))
                elif name == 'vkCmdPushConstants':
                    assert args[2:5] == (32,0,8)
                    assert C.cast(args[5],C.POINTER(C.c_uint32)).contents.value == d.LOGICAL_WORDS
                elif name == 'vkCreatePipelineLayout':
                    info=C.cast(args[1],C.POINTER(d.p.VkPipelineLayoutCreateInfo)).contents
                    assert info.pushConstantRangeCount==1
                    bound=C.cast(info.pPushConstantRanges,C.POINTER(d.p.VkPushConstantRange)).contents
                    assert (bound.stageFlags,bound.offset,bound.size)==(32,0,8)
                elif name == 'vkCmdDispatch':assert args[1:] == (1,1,1)
                elif name == 'vkMapMemory':C.cast(args[-1],C.POINTER(C.c_void_p)).contents.value=C.addressof(self.raw)
                return 0
            return call
    identifier='d5d67b06-3c02-6d92-ca68-fcb064c3bac7'
    args=SimpleNamespace(target_device_uuid=identifier,target_slot='0000:01:00.0',target_id='0000:01:00.0',
        physical_gpu_id='pci:0000:01:00.0',target_vendor_id='10de',target_device_id='',target_vendor='NVIDIA',
        target_device_name='',device_class='')
    info=dict(index=0,device_uuid=identifier,pci_slot=args.target_slot,vendor_id='10de',device_id='2b85',
        device_name='NVIDIA',device_type='discrete',max_storage_buffer_range_bytes=0xFFFFFFFF,
        max_compute_work_group_invocations=1024,max_compute_work_group_size=[1024,1024,64])
    with TemporaryDirectory(dir=ROOT) as tmp:
        for failure in (None,'vkCreateComputePipelines','vkWaitForFences','vkDestroyDevice','guard_denial','guard_zero','claim_close','wrong_vendor','invalid_output'):
            guard=Path(tmp)/'guard.json';plan=dict(consumers=[{}],system_memory_total_bytes=32*1024**3,
                system_memory_available_bytes=16*1024**3,system_memory_safety_reserve_bytes=1024**3,
                system_memory_budget_bytes=15*1024**3)
            if failure=='guard_zero':
                plan['system_memory_available_bytes']=plan['system_memory_budget_bytes']=0
            initialize_runtime_memory_guard(plan,guard)
            vk=FakeVk(failure);state={};allocations=[]
            def allocate(_vk,_dev,_mem,size,usage,flags,*_a,**_k):
                allocations.append((size,usage,flags))
                return C.c_void_p(100+len(allocations)),C.c_void_p(200+len(allocations)),size,0
            with patch.object(d.p,'load_vulkan',return_value=vk),patch.object(d.p,'extend_vulkan_prototypes'), \
                 patch.object(d.p,'resolve_vulkan_library',return_value='fake'),patch.object(d.p,'make_instance',return_value=1), \
                 patch.object(d.p,'enumerate_devices',return_value=[1]),patch.object(d.p,'parse_properties',return_value=dict(info,vendor_id='1002') if failure=='wrong_vendor' else info), \
                 patch.object(d.p,'compute_queue_family_details',return_value=(0,{})),patch.object(d.p,'create_buffer',side_effect=allocate), \
                 patch.dict(os.environ,{'LVS_RUNTIME_MEMORY_GUARD_PATH':str(guard)}), \
                 patch.object(d,'runtime_memory_stop_required',return_value=failure=='guard_denial'), \
                 patch('Modules.lvs_runtime_memory_guard.release_runtime_allocation_claim',side_effect=OSError('close failed') if failure=='claim_close' else None):
                d.execute_probe(args,state)
            assert state['status'] == ('observed' if failure is None else 'error')
            assert not worker_result_successful(state), "diagnostic observation is not a stress PASS"
            assert state['cleanup_complete'] is (failure not in ('vkDestroyDevice','claim_close'))
            assert bool(state['outstanding_system_memory_claim_bytes']) is (failure in ('vkDestroyDevice','claim_close'))
            if failure is None:
                assert vk.bindings == [(0,101,0,d.LARGE_BYTES),(1,101,0,d.SMALL_BYTES),(2,102,0,d.OUTPUT_BYTES)]
                assert vk.calls.count('vkCmdDispatch') == 1
                assert state['observations']['conclusion']=='expected_values_observed'
                assert allocations[1][2] == d.p.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|d.p.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
                assert vk.calls.index('vkWaitForFences') < vk.calls.index('vkMapMemory')
            if failure in ('guard_denial','guard_zero','wrong_vendor'):assert not allocations
            if failure=='invalid_output':assert state['invalid_readback_words']==[0]*(d.OUTPUT_BYTES//4)
            for resource in ('vkDestroyDevice','vkDestroyInstance','vkDestroyFence'):
                assert vk.calls.count(resource) <= 1

    # Missing opt-in rejects before discovering/allocating hardware.
    with patch.object(sys,'argv',['probe','--target-slot',args.target_slot,'--target-device-uuid',identifier]), \
         patch.object(d.p,'load_vulkan',side_effect=AssertionError('GPU accessed')):
        try:d.main()
        except SystemExit as exc:assert exc.code==2
        else:raise AssertionError('diagnostic ran without explicit opt-in')

    class Process:
        def __init__(self):self.terminated=False;self.killed=False
        def poll(self):return None
        def terminate(self):self.terminated=True
        def wait(self,timeout):
            if not self.killed:raise subprocess.TimeoutExpired('fake',timeout)
            return -9
        def kill(self):self.killed=True
    now=[0.];process=Process()
    with patch.object(d,'read_linux_memory_snapshot',return_value={'mem_available_bytes':16*1024**3}), \
         patch.object(d,'update_runtime_memory_guard',return_value={'stage_termination_required':False}):
        reason=d.supervise(process,{},clock=lambda:now[0],sleep=lambda amount:now.__setitem__(0,now[0]+amount))
    assert reason=='deadline' and process.terminated and process.killed
    for guard_response,expected in [({'stage_termination_required':True},'memory_guard'),(KeyboardInterrupt(),'interrupted')]:
        process=Process()
        with patch.object(d,'read_linux_memory_snapshot',return_value={'mem_available_bytes':1}), \
             patch.object(d,'update_runtime_memory_guard',side_effect=guard_response if isinstance(guard_response,BaseException) else None,return_value=guard_response):
            assert d.supervise(process,{})==expected
        assert process.terminated and process.killed

    # Failed terminal publication must propagate; it cannot return an observed
    # exit code while leaving only in-memory observations.
    with TemporaryDirectory(dir=ROOT) as tmp:
        root=Path(tmp);folder=root/'results'/'probe';folder.mkdir(parents=True)
        (folder/'diagnostic_manifest.json').write_text(json.dumps(dict(contract_id=d.CONTRACT,contract_version=1,
            diagnostic_only=True,target_slot=args.target_slot,target_uuid=identifier)))
        argv=['probe','--run','--worker','--result-dir',str(folder),'--target-slot',args.target_slot,'--target-device-uuid',identifier]
        with patch.object(d,'ROOT',root),patch.object(sys,'argv',argv),patch.object(d.signal,'signal'), \
             patch.object(d,'execute_probe',side_effect=lambda _args,s:s.update(status='observed')), \
             patch.object(d,'_write_json_atomic',side_effect=OSError('publication failed')):
            try:d.main()
            except OSError:pass
            else:raise AssertionError('failed terminal write reported completion')
    with TemporaryDirectory(dir=ROOT) as tmp:
        root=Path(tmp)
        argv=['probe','--run','--target-slot',args.target_slot,'--target-device-uuid',identifier]
        with patch.object(d,'ROOT',root),patch.object(sys,'argv',argv), \
             patch.object(d,'read_linux_memory_snapshot',return_value={}), \
             patch.object(d,'collect_source_provenance',return_value={'status':'not_recorded'}), \
             patch.object(d.subprocess,'Popen',side_effect=AssertionError('blocked diagnostic launched')),redirect_stdout(io.StringIO()):
            assert d.main()==1
        folder=next((root/'results').iterdir())
        result=json.loads((folder/'diagnostic_result.json').read_text())
        assert result['status']=='blocked' and result['worker_launched'] is False
