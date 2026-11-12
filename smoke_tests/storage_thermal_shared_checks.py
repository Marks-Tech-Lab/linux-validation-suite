"""Shared-data opt-in: topology fixtures and regular-file syscall/lock proofs only."""
from copy import deepcopy
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from unittest.mock import patch

from Modules.lvs_storage_thermal import ThermalConfig,pilot_rate
from Modules.lvs_storage_thermal_stage import stage_config,set_thermal_setting,LeaseTargets
from Modules.lvs_profile_models import StageConfig,ModuleStorageThermal
from smoke_tests.storage_thermal_runner_checks import TopologyFixture,RunnerFixture
from smoke_tests.storage_thermal_foundation_checks import rejects


def shared(**kwargs):
    return ThermalConfig(access_mode='shared_readonly_opt_in',aggregate_iops_limit=128,
                         aggregate_bps_limit=8*1024**2,**kwargs)


def run_shared_contract_checks():
    assert ThermalConfig().access_mode=='exclusive'
    rejects(lambda:ThermalConfig(access_mode='shared_readonly_opt_in'))
    rejects(lambda:shared(monitoring='approved_unmonitored',unmonitored_approval='not allowed'))
    rejects(lambda:replace(shared(),aggregate_iops_limit=True))
    assert [pilot_rate(shared(),'one',c)['effective_iops'] for c in ('hdd','ssd','nvme')]==[15,64,128]
    assert pilot_rate(shared(),'one','hdd',system=True)['effective_iops']==7
    s=StageConfig('x','x',60);s.modules.storage_thermal.enabled=True
    set_thermal_setting(s,'thermal_aggregate_iops_limit','128')
    set_thermal_setting(s,'thermal_aggregate_bps_limit','8388608')
    set_thermal_setting(s,'thermal_access_mode','shared_readonly_opt_in')
    assert stage_config(s).access_mode=='shared_readonly_opt_in'
    assert stage_config(s).duration_seconds==60
    # The stage lifetime wrapper forwards the same contract rather than reverting
    # to exclusive discovery in the supervisor subprocess.
    target=type('Targets',(),{'discover':lambda self,**kw:kw})()
    lease=type('Lease',(),{'check':lambda self:None})()
    assert LeaseTargets(target,lease).discover(access_mode='shared_readonly_opt_in')['access_mode']=='shared_readonly_opt_in'


def run_shared_topology_checks():
    with tempfile.TemporaryDirectory() as directory:
        f=TopologyFixture(directory)
        def relocate(node,base):
            base.parent.mkdir(parents=True,exist_ok=True);node.parent.parent.rename(base)
            moved=base/'block'/node.name;(moved/'device').unlink();(moved/'device').symlink_to(base)
            (f.sys/node.name).unlink();(f.sys/node.name).symlink_to(moved)
            return moved
        hdd=relocate(f.disk(),f.root/'pci/ata2/disk')
        relocate(f.disk('sdb',serial='SSD',rotating=0),f.root/'pci/ata3/disk')
        sas=relocate(f.disk('sdc',serial='SASSSD',rotating=0),f.root/'pci/port-1:0/end_device-1:0')
        address=sas.parent.parent/'sas_device/end_device-1:0';address.mkdir(parents=True);(address/'sas_address').write_text('0x1234')
        # Positive local PCIe controller + one namespace, not an nvme-shaped name.
        controller=f.root/'pci/nvme/nvme0';node=controller/'nvme0n1';node.mkdir(parents=True)
        for d in ('queue','holders','slaves'):(node/d).mkdir()
        (node/'device').symlink_to(controller)
        for name,value in {'serial':'NVME','transport':'pcie','model':'Fixture'}.items():(controller/name).write_text(value)
        for name,value in {'size':'65536','dev':'259:0','removable':'0','queue/rotational':'0','queue/logical_block_size':'512'}.items():(node/name).write_text(value)
        (f.sys/'nvme0n1').symlink_to(node);(f.root/'nvme').mkdir();(f.root/'nvme/nvme0').symlink_to(controller)
        (f.dev/'nvme0n1').write_bytes(b'fixture')
        with patch('Modules.lvs_storage_thermal_targets.Path.exists',autospec=True,side_effect=lambda p:False if str(p) in ('/.dockerenv','/run/.containerenv') else os.path.exists(p)):
            f.resolver.sys_fs_btrfs=f.root/'btrfs';(f.root/'btrfs/uuid/devices/sda').mkdir(parents=True)
            for fs in ('ext4','xfs','btrfs'):
                (f.proc/'self/mountinfo').write_text(f'1 0 0:1 / / rw - rootfs rootfs rw\n2 1 8:0 / /data rw - {fs} /dev/sda rw\n')
                original=f.resolver.discover();assert not next(r for r in original if r['identity']['name']=='sda')['eligible']
                rows=f.resolver.discover(access_mode='shared_readonly_opt_in')
                assert all(r['eligible'] for r in rows),rows
                assert all(r['access_mode']=='shared_readonly_opt_in' and 'node_inode' in r['identity'] for r in rows)
                data=next(r for r in rows if r['identity']['name']=='sda')
                assert data['mounted_or_active'] and f.resolver.revalidate(data)['eligible']
            (f.root/'btrfs/uuid/devices/sdb').mkdir()
            rows=f.resolver.discover(access_mode='shared_readonly_opt_in')
            assert not next(r for r in rows if r['identity']['name']=='sda')['eligible']
            (f.root/'btrfs/uuid/devices/sdb').rmdir()
            (f.proc/'self/mountinfo').write_text('1 0 8:0 / / rw - ext4 /dev/sda rw\n')
            rows=f.resolver.discover(access_mode='shared_readonly_opt_in');assert not next(r for r in rows if r['identity']['name']=='sda')['eligible']
            (f.proc/'self/mountinfo').write_text('1 0 0:1 / / rw - rootfs rootfs rw\n')
            (hdd/'holders/dm-0').mkdir();assert not next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['identity']['name']=='sda')['eligible']
            (hdd/'holders/dm-0').rmdir()
            second=controller/'nvme0n2';second.mkdir()
            assert not next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['transport']=='nvme')['eligible']
            second.rmdir();(controller/'transport').write_text('tcp')
            assert not next(r for r in f.resolver.discover(access_mode='shared_readonly_opt_in') if r['transport']=='nvme')['eligible']


def run_shared_descriptor_checks():
    with tempfile.TemporaryDirectory() as directory:
        f=TopologyFixture(directory);f.disk();path=f.dev/'sda'
        endpoint=path.stat()
        identity=dict(path=str(path),major=8,minor=0,size_bytes=33554432,logical_sector=512,node_device=endpoint.st_dev,node_inode=endpoint.st_ino)
        row=dict(device_id='fixture',identity=identity,access_mode='shared_readonly_opt_in')
        fd=os.open(path,os.O_RDONLY|os.O_DIRECT);real=os.fstat(fd)
        fake=type('Stat',(),dict(st_mode=0o60600,st_rdev=os.makedev(8,0),st_dev=real.st_dev,st_ino=real.st_ino))()
        def ioctl(_fd,request,data):return struct.pack('Q',33554432) if request==0x80081272 else struct.pack('I',512)
        with patch.object(f.resolver,'revalidate',return_value=row),patch('Modules.lvs_storage_thermal_targets.os.open',return_value=fd) as opener,patch('Modules.lvs_storage_thermal_targets.os.fstat',return_value=fake),patch('Modules.lvs_storage_thermal_targets.fcntl.ioctl',side_effect=ioctl):
            result=f.resolver.open(row);flags=opener.call_args.args[1]
            assert not flags&os.O_EXCL and flags&os.O_DIRECT and flags&os.O_NOFOLLOW and flags&os.O_CLOEXEC
        # Genuine independent-process OFD lifetime test, never a block device.
        code='import os,fcntl,sys;f=os.open(sys.argv[1],os.O_RDONLY);fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
        child=lambda:subprocess.run([os.sys.executable,'-B','-c',code,str(path)],capture_output=True,timeout=5)
        alias=os.dup(result);os.close(result)
        assert child().returncode!=0
        os.close(alias);assert child().returncode==0
        fd=os.open(path,os.O_RDONLY|os.O_DIRECT)
        with patch.object(f.resolver,'revalidate',side_effect=[row,ValueError('mounted target replaced')]),patch('Modules.lvs_storage_thermal_targets.os.open',return_value=fd),patch('Modules.lvs_storage_thermal_targets.os.fstat',return_value=fake),patch('Modules.lvs_storage_thermal_targets.fcntl.ioctl',side_effect=ioctl):
            rejects(lambda:f.resolver.open(row))
        rejects(lambda:os.fstat(fd))


def run_shared_supervisor_checks():
    for mode in ('exclusive','shared_readonly_opt_in'):
        with tempfile.TemporaryDirectory() as directory:
            f=RunnerFixture(directory)
            for r in f.rows:r['access_mode']=mode
            f.targets.discover=lambda **kw:deepcopy(f.rows)
            original=f.runner.activity
            def background():
                rows=original()
                for values in rows.values():values[4]=values[6]=int(f.clock.now*5)
                return rows
            f.runner.activity=background
            config=shared(duration_seconds=2) if mode!='exclusive' else ThermalConfig(duration_seconds=2)
            _,result=f.run(config)
            assert result['verdict']==('WARN' if mode!='exclusive' else 'FAIL'),result
            if mode!='exclusive':
                assert result['devices'][0]['state']=='completed' and result['devices'][0]['write_ios']==0
                assert result['devices'][0]['last_observation']['background_write_ios_since_launch']>0
                assert all(r['cleanup_confirmed'] for r in result['devices'])
    with tempfile.TemporaryDirectory() as directory:
        f=RunnerFixture(directory,2)
        config=replace(shared(),aggregate_iops_limit=29)
        assert f.plan(config)['status']=='BLOCKED'
        config=replace(shared(),aggregate_bps_limit=1)
        assert f.plan(config)['status']=='BLOCKED'
        f.temp=None;assert f.plan(shared())['status']=='BLOCKED'

    with tempfile.TemporaryDirectory() as directory:
        f=RunnerFixture(directory,28)
        for i,row in enumerate(f.rows):row['drive_class']='hdd' if i<24 else 'ssd' if i<26 else 'nvme'
        config=replace(shared(),aggregate_iops_limit=744,aggregate_bps_limit=744*65536)
        assert len(f.plan(config)['runnable_devices'])==28
        assert f.plan(shared())['status']=='BLOCKED'
        f.runner.budget=lambda:dict(memory_budget=1,fd_limit=65536)
        assert f.plan(config)['status']=='BLOCKED'


def run_shared_owned_stage_checks():
    from Modules.lvs_storage_thermal_launch import OwnedProcess,prepare,provenance
    from Modules.lvs_storage_thermal_stage import decision_key
    from smoke_tests.storage_thermal_stage_checks import fixture_stage_worker
    with tempfile.TemporaryDirectory() as directory:
        prepare(directory);f=RunnerFixture(directory)
        one=OwnedProcess(['/bin/sleep','30']);two=OwnedProcess(['/bin/sleep','30'])
        try:
            actual=one.authority_pid;one.pid=two.pid
            f.runner._signal_process(one,15);one.wait(timeout=5)
            assert f.runner._process_pid(one)==actual and f.runner._clean_process(one)
            assert two.poll() is None
        finally:
            for child in (one,two):
                if child.poll() is None:child.kill()
                child.wait(timeout=5)
    with tempfile.TemporaryDirectory() as root:
        f=RunnerFixture(root);f.rows[0]['access_mode']='shared_readonly_opt_in'
        f.targets.discover=lambda **kw:deepcopy(f.rows)
        config=shared(duration_seconds=1)
        plan=f.plan(config);plan['backend']=dict(plan['backend'],stage_admission_protocol='v2',owned_launcher=provenance())
        plan.update(requires_consent=False,decision_key=decision_key(plan))
        directory=Path(root)/'stage';directory.mkdir()
        (directory/'request.json').write_text(json.dumps(dict(plan,supervisor_parent_pid=os.getppid(),recovery_marker=str(Path(root)/'recovery.json'))))
        with patch('Modules.lvs_storage_thermal_stage.default_runner',return_value=f.runner),patch('Modules.lvs_storage_thermal_runner.capability',return_value=f.backend),f.context():
            assert fixture_stage_worker(directory,f)==0
        result=json.loads((directory/'completion.json').read_text())
        assert result['verdict']=='WARN' and result['devices'][0]['access_mode']=='shared_readonly_opt_in'
        assert result['devices'][0]['cleanup_confirmed']


def run_shared_interactive_checks():
    import contextlib,io
    from types import SimpleNamespace
    from lvs_storage_thermal_assist import ThermalMenu,main
    answers=iter(['6','2','',''])
    ui=SimpleNamespace(write=lambda text:None,ask=lambda prompt:next(answers))
    menu=ThermalMenu(None,ThermalConfig(),'/unused',screens=ui)
    menu.advanced()
    assert menu.config.access_mode=='shared_readonly_opt_in'
    assert menu.config.aggregate_iops_limit==128 and menu.config.aggregate_bps_limit==8388608
    s=StageConfig('id','stage',120);s.modules.storage_thermal.enabled=True
    set_thermal_setting(s,'thermal_device_ids','wwn:one, wwn:two')
    set_thermal_setting(s,'thermal_selection','individual')
    assert stage_config(s).device_ids==['wwn:one','wwn:two']
    calls=[]
    fake=SimpleNamespace(discover=lambda config:(calls.append(config) or []))
    with patch('lvs_storage_thermal_assist.ThermalRunner',return_value=fake),contextlib.redirect_stdout(io.StringIO()):
        assert main(['--check','--access-mode','shared_readonly_opt_in','--aggregate-iops-limit','128','--aggregate-bps-limit','8388608'])==0
    assert calls[0].access_mode=='shared_readonly_opt_in'


def run_shared_vm_evidence_checks():
    from scripts.storage_thermal_shared_probe import verify
    def reject_vm(call):
        try:call()
        except RuntimeError:return
        raise AssertionError('invalid VM evidence accepted')
    def run(name):
        target=dict(access_mode='shared_readonly_opt_in',identity=dict(node_inode=1),mounted_or_active=name!='unmounted_hdd',
                    drive_class='ssd' if name=='mounted_ssd' else 'nvme' if name in ('mounted_nvme','concurrent') else 'hdd')
        drive=dict(state='completed',read_ios=1,read_bytes=65536,guard_confirmed=True,identity_unchanged=True,
                   provenance_confirmed=True,cleanup_confirmed=True,terminal_published=True,write_ios=0,discard_ios=0,flush_ios=0,
                   started_monotonic=1,ended_monotonic=10)
        return dict(verdict='WARN',parent_finalization_complete=True,devices=[drive],readiness=dict(targets=[target]),fixture_fresh_recovery_blocked=False)
    result=dict(contract='lvs.storage_thermal.shared_vm.v1',campaign='full',error=None,ordinary_writes=[dict(bytes=4096)],results={
        name:run(name) for name in ('unmounted_hdd','mounted_hdd_writes','mounted_ssd','mounted_nvme','concurrent')})
    result['results'].update(root_rejected=True,cancel=dict(verdict='INCOMPLETE',devices=[dict(cleanup_confirmed=True)]),
        primary_proxy=dict(elapsed=2,samples=[{},{}]),observer=dict(access_mode='shared_readonly_opt_in',complete=True))
    verify(result)
    for name,field,value in [('mounted_nvme','cleanup_confirmed',False),('mounted_ssd','write_ios',1)]:
        bad=deepcopy(result);bad['results'][name]['devices'][0][field]=value;reject_vm(lambda:verify(bad))
    bad=deepcopy(result);bad['results']['mounted_hdd_writes']['readiness']['targets'][0]['access_mode']='exclusive';reject_vm(lambda:verify(bad))
    bad=deepcopy(result);bad['results']['root_rejected']=False;reject_vm(lambda:verify(bad))
    result['campaign']='active-overlap';result['results']['active_primary_proxy']=dict(start=3,end=5,samples=[{},{}]);verify(result)
    result['results']['active_primary_proxy']['end']=11;reject_vm(lambda:verify(result))
