"""Transactional installer failure fixtures; no host promotion or devices."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from scripts import storage_thermal_install as install


def bundle(root,variation=''):
    root.mkdir();files={'launch.py':b'approved fixture only','runtime/build/fio':b'approved fio','runtime/build/storage_thermal_guard':b'guard','runtime/build/storage_thermal_launch.so':b'bootstrap','runtime/native/storage_thermal_guard.c':b'guard source','runtime/native/storage_thermal_launch.c':b'launch source'}
    source=dict(digest='a'*64,status='complete')
    p=dict(source=source,fio_sha256=install.digest(files['runtime/build/fio']),native_sources={n:install.digest(files['runtime/native/'+n])for n in ('storage_thermal_guard.c','storage_thermal_launch.c')},variation=variation)
    files['preparation.json']=json.dumps(p).encode()
    for n,data in files.items():
        path=root/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    m=dict(contract='lvs.storage_thermal.offline_bundle.v1',source=source,uid=os.getuid(),gid=os.getgid(),files={n:install.digest(data)for n,data in files.items()})
    raw=json.dumps(m).encode();(root/'manifest.json').write_bytes(raw)
    (root/'SHA256SUMS').write_text(''.join(h+'  '+n+'\n'for n,h in sorted(dict(m['files'],**{'manifest.json':install.digest(raw)}).items())))
    return install.digest(raw)


class Service:
    def __init__(self,path):self.path=path;self.live=False;self.boot=False;self.fail=False;self.starts=0
    def quiescent(self,*_):return not self.live
    def active(self,*_):return self.live
    def enabled(self,*_):return self.boot
    def enable(self,unit,value):self.boot=value
    def old_unit(self,unit,path):return path.read_bytes()if path.exists()else None
    def stop(self,*_):self.live=False
    def start(self,*_):
        self.starts+=1
        if self.fail:self.fail=False;raise OSError('injected service start failure')
        self.live=True
    def run(self,*a,**k):return SimpleNamespace(returncode=0,stdout='')


def run_thermal_install_transaction_checks():
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);base=root/'opt';state=root/'state';units=root/'units'
        for p in (base,state,units):p.mkdir()
        unit=units/f'lvs-thermal-{os.getuid()}.service';svc=Service(unit);obj=install.Installer(base,state,units,svc,socket_root=root/'sockets')
        a=root/'a';ha=bundle(a);b=root/'b';hb=bundle(b,'upgrade')
        healthy=lambda p,m:dict(status='AVAILABLE',source=m['source'],recovery_blocker=None)
        with patch.object(install,'trusted',side_effect=lambda p,**k:p),patch.object(install,'worker_account',return_value=(65533,65533)),patch.object(obj,'check',return_value={'status':'VERIFIED'}),patch.object(obj,'health',side_effect=healthy),patch.object(install.pwd,'getpwuid',return_value=SimpleNamespace(pw_gid=os.getgid())):
            # No native/code execution is mocked as a qualification claim here;
            # the sealed VM separately runs the real installed call path.
            assert obj.install(a,ha)['status']=='INSTALLED';before=unit.read_bytes()
            assert obj.install(a,ha)['status']=='UNCHANGED'
            svc.fail=True
            try:obj.install(b,hb)
            except OSError:pass
            else:raise AssertionError('promotion failure accepted')
            assert svc.live and unit.read_bytes()==before
            original_atomic=install.atomic
            def failed_persistence(path,data):
                if path.name.startswith('installation-')and json.loads(data).get('phase')=='promoting':raise OSError(28,'injected durable promotion ENOSPC')
                return original_atomic(path,data)
            with patch.object(install,'atomic',side_effect=failed_persistence):
                try:obj.install(b,hb)
                except OSError:pass
                else:raise AssertionError('failed promotion persistence accepted')
            assert svc.live and unit.read_bytes()==before
            assert obj.install(b,hb)['status']=='INSTALLED';assert unit.read_bytes()!=before
            obj.rollback(os.getuid());assert svc.live and unit.read_bytes()==before
            r=state/f'installation-{os.getuid()}.json';v=json.loads(r.read_text());v['phase']='promoting';r.write_text(json.dumps(v))
            try:obj.install(a,ha)
            except ValueError:pass
            else:raise AssertionError('interrupted promotion ignored')
            obj.rollback(os.getuid());assert svc.live


def run_thermal_install_input_checks():
    for name in ('/etc/passwd','../secret','a//b','a/./b','line\nbreak','a/../../x'):
        try:install.relative(name)
        except ValueError:pass
        else:raise AssertionError(name)
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);(root/'real').mkdir();(root/'real/file').write_bytes(b'approved');(root/'link').symlink_to(root/'real',target_is_directory=True)
        try:install.source_file(root,'link/file',1024)
        except OSError:pass
        else:raise AssertionError('symlink ancestor accepted')
        fifo=root/'fifo';os.mkfifo(fifo)
        try:install.source_file(root,'fifo',1024)
        except ValueError:pass
        else:raise AssertionError('special input opened for reading')
        p=root/'file';p.write_bytes(b'x');os.link(p,root/'hard')
        try:install.source_file(root,'file',1024)
        except ValueError:pass
        else:raise AssertionError('multiply linked input accepted')
        marker=root/'storage_thermal_recovery_required.json';anchor=Path(str(marker)+'.scope');anchor.write_bytes(install.HEADER)
        for v in ({'state':'CLEAN','cleanup_confirmed':True},dict(contract_id='lvs.storage_thermal.execution_intent',version=1,state='ARMED',cleanup_confirmed=False,token='owned',owner_pid=123)):
            marker.write_text(json.dumps(v));before=marker.read_bytes()
            with patch.object(install,'trusted',side_effect=lambda p,**k:p):
                try:
                    with install.recovery_gate(root):raise AssertionError('unsafe recovery admitted')
                except ValueError:pass
            assert marker.read_bytes()==before and anchor.read_bytes()==install.HEADER


def run_thermal_install_readiness_checks():
    from Modules.lvs_storage_thermal_installation import runtime_status
    with patch('Modules.lvs_storage_thermal_runtime.rpc',side_effect=PermissionError('fixture denied')):
        assert runtime_status()['status']=='PERMISSION_DENIED'
    with patch('Modules.lvs_storage_thermal_runtime.rpc',return_value=dict(source={'digest':'foreign'})):
        assert runtime_status()['status']=='INCOMPATIBLE'
    with patch('Modules.lvs_storage_thermal_runtime.rpc',side_effect=OSError('missing')):
        assert runtime_status()['ready']is False

    from Modules.lvs_storage_thermal_installation import prepare_runtime
    source=dict(status='complete',digest='a'*64)
    for mutation in ('fio','source'):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);tool=root/'approved-fio';tool.write_bytes(b'approved regular-file fixture')
            (root/'scripts').mkdir();(root/'scripts/storage_thermal_install.py').write_text('fixture installer')
            def substituted(destination,fio,root):
                (destination/'runtime/build').mkdir(parents=True)
                data=b'changed tool'if mutation=='fio'else tool.read_bytes()
                (destination/'runtime/build/fio').write_bytes(data)
                m=dict(source=dict(source,digest='b'*64)if mutation=='source'else source,uid=os.getuid(),gid=os.getgid(),files={'runtime/build/fio':install.digest(data)})
                (destination/'manifest.json').write_text(json.dumps(m));(destination/'SHA256SUMS').write_text('self-consistent fixture only')
            with patch('Modules.lvs_storage_thermal_installation._source_snapshot',return_value=(source,{})),patch('Modules.lvs_storage_thermal_installation.collect_source_provenance',return_value={'git':{'commit':'c'*40}}),patch('scripts.storage_thermal_prepare.prepare',side_effect=substituted):
                try:prepare_runtime(tool,install.digest(tool.read_bytes()),source['digest'],root=root)
                except ValueError as exc:assert 'independent approvals'in str(exc)
                else:raise AssertionError('builder substitution entered administrator handoff')


def run_thermal_install_maintenance_checks():
    import base64
    from Modules import lvs_storage_thermal_service as service
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);record=root/f'installation-{os.getuid()}.json';deployment=root/'runtime';policy=service.RuntimePolicy(deployment,dict(uid=os.getuid(),gid=os.getgid()),'a'*32,os.getpid())
        with patch.object(service,'STATE',root),patch.object(service,'owned_path',side_effect=lambda p,**k:p):
            assert policy.installation_reason()==''
            record.write_text(json.dumps(dict(phase='active',deployment=str(deployment))));assert policy.installation_reason()==''
            record.write_text(json.dumps(dict(phase='promoting',deployment=str(deployment))));assert policy.installation_reason()
            try:policy.request({},[])
            except ValueError as exc:assert 'installation'in str(exc)
            else:raise AssertionError('pending deployment accepted a stage')
            unit=install.Installer().unit(deployment)
            record.write_text(json.dumps(dict(phase='rolled_back',previous_unit=base64.b64encode(unit).decode())));assert policy.installation_reason()==''
            record.write_text(json.dumps(dict(phase='active',deployment='foreign')));assert policy.installation_reason()
        # A same-source response from a different runtime cannot pass promotion.
        obj=install.Installer();m=dict(source={'digest':'source'},worker_uid=65533,worker_gid=65533,uid=os.getuid(),gid=os.getgid(),files={'runtime/build/storage_thermal_launch.so':'launch','runtime/build/storage_thermal_guard':'guard','runtime/build/fio':'fio'})
        wrong=dict(status='AVAILABLE',source=m['source'],root='foreign',worker_uid=65533,worker_gid=65533,bootstrap_sha256='launch',guard_sha256='guard',fio_sha256='fio')
        with patch.object(install.subprocess,'check_output',return_value=json.dumps(wrong).encode()):
            try:obj.health(deployment,m)
            except ValueError:pass
            else:raise AssertionError('wrong deployment health accepted')
    import lvs_environment_manager as environment
    with tempfile.TemporaryDirectory()as name:
        manager=environment.EnvironmentManager(root=name,output=lambda *a:None)
        value=dict(status='PREPARED',bundle='/fixture bundle',manifest_sha256='a'*64,installer='/fixture installer',installer_sha256='b'*64)
        with patch.object(manager,'require_environment'),patch.object(manager,'checked',return_value=SimpleNamespace(stdout=json.dumps(value)))as checked:
            assert manager.thermal_operation(True,None,None,'c'*64)['status']=='PREPARED'
            args=checked.call_args.args[0]
            assert args[0]==manager.python and args[1:3]==['-I','-B']
            assert manager._lock_fd is None
    controller=install.Systemd()
    with patch.object(controller,'run',return_value=SimpleNamespace(returncode=0,stdout='/system.slice/fixture.service')),patch.object(controller,'active',return_value=False),patch.object(Path,'is_file',return_value=False):
        assert not controller.quiescent('fixture.service'),'unknown cgroup hierarchy certified cleanup'
    # Dedicated identity must not be an existing general-purpose login.
    account=SimpleNamespace(pw_name='lvs-thermal-worker',pw_uid=999,pw_gid=999,pw_dir='/home/user',pw_shell='/bin/bash')
    with patch.object(install.pwd,'getpwnam',return_value=account):
        try:install.worker_account()
        except ValueError:pass
        else:raise AssertionError('login account accepted as worker')
