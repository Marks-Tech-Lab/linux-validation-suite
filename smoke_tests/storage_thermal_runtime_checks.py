"""Installed boundary regressions: private files/pipes, no privileged host execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import time
from unittest.mock import patch

from Modules import lvs_storage_thermal_runtime as rt
from Modules import lvs_storage_thermal_service as service
from Modules.lvs_storage_thermal import ThermalConfig
from Modules.lvs_storage_thermal_stage import SharedAdmission,preview


def reject(call):
    try:call()
    except (ValueError,OSError,EOFError,KeyError):return
    raise AssertionError('untrusted boundary input accepted')


def run_installed_runtime_schema_checks():
    valid=ThermalConfig().to_dict()
    assert rt.configuration(valid).to_dict()==valid
    for key,value in [('intensity_percent',True),('duration_seconds',True),('contract_version',True),('monitoring','approved_unmonitored'),('queue_depth',2),('scheduling','realtime')]:
        payload=dict(valid,**{key:value});reject(lambda:rt.configuration(payload))
    reject(lambda:rt.configuration(dict(valid,executable='/untrusted')))
    missing=dict(valid);missing.pop('block_size');reject(lambda:rt.configuration(missing))
    for value in ['../escape','0'*31,True,None,'z'*32]:reject(lambda:rt.token(value))
    assert rt.token('a'*32)=='a'*32
    a,b=socket.socketpair()
    try:
        a.sendall(struct.pack('!I',rt.MAX_PACKET+1));reject(lambda:rt.receive(b))
        a.sendall(struct.pack('!I',2)+b'[]');reject(lambda:rt.receive(b))
        rt.send(a,dict(value=1));assert rt.receive(b)==dict(value=1)
    finally:a.close();b.close()


def run_installed_runtime_authority_checks():
    # Ordinary writable source/tool paths never confer privileged runtime trust.
    with tempfile.TemporaryDirectory() as name:
        root=Path(name);(root/'file').write_text('fixture');reject(lambda:rt.owned_path(root/'file'))
        (root/'link').symlink_to('/usr/bin/true');reject(lambda:rt.owned_path(root/'link'))
        with patch.object(rt,'SOCKET_ROOT',root):reject(lambda:rt.connect())
    from smoke_tests.storage_thermal_stage_checks import stage
    s=stage();s.modules.storage_thermal.enabled=False
    with patch.object(rt,'preview',side_effect=AssertionError('disabled stage contacted privileged service')):assert preview(s) is None
    s.modules.storage_thermal.enabled=True
    with patch.object(rt,'inspect',side_effect=PermissionError('authorization absent')):
        result=preview(s);assert result['status']=='BLOCKED' and not result['runnable_devices']
        assert any('authorization absent' in text for text in result['backend']['reasons'])
    # A newer ordinary execution copy must neither rebuild nor replace the
    # independently verified installed bootstrap. Exercise a fresh interpreter.
    import subprocess,shutil
    from Modules.lvs_storage_thermal_launch import prepare,provenance
    prepare()
    binary=Path(provenance()['binary'].get('path','build/storage_thermal_launch.so'))
    if not binary.exists():binary=Path('build/storage_thermal_launch.so')
    with tempfile.TemporaryDirectory() as name:
        target=Path(name)/'storage_thermal_launch.so';shutil.copyfile(binary,target)
        os.utime(target,ns=(1,1))
        command="from Modules.lvs_storage_thermal_launch import prepare;from unittest.mock import patch;from pathlib import Path;import sys\nwith patch('Modules.lvs_native_helpers.find_c_compiler',side_effect=AssertionError('installed runtime must not build')):prepare(Path(sys.argv[1]),allow_build=False)"
        subprocess.run([__import__('sys').executable,'-B','-c',command,name],check=True,capture_output=True,timeout=10)
        assert target.stat().st_mtime_ns==1


def run_installed_runtime_descriptor_checks():
    # Host retirement records must not influence this private-descriptor fixture
    # or cause it to inspect the workstation's protected installation/recovery.
    with tempfile.TemporaryDirectory() as name,patch.object(service,'STATE',Path(name)),patch.object(rt,'STATE',Path(name)):
        _installed_runtime_descriptor_checks()


def _installed_runtime_descriptor_checks():
    lease=SharedAdmission.create();read_fd,write_fd=os.pipe()
    try:
        generation='a'*32;session='b'*32;deadline=time.monotonic()+5
        policy=service.RuntimePolicy('/unused',dict(uid=os.getuid(),gid=os.getgid(),source={'fixture':True}),generation,os.getpid())
        context=dict(version=1,run_directory='/primary',session_id=session,run_id='c'*32,stage_id='stage',started_ns=int((deadline-5)*1e9),deadline_ns=int(deadline*1e9),lease_identity=list(lease.identity))
        request=dict(plan=dict(configuration=ThermalConfig(duration_seconds=5).to_dict(),installed_runtime=dict(generation=generation,source={'fixture':True})),
            execution_context=context,directory='/etc/untrusted',recovery_marker='/etc/untrusted',supervisor_parent_pid=os.getppid(),
            stage_deadline=deadline,stage_lease_id=session,admission_fd=lease.fd,admission_identity=list(lease.identity))
        result=policy.request(request,[read_fd,write_fd,lease.fd])
        assert result['directory']==str(rt.STATE/'integrated'/str(os.getuid())/session)
        assert result['recovery_marker']==str(rt.STATE/'storage_thermal_recovery_required.json')
        assert lease.verified_identity()==list(lease.identity)  # validation never closes caller authority
        for mutate in [lambda x:x.update(stage_lease_id='../escape'),lambda x:x.update(stage_deadline=True),
                       lambda x:x.update(supervisor_parent_pid=0),lambda x:x.update(admission_identity=[1,2]),
                       lambda x:x['execution_context'].update(deadline_ns=True),
                       lambda x:x['plan']['installed_runtime'].update(generation='d'*32)]:
            bad=deepcopy(request);mutate(bad);reject(lambda:policy.request(bad,[read_fd,write_fd,lease.fd]))
        reject(lambda:policy.request(request,[write_fd,read_fd,lease.fd]))
        with tempfile.TemporaryDirectory() as name,patch.object(service,'STATE',Path(name)):
            directory=policy.directory(session);directory.mkdir(parents=True)
            witness=directory/'completion.json';witness.write_text('prior evidence')
            reject(lambda:policy.request(request,[read_fd,write_fd,lease.fd]))
            assert witness.read_text()=='prior evidence'
    finally:lease.close();os.close(read_fd);os.close(write_fd)


def run_installed_runtime_final_observation_checks():
    """Closed admission still permits metadata reconciliation after confirmed exit."""
    from smoke_tests.storage_thermal_runner_checks import RunnerFixture
    with tempfile.TemporaryDirectory() as name:
        f=RunnerFixture(name);original=f.targets.revalidate;temperature=f.runner.temperature;seen=[]
        def live(row):
            if f.clock()>.2:raise ValueError('lease closed; no new admission')
            return original(row)
        f.targets.revalidate=live
        def final(row):
            assert f.children and all(p.returncode is not None for p in f.children.values())
            seen.append('identity');return original(row)
        def final_temperature(row):
            assert f.children and all(p.returncode is not None for p in f.children.values())
            seen.append('temperature');return temperature(row)
        f.runner.final_revalidator=final;f.runner.final_temperature=final_temperature
        _,result=f.run(ThermalConfig(duration_seconds=3),control=lambda jobs:['all'] if jobs and f.clock()>.3 else [])
        d=result['devices'][0]
        assert seen==['identity','temperature']
        assert d['state']=='cancelled' and d['errors']==0 and d['identity_unchanged'] and d['provenance_confirmed']
        assert d['temperature_status']=='monitored' and d['cleanup_confirmed']
        reject(lambda:f.targets.revalidate(f.rows[0]))  # admission checks remain closed

    # Revocation racing a live observation is an orderly stop, never a reason
    # to skip actual fio/guard/exit evidence collection.
    from Modules.lvs_storage_thermal import ThermalAdmissionEnded
    with tempfile.TemporaryDirectory() as name:
        f=RunnerFixture(name);original=f.runner.temperature;seen=[]
        def live_temperature(row):
            if f.children and f.clock()>1:raise ThermalAdmissionEnded('revoked during monitor')
            return original(row)
        f.runner.temperature=live_temperature
        f.runner.final_temperature=lambda row:(seen.append('final') or original(row))
        _,result=f.run(ThermalConfig(duration_seconds=3))
        d=result['devices'][0]
        assert seen==['final'] and d['state']=='cancelled',result
        assert d['exit_code']==-15 and d['errors']==0 and d['cleanup_confirmed'],result
        assert d['guard_confirmed'] and d['read_ios']>0,result
