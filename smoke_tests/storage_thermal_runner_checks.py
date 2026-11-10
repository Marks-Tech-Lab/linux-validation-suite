"""Synthetic topology and supervisor fixtures. Never open a host block device."""
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from Modules.lvs_storage_thermal import ThermalConfig
from Modules.lvs_storage_thermal_backend import executable_identity
from Modules.lvs_storage_thermal_targets import ThermalTargets, selected, temperature
from Modules.lvs_storage_thermal_runner import ThermalRunner, approve_unmonitored, approval_valid
from Modules.lvs_profile_report_artifacts import atomic_preflight_json
from smoke_tests.storage_thermal_foundation_checks import compile_guard, rejects


class TopologyFixture:
    def __init__(self,root):
        self.root=Path(root);self.sys=self.root/'class';self.sys.mkdir()
        self.proc=self.root/'proc';(self.proc/'self/ns').mkdir(parents=True);(self.proc/'1/ns').mkdir(parents=True)
        (self.proc/'self/ns/mnt').write_text('');os.link(self.proc/'self/ns/mnt',self.proc/'1/ns/mnt')
        (self.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n')
        (self.proc/'swaps').write_text('Filename Type Size Used Priority\n')
        self.dev=self.root/'dev';self.dev.mkdir();self.hwmon=self.root/'hwmon';self.hwmon.mkdir()
        self.udev=self.root/'udev';self.udev.mkdir()
        self.resolver=ThermalTargets(self.sys,self.dev,self.proc,self.udev,self.hwmon)

    def disk(self,name='sda',serial='SERIAL-A',transport='sata',rotating=1):
        route='pci/ata1/host1/target1/disk' if transport=='sata' else 'pci/usb1/disk' if transport=='usb' else 'virtual/block'
        node=self.root/route/'block'/name;node.mkdir(parents=True)
        (self.sys/name).symlink_to(node,target_is_directory=True)
        (node/'device').symlink_to(node.parent.parent,target_is_directory=True)
        for d in ('holders','slaves','queue'):(node/d).mkdir()
        for file,value in {'size':'65536','dev':f'8:{len(list(self.sys.iterdir()))-1}','removable':'0',
                           'queue/logical_block_size':'512','queue/rotational':str(rotating),
                           'device/model':'Fixture','device/serial':serial}.items():
            (node/file).write_text(value)
        (self.dev/name).write_bytes(bytes(65536))
        return node


def run_thermal_target_discovery_checks():
    with tempfile.TemporaryDirectory() as root:
        f=TopologyFixture(root);node=f.disk()
        # Tests never depend on the development host/container mount view.
        with patch('Modules.lvs_storage_thermal_targets.Path.exists',autospec=True,side_effect=lambda p:False if str(p) in ('/.dockerenv','/run/.containerenv') else os.path.exists(p)):
            rows=f.resolver.discover();assert rows[0]['eligible'],rows
            assert rows[0]['device_id']=='serial:sata:SERIAL-A'
            for group in ('all_internal','sata_sas','hdd'):
                assert selected(rows[0],ThermalConfig(selection=group))
            expected=deepcopy(rows[0]);(node/'device/serial').write_text('REPLACED')
            rejects(lambda:f.resolver.revalidate(expected))
            (node/'device/serial').write_text('SERIAL-A')
            (node/'holders/dm-0').mkdir();assert not f.resolver.discover()[0]['eligible']
            (node/'holders/dm-0').rmdir()
            (f.proc/'self/mountinfo').write_text('1 0 8:0 / / rw - ext4 /dev/sda rw\n')
            row=f.resolver.discover()[0];assert row['system_drive'] and not row['eligible']
            btrfs=f.root/'btrfs';(btrfs/'uuid/devices/sda').mkdir(parents=True);f.resolver.sys_fs_btrfs=btrfs
            (f.proc/'self/mountinfo').write_text('1 0 0:8 / / rw - btrfs /dev/sda rw\n')
            assert f.resolver.discover()[0]['system_drive']
            (f.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n2 1 0:2 / /pool rw - zfs tank rw\n')
            assert not f.resolver.discover()[0]['eligible']
    with tempfile.TemporaryDirectory() as root:
        f=TopologyFixture(root);node=f.disk();device=(node/'device').resolve()
        monitor=device/'hwmon/hwmon0';monitor.mkdir(parents=True);(f.hwmon/'hwmon0').symlink_to(monitor)
        for name,value in {'name':'drivetemp','temp1_input':'30000','temp1_crit':'60000','temp1_max':'50000','temp1_lcrit':'-10000'}.items():
            (monitor/name).write_text(value)
        with patch('Modules.lvs_storage_thermal_targets.read_temperature_path',side_effect=AssertionError('passive discovery read a temperature')):
            sensors=f.resolver.sensors(node)
        reading=temperature({'sensors':sensors})
        assert reading['value_c']==30 and reading['critical_c']==60 and reading['low_critical_c']==-10 and reading['complete']
    with tempfile.TemporaryDirectory() as root:
        f=TopologyFixture(root);f.disk('sda',transport='usb');f.disk('sdb',serial='SSD',rotating=0)
        rows=f.resolver.discover()
        usb=next(r for r in rows if r['transport']=='usb')
        assert all(not selected(usb,ThermalConfig(selection=g)) for g in ('all_internal','sata_sas','nvme','hdd','ssd'))
        assert selected(usb,ThermalConfig(selection='individual',device_ids=(usb['device_id'],))) and not usb['eligible']


def run_thermal_exclusive_open_checks():
    with tempfile.TemporaryDirectory() as root:
        f=TopologyFixture(root);node=f.disk();row=dict(device_id='fixture',identity=dict(path=str(f.dev/'sda'),major=8,minor=0,size_bytes=33554432,logical_sector=512))
        fd=os.open(f.dev/'sda',os.O_RDONLY|os.O_DIRECT)
        original_fstat=os.fstat
        fake=type('Stat',(),dict(st_mode=0o60600,st_rdev=os.makedev(8,0)))()
        flags=os.O_RDONLY|os.O_DIRECT
        import struct,fcntl
        def ioctl(_fd,request,data):return struct.pack('Q',33554432) if request==0x80081272 else struct.pack('I',512)
        with patch.object(f.resolver,'revalidate',return_value=row) as check, patch('Modules.lvs_storage_thermal_targets.os.open',return_value=fd) as opener, patch('Modules.lvs_storage_thermal_targets.os.fstat',return_value=fake),patch('Modules.lvs_storage_thermal_targets.fcntl.ioctl',side_effect=ioctl):
            opened=f.resolver.open(row)
            assert opened==fd and check.call_count==2
            assert opener.call_args.args[1]&os.O_EXCL and opener.call_args.args[1]&os.O_NOFOLLOW
        os.close(fd)
        with patch.object(f.resolver,'revalidate',return_value=row),patch('Modules.lvs_storage_thermal_targets.os.open',side_effect=PermissionError('denied')):
            rejects(lambda:f.resolver.open(row))
        fd=os.open(f.dev/'sda',os.O_RDONLY|os.O_DIRECT)
        with patch.object(f.resolver,'revalidate',side_effect=[row,ValueError('changed after open')]),patch('Modules.lvs_storage_thermal_targets.os.open',return_value=fd),patch('Modules.lvs_storage_thermal_targets.os.fstat',return_value=fake),patch('Modules.lvs_storage_thermal_targets.fcntl.ioctl',side_effect=ioctl):
            rejects(lambda:f.resolver.open(row))
        try:original_fstat(fd)
        except OSError:pass
        else:raise AssertionError('descriptor leaked after race')


class Clock:
    def __init__(self):self.now=0
    def __call__(self):return self.now
    def sleep(self,n):self.now+=n


class RunnerFixture:
    def __init__(self,root,count=1):
        self.root=Path(root);self.clock=Clock();self.guard=compile_guard(root)
        self.fio=Path('/bin/true').resolve();self.data=self.root/'data';self.data.write_bytes(bytes(65536))
        self.rows=[dict(device_id=f'wwn:fixture-{i}',identity=dict(device_id=f'wwn:fixture-{i}',major=8,minor=i,size_bytes=65536,logical_sector=512,path=str(self.data)),
                        model='synthetic fixture',transport='sata',drive_class='hdd',internal=True,excluded_automatic=False,
                        system_drive=False,eligible=True,reasons=[],sensors=[]) for i in range(count)]
        self.temp=30.;self.failure=None;self.children={};self.fd_open=[]
        self.backend=dict(status='available',fio=executable_identity(str(self.fio)),guard=executable_identity(str(self.guard)),reasons=[])
        self.source=dict(source=dict(status='complete',digest='fixture'))
        self.targets=type('Targets',(),{})()
        self.targets.discover=lambda:deepcopy(self.rows)
        def open_target(row):
            fd=os.open(self.data,os.O_RDONLY);self.fd_open.append(fd);return fd
        def revalidate(row):
            live=next(r for r in self.rows if r['device_id']==row['device_id'])
            if live['identity']!=row['identity'] or not live['eligible']:raise ValueError('identity changed')
            return live
        self.targets.open=open_target;self.targets.revalidate=revalidate
        self.targets.output_safe=lambda path,records:None
        self.runner=ThermalRunner(self.fio,self.guard,targets=self.targets,clock=self.clock,sleep=self.clock.sleep,popen=self.popen,
                                  source=lambda:self.source,budget=lambda:dict(memory_budget=1024**3,memory_available=2*1024**3,fd_limit=1024),
                                  temperature_reader=lambda row:dict(value_c=self.temp,critical_c=60.,warning_c=50.,complete=self.temp is not None),
                                  activity=lambda:{(8,i):[int(self.clock.now*15),0,int(self.clock.now*1920),0,0,0,0,0,0,0,0,0,0,0,0,0,0] for i in range(count)})
    def popen(self,args,**kwargs):
        self.fixture_args=args;fixture=self;index=len(self.children);pid=20000+index
        seconds=int(args[-1]);iops=int(args[-2]);start=self.clock()
        class Process:
            returncode=None
            def __init__(self):self.pid=pid
            @property
            def authority_pid(self):return pid
            def send_signal(self,sig):fixture.kill(pid,sig)
            def group_cleanup_confirmed(self):return self.poll() is not None
            def poll(self):
                if self.returncode is None and fixture.clock()-start>=seconds+.2:self.returncode=0
                return self.returncode
            def wait(self,timeout=None):
                value=self.poll()
                if value is None:raise subprocess.TimeoutExpired(args,timeout)
                return value
        p=Process();self.children[pid]=p
        guard=dict(contract_id='lvs.storage_thermal.guard',contract_version=1,pid=pid,uid=os.getuid(),gid=os.getgid(),capabilities=0,seccomp=2,no_new_privs=1,readonly_direct=True)
        kwargs['stderr'].write((json.dumps(guard,separators=(',',':'))+'\n').encode());kwargs['stderr'].flush()
        job=dict(read=dict(total_ios=seconds*iops,io_bytes=seconds*iops*65536,runtime=seconds*1000),
                 write=dict(total_ios=0),trim=dict(total_ios=0),error=0,usr_cpu=.1,sys_cpu=.1)
        kwargs['stdout'].write(json.dumps(dict(jobs=[job])).encode());kwargs['stdout'].flush()
        return p
    def kill(self,pid,sig):
        if sig==0:
            if self.children[pid].poll() is not None:raise ProcessLookupError()
        else:self.children[pid].returncode=-sig
    def context(self):return patch('Modules.lvs_storage_thermal_runner.os.killpg',side_effect=self.kill)
    def plan(self,config):return self.runner.plan(config,deepcopy(self.rows),self.backend)
    def run(self,config,**kwargs):
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=self.backend),self.context():
            return self.runner.run(config,self.plan(config),self.root/'outputs',**kwargs)


def run_thermal_supervisor_completion_checks():
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root,3);config=ThermalConfig(duration_seconds=1)
        directory,result=f.run(config)
        assert result['verdict']=='PASS',result
        assert len(result['executed_devices'])==3 and all(r['cleanup_confirmed'] and r['terminal_published'] for r in result['devices'])
        assert json.loads((directory/'storage_thermal_manifest.json').read_text())['parent_finalization_complete']
        for fd in f.fd_open:
            try:os.fstat(fd)
            except OSError:pass
            else:raise AssertionError('exclusive claim leaked')
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root,28)
        for r in f.rows[24:]:r.update(eligible=False,reasons=['SSD/NVMe not approved'],drive_class='ssd')
        plan=f.plan(ThermalConfig(duration_seconds=2))
        assert len(plan['runnable_devices'])==24 and len(plan['blocked_devices'])==4 and plan['partial_coverage']
        rejects(lambda:f.run(ThermalConfig(duration_seconds=2)))
        _,result=f.run(ThermalConfig(duration_seconds=2),allow_partial=True)
        assert result['verdict']=='WARN' and len(result['executed_devices'])==24


def run_thermal_monitoring_and_approval_checks():
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.temp=None;c=ThermalConfig(duration_seconds=1)
        assert f.plan(c)['status']=='BLOCKED'
        c=replace(c,monitoring='approved_unmonitored',unmonitored_approval='pending')
        c=approve_unmonitored(c,[f.rows[0]['device_id']],'explicit synthetic test')
        assert approval_valid(c,[f.rows[0]['device_id']])
        assert not approval_valid(replace(c,duration_seconds=3600),[f.rows[0]['device_id']])
        assert not approval_valid(c,['different'])
        _,result=f.run(c);assert result['verdict']=='WARN' and result['devices'][0]['temperature_status']=='unmonitored'
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.temp=65
        assert f.plan(ThermalConfig())['status']=='BLOCKED'
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root)
        def control(jobs):
            if jobs:f.temp=None
            return []
        _,result=f.run(ThermalConfig(duration_seconds=3),control=control)
        assert result['verdict']=='FAIL' and 'temperature provider' in result['devices'][0]['stop_reason']


def run_thermal_cancellation_and_race_checks():
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root,2)
        _,result=f.run(ThermalConfig(duration_seconds=2),control=lambda jobs:['wwn:fixture-0'] if jobs else [])
        assert result['verdict']=='INCOMPLETE'
        assert result['devices'][0]['state']=='cancelled' and result['devices'][1]['state']=='completed'
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root)
        def control(jobs):
            if jobs:f.rows[0]['identity']['size_bytes']=1
            return []
        _,result=f.run(ThermalConfig(duration_seconds=8),control=control)
        assert result['verdict']=='FAIL' and result['devices'][0]['safety_stop']
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.targets.open=lambda row:(_ for _ in ()).throw(PermissionError('permission changed'))
        rejects(lambda:f.run(ThermalConfig(duration_seconds=1)))
        assert f.runner.last_preflight['status']=='BLOCKED' and not f.children


def run_thermal_persistence_and_ui_checks():
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);calls={}
        def publish(path,payload):
            calls[str(path)]=calls.get(str(path),0)+1
            if path.parent.name=='worker_results' and calls[str(path)]==1:raise OSError('transient publish error')
            atomic_preflight_json(path,payload)
        f.runner.publish=publish
        _,result=f.run(ThermalConfig(duration_seconds=1));assert result['verdict']=='PASS'
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root)
        def publish(path,payload):
            if path.name=='storage_thermal_manifest.json' and payload.get('parent_finalization_complete'):raise OSError('final commit failed')
            atomic_preflight_json(path,payload)
        f.runner.publish=publish
        try:f.run(ThermalConfig(duration_seconds=1))
        except OSError:pass
        else:raise AssertionError('failed final publication returned success')
        manifest=json.loads(next((Path(root)/'outputs').glob('*/storage_thermal_manifest.json')).read_text())
        assert manifest['verdict']=='INCOMPLETE' and manifest['status']=='running'
    # Standard-library startup and safe redirected operation; no hardware scan.
    root=Path(__file__).resolve().parents[1]
    p=subprocess.run([os.sys.executable,'-S',str(root/'lvs_storage_thermal_assist.py'),'--help'],capture_output=True,text=True)
    assert p.returncode==0 and '\x1b' not in p.stdout
    from lvs_storage_thermal_assist import ThermalMenu
    from Modules.lvs_environment_ui import EnvironmentScreens
    choices=iter(['3','40','20','4','60','8']);output=[]
    menu=ThermalMenu(None,ThermalConfig(),'/not-used',EnvironmentScreens(ask=lambda _:next(choices),output=output.append,stdin=io.StringIO(),stdout=io.StringIO()))
    menu.run();assert menu.config.intensity_percent==40 and menu.config.system_intensity_percent==20 and menu.config.duration_seconds==60
    assert not any('\x1b' in v for v in output)
    script='''import os,signal,sys
from smoke_tests.storage_thermal_runner_checks import RunnerFixture
from Modules.lvs_storage_thermal import ThermalConfig
f=RunnerFixture(sys.argv[1]); sent=False
def control(jobs):
 global sent
 if jobs and not sent:sent=True;os.kill(os.getpid(),signal.SIGHUP)
 return []
_,result=f.run(ThermalConfig(duration_seconds=2),control=control)
assert result['verdict']=='INCOMPLETE' and result['devices'][0]['cleanup_confirmed']
'''
    with tempfile.TemporaryDirectory(prefix='lvs-hup-regression-') as directory:
        p=subprocess.run([os.sys.executable,'-c',script,directory],capture_output=True,text=True,timeout=20)
        assert p.returncode==0,p.stderr
    with tempfile.TemporaryDirectory() as directory:
        f=RunnerFixture(directory);prompts=[];outputs=[]
        def cancel(prompt):prompts.append(prompt);return ''
        menu=ThermalMenu(f.runner,ThermalConfig(duration_seconds=1),Path(directory)/'ui',
                         EnvironmentScreens(ask=cancel,output=outputs.append,stdin=io.StringIO(),stdout=io.StringIO()),recovery_marker=Path(directory)/'recovery')
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend):menu.start()
        assert prompts==['Choose [2]: '] and not f.children
        answers=iter(['1','1']);prompts.clear()
        def approve(prompt):prompts.append(prompt);return next(answers)
        menu.ui.ask=approve
        with patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend),f.context():menu.start()
        assert prompts.count('Choose [2]: ')==1 and len(f.children)==1
        assert not any('"contract_id"' in v for v in outputs)


def run_thermal_io_and_cleanup_failure_checks():
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root,2);original=f.popen
        def io_error(args,**kwargs):
            p=original(args,**kwargs);p.returncode=5
            stream=kwargs['stdout'];stream.seek(0);stream.truncate()
            stream.write(json.dumps(dict(jobs=[dict(read=dict(total_ios=0,io_bytes=0,runtime=0),write=dict(total_ios=0),trim=dict(total_ios=0),error=5)])).encode());stream.flush()
            return p
        f.runner.popen=io_error
        _,result=f.run(ThermalConfig(duration_seconds=2))
        assert result['verdict']=='FAIL' and result['devices'][0]['errors']==5
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);original=f.popen
        def stuck(args,**kwargs):
            p=original(args,**kwargs);p.poll=lambda:None;return p
        f.runner.popen=stuck
        _,result=f.run(ThermalConfig(duration_seconds=1))
        r=result['devices'][0]
        assert result['verdict']=='INCOMPLETE' and r['forced_kill'] and not r['cleanup_confirmed'] and r['outstanding_descriptors']==1
        try:
            try:f.run(ThermalConfig(duration_seconds=1))
            except RuntimeError:pass
            else:raise AssertionError('unconfirmed ownership was silently reused')
        finally:
            for j in f.runner.unconfirmed:os.close(j['fd'])  # only a fake process; release fixture file


def run_thermal_reporting_and_resource_checks():
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.temp=52
        _,result=f.run(ThermalConfig(duration_seconds=1))
        assert result['verdict']=='WARN' and result['devices'][0]['temperature_warning']
        assert result['devices'][0]['temperature_end_c']==52
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root,24);f.runner.budget=lambda:dict(memory_budget=1024,memory_available=2048,fd_limit=1024)
        assert f.plan(ThermalConfig())['status']=='BLOCKED'
        f.runner.budget=lambda:dict(memory_budget=2**30,memory_available=2**30,fd_limit=36)
        assert f.plan(ThermalConfig())['status']=='BLOCKED'
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root)
        def publish(path,payload):
            if path.parent.name=='worker_results':raise OSError('terminal persistence unavailable')
            atomic_preflight_json(path,payload)
        f.runner.publish=publish
        _,result=f.run(ThermalConfig(duration_seconds=1))
        assert result['verdict']=='INCOMPLETE' and not result['devices'][0]['terminal_published']
