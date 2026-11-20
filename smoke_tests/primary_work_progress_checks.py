"""Completed-work accounting; private native processes and deterministic evidence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
from Modules.lvs_primary_work_progress import analyze_primary_work

ROOT=Path(__file__).resolve().parents[1]


def fixture(root,kind='memory',threads=2):
    path=root/'worker.json';rows=[]
    for seq,t in enumerate((10.,12.,14.,16.,18.)):
        rows.append(dict(contract='lvs_primary_work_v1',pid=123,kind=kind,sequence=seq,final=seq==4,monotonic_seconds=t+.01,realtime_seconds=t+1000,clock_pair_uncertainty_seconds=.001,
            threads=[dict(thread_index=i,monotonic_seconds=t,completed_units=seq*100*(i+1),processed_bytes=seq*1000*(i+1)if kind=='memory'else 0,verified_bytes=seq*400*(i+1)if kind=='memory'else 0,error_count=0,final=seq==4)for i in range(threads)]))
    def save(values):Path(str(path)+'.work.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in values))
    save(rows)
    worker=dict(result_path=str(path),process_pid=123,kind='memory'if kind=='memory'else'cpu',kernel_flavor=kind,threads=threads,error_count=0,verify_passes=5,verification_complete=True,observed_exit_code=0,work_progress=dict(contract='lvs_primary_work_v1',kind=kind,threads=threads,persistence_error=False,snapshot_count=5,final_threads=deepcopy(rows[-1]['threads'])))
    window=SimpleNamespace(started_monotonic=10.,ended_monotonic=18.,trim_start_seconds=2.,trim_end_seconds=2.)
    return worker,window,rows,save


def run_primary_work_analysis_checks():
    with tempfile.TemporaryDirectory()as name:
        w,win,rows,save=fixture(Path(name))
        r=analyze_primary_work(w,win);assert r['quality']=='observed',r
        assert r['rates']==dict(completed_units=150.,processed_bytes=1500.,verified_bytes=600.)
        assert all(t['observed_seconds']==4. and t['intervals']==2 for t in r['threads'])
        assert r['physical_dram_bandwidth_measured']is False
        # High core counts, heterogeneous per-thread work, no capacity proxy.
        w,win,rows,save=fixture(Path(name),'sse2',256)
        r=analyze_primary_work(w,win);assert r['quality']=='observed',r
        assert r['algorithmic_fp32_operations_per_second']==32*50*sum(range(1,257))
        assert 'verification_cycles'not in r['rates']
        # Few resources retain the same semantics.
        w,win,rows,save=fixture(Path(name),'sse2_int',1)
        assert analyze_primary_work(w,win)['rates']['completed_units']==50.
        win.trim_end_seconds=99.;assert analyze_primary_work(w,win)['rates']is None


def run_primary_work_contradiction_checks():
    with tempfile.TemporaryDirectory()as name:
        w,win,rows,save=fixture(Path(name))
        for case in ('missing','duplicate','reset','bool','negative','bad_pid','thread','future','final','unverified','partial','terminal','failed_exit'):
            a=deepcopy(rows);worker=deepcopy(w)
            if case=='missing':del a[1]
            elif case=='duplicate':a[2]['threads'][1]=a[2]['threads'][0]
            elif case=='reset':a[2]['threads'][0]['processed_bytes']=0
            elif case=='bool':a[2]['threads'][0]['completed_units']=True
            elif case=='negative':a[2]['threads'][0]['verified_bytes']=-1
            elif case=='bad_pid':a[2]['pid']=456
            elif case=='thread':a[2]['threads'].pop()
            elif case=='future':a[2]['threads'][0]['monotonic_seconds']=900.
            elif case=='final':a[-1]['threads'][1]['final']=False
            elif case=='unverified':worker['error_count']=1
            elif case=='partial':a.pop()
            elif case=='terminal':worker['work_progress']['snapshot_count']=99
            elif case=='failed_exit':worker['observed_exit_code']=-9
            save(a);r=analyze_primary_work(worker,win);assert r['rates']is None,(case,r)
        save(rows);Path(w['result_path']+'.work.jsonl').unlink()
        assert analyze_primary_work(w,win)['rates']is None
        assert analyze_primary_work({},win)['quality']=='unavailable'


def compile_helper(root,source,name,extra=()):
    compiler=shutil.which('cc')or shutil.which('gcc')
    if not compiler:raise RuntimeError('native completed-work qualification requires a compiler')
    out=root/name
    subprocess.run([compiler,'-O3','-std=c11','-pthread','-I',str(ROOT/'native'),str(source),'-DLVS_WORK_PROGRESS_EXTERNAL',str(ROOT/'native/primary_work_progress.c'),'-o',str(out),*extra],check=True,capture_output=True)
    return out


def run_primary_work_known_native_checks():
    with tempfile.TemporaryDirectory()as name:
        root=Path(name)
        # Execute the actual unchanged SSE loop bodies for exactly one batch.
        source=(ROOT/'native/cpu_stress_helper.c').read_text()
        for fn,nextfn in (('run_sse_loop','run_sse2_int_loop'),('run_sse2_int_loop','run_avx_loop')):
            start=source.index('static void '+fn+'(');end=source.index('static void '+nextfn+'(',start)
            chunk=source[start:end].replace('while (keep_running) {','for(int known_batch=0;known_batch<1;known_batch++) {',1)
            source=source[:start]+chunk+source[end:]
        # Main supervisor normally waits for SIGTERM; finite test workers end themselves.
        source=source.replace('while (keep_running) sleep(1);','/* finite known-work fixture */')
        source=source.replace('static void run_sse_loop(', '__attribute__((noinline,noclone)) static void run_sse_loop(')
        p=root/'cpu.c';p.write_text(source);cpu=compile_helper(root,p,'cpu')
        supported=subprocess.run([str(cpu),'--kernel-flavor','sse2','--print-kernel-flavor'],capture_output=True).returncode==0
        if supported:
            for flavor,units in (('sse2',200000),('sse2_int',260000)):
                result=root/(flavor+'.json');subprocess.run([str(cpu),'--kernel-flavor',flavor,'--threads','1','--result-file',str(result)],check=True,timeout=20,capture_output=True)
                rows=[json.loads(line)for line in Path(str(result)+'.work.jsonl').read_text().splitlines()]
                assert rows[-1]['threads'][0]['completed_units']==units
            disasm=subprocess.check_output(['objdump','-d','--disassemble=run_sse_loop',str(cpu)],text=True)
            # Count the actual loop body, excluding checkpoint/final sink adds.
            # Compilers may unroll and express subtraction as addition of a
            # negated constant. Count algorithmic work, never retired instructions.
            assert disasm.count('mulps')>=4 and disasm.count('mulps')%4==0,disasm
            assert disasm.count('addps')>=3 and 'vfmadd'not in disasm
        # Exact RAM regions: two writes, one comparison. Unaligned tail regions
        # deliberately remain unprocessed, rather than counting allocated bytes.
        p=root/'memory.c';p.write_text((ROOT/'native/memory_stress_helper.c').read_text().replace('while (g_running) {','while (g_running && pass_index<2) {',1))
        memory=compile_helper(root,p,'memory');result=root/'memory.json'
        subprocess.run([str(memory),'--bytes','1048576','--threads','3','--result-file',str(result)],check=True,timeout=20,capture_output=True)
        final=json.loads(Path(str(result)+'.work.jsonl').read_text().splitlines()[-1])
        spans=[1048576//3]*2+[1048576//3+1048576%3]
        for row,span in zip(final['threads'],spans):
            actual=span//64*64
            assert row['processed_bytes']==actual*3 and row['verified_bytes']==actual
            assert row['completed_units']==actual//64*2
        assert sum(r['verified_bytes']for r in final['threads'])<1048576


def run_primary_work_native_lifecycle_checks():
    from Modules.lvs_worker_evidence import apply_worker_entry_context
    from Modules.lvs_stage_process_control import launch_stage_processes_from_plan,stop_stage_processes
    from Modules.lvs_stage_launch_plan import StageLaunchCommand
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);cpu=compile_helper(root,ROOT/'native/cpu_stress_helper.c','cpu');memory=compile_helper(root,ROOT/'native/memory_stress_helper.c','memory')
        commands=[]
        for kind,command in [('cpu',[str(cpu),'--kernel-flavor','sse2','--threads','1']),('memory',[str(memory),'--bytes','8388608','--threads','3'])]:
            if kind=='cpu' and subprocess.run([str(cpu),'--kernel-flavor','sse2','--print-kernel-flavor'],capture_output=True).returncode!=0:continue
            path=root/(kind+'.json');commands.append(StageLaunchCommand(kind=kind,command=command+['--result-file',str(path)],result_path=path))
        begin=time.monotonic();entries=launch_stage_processes_from_plan(commands,stage_id='native-measurement')
        try:time.sleep(5)
        finally:stop_stage_processes(entries)
        window=SimpleNamespace(started_monotonic=begin,ended_monotonic=time.monotonic(),trim_start_seconds=.2,trim_end_seconds=0.)
        for entry in entries:
            worker=json.loads(Path(entry.result_path).read_text())
            worker=apply_worker_entry_context(worker,entry,return_code=entry.process.returncode)
            report=analyze_primary_work(worker,window)
            assert report['quality']=='observed',report
            assert all(t['observed_seconds']>0 for t in report['threads'])
            assert report['rates']['completed_units']>0
            if entry.kind=='memory':assert report['rates']['verified_bytes']>0
            else:assert report['algorithmic_fp32_operations_per_second']>0
            # Historical proxies are retained, not reinterpreted as work rates.
            assert worker['verify_passes']>0
