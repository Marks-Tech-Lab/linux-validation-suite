"""I8MM matrix software evidence: production instructions and labelled emulation.

These tests never establish physical instruction execution or stress acceptance.
"""
from __future__ import annotations
from copy import deepcopy
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

from smoke_tests.sve2_smlal_checks import _build
from Modules.lvs_worker_integrity import worker_result_successful, worker_verification_satisfied

ROOT=Path(__file__).resolve().parents[1]
KERNEL='neon_i8mm'
OPERATION='s8_s8_u8_u8_u8_s8_matrix_multiply_accumulate_2x8_8x2'


def _valid():
    from smoke_tests.neon_dotprod_checks import _valid as dot_valid
    w=dot_valid()
    for key in ['mode','kernel_flavor']:w[key]=KERNEL
    w.update(verification_contract=KERNEL+'_v1',verification_method='wide_integer_matrix_reference_modulo_2_32',
             operation_family=OPERATION,execution_implementation='aarch64_neon_i8mm_intrinsics',actual_isa='i8mm',
             matrix_rounds_per_block=256,products_per_lane=8,signed_chains=3,unsigned_chains=3,mixed_chains=2,
             matrix_layout='a_row_major_b_column_major_c_row_major')
    w.pop('dot_rounds_per_block')
    w['threads_detail'][0].update(isa_hwcap=3,isa_hwcap2=1<<13)
    return w


def _run(binary,directory,**kwargs):
    from smoke_tests.neon_dotprod_checks import _run as run_integer
    return run_integer(binary,directory,kernel=KERNEL,**kwargs)


def _check_i8mm_emission(body):
    """Trace emitted data/control flow, not static opcode-site counts.

    A bounded symbolic interpreter follows both running and final-block paths.
    Vector values carry their input/accumulator identity and recurrence count;
    this verifies operand packing, independent chains, all 256 updates and every
    output store even when GCC peels or copies accumulators. This is software
    emission evidence, not physical execution. Unknown instructions fail closed.
    """
    code=[]; labels={}
    for line in body.splitlines():
        line=line.split('//',1)[0].strip()
        if not line:continue
        if line.endswith(':'):
            labels[line[:-1]]=len(code)
        elif not line.startswith('.'):
            parts=line.split(None,1)
            code.append((parts[0],re.split(r',\s*(?![^\[]*\])',parts[1]) if len(parts)>1 else []))
    code=[(op,[a.strip() for a in args]) for op,args in code]
    assert any(op=='smmla' for op,_ in code)

    for final,running in [(0,1),(1,1),(1,0),(0,0)]:
        regs={'x0':0x10000,'x1':0x20000,'x2':final,'sp':0x30000}
        vectors={}; stores={}; counts=[0]*8; compared=None; pc=0
        def scalar(reg):
            if reg in ('wzr','xzr'):return 0
            if ':lo12:' in reg:return 0
            if reg.startswith('#') or re.fullmatch(r'-?(?:0x[0-9a-f]+|\d+)',reg):
                return int(reg.lstrip('#'),0)
            return regs['x'+reg[1:] if reg.startswith('w') else reg]
        def assign(reg,value):
            regs['x'+reg[1:] if reg.startswith('w') else reg]=value & (0xffffffff if reg.startswith('w') else 0xffffffffffffffff)
        def vector(reg):return int(re.fullmatch(r'[qv](\d+)(?:\.(?:16b|4s))?',reg)[1])
        for step in range(30000):
            assert 0<=pc<len(code),('control flow left function',pc)
            op,args=code[pc]; pc+=1
            if op in ('smmla','ummla','usmmla'):
                assert re.fullmatch(r'v\d+\.4s',args[0])
                assert all(re.fullmatch(r'v\d+\.16b',a) for a in args[1:])
                dest,left,right=map(vector,args)
                chain,rounds=vectors[dest]
                assert isinstance(chain,int) and 0<=chain<8
                assert op==('smmla' if chain<3 else 'ummla' if chain<6 else 'usmmla')
                assert vectors[left]==('input',16*chain)
                assert vectors[right]==('input',128+16*chain)
                assert rounds<256
                vectors[dest]=(chain,rounds+1); counts[chain]+=1
            elif op in ('ldr','ldp','str','stp'):
                # ABI callee-save stack traffic is unrelated to matrix inputs
                # and output. All full-width matrix loads/stores are traced.
                if any('[sp' in a for a in args):
                    assert all(re.fullmatch(r'd\d+',a) for a in args[:1 if op in ('ldr','str') else 2])
                    continue
                n=2 if op in ('ldp','stp') else 1
                mem=re.fullmatch(r'\[([xw]\d+)(?:,\s*([^\]]+))?\]',args[n]); assert mem,args
                address=scalar(mem[1])+(scalar(mem[2]) if mem[2] else 0)
                if args[0].startswith('w'):
                    assert op=='ldr' and address>=0x40000
                    assign(args[0],running)
                    continue
                for i,reg in enumerate(args[:n]):
                    offset=address+i*16
                    if op in ('ldr','ldp'):
                        assert 0x10000<=offset<0x10180 and offset%16==0
                        offset-=0x10000
                        vectors[vector(reg)]=('input',offset) if offset<256 else ((offset-256)//16,0)
                    else:
                        assert 0x20000<=offset<0x20080 and offset%16==0
                        assert offset not in stores,('duplicate store',offset)
                        stores[offset]=vectors[vector(reg)]
            elif op=='mov':
                if args[0].startswith('v'):
                    assert all(re.fullmatch(r'v\d+\.16b',a) for a in args)
                    vectors[vector(args[0])]=vectors[vector(args[1])]
                else:assign(args[0],scalar(args[1]))
            elif op=='adrp':assign(args[0],0x40000)
            elif op in ('add','and','orr'):
                a,b=map(scalar,args[1:])
                assign(args[0],a+b if op=='add' else a&b if op=='and' else a|b)
            elif op=='cmp':compared=scalar(args[0])-scalar(args[1])
            elif op=='b':pc=labels[args[0]]
            elif op in ('b.eq','beq','b.ne','bne'):
                assert compared is not None
                if (compared==0)==(op in ('b.eq','beq')):pc=labels[args[0]]
            elif op in ('cbz','cbnz'):
                if (scalar(args[0])==0)==(op=='cbz'):pc=labels[args[1]]
            elif op=='ret':
                if running or final:
                    assert scalar('w0')==1 and counts==[256]*8,counts
                    assert stores=={0x20000+16*i:(i,256) for i in range(8)},stores
                else:
                    assert scalar('w0')==0 and not stores
                    assert max(counts)<=1  # Speculated/peeled work gets no result credit.
                break
            elif op!='nop':raise AssertionError(('unsupported emitted instruction',op,args))
        else:raise AssertionError('unbounded or incomplete emitted recurrence')


def _i8mm_emission_control_flow_checks():
    # Compact assembly fixtures preserve the observed GCC 15 transformation:
    # first signed triplet before the loop, remaining signed triplets after the
    # exit test, plus accumulator copies. No retained hardware binary is needed.
    loads='\n'.join(f'ldr q{i}, [x0, #{256+16*i}]\nldr q{i+8}, [x0, #{16*i}]\nldr q{i+16}, [x0, #{128+16*i}]' for i in range(8))
    ops=[f'{"smmla" if i<3 else "ummla" if i<6 else "usmmla"} v{i}.4s, v{i+8}.16b, v{i+16}.16b' for i in range(8)]
    check='and w5, w3, #31\norr w5, w5, w2\ncbnz w5, .work\nldr w5, [x4]\ncbz w5, .cancel\n'
    stores='\n'.join(f'str q{i}, [x1, #{16*i}]' for i in range(8))
    head=loads+'\nmov w3, #0\nadrp x4, keep_running\n'
    tail='\n.done:\n'+stores+'\nmov w0, #1\nret\n.cancel:\nmov w0, #0\nret\n'
    ordinary=head+'.loop:\n'+check+'.work:\n'+'\n'.join(ops)+'\nadd w3, w3, #1\ncmp w3, #256\nb.ne .loop\nb .done'+tail
    copies='\n'.join(f'mov v{i+24}.16b, v{i}.16b\nmov v{i}.16b, v{i+24}.16b' for i in range(8))
    peeled=(head+'\n'.join(ops[:3])+'\n'+check+'.work:\n'+
            '\n'.join(ops[3:])+'\n'+copies+
            '\nadd w3, w3, #1\ncmp w3, #256\nb.eq .done\n'+
            '\n'.join(ops[:3])+'\n.loop_check:\n'+check+'b .work'+tail)
    for body in (ordinary,peeled):
        _check_i8mm_emission(body)
        # Mnemonics alone, static counts and a #256 literal cannot pass these.
        mutations=[body.replace('#256\nb.', '#255\nb.'),
                   body.replace(ops[4],''),body.replace(ops[7],ops[6]),
                   body.replace('v8.16b, v16.16b','v16.16b, v8.16b'),
                   body.replace('str q7, [x1, #112]','str q6, [x1, #112]'),
                   body.replace('str q7, [x1, #112]',''),
                   body.replace('v0.4s','v0.2s')]
        for bad in mutations:
            try:_check_i8mm_emission(bad)
            except (AssertionError,KeyError,TypeError):pass
            else:raise AssertionError('incorrect emission accepted')


def run_i8mm_reference_instruction_checks():
    _i8mm_emission_control_flow_checks()
    with TemporaryDirectory(prefix='lvs-i8mm-emission-') as directory:
        cross=shutil.which('aarch64-linux-gnu-gcc')
        if cross or importlib.util.find_spec('ziglang') or os.uname().machine=='aarch64':
            compiler=[cross or 'gcc'] if cross or os.uname().machine=='aarch64' else [sys.executable,'-m','ziglang','cc','-target','aarch64-linux-gnu']
            asm=Path(directory)/'worker.s';env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(Path(directory)/'cache'))
            for enabled in [True,False]:
                # The existing SVE FP32 header uses GCC pragmas; Clang's
                # optional-build fallback intentionally excludes that region.
                flags=['-DLVS_CPU_HELPER_ENABLE_I8MM','-DLVS_CPU_HELPER_ENABLE_DOTPROD','-DLVS_CPU_HELPER_ENABLE_SVE2'] if enabled else []
                if enabled and (cross or os.uname().machine=='aarch64'):flags.append('-DLVS_CPU_HELPER_ENABLE_SVE')
                subprocess.run([*compiler,'-O3','-std=c11','-pthread',*flags,'-S',str(ROOT/'native/cpu_stress_helper.c'),'-o',str(asm)],
                               env=env,check=True,capture_output=True,timeout=120)
                text=asm.read_text()
                if enabled:
                    match=re.search(r'execute_neon_i8mm_block[^:\n]*:',text);assert match
                    body=text[match.end():].split('.size',1)[0]
                    _check_i8mm_emission(body)
                else:assert not re.search(r'\b(?:smmla|ummla|usmmla)\s+v',text)
        else:print('I8MM emission unavailable: optional AArch64 compiler required; emulation is not opcode proof')
        source=Path(directory)/'reference.c'
        source.write_text('#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            'uint32_t ref(uint32_t i,uint8_t*a,uint8_t*b,int row,int col,int kind){return i8mm_reference(i,a,b,row,col,kind); }\n'
            'int cap(uint64_t h,uint64_t h2){return i8mm_capability(h,h2); }\n'
            'void cases(uint32_t seed,uint32_t*out){i8mm_case_t c;prepare_i8mm_case(&c,seed);memcpy(out,c.expected,sizeof(c.expected)); }\n')
        lib=Path(directory)/'reference.so'
        subprocess.run(['gcc','-O2','-pthread','-fPIC','-shared',str(source),'-o',str(lib)],check=True,capture_output=True)
        dll=ctypes.CDLL(str(lib));byte_array=ctypes.c_uint8*16
        dll.ref.restype=ctypes.c_uint32
        dll.ref.argtypes=[ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint8),ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int,ctypes.c_int]
        def value(x,unsigned):return x if unsigned or x<128 else x-256
        def reference(initial,a,b,row,col,kind):
            # Independent mathematical matrices, not a four-byte DotProd group.
            left=[a[:8],a[8:]]
            right=list(zip(b[:8],b[8:]))
            dot=sum(value(left[row][k],kind!=0)*value(right[k][col],kind==1) for k in range(8))
            return (initial+256*dot)&0xffffffff
        # Exhaustive single-entry matrix bases catch row/column swaps, transposes,
        # wrong lane ordering, truncated depth and an accidental DotProd kernel.
        for kind in range(3):
            for ai in range(16):
                for bi in range(16):
                    a=[0]*16;b=[0]*16;a[ai]=255;b[bi]=128
                    for lane in range(4):
                        expected=reference(0xffffffff,a,b,lane//2,lane%2,kind)
                        assert dll.ref(0xffffffff,byte_array(*a),byte_array(*b),lane//2,lane%2,kind)==expected
            for initial in [0,0x7fffffff,0x80000000,0xffffffff]:
                for av in [0,1,127,128,255]:
                    for bv in [0,1,127,128,255]:
                        a=[av]*16;b=[bv]*16
                        for lane in range(4):assert dll.ref(initial,byte_array(*a),byte_array(*b),lane//2,lane%2,kind)==reference(initial,a,b,lane//2,lane%2,kind)
        dll.cases.argtypes=[ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)]
        values=[128,127,255,0,1,63,193]
        for seed in [1,2,3,4,17,0xffffffff]:
            out=(ctypes.c_uint32*32)();dll.cases(seed,out)
            a=[values[((n+seed)&0xffffffff)%7] for n in range(128)]
            b=[values[((n*3+seed+1)&0xffffffff)%7] for n in range(128)]
            for n in range(32):
                chain=n//4;kind=0 if chain<3 else 1 if chain<6 else 2
                initial=0x80000000 if n%2 else (0xffffffff-seed)&0xffffffff
                assert out[n]==reference(initial,a[16*chain:16*(chain+1)],b[16*chain:16*(chain+1)],n%4//2,n%2,kind)
        dll.cap.argtypes=[ctypes.c_uint64,ctypes.c_uint64]
        assert dll.cap(3,1<<13)  # Neither SVE nor DotProd is an inferred requirement.
        for h,h2 in [(0,1<<13),(1,1<<13),(2,1<<13),(3,0),((1<<20)|3,2)]:assert not dll.cap(h,h2)


def run_i8mm_native_lifecycle_checks():
    with TemporaryDirectory(prefix='lvs-i8mm-lifecycle-') as directory:
        baseline=_build(directory,'baseline')
        for args in [['--mode',KERNEL],['--kernel-flavor',KERNEL]]:
            assert subprocess.run([str(baseline),*args,'--print-kernel-flavor'],capture_output=True).returncode==3
        assert KERNEL not in subprocess.check_output([str(baseline),'--print-supported-kernels'],text=True)
        binary=_build(directory,'emulated','-DLVS_CPU_HELPER_TEST_I8MM')
        w=_run(binary,directory,workers=2);assert worker_result_successful(w),w
        assert w['execution_implementation']=='test_integer_emulation' and w['actual_isa']=='test_integer_emulation'
        assert w['actual_worker_count']==min(2,len(os.sched_getaffinity(0)))
        for suffix in ['CORRUPT','CORRUPT_UNSIGNED','CORRUPT_MIXED','CORRUPT_LANE=1','CORRUPT_LANE=2','CORRUPT_LANE=3','CORRUPT_PERIODIC','CORRUPT_FINAL','CORRUPT_GUARD','CAPABILITY_LOST','MIGRATION','INTERRUPT','THREAD_START_FAILURE']:
            flag='LVS_CPU_HELPER_TEST_THREAD_START_FAILURE' if suffix=='THREAD_START_FAILURE' else 'LVS_CPU_HELPER_TEST_I8MM_'+suffix
            binary=_build(directory,suffix,'-DLVS_CPU_HELPER_TEST_I8MM','-D'+flag)
            if suffix=='THREAD_START_FAILURE' and len(os.sched_getaffinity(0))<2:continue
            w=_run(binary,directory,fail=suffix!='CORRUPT_FINAL',workers=2 if suffix=='THREAD_START_FAILURE' else 1)
            if suffix=='INTERRUPT':
                assert worker_result_successful(w),w
                assert w['threads_detail'][0]['interrupted_arithmetic_blocks']>0
            else:
                assert w['observed_exit_code']==4 and not worker_result_successful(w),w
                if suffix=='CORRUPT_FINAL':
                    assert w['initial_verification_completed'] and w['periodic_verification_completed'] and not w['final_verification_completed']
                if suffix=='CORRUPT_PERIODIC':assert w['threads_detail'][0]['arithmetic_verified_blocks']==2
        binary=_build(directory,'disabled','-DLVS_CPU_HELPER_TEST_I8MM','-DLVS_CPU_HELPER_TEST_DISABLE_I8MM')
        assert subprocess.run([str(binary),'--mode',KERNEL,'--print-kernel-flavor'],capture_output=True).returncode==3


def run_i8mm_integrity_reporting_checks():
    from Modules.lvs_report_data import _reported_software_verification,_stage_shell
    from Modules.lvs_report_html import _stage_card
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    good=_valid();assert worker_result_successful(good)
    assert _reported_software_verification(good,KERNEL)['software_verification_satisfied']
    changes=[('verification_contract','neon_fp32_fma_v1'),('verification_required',False),('verification_complete',False),
             ('actual_isa','neon'),('active_int32_lanes',8),('operation_family','u8_s8_dot_product_accumulate'),
             ('arithmetic_verified_blocks',31),('observed_exit_code',-9),('threads_detail',[]),('error_count',1),
             ('execution_implementation','aarch64_sve2_intrinsics'),('matrix_rounds_per_block',128),('matrix_layout','row_major_b'),('mixed_chains',0),('products_per_lane',4),('active_int32_lanes',4.0),('matrix_rounds_per_block',256.0)]
    for key,value in changes:
        bad=deepcopy(good);bad[key]=value
        assert not worker_verification_satisfied(bad) and not worker_result_successful(bad),(key,bad)
        assert not _reported_software_verification(bad,KERNEL)['software_verification_satisfied']
        assert preserve_legacy_worker_evidence_contract(bad)==bad
    for key,value in [('isa_hwcap2',0),('isa_hwcap2',True),('isa_hwcap',1),('isa_hwcap',-1),('isa_hwcap',True),('isa_hwcap',1<<64),
                      ('observed_cpu',3),('affinity_applied',False),('final_verification_completed',False),
                      ('periodic_verification_completed',False),('verify_passes',29),('error_count',1)]:
        bad=deepcopy(good);bad['threads_detail'][0][key]=value
        assert not worker_result_successful(bad),(key,bad)
    stage=_stage_shell(0,dict(stage_id='s',started_monotonic=0,ended_monotonic=90,cpu_kernel_flavor=KERNEL,cpu_selection_evidence={"selection_reason":"explicit I8MM; physical acceptance pending"},worker_results=[good]))
    assert KERNEL in _stage_card(stage,{}) and stage['cpu_instruction_selection']['workers'][0]['software_verification_status']=='verified'
    assert preserve_legacy_worker_evidence_contract(good)==good


def run_i8mm_selection_build_checks():
    from Modules.lvs_cpu_architecture import cpu_instruction_set_policy,python_cpu_fallback_policy,resolve_cpu_instruction_intent
    from Modules.lvs_cpu_targeting import common_kernel_capabilities,select_common_kernel
    from Modules.lvs_cpu_execution import cpu_candidate_kernel_flavors
    from Modules.lvs_native_helpers import resolve_native_helper_status,native_helper_binary_ready
    assert cpu_instruction_set_policy('arm64',KERNEL)['allowed'] and not python_cpu_fallback_policy('arm64',KERNEL)['allowed']
    for machine in ['x86_64','unknown']:assert not cpu_instruction_set_policy(machine,KERNEL)['allowed']
    for targets in [[2],[1,17],list(range(256))]:
        caps={cpu:['scalar','neon',KERNEL] for cpu in targets}
        assert select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common_kernel_capabilities(targets,caps)['common_kernel_flavors'])==KERNEL
        caps[targets[-1]]=['scalar','neon']
        assert not select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common_kernel_capabilities(targets,caps)['common_kernel_flavors'])
    caps=['scalar','neon','neon_fp32_fma','sve_fp32_fma','sve2_smlal',KERNEL]
    for intent in ['baseline_vector','high_throughput_vector','highest_verified_vector']:
        assert resolve_cpu_instruction_intent('arm64',intent,caps)['resolved_kernel_flavor']!=KERNEL
    assert KERNEL not in cpu_candidate_kernel_flavors(helper_available=True,policy='max_power',resolved_mode='neon',supports_kernel_flavor=lambda _:True,architecture='arm64')
    with TemporaryDirectory(prefix='lvs-i8mm-build-') as directory:
        for supported in [('dot','i8mm','sve','sve2'),('i8mm',),('i8mm','sve'),('i8mm','sve','sve2'),('dot','sve','sve2'),('dot',),()]:
            source=Path(directory)/'cpu_stress_helper.c';source.write_text('fixture')
            binary=source.with_name('cpu_stress_helper_arm64');binary.unlink(missing_ok=True);calls=[]
            def build(cmd):
                calls.append(cmd)
                flags={'dot':'-DLVS_CPU_HELPER_ENABLE_DOTPROD','i8mm':'-DLVS_CPU_HELPER_ENABLE_I8MM','sve':'-DLVS_CPU_HELPER_ENABLE_SVE','sve2':'-DLVS_CPU_HELPER_ENABLE_SVE2'}
                ok=all(flag not in cmd or key in supported for key,flag in flags.items())
                if ok:binary.write_text('fixture');binary.chmod(0o700)
                return SimpleNamespace(returncode=0 if ok else 1,stderr='' if ok else 'optional region unavailable')
            w=resolve_native_helper_status(source=source,binary=binary,compiler='gcc',reason_label='CPU',build_runner=build)
            assert w['available'] and w['i8mm_build']['status']==('compiled' if 'i8mm' in supported else 'unavailable') and w['dotprod_build']['status']==('compiled' if 'dot' in supported else 'unavailable'),w
            assert len(calls)<=12
            assert not any('-march=' in arg for cmd in calls for arg in cmd)
            header=source.with_name('cpu_i8mm_kernel.h');header.write_text('new');os.utime(header,(binary.stat().st_mtime+1,)*2)
            assert not native_helper_binary_ready(source,binary);header.unlink()


def run_i8mm_progress_checks():
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    with TemporaryDirectory(prefix='lvs-i8mm-progress-') as directory:
        w=_valid();path=Path(directory)/'progress.jsonl';w['verified_progress']=dict(contract=KERNEL+'_progress_v1',path=str(path))
        rows=[]
        for i,count in enumerate([0,3,12,21,30]):
            rows.append(dict(contract=KERNEL+'_progress_v1',kernel_flavor=KERNEL,operation_family=OPERATION,sequence=i,pid=42,
                state=['startup','initial','ongoing','ongoing','final_complete'][i],monotonic_seconds=10.+i*2,realtime_seconds=1000.+i*2,
                clock_pair_uncertainty_seconds=0.,aggregate_verified_blocks=count,threads=[dict(thread_index=0,cpu_id=2,
                published_monotonic_seconds=10.+i*2,verified_blocks=count,error_count=0,initial_verified=i>0,periodic_verified=i>1,
                final_verified=i==4,affinity_applied=True,observed_cpu=2)]))
        def write():path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        write();window=SimpleNamespace(started_monotonic=10.,ended_monotonic=18.,trim_start_seconds=0,trim_end_seconds=0,
            analysis_intent='sustained',analysis_minimum_usable_seconds=8,analysis_evidence={'quality':'sufficient'})
        result=analyze_verified_progress(w,window);assert result['quality']=='sufficient',result
        assert result['derived_byte_products_per_second']==30/8*8*4*256*8
        assert 'derived_stress_lane_fma_count' not in result['threads'][0]
        rows[-1]['threads'][0]['verified_blocks']=31;write();assert analyze_verified_progress(w,window)['quality']=='insufficient'


def run_i8mm_frontend_checks():
    from smoke_tests.neon_dotprod_checks import _frontend_checks
    _frontend_checks(KERNEL)
