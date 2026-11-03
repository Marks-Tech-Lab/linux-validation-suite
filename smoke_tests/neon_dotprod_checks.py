"""DotProd software evidence: emitted production instructions and labelled emulation.

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
KERNEL='neon_dotprod'
OPERATION='s8_s8_and_u8_u8_dot_product_accumulate'


def _valid():
    from smoke_tests.sve2_smlal_checks import _valid as sve2_valid
    w=sve2_valid()
    for k in ['mode','kernel_flavor']: w[k]=KERNEL
    w.update(verification_contract=KERNEL+'_v1',verification_method='wide_integer_dot_reference_modulo_2_32',
        operation_family=OPERATION,execution_implementation='aarch64_neon_dotprod_intrinsics',actual_isa='asimddp',
        dot_rounds_per_block=256,active_int32_lanes=4,products_per_lane=4)
    for k in ['vector_length_source','multiply_accumulate_rounds_per_block','bottom_top_mapping']:w.pop(k)
    for row in w['threads_detail']:
        for k in list(row):
            if k.startswith('vector_length') or k in ['active_int32_lanes','isa_hwcap2']:row.pop(k)
        row['isa_hwcap']=(1<<20)|3
    return w


def _run(binary,directory,*,fail=False,workers=1,kernel=KERNEL):
    path=Path(directory)/(str(time.monotonic_ns())+'.json')
    cpus=sorted(os.sched_getaffinity(0))[:workers]
    proc=subprocess.Popen([str(binary),'--mode',kernel,'--kernel-flavor',kernel,'--threads',str(len(cpus)),
        '--cpu-ids',','.join(map(str,cpus)),'--result-file',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        if not fail:
            deadline=time.monotonic()+10;sidecar=Path(str(path)+'.progress.jsonl')
            while time.monotonic()<deadline and proc.poll() is None:
                if sidecar.exists() and '"state":"initial"' in sidecar.read_text():break
                time.sleep(.02)
            assert proc.poll() is None,proc.communicate()
            proc.terminate()
        out,err=proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:proc.kill();proc.communicate(timeout=5)
    w=json.loads(path.read_text());w.update(observed_exit_code=proc.returncode,result_path=str(path))
    return w


def run_dotprod_reference_instruction_checks():
    with TemporaryDirectory(prefix='lvs-dotprod-emission-') as directory:
        cross=shutil.which('aarch64-linux-gnu-gcc')
        if cross or importlib.util.find_spec('ziglang') or os.uname().machine=='aarch64':
            compiler=[cross or 'gcc'] if cross or os.uname().machine=='aarch64' else [sys.executable,'-m','ziglang','cc','-target','aarch64-linux-gnu']
            asm=Path(directory)/'worker.s';env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(Path(directory)/'cache'))
            for enabled in [True,False]:
                command=[*compiler,'-O3','-std=c11','-pthread',*(['-DLVS_CPU_HELPER_ENABLE_DOTPROD'] if enabled else []),
                         '-S',str(ROOT/'native/cpu_stress_helper.c'),'-o',str(asm)]
                subprocess.run(command,env=env,check=True,capture_output=True,timeout=120)
                text=asm.read_text()
                if enabled:
                    body=text.split('execute_neon_dotprod_block:',1)[1].split('.size',1)[0]
                    for mnemonic in ['sdot','udot']:
                        assert len(re.findall(r'\b'+mnemonic+r'\s+v\d+\.4s,\s*v\d+\.16b,\s*v\d+\.16b',body))==4,body
                    assert re.search(r'\bstr\s+q|\bstp\s+q',body),body
                else:assert not re.search(r'\b[su]dot\s+v',text)
        else:print('DotProd emission unavailable: optional AArch64 compiler required; emulation is not opcode proof')
        source=Path(directory)/'reference.c'
        source.write_text('#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            'uint32_t ref(uint32_t i,int8_t a,int8_t b,uint8_t c,uint8_t d,int u){int8_t sa[4]={a,a,a,a},sb[4]={b,b,b,b};uint8_t ua[4]={c,c,c,c},ub[4]={d,d,d,d};return dotprod_reference(i,sa,sb,ua,ub,u);}\n'
            'int cap(uint64_t h){return dotprod_capability(h);}\n'
            'void cases(uint32_t seed,uint32_t*out){dotprod_case_t c;prepare_dotprod_case(&c,seed);memcpy(out,c.expected,sizeof(c.expected));}\n')
        lib=Path(directory)/'reference.so'
        subprocess.run(['gcc','-O2','-pthread','-fPIC','-shared',str(source),'-o',str(lib)],check=True,capture_output=True)
        dll=ctypes.CDLL(str(lib));dll.ref.restype=ctypes.c_uint32
        dll.ref.argtypes=[ctypes.c_uint32,ctypes.c_int8,ctypes.c_int8,ctypes.c_uint8,ctypes.c_uint8,ctypes.c_int]
        for initial in [0,0x7fffffff,0x80000000,0xffffffff]:
            for a in [-128,-1,0,1,127]:
                for b in [-128,-1,0,1,127]:
                    assert dll.ref(initial,a,b,0,0,0)==(initial+4*a*b*256)&0xffffffff
            for a in [0,1,127,128,255]:
                for b in [0,1,127,128,255]:
                    assert dll.ref(initial,0,0,a,b,1)==(initial+4*a*b*256)&0xffffffff
        dll.cases.argtypes=[ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)]
        signed=[-128,127,-1,0,1,-63,97];unsigned=[0,255,1,128,127,254,17]
        for seed in [1,2,3,4,17,0xffffffff]:
            out=(ctypes.c_uint32*32)();dll.cases(seed,out)
            for n in range(32):
                initial=0x80000000 if n%2 else (0xffffffff-seed)&0xffffffff
                k=(n%16)*4
                dot=sum(signed[((k+j+seed)&0xffffffff)%7]*signed[(((k+j)*3+seed+1)&0xffffffff)%7] if n<16 else
                        unsigned[((k+j+seed)&0xffffffff)%7]*unsigned[(((k+j)*5+seed+2)&0xffffffff)%7] for j in range(4))
                assert out[n]==(initial+dot*256)&0xffffffff
        dll.cap.argtypes=[ctypes.c_uint64]
        assert dll.cap((1<<20)|3)
        for h in [0,3,1<<20,(1<<20)|1,(1<<20)|2]:assert not dll.cap(h)


def run_dotprod_native_lifecycle_checks():
    with TemporaryDirectory(prefix='lvs-dotprod-lifecycle-') as directory:
        baseline=_build(directory,'baseline')
        for args in [['--mode',KERNEL],['--kernel-flavor',KERNEL]]:
            assert subprocess.run([str(baseline),*args,'--print-kernel-flavor'],capture_output=True).returncode==3
        assert KERNEL not in subprocess.check_output([str(baseline),'--print-supported-kernels'],text=True)
        binary=_build(directory,'emulated','-DLVS_CPU_HELPER_TEST_DOTPROD')
        w=_run(binary,directory,workers=2);assert worker_result_successful(w),w
        assert w['execution_implementation']=='test_integer_emulation' and w['actual_isa']=='test_integer_emulation'
        assert w['actual_worker_count']==min(2,len(os.sched_getaffinity(0)))
        for suffix in ['CORRUPT','CORRUPT_UNSIGNED','CORRUPT_PERIODIC','CORRUPT_FINAL','CORRUPT_GUARD','CAPABILITY_LOST','MIGRATION','INTERRUPT','THREAD_START_FAILURE']:
            flag='LVS_CPU_HELPER_TEST_THREAD_START_FAILURE' if suffix=='THREAD_START_FAILURE' else 'LVS_CPU_HELPER_TEST_DOTPROD_'+suffix
            binary=_build(directory,suffix,'-DLVS_CPU_HELPER_TEST_DOTPROD','-D'+flag)
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
        binary=_build(directory,'disabled','-DLVS_CPU_HELPER_TEST_DOTPROD','-DLVS_CPU_HELPER_TEST_DISABLE_DOTPROD')
        assert subprocess.run([str(binary),'--mode',KERNEL,'--print-kernel-flavor'],capture_output=True).returncode==3


def run_dotprod_integrity_reporting_checks():
    from Modules.lvs_report_data import _reported_software_verification,_stage_shell
    from Modules.lvs_report_html import _stage_card
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    good=_valid();assert worker_result_successful(good)
    assert _reported_software_verification(good,KERNEL)['software_verification_satisfied']
    changes=[('verification_contract','neon_fp32_fma_v1'),('verification_required',False),('verification_complete',False),
             ('actual_isa','neon'),('active_int32_lanes',8),('operation_family','u8_s8_dot_product_accumulate'),
             ('arithmetic_verified_blocks',31),('observed_exit_code',-9),('threads_detail',[]),('error_count',1),
             ('execution_implementation','aarch64_sve2_intrinsics'),('dot_rounds_per_block',128)]
    for key,value in changes:
        bad=deepcopy(good);bad[key]=value
        assert not worker_verification_satisfied(bad) and not worker_result_successful(bad),(key,bad)
        assert not _reported_software_verification(bad,KERNEL)['software_verification_satisfied']
        assert preserve_legacy_worker_evidence_contract(bad)==bad
    for key,value in [('isa_hwcap',3),('isa_hwcap',-1),('isa_hwcap',True),('isa_hwcap',1<<64),
                      ('observed_cpu',3),('affinity_applied',False),('final_verification_completed',False),
                      ('periodic_verification_completed',False),('verify_passes',29),('error_count',1)]:
        bad=deepcopy(good);bad['threads_detail'][0][key]=value
        assert not worker_result_successful(bad),(key,bad)
    stage=_stage_shell(0,dict(stage_id='s',started_monotonic=0,ended_monotonic=90,cpu_kernel_flavor=KERNEL,cpu_selection_evidence={"selection_reason":"explicit DotProd; physical acceptance pending"},worker_results=[good]))
    assert KERNEL in _stage_card(stage,{}) and stage['cpu_instruction_selection']['workers'][0]['software_verification_status']=='verified'
    assert preserve_legacy_worker_evidence_contract(good)==good


def run_dotprod_selection_build_checks():
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
    with TemporaryDirectory(prefix='lvs-dotprod-build-') as directory:
        for supported in [('dot','sve','sve2'),('dot',),('sve','sve2'),()]:
            source=Path(directory)/'cpu_stress_helper.c';source.write_text('fixture')
            binary=source.with_name('cpu_stress_helper_arm64');binary.unlink(missing_ok=True);calls=[]
            def build(cmd):
                calls.append(cmd)
                flags={'dot':'-DLVS_CPU_HELPER_ENABLE_DOTPROD','sve':'-DLVS_CPU_HELPER_ENABLE_SVE','sve2':'-DLVS_CPU_HELPER_ENABLE_SVE2'}
                ok=all(flag not in cmd or key in supported for key,flag in flags.items())
                if ok:binary.write_text('fixture');binary.chmod(0o700)
                return SimpleNamespace(returncode=0 if ok else 1,stderr='' if ok else 'optional region unavailable')
            w=resolve_native_helper_status(source=source,binary=binary,compiler='gcc',reason_label='CPU',build_runner=build)
            assert w['available'] and w['dotprod_build']['status']==('compiled' if 'dot' in supported else 'unavailable'),w
            assert not any('-march=' in arg for cmd in calls for arg in cmd)
            header=source.with_name('cpu_dotprod_kernel.h');header.write_text('new');os.utime(header,(binary.stat().st_mtime+1,)*2)
            assert not native_helper_binary_ready(source,binary);header.unlink()


def run_dotprod_progress_checks():
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    with TemporaryDirectory(prefix='lvs-dotprod-progress-') as directory:
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
        assert result['derived_byte_products_per_second']==30/8*8*4*256*4
        assert 'derived_stress_lane_fma_count' not in result['threads'][0]
        rows[-1]['threads'][0]['verified_blocks']=31;write();assert analyze_verified_progress(w,window)['quality']=='insufficient'


def run_dotprod_frontend_checks():
    _frontend_checks(KERNEL)


def _frontend_checks(kernel):
    # Exercise the actual shared mutation, CLI adapter and command-planning paths
    # already used by SVE2. Keep family identity separate in this fixture.
    import contextlib,io
    from smoke_tests.configuration_workflow_checks import Service,_source
    from smoke_tests.cli_configuration_checks import Host
    from Modules.lvs_cli_run_setup import RunSetupCliAdapter
    from Modules.lvs_profile_loader import ProfileLoader
    from Modules.lvs_cpu_power_selection import power_cpu_candidate_inventory
    from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
    from Modules.lvs_profile_models import ModuleCpu
    with TemporaryDirectory(dir=ROOT) as directory,contextlib.redirect_stdout(io.StringIO()):
        service=Service(Path(directory));source=_source(service);before=source.read_bytes()
        setup=service.create_run_setup(source);edit=service.run_setup_stage_edit(setup)
        fields=service.stage_configuration_settings(edit,0);slot=next(i+1 for i,f in enumerate(fields) if f.key=='cpu_instruction')
        service.apply_stage_configuration(edit,0,'cpu_instruction',kernel)
        profile=service.profile_loader.load_profile(source);host=Host(service,['o','5','1',str(slot),kernel,'','4','u'])
        cli=RunSetupCliAdapter(host);labels=service.profile_loader.load_segment_labels(source,profile)
        setup=cli._create_run_setup_state(source,profile,labels)
        cli._run_setup_review_loop(cli._build_run_setup_review_controller(setup),setup,profile,labels)
        assert ProfileLoader.profile_payload(profile)==ProfileLoader.profile_payload(edit.profile)
        assert profile.stages[0].modules.cpu.instruction_set==kernel and profile.stages[0].modules.cpu.instruction_intent==''
        assert source.read_bytes()==before and service.create_run_setup(source).profile.stages[0].modules.cpu.instruction_set!=kernel
    class Runner(WorkloadCpuMemoryMixin):
        def _cpu_machine(self):return 'arm64'
        def _cpu_helper_status(self):return dict(available=True,path='/fixture/helper')
        def _cpu_target_plan(self,cpu):return dict(target_cpu_ids=[1,17])
        def _cpu_helper_supported_kernel_flavors(self,cpu_id=None):return ['scalar','neon',kernel]
        def _python_runtime(self):return '/fixture/python'
    runner=Runner();cpu=ModuleCpu(enabled=True,backend_preference='native',instruction_set=kernel)
    plan=runner._cpu_capability_plan(cpu);assert plan['selected_kernel_flavor']==kernel
    cmd=runner._cpu_command(cpu,backend_override='cpu_native_helper');assert cmd[cmd.index('--kernel-flavor')+1]==kernel
    assert cmd[cmd.index('--cpu-ids')+1]=='1,17'
    runner._cpu_helper_supported_kernel_flavors=lambda cpu_id=None:['scalar','neon']
    assert not runner._cpu_capability_plan(cpu)['selected_kernel_flavor'] and runner._cpu_command(cpu,backend_override='cpu_native_helper') is None
    viable,unavailable=power_cpu_candidate_inventory(architecture='arm64',availability={'cpu_native_helper':True},native_kernel_flavors=['scalar',kernel],selected_native_kernel='scalar')
    assert all(c.get('kernel_flavor')!=kernel for c in viable)
    assert any(kernel in c['candidate_id'] and 'explicit-only' in c['reason'] for c in unavailable)
