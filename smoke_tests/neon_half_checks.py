"""Exact FP16/FHM software evidence; cross-emission/emulation is not acceptance."""
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
KERNELS=('neon_fp16','neon_fhm')


def _valid(kernel):
    from smoke_tests.neon_i8mm_checks import _valid as integer_valid
    p=integer_valid();wide=kernel=='neon_fhm'
    for k in ('mode','kernel_flavor'):p[k]=kernel
    for k in ('matrix_rounds_per_block','matrix_layout','signed_chains','unsigned_chains','mixed_chains','products_per_lane','active_int32_lanes'):p.pop(k)
    p.update(verification_contract=kernel+'_v1',verification_method='integer_significand_rne_fused_reference',
             operation_family='fp16_product_fp32_fused_accumulate_low_high' if wide else 'fp16_fused_multiply_add',
             execution_implementation='aarch64_neon_fhm_asm' if wide else 'aarch64_neon_fp16_asm',
             actual_isa='asimdfhm' if wide else 'asimdhp',fma_rounds_per_block=256,witness_rounds_per_block=1,
             active_lanes=4 if wide else 8,input_bits=16,accumulator_bits=32 if wide else 16,
             fhm_mapping='paired_low_high_halfwords' if wide else 'all_eight_halfwords',comparison='bit_exact')
    row=p['threads_detail'][0];row.pop('isa_hwcap2');row.update(isa_hwcap=3|(1<<(23 if wide else 10)),fpcr=0)
    return p


def _decode(bits,wide=False):
    fraction,bias,ebits=(23,127,8) if wide else (10,15,5)
    exp=(bits>>fraction)&((1<<ebits)-1);m=bits&((1<<fraction)-1)
    assert exp!=(1<<ebits)-1
    if exp:m+=1<<fraction
    value=Fraction(m)*Fraction(2)**((exp if exp else 1)-bias-fraction)
    return -value if bits>>(fraction+ebits) else value


@lru_cache(maxsize=20000)
def _reference(a,b,c,wide):
    # Independent rational arithmetic and integer division/tie handling. No C
    # reference reuse, native FMA, host half conversion, or tolerance.
    value=_decode(a)*_decode(b)+_decode(c,wide)
    fraction,bias,signbit=(23,127,31) if wide else (10,15,15)
    if not value:return ((((a^b)>>15)&(c>>signbit))&1)<<signbit
    sign=int(value<0);value=abs(value)
    exponent=value.numerator.bit_length()-value.denominator.bit_length()
    quantum=max(exponent-fraction,1-bias-fraction)
    scaled=value/Fraction(2)**quantum
    rounded,remainder=divmod(scaled.numerator,scaled.denominator)
    twice=2*remainder
    if twice>scaled.denominator or (twice==scaled.denominator and rounded&1):rounded+=1
    if rounded>=(1<<(fraction+1)):rounded>>=1;quantum+=1
    if quantum+fraction>bias:return None
    exp=quantum+fraction+bias if rounded>=1<<fraction else 0
    return (sign<<signbit)|(exp<<fraction)|(rounded&((1<<fraction)-1))


def run_half_reference_checks():
    with TemporaryDirectory(prefix='lvs-half-reference-') as tmp:
        source=Path(tmp)/'ref.c'
        source.write_text('#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            'int ref(uint16_t a,uint16_t b,uint32_t c,int wide,uint32_t*out){return half_fma_reference(a,b,c,wide,out);}\n'
            'int cap(uint64_t h,int wide){return half_capability(h,wide);}\n'
            'int cases(uint32_t seed,int wide,uint16_t*a,uint16_t*b,uint32_t*c,uint32_t*e,uint32_t*w){half_case_t t[4];'
            'if(!prepare_half_cases(t,seed,wide))return 0;for(int k=0;k<4;k++){memcpy(a+32*k,t[k].a,64);memcpy(b+32*k,t[k].b,64);'
            'for(int n=0;n<(wide?32:64);n++){c[k*64+n]=wide?t[k].wide[n]:t[k].narrow[n];e[k*64+n]=t[k].expected[n];w[k*64+n]=t[k].witness[n];}}return 1;}\n')
        lib=Path(tmp)/'ref.so';subprocess.run(['gcc','-O2','-std=c11','-pthread','-shared','-fPIC',str(source),'-o',str(lib)],check=True,capture_output=True)
        dll=ctypes.CDLL(str(lib));dll.ref.argtypes=[ctypes.c_uint16,ctypes.c_uint16,ctypes.c_uint32,ctypes.c_int,ctypes.POINTER(ctypes.c_uint32)]
        dll.cap.argtypes=[ctypes.c_uint64,ctypes.c_int]
        edges=[0,0x8000,1,0x8001,0x3ff,0x400,0x7bff,0xfbff,0x3c01,0xbc02,0x3555,0xb555]
        rng=random.Random(7419)
        for wide in (0,1):
            bit=23 if wide else 10
            assert dll.cap(3|(1<<bit),wide)
            for h in [0,3,1|(1<<bit),2|(1<<bit),3|(1<<(10 if wide else 23))]:assert not dll.cap(h,wide)
            triples=list(itertools.product(edges,edges,[0,0x80000000,0x7f7fffff] if wide else edges))
            triples += [(rng.randrange(0x7c00)|(rng.randrange(2)<<15),rng.randrange(0x7c00)|(rng.randrange(2)<<15),
                         (rng.randrange(0x28000000,0x48000000)|(rng.randrange(2)<<31)) if wide else rng.randrange(0x7c00)|(rng.randrange(2)<<15)) for _ in range(2000)]
            for a,b,c in triples:
                expected=_reference(a,b,c,wide);out=ctypes.c_uint32()
                ok=dll.ref(a,b,c,wide,ctypes.byref(out))
                # Wide exponent gaps outside the explicit bounded C domain
                # must reject; they are never generated by the worker cases.
                if ok:assert out.value==expected,(hex(a),hex(b),hex(c),wide,out.value,expected)
                elif not wide:assert expected is None
                else:assert (c&0x7fffffff)==0x7f7fffff, (a,b,c)
            out=ctypes.c_uint32();c=0xbf804000 if wide else 0xbc02
            assert dll.ref(0x3c01,0x3c01,c,wide,ctypes.byref(out))
            assert out.value==(0x35800000 if wide else 0x10)  # fused witness, not zero
            for boundary in ([0,0x80000000,1,0x80000001,0x00800000,0x7f7fffff,0xff7fffff] if wide else [0,0x8000,1,0x8001,0x0400,0x7bff,0xfbff]):
                for a,b in [(0,0x3c00),(0x8000,0x3c00)]:
                    assert dll.ref(a,b,boundary,wide,ctypes.byref(out))
                    assert out.value==_reference(a,b,boundary,wide)
            for invalid in [0x7c00,0x7e00]:assert not dll.ref(invalid,0x3c00,0,wide,ctypes.byref(out))
            for seed in [1,17,0xffffffff]:
                a=(ctypes.c_uint16*128)();b=(ctypes.c_uint16*128)();c=(ctypes.c_uint32*256)();e=(ctypes.c_uint32*256)();w=(ctypes.c_uint32*256)()
                assert dll.cases(seed,wide,a,b,c,e,w)
                for k in range(4):
                    lanes=4 if wide else 8
                    for n in range(lanes*8):
                        chain,lane=divmod(n,lanes);src=32*k+8*(chain//2)+(4*(chain%2) if wide else 0)+lane
                        v=c[k*64+n];assert _reference(a[src],b[src],v,wide)==w[k*64+n]
                        for _ in range(256):v=_reference(a[src],b[src],v,wide)
                        assert v==e[k*64+n]


def run_half_emission_checks():
    with TemporaryDirectory(prefix='lvs-half-emission-') as tmp:
        cross=shutil.which('aarch64-linux-gnu-gcc')
        compiler=[cross] if cross else ['gcc'] if os.uname().machine=='aarch64' else [sys.executable,'-m','ziglang','cc','-target','aarch64-linux-gnu']
        assert cross or os.uname().machine=='aarch64' or importlib.util.find_spec('ziglang'),'AArch64 emission compiler required'
        for flags in [[],['FP16'],['FHM'],['FP16','FHM','DOTPROD','I8MM','SVE2']]:
            asm=Path(tmp)/'worker.s';obj=Path(tmp)/'worker.o'
            cmd=[*compiler,'-O3','-std=c11','-pthread',*['-DLVS_CPU_HELPER_ENABLE_'+f for f in flags],str(ROOT/'native/cpu_stress_helper.c')]
            env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(Path(tmp)/'cache'))
            subprocess.run([*cmd,'-S','-o',str(asm)],check=True,capture_output=True,env=env,timeout=120)
            subprocess.run([*cmd,'-c','-o',str(obj)],check=True,capture_output=True,env=env,timeout=120)
            assert obj.read_bytes()[:6]==b'\x7fELF\x02\x01'
            text=asm.read_text()
            for kind in ['fp16','fhm']:
                match=re.search(r'execute_neon_'+kind+r'_block[^:\n]*:',text)
                if kind.upper() not in flags:assert not match;continue
                assert match
                body=text[match.end():].split('.size',1)[0]
                _check_i8mm_emission(body,half_kind=kind) # dynamic recurrence, operands, stores, cancellation
                # Wrong high-half mapping or lost chains/counts/stores must fail.
                mutations=[re.sub(r'\bfmlal2\b','fmlal',body),re.sub(r'\bfmla\b','fmul',body),
                           re.sub(r'\badd\s+(w\d+),\s*\1,\s*#1',r'add \1, \1, #2',body),
                           re.sub(r'\bstp\s+q[^\n]+','',body)]
                for bad in mutations:
                    if bad==body:continue
                    try:_check_i8mm_emission(bad,half_kind=kind)
                    except (AssertionError,KeyError,TypeError):pass
                    else:raise AssertionError('incorrect half emission accepted')
        from smoke_tests.neon_i8mm_checks import _i8mm_emission_control_flow_checks
        _i8mm_emission_control_flow_checks()  # Ordinary and peeled compiler forms still pass.


def run_half_lifecycle_checks():
    with TemporaryDirectory(prefix='lvs-half-lifecycle-') as tmp:
        baseline=_build(tmp,'baseline')
        for kernel in KERNELS:
            assert kernel not in subprocess.check_output([str(baseline),'--print-supported-kernels'],text=True)
            assert subprocess.run([str(baseline),'--kernel-flavor',kernel,'--print-kernel-flavor'],capture_output=True).returncode==3
        binary=_build(tmp,'emulated','-DLVS_CPU_HELPER_TEST_HALF')
        for kernel in KERNELS:
            w=_run(binary,tmp,kernel=kernel,workers=2);assert worker_result_successful(w),w
            assert w['execution_implementation']==w['actual_isa']=='test_half_emulation'
            assert w['actual_worker_count']==min(2,len(os.sched_getaffinity(0)))
            lanes=4 if kernel=='neon_fhm' else 8
            suffixes=['CORRUPT','CORRUPT_PERIODIC','CORRUPT_FINAL','CORRUPT_WITNESS','CORRUPT_GUARD','BAD_FPCR','CAPABILITY_LOST','MIGRATION','INTERRUPT','THREAD_START_FAILURE']
            suffixes += ['CORRUPT_LANE='+str(i*lanes+lanes-1) for i in range(8)]
            for suffix in suffixes:
                flag='LVS_CPU_HELPER_TEST_THREAD_START_FAILURE' if suffix=='THREAD_START_FAILURE' else 'LVS_CPU_HELPER_TEST_HALF_'+suffix
                if suffix=='THREAD_START_FAILURE' and len(os.sched_getaffinity(0))<2:continue
                b=_build(tmp,'failure','-DLVS_CPU_HELPER_TEST_HALF','-D'+flag)
                w=_run(b,tmp,kernel=kernel,fail=suffix!='CORRUPT_FINAL',workers=2 if suffix=='THREAD_START_FAILURE' else 1)
                if suffix=='INTERRUPT':assert worker_result_successful(w) and w['threads_detail'][0]['interrupted_arithmetic_blocks']>0,w
                else:
                    assert w['observed_exit_code']==4 and not worker_result_successful(w),w
                    if suffix=='CORRUPT_FINAL':assert w['initial_verification_completed'] and not w['final_verification_completed']
        b=_build(tmp,'disabled','-DLVS_CPU_HELPER_TEST_HALF','-DLVS_CPU_HELPER_TEST_DISABLE_HALF')
        for k in KERNELS:assert subprocess.run([str(b),'--kernel-flavor',k,'--print-kernel-flavor'],capture_output=True).returncode==3


def run_half_selection_build_checks():
    from Modules.lvs_cpu_architecture import cpu_instruction_set_policy,python_cpu_fallback_policy,resolve_cpu_instruction_intent
    from Modules.lvs_cpu_targeting import common_kernel_capabilities,select_common_kernel
    from Modules.lvs_native_helpers import resolve_native_helper_status,native_helper_binary_ready
    for kernel in KERNELS:
        assert cpu_instruction_set_policy('arm64',kernel)['allowed'] and not python_cpu_fallback_policy('arm64',kernel)['allowed']
        assert not cpu_instruction_set_policy('x86_64',kernel)['allowed']
        for targets in [[1],[1,17],list(range(256))]:
            caps={cpu:['scalar','neon',kernel] for cpu in targets}
            common=common_kernel_capabilities(targets,caps)['common_kernel_flavors']
            assert select_common_kernel(architecture='arm64',requested_mode=kernel,common_flavors=common)==kernel
            caps[targets[-1]]=['scalar','neon']
            assert not select_common_kernel(architecture='arm64',requested_mode=kernel,common_flavors=common_kernel_capabilities(targets,caps)['common_kernel_flavors'])
        for intent in ['baseline_vector','high_throughput_vector','highest_verified_vector']:
            assert resolve_cpu_instruction_intent('arm64',intent,['scalar','neon','neon_fp32_fma',*KERNELS])['resolved_kernel_flavor'] not in KERNELS
    regions=['DOTPROD','I8MM','FP16','FHM']
    with TemporaryDirectory(prefix='lvs-half-build-') as tmp:
        source=Path(tmp)/'cpu_stress_helper.c';source.write_text('fixture');binary=source.with_name('cpu_stress_helper_arm64')
        for mask in range(16):
            binary.unlink(missing_ok=True);calls=[];supported={r for i,r in enumerate(regions) if mask&(1<<i)}
            def build(cmd):
                calls.append(cmd);enabled={r for r in regions if '-DLVS_CPU_HELPER_ENABLE_'+r in cmd}
                ok=enabled<=supported and '-DLVS_CPU_HELPER_ENABLE_SVE' not in cmd
                if ok:binary.write_text('fixture');binary.chmod(0o700)
                return SimpleNamespace(returncode=0 if ok else 1,stderr='' if ok else 'optional region unavailable')
            w=resolve_native_helper_status(source=source,binary=binary,compiler='gcc',reason_label='CPU',build_runner=build)
            assert w['available'] and len(calls)<=21,w
            for r in regions:assert w[r.lower()+'_build']['status']==('compiled' if r in supported else 'unavailable'),w
            assert not any('-march=' in a for cmd in calls for a in cmd)
        header=source.with_name('cpu_half_kernel.h');header.write_text('fixture');os.utime(header,(binary.stat().st_mtime+1,)*2)
        assert not native_helper_binary_ready(source,binary)


def run_half_reporting_progress_checks():
    from Modules.lvs_report_data import _reported_software_verification
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    for kernel in KERNELS:
        good=_valid(kernel);assert worker_result_successful(good)
        assert _reported_software_verification(good,kernel)['software_verification_satisfied']
        changes=[('verification_contract','neon_fp32_fma_v1'),('comparison','tolerance'),('accumulator_bits',16 if kernel=='neon_fhm' else 32),('active_lanes',4.0),('fma_rounds_per_block',255),('witness_rounds_per_block',0),('fhm_mapping','wrong'),('operation_family','fp32_fused_multiply_add'),('observed_exit_code',-9),('threads_detail',[]),('arithmetic_verified_blocks',31),('verification_complete',False)]
        for key,value in changes:
            bad=deepcopy(good);bad[key]=value;assert not worker_result_successful(bad),(key,bad)
            assert not _reported_software_verification(bad,kernel)['software_verification_satisfied']
            assert preserve_legacy_worker_evidence_contract(bad)==bad
        for key,value in [('isa_hwcap',3),('isa_hwcap',True),('fpcr',True),('fpcr',1<<19),('fpcr',1<<24),('fpcr',1<<22),('fpcr',1<<26),('fpcr',1),('fpcr',2),('fpcr',1<<8),('observed_cpu',9),('affinity_applied',False),('final_verification_completed',False),('error_count',1)]:
            bad=deepcopy(good);bad['threads_detail'][0][key]=value;assert not worker_verification_satisfied(bad),(key,value)
        with TemporaryDirectory(prefix='lvs-half-progress-') as tmp:
            path=Path(tmp)/'progress.jsonl';w=deepcopy(good);w['verified_progress']=dict(contract=kernel+'_progress_v1',path=str(path))
            rows=[]
            for i,count in enumerate([0,3,12,21,30]):
                rows.append(dict(contract=kernel+'_progress_v1',kernel_flavor=kernel,operation_family=w['operation_family'],sequence=i,pid=42,
                    state=['startup','initial','ongoing','ongoing','final_complete'][i],monotonic_seconds=10.+i*2,realtime_seconds=1000.+i*2,
                    clock_pair_uncertainty_seconds=0.,aggregate_verified_blocks=count,threads=[dict(thread_index=0,cpu_id=2,
                    published_monotonic_seconds=10.+i*2,verified_blocks=count,error_count=0,initial_verified=i>0,periodic_verified=i>1,
                    final_verified=i==4,affinity_applied=True,observed_cpu=2)]))
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            window=SimpleNamespace(started_monotonic=10.,ended_monotonic=18.,trim_start_seconds=0,trim_end_seconds=0,analysis_intent='sustained',analysis_minimum_usable_seconds=8,analysis_evidence={'quality':'sufficient'})
            r=analyze_verified_progress(w,window);assert r['quality']=='sufficient',r
            assert r['derived_stress_lane_fmas_per_second']==30/8*8*w['active_lanes']*256
            rows[-1]['aggregate_verified_blocks']=31;path.write_text(''.join(json.dumps(r)+'\n' for r in rows));assert analyze_verified_progress(w,window)['quality']=='insufficient'


def run_half_frontend_checks():
    for kernel in KERNELS:_frontend_checks(kernel)
