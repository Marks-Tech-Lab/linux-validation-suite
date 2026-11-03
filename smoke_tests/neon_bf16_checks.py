"""BF16 software proofs; cross-compilation and emulation are not physical acceptance."""
from __future__ import annotations
from copy import deepcopy
import ctypes
from fractions import Fraction
from functools import lru_cache
import importlib.util
import itertools
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from smoke_tests.sve2_smlal_checks import _build
from smoke_tests.neon_dotprod_checks import _run, _frontend_checks
from smoke_tests.neon_i8mm_checks import _check_i8mm_emission
from Modules.lvs_worker_integrity import worker_result_successful, worker_verification_satisfied
ROOT=Path(__file__).resolve().parents[1]
KERNEL='neon_bf16'
OPERATION='bf16_standard_dot_matrix_and_fused_widening'


def _valid():
    from smoke_tests.neon_half_checks import _valid as half_valid
    p=half_valid('neon_fhm')
    for k in ('mode','kernel_flavor'):p[k]=KERNEL
    for k in ('fma_rounds_per_block','fhm_mapping'):p.pop(k)
    p.update(verification_contract=KERNEL+'_v1',verification_method='integer_dyadic_rto_ftz_and_rne_fused_reference',
             operation_family=OPERATION,execution_implementation='aarch64_neon_bf16_asm',actual_isa='asimdbf16',
             bf16_rounds_per_block=256,dot_chains=2,matrix_chains=2,bottom_chains=2,top_chains=2,bf16_mode='standard_ebf0')
    p['threads_detail'][0].update(isa_hwcap=3,isa_hwcap2=1<<14,ebf16_available=False)
    return p


def _decode(bits,wide=False,flush=False):
    f=23 if wide else 7;e=(bits>>f)&255;m=bits&((1<<f)-1)
    assert e!=255
    if e:m+=1<<f
    elif flush:m=0
    value=Fraction(m)*Fraction(2)**((e if e else 1)-127-f)
    return -value if bits>>(f+8) else value


def _round(value,odd=False,flush=False,negative_zero=False):
    sign=int(value<0) if value else int(negative_zero);value=abs(value)
    if not value or (flush and value<Fraction(2)**-126):return sign<<31
    exponent=value.numerator.bit_length()-value.denominator.bit_length()
    q=max(exponent-23,-149);scaled=value/Fraction(2)**q
    rounded,rem=divmod(scaled.numerator,scaled.denominator)
    if odd:
        if rem:rounded|=1
    elif 2*rem>scaled.denominator or (2*rem==scaled.denominator and rounded&1):rounded+=1
    if rounded>=1<<24:rounded>>=1;q+=1
    if q+23>127:return None
    e=q+150 if rounded>=1<<23 else 0
    return (sign<<31)|(e<<23)|(rounded&0x7fffff)


def _add(a,b):
    return _round(_decode(a,True,True)+_decode(b,True,True),True,True,bool(a&b&0x80000000))


@lru_cache(maxsize=25000)
def _fma(a,b,c):
    return _round(_decode(a)*_decode(b)+_decode(c,True),negative_zero=bool(((a^b)>>15)&(c>>31)))


@lru_cache(maxsize=25000)
def _dot(a0,a1,b0,b1,c):
    ps=[_round(_decode(a,flush=True)*_decode(b,flush=True),True,True,bool((a^b)&0x8000)) for a,b in [(a0,b0),(a1,b1)]]
    if None in ps:return None
    pair=_add(*ps)
    return None if pair is None else _add(c,pair)


def _lane(a,b,c,chain,lane):
    if chain<2:return _dot(*a[2*lane:2*lane+2],*b[2*lane:2*lane+2],c)
    if chain<4:
        a=a[4*(lane//2):4*(lane//2)+4];b=b[4*(lane%2):4*(lane%2)+4]
        t=_dot(*a[:2],*b[:2],c)
        return None if t is None else _dot(*a[2:],*b[2:],t)
    return _fma(a[2*lane+chain%2],b[2*lane+chain%2],c)


class Case(ctypes.Structure):
    _fields_=[('a',ctypes.c_uint16*32),('b',ctypes.c_uint16*32),('initial',ctypes.c_uint32*32),('expected',ctypes.c_uint32*32),('witness',ctypes.c_uint32*32)]


def run_bf16_reference_checks():
    with TemporaryDirectory(prefix='lvs-bf16-reference-') as tmp:
        source=Path(tmp)/'ref.c'
        source.write_text('#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            'int cap(uint64_t h,uint64_t h2){return bf16_capability(h,h2);}\n'
            'int env(uint64_t f){return bf16_environment_supported(f);}\n'
            'int cases(bf16_case_t*c,uint32_t seed){return prepare_bf16_cases(c,seed);}\n'
            'int fused_ref(uint16_t a,uint16_t b,uint32_t c,uint32_t*out){return bf16_fma(a,b,c,out);}\n'
            'int lane(uint16_t*a,uint16_t*b,uint32_t c,int chain,int lane,uint32_t*out){return bf16_lane_reference(a,b,c,chain,lane,out);}\n')
        lib=Path(tmp)/'ref.so';subprocess.run(['gcc','-O2','-std=c11','-pthread','-fPIC','-shared',str(source),'-o',str(lib)],check=True,capture_output=True)
        dll=ctypes.CDLL(str(lib));dll.cap.argtypes=[ctypes.c_uint64]*2;dll.env.argtypes=[ctypes.c_uint64]
        for h2 in [1<<14,(1<<14)|(1<<32)]:assert dll.cap(3,h2)
        for h,h2 in [(0,1<<14),(1,1<<14),(2,1<<14),(3,0),(3,1<<12),(3,1<<32)]:assert not dll.cap(h,h2)
        assert dll.env(0) and dll.env(1<<25) # DN does not alter finite-domain arithmetic.
        for bit in [0,1,8,9,10,11,12,13,15,19,22,23,24,26]:assert not dll.env(1<<bit)
        u32=ctypes.c_uint32;arr=ctypes.c_uint16*8
        dll.fused_ref.argtypes=[ctypes.c_uint16,ctypes.c_uint16,u32,ctypes.POINTER(u32)]
        dll.lane.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(ctypes.c_uint16),u32,ctypes.c_int,ctypes.c_int,ctypes.POINTER(u32)]
        def check(a,b,c,chain,lane):
            out=u32();ok=dll.lane(arr(*a),arr(*b),c,chain,lane,ctypes.byref(out));e=_lane(a,b,c,chain,lane)
            assert bool(ok)==(e is not None),(a,b,c,chain,lane,e)
            if ok:assert out.value==e,(a,b,hex(c),chain,lane,hex(out.value),hex(e))
        edges=[0,0x8000,1,0x8001,0x7f,0x80,0x7f7f,0xff7f,0x3f81,0xbf82,0x1a00,0x9a00]
        rng=random.Random(92741)
        triples=list(itertools.product(edges,edges,[0,0x80000000,1,0x80000001,0x00800000,0x7f7fffff,0xff7fffff,0x3f800001]))
        triples += [(rng.randrange(0x7f80)|(rng.randrange(2)<<15),rng.randrange(0x7f80)|(rng.randrange(2)<<15),rng.randrange(0x7f800000)|(rng.randrange(2)<<31)) for _ in range(1500)]
        for a,b,c in triples:
            out=u32();ok=dll.fused_ref(a,b,c,ctypes.byref(out));e=_fma(a,b,c)
            assert bool(ok)==(e is not None),(a,b,c,e)
            if ok:assert out.value==e,(hex(a),hex(b),hex(c),hex(out.value),e)
        # Exhaustive matrix placement basis and alternating widening selection.
        for chain in [0,2,4,5]:
            for ai in range(8):
                for bi in range(8):
                    a=[0]*8;b=[0]*8;a[ai]=0xbf80;b[bi]=0x3f00
                    for lane in range(4):check(a,b,0x3f800000,chain,lane)
        for chain in [0,2,4,5]:
            for _ in range(200):
                a=[rng.randrange(0x7f80)|(rng.randrange(2)<<15) for _ in range(8)]
                b=[rng.randrange(0x7f80)|(rng.randrange(2)<<15) for _ in range(8)]
                c=rng.randrange(0x7f800000)|(rng.randrange(2)<<31)
                for lane in range(4):check(a,b,c,chain,lane)
        # Standard dot RTO differs from RN; standard input/result FTZ differs
        # from widening fused RN and gradual underflow. EBF1 is not emulated.
        check([0x3980,0,0,0,0,0,0,0],[0x3900,0,0,0,0,0,0,0],0x3f800000,0,0)
        assert _dot(0x3980,0,0x3900,0,0x3f800000)==0x3f800001
        assert _fma(0x3980,0x3900,0x3f800000)==0x3f800000
        assert _dot(0x1a00,0x1a00,0x1a00,0x1a00,0)==0
        assert _fma(0x1a00,0x1a00,1)==2
        assert _fma(1,0x3f00,0)==0x8000
        for invalid in [0x7f80,0x7fc1]:assert not dll.fused_ref(invalid,0x3f80,0,ctypes.byref(u32()))
        for c in [0x7f800000,0xffc00001]:assert not dll.fused_ref(0x3f80,0x3f80,c,ctypes.byref(u32()))
        dll.cases.argtypes=[ctypes.POINTER(Case),ctypes.c_uint32]
        for seed in [1,17,0xffffffff]:
            cases=(Case*4)();assert dll.cases(cases,seed)
            for case in cases:
                for n in range(32):
                    chain,lane=divmod(n,4);a=list(case.a)[8*(chain//2):8*(chain//2)+8];b=list(case.b)[8*(chain//2):8*(chain//2)+8]
                    value=case.initial[n];assert case.witness[n]==_lane(a,b,value,chain,lane)
                    for _ in range(256):value=_lane(a,b,value,chain,lane)
                    assert case.expected[n]==value,(seed,n,value,case.expected[n])


def _object_bf16_instructions(path):
    """Read actual ELF symbol bytes and decode with an available AArch64 tool."""
    import ctypes.util
    import struct
    data=path.read_bytes()
    assert data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',data,18)[0]==183
    shoff=struct.unpack_from('<Q',data,40)[0];size,count=struct.unpack_from('<HH',data,58)
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,shoff+i*size) for i in range(count)]
    body=None
    for section in sections:
        if section[1]!=2:continue
        names=sections[section[6]];strings=data[names[4]:names[4]+names[5]]
        for offset in range(section[4],section[4]+section[5],section[9]):
            name,info,other,index,value,length=struct.unpack_from('<IBBHQQ',data,offset)
            if strings[name:].split(b'\0',1)[0]==b'execute_neon_bf16_block':
                code=sections[index];start=code[4]+value-code[3];body=data[start:start+length]
    assert body and len(body)%4==0
    library=ctypes.util.find_library('LLVM') or ctypes.util.find_library('LLVM-22')
    if not library:
        tool=shutil.which('aarch64-linux-gnu-objdump') or shutil.which('llvm-objdump')
        assert tool,'an AArch64 disassembler is required for BF16 object evidence'
        return subprocess.check_output([tool,'-d','--disassemble=execute_neon_bf16_block',str(path)],text=True)
    lib=ctypes.CDLL(library)
    for part in ['TargetInfo','Target','TargetMC','Disassembler']:getattr(lib,'LLVMInitializeAArch64'+part)()
    lib.LLVMCreateDisasmCPUFeatures.restype=ctypes.c_void_p
    lib.LLVMCreateDisasmCPUFeatures.argtypes=[ctypes.c_char_p]*3+[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p]
    context=lib.LLVMCreateDisasmCPUFeatures(b'aarch64-linux-gnu',b'generic',b'+bf16',None,0,None,None);assert context
    lib.LLVMDisasmInstruction.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_char_p,ctypes.c_size_t]
    lib.LLVMDisasmInstruction.restype=ctypes.c_size_t;lib.LLVMDisasmDispose.argtypes=[ctypes.c_void_p]
    lines=[]
    try:
        for i in range(0,len(body),4):
            raw=ctypes.create_string_buffer(body[i:i+4]);out=ctypes.create_string_buffer(256)
            assert lib.LLVMDisasmInstruction(context,raw,4,i,out,256)==4
            lines.append(out.value.decode())
    finally:lib.LLVMDisasmDispose(context)
    return '\n'.join(lines)


def run_bf16_emission_checks():
    with TemporaryDirectory(prefix='lvs-bf16-emission-') as tmp:
        cross=shutil.which('aarch64-linux-gnu-gcc')
        compiler=[cross] if cross else ['gcc'] if os.uname().machine=='aarch64' else [sys.executable,'-m','ziglang','cc','-target','aarch64-linux-gnu']
        assert cross or os.uname().machine=='aarch64' or importlib.util.find_spec('ziglang'),'AArch64 compiler required'
        for flags in [[],['BF16'],['BF16','FP16','FHM','DOTPROD','I8MM','SVE2']]:
            asm=Path(tmp)/'worker.s';obj=Path(tmp)/'worker.o';env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(Path(tmp)/'cache'))
            cmd=[*compiler,'-O3','-std=c11','-pthread',*['-DLVS_CPU_HELPER_ENABLE_'+f for f in flags],str(ROOT/'native/cpu_stress_helper.c')]
            for option,path in [('-S',asm),('-c',obj)]:subprocess.run([*cmd,option,'-o',str(path)],check=True,capture_output=True,env=env,timeout=120)
            assert obj.read_bytes()[:6]==b'\x7fELF\x02\x01'
            match=re.search(r'execute_neon_bf16_block[^:\n]*:',asm.read_text())
            if not flags:assert not match;continue
            assert match;body=asm.read_text()[match.end():].split('.size',1)[0]
            _check_i8mm_emission(body,half_kind='bf16')
            decoded=_object_bf16_instructions(obj)
            # Explicit assembly has these sites; recurrence/data flow, not
            # arbitrary compiler static counts, is checked independently above.
            for op in ['bfdot','bfmmla','bfmlalb','bfmlalt']:
                assert len(re.findall(r'\b'+op+r'\s+v\d+\.4s,\s*v\d+\.8h,\s*v\d+\.8h',decoded))==2,decoded
            mutations=[body.replace('bfmmla','bfdot'),body.replace('bfmlalt','bfmlalb'),body.replace('bfdot','fmla'),
                       re.sub(r'\badd\s+(w\d+),\s*\1,\s*#1',r'add \1, \1, #2',body),re.sub(r'\bstp\s+q[^\n]+','',body)]
            for bad in mutations:
                assert bad!=body
                try:_check_i8mm_emission(bad,half_kind='bf16')
                except (AssertionError,KeyError,TypeError):pass
                else:raise AssertionError('incorrect BF16 data flow accepted')


def run_bf16_lifecycle_checks():
    with TemporaryDirectory(prefix='lvs-bf16-lifecycle-') as tmp:
        baseline=_build(tmp,'baseline')
        for flag in ['--mode','--kernel-flavor']:
            assert subprocess.run([str(baseline),flag,KERNEL,'--print-kernel-flavor'],capture_output=True).returncode==3
        assert KERNEL not in subprocess.check_output([str(baseline),'--print-supported-kernels'],text=True)
        binary=_build(tmp,'emulated','-DLVS_CPU_HELPER_TEST_BF16')
        w=_run(binary,tmp,kernel=KERNEL,workers=2);assert worker_result_successful(w),w
        assert w['execution_implementation']==w['actual_isa']=='test_bf16_emulation'
        # Exercise actual progress-publication failure after initial progress;
        # keep exclusive-create protection and terminal arithmetic evidence.
        source=Path(tmp)/'io.c'
        source.write_text('#define _GNU_SOURCE\n#include <stdio.h>\n#include <errno.h>\nint fixture_flush(FILE*);\n'
            '#define fflush fixture_flush\n#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            '#undef main\n#undef fflush\n'
            'int fixture_flush(FILE*f){int r=fflush(f);if(f==progress_file && progress_sequence>=3){errno=ENOSPC;return EOF;}return r;}\n'
            'int main(int argc,char**argv){return fixture_main(argc,argv); }\n')
        io_binary=Path(tmp)/'io';subprocess.run(['gcc','-O3','-std=c11','-pthread','-DLVS_CPU_HELPER_TEST_BF16',str(source),'-o',str(io_binary)],check=True,capture_output=True)
        io=_run(io_binary,tmp,kernel=KERNEL)
        assert io['observed_exit_code']==4 and io['verified_progress']['persistence_error'] and not worker_result_successful(io),io
        assert io['initial_verification_completed'] and io['final_verification_completed']
        suffixes=['CORRUPT_PERIODIC','CORRUPT_FINAL','CORRUPT_WITNESS','CORRUPT_GUARD','BAD_FPCR','CAPABILITY_LOST','MIGRATION','INTERRUPT','THREAD_START_FAILURE']
        suffixes += ['CORRUPT_LANE='+str(n) for n in [3,7,11,15,19,23,27,31]]
        for suffix in suffixes:
            flag='LVS_CPU_HELPER_TEST_THREAD_START_FAILURE' if suffix=='THREAD_START_FAILURE' else 'LVS_CPU_HELPER_TEST_BF16_'+suffix
            if suffix=='THREAD_START_FAILURE' and len(os.sched_getaffinity(0))<2:continue
            binary=_build(tmp,'failure','-DLVS_CPU_HELPER_TEST_BF16','-D'+flag)
            w=_run(binary,tmp,kernel=KERNEL,fail=suffix!='CORRUPT_FINAL',workers=2 if suffix=='THREAD_START_FAILURE' else 1)
            if suffix=='INTERRUPT':assert worker_result_successful(w) and w['threads_detail'][0]['interrupted_arithmetic_blocks']>0,w
            else:
                assert w['observed_exit_code']==4 and not worker_result_successful(w),w
                if suffix=='CORRUPT_FINAL':assert w['initial_verification_completed'] and not w['final_verification_completed']
        b=_build(tmp,'disabled','-DLVS_CPU_HELPER_TEST_BF16','-DLVS_CPU_HELPER_TEST_DISABLE_BF16')
        assert subprocess.run([str(b),'--mode',KERNEL,'--print-kernel-flavor'],capture_output=True).returncode==3


def run_bf16_selection_build_checks():
    from Modules.lvs_cpu_architecture import cpu_instruction_set_policy,python_cpu_fallback_policy,resolve_cpu_instruction_intent
    from Modules.lvs_cpu_targeting import common_kernel_capabilities,select_common_kernel
    from Modules.lvs_native_helpers import resolve_native_helper_status,native_helper_binary_ready
    from Modules.lvs_cpu_execution import cpu_candidate_kernel_flavors
    assert cpu_instruction_set_policy('arm64',KERNEL)['allowed'] and not python_cpu_fallback_policy('arm64',KERNEL)['allowed']
    assert not cpu_instruction_set_policy('x86_64',KERNEL)['allowed']
    for targets in [[1],[1,17],list(range(256))]:
        caps={cpu:['scalar','neon',KERNEL] for cpu in targets}
        assert select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common_kernel_capabilities(targets,caps)['common_kernel_flavors'])==KERNEL
        caps[targets[-1]]=['scalar','neon']
        assert not select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common_kernel_capabilities(targets,caps)['common_kernel_flavors'])
    caps=['scalar','neon','neon_fp32_fma','sve_fp32_fma',KERNEL]
    for intent in ['baseline_vector','high_throughput_vector','highest_verified_vector']:
        assert resolve_cpu_instruction_intent('arm64',intent,caps)['resolved_kernel_flavor']!=KERNEL
    assert KERNEL not in cpu_candidate_kernel_flavors(helper_available=True,policy='max_power',resolved_mode='neon',supports_kernel_flavor=lambda _:True,architecture='arm64')
    regions=['DOTPROD','I8MM','FP16','FHM','BF16']
    with TemporaryDirectory(prefix='lvs-bf16-build-') as tmp:
        source=Path(tmp)/'cpu_stress_helper.c';source.write_text('fixture');binary=source.with_name('cpu_stress_helper_arm64')
        for mask in range(32):
            binary.unlink(missing_ok=True);calls=[];supported={r for i,r in enumerate(regions) if mask&(1<<i)}
            def build(cmd):
                calls.append(cmd);enabled={r for r in regions if '-DLVS_CPU_HELPER_ENABLE_'+r in cmd}
                ok=enabled<=supported and '-DLVS_CPU_HELPER_ENABLE_SVE' not in cmd
                if ok:binary.write_text('fixture');binary.chmod(0o700)
                return SimpleNamespace(returncode=0 if ok else 1,stderr='' if ok else 'optional region unavailable')
            status=resolve_native_helper_status(source=source,binary=binary,compiler='gcc',reason_label='CPU',build_runner=build)
            assert status['available'] and len(calls)<=24,status
            for r in regions:assert status[r.lower()+'_build']['status']==('compiled' if r in supported else 'unavailable'),status
            assert not any('-march=' in a for cmd in calls for a in cmd)
        header=source.with_name('cpu_bf16_kernel.h');header.write_text('fixture');os.utime(header,(binary.stat().st_mtime+1,)*2)
        assert not native_helper_binary_ready(source,binary)


def run_bf16_reporting_progress_checks():
    from Modules.lvs_report_data import _reported_software_verification,_stage_shell
    from Modules.lvs_report_html import _stage_card
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    good=_valid();assert worker_result_successful(good)
    assert _reported_software_verification(good,KERNEL)['software_verification_satisfied']
    changes=[('verification_contract','neon_fp32_fma_v1'),('comparison','tolerance'),('bf16_mode','enhanced'),('actual_isa','svebf16'),
             ('active_lanes',4.0),('bf16_rounds_per_block',255),('witness_rounds_per_block',0),('matrix_chains',0),('bottom_chains',4),
             ('operation_family','fp32_fused_multiply_add'),('observed_exit_code',-9),('threads_detail',[]),('arithmetic_verified_blocks',31),('verification_complete',False),('verified_progress',{'persistence_error':True}),('verified_progress',{'persistence_error':None}),('verified_progress',{'persistence_error':0})]
    for key,value in changes:
        bad=deepcopy(good);bad[key]=value;assert not worker_result_successful(bad),(key,bad)
        assert not _reported_software_verification(bad,KERNEL)['software_verification_satisfied']
        assert preserve_legacy_worker_evidence_contract(bad)==bad
    for key,value in [('isa_hwcap',3.0),('isa_hwcap',1),('isa_hwcap2',1<<12),('isa_hwcap2',1<<32),('isa_hwcap2',True),('ebf16_available',True),('fpcr',True),('fpcr',1<<13),('fpcr',1<<19),('fpcr',1<<24),('fpcr',1<<22),('fpcr',1<<26),('fpcr',1),('fpcr',2),('fpcr',1<<8),('observed_cpu',9),('affinity_applied',False),('final_verification_completed',False),('error_count',1)]:
        bad=deepcopy(good);bad['threads_detail'][0][key]=value;assert not worker_verification_satisfied(bad),(key,value)
    enhanced_cap=deepcopy(good);enhanced_cap['threads_detail'][0].update(isa_hwcap2=(1<<14)|(1<<32),ebf16_available=True)
    assert worker_result_successful(enhanced_cap) # EBF16 capability is not EBF=1 mode.
    with TemporaryDirectory(prefix='lvs-bf16-progress-') as tmp:
        path=Path(tmp)/'progress.jsonl';w=deepcopy(good);w['verified_progress']=dict(contract=KERNEL+'_progress_v1',path=str(path))
        rows=[]
        for i,count in enumerate([0,3,12,21,30]):
            rows.append(dict(contract=KERNEL+'_progress_v1',kernel_flavor=KERNEL,operation_family=OPERATION,sequence=i,pid=42,
                state=['startup','initial','ongoing','ongoing','final_complete'][i],monotonic_seconds=10.+i*2,realtime_seconds=1000.+i*2,
                clock_pair_uncertainty_seconds=0.,aggregate_verified_blocks=count,threads=[dict(thread_index=0,cpu_id=2,
                published_monotonic_seconds=10.+i*2,verified_blocks=count,error_count=0,initial_verified=i>0,periodic_verified=i>1,
                final_verified=i==4,affinity_applied=True,observed_cpu=2)]))
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        window=SimpleNamespace(started_monotonic=10.,ended_monotonic=18.,trim_start_seconds=0,trim_end_seconds=0,analysis_intent='sustained',analysis_minimum_usable_seconds=8,analysis_evidence={'quality':'sufficient'})
        r=analyze_verified_progress(w,window);assert r['quality']=='sufficient',r
        assert r['derived_stress_bf16_products_per_second']==30/8*64*256
        w['verified_progress_analysis']=r
        stage=_stage_shell(0,dict(stage_id='s',started_monotonic=10,ended_monotonic=18,cpu_kernel_flavor=KERNEL,cpu_selection_evidence={'selection_reason':'explicit BF16; physical acceptance pending'},worker_results=[w]))
        assert KERNEL in _stage_card(stage,{})
        rows[-1]['aggregate_verified_blocks']=31;path.write_text(''.join(json.dumps(r)+'\n' for r in rows));assert analyze_verified_progress(w,window)['quality']=='insufficient'


def run_bf16_frontend_checks():
    _frontend_checks(KERNEL)
