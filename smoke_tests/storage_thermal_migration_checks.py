"""Nonphysical retirement transactions and fail-closed startup gates."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import socket
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from Modules import lvs_storage_thermal_migration as m
_REAL_ENDPOINT_INFO=m.endpoint_info


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);state=root/'state';units=root/'units';sockets=root/'sockets';startup=root/'startup';tree=root/('runtime-'+str(os.getuid())+'-'+('a'*24))
        for p in (state,units,sockets,startup,tree):p.mkdir()
        uid=os.getuid();unit=f'lvs-thermal-{uid}.service';record=state/f'installation-{uid}.json'
        original=dict(version=1,phase='active',input_manifest='a'*64,deployment=str(tree))
        record.write_text(json.dumps(original));(units/unit).write_bytes(m.unit_bytes(tree));(state/'install.lock').touch();(startup/'startup.lock').touch()
        marker=state/'storage_thermal_recovery_required.json';marker.write_text(json.dumps(dict(contract_id='lvs.storage_thermal.execution_intent',version=1,state='CLEAN',cleanup_confirmed=True,owner_pid=123,token='fixture',lease_identity=[1,2])))
        Path(str(marker)+'.scope').write_bytes(m.HEADER)
        model=dict(enabled='enabled',active=True);calls=[]
        def props(_):
            return dict(LoadState='loaded',ActiveState='active'if model['active']else'inactive',SubState='running'if model['active']else'dead',MainPID='123'if model['active']else'0',ControlGroup='',FragmentPath=str(units/unit),DropInPaths='',UnitFileState='masked'if m.masked(unit)else model['enabled'],Transient='no',NeedDaemonReload='no',Triggers='',TriggeredBy='')
        def ctl(*args):
            calls.append(args)
            if args[0]=='disable':model['enabled']='disabled'
            if args[0]=='stop':model['active']=False
            return ''
        patches=[patch.object(m,'masked',side_effect=lambda u:(units/u).is_symlink()and os.readlink(units/u)=='/dev/null'),patch.object(m,'STATE',state),patch.object(m,'UNITS',units),patch.object(m,'SOCKETS',sockets),patch.object(m,'STARTUP',startup),patch.object(m,'trusted',side_effect=lambda p,**k:Path(p)),patch.object(m,'require_native'),patch.object(m,'endpoint_info',return_value=None),patch.object(m,'no_transient'),patch.object(m,'no_other_legacy'),patch.object(m,'no_alternate_unit'),patch.object(m,'properties',side_effect=props),patch.object(m,'ctl',side_effect=ctl),patch.object(m,'quiescent',side_effect=lambda *a,**k:dict(pid=123,start_ticks=1)if model['active']else None),patch.object(m,'deployment',return_value=(dict(gid=os.getgid(),worker_uid=999,worker_gid=999,source={'digest':'approved'}),'b'*64))]
        for p in patches:p.start()
        try:yield SimpleNamespace(root=root,state=state,units=units,record=record,marker=marker,tree=tree,unit=unit,uid=uid,original=original,calls=calls,model=model)
        finally:
            for p in reversed(patches):p.stop()


def denied(call):
    try:call()
    except (ValueError,OSError):return
    raise AssertionError('unsafe migration accepted')


def run_thermal_retirement_transaction_checks():
    with fixture()as f:
        obj=m.Migration(f.uid);before=f.marker.read_bytes();initial=obj.inspect();approval=initial['approval_sha256']
        assert not f.calls and json.loads(f.record.read_text())==f.original
        assert obj.retire(approval)['status']=='RETIRED'
        assert obj.retire(approval)['status']=='RETIRED'
        v=m.retired_record(f.uid);assert v['uid']==f.uid and f.marker.read_bytes()==before
        assert f.tree.is_dir()and m.masked(f.unit)
        assert not any(c[0]in ('start','restart','enable')for c in f.calls)
        # Old installer rollback expects previous_unit; tombstones deliberately
        # have no replayable old installer fields, and install rejects phase.
        r=json.loads(f.record.read_text());assert r['phase']=='retired'and 'previous_unit'not in r and 'deployment'not in r
        assert obj.rollback(approval)['status']=='ROLLED_BACK'
        assert json.loads(f.record.read_text())==f.original and not f.model['active']
        assert f.model['enabled']=='disabled'and not m.masked(f.unit)
        assert f.marker.read_bytes()==before
        assert obj.rollback(approval)['status']=='ROLLED_BACK'


def run_thermal_retirement_interruption_checks():
    for phase in ('PREPARED','MASKED','STOPPED','SOCKET_RECONCILED','RETIRED'):
        for operation in ('resume','rollback'):
            with fixture()as f:
                obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256'];before=f.marker.read_bytes()
                def fail(p):
                    if p==phase:raise OSError(5,'injected phase interruption')
                obj.checkpoint=fail;denied(lambda:obj.retire(approval));obj.checkpoint=lambda _:None
                if operation=='resume':assert obj.retire(approval)['status']=='RETIRED'
                else:assert obj.rollback(approval)['status']=='ROLLED_BACK'
                assert f.marker.read_bytes()==before and f.tree.exists()
                assert not any(c[0]in ('start','restart','enable')for c in f.calls)


def run_thermal_retirement_recovery_checks():
    import fcntl
    for invalid in ('missing','corrupt','ARMED','missing-anchor','locked'):
        with fixture()as f:
            obj=m.Migration(f.uid);fd=None
            if invalid=='missing':f.marker.unlink()
            if invalid=='corrupt':f.marker.write_text('{}')
            if invalid=='ARMED':v=json.loads(f.marker.read_text());v.update(state='ARMED',cleanup_confirmed=False);f.marker.write_text(json.dumps(v))
            anchor=Path(str(f.marker)+'.scope')
            if invalid=='missing-anchor':anchor.unlink()
            if invalid=='locked':fd=os.open(anchor,os.O_RDONLY);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:
                denied(obj.inspect);denied(lambda:obj.retire('a'*64));assert not f.calls
            finally:
                if fd is not None:os.close(fd)
    with fixture()as f:
        obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256'];obj.retire(approval)
        v=json.loads(f.marker.read_text());v.update(state='ARMED',cleanup_confirmed=False);f.marker.write_text(json.dumps(v))
        count=len(f.calls);denied(lambda:obj.rollback(approval));assert len(f.calls)==count and m.masked(f.unit)


def run_thermal_retirement_approval_checks():
    for field in ('unit','record','journal','transaction','generation','override','competing','worker'):
        with fixture()as f:
            obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256']
            if field=='unit':(f.units/f.unit).write_bytes(b'changed unit')
            if field=='record':f.record.write_text('{}')
            if field=='journal':v=json.loads(f.marker.read_text());v['token']='changed';f.marker.write_text(json.dumps(v))
            if field=='transaction':
                obj.retire(approval);d=obj._pending(approval);(d/'original-unit').write_bytes(b'changed archive')
            if field=='generation':
                obj.checkpoint=lambda phase:(_ for _ in ()).throw(OSError('interrupted'))if phase=='PREPARED'else None
                denied(lambda:obj.retire(approval));obj.checkpoint=lambda _:None
                m.quiescent.side_effect=lambda *a,**k:dict(pid=124,start_ticks=2)
            if field=='override':old=m.properties.side_effect;m.properties.side_effect=lambda u:dict(old(u),DropInPaths='unsafe')
            if field=='competing':m.no_transient.side_effect=ValueError('active transient')
            if field=='worker':m.quiescent.side_effect=ValueError('worker escaped')
            n=len(f.calls);denied(lambda:obj.retire(approval));assert len(f.calls)==n
            if field=='transaction':denied(lambda:m.retired_record(f.uid))


def run_thermal_retirement_socket_checks():
    with fixture()as f:
        path=m.SOCKETS/(str(f.uid)+'.sock');s=socket.socket(socket.AF_UNIX);s.bind(str(path));s.listen(1);path.chmod(0o660)
        actual_lstat=Path.lstat
        def root_socket(p,*a,**k):
            v=actual_lstat(p,*a,**k)
            if p==path:return SimpleNamespace(st_mode=v.st_mode,st_uid=0,st_gid=os.getgid(),st_dev=v.st_dev,st_ino=v.st_ino)
            return v
        with patch.object(Path,'lstat',root_socket):
            _REAL_ENDPOINT_INFO(f.uid,os.getgid(),m.process_identity(os.getpid()))
            denied(lambda:_REAL_ENDPOINT_INFO(f.uid,os.getgid(),None))
            denied(lambda:_REAL_ENDPOINT_INFO(f.uid,os.getgid(),dict(pid=os.getpid(),start_ticks=-1)))
            s.close();assert _REAL_ENDPOINT_INFO(f.uid,os.getgid(),None)

    with fixture()as f:
        path=m.SOCKETS/(str(f.uid)+'.sock');s=socket.socket(socket.AF_UNIX);s.bind(str(path));s.close();path.chmod(0o660)
        # Root ownership is fixture-only substituted; actual VM exercises it.
        def info(*a):
            st=path.lstat()if path.exists()else None
            return dict(device=st.st_dev,inode=st.st_ino,gid=os.getgid(),mode=0o660,main=None)if st else None
        with patch.object(m,'endpoint_info',side_effect=info):
            obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256'];obj.retire(approval)
            assert not path.exists()
    with fixture()as f:
        obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256']
        def changed(p):
            if p=='STOPPED':
                q=socket.socket(socket.AF_UNIX);q.bind(str(m.SOCKETS/(str(f.uid)+'.sock')));q.close()
        obj.checkpoint=changed;denied(lambda:obj.retire(approval));assert json.loads(f.record.read_text())['phase']=='retiring'


def run_thermal_retirement_shared_gate_checks():
    from Modules import lvs_storage_thermal_service as service
    from Modules import lvs_storage_thermal_transient as transient
    import inspect
    text=inspect.getsource(transient.bootstrap)
    assert text.index("STATE/'install.lock'")<text.index("BASE/'startup.lock'")<text.index('gate=canonical_gate()')
    with fixture()as f,patch.object(service,'STATE',f.state),patch.object(service,'owned_path',side_effect=lambda p,**k:p):
        obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256'];obj.retire(approval)
        policy=service.RuntimePolicy(f.root,dict(uid=f.uid,gid=os.getgid(),runtime_mode=transient.MODE),'a'*32,os.getpid())
        assert policy.installation_reason()==''
        policy.manifest.pop('runtime_mode');assert policy.installation_reason()
        transaction=obj._pending(approval);v=json.loads((transaction/'state.json').read_text());v['phase']='SOCKET_RECONCILED';(transaction/'state.json').write_text(json.dumps(v))
        denied(lambda:m.retired_record(f.uid))


def run_thermal_retirement_persistence_checks():
    for phase in ('audit','retiring','MASKED','STOPPED','SOCKET_RECONCILED','retired','RETIRED'):
        with fixture()as f:
            obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256'];before=f.marker.read_bytes();original=m.atomic;fired=[]
            def fail(path,data):
                value=json.loads(data)if path.suffix=='.json'else {}
                selected=(path.name=='approval.json')if phase=='audit'else value.get('phase')==phase
                if selected and not fired:fired.append(True);raise OSError(28 if phase in ('audit','retiring')else 5,'injected persistence failure')
                return original(path,data)
            with patch.object(m,'atomic',side_effect=fail):denied(lambda:obj.retire(approval))
            assert fired and f.marker.read_bytes()==before
            assert obj.retire(approval)['status']=='RETIRED'
            assert f.marker.read_bytes()==before
    with fixture()as f:
        # Inspection never creates an absent startup lock or repairs recovery.
        startup=m.STARTUP/'startup.lock';startup.unlink()
        obj=m.Migration(f.uid);obj.inspect();assert not startup.exists()
        f.marker.unlink();denied(obj.inspect);assert not startup.exists()


def run_thermal_retirement_lock_checks():
    import fcntl
    for name in ('install','startup'):
        with fixture()as f:
            path=(f.state/'install.lock')if name=='install'else m.STARTUP/'startup.lock'
            fd=os.open(path,os.O_RDONLY);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:denied(m.Migration(f.uid).inspect);assert not f.calls
            finally:os.close(fd)
    with fixture()as f:
        obj=m.Migration(f.uid);approval=obj.inspect()['approval_sha256'];obj.retire(approval)
        # Replacing the permanent scope inode is not a legitimate update.
        anchor=Path(str(f.marker)+'.scope');anchor.rename(anchor.with_suffix('.old'));anchor.write_bytes(m.HEADER)
        denied(lambda:m.retired_record(f.uid));denied(lambda:obj.rollback(approval))


def run_thermal_retirement_other_service_checks():
    with patch.object(m,'ctl',return_value='lvs-thermal-demand-1000.service loaded failed failed old'),patch.object(m,'properties',return_value=dict(MainPID='17',ControlGroup='')):
        denied(m.no_transient)
    with patch.object(m,'ctl',return_value='lvs-thermal-demand-1000.service loaded inactive dead old'),patch.object(m,'properties',return_value=dict(MainPID='0',ControlGroup='')):
        m.no_transient()
    with patch.object(m,'ctl',return_value='lvs-thermal-2000.service loaded active running legacy'):
        denied(lambda:m.no_other_legacy('lvs-thermal-1000.service'))
    with patch.object(m,'ctl',return_value='lvs-thermal-2000.service loaded inactive dead legacy'):
        m.no_other_legacy('lvs-thermal-1000.service')


@contextmanager
def historical_fixture():
    with fixture()as f:
        f.record.unlink();(f.units/f.unit).unlink();old=f.root/m.EA60;old.mkdir();fragment=f.root/'transient';fragment.mkdir();(fragment/f.unit).write_bytes(m.historical_unit())
        def props(_):
            mask=m.masked(f.unit)
            return dict(LoadState='masked'if mask and not f.model['active']else'loaded'if f.model['active']else'not-found',ActiveState='active'if f.model['active']else'inactive',SubState='running'if f.model['active']else'dead',MainPID='123'if f.model['active']else'0',ControlGroup='',FragmentPath=str(fragment/f.unit)if f.model['active']else str(f.units/f.unit)if mask else'',DropInPaths='',UnitFileState='masked'if mask else'transient'if f.model['active']else'',Transient='yes'if f.model['active']else'no',NeedDaemonReload='no',Triggers='',TriggeredBy='')
        def ctl(*args):
            f.calls.append(args)
            if args[0]=='stop':f.model['active']=False;(fragment/f.unit).unlink(missing_ok=True)
            return ''
        patches=[patch.object(m,'TRANSIENT_UNITS',fragment),patch.object(m,'canonical',return_value=f.root),patch.object(m,'historical_deployment',return_value=(dict(uid=f.uid,gid=os.getgid(),source={'digest':m.EA60_SOURCE}),'b'*64)),patch.object(m,'properties',side_effect=props),patch.object(m,'ctl',side_effect=ctl)]
        for p in patches:p.start()
        try:yield f
        finally:
            for p in reversed(patches):p.stop()


def run_thermal_historical_transaction_checks():
    for phase in ('PREPARED','MASKED','STOPPED','SOCKET_RECONCILED','RETIRED'):
        for operation in ('resume','rollback'):
            with historical_fixture()as f:
                obj=m.Migration(f.uid,historical_ea60=True);approval=obj.inspect()['approval_sha256'];before=f.marker.read_bytes()
                assert not f.record.exists()
                def crash(p):
                    if p==phase:raise OSError('historical interruption')
                obj.checkpoint=crash;denied(lambda:obj.retire(approval));obj.checkpoint=lambda _:None
                if operation=='resume':
                    obj.retire(approval);v=m.retired_record(f.uid);assert v['worker_uid']is None and v['record_absent'];obj.retire(approval)
                else:
                    obj.rollback(approval);obj.rollback(approval);assert not f.record.exists()and not(f.units/f.unit).exists()
                assert f.marker.read_bytes()==before
                assert not any(c[0]in ('start','enable','restart')for c in f.calls)
                d=obj._pending(approval);assert (d/'original-record.json').read_bytes()==m.ABSENT_RECORD
                assert (d/'original-unit').read_bytes()==m.historical_unit()
    with historical_fixture()as f:
        obj=m.Migration(f.uid,historical_ea60=True);approval=obj.inspect()['approval_sha256'];obj.retire(approval)
        denied(lambda:m.Migration(f.uid).rollback(approval))
        f.marker.write_text('{}');denied(lambda:obj.rollback(approval))
        assert m.masked(f.unit)


def run_thermal_historical_format_checks():
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);tree=root/m.EA60;tree.mkdir()
        paths=[f'runtime/Modules/source_{n}.py'for n in range(392)]+['launch.py','runtime/build/fio','runtime/build/storage_thermal_guard','runtime/build/storage_thermal_launch.so','runtime/scripts/storage_thermal_acceptance.py']
        for n in paths:
            p=tree/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic historical fixture')
        manifest=dict(contract='lvs.storage_thermal.offline_bundle.v1',source=dict(scope='lvs_execution_source_v1',algorithm='sha256',file_count=392,digest=m.EA60_SOURCE,status='complete',error_count=0),uid=os.getuid(),gid=os.getgid(),files={p:m.sha((tree/p).read_bytes())for p in paths},backend={'fio_version':'fio-3.42'})
        raw=json.dumps(manifest).encode();(tree/'manifest.json').write_bytes(raw);sums=''.join(h+'  '+n+'\n'for n,h in sorted(dict(manifest['files'],**{'manifest.json':m.sha(raw)}).items())).encode();(tree/'SHA256SUMS').write_bytes(sums)
        with patch.object(m,'trusted',side_effect=lambda p,**k:Path(p)),patch.object(m,'canonical',return_value=root),patch.object(m,'EA60_MANIFEST',m.sha(raw)),patch.object(m,'EA60_SUMS',m.sha(sums)),patch.object(m.pwd,'getpwnam',side_effect=AssertionError('must not infer dedicated identity')):
            assert m.historical_deployment(tree,os.getuid())[0]['uid']==os.getuid()
            (tree/'runtime/build/fio').write_bytes(b'substituted executable');denied(lambda:m.historical_deployment(tree,os.getuid()));(tree/'runtime/build/fio').write_bytes(b'synthetic historical fixture')
            (tree/'extra').write_bytes(b'extra');denied(lambda:m.historical_deployment(tree,os.getuid()));(tree/'extra').unlink()
            manifest['worker_uid']=999;raw2=json.dumps(manifest).encode();(tree/'manifest.json').write_bytes(raw2)
            denied(lambda:m.historical_deployment(tree,os.getuid()))
            with patch.object(m,'EA60_MANIFEST',m.sha(raw2)):denied(lambda:m.historical_deployment(tree,os.getuid()))


def run_thermal_historical_lock_checks():
    import fcntl
    with historical_fixture()as f:
        lock=f.state/'install.lock';lock.unlink();obj=m.Migration(f.uid,historical_ea60=True)
        approval=obj.inspect()['approval_sha256'];assert not lock.exists()
        obj.retire(approval);assert lock.is_file()
        # Creating serialization never creates/replaces a journal or anchor.
        inode=Path(str(f.marker)+'.scope').stat().st_ino
        obj.rollback(approval);assert Path(str(f.marker)+'.scope').stat().st_ino==inode
    with historical_fixture()as f:
        (f.state/'install.lock').unlink();f.marker.unlink();denied(m.Migration(f.uid,historical_ea60=True).inspect)
        assert not(f.state/'install.lock').exists()


def run_thermal_historical_mapping_checks():
    with tempfile.TemporaryDirectory()as name:
        root=Path(name);tool=root/'file';tool.write_bytes(b'\0'*4096)
        observed=m.mapping_identity(tool);assert observed[1]==tool.stat().st_ino
        fifo=root/'fifo';os.mkfifo(fifo);denied(lambda:m.mapping_identity(fifo))
        actual=Path.read_bytes
        # Model the actual Btrfs stat/proc-device disagreement. The returned
        # token must come from the observed read-only mapping, not stat().
        for row,valid in ((b'1000-2000 r--p 00000000 00:26 4242 /opaque\n',True),(b'1000-2000 rw-p 00000000 00:26 4242 /opaque\n',False),(b'1000-3000 r--p 00000000 00:26 4242 /opaque\n',False)):
            samples=[b'',row]
            def read(p):return samples.pop(0)if str(p)=='/proc/self/maps'else actual(p)
            with patch.object(Path,'read_bytes',read):
                if valid:assert m.mapping_identity(tool)==(os.makedev(0,0x26),4242)
                else:denied(lambda:m.mapping_identity(tool))
