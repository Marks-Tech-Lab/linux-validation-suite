"""Real controlling-PTY regression fixtures; no physical device access.

Only inventory, backend security witnesses and temperature are simulated. The
production menu, controls, runner, owned launcher and recovery scope run intact.
Workers perform bounded reads from one private regular file.
"""
import errno
import json
import os
from pathlib import Path
import pty
import select
import signal
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def fixture(out,count,mode,scenario):
    import termios
    import fcntl
    from copy import deepcopy
    from unittest.mock import patch
    from Modules import lvs_storage_thermal_launch as launch
    from Modules.lvs_storage_thermal_runner import ThermalRunner
    from Modules.lvs_storage_thermal_backend import executable_identity
    from Modules.lvs_storage_thermal import ThermalConfig
    from lvs_storage_thermal_assist import ThermalMenu
    launch.prepare()
    epoch=time.monotonic()
    assert sys.stdin.isatty() and sys.stdout.isatty()
    if mode.startswith('noncanonical'):
     attrs=termios.tcgetattr(0);attrs[3]&=~termios.ICANON;attrs[6][termios.VMIN]=1;attrs[6][termios.VTIME]=0;termios.tcsetattr(0,termios.TCSANOW,attrs)
    if mode=='noncanonical_raw':
        attrs=termios.tcgetattr(0);attrs[3]&=~termios.ISIG;attrs[6][termios.VMIN]=0
        termios.tcsetattr(0,termios.TCSANOW,attrs)
    if mode=='nonblocking':os.set_blocking(0,False)
    attrs=termios.tcgetattr(0)
    (out/'terminal.json').write_text(json.dumps(dict(isatty=sys.stdin.isatty(),canonical=bool(attrs[3]&termios.ICANON),isig=bool(attrs[3]&termios.ISIG),flags=fcntl.fcntl(0,fcntl.F_GETFL),foreground_group=os.tcgetpgrp(0),process_group=os.getpgrp(),native_bootstrap='production OwnedProcess launcher',simulation_only=True),indent=2))
    corpus=out/'private-corpus.bin';corpus.write_bytes(b'X'*65536)
    rows=[dict(device_id='simulation-'+str(i+1),identity=dict(device_id='simulation-'+str(i+1),major=0,minor=i,size_bytes=65536,logical_sector=512,path=str(corpus)),model='SIMULATED PRIVATE FILE',transport='synthetic',drive_class='hdd',internal=True,excluded_automatic=False,system_drive=False,eligible=True,reasons=[],sensors=[]) for i in range(count)]
    class Targets:
     def discover(self,**kw):return deepcopy(rows)
     def open(self,row):return os.open(corpus,os.O_RDONLY|os.O_CLOEXEC)
     def revalidate(self,row):return row
     def output_safe(self,path,records):Path(path).absolute().relative_to(out.absolute())
    def spawn(argv,**kw):
     if 'nonblocking_after' in mode:
      os.set_blocking(0,False)
      (out/'terminal-after-launch.json').write_text(json.dumps(dict(flags=fcntl.fcntl(0,fcntl.F_GETFL),canonical=bool(termios.tcgetattr(0)[3]&termios.ICANON))))
     return launch.OwnedProcess([sys.executable,'-u','-B',str(Path(__file__).resolve()),'worker',argv[-1],argv[-2],argv[-3],str(out/'worker-events.jsonl')],**kw)
    exe=Path('/usr/bin/true').resolve();backend=dict(status='available',fio=executable_identity(str(exe)),guard=executable_identity(str(exe)),reasons=[],active_storage_supported=True,simulation_only=True)
    config=ThermalConfig(access_mode='shared_readonly_opt_in',aggregate_iops_limit=64,aggregate_bps_limit=4194304,intensity_percent=25,duration_seconds=3,temperature_limit_c=60)
    def temperature_fixture(row):
     with (out/'temperature-calls.jsonl').open('a') as stream:
      stream.write(json.dumps(dict(monotonic=time.monotonic(),simulation_only=True))+'\n')
     return dict(value_c=65. if 'temperature' in scenario and time.monotonic()-epoch>1.1 else 30.,critical_c=70.,warning_c=55.,complete=True)
    runner=ThermalRunner(exe,exe,targets=Targets(),popen=spawn,source=lambda:dict(source=dict(status='complete',digest='SIMULATION_ONLY')),budget=lambda:dict(memory_budget=256*1024**2,memory_available=512*1024**2,fd_limit=1024),temperature_reader=temperature_fixture,activity=lambda:{(0,i):[0]*17 for i in range(count)})
    menu=ThermalMenu(runner,config,out/'outputs',recovery_marker=out/'recovery.json')
    if scenario=='completion_race':
        original_observe=menu.observe
        delayed=False
        def delayed_observe(jobs):
            nonlocal delayed
            original_observe(jobs)
            if jobs and not delayed and time.monotonic()-jobs[0]['started']>2.7:
                delayed=True;time.sleep(.6)
        menu.observe=delayed_observe
    if scenario=='output_pressure':
        original_observe=menu.observe
        def verbose_observe(jobs):
            original_observe(jobs)
            menu.ui.write('synthetic display pressure '*3000)
        menu.observe=verbose_observe

    initial=termios.tcgetattr(0);initial_flags=fcntl.fcntl(0,fcntl.F_GETFL)
    try:
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=backend):
            if scenario=='exception':
                def raise_after_mode_change(*args,**kwargs):
                    changed=termios.tcgetattr(0);changed[3]^=termios.ICANON
                    termios.tcsetattr(0,termios.TCSANOW,changed)
                    raise RuntimeError('injected supervisor exception')
                with patch.object(runner,'run',side_effect=raise_after_mode_change):
                    menu.start()
            else:menu.run()
    except RuntimeError:
        if scenario!='exception':raise
    finally:
        after=termios.tcgetattr(0)
        (out/'restoration.json').write_text(json.dumps(dict(settings=initial==after,
            flags=(initial_flags | (os.O_NONBLOCK if 'nonblocking_after' in mode else 0))==fcntl.fcntl(0,fcntl.F_GETFL),unconfirmed=len(runner.unconfirmed))))


def run_case(root,name,command=b'0\n',count=1,mode='canonical',scenario='stop',actions=None,batch=False):
    out=root/name;out.mkdir()
    pid,master=pty.fork()
    if pid==0:
        os.execv(sys.executable,[sys.executable,'-u','-B',str(Path(__file__).resolve()),
            'fixture',str(out),str(count),mode,scenario])
    os.set_blocking(master,False)
    output=bytearray();records=[];began=time.monotonic();phase='confirm' if scenario=='exception' else 'menu'
    due=None;sent=set();status=None;reaped=False;results_seen=False
    scheduled=actions if actions is not None else [(0,command)]
    def send(data,label):
        os.write(master,data)
        records.append(dict(event=label,bytes_hex=data.hex(),monotonic=time.monotonic()))
    try:
        while time.monotonic()-began<12:
            if select.select([master],[],[],.01)[0]:
                try:chunk=os.read(master,65536)
                except OSError as error:
                    if error.errno==errno.EIO:break
                    raise
                if not chunk:break
                output.extend(chunk)
            text=output.decode(errors='replace')
            if phase=='menu' and 'Choose [8]:' in text:
                send(b'7\n','start');phase='confirm'
            elif phase=='confirm' and 'Choose [2]:' in text:
                send(b'1\n'+(command if batch else b''),'confirm');phase='active'
            if phase=='active' and 'Drive 1:' in text and due is None:
                due=time.monotonic()+(.45 if count==1 else 1.35)
            if due is not None and not batch and 'Run finished' not in text:
                for i,(delay,data) in enumerate(scheduled):
                    if i not in sent and time.monotonic()>=due+delay:
                        send(data,f'control-{i}');sent.add(i)
            if 'Run finished' in text and not results_seen:
                results_seen=True
                # Finish any unterminated canonical line, then acknowledge.
                send(b'1\n','results');phase='exit'
            if phase=='exit' and text.count('Choose [8]:')>=2:
                send(b'8\n','exit');phase='done'
            done,wait_status=os.waitpid(pid,os.WNOHANG)
            if done:
                status=os.waitstatus_to_exitcode(wait_status);reaped=True;break
        if not reaped:
            done,wait_status=os.waitpid(pid,os.WNOHANG)
            if done:status=os.waitstatus_to_exitcode(wait_status);reaped=True
        assert reaped or (out/'restoration.json').exists(),(name,'PTY child did not finish',output[-2000:])
        if not reaped:
            _,wait_status=os.waitpid(pid,0);status=os.waitstatus_to_exitcode(wait_status);reaped=True
    finally:
        if not reaped:
            os.kill(pid,signal.SIGTERM)
            limit=time.monotonic()+5
            while time.monotonic()<limit:
                done,_=os.waitpid(pid,os.WNOHANG)
                if done:reaped=True;break
                time.sleep(.02)
            if not reaped:os.kill(pid,signal.SIGKILL);os.waitpid(pid,0)
        os.close(master)
        (out/'transcript.txt').write_bytes(output)
        (out/'actions.json').write_text(json.dumps(records,indent=2))
    assert status==0,(name,status,output[-2000:])
    restored=json.loads((out/'restoration.json').read_text())
    assert restored['settings'] and restored['unconfirmed']==0,(name,restored)
    assert restored['flags'],(name,restored)
    if scenario=='exception':return dict(name=name,restored=restored)
    paths=list((out/'outputs').glob('*/storage_thermal_manifest.json'));assert len(paths)==1,name
    result=json.loads(paths[0].read_text());devices=result['devices']
    if batch:
        assert not devices and not result['execution_started'] and result['verdict']=='INCOMPLETE'
        assert result['control_events'][0]['command']=='all'
        return dict(name=name,states=[],stopped_before_launch=True,restored=restored)
    assert devices and all(d['cleanup_confirmed'] and d['terminal_published'] and not d['outstanding_descriptors'] for d in devices),(name,devices)
    calls=[json.loads(line)['monotonic'] for line in (out/'temperature-calls.jsonl').read_text().splitlines()]
    assert max([b-a for a,b in zip(calls,calls[1:])]+[0])<1.6,(name,calls)
    if scenario.startswith('temperature'):
        assert any(d['safety_stop'] and 'temperature' in d['stop_reason'] for d in devices),(name,devices)
    elif scenario in ('natural_partial','completion_race'):
        assert all(d['state']=='completed' and d['duration_completed'] for d in devices),(name,devices)
    else:
        assert any(d['state']=='cancelled' or d['safety_stop'] and d['stop_reason']=='group emergency stop' for d in devices),(name,devices)
        for d in devices:
            if d['state']=='cancelled' or d['stop_reason']=='group emergency stop':
                timing=d['control_timing']
                assert timing['signal_dispatched'] and timing['cleanup_confirmed_monotonic']>=timing['worker_exit_observed_monotonic']
                assert timing['signal_dispatch_monotonic']-timing['request_recognized_monotonic']<.5,(name,timing)
        if command.startswith((b's ',b'\x1b[200~s ')) and count==2:
            assert sum(d['state']=='completed' for d in devices)==1,(name,devices)
    observation=result['input_observation']
    assert observation['max_queued_commands']<=32 and observation['max_line_bytes']<=512
    if scenario=='overflow':assert observation['overflow'],observation
    if scenario=='output_pressure':assert observation['dropped_display_bytes']>0
    if actions and len(actions)>1 and scenario=='stop' and not actions[0][1].endswith(b'\n'):
        recognized=[e['recognized_monotonic'] for e in result['control_events'] if e['kind'] in ('control_request','signal_request')]
        first_complete=next((r['monotonic'] for r in records if r['event']==f'control-{len(actions)-1}'),None)
        if first_complete is not None:assert not recognized or min(recognized)>=first_complete-.01
    if scenario=='completion_race':
        assert any(e['kind']=='late_stop_request' for e in result['control_events']),result['control_events']
    if b'unknown' in command and not observation['overflow']:assert b'Invalid control.' in output
    if scenario not in ('natural_partial','temperature_partial'):assert result['control_events'] or scenario.startswith('temperature')
    return dict(name=name,states=[d['state'] for d in devices],timings=[d['control_timing'] for d in devices],
                input=observation,restored=restored,max_temperature_gap=max([b-a for a,b in zip(calls,calls[1:])]+[0]))


# Original 24 qualified reproductions, retaining canonical/noncanonical and
# inherited/non-inherited O_NONBLOCK distinctions. No sleeping driver hides output.
ORIGINAL_CASES=[
    ('v2_zero',b'0\n'),('v2_per_device',b's 1\n',2),('v2_per_device_second',b's 2\n',2),
    ('v2_emergency',b'e\n',2),('v2_ctrl_c',b'\x03',2),
    ('v2_split_zero',b'0\n',1,'canonical','stop',[(0,b'0'),(.25,b'\n')]),
    ('v2_batched_zero',b'0\n',1,'canonical','stop',None,True),
    ('v2_queued_canonical',b'unknown\n0\n'),('v2_queued_noncanonical',b'unknown\n0\n',1,'noncanonical'),
    ('v2_paste_markers',b'\x1b[200~0\x1b[201~\n'),('v2_crlf',b'0\r\n'),
    ('v2_partial_noncanonical',b'0\n',1,'noncanonical','natural_partial',[(0,b'0'),(4,b'\n')]),
    ('v3_buffer_wake',b'unknown\n0\n',1,'noncanonical','stop',[(0,b'unknown\n0\n'),(.7,b'\n')]),
    ('v3_repeated_zero',b'0\n'),('v3_repeated_emergency',b'e\n'),('v3_repeated_ctrl_c',b'\x03'),
    ('v3_nonblocking_after',b'0\n',1,'nonblocking_after'),
    ('v3_partial_nonblocking',b's 1\n',1,'noncanonical_nonblocking_after','stop',[(0,b's'),(.25,b' 1\n')]),
    ('v3_per_device_paste',b'\x1b[200~s 1\x1b[201~\n',2),
    ('v4_partial_token',b's 1\n',1,'noncanonical_nonblocking_after','stop',[(0,b's 1'),(.25,b'\n')]),
    ('v4_partial_ctrl_c_noncanonical',b'\x03',1,'noncanonical','stop',[(0,b's'),(.4,b'\x03')]),
    ('v4_late_partial_canonical',b'0\n',1,'canonical','natural_partial',[(0,b'0'),(4,b'\n')]),
    ('v4_late_partial_noncanonical',b'0\n',1,'noncanonical','natural_partial',[(0,b'0'),(4,b'\n')]),
    ('v6_partial_ctrl_c_canonical',b'\x03',1,'canonical','stop',[(0,b's'),(.4,b'\x03')]),
]


def run_terminal_original_pty_checks():
    with tempfile.TemporaryDirectory(prefix='lvs-original-pty-') as name:
        rows=[run_case(Path(name),*case) for case in ORIGINAL_CASES]
        assert len(rows)==24


def run_terminal_boundary_pty_checks():
    cases=[
        ('inherited_nonblocking',b'0\n',1,'nonblocking'),
        ('raw_ctrl_c',b'\x03',1,'noncanonical_raw','stop',[(0,b's'),(.3,b'\x03')]),
        ('partial_temperature',b'0',1,'noncanonical','temperature_partial'),
        ('canonical_partial_temperature',b'0',1,'canonical','temperature_partial'),
        ('temperature_under_traffic',b'unknown\n'*8,1,'noncanonical','temperature_flood',
            [(i*.15,b'unknown\n'*8) for i in range(12)]),
        ('no_input',b'',1,'canonical','natural_partial',[]),
        ('fragmented_paste',b'0\n',1,'noncanonical','stop',[(0,b'\x1b[20'),(.1,b'0~s'),(.2,b' 1\x1b[201'),(.3,b'~\n')]),
        ('overlong',b'x'*1024+b'\n',1,'noncanonical','overflow'),
        ('queue_flood',b'unknown\n'*300,1,'noncanonical','overflow'),
        ('canonical_flood',b'x'*2048+b'\n',1,'canonical','overflow'),
        ('queued_beyond_cycle',b'unknown\n'*20+b'0\n',1,'noncanonical'),
        ('multiple_commands',b'unknown\ninvalid\ns 1\ns 2\n',2,'noncanonical'),
        ('completion_race',b'0\n',1,'canonical','completion_race',[(2.5,b'0\n')]),
        ('output_pressure',b'0\n',1,'noncanonical','output_pressure'),
        ('exception',b'',1,'canonical','exception'),
    ]
    with tempfile.TemporaryDirectory(prefix='lvs-boundary-pty-') as name:
        for case in cases:run_case(Path(name),*case)


def worker():
    """SIMULATION ONLY: bounded reads from a private regular file, not fio/guard."""
    import os,sys,time,json,signal,stat,fcntl
    seconds=float(sys.argv[2]);iops=int(sys.argv[3]);block=int(sys.argv[4]);events=sys.argv[5]
    assert stat.S_ISREG(os.fstat(0).st_mode) and fcntl.fcntl(0,fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY
    start=time.monotonic();stop=False;count=0;sig_received=None

    def event(kind,**more):
     with open(events,'a') as f:f.write(json.dumps(dict(kind=kind,pid=os.getpid(),monotonic=time.monotonic(),simulation_only=True,**more))+'\n')
    def interrupted(sig,frame):
     nonlocal stop,sig_received
     sig_received=sig;stop=True;event('signal',signal=sig)
    signal.signal(signal.SIGTERM,interrupted)
    event('started')
    print(json.dumps(dict(contract_id='lvs.storage_thermal.guard',contract_version=1,pid=os.getpid(),uid=os.getuid(),gid=os.getgid(),capabilities=0,seccomp=2,no_new_privs=1,readonly_direct=True,simulation_only=True),separators=(",",":")),file=sys.stderr,flush=True)
    while not stop and time.monotonic()-start<seconds:
     data=os.pread(0,block,0);assert len(data)==block;count+=1
     time.sleep(min(.02,max(0,start+count/iops-time.monotonic())))
     # paced in small steps for prompt simulated signal response
     while not stop and time.monotonic()<min(start+seconds,start+count/iops):time.sleep(.01)
    elapsed=time.monotonic()-start
    event('ended',signal=sig_received,reads=count,seconds=elapsed)
    print(json.dumps(dict(simulation_only=True,jobs=[dict(read=dict(total_ios=count,io_bytes=count*block,runtime=int(elapsed*1000)),write=dict(total_ios=0),trim=dict(total_ios=0),sync=dict(total_ios=0),error=0,usr_cpu=0,sys_cpu=0)])),flush=True)


if __name__=='__main__':
    sys.path.insert(0,str(ROOT))
    if sys.argv[1]=='fixture':fixture(Path(sys.argv[2]),int(sys.argv[3]),sys.argv[4],sys.argv[5])
    elif sys.argv[1]=='worker':
        worker()
