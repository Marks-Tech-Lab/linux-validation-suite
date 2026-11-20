"""Finite CPU/RAM completed-work qualification on the existing sealed QEMU harness.

Private images only. No Thermal Assist workload or host block-device access.
"""
from pathlib import Path
import argparse
import base64
from dataclasses import asdict
from datetime import datetime
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

ROOT=Path('/lvs') if Path('/fixture.json').exists() else Path(__file__).resolve().parents[1]


def stage(directory,cancel=False):
    from Modules.lvs_profile_models import StageConfig,StageModules,ModuleCpu,ModuleMemory
    from Modules.lvs_run_models import StageWindow
    from Modules.lvs_stage_execution import execute_stage_runtime
    from Modules.lvs_stage_process_control import launch_stage_processes_from_plan,stop_stage_processes
    from Modules.lvs_stage_launch_plan import StageLaunchCommand
    from Modules.lvs_stage_worker_evidence import worker_result_events
    from Modules.lvs_primary_work_progress import attach_primary_work
    stage=StageConfig('work-proof','CPU/RAM',10,modules=StageModules(cpu=ModuleCpu(enabled=True,threads='1'),memory=ModuleMemory(enabled=True,threads='2')))
    stage.normalization.trim_start_seconds=1;stage.normalization.trim_end_seconds=1
    commands=[]
    for kind,binary,args in [('cpu','cpu_stress_helper',['--kernel-flavor','sse2','--threads','1']),('memory','memory_stress_helper',['--bytes','8388608','--threads','2'])]:
        result=directory/(kind+'.json');commands.append(StageLaunchCommand(kind=kind,command=['/lvs/build/'+binary,*args,'--result-file',str(result)],result_path=str(result)))
    args={k:(lambda *a,**kw:None)for k,p in inspect.signature(execute_stage_runtime).parameters.items()if p.default is inspect.Parameter.empty}
    for k in ('profile_name','display_name','stage_started_iso','cpu_kernel_flavor','cpu_backend','cpu_mode_requested','cpu_mode_resolved','cpu_tuning_policy','gpu_3d_backend_preference','gpu_3d_backend_resolved','vram_backend_preference','vram_backend_resolved','gpu_target_mode','operator_stop_source'):args[k]=''
    begin=time.monotonic();samples=[]
    def sample():samples.append(dict(monotonic_seconds=time.monotonic(),cpu=Path('/proc/stat').read_text().splitlines()[0],memory=Path('/proc/meminfo').read_text()))
    args.update(stage_window_cls=StageWindow,stage=stage,run_dir=directory,stage_plan={},stage_start=begin,stage_started_iso=datetime.now().astimezone().isoformat(),cpu_tuned_avg_power_w=None,gpu_targets=[],gpu_workers_initial=[],gpu_lifecycle_backends=set(),gpu_retune_events=[],stage_error_events=[],stage_failure_reasons=[],stage_verdict='pass',stage_aborted=False,stage_abort_reason='',run_aborted=False,abort_on_worker_error=False,abort_on_fail_threshold=False,telemetry_interval_seconds=.2,progress_interval_seconds=30,strict_threshold_recommendation_warnings=False,
        launch_stage_processes=lambda *a:launch_stage_processes_from_plan(commands,stage_id='work-proof'),stop_stage_processes=stop_stage_processes,telemetry_collect_once=sample,poll_stage_process_failures=lambda *a:[],stage_sensor_events=lambda *a:[],maybe_retune_gpu_processes=lambda p,*a:p,stage_target_gpu_progress_summary=lambda *a:'',effective_gpu_retune_cooldown_seconds=lambda *a:20,worker_result_events_func=lambda p,n:worker_result_events(p,n,lambda name:{}),utilization_events_func=lambda *a:[],backend_effectiveness_events_func=lambda *a:[],vram_attainment_events_func=lambda *a:[],now_local_iso=lambda:datetime.now().astimezone().isoformat(),monotonic=time.monotonic,sleep=time.sleep,cancel_check=(lambda:time.monotonic()-begin>=7)if cancel else None)
    result=execute_stage_runtime(**args);window=result.stage_completion.stage_window
    attach_primary_work(window)
    for worker in window.worker_results:
        assert worker['primary_work_analysis']['quality']=='observed',worker
    assert len(samples)>=20 and len(window.worker_results)==2
    assert result.stage_aborted is cancel
    if not cancel:assert result.stage_verdict=='pass',result
    (directory/'raw-telemetry.jsonl').write_text(''.join(json.dumps(s)+'\n'for s in samples))
    payload=asdict(window);(directory/'stage-window.json').write_text(json.dumps(payload,indent=2))
    return dict(elapsed=result.stage_elapsed,verdict=result.stage_verdict,aborted=result.stage_aborted,telemetry_samples=len(samples),workers=window.worker_results)


def guest():
    assert os.getuid()==0 and 'QEMU'in Path('/sys/class/dmi/id/sys_vendor').read_text() and 'lvs_fixture='in Path('/proc/cmdline').read_text()
    sys.path.insert(0,'/lvs');out=Path('/evidence');out.mkdir()
    results=dict(kernel=os.uname().release,build=json.loads(Path('/lvs/primary-build.json').read_text()),real_primary_workloads=True,cases={})
    for case in ('complete','cancel'):
        directory=out/case;directory.mkdir();results['cases'][case]=stage(directory,case=='cancel')
    # Alternating bounded reference pairs: prior accepted helpers, identical
    # commands/working sets. Legacy passes are diagnostic overhead proxies only.
    import resource
    overhead=[]
    for repeat in range(3):
        for version in (('reference','instrumented')if repeat%2==0 else('instrumented','reference')):
            directory=out/('overhead-'+str(repeat)+'-'+version);directory.mkdir();processes=[]
            before=resource.getrusage(resource.RUSAGE_CHILDREN);begin=time.monotonic()
            for kind,args in [('cpu',['--kernel-flavor','sse2','--threads','1']),('memory',['--bytes','8388608','--threads','2'])]:
                binary='/lvs/build/'+(kind+'_reference'if version=='reference'else'cpu_stress_helper'if kind=='cpu'else'memory_stress_helper')
                result=directory/(kind+'.json');processes.append((kind,result,subprocess.Popen([binary,*args,'--result-file',str(result)])))
            time.sleep(4)
            for _,_,process in processes:process.terminate()
            for _,_,process in processes:assert process.wait(timeout=20)==0
            elapsed=time.monotonic()-begin;after=resource.getrusage(resource.RUSAGE_CHILDREN)
            overhead.append(dict(repeat=repeat,version=version,elapsed=elapsed,children_cpu_seconds=(after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime),workers={kind:json.loads(result.read_text())for kind,result,_ in processes}))
    results['overhead_reference_pairs']=overhead
    # Kill before terminal publication: missing evidence stays unavailable.
    from Modules.lvs_primary_work_progress import analyze_primary_work
    from types import SimpleNamespace
    results['missing_unavailable']=analyze_primary_work({},SimpleNamespace())['quality']=='unavailable'
    (out/'results.json').write_text(json.dumps(results,indent=2))
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w:gz')as archive:archive.add(out,arcname='evidence')
    print('LVS_EVIDENCE_BEGIN\n'+base64.b64encode(data.getvalue()).decode()+'\nLVS_EVIDENCE_END',flush=True)
    subprocess.run(['/bin/sh','-c','exec /usr/bin/python3 -c "import ctypes; ctypes.CDLL(None).reboot(0x4321fedc)"'])


def host(args):
    from scripts import storage_thermal_fio_probe as base
    from Modules.lvs_native_helpers import native_helper_build_command,find_c_compiler
    from scripts.storage_thermal_causal_probe import require_kernel_image
    require_kernel_image(args.kernel)
    import tempfile
    build=Path(tempfile.mkdtemp(prefix='lvs-primary-build-'));extra=[]
    for name in ('cpu_stress_helper','memory_stress_helper'):
        binary=build/name;subprocess.run(native_helper_build_command(find_c_compiler(),ROOT/'native'/(name+'.c'),binary),check=True)
        extra.append((binary,'/lvs/build/'+name))
    # Compile the accepted pre-instrumentation native sources, preserving
    # include dependencies in a private research directory.
    reference=build/'reference';reference.mkdir()
    archive=subprocess.check_output(['git','-C',str(ROOT),'archive','2ee5db0429882f541634cb66802d3d5b512cf22f','native'])
    with tarfile.open(fileobj=io.BytesIO(archive))as tar:tar.extractall(reference,filter='data')
    for kind,name in [('cpu','cpu_stress_helper'),('memory','memory_stress_helper')]:
        binary=build/(kind+'_reference');subprocess.run([find_c_compiler(),'-O3','-std=c11','-pthread',str(reference/'native'/(name+'.c')),'-o',str(binary)],check=True)
        extra.append((binary,'/lvs/build/'+kind+'_reference'))
    from Modules.lvs_source_provenance import _source_snapshot
    import hashlib
    provenance=build/'primary-build.json';provenance.write_text(json.dumps(dict(source=_source_snapshot(ROOT)[0],reference_commit='2ee5db0429882f541634cb66802d3d5b512cf22f',compiler=subprocess.check_output([find_c_compiler(),'--version'],text=True).splitlines()[0],binaries={destination:hashlib.sha256(Path(path).read_bytes()).hexdigest()for path,destination in extra}),indent=2));extra.append((provenance,'/lvs/primary-build.json'))
    for directory in ('Modules','scripts'):

        extra.extend((p,'/lvs/'+str(p.relative_to(ROOT)))for p in (ROOT/directory).glob('*.py'))
    extra.extend((p,'/lvs/'+p.name)for p in ROOT.glob('*.py'))
    def verify(result):
        assert result['real_primary_workloads'] and result['missing_unavailable']
        assert result['cases']['complete']['verdict']=='pass' and result['cases']['cancel']['aborted']
    base.host(args,guest_script=Path(__file__),extra_files=extra,verifier=verify,guest_timeout=240)


if __name__=='__main__':
    if Path('/fixture.json').exists() and 'lvs_fixture='in Path('/proc/cmdline').read_text():guest()
    else:
        parser=argparse.ArgumentParser(description=__doc__)
        for name in ('fio','old-fio','strace','kernel','python','guard'):parser.add_argument('--'+name,required=True)
        host(parser.parse_args())
