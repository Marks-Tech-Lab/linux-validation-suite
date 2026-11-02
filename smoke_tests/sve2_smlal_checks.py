"""SVE2 software evidence: cross-emission and labelled integer emulation only."""
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

from Modules.lvs_worker_integrity import worker_result_successful, worker_verification_satisfied, worker_integrity_error_count

ROOT = Path(__file__).resolve().parents[1]
KERNEL = 'sve2_smlal'
OPERATION = 's16_widening_multiply_accumulate_bottom_top'


def _build(directory, name, *flags):
    path = Path(directory)/name
    subprocess.run(['gcc','-O3','-std=c11','-pthread',*flags,str(ROOT/'native/cpu_stress_helper.c'),'-o',str(path)],
                   check=True,capture_output=True,timeout=60)
    return path


def _run(binary, directory, vl=16, *, fail=False, workers=1):
    path = Path(directory)/(str(time.monotonic_ns())+'.json')
    cpus = sorted(os.sched_getaffinity(0))[:workers]
    proc = subprocess.Popen([str(binary),'--kernel-flavor',KERNEL,'--threads',str(len(cpus)),
        '--cpu-ids',','.join(map(str,cpus)),'--result-file',str(path)],
        env=dict(os.environ,LVS_TEST_SVE2_VL_BYTES=str(vl)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        if not fail:
            deadline=time.monotonic()+10
            sidecar=Path(str(path)+'.progress.jsonl')
            while time.monotonic()<deadline and proc.poll() is None:
                if sidecar.exists() and '"state":"initial"' in sidecar.read_text():
                    break
                time.sleep(.02)
            assert proc.poll() is None,proc.communicate()
            proc.terminate()
        out,err=proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill();proc.communicate(timeout=5)
    data=json.loads(path.read_text());data.update(observed_exit_code=proc.returncode,result_path=str(path))
    return data


def _valid(vl=16):
    return dict(kind='cpu',status='ok',observed_exit_code=0,mode=KERNEL,kernel_flavor=KERNEL,
        verification_required=True,verification_complete=True,verification_version=1,
        verification_contract=KERNEL+'_v1',verification_method='wide_integer_smlal_reference_modulo_2_32',
        operation_family=OPERATION,execution_implementation='aarch64_sve2_intrinsics',actual_isa='sve2',
        isa_capability_source='linux_aarch64_hwcap_common_set',vector_length_source='linux_prctl_pr_sve_get_vl_per_thread',
        bottom_top_mapping='even_odd_halfwords',accumulator_chains=8,multiply_accumulate_rounds_per_block=256,
        initial_verification_completed=True,periodic_verification_completed=True,final_verification_completed=True,
        requested_thread_count=1,actual_worker_count=1,target_cpu_ids=[2],affinity_attempted_count=1,
        affinity_applied_count=1,affinity_failed_count=0,error_count=0,verify_passes=30,arithmetic_verified_blocks=30,
        threads_detail=[dict(thread_index=0,affinity_target_cpu=2,observed_cpu=2,affinity_applied=True,
            affinity_required=True,error_count=0,verify_passes=30,arithmetic_verified_blocks=30,
            initial_verification_completed=True,periodic_verification_completed=True,final_verification_completed=True,
            vector_length_bytes=vl,vector_length_bits=vl*8,vector_length_flags=0,vector_length_errno=0,
            active_int32_lanes=vl//4,isa_hwcap=(1<<22)|3,isa_hwcap2=2)])


def run_sve2_reference_instruction_checks():
    with TemporaryDirectory(prefix='lvs-sve2-instructions-') as directory:
        # AArch64 GCC when available; otherwise cross-compile the actual full
        # production translation unit using optional Zig/Clang (no execution).
        cross=shutil.which('aarch64-linux-gnu-gcc')
        zig=importlib.util.find_spec('ziglang')
        if cross or zig:
            compiler=[cross] if cross else [sys.executable,'-m','ziglang','cc','-target','aarch64-linux-gnu']
            assembly=Path(directory)/'worker.s'
            env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(Path(directory)/'zig-cache'))
            command=[*compiler,'-O3','-std=c11','-pthread','-DLVS_CPU_HELPER_ENABLE_SVE2','-S',
                     str(ROOT/'native/cpu_stress_helper.c'),'-o',str(assembly)]
            subprocess.run(command,env=env,check=True,capture_output=True,timeout=120)
            text=assembly.read_text()
            body=text.split('execute_sve2_smlal_block:',1)[1].split('.size',1)[0]
            assert len(re.findall(r'\bsmlalb\s+z\d+\.s,\s*z\d+\.h,\s*z\d+\.h',body))==4
            assert len(re.findall(r'\bsmlalt\s+z\d+\.s,\s*z\d+\.h,\s*z\d+\.h',body))==4
            assert 'cntw' in body and 'st1w' in body
            # Full AArch64 baseline also compiles with optional regions absent.
            command=[*compiler,'-O3','-std=c11','-pthread','-S',str(ROOT/'native/cpu_stress_helper.c'),'-o',str(assembly)]
            subprocess.run(command,env=env,check=True,capture_output=True,timeout=120)
            assert not re.search(r'\bsmlal[bt]\s+z',assembly.read_text())
        elif os.uname().machine=='aarch64':
            assembly=Path(directory)/'worker.s'
            subprocess.run(['gcc','-O3','-std=c11','-pthread','-DLVS_CPU_HELPER_ENABLE_SVE2','-S',
                            str(ROOT/'native/cpu_stress_helper.c'),'-o',str(assembly)],check=True,capture_output=True)
            assert 'smlalb' in assembly.read_text() and 'smlalt' in assembly.read_text()
        else:
            print('SVE2 emission unavailable: install AArch64 GCC or optional ziglang; emulation is not instruction proof')
        source=Path(directory)/'reference.c'
        source.write_text('#define main fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            'uint32_t ref(uint32_t i,int16_t a,int16_t b){return sve2_reference(i,a,b);}\n'
            'int cap(uint64_t h,uint64_t h2){return sve2_capability(h,h2);}\n'
            'void cases(uint32_t seed,int lanes,uint32_t*out){sve2_case_t c;prepare_sve2_case(&c,seed,lanes);memcpy(out,c.expected,8*lanes*4);}\n')
        lib=Path(directory)/'reference.so'
        subprocess.run(['gcc','-O2','-pthread','-fPIC','-shared',str(source),'-o',str(lib)],check=True,capture_output=True)
        dll=ctypes.CDLL(str(lib));dll.ref.argtypes=[ctypes.c_uint32,ctypes.c_int16,ctypes.c_int16];dll.ref.restype=ctypes.c_uint32
        for initial in [0,0x7fffffff,0x80000000,0xffffffff]:
            for a in [-32768,-1,0,1,32767]:
                for b in [-32768,-1,0,1,32767]:assert dll.ref(initial,a,b)==(initial+a*b*256)&0xffffffff
        dll.cases.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.POINTER(ctypes.c_uint32)]
        extremes=[-32768,32767,-1,0,1,-12345,23456]
        for vl in [16,32,48,64,128,256]:
            lanes=vl//4
            for seed in [1,2,3,4,17]:
                out=(ctypes.c_uint32*(8*lanes))();dll.cases(seed,lanes,out)
                for chain in range(8):
                    for lane in range(lanes):
                        n=chain*lanes+lane;j=(chain//2)*2*lanes+lane*2+chain%2
                        a=extremes[(j+seed)%7];b=extremes[(j*3+seed+1)%7]
                        initial=0x80000000 if n%2 else (0xffffffff-seed)&0xffffffff
                        assert out[n]==(initial+a*b*256)&0xffffffff
        dll.cap.argtypes=[ctypes.c_uint64,ctypes.c_uint64]
        assert dll.cap((1<<22)|3,2)
        for h,h2 in [(3,2),((1<<22)|3,0),((1<<22)|1,2),(0,0)]:assert not dll.cap(h,h2)


def run_sve2_native_lifecycle_checks():
    with TemporaryDirectory(prefix='lvs-sve2-lifecycle-') as directory:
        baseline=_build(directory,'baseline')
        for args in [['--mode',KERNEL],['--kernel-flavor',KERNEL]]:
            assert subprocess.run([str(baseline),*args,'--print-kernel-flavor'],capture_output=True).returncode==3
        assert KERNEL not in subprocess.check_output([str(baseline),'--print-supported-kernels'],text=True)
        emulator=_build(directory,'emulator','-DLVS_CPU_HELPER_TEST_SVE2')
        for vl in [16,32,48,256]:
            w=_run(emulator,directory,vl);assert worker_result_successful(w),w
            assert w['execution_implementation']=='test_integer_emulation' and w['actual_isa']=='test_integer_emulation'
            assert w['threads_detail'][0]['vector_length_bytes']==vl
        for vl in [-1,0,17,272]:
            w=_run(emulator,directory,vl,fail=True);assert w['observed_exit_code']==4 and not worker_result_successful(w)
        for name in ['CORRUPT','CORRUPT_TOP','MIGRATION','INTERRUPT','MIXED_VL']:
            binary=_build(directory,name,'-DLVS_CPU_HELPER_TEST_SVE2','-DLVS_CPU_HELPER_TEST_SVE2_'+name)
            w=_run(binary,directory,fail=name!='MIXED_VL',workers=2 if name=='MIXED_VL' else 1)
            if name in ['INTERRUPT','MIXED_VL']:
                assert worker_result_successful(w),w
                if name=='INTERRUPT':assert w['threads_detail'][0]['interrupted_arithmetic_blocks']>0
                elif len(w['threads_detail'])==2:assert {r['vector_length_bytes'] for r in w['threads_detail']}=={32,48}
            else:
                assert w['observed_exit_code']==4 and not worker_result_successful(w),w
        disabled=_build(directory,'disabled','-DLVS_CPU_HELPER_TEST_SVE2','-DLVS_CPU_HELPER_TEST_DISABLE_SVE2')
        assert subprocess.run([str(disabled),'--mode',KERNEL,'--print-kernel-flavor'],capture_output=True).returncode==3
        partial=_build(directory,'partial','-DLVS_CPU_HELPER_TEST_SVE2','-DLVS_CPU_HELPER_TEST_THREAD_START_FAILURE')
        if len(os.sched_getaffinity(0))>1:
            w=_run(partial,directory,fail=True,workers=2);assert not worker_result_successful(w) and w['actual_worker_count']<w['requested_thread_count']


def run_sve2_integrity_reporting_checks():
    from Modules.lvs_report_data import _reported_software_verification,_stage_shell
    from Modules.lvs_report_html import _stage_card
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    for vl in [16,48,256]:
        good=_valid(vl);assert worker_result_successful(good)
        assert _reported_software_verification(good,KERNEL)['software_verification_satisfied']
        mutations=[lambda w:w.update(verification_contract='sve_fp32_fma_v1'),lambda w:w.update(actual_isa='sve'),
            lambda w:w.update(verification_required=False),lambda w:w.update(verification_complete=False),
            lambda w:w.update(arithmetic_verified_blocks=31),lambda w:w.update(observed_exit_code=-9),
            lambda w:w.update(accumulator_chains=True),lambda w:w.update(error_count=-1),
            lambda w:w.update(bottom_top_mapping='low_half_high_half'),lambda w:w.update(threads_detail=[])]
        for key,value in [('isa_hwcap2',0),('isa_hwcap',3),('vector_length_errno',22),('vector_length_bytes',17),
                          ('active_int32_lanes',0),('vector_length_bits',128.0),('observed_cpu',1),
                          ('final_verification_completed',False),('periodic_verification_completed',False),('error_count',1),
                          ('first_error',{'kind':'sve2_smlal_mismatch'})]:
            mutations.append(lambda w,key=key,value=value:w['threads_detail'][0].update({key:value}))
        for mutate in mutations:
            bad=deepcopy(good);mutate(bad)
            assert not worker_verification_satisfied(bad),bad
            assert not worker_result_successful(bad) and worker_integrity_error_count([bad])>0
            assert not _reported_software_verification(bad,KERNEL)['software_verification_satisfied']
            assert preserve_legacy_worker_evidence_contract(bad)==bad
        assert not _reported_software_verification({},KERNEL)['software_verification_satisfied']
        assert not _reported_software_verification(good,'sve_fp32_fma')['software_verification_satisfied']
        stage=_stage_shell(0,dict(stage_id='s',started_monotonic=0,ended_monotonic=90,
            cpu_kernel_flavor=KERNEL,cpu_selection_evidence={'selection_reason':'explicit SVE2; physical acceptance separate'},worker_results=[good]))
        assert KERNEL in _stage_card(stage,{})
        assert stage['cpu_instruction_selection']['workers'][0]['software_verification_status']=='verified'


def run_sve2_selection_build_checks():
    from Modules.lvs_cpu_architecture import cpu_instruction_set_policy,python_cpu_fallback_policy,resolve_cpu_instruction_intent
    from Modules.lvs_cpu_targeting import common_kernel_capabilities,select_common_kernel
    from Modules.lvs_cpu_execution import cpu_candidate_kernel_flavors
    from Modules.lvs_native_helpers import resolve_native_helper_status,native_helper_binary_ready
    for machine in ['x86_64','riscv64','unknown']:assert not cpu_instruction_set_policy(machine,KERNEL)['allowed']
    assert cpu_instruction_set_policy('arm64',KERNEL)['allowed'] and not python_cpu_fallback_policy('arm64',KERNEL)['allowed']
    for targets in [[2],[1,17],list(range(0,256,2))]:
        caps={cpu:['scalar','neon',KERNEL] for cpu in targets}
        common=common_kernel_capabilities(targets,caps)
        assert select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common['common_kernel_flavors'])==KERNEL
        caps.pop(targets[-1]);common=common_kernel_capabilities(targets,caps)
        assert not select_common_kernel(architecture='arm64',requested_mode=KERNEL,common_flavors=common['common_kernel_flavors'])
    caps=['scalar','neon','neon_fp32_fma','sve_fp32_fma',KERNEL]
    for intent in ['baseline_vector','high_throughput_vector','highest_verified_vector']:
        assert resolve_cpu_instruction_intent('arm64',intent,caps)['resolved_kernel_flavor']!=KERNEL
    assert KERNEL not in cpu_candidate_kernel_flavors(helper_available=True,policy='max_power',resolved_mode='neon',supports_kernel_flavor=lambda _:True,architecture='arm64')
    with TemporaryDirectory(prefix='lvs-sve2-build-') as directory:
        for succeed in ['all','sve','baseline']:
            source=Path(directory)/'cpu_stress_helper.c';source.write_text('fixture')
            binary=Path(directory)/'cpu_stress_helper_arm64';binary.unlink(missing_ok=True);calls=[]
            def build(cmd):
                calls.append(cmd)
                ok=(succeed=='all' or ('-DLVS_CPU_HELPER_ENABLE_SVE2' not in cmd and (succeed=='sve' or '-DLVS_CPU_HELPER_ENABLE_SVE' not in cmd)))
                if ok:binary.write_text('fixture');binary.chmod(0o700)
                return SimpleNamespace(returncode=0 if ok else 1,stdout='',stderr='' if ok else 'optional compilation unavailable')
            result=resolve_native_helper_status(source=source,binary=binary,compiler='gcc',reason_label='CPU',build_runner=build)
            assert result['available'] and len(calls)=={'all':1,'sve':3,'baseline':5}[succeed]
            assert result['sve2_build']['status']==('compiled' if succeed=='all' else 'unavailable')
            assert not any('-march=' in arg for cmd in calls for arg in cmd)
        header=source.with_name('cpu_sve2_kernel.h');header.write_text('changed header')
        os.utime(header,(binary.stat().st_mtime+1,)*2);assert not native_helper_binary_ready(source,binary)


def run_sve2_progress_checks():
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    from Modules.lvs_report_html import _stage_card
    for vl in [16,48,256]:
        with TemporaryDirectory(prefix='lvs-sve2-progress-') as directory:
            w=_valid(vl);path=Path(directory)/'p.jsonl'
            w['verified_progress']=dict(contract=KERNEL+'_progress_v1',path=str(path),snapshot_count=5,persistence_error=False)
            rows=[]
            for i,count in enumerate([0,3,12,21,30]):
                rows.append(dict(contract=KERNEL+'_progress_v1',kernel_flavor=KERNEL,operation_family=OPERATION,
                    sequence=i,pid=42,state=['startup','initial','ongoing','ongoing','final_complete'][i],
                    monotonic_seconds=10.+2*i,realtime_seconds=1000.+2*i,clock_pair_uncertainty_seconds=0.,aggregate_verified_blocks=count,
                    threads=[dict(thread_index=0,cpu_id=2,published_monotonic_seconds=10.+2*i,verified_blocks=count,error_count=0,
                        initial_verified=i>0,periodic_verified=i>1,final_verified=i==4,affinity_applied=True,observed_cpu=2,
                        vector_length_bytes=vl,active_int32_lanes=vl//4)]))
            def write():path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            write();window=SimpleNamespace(started_monotonic=10.,ended_monotonic=18.,trim_start_seconds=0,trim_end_seconds=0,
                analysis_intent='sustained',analysis_minimum_usable_seconds=8,analysis_evidence={'quality':'sufficient'})
            result=analyze_verified_progress(w,window);assert result['quality']=='sufficient',result
            assert result['derived_signed_products_per_second']==30/8*8*(vl//4)*256
            assert 'derived_stress_lane_fma_count' not in result['threads'][0]
            rows[2]['threads'][0]['active_int32_lanes']+=1;write()
            assert analyze_verified_progress(w,window)['quality']=='insufficient'
            rows[2]['threads'][0]['active_int32_lanes']-=1
            rows[-1]['state']='interrupted';write();assert not analyze_verified_progress(w,window)['final_snapshot_complete']


def run_sve2_frontend_checks():
    import contextlib,io
    from smoke_tests.configuration_workflow_checks import Service,_source
    from smoke_tests.cli_configuration_checks import Host
    from Modules.lvs_cli_run_setup import RunSetupCliAdapter
    from Modules.lvs_profile_loader import ProfileLoader
    from Modules.lvs_cpu_power_selection import power_cpu_candidate_inventory
    from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
    from Modules.lvs_profile_models import ModuleCpu
    with TemporaryDirectory(dir=ROOT) as directory,contextlib.redirect_stdout(io.StringIO()) as output:
        service=Service(Path(directory));source=_source(service);before=source.read_bytes()
        setup=service.create_run_setup(source);edit=service.run_setup_stage_edit(setup)
        fields=service.stage_configuration_settings(edit,0);slot=next(i+1 for i,f in enumerate(fields) if f.key=='cpu_instruction')
        service.apply_stage_configuration(edit,0,'cpu_instruction',KERNEL)
        profile=service.profile_loader.load_profile(source);host=Host(service,['o','5','1',str(slot),KERNEL,'','4','u'])
        cli=RunSetupCliAdapter(host);labels=service.profile_loader.load_segment_labels(source,profile)
        setup=cli._create_run_setup_state(source,profile,labels)
        cli._run_setup_review_loop(cli._build_run_setup_review_controller(setup),setup,profile,labels)
        assert ProfileLoader.profile_payload(profile)==ProfileLoader.profile_payload(edit.profile)
        assert profile.stages[0].modules.cpu.instruction_set==KERNEL and profile.stages[0].modules.cpu.instruction_intent==''
        assert source.read_bytes()==before and service.create_run_setup(source).profile.stages[0].modules.cpu.instruction_set!=KERNEL
    class Runner(WorkloadCpuMemoryMixin):
        def _cpu_machine(self):return 'arm64'
        def _cpu_helper_status(self):return dict(available=True,path='/fixture/helper')
        def _cpu_target_plan(self,cpu):return dict(target_cpu_ids=[1,17])
        def _cpu_helper_supported_kernel_flavors(self,cpu_id=None):return ['scalar','neon',KERNEL]
        def _python_runtime(self):return '/fixture/python'
    runner=Runner();cpu=ModuleCpu(enabled=True,backend_preference='native',instruction_set=KERNEL)
    plan=runner._cpu_capability_plan(cpu);assert plan['selected_kernel_flavor']==KERNEL
    command=runner._cpu_command(cpu,backend_override='cpu_native_helper');assert command[command.index('--kernel-flavor')+1]==KERNEL
    assert command[command.index('--cpu-ids')+1]=='1,17'
    runner._cpu_helper_supported_kernel_flavors=lambda cpu_id=None:['scalar','neon']
    assert not runner._cpu_capability_plan(cpu)['selected_kernel_flavor'] and runner._cpu_command(cpu,backend_override='cpu_native_helper') is None
    viable,unavailable=power_cpu_candidate_inventory(architecture='arm64',availability={'cpu_native_helper':True},native_kernel_flavors=['scalar',KERNEL],selected_native_kernel='scalar')
    assert all(c.get('kernel_flavor')!=KERNEL for c in viable)
    assert any(KERNEL in c['candidate_id'] and 'explicit-only' in c['reason'] for c in unavailable)
