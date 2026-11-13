"""Acceptance observer tests: disposable regular files, counters and fake clocks only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from scripts import storage_thermal_acceptance as a


def reject(f):
    try:f()
    except (ValueError,OSError):return
    raise AssertionError('invalid observation accepted')


def run_acceptance_accounting_checks():
    before=[10,0,100,20,0,0,0,0,0,20,30,0,0,0,0,0,0]
    after=before.copy();after[0]+=2;after[2]+=256;after[3]+=10;after[9]+=40;after[10]+=60
    d=a.counter_delta(before,after,2)
    assert d['read_iops']==1 and d['read_bps']==65536 and d['read_await_ms']==5 and d['average_queue']==.03
    assert a.counter_delta(after,before,2)['status']=='reset'
    assert a.counter_delta(None,after,2)['status']=='unavailable'
    assert a.counter_delta(before,after,0)['status']=='unavailable'
    bad=after.copy();bad[0]=True
    assert a.counter_delta(before,bad,2)['status']=='unavailable'
    rows={10:dict(pid=10,start_ticks=100,cpu_ticks=1,children=[11]),11:dict(pid=11,start_ticks=101,cpu_ticks=2,children=[])}
    tracker=a.Processes(lambda p:deepcopy(rows[p]));tracker.register(10,'auxiliary')
    seen,errors=tracker.sample();assert {p['pid'] for p in seen}=={10,11} and not errors
    rows[11]['start_ticks']=999
    seen,errors=tracker.sample();assert 11 not in {p['pid'] for p in seen} and 'reused' in errors[0]['reason']
    assert 11 not in tracker.known
    # The replacement must remain quarantined, not be rediscovered from parent.
    seen,errors=tracker.sample()
    assert 11 not in {p['pid'] for p in seen}


def fixture(root):
    proc=root/'proc';pid=os.getpid();d=proc/str(pid);(d/'fd').mkdir(parents=True);(d/'task'/str(pid)).mkdir(parents=True)
    f=['S']+['0']*30;f[11]='3';f[12]='2';f[17]='1';f[19]='100';f[21]='1'
    (d/'stat').write_text(f'{pid} (name with ) parens) '+' '.join(f));(d/'task'/str(pid)/'children').write_text('')
    (proc/'sys/kernel/random').mkdir(parents=True);(proc/'sys/kernel/random/boot_id').write_text('synthetic-boot')
    (proc/'stat').write_text('cpu 10 0 5 90 0 0 0 0\ncpu0 10 0 5 90 0 0 0 0\n')
    (proc/'meminfo').write_text('MemTotal: 1024 kB\nMemAvailable: 512 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n')
    (proc/'vmstat').write_text('pgmajfault 0\npswpin 0\npswpout 0\n')
    counters=[10,0,100,20,0,0,0,0,0,20,30,0,0,0,0,0,0]
    (proc/'diskstats').write_text('8 0 synthetic '+' '.join(map(str,counters)))
    row=dict(device_id='fixture',eligible=True,drive_class='hdd',system_drive=False,identity=dict(major=8,minor=0),sensors=[])
    inv=root/'inventory.json';inv.write_text(json.dumps([row]))
    return proc,row,inv


def run_acceptance_capture_checks():
    with tempfile.TemporaryDirectory() as name:
        root=Path(name);proc,row,inv=fixture(root)
        class Clock:
            now=10.
            def __call__(self):return self.now
            def sleep(self,n):self.now+=n
        clock=Clock();targets=SimpleNamespace(discover=lambda:[deepcopy(row)],output_safe=lambda p,r:None)
        args=SimpleNamespace(inventory=inv,device_id=['fixture'],directory=root/'capture',interval=1,seconds=3,temperatures=False,sensor_resolution_c=1)
        with patch.object(a,'stamp',side_effect=lambda:dict(monotonic_ns=int(clock.now*1e9),realtime_ns=int(clock.now*1e9)+100)),patch.object(a,'temperature',side_effect=AssertionError('passive capture read sensor')):
            meta=a.capture(args,targets=targets,proc=proc,clock=clock,sleep=clock.sleep)
        assert meta['samples']==3 and meta['complete'] and meta['cleanup_authority'] is False
        report=a.analyze(args.directory);assert report['samples']==3 and not report['issues']
        assert report['cleanup_confirmed'].startswith('not established')
        reject(lambda:a.capture(args,targets=targets,proc=proc,clock=clock,sleep=clock.sleep))
        args.directory=root/'stale';targets.discover=lambda:[dict(row,eligible=False)]
        reject(lambda:a.capture(args,targets=targets,proc=proc,clock=clock,sleep=clock.sleep))
        assert not args.directory.exists()
        args.directory=root/'monitored';args.temperatures=True;clock.now=10.
        targets.discover=lambda:[deepcopy(row)]
        with patch.object(a,'stamp',side_effect=lambda:dict(monotonic_ns=int(clock.now*1e9),realtime_ns=int(clock.now*1e9)+100)),patch.object(a,'temperature',return_value=dict(complete=False,value_c=None)) as reader:
            a.capture(args,targets=targets,proc=proc,clock=clock,sleep=clock.sleep)
        assert reader.call_count==3
        assert 'missing/incomplete temperature' in a.analyze(args.directory)['issues']
        args.directory=root/'changed';clock.now=10.;calls=[]
        def changed():
            calls.append(1);return [deepcopy(row) if len(calls)==1 else dict(row,eligible=False)]
        targets.discover=changed
        reject(lambda:a.capture(args,targets=targets,proc=proc,clock=clock,sleep=clock.sleep))
        assert json.loads((args.directory/'session.json').read_text())['complete'] is False
        (root/'capture/events/tmp-pending-publication').write_text('{')
        assert a.event_paths(root/'capture')==[]
        marker=SimpleNamespace(directory=root/'capture',event='ambient',phase='idle',ambient_c=22.,pid=None,role='auxiliary')
        with patch.object(a,'boot_id',return_value='synthetic-boot'),patch.object(a,'stamp',return_value=dict(monotonic_ns=12*10**9,realtime_ns=24*10**9)):
            event=a.mark(marker)
            assert event['ambient_c']==22 and event['session']==meta['session']
            marker.ambient_c=float('nan');reject(lambda:a.mark(marker))
        args.directory=root/'shared';args.temperatures=False;clock.now=10.
        data=dict(row,access_mode='shared_readonly_opt_in',drive_class='nvme',mounted_or_active=True)
        inv.write_text(json.dumps([data]));targets.discover=lambda **kw:[deepcopy(data)]
        with patch.object(a,'stamp',side_effect=lambda:dict(monotonic_ns=int(clock.now*1e9),realtime_ns=int(clock.now*1e9)+100)):
            meta_shared=a.capture(args,targets=targets,proc=proc,clock=clock,sleep=clock.sleep)
        assert meta_shared['access_mode']=='shared_readonly_opt_in' and meta_shared['complete']
        # proc stat parsing tolerates spaces/parentheses and refuses replacement.
        assert a.process(os.getpid(),proc)['start_ticks']==100
        reject(lambda:a.json_file(root))


def run_acceptance_analysis_checks():
    with tempfile.TemporaryDirectory() as name:
        root=Path(name);(root/'events').mkdir();target=dict(device_id='fixture')
        meta=dict(contract=a.CONTRACT,session='s',boot_id='b',samples=3,complete=True,temperature_reads=True,
                  interval_seconds=1,duration_seconds=3,observed_seconds=3,clock_ticks=100,targets=[target],sensor_resolution_c=1)
        (root/'session.json').write_text(json.dumps(meta))
        rows=[]
        for i,(phase,temp) in enumerate([('idle',30),('heat',33),('heat',34)]):
            rows.append(dict(session='s',boot_id='b',monotonic_ns=(10+i)*10**9,realtime_ns=(20+i)*10**9,phase=phase,
                ambient=dict(ambient_c=20,monotonic_ns=10*10**9),devices={'fixture':dict(counters=[i]*17,temperature=dict(complete=True,value_c=temp))},
                processes=[dict(pid=7,start_ticks=1,cpu_ticks=i*10,role='auxiliary',rss_bytes=1024,fds=3,threads=1)],host=dict(logical_cpus=6)))
        def put():(root/'samples.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        put();report=a.analyze(root)
        assert report['ambient_corrected_heating']['fixture']['final_minus_idle_c']==3.5
        assert report['sampled_cpu_seconds_lower_bound']['auxiliary']==.2
        assert report['process_group_sampled_peaks']['auxiliary']['fds']==3
        rows[1]['ambient']['monotonic_ns']=-400*10**9;put()
        assert any('ambient' in i for i in a.analyze(root)['issues'])
        rows[1]['ambient']['monotonic_ns']=10*10**9
        rows[1]['realtime_ns']+=100*10**9;put()
        assert any('wall clock' in i for i in a.analyze(root)['issues'])
        rows[1]['devices']['fixture']['temperature']=None;rows[1]['devices']['fixture']['counters']=None
        rows[2]['monotonic_ns']=rows[0]['monotonic_ns'];put();report=a.analyze(root)
        assert any('temperature' in i for i in report['issues']) and any('monotonic' in i for i in report['issues'])
        rows[2]['host']['cpu_ticks']=[1];put();assert any('host CPU counters' in i for i in a.analyze(root)['issues'])
        rows[2]['session']='old';put();assert any('foreign sample' in i for i in a.analyze(root)['issues'])
        with (root/'samples.jsonl').open('a') as stream:stream.write('{')
        assert any('malformed' in i for i in a.analyze(root)['issues'])
        meta['access_mode']='shared_readonly_opt_in';(root/'session.json').write_text(json.dumps(meta))
        shared_report=a.analyze(root)
        assert not any('exclusive target mutation' in i for i in shared_report['issues'])
        meta['complete']=False;(root/'session.json').write_text(json.dumps(meta))
        assert any('incomplete' in i for i in a.analyze(root)['issues'])


def run_acceptance_child_disappearance_checks():
    """A real child disappears between its parent's proc snapshot and registration."""
    import subprocess
    import sys
    program='''import subprocess,sys
child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])
print(child.pid,flush=True)
try:
 for line in sys.stdin:
  if line.strip()=="REAP":
   child.terminate();child.wait();print("REAPED",flush=True)
  elif line.strip()=="QUIT":break
finally:
 if child.poll() is None:child.terminate();child.wait()
'''
    parent=subprocess.Popen([sys.executable,'-u','-B','-c',program],stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,text=True,start_new_session=True)
    child=int(parent.stdout.readline());during=False;reaped=False
    try:
        def reader(pid):
            nonlocal reaped
            row=a.process(pid)
            if pid==parent.pid and during and not reaped:
                assert child in row['children']
                parent.stdin.write('REAP\n');parent.stdin.flush()
                assert parent.stdout.readline().strip()=='REAPED';reaped=True
            return row
        tracker=a.Processes(reader);creation=tracker.register(parent.pid,'auxiliary');during=True
        first,errors=tracker.sample();second,second_errors=tracker.sample()
        assert parent.poll() is None and a.process(parent.pid)['start_ticks']==creation
        assert parent.pid in tracker.known and parent.pid not in tracker.retired
        assert {r['pid'] for r in first}=={parent.pid}=={r['pid'] for r in second}
        assert len(errors)==1 and errors[0]['pid']==child and errors[0]['parent_pid']==parent.pid
        assert errors[0]['observation']=='child registration incomplete' and not second_errors
    finally:
        parent.stdin.write('QUIT\n');parent.stdin.flush();parent.wait(timeout=5)
        parent.stdin.close();parent.stdout.close()
