"""VNNI software contracts: real emitted instructions, integer-only execution fixtures.

No target-specific stress is executed on the development host. Native lifecycle
fixtures explicitly advertise test_integer_emulation and are not ISA acceptance.
"""
from __future__ import annotations

from copy import deepcopy
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

from Modules.lvs_worker_integrity import worker_verification_satisfied, worker_result_successful, worker_integrity_error_count

ROOT = Path(__file__).resolve().parents[1]
KERNELS = ("avx_vnni", "avx512_vnni")


def _build(directory, name, *flags):
    compiler = shutil.which("gcc")
    assert compiler, "VNNI regressions require the normal GCC compiler"
    path = Path(directory)/name
    subprocess.run([compiler, "-O3", "-std=c11", "-pthread", *flags,
                    str(ROOT/"native/cpu_stress_helper.c"), "-o", str(path)],
                   check=True, capture_output=True, timeout=60)
    return path


def _emulated_run(binary, directory, kernel, *, failure=False, workers=2):
    path = Path(directory)/(kernel+".json")
    cpus = sorted(os.sched_getaffinity(0))[:workers]
    process = subprocess.Popen([str(binary), "--kernel-flavor", kernel, "--threads", str(len(cpus)),
        "--cpu-ids", ",".join(map(str,cpus)), "--result-file", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if not failure:
            # Require real initial publications before cancellation, not a fixed
            # startup sleep that could conceal slow/failed initialization.
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                progress=Path(str(path)+".progress.jsonl")
                if progress.exists() and '"state":"initial"' in progress.read_text():
                    break
                if process.poll() is not None:
                    break
                time.sleep(.01)
            assert process.poll() is None, process.communicate()
            time.sleep(.05)
            process.terminate()
        out,err = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill(); process.communicate(timeout=5)
    result = json.loads(path.read_text())
    result["observed_exit_code"] = process.returncode
    result["result_path"] = str(path)
    return result


def _valid(kernel="avx_vnni"):
    wide=kernel=="avx512_vnni"
    return dict(kind="cpu", status="ok", kernel_flavor=kernel, requested_kernel_flavor=kernel,
        verification_contract=kernel+"_v1", verification_version=1, verification_required=True,
        verification_complete=True, verification_method="wide_integer_dot_reference_modulo_2_32",
        operation_family="u8_s8_dot_product_accumulate", execution_implementation="x86_vnni_intrinsics",
        actual_isa=kernel, isa_capability_source="per_cpu_affinity_pinned_cpuid", error_count=0,
        accumulator_chains=8, dot_rounds_per_block=256, active_int32_lanes=16 if wide else 8, products_per_lane=4,
        initial_verification_completed=True, periodic_verification_completed=True, final_verification_completed=True,
        requested_thread_count=1, actual_worker_count=1, target_cpu_ids=[2], verify_passes=30,
        arithmetic_verified_blocks=30, affinity_attempted_count=1, affinity_applied_count=1, affinity_failed_count=0,
        observed_exit_code=0,
        threads_detail=[dict(thread_index=0, affinity_target_cpu=2, observed_cpu=2, affinity_applied=True,
            affinity_required=True, error_count=0, verify_passes=30, arithmetic_verified_blocks=30,
            initial_verification_completed=True, periodic_verification_completed=True, final_verification_completed=True,
            vnni_capability=dict(xcr0=0xe6,cpuid_7_0_ebx=(1<<5)|(1<<16),cpuid_7_0_ecx=1<<11,
                                 cpuid_7_max_subleaf=1,cpuid_7_1_eax=1<<4))])


def run_vnni_reference_instruction_checks():
    with TemporaryDirectory(prefix="lvs_vnni_isa_") as directory:
        binary=_build(directory,"production")
        capability=json.loads(subprocess.check_output([str(binary),"--print-isa-capabilities"],text=True))
        if os.uname().machine == "x86_64":
            assert capability["hwcap"] is None and capability["hwcap2"] is None
            assert capability["current_vector_length_bytes"] is None and capability["sve_compiled"] is False
        # Real disassembly, never intrinsic names or helper math alone.
        for kernel,register,prefix in (("avx_vnni","ymm","c4"),("avx512_vnni","zmm","62")):
            if not capability.get(kernel+"_compiled"):
                supported=subprocess.check_output([str(binary),"--print-supported-kernels"],text=True)
                assert kernel not in supported
                print(f"Optional {kernel} instruction emission unavailable on this compiler/architecture")
                continue
            dis=subprocess.run(["objdump","-d","-M","intel", "--disassemble=execute_"+kernel+"_block",str(binary)],
                               capture_output=True,text=True,check=True,timeout=10).stdout
            instructions=[line for line in dis.splitlines() if "vpdpbusd " in line]
            assert len(instructions)==8,(kernel,dis)
            assert all(register in line and re.search(r":\s+"+prefix+r"\s",line) for line in instructions)
        # A shared-library harness exercises the independent C reference and
        # pure CPUID/XCR0 decoder without executing SIMD.
        source=Path(directory)/"reference.c"
        source.write_text('#define main lvs_fixture_main\n#include "'+str(ROOT/'native/cpu_stress_helper.c')+'"\n'
            'uint32_t reference(uint32_t x,const uint8_t*a,const int8_t*b){return vnni_reference(x,a,b);}\n'
            'int caps(int w,int os,uint64_t x,uint32_t b,uint32_t c,uint32_t max,uint32_t a){return vnni_capability(w,os,x,b,c,max,a);}\n')
        library=Path(directory)/"reference.so"
        subprocess.run(["gcc","-O2","-shared","-fPIC","-pthread",str(source),"-o",str(library)],check=True,capture_output=True)
        dll=ctypes.CDLL(str(library)); dll.reference.argtypes=[ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint8),ctypes.POINTER(ctypes.c_int8)]
        dll.reference.restype=ctypes.c_uint32
        for initial in (0,0x7fffffff,0x80000000,0xffffffff):
            for a in ((255,255,255,255),(0,1,127,255),(17,91,200,254)):
                for b in ((127,127,127,127),(-128,-128,-128,-128),(-128,127,-1,0)):
                    expected=(initial+256*sum(x*y for x,y in zip(a,b))) & 0xffffffff
                    assert dll.reference(initial,(ctypes.c_uint8*4)(*a),(ctypes.c_int8*4)(*b))==expected
        dll.caps.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,*([ctypes.c_uint32]*4)]
        # Decode missing subleaf, OSXSAVE/XCR0, AVX2, F and VNNI independently.
        narrow=[0,1,6,1<<5,0,1,1<<4]; wide=[1,1,0xe6,(1<<5)|(1<<16),1<<11,0,0]
        assert dll.caps(*narrow) and dll.caps(*wide)
        for base,positions in ((narrow,(1,2,3,5,6)),(wide,(1,2,3,4))):
            for pos in positions:
                bad=base.copy(); bad[pos]=0
                assert not dll.caps(*bad)
        disabled=_build(directory,"baseline","-DLVS_CPU_HELPER_DISABLE_VNNI")
        supported=subprocess.check_output([str(disabled),"--print-supported-kernels"],text=True)
        assert "scalar" in supported and all(k not in supported for k in KERNELS)
        for kernel in KERNELS:
            assert subprocess.run([str(disabled),"--mode",kernel,"--print-kernel-flavor"],capture_output=True).returncode==3


def run_vnni_native_lifecycle_checks():
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    from Modules.lvs_report_data import _reported_software_verification
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    with TemporaryDirectory(prefix="lvs_vnni_lifecycle_") as directory:
        binary=_build(directory,"emulator","-DLVS_CPU_HELPER_TEST_VNNI")
        for kernel in KERNELS:
            sub=Path(directory)/kernel; sub.mkdir()
            result=_emulated_run(binary,sub,kernel)
            assert result["observed_exit_code"]==0 and result["execution_implementation"]=="test_integer_emulation"
            assert worker_result_successful(result),result
            assert worker_integrity_error_count([result])==0
            assert preserve_legacy_worker_evidence_contract(result)==result
            assert _reported_software_verification(result,kernel)["software_verification_status"]=="verified"
            assert _reported_software_verification(result,KERNELS[1-KERNELS.index(kernel)])["software_verification_satisfied"] is False
            rows=[json.loads(line) for line in Path(str(sub/(kernel+".json"))+".progress.jsonl").read_text().splitlines()]
            assert rows[0]["state"]=="startup" and rows[-1]["state"]=="final_complete"
            assert all(row["operation_family"]=="u8_s8_dot_product_accumulate" for row in rows)
            assert sum(row["verified_blocks"] for row in rows[-1]["threads"])==result["arithmetic_verified_blocks"]
            window=SimpleNamespace(started_monotonic=rows[0]["monotonic_seconds"],ended_monotonic=rows[-1]["monotonic_seconds"],trim_start_seconds=0,trim_end_seconds=0)
            analysis=analyze_verified_progress(result,window)
            assert analysis["contract"]==kernel+"_progress_v1" and analysis["final_snapshot_complete"]
            assert all("derived_stress_lane_fma_count" not in row for row in analysis["threads"])
        for flag,failure in (("INTERRUPT",False),("CORRUPT",True)):
            sub=Path(directory)/flag;sub.mkdir()
            binary=_build(directory,flag+"-helper","-DLVS_CPU_HELPER_TEST_VNNI","-DLVS_CPU_HELPER_TEST_VNNI_"+flag)
            result=_emulated_run(binary,sub,"avx_vnni",failure=True,workers=1)
            if failure:
                assert result["observed_exit_code"]==4 and not worker_result_successful(result)
                assert any(r.get("first_error",{}).get("kind")=="vnni_mismatch" for r in result["threads_detail"])
            else:
                assert worker_result_successful(result)
                assert sum(r["interrupted_arithmetic_blocks"] for r in result["threads_detail"])>0


def run_vnni_integrity_reporting_checks():
    from Modules.lvs_report_data import _reported_software_verification, _stage_shell
    from Modules.lvs_report_html import _stage_card
    from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
    from Modules.lvs_report_helpers import summarize_cpu_memory_worker_results
    for kernel in KERNELS:
        good=_valid(kernel)
        assert worker_result_successful(good)
        assert preserve_legacy_worker_evidence_contract(good)==good
        assert _reported_software_verification(good,kernel)["software_verification_satisfied"]
        mutations=[lambda p:p.update(verification_contract="unknown"),lambda p:p.update(error_count=1),
            lambda p:p.update(actual_isa="avx2"),lambda p:p.update(verification_complete=False),
            lambda p:p.update(verification_required=False),lambda p:p.update(actual_worker_count=2),lambda p:p.update(observed_exit_code=-9),
            lambda p:p.update(affinity_applied_count=True),
            lambda p:p.update(initial_verification_completed=False),lambda p:p.update(periodic_verification_completed=False),
            lambda p:p.update(final_verification_completed=False),lambda p:p.update(arithmetic_verified_blocks=31),
            lambda p:p.update(requested_kernel_flavor="scalar"),lambda p:p.update(verification_version=True),
            lambda p:p["threads_detail"][0].update(observed_cpu=3),
            lambda p:p["threads_detail"][0].update(thread_index=False),
            lambda p:p["threads_detail"][0].update(first_error={"kind":"vnni_mismatch"}),
            lambda p:p["threads_detail"][0].update(error_count=-1),
            lambda p:p["threads_detail"][0]["vnni_capability"].update(xcr0=0),
            lambda p:p["threads_detail"][0]["vnni_capability"].update(xcr0=6.0),
            lambda p:p["threads_detail"][0]["vnni_capability"].update(cpuid_7_1_eax=1<<40),
            lambda p:p["threads_detail"][0]["vnni_capability"].update(cpuid_7_0_ecx=0,cpuid_7_1_eax=0)]
        for mutate in mutations:
            bad=deepcopy(good); mutate(bad)
            assert not worker_verification_satisfied(bad),bad
            assert not worker_result_successful(bad)
            assert worker_integrity_error_count([bad])>0
            assert not _reported_software_verification(bad,kernel)["software_verification_satisfied"]
        assert not _reported_software_verification({},kernel)["software_verification_satisfied"]
        # The actual stage/report projection preserves selected versus observed.
        stage=_stage_shell(0,dict(stage_id="s",started_monotonic=0,ended_monotonic=90,
            cpu_kernel_flavor=kernel,cpu_selection_evidence={"selection_reason":"explicit VNNI; physical acceptance separate"},worker_results=[good]))
        assert stage["cpu_instruction_selection"]["workers"][0]["software_verification_status"]=="verified"
        html=_stage_card(stage,{})
        assert kernel in html and 'software verification satisfied' in html
        assert 'Software verification does not establish prior physical acceptance' in html
        failed=deepcopy(stage)
        failed['cpu_instruction_selection']['workers'][0].update(software_verification_status='failed_or_incomplete',software_verification_satisfied=False)
        assert 'software verification not established' in _stage_card(failed,{})


def run_vnni_selection_configuration_checks():
    from Modules.lvs_cpu_architecture import cpu_native_capability_kernel_order,resolve_cpu_instruction_intent,cpu_instruction_set_policy
    from Modules.lvs_cpu_execution import build_cpu_command,cpu_candidate_kernel_flavors
    from Modules.lvs_cpu_targeting import common_kernel_capabilities,select_common_kernel,mode_for_common_kernel
    from Modules.lvs_cpu_power_selection import power_cpu_candidate_inventory
    from Modules.lvs_profile_editor import ProfileEditor
    from Modules.lvs_profile_loader import ProfileLoader
    from Modules.lvs_profile_validation import ProfileValidator
    from Modules.lvs_profile_edit_controller import ProfileEditController
    from Modules.lvs_service_models import ProfileEditState
    from Modules.lvs_stage_configuration import stage_settings,apply_stage_setting
    from Modules.lvs_workload_cpu_memory import WorkloadCpuMemoryMixin
    from Modules.lvs_native_helpers import native_helper_binary_ready
    from Modules.lvs_profile_models import ModuleCpu
    editor=ProfileEditor();loader=ProfileLoader(ROOT/'profiles')
    for kernel in KERNELS:
        assert kernel in cpu_native_capability_kernel_order("x86_64")
        assert cpu_instruction_set_policy("x86_64",kernel)["allowed"]
        assert all(not cpu_instruction_set_policy(arch,kernel)["allowed"] for arch in ("arm64","riscv64","i686"))
        for targets,caps in (([1],{1:[kernel]}),([1,17],{1:[kernel],17:[kernel]}),
                             (list(range(0,256,2)),{i:[kernel] for i in range(0,256,2)})):
            common=common_kernel_capabilities(targets,caps)
            assert select_common_kernel(architecture="x86_64",requested_mode=kernel,common_flavors=common['common_kernel_flavors'])==kernel
        for caps in ({1:[kernel],17:["avx2_fma"]},{1:[kernel]},{}):
            common=common_kernel_capabilities([1,17],caps)
            assert not select_common_kernel(architecture="x86_64",requested_mode=kernel,common_flavors=common['common_kernel_flavors'])
        allcaps=[kernel,"avx2_fma","scalar"]
        assert select_common_kernel(architecture="x86_64",requested_mode="auto",common_flavors=allcaps)=="avx2_fma"
        for intent in ("baseline_vector","high_throughput_vector","highest_verified_vector"):
            assert resolve_cpu_instruction_intent("x86_64",intent,allcaps)["resolved_kernel_flavor"]!=kernel
        assert kernel not in cpu_candidate_kernel_flavors(helper_available=True,policy="max_power",resolved_mode="auto",supports_kernel_flavor=lambda _:True)
        # Real transactional settings -> captured JSON -> runtime selection and command.
        profile=loader.load_profile(ROOT/'profiles/Quick Test.json')
        index=next(i for i,s in enumerate(profile.stages) if s.modules.cpu.enabled and not s.modules.cpu.power_auto)
        stage=profile.stages[index];stage.modules.cpu.instruction_intent="";stage.modules.cpu.backend_preference="native"
        edit=ProfileEditState(Path('<run-only>'),profile,[s.name for s in profile.stages])
        field=next(f for f in stage_settings(stage,editor) if f.key=='cpu_instruction')
        assert kernel in field.options
        apply_stage_setting(edit,index,'cpu_instruction',kernel,ProfileEditController(editor),ProfileValidator())
        captured=ProfileLoader.profile_payload(edit.profile)
        assert captured['stages'][index]['modules']['cpu']['instruction_set']==kernel
        restored=loader._profile_from_payload(captured,Path('captured.json'))
        assert restored.stages[index].modules.cpu.instruction_set==kernel
        assert loader.load_profile(ROOT/'profiles/Quick Test.json').stages[index].modules.cpu.instruction_set!=kernel
        class Runner(WorkloadCpuMemoryMixin):
            def _cpu_machine(self):return 'x86_64'
            def _cpu_helper_status(self):return dict(available=True,path='/fixture/helper')
            def _cpu_target_plan(self,cpu):return dict(target_cpu_ids=[1,17])
            def _cpu_helper_supported_kernel_flavors(self,cpu_id=None):return [kernel,'scalar']
            def _python_runtime(self):return '/fixture/python'
            def _cpu_resolved_mode(self,cpu,backend_override=''):return kernel
        runner=Runner()
        config=ModuleCpu(enabled=True,backend_preference='native',instruction_set=kernel)
        plan=runner._cpu_capability_plan(config)
        assert plan['selected_kernel_flavor']==kernel and mode_for_common_kernel(kernel)==kernel
        command=runner._cpu_command(config,backend_override='cpu_native_helper')
        assert command[command.index('--kernel-flavor')+1]==kernel
        assert command[command.index('--cpu-ids')+1]=='1,17'
        runner._cpu_helper_supported_kernel_flavors=lambda cpu_id=None:['scalar']
        assert not runner._cpu_capability_plan(config)['selected_kernel_flavor']
        assert runner._cpu_command(config,backend_override='cpu_native_helper') is None


def run_vnni_sustained_progress_checks():
    from Modules.lvs_cpu_verified_progress import analyze_verified_progress
    for kernel in KERNELS:
        worker=_valid(kernel)
        with TemporaryDirectory(prefix='lvs_vnni_progress_') as directory:
            path=Path(directory)/'progress.jsonl'
            worker['verified_progress']=dict(contract=kernel+'_progress_v1',path=str(path),snapshot_count=5,persistence_error=False)
            rows=[]
            for i,count in enumerate((0,3,12,21,30)):
                rows.append(dict(contract=kernel+'_progress_v1',kernel_flavor=kernel,operation_family='u8_s8_dot_product_accumulate',
                    sequence=i,pid=42,state=('startup','initial','ongoing','ongoing','final_complete')[i],
                    monotonic_seconds=10.+i*2,realtime_seconds=1000.+i*2,clock_pair_uncertainty_seconds=0.,aggregate_verified_blocks=count,
                    threads=[dict(thread_index=0,cpu_id=2,published_monotonic_seconds=10.+i*2,verified_blocks=count,error_count=0,
                        initial_verified=i>0,periodic_verified=i>1,final_verified=i==4,affinity_applied=True,observed_cpu=2)]))
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            window=SimpleNamespace(started_monotonic=10.,ended_monotonic=18.,trim_start_seconds=0,trim_end_seconds=0,
                analysis_intent='sustained',analysis_minimum_usable_seconds=8,analysis_evidence={'quality':'sufficient'})
            result=analyze_verified_progress(worker,window)
            assert result['quality']=='sufficient',result
            assert result['aggregate_blocks_per_second']==30/8
            expected=30/8*8*(8 if kernel=='avx_vnni' else 16)*256*4
            assert result['derived_byte_products_per_second']==expected
            assert result['threads'][0]['coverage_fraction']==1.0
            assert result['threads'][0]['first_half']['blocks_per_second'] is not None
            rows[2]['aggregate_verified_blocks']=11
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            assert analyze_verified_progress(worker,window)['quality']=='insufficient'


def run_vnni_frontend_parity_checks():
    import contextlib
    import io
    from smoke_tests.configuration_workflow_checks import Service,_source
    from smoke_tests.cli_configuration_checks import Host
    from Modules.lvs_cli_run_setup import RunSetupCliAdapter
    from Modules.lvs_profile_loader import ProfileLoader
    from Modules.lvs_cpu_power_selection import power_cpu_candidate_inventory
    for kernel in KERNELS:
        with TemporaryDirectory(dir=ROOT) as directory,contextlib.redirect_stdout(io.StringIO()) as output:
            service=Service(Path(directory));source=_source(service);before=source.read_bytes()
            tui=service.create_run_setup(source);edit=service.run_setup_stage_edit(tui)
            fields=service.stage_configuration_settings(edit,0)
            slot=next(i+1 for i,f in enumerate(fields) if f.key=='cpu_instruction')
            service.apply_stage_configuration(edit,0,'cpu_instruction',kernel)
            profile=service.profile_loader.load_profile(source)
            host=Host(service,['o','5','1',str(slot),kernel,'','4','u'])
            cli=RunSetupCliAdapter(host)
            labels=service.profile_loader.load_segment_labels(source,profile)
            setup=cli._create_run_setup_state(source,profile,labels)
            cli._run_setup_review_loop(cli._build_run_setup_review_controller(setup),setup,profile,labels)
            assert ProfileLoader.profile_payload(profile)==ProfileLoader.profile_payload(edit.profile)
            assert profile.stages[0].modules.cpu.instruction_set==kernel
            assert profile.stages[0].modules.cpu.instruction_intent==''
            assert kernel in output.getvalue()
            assert source.read_bytes()==before
            assert service.create_run_setup(source).profile.stages[0].modules.cpu.instruction_set!=kernel
        viable,unavailable=power_cpu_candidate_inventory(architecture='x86_64',availability={'cpu_native_helper':True},
            native_kernel_flavors=['scalar',*KERNELS],selected_native_kernel='scalar')
        assert all(c.get('kernel_flavor') not in KERNELS for c in viable)
        assert all(any(kernel in c['candidate_id'] for c in unavailable) for kernel in KERNELS)
